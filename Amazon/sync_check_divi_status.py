#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
终极精准补导 + 字段同步脚本（你最想要的版本）

功能：
1. 始终只处理：2025-11-19及之后 + MFN + divi_order_status=1~4 的进行中订单
2. 所有订单都强制更新最新 divi_ 字段（含商品明细 divi_product_name）
3. 额外功能（可控补导）：
   - 当你手动把 FORCE_REIMPORT = True 时
   - 且订单的 is_exported_to_divi = False
   → 才会调用 import_order_from_lingxing_to_divi 进行一次“补导”
   → 其他情况一律不导入（安全！）

使用方式：
    python sync_check_divi_status.py                 # 普通模式：只更新字段
    编辑脚本第23行改成 True → 下次运行就是补导模式
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

from django.db import models
from Amazon.models import AmazonOrders
from Api.divi.divi_order_service import (
    query_divi_order,
    get_divi_brand_id_from_sid,
    import_order_from_lingxing_to_divi,   # 只在需要时使用
)
from Amazon.amazon_divi_views import update_divi_order_fields


# 要排除的亚马逊订单状态
EXCLUDE_AMAZON_STATUS = {'PendingAvailability', 'Pending', 'Canceled'}
TARGET_DIVI_STATUS = {1, 2, 3, 4}

# ============ 核心开关：默认关闭，你想补导时手动改为 True ============
FORCE_REIMPORT = False   # ← 改成 True 就开启“精准补导模式”
# =====================================================================


def process_orders(target_date_str="2025-11-19"):
    reimport_mode = "开启（仅对 is_exported_to_divi=False 的订单补导）" if FORCE_REIMPORT else "关闭"
    print(f"\n{'='*96}")
    print(f"精准补导 + 字段同步脚本启动")
    print(f"日期：{target_date_str} 及之后 | MFN | divi_order_status=1~4")
    print(f"强制补导模式：{reimport_mode}")
    print(f"{'='*96}\n")

    start_datetime = datetime.strptime(f"{target_date_str} 00:00:00", "%Y-%m-%d %H:%M:%S")

    # 精准筛选：只处理还在流转中的订单
    queryset = AmazonOrders.objects.filter(
        fulfillment_channel='MFN',
        purchase_date_local__gte=start_datetime,
        divi_order_status__in=TARGET_DIVI_STATUS,
    ).exclude(
        order_status__in=EXCLUDE_AMAZON_STATUS
    ).select_related('lingxing_shop', 'amazon_shop').order_by('purchase_date_local')

    total = queryset.count()
    print(f"找到 {total} 条进行中订单（divi_order_status=1~4）\n")

    if total == 0:
        print("无订单需要处理，任务结束。")
        return

    sync_success = 0
    reimport_success = 0
    already_exported = 0
    error = 0

    for i, order in enumerate(queryset, 1):
        order_id = order.amazon_order_id
        is_exported = order.is_exported_to_divi
        print(f"[{i:>4}/{total}] {order_id}", end="  ")

        try:
            sid = order.lingxing_shop.sid if order.lingxing_shop else None
            if not sid:
                print("无领星店铺")
                error += 1
                continue

            brand_id = get_divi_brand_id_from_sid(sid)
            if not brand_id:
                print(f"sid={sid} 无divi_shop_id")
                error += 1
                continue

            # ========== 核心逻辑：是否需要补导 ==========
            need_reimport = FORCE_REIMPORT and not is_exported
            if need_reimport:
                print("检测到未导出 → 正在补导...", end="")
                result = import_order_from_lingxing_to_divi(
                    order_id=order_id,
                    print_if=True
                )
                if result and getattr(result, 'code', 200) == 200:
                    print("补导成功", end="")
                    reimport_success += 1
                else:
                    print(f"补导失败: {result}", end="")
                    error += 1
                    # 补导失败也不影响后续字段更新

            # ========== 无论是否补导，都强制更新最新字段 ==========
            exists, divi_orders, _ = query_divi_order(
                amazon_order_id=order_id,
                brand_id=brand_id,
                has_logistics=False
            )

            if exists and divi_orders:
                update_divi_order_fields(order, divi_orders[0])
                if not need_reimport:
                    print("字段已同步")
                else:
                    print(" → 字段已同步")
                sync_success += 1
            else:
                print("Divi中不存在（异常）")
                error += 1

        except Exception as e:
            print(f"异常: {str(e)}")
            error += 1

    print(f"\n{'='*96}")
    print("任务完成！最终统计：")
    print(f"  总处理订单数         : {total}")
    print(f"  字段同步成功         : {sync_success}")
    if FORCE_REIMPORT:
        print(f"  补导成功（未导出订单）: {reimport_success}")
        print(f"  已导出不需补导       : {total - reimport_success - error}")
    print(f"  失败/异常            : {error}")
    print(f"{'='*96}")
    if FORCE_REIMPORT:
        print("补导模式已执行：仅对 is_exported_to_divi=False 的订单进行了导入")
    else:
        print("普通模式：所有进行中订单字段已更新最新")
    print("完美结束！去页面看看吧～")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="精准补导 + 字段同步脚本")
    parser.add_argument('date', nargs='?', default='2025-11-19', help='起始日期（默认 2025-11-19）')
    args = parser.parse_args()
    process_orders(args.date)