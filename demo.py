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
from api.divi.divi_d import post_partner_list_partner_user_order
from temu.models import TemuOrder, TemuOrderItem
from datetime import datetime, timedelta
from asgiref.sync import sync_to_async


def get_temu_order_for_divi(global_order_no: str):
    """
    导入divi订单
    :param global_order_no:系统单号
    :return:
    """
    # 获取订单主表
    order = TemuOrder.objects.select_related(
        'temu_shop__project',
        'lingxing_shop__temu_shop__project'
    ).get(global_order_no=global_order_no)

    # 获取订单商品明细
    items = TemuOrderItem.objects.filter(order=order)

    # 解析地址信息
    address_info = order.address_info or {}

    # 构建 orderGoodsList
    order_goods_list = []
    for item in items:
        order_goods_list.append({
            "orderItemId": item.product_no or "",
            "quantityOrdered": item.quantity or 0,
            "title": item.title or "",
            "shippingTax": "0",
            "shippingPrice": "0",
            "itemPrice": str(item.unit_price_amount) if item.unit_price_amount else "0",
            "itemTax": "0",
            "sellerSku": item.msku or ""
        })

    # 构建订单详情
    order_detail = {
        "shippingAddressCity": address_info.get("city", ""),
        "shippingAddressStateOrRegion": address_info.get("state_or_region", ""),
        "orderGoodsList": order_goods_list,
        "amazonOrderId": order.reference_no or "",
        "buyerEmail": "mai@zitu.com",
        "shippingAddressName": "zitu",
        "buyerPhoneNumber": "123456-789",
        "buyerName": "zitusang",
        "shippingAddressPhone": "123456-789",
        "shippingAddressLine1": "1500 Main St",
        "shippingAddressCountryCode": "US",
        "currency": "USD",
        "shippingAddressPostalCode": address_info.get("postal_code", "")
    }

    # 获取 brandId，优先从 temu_shop 获取，如果没有则从 lingxing_shop.temu_shop 获取
    temu_shop = order.temu_shop or (order.lingxing_shop.temu_shop if order.lingxing_shop else None)
    if not temu_shop or not temu_shop.divi_shop_id:
        raise ValueError(f"订单 {global_order_no} 未关联店铺或 divi_shop_id 为空")
    brand_id = temu_shop.divi_shop_id

    # 获取 Project 的 divi 认证信息
    project = temu_shop.project
    if not project or not project.divi_partner_code or not project.divi_secret:
        raise ValueError(f"订单 {global_order_no} 关联的店铺未配置 divi 认证信息")

    # 构建返回结果（brandId 在最外层）
    req_body = {
        "orderList": [order_detail],
        "brandId": brand_id,
    }
    resp = post_partner_list_partner_user_order(req_body=req_body, api_path="/partnerTaskOrder/addPartnerUserOrder",
                                                partner_code=project.divi_partner_code, secret=project.divi_secret)
    print(resp.text)
    if resp.json().get("code") != 200:
        raise ValueError(f"订单 {global_order_no} 同步到 Divi 失败，code={resp.json().get('code')}, message={resp.json().get('message')}")



async def check_temu_order_to_divi(global_order_no: str, pdf: bool = False, status=None):
    """
    检查 Temu 订单是否已经同步到 Divi，返回 True/False
    :param global_order_no: 系统单号
    :param pdf: 是否有面单
    :param status: 状态列表(0：订单取消，1：未付货款，2：未审核，3：排单中，4：生产中，5：发货 )
    :return:True/False
    """
    # 获取订单主表
    if status is None:
        status = [0, 1, 2, 3, 4, 5]
    
    @sync_to_async
    def get_order():
        return TemuOrder.objects.select_related(
            'temu_shop__project',
            'lingxing_shop__temu_shop__project'
        ).get(global_order_no=global_order_no)
    
    try:
        order = await get_order()
    except TemuOrder.DoesNotExist:
        raise ValueError(f"订单 {global_order_no} 不存在")

    # 获取 reference_no
    reference_no = order.reference_no

    # 获取 temu_shop 和 divi_shop_id
    temu_shop = order.temu_shop or (order.lingxing_shop.temu_shop if order.lingxing_shop else None)
    if not temu_shop:
        raise ValueError(f"订单 {global_order_no} 未关联店铺")
    divi_shop_id = temu_shop.divi_shop_id

    # 获取 Project 的 divi 认证信息
    project = temu_shop.project
    if not project or not project.divi_partner_code or not project.divi_secret:
        raise ValueError(f"订单 {global_order_no} 关联的店铺未配置 divi 认证信息")

    start_time = (datetime.now() - timedelta(days=15)).replace(hour=0, minute=0, second=0, microsecond=0)
    end_time = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0)
    req_body = {
        "importTimeStart": start_time.strftime("%Y-%m-%d %H:%M:%S"),
        "importTimeEnd": end_time.strftime("%Y-%m-%d %H:%M:%S"),
        "brandIds": [divi_shop_id],
        "status": status,
        "amazonOrderId": reference_no,
    }
    if pdf:
        req_body["hasLogistics"] = 1
    resp = post_partner_list_partner_user_order(req_body=req_body, api_path="/partnerTaskOrder/listPartnerUserOrder",
                                                partner_code=project.divi_partner_code, secret=project.divi_secret)
    j = resp.json()
    if j.get("code") != 200:
        print(f"查询失败，code={j.get('code')}, message={j.get('message')}")
        return False
    for divi_order in j.get("data", []):
        if divi_order.get("amazonOrderId") == reference_no:
            # 更新 TemuOrder 的 DIVI 字段
            from datetime import datetime as dt
            
            # 时间字符串转 datetime
            create_time = divi_order.get("createTime")
            payment_time = divi_order.get("paymentTime")
            send_order_time = divi_order.get("sendOrderTime")
            send_goods_time = divi_order.get("sendGoodsTime")
            
            order.divi_import_time = dt.strptime(create_time, "%Y-%m-%d %H:%M:%S") if create_time else None
            order.divi_payment_time = dt.strptime(payment_time, "%Y-%m-%d %H:%M:%S") if payment_time else None
            order.divi_dispatch_time = dt.strptime(send_order_time, "%Y-%m-%d %H:%M:%S") if send_order_time else None
            order.divi_shipment_time = dt.strptime(send_goods_time, "%Y-%m-%d %H:%M:%S") if send_goods_time else None
            
            # 其他字段
            order.divi_logistics_method = divi_order.get("logisticsMethodName")
            order.divi_tracking_number = divi_order.get("trackingNumber")
            order.divi_shipping_amount = divi_order.get("taskShippingTotal")
            order.divi_goods_payment_total = divi_order.get("goodsPaymentTotal")
            order.divi_order_status = divi_order.get("status")
            
            @sync_to_async
            def save_order():
                order.save(update_fields=[
                    'divi_import_time', 'divi_payment_time', 'divi_dispatch_time', 'divi_shipment_time',
                    'divi_logistics_method', 'divi_tracking_number', 'divi_shipping_amount',
                    'divi_goods_payment_total', 'divi_order_status'
                ])
            
            await save_order()
            return True
    return False


if __name__ == '__main__':
    result = get_temu_order_for_divi("103682700755929727")
    t = check_temu_order_to_divi("103682700755929727", pdf=False, status=[0, 1, 2, 3, 4, 5])
    print(t)
