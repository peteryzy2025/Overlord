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


# ================== 通用 Divi 请求封装（就是你原来的签名逻辑） ==================

PARTNER_CODE = "7607f3480484b48235"
SECRET = "655d0d4e9534f0e37381"
BASE_URL = "http://www.dividiy.com/partner/use/service"


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
    amazon_order_id: str,
    brand_id: int,
    has_logistics: bool = False,
    days: int = 15,
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
    import_time_start, import_time_end = get_default_divi_time_range(days)

    endpoint_path = "/partnerTaskOrder/listPartnerUserOrder"
    data_dict: Dict[str, Any] = {
        "importTimeStart": import_time_start,
        "importTimeEnd": import_time_end,
        "brandIds": [brand_id],
        "amazonOrderId": amazon_order_id,
    }
    if has_logistics:
        data_dict["hasLogistics"] = 1

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

    return {
        "name":         pick("Name", "buyer_name"),
        "phone":        pick("Phone", "phone"),
        "line1":        pick("AddressLine1", "address_line1"),
        "city":         pick("City", "city"),
        "region":       pick("StateOrRegion", "state_or_region"),
        "postal_code":  pick("PostalCode", "postal_code"),
        "email":        order.get("buyer_email", ""),
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
        goods_list.append({
            "orderItemId":     item.get("order_item_id"),
            "quantityOrdered": item.get("quantity_ordered"),
            "title":           item.get("title"),
            "shippingTax":     str(item.get("shipping_tax_amount", "0")),
            "shippingPrice":   str(item.get("shipping_price_amount", "0")),
            "itemPrice":       str(item.get("item_price_amount", "0")),
            "itemTax":         str(item.get("item_tax_amount", "0")),
            "sellerSku":       item.get("seller_sku"),
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

    order_payload = {
        "shippingAddressCity":         address.get("city"),
        "shippingAddressStateOrRegion": address.get("region"),
        "orderGoodsList":              order_goods_list,
        "amazonOrderId":               amazon_order_id,
        "buyerEmail":                  address.get("email"),
        "shippingAddressName":         address.get("name"),
        "buyerPhoneNumber":            address.get("phone"),
        "buyerName":                   address.get("name"),
        "shippingAddressPhone":        address.get("phone"),
        "shippingAddressLine1":        address.get("line1"),
        "shippingAddressCountryCode":  address.get("country_code", "US"),
        "currency":                    currency,
        "shippingAddressPostalCode":   address.get("postal_code"),
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
    return result

