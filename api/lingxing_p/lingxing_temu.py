from api.lingxing.Y_OpenApi import get_api_resp
import datetime
from typing import List, Dict, Any
import asyncio


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

async def get_lx_temu_orders_list(platform_order_nos:List[str]):
    """
        通过平台订单号列表获取订单详情（一次最多500个订单号）
    :param platform_order_nos:
    :return:
    """
    req_body = {
        "platform_order_nos": platform_order_nos,
        "offset": 0,
        "length": 500,
        "platform_code":["10024"]
    }
    print(req_body)
    resp = await get_api_resp(req_body, api_path="/pb/mp/order/v2/list")
    print(resp)

async def temu_address_decrypt(decrypt_sn_list:List[str]):
    """
        批量TEMU地址解密 系统单号列表
    :param decrypt_sn_list:
    :return:
    """
    req_body = {
        "decryptSnList": decrypt_sn_list,
    }
    print("入参：",req_body)
    resp = await get_api_resp(req_body, api_path="/basicOpen/temu/temuAddressDecrypt")
    print(resp)

if __name__ == '__main__':
    asyncio.run(get_lx_temu_orders_list(platform_order_nos=["PO-211-14658323825273284"]))
    # asyncio.run(temu_address_decrypt(decrypt_sn_list=["103680050723201224"]))