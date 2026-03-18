import os
import sys
import django
import asyncio
import datetime
from decimal import Decimal, InvalidOperation
from django.db import transaction

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
from temu.models import TemuOrder


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
        return datetime.datetime.fromtimestamp(int(ts), tz=datetime.timezone.utc)
    except (ValueError, TypeError):
        print(f"警告: 时间戳转换失败: {ts}")
        return None


async def get_lx_temu_shops():
    req_body = {
        "offset": 0,
        "length": 200,
        "platform_code": [10022, 10024],  # Temu全托管,Temu半托管
        "is_sync": 1,
        "status": 1
    }

    resp = await get_api_resp(req_body, api_path="/pb/mp/shop/v2/getSellerList")
    print(resp)
    return resp.data.get("list")


async def get_lx_temu_orders(store_ids: List[str], day: int = 3) -> Dict[str, List[Dict[str, Any]]]:
    """
    按 store_id（一次只传一个给 API）拉取领星/Temu 订单（带分页），时间范围由 day 决定：
      start_time = (today - day days) 00:00:00 (UTC)
      end_time   = today 23:59:59 (UTC)

    Args:
        store_ids: list of store_id strings (可以传多个，本函数会为每个店铺单独请求)
        day: 向前的天数窗口（例如 day=3 则从 3 天前 00:00:00 到 今天 23:59:59）

    Returns:
        dict: { store_id: [order_dict, ...], ... }
    """
    results: Dict[str, List[Dict[str, Any]]] = {}

    # 以 UTC 计算 start/end
    now_utc = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
    today_utc_date = now_utc.date()
    # start = (today - day) at 00:00:00  (例如 day=3 -> 3 days ago 00:00:00)
    start_date = today_utc_date - datetime.timedelta(days=day)
    start_dt = datetime.datetime.combine(start_date, datetime.time(0, 0, 0), tzinfo=datetime.timezone.utc)
    # end = today 23:59:59
    end_dt = datetime.datetime.combine(today_utc_date, datetime.time(23, 59, 59), tzinfo=datetime.timezone.utc)

    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())

    LENGTH = 500

    for store_id in store_ids:
        store_results = []
        offset = 0

        while True:
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
                resp = await get_api_resp(req_body, api_path="/pb/mp/order/v2/list")
            except Exception as e:
                # 捕获网络/解析异常，记录并跳出当前店铺的循环（或你可以改为重试）
                print(f"[get_lingxing_orders] Exception fetching store {store_id}, offset {offset}: {e}")
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
        批量TEMU地址解密 系统单号列表
    :param decrypt_sn_list:
    :return:
    """
    req_body = {
        "decryptSnList": decrypt_sn_list,
    }
    resp = await get_api_resp(req_body, api_path="/basicOpen/temu/temuAddressDecrypt")
    print(resp)
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
                    items_to_create.append(
                        TemuOrderItem(
                            order=order,
                            global_item_no=global_item_no,
                            platform_order_no=row.get('platform_order_no'),
                            order_item_no=row.get('order_item_no'),
                            item_from_name=row.get('item_from_name'),
                            msku=row.get('msku'),
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

        # 构建 address_line_all
        address_parts = []
        for key in ['address_line1', 'address_line2', 'address_line3']:
            value = address_info.get(key)
            if value:
                address_parts.append(value)
        address_line_all = ' '.join(address_parts)

        # 合并数据
        result = {
            **buyers_info,
            **address_info,
            'address_line_all': address_line_all,
        }

        return result
    except TemuOrder.DoesNotExist:
        return None


async def ck():
    """拿"""
    req_body = {
        "type": 3
    }
    resp = await get_api_resp(req_body=req_body, api_path="/erp/sc/data/local_inventory/warehouse")
    print(resp)

async def step3_add_warehousing(items_with_qty_price: list, execute: bool = True, app_id: str = None, app_secret: str = None):
    print(f"\n【步骤3】批量入库 add_warehousing 传参：")
    print(f"   → sys_wid = 509522, type = 1")
    print(f"   → product_list = [")
    for it in items_with_qty_price:
        print(f"       {{ sku: {it['sku']}, good_num: {it['quantity']}, price: {it['price_per_unit']} }}")
    print(f"   ]")
    if not execute:
        print("   → [预览模式] 不执行")
        return
    product_list = [
        {"sku": it['sku'], "good_num": it['quantity'], "bad_num": 0, "price": it['price_per_unit'], "fnsku": ""}
        for it in items_with_qty_price
    ]
    req_body = {"sys_wid": 509522, "type": 1, "product_list": product_list}
    resp = await get_api_resp(req_body=req_body, api_path="/erp/sc/routing/storage/storage/orderAdd", app_id=app_id, app_secret=app_secret)
    # print(f"   → 返回结果 = {resp.dict().get('msg', 'OK')}")
    print(f"   → 入库结果 = {resp}")
async def test():
    sn_no = "103680374441311872"
    # success = await temu_address_decrypt([sn_no]) # 先解密地址（如果订单地址未解密则无法正确保存地址信息）
    # if not success:
    #     raise f"订单号：{sn_no},地址解密失败，无法继续下一步骤"
    # success = await refresh_temu_order_by_sn(sn_no) # 刷新订单数据（会调用 save_temu_orders_data 保存到数据库）
    # if not success:
    #     raise f"订单号：{sn_no},订单数据刷新失败，无法继续下一步骤"
    order_info = await get_temu_order_address_data(sn_no)  # 从数据库获取订单地址数据（包含买家信息和地址信息）
    print(order_info)

    # 判断美东/美西
    postal_code = order_info.get('postal_code', '')
    if postal_code:
        first_digit = postal_code[0]
        if first_digit in '0123':
            region = '美东'
            wid = "530524"
        elif first_digit in '456789':
            region = '美西'
            wid = "530525"
        else:
            region = '未知'
            wid = None
        print(f"邮编: {postal_code}, 地区: {region}, wid: {wid}")
    else:
        print("邮编信息缺失")


if __name__ == '__main__':
    # asyncio.run(test())
    asyncio.run(ck())
