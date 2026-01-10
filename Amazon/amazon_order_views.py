# Amazon/amazon_order_views.py

from django.http import JsonResponse
from django.db.models import Sum, Q
from datetime import datetime
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
import json
import time
from django.utils import timezone

from django.shortcuts import render
from amazon.models import LingXingAmazonShop, AmazonOrders, AmazonOrderItem
from amazon.amazon_views import parse_permissions, determine_filter_type_and_value, get_date_range_from_option,get_shop_ids_by_filter
# DIVI服务导入
from api.divi.divi_order_service import query_divi_order
from amazon.amazon_divi_views import update_divi_order_fields




# ========== 新增辅助函数 ==========

def parse_divi_time(time_str):
    """解析DIVI时间字符串为Django DateTimeField"""
    if not time_str:
        return None
    try:
        dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
        return timezone.make_aware(dt)
    except:
        return None



