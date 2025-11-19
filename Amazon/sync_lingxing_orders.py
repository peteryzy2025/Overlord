#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import django
import asyncio
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils.dateparse import parse_datetime

# ====== Django 初始化部分（照抄你原来的） ======
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

from Amazon.models import LingXingAmazonShop, AmazonOrders, AmazonOrderItem
from General.models import AmazonShop  # 目前没直接用到，先保留
from Api.lingxing_p.lingxing_jc1 import get_lingxing_orders


def _to_decimal(value, default=None):
    """安全地把金额转成 Decimal"""
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def _to_datetime(value):
    """安全地把字符串转成 datetime"""
    if not value:
        return None
    # 兼容 '2025-11-16 18:36:28' 和 '2025-11-16T18:36:28+00:00' 这种格式
    dt = parse_datetime(value)
    return dt


def sync_amazon_orders(data_list):
    """
    把领星订单数据写入本地 AmazonOrders / AmazonOrderItem
    并绑定 LingXingAmazonShop、AmazonShop
    """
    for item in data_list:
        amazon_order_id = item.get("amazon_order_id")
        if not amazon_order_id:
            print("跳过：没有 amazon_order_id:", item)
            continue

        # ========== 先找对应的领星店铺 / 本地店铺 ==========
        lingxing_shop = None
        amazon_shop = None

        sid = item.get("sid")
        if sid:
            try:
                sid_int = int(sid)
            except (TypeError, ValueError):
                sid_int = None

            if sid_int:
                lingxing_shop = LingXingAmazonShop.objects.filter(sid=sid_int).first()
                if lingxing_shop:
                    amazon_shop = lingxing_shop.amazon_shop

        # ========== 准备订单主表字段 ==========
        defaults = {
            "lingxing_shop": lingxing_shop,
            "amazon_shop": amazon_shop,

            "order_status": item.get("order_status"),
            "order_total_amount": _to_decimal(item.get("order_total_amount")),
            "order_total_currency_code": item.get("order_total_currency_code"),
            "fulfillment_channel": item.get("fulfillment_channel"),
            "sales_channel": item.get("sales_channel"),

            "buyer_email": item.get("buyer_email"),
            "buyer_name": item.get("buyer_name"),
            "phone": item.get("phone"),
            "address": item.get("address"),
            "postal_code": item.get("postal_code"),

            "tracking_number": item.get("tracking_number"),

            "is_return": item.get("is_return") or 0,
            "is_mcf_order": item.get("is_mcf_order") or 0,
            "is_assessed": item.get("is_assessed") or 0,
            "is_replaced_order": item.get("is_replaced_order") or 0,
            "is_replacement_order": item.get("is_replacement_order") or 0,
            "is_return_order": item.get("is_return_order") or 0,
            "refund_amount": _to_decimal(
                item.get("refund_amount", 0),
                default=Decimal("0")
            ),

            # 日期相关
            "purchase_date_local": _to_datetime(item.get("purchase_date_local")),
            "purchase_date_utc": _to_datetime(
                item.get("purchase_date_utc") or item.get("purchase_date")
            ),
            "shipment_date_local": _to_datetime(item.get("shipment_date_local")),
            "shipment_date_utc": _to_datetime(
                item.get("shipment_date_utc") or item.get("shipment_date")
            ),
            "last_update_date_local": _to_datetime(item.get("last_update_date")),
            "last_update_date_utc": _to_datetime(item.get("last_update_date_utc")),
            "gmt_modified": _to_datetime(item.get("gmt_modified")),
            "gmt_modified_utc": _to_datetime(item.get("gmt_modified_utc")),
            "hide_time": _to_datetime(item.get("hide_time")),
        }

        with transaction.atomic():
            order, created = AmazonOrders.objects.update_or_create(
                amazon_order_id=amazon_order_id,
                defaults=defaults
            )

            # print(f"{'新增' if created else '更新'}订单：{order.amazon_order_id}，状态={order.order_status}")

            # ========== 同步明细 item_list ==========
            item_list = item.get("item_list") or []

            # 简单粗暴：先删后插
            AmazonOrderItem.objects.filter(order=order).delete()

            for row in item_list:
                AmazonOrderItem.objects.create(
                    order=order,
                    asin=row.get("asin", ""),
                    seller_sku=row.get("seller_sku") or "",
                    local_sku=row.get("local_sku") or "",
                    local_name=row.get("local_name") or "",
                    order_status=row.get("order_status") or "",
                    quantity_ordered=row.get("quantity_ordered") or 1,
                )

            # if item_list:
            #     print(f"  -> 已写入 {len(item_list)} 条明细")


def main():
    print("开始同步亚马逊订单数据…")

    # 1. 从 LingXingAmazonShop 表中获取需要同步的店铺 sid
    #    这里示例按国家=“美国”筛选，你可以按需要改条件
    sids = list(
        LingXingAmazonShop.objects
        .filter(country="美国")
        .values_list("sid", flat=True)
    )

    if not sids:
        print("没有找到任何国家为“美国”的领星店铺，结束。")
        return

    print(f"共找到 {len(sids)} 个美国店铺 sid")

    # 2. 用异步接口从领星批量拉取订单（内部会自动按 20 个 sid 分组请求）
    # try:
    resp_data = asyncio.run(get_lingxing_orders(sids, days=30))
    # except TypeError:
    #     # 如果你的 get_lingxing_orders 不需要参数，可以退回到不带参数调用
    #     resp_data = asyncio.run(get_lingxing_orders())

    if not resp_data:
        print("接口没有返回任何订单数据，结束。")
        return

    # 3. 写入本地数据库
    sync_amazon_orders(resp_data)
    print("完成同步订单")


if __name__ == "__main__":
    main()
