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
import pandas as pd
from tqdm import tqdm


async def get_order_transaction(sids=None, start_date=None, end_date=None):
    """
    获取订单交易明细数据（订单维度）
    注意：日期范围可以超过7天
    :param sids: 店铺ID列表，如 [522034]
    :param start_date: 开始日期，如 "2026-01-01"
    :param end_date: 结束日期，如 "2026-02-28"
    :return: 交易明细列表
    """
    # 默认查询本月数据
    if start_date is None:
        start_date = datetime.now().replace(day=1).strftime('%Y-%m-%d')
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')
    if sids is None:
        sids = [522034]
    
    all_records = []
    offset = 0
    length = 1000
    total = None

    print(f"开始获取订单交易明细 ({start_date} ~ {end_date})")
    print(f"店铺: {sids}")

    while True:
        req_body = {
            "sids": sids,
            "startDate": start_date,
            "endDate": end_date,
            "offset": offset,
            "length": length,
        }
        resp = await get_api_resp(req_body=req_body, api_path="/basicOpen/finance/profitReport/order/transcation/list")
        
        # 获取总数（仅在第一页）
        if total is None:
            total = resp.data.get("total", 0)
            print(f"总记录数: {total}")
        
        # 获取数据列表
        records = resp.data.get("records", [])
        
        if records and len(records) > 0:
            all_records.extend(records)
            print(f"  已获取 {len(all_records)} / {total} 条数据")
            
            # 如果获取的数据已经达到总数，或者本次获取不足length条（说明是最后一页），则结束
            if len(all_records) >= total or len(records) < length:
                break
            offset += length
        else:
            break

    print(f"✅ 总共获取 {len(all_records)} 条订单交易明细数据")
    return all_records


def export_to_excel(records, output_file=None):
    """
    将订单交易明细导出为Excel
    :param records: 交易明细列表
    :param output_file: 输出文件名，默认为 订单交易明细_时间戳.xlsx
    """
    if not records:
        print("没有数据可导出")
        return
    
    if output_file is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = f"订单交易明细_{timestamp}.xlsx"
    
    df = pd.DataFrame(records)
    
    # 导出Excel
    df.to_excel(output_file, index=False, engine='openpyxl')
    print(f"\n📊 数据已导出到: {output_file}")
    print(f"   共 {len(df)} 行，{len(df.columns)} 列")
    
    return output_file


async def main():
    """主函数"""
    # ========== 配置区域 ==========
    sids = [522034]  # 店铺ID列表
    start_date = "2026-01-01"
    end_date = "2026-02-28"
    # =============================
    
    # 获取订单交易明细
    records = await get_order_transaction(sids, start_date, end_date)
    
    # 导出Excel
    if records:
        export_to_excel(records)
    else:
        print("未获取到任何数据")


if __name__ == '__main__':
    asyncio.run(main())
