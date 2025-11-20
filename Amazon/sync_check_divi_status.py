#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
独立脚本：检查Divi订单存在性并标记已导出
使用方法：python check_divi_status.py
"""

import os
import sys
import django
import asyncio

# ========== Django环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

# ========== 导入Django模型和函数 ==========
from datetime import datetime
from django.utils import timezone
from Amazon.models import AmazonOrders
from Api.divi.divi_order_service import query_divi_order, get_divi_brand_id_from_sid


def process_orders(target_date='2025-11-19'):
    """
    处理指定日期及之后的MFN未导出订单
    """
    print(f"开始处理 {target_date} 及之后的MFN未导出订单...")

    # 查询符合条件的订单
    start_datetime = f"{target_date} 00:00:00"
    orders = AmazonOrders.objects.filter(
        fulfillment_channel='MFN',
        purchase_date_local__gte=start_datetime,
        is_exported_to_divi=False
    ).select_related('lingxing_shop')

    total = orders.count()
    print(f"找到 {total} 条待处理订单")

    if total == 0:
        print("没有需要处理的订单")
        return

    success_count = 0
    skip_count = 0
    error_count = 0

    for i, order in enumerate(orders, 1):
        print(f"\n[{i}/{total}] 订单: {order.amazon_order_id}")

        try:
            # 获取sid
            if not order.lingxing_shop:
                print("  ❌ 错误：订单未关联领星店铺")
                error_count += 1
                continue

            sid = order.lingxing_shop.sid

            # 获取brand_id
            brand_id = get_divi_brand_id_from_sid(sid)
            if not brand_id:
                print(f"  ❌ 错误：sid={sid} 未配置divi_shop_id")
                error_count += 1
                continue

            print(f"  -> brand_id: {brand_id}")

            # 查询Divi订单是否存在（同步调用）
            exists, divi_orders, _ = query_divi_order(
                amazon_order_id=order.amazon_order_id,
                brand_id=brand_id,
                has_logistics=False
            )

            if exists:
                # 标记为已导出
                order.is_exported_to_divi = True
                order.save(update_fields=['is_exported_to_divi'])
                print(f"  ✅ 成功：Divi中存在({len(divi_orders)}条)，已标记为已导出")
                success_count += 1
            else:
                print(f"  ⏭️  跳过：Divi中不存在")
                skip_count += 1

        except Exception as e:
            print(f"  ❌ 异常：{str(e)}")
            error_count += 1

    # 打印汇总
    print("\n" + "=" * 60)
    print("处理完成统计:")
    print(f"  ✅ 成功标记: {success_count}")
    print(f"  ⏭️  跳过: {skip_count}")
    print(f"  ❌ 错误: {error_count}")
    print("=" * 60)


def main():
    """主函数"""
    # 可修改日期参数
    TARGET_DATE = '2025-11-19'
    process_orders(TARGET_DATE)


if __name__ == '__main__':
    main()