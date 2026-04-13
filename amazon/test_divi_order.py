#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
单订单 DIVI 查询测试脚本
用法：
    python amazon/test_divi_order.py <amazon_order_id>
示例：
    python amazon/test_divi_order.py 111-9386675-2885004
"""

import os
import sys
import json
import argparse

# ========== Django 环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
import django
django.setup()

from amazon.models import AmazonOrders
from api.divi.divi_order_service import get_divi_brand_id_from_sid, query_divi_order


def test_order(amazon_order_id: str):
    print(f"\n{'=' * 80}")
    print(f"正在测试订单: {amazon_order_id}")
    print(f"{'=' * 80}\n")

    # 1. 查本地
    order = AmazonOrders.objects.filter(amazon_order_id=amazon_order_id).select_related(
        'lingxing_shop', 'amazon_shop'
    ).first()

    if not order:
        print(f"❌ 本地数据库中未找到订单 {amazon_order_id}")
        return

    print("【本地数据库信息】")
    print(f"  订单号          : {order.amazon_order_id}")
    print(f"  店铺            : {order.amazon_shop.shop_name if order.amazon_shop else 'N/A'}")
    print(f"  sid             : {order.lingxing_shop.sid if order.lingxing_shop else 'N/A'}")
    print(f"  是否已导DIVI    : {order.is_exported_to_divi}")
    print(f"  DIVI状态        : {order.divi_order_status}")
    print(f"  DIVI物流方式    : {order.divi_logistics_method or 'N/A'}")
    print(f"  DIVI物流单号    : {order.divi_tracking_number or 'N/A'}")
    print(f"  DIVI导入时间    : {order.divi_import_time or 'N/A'}")
    print(f"  DIVI付款时间    : {order.divi_payment_time or 'N/A'}")
    print(f"  DIVI发货时间    : {order.divi_shipment_time or 'N/A'}")
    print()

    # 2. 获取 brand_id
    sid = order.lingxing_shop.sid if order.lingxing_shop else None
    if not sid:
        print("❌ 该订单没有关联领星店铺(sid)，无法查询 DIVI")
        return

    brand_id = get_divi_brand_id_from_sid(sid)
    if not brand_id:
        print(f"❌ sid={sid} 未找到对应的 DIVI brand_id")
        return

    print(f"sid={sid} -> brand_id={brand_id}")
    print()

    # 3. 调 DIVI API
    print("【DIVI API 查询中...】")
    exists, orders, raw_json = query_divi_order(
        amazon_order_id=amazon_order_id,
        brand_id=brand_id,
        has_logistics=False,
        days=None,
        start_time="2024-01-01 00:00:00",
        end_time="2026-12-31 23:59:59",
        print_if=True,
    )

    print()
    if not exists or not orders:
        print(f"❌ DIVI 系统中未找到订单 {amazon_order_id}")
        return

    divi_data = orders[0]
    print("【DIVI 返回的订单字段】")
    print(json.dumps(divi_data, indent=2, ensure_ascii=False))
    print()

    # 4. 关键字段摘要
    print("【DIVI 字段摘要】")
    print(f"  taskOrderId       : {divi_data.get('taskOrderId')}")
    print(f"  amazonOrderId     : {divi_data.get('amazonOrderId')}")
    print(f"  taskOrderNumber   : {divi_data.get('taskOrderNumber')}")
    print(f"  status            : {divi_data.get('status')}")
    print(f"  createTime        : {divi_data.get('createTime')}")
    print(f"  paymentTime       : {divi_data.get('paymentTime')}")
    print(f"  sendOrderTime     : {divi_data.get('sendOrderTime')}")
    print(f"  sendGoodsTime     : {divi_data.get('sendGoodsTime')}")
    print(f"  logisticsMethod   : {divi_data.get('logisticsMethodName')}")
    print(f"  trackingNumber    : {divi_data.get('trackingNumber')}")
    print(f"  taskOrderTotal    : {divi_data.get('taskOrderTotal')}")
    print(f"  taskShippingTotal : {divi_data.get('taskShippingTotal')}")
    print(f"  goodsPaymentTotal : {divi_data.get('goodsPaymentTotal')}")
    print(f"  goodsShippingTotal: {divi_data.get('goodsShippingTotal')}")

    goods_list = divi_data.get('orderGoodsList', [])
    if goods_list:
        print(f"\n  商品明细 ({len(goods_list)} 条):")
        for idx, g in enumerate(goods_list, 1):
            print(f"    [{idx}] {g.get('sellerSku')} | {g.get('productName')} | x{g.get('quantityOrdered')}")
    else:
        print(f"\n  商品明细: 无")

    print(f"\n{'=' * 80}")
    print("✅ 查询完成")
    print(f"{'=' * 80}\n")


if __name__ == '__main__':
    # 直接在这里改要测试的订单号
    ORDER_ID = "111-9386675-2885004"
    test_order(ORDER_ID)
