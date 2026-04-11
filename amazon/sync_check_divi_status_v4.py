#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
终极精准补导 + 字段同步脚本（v2.1 - 增加店铺状态过滤）

核心改进：
1. 按 brand_id 批量拉取 DIVI 订单，不再是逐单请求
2. 从源头过滤：只查询店铺状态为"正常"的订单
3. 使用 select_related 优化查询性能
4. 对于没有关联 amazon_shop 的订单自动排除（外键为NULL）
5.
"""

import os
import sys
import time

import django
from datetime import datetime

from api.Y.y_tiem import Timer

# ========== Django环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

from amazon.models import AmazonOrders, LingXingAmazonShop
from general.models import AmazonShop, Project

from api.divi.divi_order_service import (
    query_divi_order,
    get_divi_brand_id_from_sid,
    import_order_from_lingxing_to_divi,
)
from amazon.amazon_divi_views import update_divi_order_fields

# 要排除的亚马逊订单状态
EXCLUDE_AMAZON_STATUS = {'PendingAvailability', 'Pending', 'Canceled'}

# ============ 核心配置：直接修改此变量切换模式 ============
# 设置为 True 启用补导模式，False 仅同步字段
ENABLE_REIMPORT = True  # 修改这个值即可切换模式！
# ===========================================================

# ============ 日期配置 ============
TARGET_DATE = "2026-01-01"  # 同步/补导的起始日期

# 注意：本脚本被 sync_a_doing.py 7×24小时循环调用，不能使用缓存
# 所有数据必须实时从数据库获取，确保数据一致性


def check_project_divi_config(brand_id):
    """
    检查 brand_id 对应的项目是否配置了 DIVI 接口
    返回: (是否可导单, 项目信息字符串)
    注意：实时查询，不使用缓存（因为被循环调用）
    """
    try:
        # 通过 brand_id (divi_shop_id) 找到 AmazonShop
        shop = AmazonShop.objects.filter(divi_shop_id=brand_id).select_related('project').first()
        if not shop:
            return (False, f"brand_id={brand_id} 无对应店铺")
        
        if not shop.project:
            return (False, f"店铺 {shop.name} 未绑定项目")
        
        project = shop.project
        # 检查项目是否配置了 DIVI 凭证
        if not project.divi_partner_code or not project.divi_secret:
            return (False, f"项目 '{project.name}'(ID:{project.id}) 未配置 DIVI 凭证")
        
        return (True, f"项目 '{project.name}'")
        
    except Exception as e:
        return (False, f"检查项目配置异常: {str(e)}")


# ==================================


def query_reimport_orders(start_datetime):
    """查询需要补导的订单：本地标记为未导出 + 店铺状态正常 + 项目已配置DIVI凭证"""
    # 先获取所有符合条件的订单（未导出、店铺状态正常）
    orders = AmazonOrders.objects.filter(
        fulfillment_channel='MFN',
        purchase_date_local__gte=start_datetime,
        is_exported_to_divi=False,  # 核心条件：只找漏单
        amazon_shop__shop_status='正常',  # ⭐ 只查询正常状态的店铺
    ).exclude(
        divi_order_status__in={0, 5}
    ).exclude(
        order_status__in=EXCLUDE_AMAZON_STATUS
    ).select_related(
        'lingxing_shop',
        'amazon_shop',  # ⭐ 新增：优化查询
        'amazon_shop__project'  # ⭐ 新增：获取项目信息用于检查凭证
    ).order_by('purchase_date_local')
    
    # ⭐ 新增：过滤出项目已配置 DIVI 凭证的订单
    # 先收集所有需要检查的 brand_id
    brand_ids_to_check = set()
    for order in orders:
        sid = order.lingxing_shop.sid if order.lingxing_shop else None
        if sid:
            brand_id = get_brand_id(sid)
            if brand_id:
                brand_ids_to_check.add(brand_id)
    
    # 批量检查项目配置，缓存结果
    valid_brand_ids = set()
    for brand_id in brand_ids_to_check:
        can_import, _ = check_project_divi_config(brand_id)
        if can_import:
            valid_brand_ids.add(brand_id)
    
    # 过滤订单：只保留项目已配置凭证的
    filtered_order_ids = []
    for order in orders:
        sid = order.lingxing_shop.sid if order.lingxing_shop else None
        if sid:
            brand_id = get_brand_id(sid)
            if brand_id in valid_brand_ids:
                filtered_order_ids.append(order.id)
    
    return AmazonOrders.objects.filter(id__in=filtered_order_ids).select_related(
        'lingxing_shop', 'amazon_shop'
    ).order_by('purchase_date_local')


def query_sync_orders(start_datetime):
    """查询需要同步的订单：店铺状态必须为正常"""
    return AmazonOrders.objects.filter(
        fulfillment_channel='MFN',
        purchase_date_local__gte=start_datetime,
        amazon_shop__shop_status='正常',  # ⭐ 新增：只查询正常状态的店铺
    ).exclude(
        order_status__in=EXCLUDE_AMAZON_STATUS
    ).select_related(
        'lingxing_shop',
        'amazon_shop'  # ⭐ 新增：优化查询
    ).order_by('purchase_date_local')


def reimport_orders(queryset, total):
    """执行补导操作（逐单模式，仅用于补导）"""
    if total == 0:
        print("【补导阶段】未发现漏单，跳过")
        return 0, 0

    print(f"\n【补导阶段】找到 {total} 条漏单，开始导入DIVI...\n")
    success = error = 0

    for i, order in enumerate(queryset, 1):
        order_id = order.amazon_order_id
        print(f"[补导 {i:>4}/{total}] {order_id}", end="  ")

        try:
            sid = order.lingxing_shop.sid if order.lingxing_shop else None
            if not sid:
                print("× 无领星店铺")
                error += 1
                continue

            brand_id = get_brand_id(sid)
            if not brand_id:
                print(f"× sid={sid} 无对应divi品牌")
                error += 1
                continue

            # ⭐ 提前检查项目是否配置了 DIVI 接口
            can_import, project_info = check_project_divi_config(brand_id)
            if not can_import:
                print(f"× {project_info}，跳过导单")
                error += 1
                continue

            # 执行补导
            result = import_order_from_lingxing_to_divi(order_id=order_id, print_if=True)
            if result and getattr(result, 'code', 200) == 200:
                print(result)
                print("✓ 补导成功")
                success += 1
                # 立即标记，避免重复导入
                order.is_exported_to_divi = True
                order.save(update_fields=['is_exported_to_divi'])
            else:
                print(f"× 补导失败: {result}")
                error += 1

        except Exception as e:
            print(f"× 异常: {str(e)}")
            error += 1

    return success, error

def get_brand_id(sid):
    """获取 SID 对应的 BrandID（实时查询，无缓存）"""
    return get_divi_brand_id_from_sid(sid)


def get_brand_info(brand_id):
    """获取 brand_id → 店铺信息映射（实时查询，无缓存）"""
    shop = AmazonShop.objects.filter(
        divi_shop_id=brand_id
    ).select_related('project').first()
    
    if shop:
        return {
            'shop_name': shop.shop_name or '未命名店铺',
            'project_name': shop.project.name if shop.project else '未分配项目',
            'sid': shop.id
        }
    else:
        return {
            'shop_name': '未知店铺',
            'project_name': '未知项目',
            'sid': None
        }


def extract_unique_brand_ids(start_datetime):
    """
    提取需要同步的订单中出现的所有唯一 brand_id（只包含项目已配置DIVI凭证的）
    通过 SID → BrandID 映射，并自动去重，同时过滤掉未配置凭证的项目
    返回: (brand_ids列表, brand_info_dict)
        - brand_ids: [brand_id1, brand_id2, ...]
        - brand_info_dict: {brand_id: {'shop_name': ..., 'project_name': ...}, ...}
    """
    # 1. 先获取所有待同步订单的店铺 SID（去重）
    # ⭐ 注意：这里已经通过 query_sync_orders 过滤了店铺状态
    orders_with_sid = AmazonOrders.objects.filter(
        fulfillment_channel='MFN',
        purchase_date_local__gte=start_datetime,
        amazon_shop__shop_status='正常',  # ⭐ 确保只查询正常店铺
    ).exclude(
        order_status__in=EXCLUDE_AMAZON_STATUS
    ).exclude(
        lingxing_shop__isnull=True
    ).values('lingxing_shop__sid').distinct()

    # 2. 映射为 BrandID 并去重，同时检查项目配置
    brand_ids = set()
    brand_info = {}
    skipped_brands = []  # 记录被跳过的品牌
    
    for row in orders_with_sid:
        sid = row['lingxing_shop__sid']
        brand_id = get_brand_id(sid)
        if brand_id:
            # ⭐ 新增：检查项目是否配置了 DIVI 凭证
            can_import, msg = check_project_divi_config(brand_id)
            if not can_import:
                if brand_id not in [b['brand_id'] for b in skipped_brands]:
                    skipped_brands.append({'brand_id': brand_id, 'reason': msg})
                continue
            
            brand_ids.add(brand_id)
            # 获取店铺详细信息（实时查询）
            if brand_id not in brand_info:
                brand_info[brand_id] = get_brand_info(brand_id)

    # 打印被跳过的品牌信息
    if skipped_brands:
        print(f"\n⚠️  跳过 {len(skipped_brands)} 个未配置DIVI凭证的品牌：")
        for sb in skipped_brands:
            print(f"    - brand_id={sb['brand_id']}: {sb['reason']}")
        print()

    return list(brand_ids), brand_info

def sync_brand_orders(brand_ids, brand_info=None):
    """
    按 brand_id 批量同步 DIVI 订单数据（v2 核心函数）
    一个 brand_id 可能对应多个领星店铺
    
    Args:
        brand_ids: brand_id 列表
        brand_info: {brand_id: {'shop_name': ..., 'project_name': ...}, ...}
    """
    total_success = total_error = 0
    
    if brand_info is None:
        brand_info = {}

    for brand_id in brand_ids:
        # 获取店铺名
        info = brand_info.get(brand_id, {})
        shop_name = info.get('shop_name', '未知店铺')
        
        print(f"\n{'=' * 60}")
        print(f">>> 开始同步 brand_id={brand_id} (店铺: {shop_name})")

        try:
            # 1. 批量获取该品牌下所有 DIVI 订单（一次网络请求）
            exists, divi_orders, _ = query_divi_order(
                amazon_order_id=None,  # 空值代表全量拉取
                brand_id=brand_id,
                has_logistics=False
            )

            if not exists or not divi_orders:
                print(f"  ⚠️  无数据或 brand_id={brand_id} 下没有可同步订单")
                continue

            # 2. 转换为字典：key 是 amazon_order_id，实现 O(1) 查找
            divi_dict = {
                str(d.get("amazonOrderId")).strip(): d
                for d in divi_orders
                if d.get("amazonOrderId")
            }

            # 3. 提取所有订单 ID，用于一次性查询本地订单
            divi_order_ids = list(divi_dict.keys())

            # 4. 批量查询本地待同步订单（一次数据库查询，已过滤店铺状态）
            local_orders = AmazonOrders.objects.filter(
                amazon_order_id__in=divi_order_ids,
                fulfillment_channel='MFN',
                purchase_date_local__gte=datetime.strptime(f"{TARGET_DATE} 00:00:00",
                                                           "%Y-%m-%d %H:%M:%S"),
                amazon_shop__shop_status='正常',  # ⭐ 确保只查询正常店铺
            ).exclude(
                order_status__in=EXCLUDE_AMAZON_STATUS
            ).select_related(
                'lingxing_shop',
                'amazon_shop'  # ⭐ 确保能访问店铺状态
            )

            print(f"  📦 DIVI 返回 {len(divi_orders)} 条订单")
            print(f"  🎯 本地匹配到 {local_orders.count()} 条待更新订单（店铺状态正常）")

            # 5. 批量更新
            success_batch, error_batch = 0, 0
            for order in local_orders:
                order_id = order.amazon_order_id
                divi_data = divi_dict.get(order_id)

                if not divi_data:
                    error_batch += 1
                    print(f"  ❌ 订单 {order_id} 在 DIVI 字典中不存在")
                    continue

                try:
                    update_divi_order_fields(order, divi_data)
                    success_batch += 1
                    print(f"  ✅ {order_id} 字段已同步")
                except Exception as e:
                    error_batch += 1
                    print(f"  ❌ 更新 {order_id} 失败: {e}")

            total_success += success_batch
            total_error += error_batch

            print(f"  📊 本批次成功: {success_batch} | 失败: {error_batch}")

        except Exception as e:
            print(f"  🔥 brand_id={brand_id} 处理异常: {e}")
            continue

    return total_success, total_error

def divi_process_orders(target_date_str, force_reimport):
    """主流程：根据模式执行补导 + 批量同步"""
    start_datetime = datetime.strptime(f"{target_date_str} 00:00:00", "%Y-%m-%d %H:%M:%S")

    print(f"\n{'=' * 96}")
    print(f"精准补导 + 字段同步脚本启动 (v2.1 - 增加店铺状态过滤)")
    print(f"目标日期：{target_date_str} 及之后 | MFN订单 | 仅处理店铺状态=正常的订单")
    print(f"补导模式：{'开启' if force_reimport else '关闭'}")
    print(f"{'=' * 96}\n")

    # 步骤1：补导模式才执行的补漏单操作（查询时已过滤店铺状态）
    reimport_success = reimport_errors = 0
    if force_reimport:
        reimport_queryset = query_reimport_orders(start_datetime)
        reimport_total = reimport_queryset.count()

        # ⭐ 打印过滤后的数量
        all_queryset = AmazonOrders.objects.filter(
            fulfillment_channel='MFN',
            purchase_date_local__gte=start_datetime,
            is_exported_to_divi=False,
        ).exclude(order_status__in=EXCLUDE_AMAZON_STATUS)
        total_without_status_filter = all_queryset.count()

        print(f"【补导阶段】原始漏单数量: {total_without_status_filter}")
        print(f"【补导阶段】过滤后（店铺状态正常）: {reimport_total}\n")

        if reimport_total > 0:
            reimport_success, reimport_errors = reimport_orders(reimport_queryset, reimport_total)
            time.sleep(1)

    # 步骤2：所有模式都执行的批量字段同步操作（已过滤店铺状态）
    print("\n【批量同步阶段】正在提取需要同步的品牌...")
    brand_ids, brand_info = extract_unique_brand_ids(start_datetime)
    
    # 按项目分组统计
    project_groups = {}
    for bid in brand_ids:
        info = brand_info.get(bid, {})
        proj_name = info.get('project_name', '未知项目')
        if proj_name not in project_groups:
            project_groups[proj_name] = []
        project_groups[proj_name].append({
            'brand_id': bid,
            'shop_name': info.get('shop_name', '未知店铺')
        })
    
    print(f"🚀 准备同步 {len(brand_ids)} 个品牌的数据（已过滤店铺状态），分布如下：")
    for proj_name, shops in sorted(project_groups.items()):
        print(f"\n  【{proj_name}】: {len(shops)}个品牌")
        for shop in shops:
            print(f"    - brand_id={shop['brand_id']} (店铺: {shop['shop_name']})")
    print()  # 空行

    sync_success, sync_errors = sync_brand_orders(brand_ids, brand_info)

    # 最终统计报告
    print(f"\n{'=' * 96}")
    print("任务完成！最终统计：")
    if force_reimport:
        print(f"  补导成功（店铺正常）: {reimport_success}")
        print(f"  补导失败             : {reimport_errors}")
    print(f"  字段同步成功         : {sync_success}")
    print(f"  字段同步失败         : {sync_errors}")
    print(f"{'=' * 96}")
    if force_reimport:
        print("✓ 补导模式：已跳过非正常店铺，完成补导和同步")
    else:
        print("✓ 同步模式：已跳过非正常店铺，完成字段同步")
    print("✅ 完美结束！去页面看看吧～")

if __name__ == '__main__':
    t = Timer()
    t.start()
    divi_process_orders(TARGET_DATE, ENABLE_REIMPORT)
    t.stop()
    print("运行时长：", t)