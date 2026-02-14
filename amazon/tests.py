2
import os
import sys
import asyncio
import json
from decimal import Decimal, InvalidOperation
from datetime import datetime

# ====== Django 初始化部分（必须先执行） ======
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")

import django
django.setup()

# Django 配置完成后才能导入以下模块
from django.db import transaction
from django.utils.dateparse import parse_datetime
from api.Y.y_tiem import Timer
from api.lingxing.Y_OpenApi import get_api_resp
from theme.view.views_trend import analyze_theme_trend



# async def get_lingxing_listing(sid):
#     """
#     获取领星店铺列表
#     """
#     resp = await get_api_resp(
#         req_body={
#             "sid": sid
#         },
#         api_path="/erp/sc/data/mws/listing",
#         method="POST"
#     )
#     print(f"数据条数: {len(resp.data)}")
#
#     # 将数据转换为JSON格式并写入文件（仅保存原始接口返回数据）
#     json_data = json.dumps(resp.data, ensure_ascii=False, indent=2)
#
#     # 创建输出目录（如果不存在）
#     output_dir = "output"
#     if not os.path.exists(output_dir):
#         os.makedirs(output_dir)
#
#     # 生成文件名（包含时间戳和店铺ID）
#     timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
#     filename = f"{output_dir}/lingxing_listing_sid{sid}_{timestamp}.txt"
#
#     # 写入文件（仅保存原始数据，不添加额外信息）
#     with open(filename, 'w', encoding='utf-8') as f:
#         f.write(json_data)
#
#     print(f"数据已写入文件: {filename}")
#     print(f"文件大小: {os.path.getsize(filename)} 字节")
#     print(f"数据条数: {len(resp.data)}")
#
#     return resp.data

#total: 数据总数
#offset：获取第x页的数据，但建议先用total获取数据总数，再根据总数/1000(每页1000条)计算需要获取的页数

async def lingxing_api_info_getter(sid):
    """
    获取领星店铺列表
    """
    # total: 数据总数
    # offset：获取第x页的数据，但建议先用total获取数据总数，再根据总数/1000(每页1000条)计算需要获取的页数
    counts = 0
    resp = await get_api_resp(
        req_body={
            "sid": sid,
            "offset": 0,
            "search_field":"asin",
            "search_value":["B0FGNNBP98"]
        },
        api_path="/erp/sc/data/mws/listing",
        method="POST"
    )
    # print(resp)
    for i in resp.data:
        item_name = i.get("item_name", "")
        print(item_name)


    # 将数据转换为JSON格式并写入文件（仅保存原始接口返回数据）
    # json_data = json.dumps(resp.data, ensure_ascii=False, indent=2)
    #
    # # 创建输出目录（如果不存在）
    # output_dir = "output"
    # if not os.path.exists(output_dir):
    #     os.makedirs(output_dir)
    #
    # # 生成文件名（包含时间戳和店铺ID）
    # timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # filename = f"{output_dir}/lingxing_listing_sid{sid}_{timestamp}.txt"
    #
    # # 写入文件（仅保存原始数据，不添加额外信息）
    # with open(filename, 'a', encoding='utf-8') as f:
    #     f.write(json_data)
    # print(f"数据已写入文件: {filename}")
    # print(f"文件大小: {os.path.getsize(filename)} 字节")
    # print(f"数据条数: {len(resp.data)}")
    # # print(resp.data)
    return resp.data


#======================构造表格所需数据======================
def get_lingxing_api_info(sid):
    """
    获取领星API数据，返回JSON字符串
    如果API返回空或出错，返回None
    """
    try:
        info = asyncio.run(lingxing_api_info_getter(sid))
        if not info:
            print(f"sid={sid}, API返回为空")
            return None
        json_data = json.dumps(info, ensure_ascii=False, indent=2)
        return json_data
    except Exception as e:
        print(f"sid={sid}, API调用异常: {e}")
        return None

def process_lingxing_api_info(json_data, shop_name, amazon_shop_name, shop_owner, limit=None):
    """
    处理领星店铺列表数据，返回listing列表

    Args:
        json_data: API 返回的 JSON 数据
        shop_name: 领星店铺名称
        amazon_shop_name: Amazon 店铺名称
        shop_owner: 店铺负责人
        limit: 最多返回的数据条数，None 表示不限制
    """
    # 1. 检查空值
    if not json_data:
        return []

    # 2. 解析 JSON 数据
    try:
        data = json.loads(json_data)
    except json.JSONDecodeError as e:
        print(f"JSON解析失败: {e}")
        return []

    # 3. 检查数据是否为列表
    if not isinstance(data, list):
        print(f"API返回数据格式错误，期望list，实际: {type(data)}")
        return []
    else:
        return data

    result = []
    # 4. 提取需要的字段
    # for item in data:
    #     # 如果已达到限制条数，停止处理
    #     if limit is not None and len(result) >= limit:
    #         break
    #
    #     item_name = item.get("item_name", "")
    #
    #     # 过滤掉 title 为空的数据项
    #     if not item_name or not item_name.strip():
    #         continue
    #
    #     tro_words_analyze = analyze_theme_trend(item_name)
    #     title_risk_level = tro_words_analyze.get("theme_risk_text", "")
    #
    #     if title_risk_level == "low":
    #         continue
    #
    #     tro_words_origin = []
    #     if len(tro_words_analyze.get('uspto_keywords')) != 0:
    #         tro_words_origin.append("美标网")
    #     if len(tro_words_analyze.get('tro_keywords')) != 0:
    #         tro_words_origin.append("数据库")
    #
    #     asin = item.get("asin", "")
    #     high_risk_list = tro_words_analyze.get("high_risk_words", [])
    #     medium_risk_list = tro_words_analyze.get("medium_risk_words", [])
    #
    #     item_result = {
    #         "amazon_shop_name": amazon_shop_name,
    #         "shop_name": shop_name,
    #         "shop_owner": shop_owner,
    #         "asin": asin,
    #         "title": item_name,
    #         "title_risk_level": title_risk_level,
    #         "high_risk_list": high_risk_list,
    #         "medium_risk_list": medium_risk_list,
    #         "tro_words_origin": tro_words_origin,
    #     }
    #     result.append(item_result)
    #
    # return result


# 测试代码（手动运行时取消注释）
if __name__ == "__main__":
    json_data = get_lingxing_api_info("521738")
    # result = process_lingxing_api_info(json_data, "领星店铺", "美国店铺", "领星")
    # print(result)
    # print(f"共获取 {len(result)} 条数据")

