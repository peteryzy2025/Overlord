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
    current_time = datetime.today()# + timedelta(days=1)
    thirty_days_ago_time = current_time - timedelta(days=1)
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



