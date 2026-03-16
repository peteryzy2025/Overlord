"""
亚马逊巡店 API - 影刀调用示例
使用方法：复制整个代码到影刀的 Python 代码块中
"""

import requests
import json

# ==================== 配置区域 ====================
# 修改为你的服务器地址
BASE_URL = "http://你的服务器地址/amazon/api/shop-check"
# 示例：
# BASE_URL = "http://192.168.1.100:8000/amazon/api/shop-check"
# BASE_URL = "http://localhost:8000/amazon/api/shop-check"


# ==================== 接口1：初始化当日巡店 ====================
def init_daily_shop_check(
    shop_status=None,
    browser=None,
    project_id=None,
    check_date=None
):
    """
    初始化今日巡店记录
    
    参数说明：
        shop_status (str): 店铺状态，如 "正常"、"停用"，不传则不过滤
        browser (str): 浏览器，如 "闪店"、"紫鸟"，不传则不过滤
        project_id (int): 项目ID，如 1，不传则不过滤
        check_date (str): 日期格式 "YYYY-MM-DD"，不传则默认今天
    
    返回示例：
        {
            "success": True,
            "data": {
                "check_date": "2026-03-16",
                "total_shops": 100,
                "inserted": 80,
                "skipped": 20
            }
        }
    """
    url = f"{BASE_URL}/init/"
    
    # 构建请求数据（只添加有值的参数）
    data = {}
    if shop_status:
        data["shop_status"] = shop_status
    if browser:
        data["browser"] = browser
    if project_id is not None:
        data["project_id"] = project_id
    if check_date:
        data["check_date"] = check_date
    
    try:
        response = requests.post(url, json=data, timeout=30)
        result = response.json()
        
        if result.get("success"):
            data = result.get("data", {})
            print(f"✅ 初始化成功")
            print(f"   日期：{data.get('check_date')}")
            print(f"   总店铺数：{data.get('total_shops')}")
            print(f"   新增记录：{data.get('inserted')}")
            print(f"   跳过记录：{data.get('skipped')}")
        else:
            print(f"❌ 初始化失败：{result.get('message')}")
        
        return result
        
    except Exception as e:
        print(f"❌ 请求异常：{e}")
        return {"success": False, "message": str(e)}


# ==================== 接口2：获取巡店列表 ====================
def get_daily_check_list(
    check_date=None,
    shop_status=None,
    browser=None,
    project_id=None,
    visited=None,
    performance_checked=None,
    withdrawal_processed=None
):
    """
    获取巡店日报列表
    
    参数说明：
        check_date (str): 日期格式 "YYYY-MM-DD"，不传则默认今天
        shop_status (str): 按店铺状态筛选，如 "正常"
        browser (str): 按浏览器筛选，如 "闪店"
        project_id (int): 按项目ID筛选，如 1
        visited (bool): 按是否访问筛选，True/False
        performance_checked (bool): 按是否检查绩效筛选，True/False
        withdrawal_processed (bool): 按是否提现筛选，True/False
    
    返回：记录列表
    """
    url = f"{BASE_URL}/list/"
    
    # 构建查询参数
    params = {}
    if check_date:
        params["check_date"] = check_date
    if shop_status:
        params["shop_status"] = shop_status
    if browser:
        params["browser"] = browser
    if project_id is not None:
        params["project_id"] = project_id
    if visited is not None:
        params["visited"] = "true" if visited else "false"
    if performance_checked is not None:
        params["performance_checked"] = "true" if performance_checked else "false"
    if withdrawal_processed is not None:
        params["withdrawal_processed"] = "true" if withdrawal_processed else "false"
    
    try:
        response = requests.get(url, params=params, timeout=30)
        result = response.json()
        
        if result.get("success"):
            data = result.get("data", {})
            records = data.get("records", [])
            
            print(f"✅ 查询成功")
            print(f"   日期：{data.get('check_date')}")
            print(f"   总记录：{data.get('total')} | 已检查：{data.get('checked')} | 未检查：{data.get('unchecked')}")
            
            return records
        else:
            print(f"❌ 查询失败：{result.get('message')}")
            return []
        
    except Exception as e:
        print(f"❌ 请求异常：{e}")
        return []


# ==================== 接口3：更新巡店记录 ====================
def update_daily_check(
    record_id,
    visited=None,
    performance_checked=None,
    withdrawal_processed=None,
    withdrawal_amount=None,
    last_restock_date=None,
    shop_status=None
):
    """
    更新巡店日报记录
    
    参数说明：
        record_id (int): 【必填】巡店记录ID
        visited (bool): 是否进入店铺，True/False
        performance_checked (bool): 是否检查绩效，True/False
        withdrawal_processed (bool): 是否处理提现，True/False
        withdrawal_amount (float): 提现金额，如 1000.50
        last_restock_date (str): 最后上货日期，格式 "YYYY-MM-DD"
        shop_status (str): 店铺状况描述
    
    返回示例：
        {
            "success": True,
            "data": {
                "id": 1,
                "visited": True,
                "performance_checked": True,
                ...
            }
        }
    """
    url = f"{BASE_URL}/update/"
    
    # 构建请求数据
    data = {"id": record_id}
    
    if visited is not None:
        data["visited"] = visited
    if performance_checked is not None:
        data["performance_checked"] = performance_checked
    if withdrawal_processed is not None:
        data["withdrawal_processed"] = withdrawal_processed
    if withdrawal_amount is not None:
        data["withdrawal_amount"] = withdrawal_amount
    if last_restock_date:
        data["last_restock_date"] = last_restock_date
    if shop_status:
        data["shop_status"] = shop_status
    
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


# ==================== 使用示例 ====================

# 示例1：初始化今日巡店（筛选条件）
# init_daily_shop_check(
#     shop_status="正常",
#     browser="闪店",
#     project_id=1
# )

# 示例2：获取今天的所有巡店记录
# records = get_daily_check_list()

# 示例3：获取今天未访问的店铺
# unchecked_records = get_daily_check_list(visited=False)

# 示例4：获取指定日期的、项目ID=1的、未检查绩效的店铺
# records = get_daily_check_list(
#     check_date="2026-03-16",
#     project_id=1,
#     performance_checked=False
# )

# 示例5：更新巡店记录（标记为已访问、已检查绩效）
# update_daily_check(
#     record_id=123,
#     visited=True,
#     performance_checked=True,
#     shop_status="正常运营"
# )

# 示例6：更新巡店记录（记录提现信息）
# update_daily_check(
#     record_id=123,
#     withdrawal_processed=True,
#     withdrawal_amount=1500.00,
#     last_restock_date="2026-03-10"
# )

# ==================== 完整业务流程示例 ====================

def run_daily_check_workflow(project_id=None):
    """
    完整的巡店流程示例
    1. 初始化今日巡店
    2. 获取未访问的店铺列表
    3. 遍历处理每个店铺
    4. 更新巡店记录
    """
    print("=" * 50)
    print("开始执行巡店流程")
    print("=" * 50)
    
    # 步骤1：初始化
    print("\n【步骤1】初始化今日巡店...")
    init_result = init_daily_shop_check(
        shop_status="正常",
        browser="闪店",
        project_id=project_id
    )
    
    if not init_result or not init_result.get("success"):
        print("初始化失败，退出流程")
        return
    
    # 步骤2：获取未访问的店铺
    print("\n【步骤2】获取未访问店铺列表...")
    records = get_daily_check_list(
        visited=False,
        project_id=project_id
    )
    
    if not records:
        print("没有需要处理的店铺")
        return
    
    print(f"共找到 {len(records)} 个未访问店铺")
    
    # 步骤3：遍历处理每个店铺
    print("\n【步骤3】开始处理店铺...")
    for record in records:
        record_id = record.get("id")
        shop_name = record.get("shop_name")
        
        print(f"\n正在处理：{shop_name} (ID:{record_id})")
        
        # ============================================
        # 在这里插入影刀的巡店操作
        # 例如：
        # - 打开浏览器
        # - 登录店铺后台
        # - 检查绩效通知
        # - 处理提现
        # 等等...
        # ============================================
        
        # 模拟操作结果（实际使用时根据影刀执行结果设置）
        visit_success = True           # 是否成功访问店铺
        performance_ok = True          # 是否检查了绩效
        need_withdrawal = False        # 是否需要提现
        withdrawal_money = None        # 提现金额
        
        # 步骤4：更新记录
        update_data = {
            "record_id": record_id,
            "visited": visit_success,
            "performance_checked": performance_ok,
            "withdrawal_processed": need_withdrawal,
            "shop_status": "正常运营"
        }
        
        if need_withdrawal and withdrawal_money:
            update_data["withdrawal_amount"] = withdrawal_money
        
        update_daily_check(**update_data)
    
    print("\n" + "=" * 50)
    print("巡店流程执行完成")
    print("=" * 50)


# 运行完整流程（取消注释即可执行）
# run_daily_check_workflow(project_id=1)
