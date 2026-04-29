# temu导单发货集成


import os
import sys
import time

import django

# ====== Django 初始化（保持不变） ======
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

from api.lingxing.Y_OpenApi import get_api_resp
import datetime
from typing import List, Dict, Any
import asyncio
from decimal import Decimal, InvalidOperation
from asgiref.sync import sync_to_async
import requests
from api.divi.divi_d import post_partner_list_partner_user_order
from temu.models import TemuOrder, TemuOrderItem
from datetime import datetime, timedelta, timezone, date, time as dt_time

def _to_decimal(value, default=Decimal('0.00')):
    """安全地把字符串金额转成 Decimal"""
    if value in (None, "", "0.00", "-￥0.00", "￥0.00"):
        return default
    try:
        if isinstance(value, str):
            value = value.replace('￥', '').replace('$', '').replace('€', '').strip()
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        print(f"警告: 金额转换失败: {value}")
        return default


def _timestamp_to_datetime(ts):
    """将 Unix 时间戳转换为 UTC datetime"""
    if not ts or ts == 0:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except (ValueError, TypeError):
        print(f"警告: 时间戳转换失败: {ts}")
        return None


async def get_lx_temu_shops(app_id: str = None, app_secret: str = None):
    req_body = {
        "offset": 0,
        "length": 200,
        "platform_code": [10022, 10024],  # Temu全托管,Temu半托管
        "is_sync": 1,
        "status": 1
    }

    resp = await get_api_resp(
        req_body,
        api_path="/pb/mp/shop/v2/getSellerList",
        app_id=app_id,
        app_secret=app_secret
    )
    # print(resp)
    return (resp.data or {}).get("list") or []

async def get_temu_order_for_divi(global_order_no: str):
    """
    导入divi订单
    :param global_order_no:系统单号
    :return:
    """
    # 获取订单主表
    @sync_to_async
    def get_order():
        return TemuOrder.objects.select_related(
            'temu_shop__project',
            'lingxing_shop__temu_shop__project'
        ).get(global_order_no=global_order_no)
    
    order = await get_order()

    # 获取订单商品明细
    @sync_to_async
    def get_items():
        return list(TemuOrderItem.objects.filter(order=order))
    
    items = await get_items()

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
    print(req_body)
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
            order.divi_if_order = True  # 标记为DIVI订单

            @sync_to_async
            def save_order():
                order.save(update_fields=[
                    'divi_import_time', 'divi_payment_time', 'divi_dispatch_time', 'divi_shipment_time',
                    'divi_logistics_method', 'divi_tracking_number', 'divi_shipping_amount',
                    'divi_goods_payment_total', 'divi_order_status', 'divi_if_order'
                ])

            await save_order()
            return True
    
    # 遍历完没有找到订单，设置 divi_if_order 为 False
    order.divi_if_order = False
    @sync_to_async
    def save_order_not_found():
        order.save(update_fields=['divi_if_order'])
    await save_order_not_found()
    return False
async def get_lx_temu_orders(
    store_ids: List[str],
    day: int = 3,
    shop_map: Dict[str, str] = None,
    app_id: str = None,
    app_secret: str = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    按 store_id（一次只传一个给 API）拉取领星/Temu 订单（带分页），时间范围由 day 决定：
      start_time = (today - day days) 00:00:00 (UTC)
      end_time   = today 23:59:59 (UTC)

    Args:
        store_ids: list of store_id strings (可以传多个，本函数会为每个店铺单独请求)
        day: 向前的天数窗口（例如 day=3 则从 3 天前 00:00:00 到 今天 23:59:59）
        shop_map: {store_id: shop_name, ...} 店铺名称映射，用于日志显示
        app_id: 领星AppID（可选）
        app_secret: 领星AppSecret（可选）

    Returns:
        dict: { store_id: [order_dict, ...], ... }
    """
    results: Dict[str, List[Dict[str, Any]]] = {}
    shop_map = shop_map or {}  # 如果没有传入，使用空字典

    # 以 UTC 计算 start/end
    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
    today_utc_date = now_utc.date()
    # start = (today - day) at 00:00:00  (例如 day=3 -> 3 days ago 00:00:00)
    start_date = today_utc_date - timedelta(days=day)
    start_dt = datetime.combine(start_date, dt_time(0, 0, 0), tzinfo=timezone.utc)
    # end = today 23:59:59
    end_dt = datetime.combine(today_utc_date, dt_time(23, 59, 59), tzinfo=timezone.utc)

    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())

    LENGTH = 500

    for store_id in store_ids:
        shop_name = shop_map.get(store_id, '未知店铺')
        store_results = []
        offset = 0
        request_count = 0  # 统计请求次数

        while True:
            request_count += 1
            req_body = {
                "start_time": start_ts,
                "end_time": end_ts,
                "date_type": "global_purchase_time",
                "offset": offset,
                "length": LENGTH,
                "store_id": [store_id],
                "platform_code": [10024],
            }

            try:
                resp = await get_api_resp(
                    req_body,
                    api_path="/pb/mp/order/v2/list",
                    app_id=app_id,
                    app_secret=app_secret,
                )
            except Exception as e:
                # 捕获网络/解析异常，记录并跳出当前店铺的循环（或你可以改为重试）
                print(f"[get_lingxing_orders] Exception fetching store {store_id}({shop_name}), offset {offset}: {e}")
                break

            # 兼容原始函数里 resp.data.get("list") 的结构
            data_list = []
            try:
                # 有时 resp.data 可能不存在或为 None，做安全检查
                if resp is None:
                    data_list = []
                else:
                    _data = getattr(resp, "data", None) or resp
                    # 常见结构： resp.data.get("list")
                    if isinstance(_data, dict):
                        data_list = _data.get("list") or []
                    else:
                        # 如果 resp 直接就是对象并有 .data
                        _inner = getattr(resp, "data", None)
                        if isinstance(_inner, dict):
                            data_list = _inner.get("list") or []
                        else:
                            data_list = []
            except Exception:
                data_list = []

            print(
                f"[API请求] {shop_name}(ID:{store_id}), 第{request_count}次请求, offset={offset}, 返回{len(data_list)}条数据")

            if not data_list:
                # 没有数据则结束分页
                break

            store_results.extend(data_list)

            # 如果返回结果少于 PAGE 长度，则表示最后一页
            if len(data_list) < LENGTH:
                break

            # 否则继续下一页
            offset += LENGTH

            # 如果你希望在分页间做短暂sleep以防限速，取消下面注释（需要 asyncio）
            # await asyncio.sleep(0.1)

        print(f"[店铺汇总] {shop_name}(ID:{store_id}), 共请求{request_count}次, 获取{len(store_results)}条订单")
        results[store_id] = store_results

    return results


async def get_lx_temu_orders_list(platform_order_nos: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """
    通过平台订单号列表获取订单详情（一次最多500个订单号）
    
    Args:
        platform_order_nos: 平台订单号列表
        
    Returns:
        dict: { store_id: [order_dict, ...], ... }
    """
    req_body = {
        "platform_order_nos": platform_order_nos,
        "offset": 0,
        "length": 500,
        "platform_code": ["10024"]
    }
    # print(req_body)
    resp = await get_api_resp(req_body, api_path="/pb/mp/order/v2/list")
    # 提取订单列表
    order_list = []
    try:
        if resp is not None:
            _data = getattr(resp, "data", None) or resp
            if isinstance(_data, dict):
                order_list = _data.get("list") or []
    except Exception:
        order_list = []
    # print(resp)
    
    # 检测 IP 白名单错误
    if resp is not None:
        resp_code = getattr(resp, "code", None)
        resp_message = getattr(resp, "message", "") or ""
        if resp_code == 3001002 or "ip not permit" in resp_message.lower():
            # 提取IP地址
            import re
            ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', resp_message)
            current_ip = ip_match.group(1) if ip_match else "未知"
            raise Exception(f"当前IP【{current_ip}】不在白名单中，请稍等几分钟")
    
    # 按 store_id 分组
    results: Dict[str, List[Dict[str, Any]]] = {}
    for order in order_list:
        store_id = order.get("store_id")
        if store_id:
            if store_id not in results:
                results[store_id] = []
            results[store_id].append(order)
    return results


async def refresh_temu_order_by_sn(global_order_no: str):
    """
    通过系统单号刷新订单数据
    
    流程：
    1. 从数据库找到该订单的平台单号（platform_order_no）
    2. 调用 get_lx_temu_orders_list 获取最新数据
    3. 调用 save_temu_orders_data 保存到数据库
    
    Args:
        global_order_no: 系统单号（如 '103680050723201224'）
        
    Returns:
        bool: 是否成功刷新
    """
    # 延迟导入 Django 模型
    from temu.models import TemuOrder
    from asgiref.sync import sync_to_async

    @sync_to_async
    def get_platform_order_no(sn):
        try:
            order = TemuOrder.objects.get(global_order_no=sn)
            # 优先从 reference_no 获取平台单号，这是存储 platform_order_no 的字段
            return order.reference_no
        except TemuOrder.DoesNotExist:
            return None

    print(f"开始刷新订单: {global_order_no}")

    # 1. 获取平台单号
    platform_order_no = await get_platform_order_no(global_order_no)
    if not platform_order_no:
        print(f"错误: 未找到系统单号 {global_order_no} 对应的订单或平台单号")
        return False

    print(f"找到平台单号: {platform_order_no}")

    # 2. 调用 API 获取最新数据
    results = await get_lx_temu_orders_list([platform_order_no])
    if not results:
        print(f"警告: API 未返回数据")
        return False

    # 3. 保存数据
    await save_temu_orders_data(results)
    print(f"订单 {global_order_no} 刷新完成")
    return True


async def temu_address_decrypt(decrypt_sn_list: List[str]):
    """
        批量TEMU地址解密 系统单号列表 目前没使用了
    :param decrypt_sn_list:
    :return:
    """
    req_body = {
        "decryptSnList": decrypt_sn_list,
    }
    resp = await get_api_resp(req_body, api_path="/basicOpen/temu/temuAddressDecrypt")
    # print(resp)
    if resp.message == "操作成功":
        return True
    else:
        print("警告！警告！地址解密失败！")
        return False


async def save_temu_orders_data(data_dict: Dict[str, List[Dict[str, Any]]]):
    """
    将 Temu 订单数据批量写入数据库（新建或更新）
    
    Args:
        data_dict: {store_id: [order_dict, ...], ...}
    """
    # 延迟导入 Django 模型
    from django.db import transaction
    from temu.models import LingXingTemuShop, TemuOrder, TemuOrderItem

    # 将同步 ORM 操作包装为 async
    @sync_to_async
    def get_shops(store_ids):
        shop_qs = LingXingTemuShop.objects.filter(store_id__in=store_ids)
        return {shop.store_id: shop for shop in shop_qs}

    @sync_to_async
    def save_order_with_items(global_order_no, defaults, item_list, lingxing_shop):
        with transaction.atomic():
            # 更新或创建订单主表
            order, created = TemuOrder.objects.update_or_create(
                global_order_no=global_order_no,
                defaults=defaults
            )

            # 处理订单明细
            if item_list:
                TemuOrderItem.objects.filter(order=order).delete()
                items_to_create = []
                seen_global_item_nos = set()

                for row in item_list:
                    global_item_no = row.get('global_item_no') or row.get('globalItemNo')

                    if not global_item_no or global_item_no in seen_global_item_nos:
                        continue

                    seen_global_item_nos.add(global_item_no)
                    # 如果 msku 为空，用订单号 global_order_no 填充
                    msku_value = row.get('msku') or global_order_no
                    items_to_create.append(
                        TemuOrderItem(
                            order=order,
                            global_item_no=global_item_no,
                            platform_order_no=row.get('platform_order_no'),
                            order_item_no=row.get('order_item_no'),
                            item_from_name=row.get('item_from_name'),
                            msku=msku_value,
                            local_sku=row.get('local_sku'),
                            product_no=row.get('product_no'),
                            title=row.get('title'),
                            variant_attr=row.get('variant_attr'),
                            unit_price_amount=_to_decimal(row.get('unit_price_amount')),
                            item_price_amount=_to_decimal(row.get('item_price_amount')),
                            quantity=row.get('quantity', 0),
                            platform_status=row.get('platform_status'),
                            type=row.get('type'),
                            data_json=row.get('data_json'),
                            item_custom_fields=row.get('item_custom_fields'),
                            is_delete=row.get('is_delete', 0),
                        )
                    )

                if items_to_create:
                    TemuOrderItem.objects.bulk_create(items_to_create)

            return created, len(items_to_create) if item_list else 0

    # 预加载所有店铺配置
    store_ids = list(data_dict.keys())
    shop_map = await get_shops(store_ids)

    # print(f"预加载店铺数量: {len(shop_map)}")

    # 统计信息
    total_orders = 0
    created_orders = 0
    updated_orders = 0
    skipped_orders = 0
    total_items = 0

    for store_id, orders in data_dict.items():
        lingxing_shop = shop_map.get(store_id)
        if not lingxing_shop:
            print(f"错误: 未找到 store_id={store_id} 的店铺配置，跳过该店铺 {len(orders)} 条订单")
            skipped_orders += len(orders)
            continue

        # 店铺级统计初始化
        shop_created_orders = 0
        shop_updated_orders = 0
        shop_total_items = 0
        shop_name = getattr(lingxing_shop, 'name', store_id)

        for raw_order in orders:
            try:
                global_order_no = raw_order.get("global_order_no")
                if not global_order_no:
                    print(f"警告: 订单数据缺少 global_order_no，跳过: {raw_order}")
                    skipped_orders += 1
                    continue

                # 准备订单数据
                # 从 platform_info 提取 Temu 平台订单号
                platform_info_list = raw_order.get('platform_info', [])
                platform_order_no = None
                if platform_info_list and isinstance(platform_info_list, list) and len(platform_info_list) > 0:
                    platform_order_no = platform_info_list[0].get('platform_order_no')
                # 如果 platform_info 中没有，则尝试从商品明细中获取
                if not platform_order_no:
                    item_info = raw_order.get('item_info', [])
                    if item_info and isinstance(item_info, list) and len(item_info) > 0:
                        platform_order_no = item_info[0].get('platform_order_no')

                defaults = {
                    'lingxing_shop': lingxing_shop,
                    'reference_no': platform_order_no or raw_order.get('reference_no'),
                    'order_from_name': raw_order.get('order_from_name'),
                    'delivery_type': raw_order.get('delivery_type'),
                    'split_type': raw_order.get('split_type'),
                    'status': raw_order.get('status'),
                    'wid': raw_order.get('wid'),
                    'warehouse_name': raw_order.get('warehouse_name'),
                    'amount_currency': raw_order.get('amount_currency'),
                    'supplier_id': raw_order.get('supplier_id'),
                    'is_delete': raw_order.get('is_delete', 0),
                    'global_purchase_time': _timestamp_to_datetime(raw_order.get('global_purchase_time')),
                    'global_payment_time': _timestamp_to_datetime(raw_order.get('global_payment_time')),
                    'global_review_time': _timestamp_to_datetime(raw_order.get('global_review_time')),
                    'global_distribution_time': _timestamp_to_datetime(raw_order.get('global_distribution_time')),
                    'global_print_time': _timestamp_to_datetime(raw_order.get('global_print_time')),
                    'global_mark_time': _timestamp_to_datetime(raw_order.get('global_mark_time')),
                    'global_delivery_time': _timestamp_to_datetime(raw_order.get('global_delivery_time')),
                    'global_create_time': raw_order.get('global_create_time'),
                    'receiver_country_code': raw_order.get('address_info', {}).get('receiver_country_code'),
                    'postal_code': raw_order.get('address_info', {}).get('postal_code'),
                    'city': raw_order.get('address_info', {}).get('city'),
                    'tracking_number': raw_order.get('logistics_info', {}).get('tracking_no'),
                    'logistics_provider_name': raw_order.get('logistics_info', {}).get('logistics_provider_name'),
                    'order_total_amount': _to_decimal(
                        raw_order.get('transaction_info', [{}])[0].get('order_total_amount')
                    ),
                    'buyer_name_masked': raw_order.get('buyers_info', {}).get('buyer_name'),
                    'buyer_email_masked': raw_order.get('buyers_info', {}).get('buyer_email'),
                    'order_tag': raw_order.get('order_tag'),
                    'pending_order_tag': raw_order.get('pending_order_tag'),
                    'exception_order_tag': raw_order.get('exception_order_tag'),
                    'buyers_info': raw_order.get('buyers_info'),
                    'address_info': raw_order.get('address_info'),
                    'platform_info': raw_order.get('platform_info'),
                    'payment_info': raw_order.get('payment_info'),
                    'logistics_info': raw_order.get('logistics_info'),
                    'transaction_info': raw_order.get('transaction_info'),
                    'order_custom_fields': raw_order.get('order_custom_fields'),
                }

                item_list = raw_order.get('item_info') or []
                created, items_count = await save_order_with_items(
                    global_order_no, defaults, item_list, lingxing_shop
                )

                if created:
                    created_orders += 1
                    shop_created_orders += 1
                else:
                    updated_orders += 1
                    shop_updated_orders += 1
                total_orders += 1
                total_items += items_count
                shop_total_items += items_count

            except Exception as e:
                print(
                    f"错误: 处理订单失败 - store_id: {store_id}, order_no: {raw_order.get('global_order_no')}, 错误: {e}")
                skipped_orders += 1
                continue

        # 打印店铺级统计
        # print(
        #     f"【店铺: {shop_name}】订单处理完成 - 新增: {shop_created_orders}条 | 更新: {shop_updated_orders}条 | 商品明细: {shop_total_items}条")

    # 同步统计
    # print(
    #     f"\n同步完成 - 订单总计: {total_orders}, 新增: {created_orders}, 更新: {updated_orders}, 跳过: {skipped_orders}, 商品明细总数: {total_items}")


@sync_to_async
def get_temu_order_address_data(sn):
    """获取 Temu 订单地址数据（包含买家信息和地址信息）"""
    try:
        order = TemuOrder.objects.get(global_order_no=sn)
        buyers_info = order.buyers_info or {}
        address_info = order.address_info or {}
        # 合并数据
        result = {
            **buyers_info,
            **address_info,
        }

        return result
    except TemuOrder.DoesNotExist:
        return None


async def ck():
    """拿仓库"""
    req_body = {
        "type": 3
    }
    resp = await get_api_resp(req_body=req_body, api_path="/erp/sc/data/local_inventory/warehouse")
    # print(resp)


async def step3_add_warehousing_temu(items_with_qty_price: list, wid: str, app_id: str = None,
                                     app_secret: str = None):
    product_list = []
    for it in items_with_qty_price:
        product_item = {
            "sku": it['sku'],
            "good_num": it['quantity'],
            "bad_num": 0,
            "price": it['price_per_unit'],
            "fnsku": ""
        }
        product_list.append(product_item)

    req_body = {"sys_wid": wid, "type": 1, "product_list": product_list}
    resp = await get_api_resp(req_body=req_body, api_path="/erp/sc/routing/storage/storage/orderAdd", app_id=app_id,
                              app_secret=app_secret)
    print(f"   → 入库结果 = {resp}")
    
    # 检测 IP 白名单错误
    if resp is not None:
        resp_code = getattr(resp, "code", None)
        resp_message = getattr(resp, "message", "") or ""
        if resp_code == 3001002 or "ip not permit" in resp_message.lower():
            # 提取IP地址
            import re
            ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', resp_message)
            current_ip = ip_match.group(1) if ip_match else "未知"
            raise Exception(f"当前IP【{current_ip}】不在白名单中，请稍等几分钟")


@sync_to_async
def get_temu_order_status(sn_no: str):
    """根据系统单号获取订单状态码
    系统订单状态：
        1 同步中
        2 已同步
        3 未付款
        4 待审核
        5 待发货
        6 已发货
        7 已取消/不发货
        8 不显示
        9 平台发货

    """
    try:
        order = TemuOrder.objects.get(global_order_no=sn_no)
        return order.status
    except TemuOrder.DoesNotExist:
        return None


@sync_to_async
def get_temu_wid(sn_no: str):
    """根据系统单号获取 Temu 仓库 wid（美东/美西）"""
    try:
        order = TemuOrder.objects.get(global_order_no=sn_no)
        address_info = order.address_info or {}
        postal_code = address_info.get('postal_code', '')

        if postal_code:
            first_digit = postal_code[0]
            if first_digit in '0123':
                print(f"根据邮编 {postal_code} 判断为美东仓库 (530524)")
                return "530524"  # 美东
            elif first_digit in '456789':
                print(f"根据邮编 {postal_code} 判断为美西仓库 (530525)")
                return "530525"  # 美西
        raise ValueError(f"无法根据邮编判断仓库（美东/美西），请检查订单 {sn_no} 的地址信息")
    except TemuOrder.DoesNotExist:
        raise ValueError(f"订单 {sn_no} 不存在")


async def temu_order_create_skus(global_order_no: str):
    """
    为 Temu 订单批量创建/编辑 SKU 到领星仓库

    Args:
        global_order_no: 系统单号
    """

    @sync_to_async
    def get_order_skus_and_auth(sn):
        from temu.models import TemuOrderItem, TemuOrder
        try:
            order = TemuOrder.objects.select_related(
                'lingxing_shop__temu_shop__project'
            ).get(global_order_no=sn)

            # 获取所有商品 SKU
            items = TemuOrderItem.objects.filter(order=order)
            sku_list = [item.msku for item in items if item.msku]

            # 获取 app_id/app_secret
            app_id = None
            app_secret = None
            if order.lingxing_shop and order.lingxing_shop.temu_shop and order.lingxing_shop.temu_shop.project:
                project = order.lingxing_shop.temu_shop.project
                app_id = project.lingxing_app_id
                app_secret = project.lingxing_app_secret

            # 获取店铺包装规格（inch/lb）
            temu_shop = order.lingxing_shop.temu_shop if order.lingxing_shop else None
            dimensions = {
                'length': temu_shop.length if temu_shop else None,
                'width': temu_shop.width if temu_shop else None,
                'height': temu_shop.height if temu_shop else None,
                'weight': temu_shop.weight if temu_shop else None,
            }

            return sku_list, app_id, app_secret, dimensions
        except TemuOrder.DoesNotExist:
            return [], None, None, {}

    sku_list, app_id, app_secret, dimensions = await get_order_skus_and_auth(global_order_no)

    if not sku_list:
        print("没有可创建的 SKU")
        return False

    if not app_id or not app_secret:
        print("缺少领星API认证信息")
        return False

    print(f"待创建 SKU 列表: {sku_list}")
    print(f"店铺包装规格: {dimensions}")

    # 循环创建/编辑 SKU
    for sku in sku_list:
        print(f"开始创建/编辑 SKU: {sku}")
        await step1_set_sku(
            sku=sku,
            cg_price="10",  # 暂时写死
            app_id=app_id,
            app_secret=app_secret,
            length_inch=dimensions.get('length'),
            width_inch=dimensions.get('width'),
            height_inch=dimensions.get('height'),
            weight_lb=dimensions.get('weight'),
        )

    return True


async def temu_order_binding(global_order_no: str):
    """
    为 Temu 订单批量绑定商品 SKU

    Args:
        global_order_no: 系统单号
    """

    @sync_to_async
    def get_order_skus_and_auth(sn):
        from temu.models import TemuOrderItem, TemuOrder
        try:
            order = TemuOrder.objects.select_related(
                'lingxing_shop__temu_shop__project'
            ).get(global_order_no=sn)

            # 获取所有商品 SKU
            items = TemuOrderItem.objects.filter(order=order)
            sku_list = [item.msku for item in items if item.msku]

            # 获取 app_id/app_secret
            app_id = None
            app_secret = None
            if order.lingxing_shop and order.lingxing_shop.temu_shop and order.lingxing_shop.temu_shop.project:
                project = order.lingxing_shop.temu_shop.project
                app_id = project.lingxing_app_id
                app_secret = project.lingxing_app_secret

            return sku_list, app_id, app_secret
        except TemuOrder.DoesNotExist:
            return [], None, None

    sku_list, app_id, app_secret = await get_order_skus_and_auth(global_order_no)

    if not sku_list:
        print("没有可绑定的 SKU")
        return False

    if not app_id or not app_secret:
        print("缺少领星API认证信息")
        return False

    print(f"待绑定 SKU 列表: {sku_list}")

    # 调用步骤2：绑定商品
    await step2_update_order_binding(global_order_no, sku_list, app_id, app_secret)
    return True


async def temu_order_to_warehouse(global_order_no: str, wid: str):
    """
    将 Temu 订单商品入库到指定仓库

    Args:
        global_order_no: 系统单号
        wid: 仓库ID
    """

    @sync_to_async
    def get_order_items_and_auth(sn):
        from temu.models import TemuOrderItem, TemuOrder
        try:
            order = TemuOrder.objects.select_related(
                'lingxing_shop__temu_shop__project'
            ).get(global_order_no=sn)

            # 获取商品
            items = TemuOrderItem.objects.filter(order=order)
            items_list = []
            for item in items:
                items_list.append({
                    'sku': item.msku,
                    'quantity': item.quantity,
                    'price_per_unit': str(item.unit_price_amount) if item.unit_price_amount else '0.00'
                })

            # 获取 app_id/app_secret
            app_id = None
            app_secret = None
            if order.lingxing_shop and order.lingxing_shop.temu_shop and order.lingxing_shop.temu_shop.project:
                project = order.lingxing_shop.temu_shop.project
                app_id = project.lingxing_app_id
                app_secret = project.lingxing_app_secret

            return items_list, app_id, app_secret
        except TemuOrder.DoesNotExist:
            return [], None, None

    items_with_qty_price, app_id, app_secret = await get_order_items_and_auth(global_order_no)
    print(f"订单商品: {items_with_qty_price}")
    print(f"app_id: {app_id}, app_secret: {'有' if app_secret else '无'}")

    if items_with_qty_price and app_id and app_secret:
        await step3_add_warehousing_temu(items_with_qty_price, wid, app_id, app_secret)
        return True
    else:
        if not items_with_qty_price:
            print("没有可入库的商品")
        if not app_id or not app_secret:
            print("缺少领星API认证信息")
        return False


async def step1_set_sku(
        sku: str,
        cg_price: str,
        app_id: str = None,
        app_secret: str = None,
        length_inch: float = None,
        width_inch: float = None,
        height_inch: float = None,
        weight_lb: float = None,
):
    """
    新建/编辑产品到领星仓库
    
    Args:
        sku: SKU编码
        cg_price: 采购价格
        app_id: 领星AppID
        app_secret: 领星AppSecret
        length_inch: 包装长度（英寸），内部转换为厘米
        width_inch: 包装宽度（英寸），内部转换为厘米
        height_inch: 包装高度（英寸），内部转换为厘米
        weight_lb: 产品重量（磅），内部转换为克
    """
    # 单位转换：inch -> cm (1 inch = 2.54 cm)
    # 单位转换：lb -> g (1 lb = 453.592 g)
    def inch_to_cm(inch):
        if inch is None or inch == '':
            return 20  # 默认值
        try:
            return round(float(inch) * 2.54, 2)
        except (ValueError, TypeError):
            return 20
    
    def lb_to_g(lb):
        if lb is None or lb == '':
            return 150  # 默认值
        try:
            return round(float(lb) * 453.592, 2)
        except (ValueError, TypeError):
            return 150
    
    # 转换尺寸重量
    cg_length = inch_to_cm(length_inch)
    cg_width = inch_to_cm(width_inch)
    cg_height = inch_to_cm(height_inch)
    cg_weight = lb_to_g(weight_lb)
    
    req_body = {
        "sku": sku,
        "product_name": sku,
        "sku_identifier": sku,
        "cg_price": cg_price,
        'cg_package_length': cg_length,
        'cg_package_width': cg_width,
        'cg_package_height': cg_height,
        'cg_product_gross_weight': cg_weight,
        'description': "temu订单同步，自动创建/更新产品",
    }

    resp = await get_api_resp(
        req_body=req_body,
        api_path="/erp/sc/routing/storage/product/set",
        app_id=app_id,
        app_secret=app_secret
    )
    print(f"创建/编辑sku→ 返回结果   = {resp}")
    return resp


async def step2_update_order_binding(global_order_no: str, list_mskus: list, app_id: str = None,
                                     app_secret: str = None):
    order_item_list = []
    for msku in list_mskus:
        order_item_list.append({"sku": msku, "msku": msku, "type": 3})
    req_body = {"order_list": [{"global_order_no": global_order_no, "order_item_list": order_item_list}]}
    print(f"批量绑定商品 updateOrder 传参：{req_body}")
    resp = await get_api_resp(req_body=req_body, api_path="/pb/mp/order/v2/updateOrder", app_id=app_id,
                              app_secret=app_secret)
    print(f"   → 绑定结果 = {resp}")
    
    # 检测 IP 白名单错误
    if resp is not None:
        resp_code = getattr(resp, "code", None)
        resp_message = getattr(resp, "message", "") or ""
        if resp_code == 3001002 or "ip not permit" in resp_message.lower():
            # 提取IP地址
            import re
            ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', resp_message)
            current_ip = ip_match.group(1) if ip_match else "未知"
            raise Exception(f"当前IP【{current_ip}】不在白名单中，请稍等几分钟")


def rule_review(global_order_no_list: str):
    url = "https://erp.lingxing.com/api/platforms/order_flow/ruleReview"
    headers = {
        "auth-token": "c8b4eN2IMIbc4VQ3o5+3IKKvR9zyvSP/R5HKD4babBbkROMtzJfeHIpZc/H9lcj21fYxXi7oDv4JjpXKbh/J/niPVKti4tBsSHXuyz1XE1pmJKnhHDN8IA07bDbgH7o3h8jqKpSORUtH8pZxP+gSaLarpU/K8i0HAGVZtIY",
        "cookie": "sensorsdata2015jssdkchannel=%7B%22prop%22%3A%7B%22_sa_channel_landing_url%22%3A%22%22%7D%7D; _ga=GA1.1.1080743940.1758938699; __wpkreporterwid_=0b3c8410-66b0-492a-80de-ad88719bf782; seller-auth-erp-url=https%3A%2F%2Ferp.lingxing.com%2Fapi%2Fseller%2FoauthRedirect; _gcl_au=1.1.794625941.1768957315; _uetvid=5ef977909b4611f0be08dbb64ee72a9b; _clck=ch24da%5E2%5Eg43%5E0%5E2096; _ga_57W1QW8BJG=GS2.1.s1772679296$o12$g0$t1772679299$j57$l0$h688668351; sensorsdata2015jssdkcross=%7B%22distinct_id%22%3A%2210479745-10479745%22%2C%22first_id%22%3A%2219988ea949ec70-0a82006be0d1038-4c657b58-2073600-19988ea949f1da8%22%2C%22props%22%3A%7B%7D%2C%22identities%22%3A%22eyIkaWRlbnRpdHlfY29va2llX2lkIjoiMTk5ODhlYTk0OWVjNzAtMGE4MjAwNmJlMGQxMDM4LTRjNjU3YjU4LTIwNzM2MDAtMTk5ODhlYTk0OWYxZGE4IiwiJGlkZW50aXR5X2xvZ2luX2lkIjoiMTA0Nzk3NDUtMTA0Nzk3NDUifQ%3D%3D%22%2C%22history_login_id%22%3A%7B%22name%22%3A%22%24identity_login_id%22%2C%22value%22%3A%2210479745-10479745%22%7D%2C%22%24device_id%22%3A%2219988ea949ec70-0a82006be0d1038-4c657b58-2073600-19988ea949f1da8%22%7D; uid=10479745; zid=10479745; Hm_lvt_e1b07b01489084694814b73e755122ea=1772499632,1773017123,1773998154,1774252571; HMACCOUNT=B78407243006DBCA; is_sellerAuth=1; Hm_lvt_49f9312a5d99eba61237ede945a266af=1772611531,1773795289,1774317596; Hm_lpvt_49f9312a5d99eba61237ede945a266af=1774317596; HMACCOUNT=B78407243006DBCA; company_id=901372455441989632; envKey=SAAS-103; env_key=SAAS-103; authToken=01acdQKGW6tS9WEI0MCAFXTe1rVvUec38MmtFG9E5ylwvt%2F50TLbpdkPntu0hxi1X%2FW9BlOng4rXWkRctA9iVuYbGP5Ua7TWFTH%2BjPPQ9qNUzI%2Bna3YmDz38C7N2EOx9ConFscjhby6iYWkn4P1glNn2USwbZWXTCvGAfcQ; auth-token=01acdQKGW6tS9WEI0MCAFXTe1rVvUec38MmtFG9E5ylwvt%2F50TLbpdkPntu0hxi1X%2FW9BlOng4rXWkRctA9iVuYbGP5Ua7TWFTH%2BjPPQ9qNUzI%2Bna3YmDz38C7N2EOx9ConFscjhby6iYWkn4P1glNn2USwbZWXTCvGAfcQ; isNeedReset=0; isUpdatePwd=0; isLogin=true; _ga_YG2XNMH0EE=GS2.1.s1774831494$o52$g0$t1774831496$j58$l0$h300101792; Hm_lpvt_e1b07b01489084694814b73e755122ea=1774831497; info=%7B%22uid%22%3A%2210479745%22%2C%22zid%22%3A%2210479745%22%2C%22username%22%3A%22m.1113CzVrBn9a%22%2C%22siteUsername%22%3A%22%22%2C%22realname%22%3A%22%E5%90%B4%E5%B0%8F%E5%A7%90%22%2C%22mobile%22%3A%2213669591113%22%2C%22nationCode%22%3A%22%22%2C%22adminNationCode%22%3A%22%22%2C%22mealInfo%22%3A%7B%22recharge_num%22%3A0%7D%2C%22loginGuide%22%3Afalse%2C%22loginEnv%22%3A2%2C%22isPartner%22%3A0%2C%22email%22%3A%22%22%2C%22sysSubAdminFlag%22%3A0%2C%22editFlag%22%3A1%2C%22isDisableResetPwd%22%3A0%2C%22is_mobile_verified%22%3A1%2C%22is_master%22%3A1%2C%22is_email_verified%22%3A0%2C%22hide_init_guide%22%3A1%2C%22mp_hide_init_guide%22%3A0%2C%22has_bind_oauth_center%22%3A0%2C%22has_bind_jst%22%3A0%2C%22feature_info%22%3A%7B%7D%2C%22customer_id%22%3A%2210479745%22%2C%22show_zid%22%3A%2210479745%22%2C%22available_env%22%3A%5B%22amazon%22%2C%22multi%22%5D%2C%22api_info%22%3A%5B%5D%7D; sensor-distinace-id=10479745-10479745; token=01acdQKGW6tS9WEI0MCAFXTe1rVvUec38MmtFG9E5ylwvt%2F50TLbpdkPntu0hxi1X%2FW9BlOng4rXWkRctA9iVuYbGP5Ua7TWFTH%2BjPPQ9qNUzI%2Bna3YmDz38C7N2EOx9ConFscjhby6iYWkn4P1glNn2USwbZWXTCvGAfcQ; _ga_89WN60ZK2E=GS2.1.s1774831497$o7$g0$t1774831497$j60$l0$h0; udesk_info_901372455441989632=%7B%22level%22%3A%22B%22%2C%22klevel%22%3A%22%E5%90%A6%22%2C%22company_id%22%3A%22901372455441989632%22%2C%22customer_id%22%3A%2210479745%22%2C%22cs_group%22%3A%22CSG1-009%22%7D",
        "Content-Type": "application/json;charset=UTF-8",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0",
        'Host': 'erp.lingxing.com',
        'Origin': 'https://erp.lingxing.com',
        'Referer': 'https://erp.lingxing.com/erp/mmulti/mpOrderManagement',
        'Sec-Ch-Ua': '"Chromium";v="146", "Not-A.Brand";v="24", "Microsoft Edge";v="146"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"Windows"',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin',
        'Sentry-Trace': '600e5906ff2540d9a418e14bc507e3f4-8bdff8497115cc56-0',
        'X-Ak-Company-Id': '901372455441989632',
        'X-Ak-Env-Key': 'SAAS-103',
        'X-Ak-Language': 'zh',
        'X-Ak-Platform': '2',
        'X-Ak-Request-Id': '6b86a30e-6f6b-4756-a932-6c6e777e1b14',
        'X-Ak-Request-Source': 'erp',
        'X-Ak-Uid': '10479745',
        'X-Ak-Version': '3.7.9.3.0.118',
        'X-Ak-Zid': '10479745',
    }

    json_data = {
        "global_order_no": [
            global_order_no_list
        ],
        "req_time_sequence": "/api/platforms/order_flow/ruleReview$$1"
    }

    response = requests.post(url, json=json_data, headers=headers)
    return response


async def shipment_order(order_number_list, app_id: str = None, app_secret: str = None):
    req_body = {
        "order_number_list": order_number_list,
    }
    resp = await get_api_resp(
        req_body=req_body,
        api_path="/basicOpen/selfShipmentOrder/deliveryGoods",
        app_id=app_id,
        app_secret=app_secret,
    )
    print(f"发货返回：{resp}")
    
    # 检测 IP 白名单错误
    if resp is not None:
        resp_code = getattr(resp, "code", None)
        resp_message = getattr(resp, "message", "") or ""
        if resp_code == 3001002 or "ip not permit" in resp_message.lower():
            # 提取IP地址
            import re
            ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', resp_message)
            current_ip = ip_match.group(1) if ip_match else "未知"
            raise Exception(f"当前IP【{current_ip}】不在白名单中，请稍等几分钟")


async def get_wms_orders_by_order_numbers(order_numbers: str, app_id: str = None, app_secret: str = None):
    """
    查询销售出库单详情-支持查询ERP中【仓库】>【销售出库单】数据，即自发货订单销售出库单
    :param order_numbers: 系统单号
    :return:
    """
    req_body = {
        "isPrintCenter": 1,  # 是否需要拣货信息，枚举值：1-是, 0-否
        "orderNumbers": order_numbers,
    }
    resp = await get_api_resp(
        req_body=req_body,
        api_path="/basicOpen/wmsOrder/getWmsOrdersByOrderNumbers",
        app_id=app_id,
        app_secret=app_secret,
    )
    order_list = resp.data.get("orderList", [])
    if not order_list:
        print(f"订单 {order_numbers} 暂无面单信息")
        return
    order_i = order_list[0]
    surface_pdf = order_i.get("surfacePdf")
    if not surface_pdf:
        print(f"订单 {order_numbers} 暂无面单PDF链接")
        return
    filename = "\\\\192.168.110.54\overlord_555\自动化\Temu面单\\" + order_i.get("amazonOrderId") + "#" + order_i.get("trackingNo") + ".pdf"
    if os.path.exists(filename):
        print(f"文件已存在，跳过下载: {filename}")
        return
    print(surface_pdf, filename)
    download_pdf(download_url=surface_pdf, save_path=filename)


def download_pdf(download_url, save_path, headers=None, timeout=30):
    """
    下载PDF文件并保存到本地

    Args:
        download_url: PDF下载链接（如 https://erp.lingxing.com/api/file/downloadById?...）
        save_path: 本地保存路径（如 ./downloads/file.pdf）
        headers: 可选的请求头字典（如需Cookie、Authorization等）
        timeout: 请求超时时间（秒）

    Returns:
        tuple: (success: bool, message: str)
    """
    # 默认请求头（模拟浏览器）
    default_headers = {
        "auth-token": "c8b4eN2IMIbc4VQ3o5+3IKKvR9zyvSP/R5HKD4babBbkROMtzJfeHIpZc/H9lcj21fYxXi7oDv4JjpXKbh/J/niPVKti4tBsSHXuyz1XE1pmJKnhHDN8IA07bDbgH7o3h8jqKpSORUtH8pZxP+gSaLarpU/K8i0HAGVZtIY",
        "cookie": "sensorsdata2015jssdkchannel=%7B%22prop%22%3A%7B%22_sa_channel_landing_url%22%3A%22%22%7D%7D; _ga=GA1.1.1080743940.1758938699; __wpkreporterwid_=0b3c8410-66b0-492a-80de-ad88719bf782; seller-auth-erp-url=https%3A%2F%2Ferp.lingxing.com%2Fapi%2Fseller%2FoauthRedirect; _gcl_au=1.1.794625941.1768957315; _uetvid=5ef977909b4611f0be08dbb64ee72a9b; _clck=ch24da%5E2%5Eg43%5E0%5E2096; _ga_57W1QW8BJG=GS2.1.s1772679296$o12$g0$t1772679299$j57$l0$h688668351; sensorsdata2015jssdkcross=%7B%22distinct_id%22%3A%2210479745-10479745%22%2C%22first_id%22%3A%2219988ea949ec70-0a82006be0d1038-4c657b58-2073600-19988ea949f1da8%22%2C%22props%22%3A%7B%7D%2C%22identities%22%3A%22eyIkaWRlbnRpdHlfY29va2llX2lkIjoiMTk5ODhlYTk0OWVjNzAtMGE4MjAwNmJlMGQxMDM4LTRjNjU3YjU4LTIwNzM2MDAtMTk5ODhlYTk0OWYxZGE4IiwiJGlkZW50aXR5X2xvZ2luX2lkIjoiMTA0Nzk3NDUtMTA0Nzk3NDUifQ%3D%3D%22%2C%22history_login_id%22%3A%7B%22name%22%3A%22%24identity_login_id%22%2C%22value%22%3A%2210479745-10479745%22%7D%2C%22%24device_id%22%3A%2219988ea949ec70-0a82006be0d1038-4c657b58-2073600-19988ea949f1da8%22%7D; uid=10479745; zid=10479745; Hm_lvt_e1b07b01489084694814b73e755122ea=1772499632,1773017123,1773998154,1774252571; HMACCOUNT=B78407243006DBCA; is_sellerAuth=1; Hm_lvt_49f9312a5d99eba61237ede945a266af=1772611531,1773795289,1774317596; Hm_lpvt_49f9312a5d99eba61237ede945a266af=1774317596; HMACCOUNT=B78407243006DBCA; company_id=901372455441989632; envKey=SAAS-103; env_key=SAAS-103; authToken=01acdQKGW6tS9WEI0MCAFXTe1rVvUec38MmtFG9E5ylwvt%2F50TLbpdkPntu0hxi1X%2FW9BlOng4rXWkRctA9iVuYbGP5Ua7TWFTH%2BjPPQ9qNUzI%2Bna3YmDz38C7N2EOx9ConFscjhby6iYWkn4P1glNn2USwbZWXTCvGAfcQ; auth-token=01acdQKGW6tS9WEI0MCAFXTe1rVvUec38MmtFG9E5ylwvt%2F50TLbpdkPntu0hxi1X%2FW9BlOng4rXWkRctA9iVuYbGP5Ua7TWFTH%2BjPPQ9qNUzI%2Bna3YmDz38C7N2EOx9ConFscjhby6iYWkn4P1glNn2USwbZWXTCvGAfcQ; isNeedReset=0; isUpdatePwd=0; isLogin=true; _ga_YG2XNMH0EE=GS2.1.s1774831494$o52$g0$t1774831496$j58$l0$h300101792; Hm_lpvt_e1b07b01489084694814b73e755122ea=1774831497; info=%7B%22uid%22%3A%2210479745%22%2C%22zid%22%3A%2210479745%22%2C%22username%22%3A%22m.1113CzVrBn9a%22%2C%22siteUsername%22%3A%22%22%2C%22realname%22%3A%22%E5%90%B4%E5%B0%8F%E5%A7%90%22%2C%22mobile%22%3A%2213669591113%22%2C%22nationCode%22%3A%22%22%2C%22adminNationCode%22%3A%22%22%2C%22mealInfo%22%3A%7B%22recharge_num%22%3A0%7D%2C%22loginGuide%22%3Afalse%2C%22loginEnv%22%3A2%2C%22isPartner%22%3A0%2C%22email%22%3A%22%22%2C%22sysSubAdminFlag%22%3A0%2C%22editFlag%22%3A1%2C%22isDisableResetPwd%22%3A0%2C%22is_mobile_verified%22%3A1%2C%22is_master%22%3A1%2C%22is_email_verified%22%3A0%2C%22hide_init_guide%22%3A1%2C%22mp_hide_init_guide%22%3A0%2C%22has_bind_oauth_center%22%3A0%2C%22has_bind_jst%22%3A0%2C%22feature_info%22%3A%7B%7D%2C%22customer_id%22%3A%2210479745%22%2C%22show_zid%22%3A%2210479745%22%2C%22available_env%22%3A%5B%22amazon%22%2C%22multi%22%5D%2C%22api_info%22%3A%5B%5D%7D; sensor-distinace-id=10479745-10479745; token=01acdQKGW6tS9WEI0MCAFXTe1rVvUec38MmtFG9E5ylwvt%2F50TLbpdkPntu0hxi1X%2FW9BlOng4rXWkRctA9iVuYbGP5Ua7TWFTH%2BjPPQ9qNUzI%2Bna3YmDz38C7N2EOx9ConFscjhby6iYWkn4P1glNn2USwbZWXTCvGAfcQ; _ga_89WN60ZK2E=GS2.1.s1774831497$o7$g0$t1774831497$j60$l0$h0; udesk_info_901372455441989632=%7B%22level%22%3A%22B%22%2C%22klevel%22%3A%22%E5%90%A6%22%2C%22company_id%22%3A%22901372455441989632%22%2C%22customer_id%22%3A%2210479745%22%2C%22cs_group%22%3A%22CSG1-009%22%7D",
        "Content-Type": "application/json;charset=UTF-8",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0",
        'Host': 'erp.lingxing.com',
        'Origin': 'https://erp.lingxing.com',
        'Referer': 'https://erp.lingxing.com/erp/mmulti/mpOrderManagement',
        'Sec-Ch-Ua': '"Chromium";v="146", "Not-A.Brand";v="24", "Microsoft Edge";v="146"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"Windows"',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin',
        'Sentry-Trace': '600e5906ff2540d9a418e14bc507e3f4-8bdff8497115cc56-0',
        'X-Ak-Company-Id': '901372455441989632',
        'X-Ak-Env-Key': 'SAAS-103',
        'X-Ak-Language': 'zh',
        'X-Ak-Platform': '2',
        'X-Ak-Request-Id': '6b86a30e-6f6b-4756-a932-6c6e777e1b14',
        'X-Ak-Request-Source': 'erp',
        'X-Ak-Uid': '10479745',
        'X-Ak-Version': '3.7.9.3.0.118',
        'X-Ak-Zid': '10479745',
    }

    # 合并用户提供的headers
    if headers:
        default_headers.update(headers)

    try:
        # 确保目录存在
        save_dir = os.path.dirname(os.path.abspath(save_path))
        if save_dir and not os.path.exists(save_dir):
            os.makedirs(save_dir, exist_ok=True)

        # 流式下载，节省内存
        print(f"开始下载: {download_url}")
        response = requests.get(
            download_url,
            headers=default_headers,
            stream=True,
            timeout=timeout,
            allow_redirects=True
        )
        response.raise_for_status()  # 检查HTTP错误

        # 检查Content-Type是否为PDF（可选）
        content_type = response.headers.get('Content-Type', '')

        # 写入文件
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        chunk_size = 8192

        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    # 简单的进度显示
                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        print(f"\r下载进度: {percent:.1f}%", end='', flush=True)

        print(f"\n✓ 下载完成: {save_path} ({downloaded / 1024:.1f} KB)")
        return True, "下载成功"

    except requests.exceptions.Timeout:
        error_msg = "请求超时"
        print(f"✗ {error_msg}")
        return False, error_msg

    except requests.exceptions.HTTPError as e:
        error_msg = f"HTTP错误: {e.response.status_code}"
        print(f"✗ {error_msg}")
        return False, error_msg

    except Exception as e:
        error_msg = f"下载失败: {str(e)}"
        print(f"✗ {error_msg}")
        return False, error_msg

@sync_to_async
def check_y2_pre_sale(order_sn):
    try:
        order = TemuOrder.objects.get(global_order_no=order_sn)
        order_tags = order.order_tag or []
        for tag in order_tags:
            if tag.get('tag_name') == 'Y2 预售':
                return True
        return False
    except TemuOrder.DoesNotExist:
        return False

async def temu_order_to_divi_and_lingxing(sn_no):
    """
    temu订单从领星导入divi并发货
    :param sn_no: 系统单号
    :return:
    """
    success = await refresh_temu_order_by_sn(sn_no)  # 刷新订单数据（会调用 save_temu_orders_data 保存到数据库）
    if not success:
        raise Exception(f"订单号：{sn_no},订单数据刷新失败，无法继续下一步骤")


    is_y2_pre_sale = await check_y2_pre_sale(sn_no)
    if is_y2_pre_sale:
        raise Exception(f"【注意】订单 {sn_no} 包含 'Y2 预售' 标签~")

    status = await get_temu_order_status(sn_no)
    if status in [0,1,2,3]:
        raise Exception(f"{sn_no}订单处于：同步中/已同步/未付款 阶段")
    # 检查订单在DIVI中的状态
    status = await get_temu_order_status(sn_no)
    print(f"订单号：{sn_no}，领星状态：{status}")
    
    # 只有在状态为待审核(4)或待发货(5)时才需要处理
    if status not in [4, 5]:
        print(f"订单号：{sn_no} 状态不是待审核/待发货，跳过处理")
        return
    
    # 检查DIVI中是否已有面单
    divi_order_with_pdf = await check_temu_order_to_divi(sn_no, pdf=True, status=[0, 1, 2, 3, 4, 5])
    if divi_order_with_pdf:
        await get_wms_orders_by_order_numbers(sn_no)
        print(f"订单号：{sn_no} 已存在divi且有面单，处理完成")
        return
    
    # 检查DIVI中是否存在（无面单）
    divi_order_bool = await check_temu_order_to_divi(sn_no, pdf=False, status=[0, 1, 2, 3, 4, 5])
    if not divi_order_bool:
        # DIVI中不存在，需要导单
        await get_temu_order_for_divi(sn_no) # 导入订单
        print(f"订单号：{sn_no} 已导入DIVI")
    else:
        print(f"订单号：{sn_no} 已存在divi但没有面单，继续执行后续流程")

    # 根据状态执行后续操作
    if status == 4: # 待审核
        wid = await get_temu_wid(sn_no)
        await temu_order_create_skus(sn_no)# 创建/编辑 SKU
        await temu_order_to_warehouse(sn_no, wid)# 执行入库
        await temu_order_binding(sn_no)# 绑定商品（编辑/更新自发货订单）
        rule_review(sn_no) # 订单审核（调用ERP规则审核接口，触发订单审核流程）
        print(f"订单号：{sn_no} 待审核流程执行完成")

    elif status == 5: # 待发货
        await shipment_order(sn_no)  # 订单发货
        print(f"订单号：{sn_no} 待发货流程执行完成")
        
    await get_wms_orders_by_order_numbers(sn_no)  # 下载面单


if __name__ == '__main__':
    sn_no = "103683121034022662"
    asyncio.run(temu_order_to_divi_and_lingxing(sn_no))
    # asyncio.run(ck())
