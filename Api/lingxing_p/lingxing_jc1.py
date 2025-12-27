import asyncio
from typing import List, Dict
from Api.lingxing.Y_OpenApi import get_api_resp
from datetime import datetime, timedelta


async def get_lingxing_shop():
    """
    获取领星店铺列表
    """
    resp = await get_api_resp(
        req_body={},
        api_path="/erp/sc/data/seller/lists",
        method="POST"
    )
    print(f"接口返回的店铺数据量：{len(resp.data) if resp.data else 0}")
    return resp.data


async def get_lingxing_orders(sid_list: List[int], days: int = 3) -> List[Dict]:
    """
    根据 sid_list 从领星获取订单数据（自动处理每次最多 20 个 sid 的限制）

    :param sid_list: 店铺 sid 列表（可以超过 20 个，本函数会自动分组）
    :param days: 取最近多少天的订单（默认 3 天）
    :return: 订单列表（直接返回领星接口返回的 data 合并结果）
    """
    if not sid_list:
        print("get_lingxing_orders: sid_list 为空，直接返回 []")
        return []

    # 时间范围：最近 days 天
    current_time = datetime.today()
    start_time = current_time - timedelta(days=days)

    # 接口限制：sid_list 每次最多 20 个，这里自动分组
    grouped_sids = [sid_list[i:i + 20] for i in range(0, len(sid_list), 20)]
    print(f"总共 {len(sid_list)} 个 sid，分成 {len(grouped_sids)} 组（每组最多 20 个）")

    all_orders: List[Dict] = []

    for idx, group in enumerate(grouped_sids, start=1):
        req_body = {
            "sid_list": group,
            "date_type": 1,  # 订购时间
            "order_status": ["Pending", "Unshipped", "PartiallyShipped", "Shipped", "Canceled"],
            "start_date": start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "end_date": current_time.strftime("%Y-%m-%d %H:%M:%S"),
            "length": 5000,
        }

        print(f"[get_lingxing_orders] 开始请求第 {idx} 组 sid_list: {group}")
        try:
            resp = await get_api_resp(
                req_body=req_body,
                api_path="/erp/sc/data/mws/orders",
                method="POST"
            )
        except Exception as e:
            print(f"[get_lingxing_orders] 第 {idx} 组请求失败：{e}")
            # 出错继续下一组
            continue

        data = resp.data or []
        print(f"[get_lingxing_orders] 第 {idx} 组返回 {len(data)} 条订单")
        if data:
            all_orders.extend(data)

    print(f"[get_lingxing_orders] 合计获取到 {len(all_orders)} 条订单")
    return all_orders


async def get_lingxing_zifa_order(sid:str, days: int = 3):
    current_time = datetime.today()
    start_time = current_time - timedelta(days=days)
    req_body = {
        "sid": sid,
        "start_time": start_time.strftime("%Y-%m-%d %H:%M:%S"),
        "end_time": current_time.strftime("%Y-%m-%d %H:%M:%S"),
        "length": 5000,
    }
    resp = await get_api_resp(req_body, api_path="/erp/sc/routing/order/Order/getOrderList")
    # print(resp.data)
    return resp.data


async def get_amazon_order_detail(amazon_order_ids: List[str]) -> List[Dict]:
    """
    批量获取亚马逊订单详情（支持超过200个订单号，内部自动分批）

    :param amazon_order_ids: 订单号列表，如 ["111-4997053-2861834", "113-7088145-9667414"]
    :return: 合并后的订单详情列表
    :raises: 任一分批请求失败会抛出异常
    """
    if not amazon_order_ids:
        print("[get_amazon_order_detail] 订单号列表为空，直接返回 []")
        return []

    # API限制：每次最多200个，留10个余量，按190个一批
    BATCH_SIZE = 190
    total_orders = len(amazon_order_ids)

    if total_orders <= BATCH_SIZE:
        # 数量在限制内，直接查询
        order_ids_str = ",".join(amazon_order_ids)
        req_body = {"order_id": order_ids_str}

        try:
            resp = await get_api_resp(
                req_body=req_body,
                api_path="/erp/sc/data/mws/orderDetail"
            )
            result_count = len(resp.data) if resp.data else 0
            print(f"[get_amazon_order_detail] 查询 {total_orders} 个订单，获取到 {result_count} 条详情")
            return resp.data or []
        except Exception as e:
            print(f"[get_amazon_order_detail] 查询失败: {str(e)}")
            raise  # 抛出异常

    # 超过限制，需要分批
    print(
        f"[get_amazon_order_detail] 订单总数 {total_orders}，超过 {BATCH_SIZE} 限制，将分成 {(total_orders + BATCH_SIZE - 1) // BATCH_SIZE} 批查询")

    all_details = []
    batches = [amazon_order_ids[i:i + BATCH_SIZE] for i in range(0, total_orders, BATCH_SIZE)]

    for idx, batch in enumerate(batches, 1):
        print(f"[get_amazon_order_detail] 开始查询第 {idx}/{len(batches)} 批，共 {len(batch)} 个订单")

        order_ids_str = ",".join(batch)
        req_body = {"order_id": order_ids_str}

        try:
            resp = await get_api_resp(
                req_body=req_body,
                api_path="/erp/sc/data/mws/orderDetail"
            )
            batch_result = resp.data or []
            print(f"[get_amazon_order_detail] 第 {idx} 批查询成功，获取到 {len(batch_result)} 条详情")
            all_details.extend(batch_result)
        except Exception as e:
            print(f"[get_amazon_order_detail] 第 {idx} 批查询失败: {str(e)}，中止后续批次")
            raise  # 任一批失败，整体失败

    print(f"[get_amazon_order_detail] 所有批次完成，总计获取 {len(all_details)} 条详情")
    return all_details

