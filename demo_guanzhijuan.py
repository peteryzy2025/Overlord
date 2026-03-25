#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import django
import asyncio
import datetime

# ====== Django 初始化 ======
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
django.setup()

from api.lingxing.Y_OpenApi import get_api_resp


async def debug_single_store():
    """单独调试 吴晓云-guanzhijuan-贴布 店铺"""
    
    store_id = "110547698341553664"
    shop_name = "吴晓云-guanzhijuan-贴布"
    day = 14
    
    # 计算时间范围（和原脚本一致）
    now_utc = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
    today_utc_date = now_utc.date()
    start_date = today_utc_date - datetime.timedelta(days=day)
    start_dt = datetime.datetime.combine(start_date, datetime.time(0, 0, 0), tzinfo=datetime.timezone.utc)
    end_dt = datetime.datetime.combine(today_utc_date, datetime.time(23, 59, 59), tzinfo=datetime.timezone.utc)
    
    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())
    
    print(f"=" * 60)
    print(f"调试店铺: {shop_name}")
    print(f"store_id: {store_id}")
    print(f"时间范围: {start_dt} ~ {end_dt}")
    print(f"时间戳: {start_ts} ~ {end_ts}")
    print(f"=" * 60)
    
    req_body = {
        "start_time": start_ts,
        "end_time": end_ts,
        "date_type": "global_purchase_time",
        "offset": 0,
        "length": 500,
        "store_id": [store_id],
        "platform_code": [10024],  # Temu半托管
    }
    
    print(f"\n【请求参数】")
    print(f"{req_body}")
    
    print(f"\n【调用 API】/pb/mp/order/v2/list ...")
    
    try:
        resp = await get_api_resp(req_body, api_path="/pb/mp/order/v2/list")
        
        print(f"\n【原始返回值】")
        print(f"resp 类型: {type(resp)}")
        print(f"resp: {resp}")
        
        # 尝试提取数据
        print(f"\n【数据提取】")
        if resp is None:
            print("resp is None")
            data_list = []
        else:
            _data = getattr(resp, "data", None) or resp
            print(f"_data 类型: {type(_data)}")
            print(f"_data: {_data}")
            
            if isinstance(_data, dict):
                data_list = _data.get("list") or []
                print(f"data_list 长度: {len(data_list)}")
                # 如果有数据，打印第一条看看结构
                if data_list:
                    print(f"\n【第一条订单数据示例】")
                    print(f"{data_list[0]}")
            else:
                print(f"_data 不是字典，无法提取 list")
                data_list = []
        
        print(f"\n【结论】")
        print(f"共获取到 {len(data_list)} 条订单")
        
    except Exception as e:
        print(f"\n【异常】")
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(debug_single_store())
