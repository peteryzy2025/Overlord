import os
import sys
import django
import asyncio
from decimal import Decimal, ROUND_HALF_UP
from asgiref.sync import sync_to_async
from datetime import datetime, timedelta

# ========== Django环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(CURRENT_DIR))
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

from api.lingxing.Y_OpenApi import get_api_resp
from amazon.models import LingXingAmazonShop
import pandas as pd
from tqdm import tqdm


async def get_amazon_order_detail(sid, start_date=None, end_date=None, show_detail=True):
    """
    获取单个店铺的订单详情
    :param sid: 领星店铺ID
    :param start_date: 开始日期，默认本月1号
    :param end_date: 结束日期，默认今天
    :param show_detail: 是否显示详细进度
    :return: 订单列表
    """
    # 默认查询本月数据
    if start_date is None:
        start_date = datetime.now().replace(day=1).strftime('%Y-%m-%d')
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')
    
    all_orders = []
    offset = 0
    length = 1000

    while True:
        req_body = {
            "sid": sid,
            "start_date": start_date,
            "end_date": end_date,
            "offset": offset,
            "length": length,
        }
        resp = await get_api_resp(req_body=req_body, api_path="/erp/sc/data/mws_report/allOrders")

        if resp.data and len(resp.data) > 0:
            all_orders.extend(resp.data)
            
            if show_detail and len(all_orders) < resp.total:
                tqdm.write(f"    已获取 {len(all_orders)} / {resp.total} 条数据")

            # 如果获取的数据已经达到总数，或者本次获取不足1000条（说明是最后一页），则结束
            if len(all_orders) >= resp.total or len(resp.data) < length:
                break
            offset += length
        else:
            break

    if show_detail:
        tqdm.write(f"    ✅ 共 {len(all_orders)} 条")
    return all_orders


async def get_all_us_orders(start_date=None, end_date=None):
    """
    获取所有美国区店铺的订单数据
    :param start_date: 开始日期
    :param end_date: 结束日期
    :return: 合并后的订单DataFrame
    """
    # 查询所有美国区店铺（通过country或region筛选）
    us_shops = await sync_to_async(list)(
        LingXingAmazonShop.objects.filter(
            country='美国'
        ).select_related('amazon_shop')
    )
    
    print(f"找到 {len(us_shops)} 个美国区店铺")
    
    all_orders = []
    
    for shop in tqdm(us_shops, desc="获取店铺订单", unit="店"):
        tqdm.write(f"📦 {shop.name} (sid={shop.sid})")
        try:
            orders = await get_amazon_order_detail(shop.sid, start_date, end_date, show_detail=True)
            
            # 为每个订单添加店铺信息
            for order in orders:
                order['shop_sid'] = shop.sid
                order['shop_name'] = shop.name
                order['account_name'] = shop.account_name
                order['seller_id'] = shop.seller_id
                # 关联的本地店铺信息
                if shop.amazon_shop:
                    order['local_shop_name'] = shop.amazon_shop.shop_name
                    order['local_shop_id'] = shop.amazon_shop.id
                else:
                    order['local_shop_name'] = ''
                    order['local_shop_id'] = ''
            
            all_orders.extend(orders)
            
        except Exception as e:
            tqdm.write(f"  ❌ 获取店铺 {shop.name} (sid={shop.sid}) 数据失败: {e}")
            continue
    
    print(f"\n✅ 所有店铺共获取 {len(all_orders)} 条订单数据")
    
    return all_orders


def export_orders_to_excel(orders, output_file=None):
    """
    将订单数据导出为Excel
    :param orders: 订单列表
    :param output_file: 输出文件名，默认为 amazon_us_orders_时间戳.xlsx
    """
    if not orders:
        print("没有数据可导出")
        return
    
    if output_file is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = f"amazon_us_orders_{timestamp}.xlsx"
    
    df = pd.DataFrame(orders)
    
    # 调整列顺序，将店铺信息放在前面
    priority_columns = [
        'shop_sid', 'shop_name', 'account_name', 'local_shop_name',
        'amazon_order_id', 'purchase_date', 'purchase_date_local',
        'order_status', 'sku', 'asin', 'product_name',
        'quantity', 'currency', 'item_price', 'item_tax'
    ]
    
    # 获取所有列，优先列在前，其余保持原顺序
    all_columns = list(df.columns)
    ordered_columns = [c for c in priority_columns if c in all_columns]
    ordered_columns += [c for c in all_columns if c not in priority_columns]
    df = df[ordered_columns]
    
    # 导出Excel
    df.to_excel(output_file, index=False, engine='openpyxl')
    print(f"\n📊 数据已导出到: {output_file}")
    print(f"   共 {len(df)} 行，{len(df.columns)} 列")
    
    return output_file


def get_month_date_range(year, month):
    """
    获取指定月份的起止日期
    逻辑：从1月1日开始，到指定月份的最后一天
    例如：要2月的数据，返回 (2026-01-01, 2026-02-28)
    :param year: 年份
    :param month: 月份（1-12）
    :return: (start_date, end_date)
    """
    start_date = f"{year}-01-01"
    
    # 计算指定月份的最后一天
    if month == 12:
        next_month = datetime(year + 1, 1, 1)
    else:
        next_month = datetime(year, month + 1, 1)
    
    # 最后一天 = 下个月1号 - 1天
    last_day = next_month - timedelta(days=1)
    end_date = last_day.strftime('%Y-%m-%d')
    
    return start_date, end_date


async def main():
    """主函数
    
    修改 year 和 month 参数来导出不同月份的数据：
    - 例如要导出 2026年2月的数据，会导出 2026-01-01 到 2026-02-28 的订单
    """
    # ========== 配置区域 ==========
    year = 2026      # 年份
    month = 2        # 月份（1-12）
    # =============================
    
    start_date, end_date = get_month_date_range(year, month)
    
    print(f"开始获取美国区店铺订单数据 ({start_date} ~ {end_date})\n")
    
    # 获取所有美国区店铺订单
    orders = await get_all_us_orders(start_date, end_date)
    
    # 导出Excel
    if orders:
        output_file = f"amazon_us_orders_{year}年{month}月.xlsx"
        export_orders_to_excel(orders, output_file)
    else:
        print("未获取到任何订单数据")


if __name__ == '__main__':
    asyncio.run(main())
