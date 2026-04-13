#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DIVI孤儿订单检测与修复脚本 (v1.0)
功能：每日自动扫描近7天标记为"已导出DIVI"但实际在DIVI中丢失的订单，自动重置状态
执行方式：python detect_and_fix_orphaned_divi_orders.py
建议：加入crontab，每天凌晨执行一次
"""

import os
import sys
import django
from datetime import datetime, timedelta
from django.db.models import Q

# ========== Django环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

from amazon.models import AmazonOrders, LingXingAmazonShop
from api.divi.divi_order_service import query_divi_order, get_divi_brand_id_from_sid
from api.Y.y_tiem import Timer

# ========== 核心配置 ==========
DAYS_BACK = 7  # 扫描近7天的订单
DRY_RUN = False  # 设为True则只检测不修复（测试模式）

# 注意：本脚本被 sync_a_doing.py 7×24小时循环调用，不能使用缓存
# 所有数据必须实时从数据库获取，确保数据一致性


def get_brand_id(sid):
    """获取 SID 对应的 BrandID（实时查询，无缓存）"""
    return get_divi_brand_id_from_sid(sid)


def extract_orphaned_orders_candidates(start_datetime):
    """
    提取需要检测的候选订单：已标记导出 + 店铺状态正常 + 近7天
    返回：按brand_id分组的订单字典
    """
    print(f"\n🔍 正在提取候选订单（近7天、已标记导出、店铺正常）...")

    # 1. 查询所有符合条件的订单
    candidate_orders = AmazonOrders.objects.filter(
        fulfillment_channel='MFN',
        purchase_date_local__gte=start_datetime,
        is_exported_to_divi=True,  # ⭐ 核心：只查已导出的
        amazon_shop__shop_status='status-active',
    ).exclude(
        order_status__in={'PendingAvailability', 'Pending', 'Canceled'}
    ).select_related(
        'lingxing_shop',
        'amazon_shop'
    ).order_by('lingxing_shop__sid', 'amazon_order_id')

    total_candidates = candidate_orders.count()
    print(f"📊 找到 {total_candidates} 条已标记导出的候选订单")

    # 2. 按 brand_id 分组
    brand_order_map = {}
    no_brand_id_orders = []  # 无法映射brand_id的订单

    for order in candidate_orders:
        if not order.lingxing_shop:
            no_brand_id_orders.append((order.amazon_order_id, "无领星店铺"))
            continue

        sid = order.lingxing_shop.sid
        brand_id = get_brand_id(sid)

        if not brand_id:
            no_brand_id_orders.append((order.amazon_order_id, f"sid={sid} 无对应divi品牌"))
            continue

        if brand_id not in brand_order_map:
            brand_order_map[brand_id] = []

        brand_order_map[brand_id].append(order)

    # 3. 打印无法分组的订单
    if no_brand_id_orders:
        print(f"\n⚠️  警告：{len(no_brand_id_orders)} 条订单无法映射brand_id，将跳过检测：")
        for order_id, reason in no_brand_id_orders[:10]:  # 只打印前10条
            print(f"   - {order_id}: {reason}")
        if len(no_brand_id_orders) > 10:
            print(f"   ... 还有 {len(no_brand_id_orders) - 10} 条未显示")

    # 4. 打印分组统计
    print(f"\n📦 按品牌分组统计：")
    for brand_id, orders in brand_order_map.items():
        print(f"   - brand_id={brand_id}: {len(orders)} 条订单")

    return brand_order_map, total_candidates


def detect_and_fix_orphaned_orders(brand_order_map, start_datetime):
    """
    核心检测与修复逻辑
    对每个brand_id批量查询DIVI，找出本地有但DIVI无的孤儿订单
    """
    print(f"\n{'=' * 80}")
    print(f"开始批量检测与修复...")
    print(f"{'=' * 80}")

    total_checked = 0
    total_orphaned = 0
    total_fixed = 0
    total_failed = 0
    orphaned_details = []  # 记录所有孤儿订单详情

    for brand_id, local_orders in brand_order_map.items():
        print(f"\n>>> 处理品牌 brand_id={brand_id} (共 {len(local_orders)} 条订单)")

        try:
            # 1. 批量查询DIVI该品牌下所有订单（一次网络请求）
            exists, divi_orders, _ = query_divi_order(
                amazon_order_id=None,  # 空值代表全量拉取
                brand_id=brand_id,
                has_logistics=False
            )

            if not exists or not divi_orders:
                print(f"   ⚠️  DIVI返回空数据，该品牌下所有订单可能都已丢失")
                divi_order_ids = set()
            else:
                # 2. 构建DIVI订单ID集合
                divi_order_ids = {
                    str(d.get("amazonOrderId")).strip()
                    for d in divi_orders
                    if d.get("amazonOrderId")
                }
                print(f"   📦 DIVI返回 {len(divi_order_ids)} 条订单记录")

            # 3. 对比找出孤儿订单
            local_order_ids = {o.amazon_order_id for o in local_orders}
            orphaned_ids = local_order_ids - divi_order_ids  # 集合差：本地有但DIVI无

            if not orphaned_ids:
                print(f"   ✅ 该品牌无孤儿订单")
                total_checked += len(local_orders)
                continue

            print(f"   🚨 发现 {len(orphaned_ids)} 条孤儿订单：")
            for oid in list(orphaned_ids)[:5]:  # 打印前5条
                print(f"      - {oid}")
            if len(orphaned_ids) > 5:
                print(f"      ... 还有 {len(orphaned_ids) - 5} 条未显示")

            total_orphaned += len(orphaned_ids)
            total_checked += len(local_orders)

            # 4. 修复孤儿订单
            if DRY_RUN:
                print(f"   ⏭️  DRY_RUN模式，跳过修复")
                continue

            orphaned_orders = AmazonOrders.objects.filter(
                amazon_order_id__in=orphaned_ids,
                is_exported_to_divi=True
            )

            # 批量更新
            try:
                # 方案A：使用update()批量更新（无信号触发，性能高）
                updated_count = orphaned_orders.update(
                    is_exported_to_divi=False,
                    # divi_order_status=None,  # 可选：同时清空其他DIVI字段
                    # divi_import_time=None,
                    # ... 其他字段按需清空
                )
                total_fixed += updated_count
                print(f"   ✅ 成功重置 {updated_count} 条订单状态")

                # 记录详情
                for order in orphaned_orders:
                    orphaned_details.append({
                        'amazon_order_id': order.amazon_order_id,
                        'lingxing_shop_name': order.lingxing_shop.name if order.lingxing_shop else '未知',
                        'purchase_date_local': order.purchase_date_local.strftime('%Y-%m-%d %H:%M:%S'),
                        'reason': '在DIVI中不存在',
                        'fixed': True
                    })

            except Exception as e:
                print(f"   ❌ 批量更新失败: {e}")
                total_failed += len(orphaned_ids)

        except Exception as e:
            print(f"   🔥 brand_id={brand_id} 处理异常: {e}")
            total_failed += len(local_orders)
            continue

    return total_checked, total_orphaned, total_fixed, total_failed, orphaned_details


def amazon_order_divi_guer():
    """主入口"""
    t = Timer()
    t.start()

    # 计算时间范围：近7天
    end_date = datetime.now()
    start_date = end_date - timedelta(days=DAYS_BACK)
    start_datetime = datetime.combine(start_date, datetime.min.time())

    print(f"\n{'=' * 80}")
    print(f"DIVI孤儿订单检测与修复脚本启动")
    print(f"扫描时间范围: {start_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}")
    print(f"DRY_RUN模式: {'是（只检测不修复）' if DRY_RUN else '否（执行修复）'}")
    print(f"{'=' * 80}\n")

    try:
        # 步骤1：提取候选订单
        brand_order_map, total_candidates = extract_orphaned_orders_candidates(start_datetime)

        if total_candidates == 0:
            print("✅ 没有符合条件的候选订单，脚本结束")
            return

        # 步骤2：检测并修复
        total_checked, total_orphaned, total_fixed, total_failed, details = detect_and_fix_orphaned_orders(
            brand_order_map, start_datetime
        )

        # 步骤3：输出报告
        print(f"\n{'=' * 80}")
        print(f"检测完成！最终报告:")
        print(f"{'=' * 80}")
        print(f"候选订单总数: {total_candidates}")
        print(f"实际检测数  : {total_checked}")
        print(f"孤儿订单数  : {total_orphaned}")
        print(f"成功修复数  : {total_fixed}")
        print(f"修复失败数  : {total_failed}")
        print(f"{'=' * 80}")

        if DRY_RUN and total_orphaned > 0:
            print("\n⚠️  DRY_RUN模式：以下订单将被修复（实际未执行）：")
            for detail in details:
                print(f"   - {detail['amazon_order_id']} ({detail['lingxing_shop_name']})")

        if total_orphaned > 0 and not DRY_RUN:
            print("\n✅ 修复成功！建议稍后重新运行同步脚本补导这些订单。")
        elif total_orphaned == 0:
            print("\n✅ 未发现孤儿订单，数据一致性良好。")

    except Exception as e:
        print(f"\n{'=' * 80}")
        print(f"❌ 脚本执行异常: {str(e)}")
        import traceback
        traceback.print_exc()
        print(f"{'=' * 80}")
        sys.exit(1)

    finally:
        t.stop()
        print(f"\n⏱️  脚本运行时长: {t}")


if __name__ == '__main__':
    amazon_order_divi_guer()