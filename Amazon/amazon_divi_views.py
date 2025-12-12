# Amazon/amazon_divi_views.py

import asyncio
from django.http import JsonResponse

from datetime import datetime
from django.utils import timezone

from Api.lingxing.Y_OpenApi import get_api_resp
from Api.divi.divi_order_service import (
    query_divi_order,
    import_order_from_lingxing_to_divi,
    get_divi_brand_id_from_sid,
)
from Amazon.models import AmazonOrders, AmazonOrderItem, LingXingAmazonShop
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

# ✅ 新增：日志模型导入
from django.contrib.auth.decorators import login_required
from General.models import UserOperationLog


def parse_divi_time(time_str):
    """解析DIVI时间字符串为Django DateTimeField"""
    if not time_str:
        return None
    try:
        dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
        return timezone.make_aware(dt)
    except:
        return None


def parse_divi_time(time_str: str) -> Optional[datetime]:
    """解析 DIVI 时间字符串为 datetime"""
    if not time_str:
        return None
    try:
        return datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def parse_divi_amount(amount) -> Optional[Decimal]:
    """解析金额为 Decimal"""
    if amount is None or amount == '':
        return None
    try:
        return Decimal(str(amount))
    except (InvalidOperation, TypeError):
        return None


def update_divi_order_fields(order, divi_order_data):
    """
    更新订单的DIVI字段（包括商品明细）
    """
    # 更新主订单字段
    update_data = {
        'is_exported_to_divi': True,
        'divi_import_time': parse_divi_time(divi_order_data.get('createTime')),
        'divi_payment_time': parse_divi_time(divi_order_data.get('paymentTime')),
        'divi_dispatch_time': parse_divi_time(divi_order_data.get('sendOrderTime')),
        'divi_shipment_time': parse_divi_time(divi_order_data.get('sendGoodsTime')),
        'divi_shipping_amount': parse_divi_amount(divi_order_data.get('goodsShippingTotal')),
        'divi_goods_payment_total': parse_divi_amount(divi_order_data.get('goodsPaymentTotal')),
        'divi_logistics_method': divi_order_data.get('logisticsMethodName'),
        'divi_tracking_number': divi_order_data.get('trackingNumber'),
        'divi_order_status': divi_order_data.get('status'),
    }

    # 审核时间特殊处理（JSON中没有，可能需要从其他来源获取）
    # 如果状态>=3且审核时间为空，可设置当前时间为审核时间
    if divi_order_data.get('status') >= 3 and not order.divi_audit_time:
        update_data['divi_audit_time'] = timezone.now()

    # 使用update批量更新字段
    AmazonOrders.objects.filter(id=order.id).update(**update_data)

    # 更新商品明细
    order_goods_list = divi_order_data.get('orderGoodsList', [])
    for goods in order_goods_list:
        # 根据seller_sku查找或创建商品明细
        item_defaults = {
            'divi_product_name': goods.get('productName'),
            'quantity_ordered': goods.get('quantityOrdered', 1),
        }

        AmazonOrderItem.objects.update_or_create(
            order=order,
            seller_sku=goods.get('sellerSku'),
            defaults=item_defaults
        )

    return True


