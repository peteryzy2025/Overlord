#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys
import django

# ========== Django环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(CURRENT_DIR))
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

from divi_order_service import query_divi_order, send_wechat_with_retry

from datetime import datetime, timedelta
from typing import Tuple, Optional
def get_previous_hour_range(current_time: Optional[datetime] = None) -> Tuple[str, str]:
    """
    获取前一个小时的时间范围

    :param current_time: 当前时间，默认为系统当前时间
    :return: (开始时间, 结束时间) 字符串元组，格式为 YYYY-MM-DD HH:MM:SS
    """
    # 如果没有传入时间，则获取当前系统时间
    if current_time is None:
        current_time = datetime.now()

    # 减去1小时，得到前一个小时的时间点
    prev_hour = current_time - timedelta(hours=1)

    # 获取前一个小时开始时间（00分00秒）
    start_time = prev_hour.replace(minute=0, second=0, microsecond=0)

    # 获取前一个小时结束时间（59分59秒）
    end_time = prev_hour.replace(minute=59, second=59, microsecond=0)

    # 格式化为字符串
    return (
        start_time.strftime("%Y-%m-%d %H:%M:%S"),
        end_time.strftime("%Y-%m-%d %H:%M:%S")
    )
s,e = get_previous_hour_range()
print(s,e)
exists, orders, resp_json = query_divi_order(amazon_order_id=None, brand_id=None, days=None,
                                             start_time=s, end_time=e)
mess_list = []
for order in orders:
    meet = False
    if len(order.get("orderGoodsList")) > 1:
        meet = True
    for order_goods in order.get("orderGoodsList"):
        product_name = order_goods.get("productName")  # 产品名字
        quantity_ordered = order_goods.get("quantityOrdered")  # 订购数量
        if quantity_ordered > 1:
            meet = True
    if meet:
        mess_list.append((order.get("amazonOrderId")))
mess_str = " ".join(list(mess_list))
send_wechat_with_retry(mess_str)
print(mess_str)
