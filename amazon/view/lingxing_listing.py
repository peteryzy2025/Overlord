from api.lingxing.Y_OpenApi import get_api_resp
import asyncio
import json
import os
from datetime import datetime



async def get_lingxing_listing(sid):
    """
    获取领星店铺列表
    """
    resp = await get_api_resp(
        req_body={
            "sid": sid
        },
        api_path="/erp/sc/data/mws/listing",
        method="POST"
    )
    print(f"数据条数: {len(resp.data)}")
    
    # 将数据转换为JSON格式并写入文件（仅保存原始接口返回数据）
    json_data = json.dumps(resp.data, ensure_ascii=False, indent=2)
    
    # 创建输出目录（如果不存在）
    output_dir = "output"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # 生成文件名（包含时间戳和店铺ID）
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{output_dir}/lingxing_listing_sid{sid}_{timestamp}.txt"
    
    # 写入文件（仅保存原始数据，不添加额外信息）
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(json_data)
    
    print(f"数据已写入文件: {filename}")
    print(f"文件大小: {os.path.getsize(filename)} 字节")
    print(f"数据条数: {len(resp.data)}")
    
    return resp.data


asyncio.run(get_lingxing_listing(522144))