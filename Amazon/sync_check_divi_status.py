#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
终极精准补导 + 字段同步脚本（变量控制版）

使用方式：
    直接运行：python sync_check_divi_status.py

配置项：
    ENABLE_REIMPORT = True   # 启用补导模式（先补漏单再同步字段）
    ENABLE_REIMPORT = False  # 仅同步字段模式
"""

import os
import sys
import django
from datetime import datetime

# ========== Django环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

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
# 设置为 True 启用补导模式，False 仅同步字段
# ENABLE_REIMPORT = False  # 修改这个值即可切换模式！
ENABLE_REIMPORT = True # 修改这个值即可切换模式！
# ===========================================================

# ============ 日期配置 ============
TARGET_DATE = "2025-11-19"  # 同步/补导的起始日期


# ==================================

def query_reimport_orders(start_datetime):
    """查询需要补导的订单：本地标记为未导出"""
    return (AmazonOrders.objects.filter(
        fulfillment_channel='MFN',
        purchase_date_local__gte=start_datetime,
        is_exported_to_divi=False,  # 核心条件：只找漏单
    ).exclude(
        divi_order_status__in={0, 5}
    ).exclude(
        order_status__in=EXCLUDE_AMAZON_STATUS
    ).select_related('lingxing_shop', 'amazon_shop').order_by('purchase_date_local'))


def query_sync_orders(start_datetime):
    """查询需要同步的订单：DIVI系统中进行中状态"""
    return AmazonOrders.objects.filter(
        fulfillment_channel='MFN',
        purchase_date_local__gte=start_datetime,
    ).exclude(
        order_status__in=EXCLUDE_AMAZON_STATUS
    ).select_related('lingxing_shop', 'amazon_shop').order_by('purchase_date_local')


def reimport_orders(queryset, total):
    """执行补导操作"""
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

            brand_id = get_divi_brand_id_from_sid(sid)
            if not brand_id:
                print(f"× sid={sid} 无对应divi品牌")
                error += 1
                continue

            # 执行补导
            result = import_order_from_lingxing_to_divi(order_id=order_id, print_if=True)
            if result and getattr(result, 'code', 200) == 200:
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


def sync_orders(queryset, total, is_reimport_mode=False):
    """执行字段同步操作"""
    if total == 0:
        print("【同步阶段】无订单需要同步字段")
        return 0, 0

    mode_desc = "（含刚补导的订单）" if is_reimport_mode else ""
    print(f"\n【同步阶段】找到 {total} 条订单{mode_desc}，开始同步最新字段...\n")
    success = error = 0

    for i, order in enumerate(queryset, 1):
        order_id = order.amazon_order_id
        print(f"[同步 {i:>4}/{total}] {order_id}", end="  ")

        try:
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

            # 查询DIVI最新数据并更新
            exists, divi_orders, _ = query_divi_order(
                amazon_order_id=order_id,
                brand_id=brand_id,
                has_logistics=False
            )

            if exists and divi_orders:
                update_divi_order_fields(order, divi_orders[0])
                print("✓ 字段已同步")
                success += 1
            else:
                print("→ DIVI中不存在（可能已取消或导入中）")

        except Exception as e:
            print(f"× 异常: {str(e)}")
            error += 1

    return success, error


def process_orders(target_date_str, force_reimport):
    """主流程：根据模式执行不同操作"""
    start_datetime = datetime.strptime(f"{target_date_str} 00:00:00", "%Y-%m-%d %H:%M:%S")

    print(f"\n{'=' * 96}")
    print(f"精准补导 + 字段同步脚本启动")
    print(f"目标日期：{target_date_str} 及之后 | MFN订单")
    print(f"补导模式：{'开启' if force_reimport else '关闭'}")
    print(f"{'=' * 96}\n")

    # 步骤1：补导模式才执行的补漏单操作
    reimport_success = reimport_errors = 0
    if force_reimport:
        reimport_queryset = query_reimport_orders(start_datetime)
        reimport_total = reimport_queryset.count()
        reimport_success, reimport_errors = reimport_orders(reimport_queryset, reimport_total)

    # 步骤2：所有模式都执行的字段同步操作
    sync_queryset = query_sync_orders(start_datetime)
    sync_total = sync_queryset.count()
    sync_success, sync_errors = sync_orders(sync_queryset, sync_total, force_reimport)

    # 最终统计
    print(f"\n{'=' * 96}")
    print("任务完成！最终统计：")
    if force_reimport:
        print(f"  补导成功             : {reimport_success}")
        print(f"  补导失败             : {reimport_errors}")
    print(f"  字段同步成功         : {sync_success}")
    print(f"  字段同步失败         : {sync_errors}")
    print(f"{'=' * 96}")
    if force_reimport:
        print("✓ 补导模式：漏单已补导，所有进行中订单字段已同步")
    else:
        print("✓ 同步模式：所有进行中订单字段已更新")
    print("完美结束！去页面看看吧～")


if __name__ == '__main__':
    # 直接调用，不再需要命令行参数
    process_orders(TARGET_DATE, ENABLE_REIMPORT)