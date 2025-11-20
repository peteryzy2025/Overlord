# import json
# from typing import Any, Dict, List, Optional
#
# import asyncio
# import requests
#
# from urllib.parse import quote_plus
#
# from Api.lingxing.Y_OpenApi import get_api_resp
# from Api.lingxing.resp_schema import ResponseResult
#
# from Amazon.models import LingXingAmazonShop
# from General.models import AmazonShop
#
#
# # ================== 通用 Divi 请求封装 ==================
#
# PARTNER_CODE = "7607f3480484b48235"
# SECRET = "655d0d4e9534f0e37381"
# BASE_URL = "http://www.dividiy.com/partner/use/service"
#
#
# def get_divi_api_resp(
#     endpoint_path: str,
#     data_dict: Dict[str, Any],
#     timeout: int = 10,
#     print_if: bool = False,
# ) -> requests.Response:
#     """
#     封装 Divi 请求 + 签名
#     """
#     # 1) 原始 data（不排序）
#     data_json_original = json.dumps(
#         data_dict, ensure_ascii=False, separators=(",", ":")
#     )
#
#     # 2) 按 key 排序，用于签名
#     sorted_items = sorted(data_dict.items(), key=lambda kv: kv[0])
#     sorted_dict = {k: v for k, v in sorted_items}
#     sorted_data_json = json.dumps(
#         sorted_dict, ensure_ascii=False, separators=(",", ":")
#     )
#
#     # 3) 时间戳（毫秒）
#     import time
#     timestamp = int(time.time() * 1000)
#
#     # 4) 待签名字符串
#     to_verify = f"{sorted_data_json}{timestamp}{SECRET}"
#
#     # 5) URL 编码
#     to_verify_encoded = quote_plus(to_verify, encoding="utf-8")
#
#     # 6) MD5 + Base64
#     import hashlib
#     import base64
#
#     md5_obj = hashlib.md5()
#     md5_obj.update(to_verify_encoded.encode("utf-8"))
#     md5_bytes = md5_obj.digest()
#     digest_base64 = base64.b64encode(md5_bytes).decode("utf-8")
#
#     # 7) 构造 payload
#     payload = {
#         "partnerCode": PARTNER_CODE,
#         "timestamp": timestamp,
#         "data": data_json_original,
#         "digest": digest_base64,
#     }
#
#     url = BASE_URL.rstrip("/") + endpoint_path
#     headers = {
#         "Content-Type": "application/json; charset=utf-8",
#     }
#
#     if print_if:
#         print(f"[Divi] 请求 URL: {url}")
#         print(f"[Divi] payload: {payload}")
#
#     resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
#     resp.raise_for_status()
#     return resp
#
#
# # ================== 模型相关：sid → brand_id(divi_shop_id) ==================
#
# def get_divi_brand_id_from_sid(sid: int) -> Optional[int]:
#     """
#     通过 领星 sid 找到本地 AmazonShop，再取 divi_shop_id 作为 Divi 的 brand_id
#     """
#     try:
#         lx_shop = LingXingAmazonShop.objects.select_related("amazon_shop").get(sid=sid)
#     except LingXingAmazonShop.DoesNotExist:
#         return None
#
#     if not lx_shop.amazon_shop:
#         return None
#
#     # General.AmazonShop 中的字段 divi_shop_id 即 Divi 的品牌ID
#     return lx_shop.amazon_shop.divi_shop_id
#
#
# # ================== 数据转换：领星订单 → Divi 所需格式 ==================
#
# def build_address_from_lingxing_order(order: Dict[str, Any]) -> Dict[str, Any]:
#     """
#     从 Y_OpenApi 返回的订单数据中，构造 Divi 需要的 address 字段
#     """
#     shipping_addr_raw = order.get("shipping_address") or ""
#     shipping_addr = {}
#     if shipping_addr_raw:
#         try:
#             shipping_addr = json.loads(shipping_addr_raw)
#         except json.JSONDecodeError:
#             shipping_addr = {}
#
#     def pick(*keys, default=""):
#         """
#         优先从 shipping_addr 取，没有就从 order 取
#         """
#         for k in keys:
#             if k in shipping_addr and shipping_addr.get(k):
#                 return shipping_addr.get(k)
#             if k in order and order.get(k):
#                 return order.get(k)
#         return default
#
#     address: Dict[str, Any] = {
#         "name": pick("Name", "buyer_name"),
#         "phone": pick("Phone", "phone"),
#         "line1": pick("AddressLine1", "address_line1"),
#         "city": pick("City", "city"),
#         "region": pick("StateOrRegion", "state_or_region"),
#         "postal_code": pick("PostalCode", "postal_code"),
#         "email": order.get("buyer_email", ""),
#         "country_code": pick("CountryCode", "country_code", default="US"),
#     }
#     return address
#
#
# def build_goods_from_lingxing_items(
#     item_list: List[Dict[str, Any]]
# ) -> List[Dict[str, Any]]:
#     """
#     领星 item_list → Divi orderGoodsList
#     """
#     goods_list: List[Dict[str, Any]] = []
#
#     for item in item_list:
#         goods = {
#             "orderItemId": item.get("order_item_id"),
#             "quantityOrdered": item.get("quantity_ordered"),
#             "title": item.get("title"),
#             "shippingTax": str(item.get("shipping_tax_amount", "0")),
#             "shippingPrice": str(item.get("shipping_price_amount", "0")),
#             "itemPrice": str(item.get("item_price_amount", "0")),
#             "itemTax": str(item.get("item_tax_amount", "0")),
#             "sellerSku": item.get("seller_sku"),
#         }
#         goods_list.append(goods)
#
#     return goods_list
#
#
# def build_divi_order_data_dict(
#     brand_id: int,
#     address: Dict[str, Any],
#     order_goods_list: List[Dict[str, Any]],
#     amazon_order_id: str,
#     currency: str = "USD",
#     shipping_country_code: str = "US",
# ) -> Dict[str, Any]:
#     """
#     构造 Divi addPartnerUserOrder 所需 data_dict
#     """
#     order = {
#         "shippingAddressCity": address.get("city"),
#         "shippingAddressStateOrRegion": address.get("region"),
#         "orderGoodsList": order_goods_list,
#         "amazonOrderId": amazon_order_id,
#         "buyerEmail": address.get("email"),
#         "shippingAddressName": address.get("name"),
#         "buyerPhoneNumber": address.get("phone"),
#         "buyerName": address.get("name"),
#         "shippingAddressPhone": address.get("phone"),
#         "shippingAddressLine1": address.get("line1"),
#         "shippingAddressCountryCode": shipping_country_code or address.get("country_code") or "US",
#         "currency": currency,
#         "shippingAddressPostalCode": address.get("postal_code"),
#     }
#
#     data_dict = {
#         "orderList": [order],
#         "brandId": brand_id,
#     }
#     return data_dict
#
#
# # ================== Divi 下单函数 ==================
#
# def divi_add_order(
#     brand_id: int,
#     address: Dict[str, Any],
#     order_goods_list: List[Dict[str, Any]],
#     amazon_order_id: str,
#     currency: str = "USD",
#     timeout: int = 10,
#     print_if: bool = False,
# ) -> ResponseResult:
#     """
#     调用 Divi 下单接口
#     """
#     endpoint_path = "/partnerTaskOrder/addPartnerUserOrder"
#
#     data_dict = build_divi_order_data_dict(
#         brand_id=brand_id,
#         address=address,
#         order_goods_list=order_goods_list,
#         amazon_order_id=amazon_order_id,
#         currency=currency,
#         shipping_country_code=address.get("country_code", "US"),
#     )
#
#     resp = get_divi_api_resp(
#         endpoint_path=endpoint_path,
#         data_dict=data_dict,
#         timeout=timeout,
#         print_if=print_if,
#     )
#
#     # 根据你的 ResponseResult 实现调整
#     return ResponseResult(**resp.json())
#
#
# # ================== 主流程：查询领星订单 → Divi 创建订单 ==================
#
# async def create_divi_order_from_lingxing(order_id: str, print_if: bool = False) -> ResponseResult:
#     """
#     整条链路：
#     1. 用 Y_OpenApi 查询领星订单详情（包含 sid、地址、item_list 等）
#     2. 用 sid 在本地表中找到 AmazonShop，再取 divi_shop_id 作为 brand_id
#     3. 拼接地址 address 和 order_goods_list
#     4. 调用 Divi 下单接口
#     """
#
#     # 1) 查询订单详情
#     req_body = {"order_id": order_id}
#     y_resp = await get_api_resp(
#         req_body=req_body,
#         api_path="/erp/sc/data/mws/orderDetail",
#     )
#
#     if not y_resp.data:
#         raise ValueError(f"未找到订单 {order_id} 的详情")
#
#     order = y_resp.data[0]
#
#     # 2) 通过 sid 找 brand_id(divi_shop_id)
#     sid = order.get("sid")
#     if not sid:
#         raise ValueError(f"订单 {order_id} 返回数据中缺少 sid，无法匹配店铺")
#
#     brand_id = get_divi_brand_id_from_sid(sid)
#     if not brand_id:
#         raise ValueError(f"未找到 sid={sid} 对应的 divi_shop_id（brand_id），请检查 LingXingAmazonShop 与 AmazonShop 绑定及 divi_shop_id 是否填写")
#
#     # 3) 拼地址
#     address = build_address_from_lingxing_order(order)
#
#     # 4) 拼商品列表
#     item_list = order.get("item_list") or []
#     if not item_list:
#         raise ValueError(f"订单 {order_id} 的 item_list 为空，无法创建 Divi 订单")
#
#     order_goods_list = build_goods_from_lingxing_items(item_list)
#
#     # 5) 其他字段
#     amazon_order_id = order.get("amazon_order_id", order_id)
#     currency = order.get("currency", "USD")
#
#     # 6) 调用 Divi 下单
#     result = divi_add_order(
#         brand_id=brand_id,
#         address=address,
#         order_goods_list=order_goods_list,
#         amazon_order_id=amazon_order_id,
#         currency=currency,
#         timeout=10,
#         print_if=print_if,
#     )
#
#     return result
#
#
# # ============ 简单测试调用 ============
# if __name__ == "__main__":
#     async def main():
#         res = await create_divi_order_from_lingxing(
#             order_id="113-0126122-3551448",
#             print_if=True,
#         )
#         print("Divi 下单结果：", res)
#
#     asyncio.run(main())
