#!/usr/bin/env python
# -*- coding: utf-8 -*-


import os
import sys
import django

# ========== Django环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

from divi_order_service import query_divi_order, send_wechat_with_retry

# ================== 通用 Divi 请求封装（就是你原来的签名逻辑） ==================

PARTNER_CODE = "7607f3480484b48235"
SECRET = "655d0d4e9534f0e37381"
BASE_URL = "http://www.dividiy.com/partner/use/service"

# 企业微信Webhook URL列表
WECHAT_WEBHOOK_URLS = [
    "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=d910f7a2-bb75-435e-a8ce-777efdab8eab",
    "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=4391c008-ea12-4243-a0aa-72f12b31cb21",
    "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=a4bbf1b1-fb28-42a0-a291-bcf207180d4c",
    "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=f5482538-c667-4525-bab6-ae8334d03548",
    "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=874e31e7-d6d5-4016-b6b3-478ed60a2fc0",
]
exists, orders, resp_json = query_divi_order(amazon_order_id=None, brand_id=None, days=None,
                                             start_time="2025-12-01 01:00:00", end_time="2025-12-01 08:59:59")
mess_list = []
for order in orders:
    meet = False
    if len(order.get("orderGoodsList")) > 1:
        meet = True
    order_goods_list = []
    for order_goods in order.get("orderGoodsList"):
        product_name = order_goods.get("productName")  # 产品名字
        quantity_ordered = order_goods.get("quantityOrdered")  # 订购数量
        order_goods_list.append((product_name, quantity_ordered))
        if quantity_ordered > 1:
            meet = True
    if meet:
        mess_list.append((order.get("amazonOrderId"), order_goods_list))
mess_str = "\n".join([str(item) for item in mess_list])
send_wechat_with_retry(mess_str)
print(mess_list)
