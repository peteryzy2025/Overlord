#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
终极精准补导 + 字段同步脚本（v3.2 - 保留两阶段结构）

核心改进：
1. 补导阶段：完全保留原有逐单逻辑（使用SID）
2. 同步阶段：优化为一次性拉取 + 内存分组（使用divi_shop_id + shop_name）
3. 修复brand_id传参无效导致的重复拉取问题
4. 保持v2的两阶段清晰结构
"""

import os
import sys
import django
from datetime import datetime
from collections import defaultdict

from Api.Y.y_tiem import Timer

# ========== Django环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()
from General.models import AmazonShop
from Amazon.models import AmazonOrders
from Api.divi.divi_order_service import (
    query_divi_order,
    get_divi_brand_id_from_sid,
    import_order_from_lingxing_to_divi,
)
from Amazon.amazon_divi_views import update_divi_order_fields

# 要排除的亚马逊订单状态
EXCLUDE_AMAZON_STATUS = {'PendingAvailability', 'Pending', 'Canceled'}

# ============ 核心配置：直接修改此变量切换模式 ============
ENABLE_REIMPORT = True  # 修改这个值即可切换模式！
TARGET_DATE = "2025-11-19"
# ===========================================================

# ============ 缓存 ============
_BRAND_ID_CACHE = {}


def query_reimport_orders(start_datetime):
    """查询需要补导的订单：本地标记为未导出 + 店铺状态正常"""
    return (AmazonOrders.objects.filter(
        fulfillment_channel='MFN',
        purchase_date_local__gte=start_datetime,
        is_exported_to_divi=False,
        amazon_shop__shop_status='正常',
    ).exclude(
        divi_order_status__in={0, 5}
    ).exclude(
        order_status__in=EXCLUDE_AMAZON_STATUS
    ).select_related(
        'lingxing_shop',
        'amazon_shop'
    ).order_by('purchase_date_local'))


def reimport_orders(queryset, total):
    """执行补导操作（逐单模式，完全保留v2逻辑）"""
    if total == 0:
        print("【补导阶段】未发现漏单，跳过")
        return 0, 0

    print(f"\n【补导阶段】找到 {total} 条漏单，开始导入DIVI...\n")
    success = error = 0

    for i, order in enumerate(queryset, 1):
        order_id = order.amazon_order_id
        print(f"[补导 {i:>4}/{total}] {order_id}", end="  ")

        try:
            # 补导阶段仍使用SID路径（保留原有逻辑）
            sid = order.lingxing_shop.sid if order.lingxing_shop else None
            if not sid:
                print("× 无领星店铺")
                error += 1
                continue

            brand_id = get_divi_brand_id_from_sid(sid)
            if not brand_id:
                print(f"× sid={sid} 无对应divi品牌")
                error += 1
                continue

            result = import_order_from_lingxing_to_divi(order_id=order_id, print_if=True)
            if result and getattr(result, 'code', 200) == 200:
                print("✓ 补导成功")
                success += 1
                order.is_exported_to_divi = True
                order.save(update_fields=['is_exported_to_divi'])
            else:
                print(f"× 补导失败: {result}")
                error += 1

        except Exception as e:
            print(f"× 异常: {str(e)}")
            error += 1

    return success, error


def get_brand_id_with_cache(sid):
    """带缓存的 SID 到 BrandID 映射"""
    if sid not in _BRAND_ID_CACHE:
        _BRAND_ID_CACHE[sid] = get_divi_brand_id_from_sid(sid)
    return _BRAND_ID_CACHE[sid]


def fetch_all_divi_orders():
    """一次性拉取所有DIVI订单（解决brand_id参数无效问题）"""
    exists, orders, extra = query_divi_order(
        amazon_order_id=None,
        brand_id=None,
        has_logistics=False
    )
    return exists, orders or [], extra  # ← 返回3个值


def group_divi_by_brand_name(divi_orders):
    """内存分组：按 brandName 对DIVI订单建索引"""
    grouped = defaultdict(list)
    for order in divi_orders:
        brand_name = order.get('brandName', '').strip()
        if brand_name:
            grouped[brand_name].append(order)
    return grouped


def get_active_shops_with_divi():
    """获取所有正常且配置了divi_shop_id的店铺"""
    return AmazonShop.objects.filter(
        shop_status='正常',
        divi_shop_id__isnull=False,
    ).select_related()


def sync_brand_orders(divi_by_brand_name, force_reimport):
    """
    批量同步DIVI订单数据（v3优化版）
    使用预分组数据，避免重复API调用
    """
    total_success = total_error = 0

    # 获取所有待处理的店铺
    shops = get_active_shops_with_divi()

    print(f"\n【批量同步阶段】共 {shops.count()} 个品牌需要处理")
    print("=" * 96)

    for shop in shops:
        brand_id = shop.divi_shop_id
        brand_name = shop.shop_name

        # 获取该品牌的本地订单
        start_datetime = datetime.strptime(f"{TARGET_DATE} 00:00:00", "%Y-%m-%d %H:%M:%S")
        local_orders = list(AmazonOrders.objects.filter(
            amazon_shop=shop,
            fulfillment_channel='MFN',
            purchase_date_local__gte=start_datetime,
        ).exclude(
            order_status__in=EXCLUDE_AMAZON_STATUS
        ).select_related('lingxing_shop'))

        if not local_orders:
            continue

        # 从内存中获取该品牌的DIVI订单
        divi_orders = divi_by_brand_name.get(brand_name, [])
        divi_dict = {
            str(d.get("amazonOrderId")).strip(): d
            for d in divi_orders
            if d.get("amazonOrderId")
        }

        print(f"\n>>> 开始同步品牌: {brand_name} (brand_id={brand_id})")
        print(f"  📦 本地订单数: {len(local_orders)}")
        print(f"  🎯 DIVI匹配数: {len(divi_dict)}")

        success_batch = error_batch = 0

        for i, order in enumerate(local_orders, 1):
            order_id = order.amazon_order_id
            divi_data = divi_dict.get(order_id)

            if not divi_data:
                error_batch += 1
                print(f"  ❌ [{i}/{len(local_orders)}] {order_id} 在DIVI中不存在")
                continue

            # 补导逻辑（仅漏单）
            if force_reimport and not order.is_exported_to_divi:
                try:
                    result = import_order_from_lingxing_to_divi(order_id=order_id, print_if=False)
                    if result and getattr(result, 'code', 200) == 200:
                        print(f"  🔄 [{i}/{len(local_orders)}] {order_id} 补导成功")
                        order.is_exported_to_divi = True
                        order.save(update_fields=['is_exported_to_divi'])
                    else:
                        print(f"  ❌ [{i}/{len(local_orders)}] {order_id} 补导失败: {result}")
                        error_batch += 1
                        continue
                except Exception as e:
                    print(f"  ❌ [{i}/{len(local_orders)}] {order_id} 补导异常: {e}")
                    error_batch += 1
                    continue

            # 字段同步
            try:
                update_divi_order_fields(order, divi_data)
                success_batch += 1
                if i % 10 == 0 or i == len(local_orders):  # 每10条打印一次，避免刷屏
                    print(f"  ✅ [{i}/{len(local_orders)}] {order_id} 字段同步成功")
            except Exception as e:
                error_batch += 1
                print(f"  ❌ [{i}/{len(local_orders)}] {order_id} 字段同步失败: {e}")

        total_success += success_batch
        total_error += error_batch
        print(f"  📊 本批次: 成功 {success_batch} | 失败 {error_batch}")

    return total_success, total_error


def divi_process_orders(target_date_str, force_reimport):
    """主流程：保留v2两阶段结构，仅优化同步阶段"""
    start_datetime = datetime.strptime(f"{target_date_str} 00:00:00", "%Y-%m-%d %H:%M:%S")

    print(f"\n{'=' * 96}")
    print(f"精准补导 + 字段同步脚本启动 (v3.2 - 保留两阶段结构)")
    print(f"目标日期：{target_date_str} 及之后 | MFN订单 | 仅处理店铺状态=正常的订单")
    print(f"补导模式：{'开启 ✅' if force_reimport else '关闭 ❌'}")
    print(f"{'=' * 96}\n")

    # ========== 阶段1：补导（逐单）==========
    if force_reimport:
        reimport_queryset = query_reimport_orders(start_datetime)
        reimport_total = reimport_queryset.count()

        # 打印统计
        all_missed = AmazonOrders.objects.filter(
            fulfillment_channel='MFN',
            purchase_date_local__gte=start_datetime,
            is_exported_to_divi=False,
        ).exclude(order_status__in=EXCLUDE_AMAZON_STATUS)
        print(f"【补导阶段】原始漏单: {all_missed.count()} | 过滤后（店铺正常）: {reimport_total}\n")

        if reimport_total > 0:
            reimport_success, reimport_errors = reimport_orders(reimport_queryset, reimport_total)
        else:
            reimport_success = reimport_errors = 0
    else:
        reimport_success = reimport_errors = 0
        print("【补导阶段】补导模式关闭，跳过")

    # ========== 阶段2：同步（批量）==========
    print("\n" + "=" * 96)
    print("【批量同步阶段】正在准备数据...")

    # 一次性拉取DIVI全量订单
    exists, divi_orders_all, _ = fetch_all_divi_orders()
    if not exists or not divi_orders_all:
        print("❌ 未能从 DIVI 获取订单数据，同步终止！")
        return

    print(f"📦 成功获取 {len(divi_orders_all)} 条 DIVI 订单")

    # 内存分组
    divi_by_brand_name = group_divi_by_brand_name(divi_orders_all)
    print(f"🎯 共涉及 {len(divi_by_brand_name)} 个品牌\n")

    # 执行同步
    sync_success, sync_errors = sync_brand_orders(divi_by_brand_name, force_reimport)

    # ========== 最终统计 ==========
    print(f"\n{'=' * 96}")
    print("任务完成！最终统计：")
    if force_reimport:
        print(f"  补导成功: {reimport_success}")
        print(f"  补导失败: {reimport_errors}")
    print(f"  字段同步成功: {sync_success}")
    print(f"  字段同步失败: {sync_errors}")
    print(f"{'=' * 96}")
    print("✅ 完美结束！去页面看看吧～")


if __name__ == '__main__':
    t = Timer()
    t.start()
    divi_process_orders(TARGET_DATE, ENABLE_REIMPORT)
    t.stop()
    print("运行时长：", t)