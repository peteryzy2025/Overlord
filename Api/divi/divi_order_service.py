import asyncio
import time
import json
import hashlib
import base64

from urllib.parse import quote_plus
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests
from Api.lingxing.Y_OpenApi import get_api_resp
from Api.lingxing.resp_schema import ResponseResult

from Amazon.models import LingXingAmazonShop
from General.models import AmazonShop
import random

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


def check_and_send_wechat_notification(order_goods_list: list, amazon_order_id: str) -> None:
    """
    识别订单类型并发送企业微信通知（详细版）

    :param order_goods_list: DIVI商品列表
    :param amazon_order_id: 亚马逊订单号
    """
    # 情况1：多SKU订单
    if len(order_goods_list) > 1:
        message = f"订单号：{amazon_order_id}\n类型：多SKU订单\n数量：{len(order_goods_list)}"
        # 追加每个商品的详细信息
        for item in order_goods_list:
            sku = item.get("sellerSku", "")
            title = item.get("title", "")
            quantity = item.get("quantityOrdered", 1)
            message += f"\nsku-title:{sku}-{title}-{quantity}"

        send_wechat_with_retry(message)
        return

    # 情况2：单SKU但数量>1
    if len(order_goods_list) == 1:
        item = order_goods_list[0]
        quantity = item.get("quantityOrdered", 1)
        if quantity > 1:
            sku = item.get("sellerSku", "")
            title = item.get("title", "")

            message = f"订单号：{amazon_order_id}\n类型：单SKU多数量\n数量：{quantity}"
            message += f"\nsku-title:{sku}-{title}-{quantity}"

            send_wechat_with_retry(message)
            return

    # 情况3：单SKU数量为1（不发送通知）
    print(f"📋 订单 {amazon_order_id} 为普通单SKU订单，无需通知")


def send_wechat_with_retry(message: str) -> None:
    """
    发送企业微信消息（无限重试直到成功）

    :param message: 要发送的文本内容
    """
    attempt_count = 0

    while True:
        attempt_count += 1
        # 随机选择一个URL
        webhook_url = random.choice(WECHAT_WEBHOOK_URLS)

        try:
            payload = {
                "msgtype": "text",
                "text": {"content": message}
            }

            response = requests.post(
                webhook_url,
                json=payload,
                timeout=5,
                headers={"Content-Type": "application/json"}
            )

            # 检查HTTP状态码
            if response.status_code == 200:
                result = response.json()
                # 检查企业微信返回的errcode
                if result.get("errcode") == 0:
                    print(f"✅ 消息发送成功（第{attempt_count}次尝试）")
                    return  # 成功则退出循环
                else:
                    print(f"❌ 消息发送失败：errcode={result.get('errcode')}, errmsg={result.get('errmsg')}")
            else:
                print(f"❌ HTTP请求失败：状态码 {response.status_code}")

        except requests.exceptions.RequestException as e:
            print(f"❌ 请求异常：{str(e)}")

        # 失败时等待1秒后重试
        print(f"⏳ 等待1秒后重试...（当前已尝试{attempt_count}次）")
        time.sleep(1)


def get_divi_api_resp(
        endpoint_path: str,
        data_dict: Dict[str, Any],
        timeout: int = 10,
        print_if: bool = False,
) -> requests.Response:
    """
    Divi 通用请求函数（带签名）
    """
    # 1) 原始 JSON（不排序）→ payload.data
    data_json_original = json.dumps(
        data_dict, ensure_ascii=False, separators=(",", ":")
    )

    # 2) 排序 JSON（签名用）
    sorted_items = sorted(data_dict.items(), key=lambda kv: kv[0])
    sorted_dict = {k: v for k, v in sorted_items}
    sorted_data_json = json.dumps(
        sorted_dict, ensure_ascii=False, separators=(",", ":")
    )

    # 3) 时间戳（毫秒）
    timestamp = int(time.time() * 1000)

    # 4) 签名原文
    to_verify = f"{sorted_data_json}{timestamp}{SECRET}"

    # 5) URL 编码
    to_verify_encoded = quote_plus(to_verify, encoding="utf-8")

    # 6) MD5 → Base64
    md5_obj = hashlib.md5()
    md5_obj.update(to_verify_encoded.encode("utf-8"))
    md5_bytes = md5_obj.digest()
    digest_base64 = base64.b64encode(md5_bytes).decode("utf-8")

    # 7) payload
    payload = {
        "partnerCode": PARTNER_CODE,
        "timestamp": timestamp,
        "data": data_json_original,
        "digest": digest_base64,
    }

    url = BASE_URL.rstrip("/") + endpoint_path
    headers = {"Content-Type": "application/json; charset=utf-8"}

    if print_if:
        print(f"[Divi] URL: {url}")
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp


# ================== 时间范围工具（默认前 15 天） ==================

def get_default_divi_time_range(days: int = 15) -> Tuple[str, str]:
    """
    默认查询时间：前 15 天的 00:00:00 到今天的 23:59:59
    """
    today = datetime.now()
    start = (today - timedelta(days=days)).strftime("%Y-%m-%d 00:00:00")
    end = today.strftime("%Y-%m-%d 23:59:59")
    return start, end


# ================== 1. 查询 Divi 订单 ==================

def query_divi_order(
        amazon_order_id: str | None,
        brand_id: int | None,
        has_logistics: bool = False,
        days: int | None = 15,
        start_time: str = "",
        end_time: str = "",
        timeout: int = 10,
        print_if: bool = False,
) -> Tuple[bool, List[Dict[str, Any]], Dict[str, Any]]:
    """
    查询 Divi 是否存在指定订单（同一店铺维度），以及是否有面单（has_logistics 控制）

    :param amazon_order_id: 亚马逊订单号
    :param brand_id: Divi 店铺 ID（brandId，即 divi_shop_id）
    :param has_logistics: True 时带 hasLogistics=1（查询有面单的订单）
    :return: (exists, orders, raw_json)
    """
    if days is None:
        import_time_start, import_time_end = start_time, end_time
    else:
        import_time_start, import_time_end = get_default_divi_time_range(days)

    endpoint_path = "/partnerTaskOrder/listPartnerUserOrder"
    data_dict: Dict[str, Any] = {
        "importTimeStart": import_time_start,
        "importTimeEnd": import_time_end,
    }
    if brand_id:
        data_dict["brandId"] = [brand_id]
    if amazon_order_id:
        data_dict["amazonOrderId"] = amazon_order_id
    if has_logistics:
        data_dict["hasLogistics"] = 1
    print(data_dict)
    resp = get_divi_api_resp(
        endpoint_path=endpoint_path,
        data_dict=data_dict,
        timeout=timeout,
        print_if=print_if,
    )
    resp_json = resp.json()

    # 兼容几种结构：data 是 list / data.list / data.rows
    orders: List[Dict[str, Any]] = []
    data = resp_json.get("data")
    if isinstance(data, list):
        orders = data
    elif isinstance(data, dict):
        if isinstance(data.get("list"), list):
            orders = data["list"]
        elif isinstance(data.get("rows"), list):
            orders = data["rows"]

    exists = len(orders) > 0
    return exists, orders, resp_json


# ================== 2. sid -> brandId(divi_shop_id) ==================

def get_divi_brand_id_from_sid(sid: int) -> Optional[int]:
    """
    通过领星店铺 sid -> 找到本地 AmazonShop -> 拿 divi_shop_id 作为 Divi brandId
    """
    try:
        lx_shop = LingXingAmazonShop.objects.select_related("amazon_shop").get(sid=sid)
    except LingXingAmazonShop.DoesNotExist:
        return None

    if not lx_shop.amazon_shop:
        return None

    return lx_shop.amazon_shop.divi_shop_id


# ================== 3. 地址构建 ==================

def build_address_from_lingxing_order(order: Dict[str, Any]) -> Dict[str, Any]:
    """
    领星订单结构 -> Divi 需要的 address 结构
    """
    shipping_addr_raw = order.get("shipping_address") or ""
    shipping_addr: Dict[str, Any] = {}
    if shipping_addr_raw:
        try:
            shipping_addr = json.loads(shipping_addr_raw)
        except json.JSONDecodeError:
            shipping_addr = {}

    def pick(*keys, default=""):
        for k in keys:
            if k in shipping_addr and shipping_addr.get(k):
                return shipping_addr.get(k)
            if k in order and order.get(k):
                return order.get(k)
        return default

    raw_phone = pick("Phone", "phone")
    clean_phone = raw_phone.split('ext.')[0].strip() if raw_phone else ''
    return {
        "name": pick("Name", "buyer_name"),
        "phone": clean_phone,
        "line1": pick("AddressLine1", "address_line1"),
        "city": pick("City", "city"),
        "region": pick("StateOrRegion", "state_or_region"),
        "postal_code": pick("PostalCode", "postal_code"),
        "email": order.get("buyer_email", ""),
        "country_code": pick("CountryCode", "country_code", default="US"),
    }


# ================== 4. 商品列表构建 ==================

def build_goods_from_lingxing_items(
        item_list: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    领星 item_list -> Divi orderGoodsList（列表）
    """
    goods_list: List[Dict[str, Any]] = []

    for item in item_list:
        quantity_raw = item.get("quantity_ordered")
        quantity = quantity_raw if quantity_raw is not None else 0
        # 跳过数量为 0 的商品
        if quantity == 0:
            sku = item.get("seller_sku", "未知")
            print(f"⚠️ 跳过商品 (sku: {sku})，数量为0")
            continue

        goods_list.append({
            "orderItemId": item.get("order_item_id"),
            "quantityOrdered": item.get("quantity_ordered"),
            "title": item.get("title").replace("*", "x"),
            "shippingTax": str(item.get("shipping_tax_amount", "0")),
            "shippingPrice": str(item.get("shipping_price_amount", "0")),
            "itemPrice": str(item.get("item_price_amount", "0")),
            "itemTax": str(item.get("item_tax_amount", "0")),
            "sellerSku": item.get("seller_sku"),
        })

    return goods_list


# ================== 5. Divi 下单 ==================

def divi_add_order(
        brand_id: int,
        address: Dict[str, Any],
        order_goods_list: List[Dict[str, Any]],
        amazon_order_id: str,
        currency: str = "USD",
        timeout: int = 10,
        print_if: bool = False,
) -> ResponseResult:
    """
    调用 Divi 下单接口 /partnerTaskOrder/addPartnerUserOrder
    """

    endpoint_path = "/partnerTaskOrder/addPartnerUserOrder"
    if address.get("phone") == "":
        address["phone"] = "1234567890"
    order_payload = {
        "shippingAddressCity": address.get("city"),
        "shippingAddressStateOrRegion": address.get("region"),
        "orderGoodsList": order_goods_list,
        "amazonOrderId": amazon_order_id,
        "buyerEmail": address.get("email"),
        "shippingAddressName": address.get("name"),
        "buyerPhoneNumber": address.get("phone"),
        "buyerName": address.get("name"),
        "shippingAddressPhone": address.get("phone"),
        "shippingAddressLine1": address.get("line1"),
        "shippingAddressCountryCode": address.get("country_code", "US"),
        "currency": currency,
        "shippingAddressPostalCode": address.get("postal_code"),
    }

    data_dict = {
        "orderList": [order_payload],
        "brandId": brand_id,
    }

    resp = get_divi_api_resp(
        endpoint_path=endpoint_path,
        data_dict=data_dict,
        timeout=timeout,
        print_if=print_if,
    )

    return ResponseResult(**resp.json())


# ================== 6. 导入订单：从领星 -> Divi ==================

def import_order_from_lingxing_to_divi(
        order_id: str,
        print_if: bool = False,
) -> ResponseResult:
    """
    导入订单（去领星获取数据并在 Divi 创建订单）
    同步版本：内部用 asyncio.run 调用领星的 get_api_resp
    """
    # 1) 从领星获取订单详情（这里是 async 调用，外面同步，所以用 asyncio.run）
    req_body = {"order_id": order_id}
    y_resp = asyncio.run(
        get_api_resp(
            req_body=req_body,
            api_path="/erp/sc/data/mws/orderDetail",
        )
    )
    if y_resp and y_resp.data and len(y_resp.data) > 0:
        lx_order_data = y_resp.data[0]
        print(f"🔄 准备用领星数据更新本地订单...")

        try:
            from Amazon.models import LingXingAmazonShop, AmazonOrders, AmazonOrderItem

            sid = lx_order_data.get('sid')
            amazon_order_id = lx_order_data.get('amazon_order_id')

            if sid and amazon_order_id:
                # 查找领星店铺
                lingxing_shop = LingXingAmazonShop.objects.filter(sid=sid).first()
                if lingxing_shop:
                    # 查找本地订单
                    order = AmazonOrders.objects.filter(
                        lingxing_shop=lingxing_shop,
                        amazon_order_id=amazon_order_id
                    ).first()

                    if order:
                        update_fields = []

                        # 更新买家信息
                        if lx_order_data.get('buyer_name'):
                            order.buyer_name = lx_order_data['buyer_name']
                            update_fields.append('buyer_name')
                        if lx_order_data.get('buyer_email'):
                            order.buyer_email = lx_order_data['buyer_email']
                            update_fields.append('buyer_email')
                        if phone_raw := lx_order_data.get('phone'):
                            order.phone = phone_raw.split('ext.')[0].strip()
                            update_fields.append('phone')
                        if lx_order_data.get('shipping_address'):
                            order.address = str(lx_order_data['shipping_address'])
                            update_fields.append('address')
                        if lx_order_data.get('postal_code'):
                            order.postal_code = lx_order_data['postal_code']
                            update_fields.append('postal_code')

                        # 保存订单更新
                        if update_fields:
                            order.save(update_fields=update_fields)
                            print(f"   ✅ 更新订单主表 {len(update_fields)} 个字段: {update_fields}")

                        # 更新商品明细
                        item_list = lx_order_data.get('item_list', [])
                        for item_data in item_list:
                            seller_sku = item_data.get('seller_sku')
                            if seller_sku:
                                defaults = {
                                    'quantity_ordered': item_data.get('quantity_ordered', 1)
                                }
                                if item_data.get('title'):
                                    defaults['local_name'] = item_data['title']
                                if item_data.get('asin'):
                                    defaults['asin'] = item_data['asin']

                                AmazonOrderItem.objects.update_or_create(
                                    order=order,
                                    seller_sku=seller_sku,
                                    defaults=defaults
                                )
                        print(f"   ✅ 更新/创建 {len(item_list)} 个商品明细")
                    else:
                        print(f"⚠️ 未找到本地订单 {amazon_order_id}，跳过更新")
                else:
                    print(f"⚠️ 未找到sid={sid}的领星店铺，跳过更新")
        except Exception as e:
            print(f"⚠️ 更新本地订单时出错（不影响后续流程）: {str(e)}")
            # 不抛出异常，让后续流程继续执行

    # ==================== 更新逻辑结束 ====================
    if not y_resp.data:
        raise ValueError(f"未找到订单 {order_id} 的领星详情")

    order = y_resp.data[0]

    # 2) 通过 sid 找 brandId（这里已经是同步代码，可以安全用 ORM）
    sid = order.get("sid")
    if not sid:
        raise ValueError(f"订单 {order_id} 缺少 sid，无法匹配店铺")

    brand_id = get_divi_brand_id_from_sid(sid)
    if not brand_id:
        raise ValueError(f"sid={sid} 未配置 divi_shop_id（brandId）")

    # 3) 构造地址
    address = build_address_from_lingxing_order(order)

    # 4) 构造商品列表
    item_list = order.get("item_list") or []
    if not item_list:
        raise ValueError(f"订单 {order_id} 的 item_list 为空，无法导入 Divi")
    for item in item_list:
        title = item.get("title", "").strip()
        if not title:
            raise ValueError(
                f"订单 {order_id} 中商品 (sku: {item.get('seller_sku')}) 的 title 为空，禁止导入"
            )
    order_goods_list = build_goods_from_lingxing_items(item_list)

    # 5) 其他字段
    amazon_order_id = order.get("amazon_order_id", order_id)
    currency = order.get("currency", "USD")

    # 6) Divi 下单（纯同步）
    result = divi_add_order(
        brand_id=brand_id,
        address=address,
        order_goods_list=order_goods_list,
        amazon_order_id=amazon_order_id,
        currency=currency,
        timeout=10,
        print_if=print_if,
    )
    # 不用这个了
    # try:
    #     if result and getattr(result, 'code', 200) == 200:
    #         # 只有导单成功才发送通知
    #         check_and_send_wechat_notification(order_goods_list, amazon_order_id)
    #     else:
    #         print(f"⚠️ 订单 {amazon_order_id} 导单未成功，跳过通知发送")
    # except Exception as e:
    #     # 即使消息发送失败，也不影响主流程
    #     print(f"⚠️ 消息发送异常（不影响导单结果）：{str(e)}")
    return result
