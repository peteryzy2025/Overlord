"""
更新巡店记录 - 影刀调用示例
使用方法：复制整个代码到影刀的 Python 代码块中
"""

import requests

BASE_URL = "http://192.168.110.55:5555/amazon/api"


def update_daily_check(
    record_id,
    visited=None,
    performance_checked=None,
    withdrawal_processed=None,
    withdrawal_amount=None,
    last_restock_date=None,
    shop_status=None,
    is_restricted=None,
    restricted_regions=None
):
    """
    更新巡店日报记录
    
    参数：
        record_id (int): 【必填】巡店记录ID
        visited (bool): 是否进入店铺，True/False
        performance_checked (bool): 是否检查绩效，True/False
        withdrawal_processed (bool): 是否处理提现，True/False
        withdrawal_amount (float): 提现金额，如 1000.50
        last_restock_date (str): 最后上货日期，格式 "YYYY-MM-DD"，传空则清空
        shop_status (str): 店铺状况描述
        is_restricted (bool): 是否受限，True/False ← 新增
        restricted_regions (list): 受限地区列表，如 ["加拿大", "美国", "墨西哥"] ← 新增
    """
    url = f"{BASE_URL}/shop-check/update/"
    
    # 构建请求数据（只添加有值的参数）
    data = {"id": record_id}
    
    if visited is not None:
        data["visited"] = visited
    if performance_checked is not None:
        data["performance_checked"] = performance_checked
    if withdrawal_processed is not None:
        data["withdrawal_processed"] = withdrawal_processed
    if withdrawal_amount is not None:
        data["withdrawal_amount"] = withdrawal_amount
    if last_restock_date is not None:
        data["last_restock_date"] = last_restock_date
    if shop_status is not None:
        data["shop_status"] = shop_status
    if is_restricted is not None:
        data["is_restricted"] = is_restricted
    if restricted_regions is not None:
        data["restricted_regions"] = restricted_regions
    
    try:
        response = requests.post(url, json=data, timeout=30)
        result = response.json()
        
        if result.get("success"):
            print(f"✅ 更新成功：记录ID={record_id}")
        else:
            print(f"❌ 更新失败：{result.get('message')}")
        
        return result
        
    except Exception as e:
        print(f"❌ 请求异常：{e}")
        return {"success": False, "message": str(e)}


# ========== 使用示例 ==========

# 示例1：标记店铺受限
# update_daily_check(
#     record_id=123,
#     is_restricted=True,
#     restricted_regions=["加拿大", "美国", "墨西哥"]
# )

# 示例2：取消受限
# update_daily_check(
#     record_id=123,
#     is_restricted=False,
#     restricted_regions=[]
# )

# 示例3：同时更新多个字段
# update_daily_check(
#     record_id=123,
#     visited=True,
#     performance_checked=True,
#     shop_status="正常运营",
#     is_restricted=True,
#     restricted_regions=["加拿大"]
# )

# 示例4：清空上货日期
# update_daily_check(
#     record_id=123,
#     last_restock_date=""  # 传空字符串清空
# )
