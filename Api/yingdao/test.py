import requests
import time
from typing import Dict, List, Any, Optional, Generator
from datetime import datetime


class YingdaoAPIClient:
    """
    影刀RPA API客户端

    已实现接口：
    - 鉴权（自动token缓存与刷新）
    - 查询机器人任务队列（支持分页）
    - 查询任务&机器人应用运行详情
    - 查询任务运行结果（支持轮询）
    """

    # ==================== 状态枚举 ====================
    class AppStatus:
        """应用运行状态枚举"""
        WAITING = "waiting"  # 等待调度
        CREATED = "created"  # 已创建
        RUNNING = "running"  # 运行中
        FINISH = "finish"  # 完成
        FAIL = "fail"  # 失败
        STOP = "stop"  # 已停止
        TIMEOUT = "timeout"  # 超时

        @classmethod
        def is_terminal(cls, status: str) -> bool:
            """判断是否为终态"""
            return status in [cls.FINISH, cls.FAIL, cls.STOP, cls.TIMEOUT]

    class TaskStatus:
        """任务运行状态枚举"""
        CREATED = "created"  # 已创建
        WAITING = "waiting"  # 等待调度
        RUNNING = "running"  # 运行中
        FINISH = "finish"  # 完成
        STOP = "stop"  # 已停止
        FAIL = "fail"  # 失败

        @classmethod
        def is_terminal(cls, status: str) -> bool:
            """判断是否为终态"""
            return status in [cls.FINISH, cls.STOP, cls.FAIL]

    class CursorDirection:
        """游标方向枚举"""
        PREVIOUS = "pre"  # 往前翻页
        NEXT = "next"  # 往后翻页

    # ==================== 初始化 ====================
    def __init__(self, access_key_id: str, access_key_secret: str,
                 base_url: str = "https://api.yingdao.com"):
        """
        初始化客户端

        Args:
            access_key_id: 从影刀控制台获取的accessKeyId
            access_key_secret: 从影刀控制台获取的accessKeySecret
            base_url: API基础地址，专有云请修改为对应地址
        """
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.base_url = base_url.rstrip('/')

        # Token缓存
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0
        self._buffer_time: int = 300  # 预留5分钟缓冲期

    # ==================== 鉴权 ====================
    def get_access_token(self) -> str:
        """
        获取accessToken，自动缓存并在过期前刷新

        Returns:
            accessToken字符串
        """
        current_time = time.time()

        # 缓存有效则直接返回
        if self._access_token and current_time < self._token_expires_at:
            return self._access_token

        # 重新获取
        url = f"{self.base_url}/oapi/token/v2/token/create"
        params = {
            "accessKeyId": self.access_key_id,
            "accessKeySecret": self.access_key_secret
        }

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        result = response.json()
        if not result.get("success"):
            raise Exception(f"获取token失败: {result.get('msg')} (code: {result.get('code')})")

        data = result["data"]
        token = data["accessToken"]
        expires_in = data["expiresIn"]

        self._access_token = token
        self._token_expires_at = current_time + expires_in - self._buffer_time

        return token

    def get_headers(self) -> Dict[str, str]:
        """获取包含认证的请求头"""
        return {
            "Authorization": f"Bearer {self.get_access_token()}",
            "Content-Type": "application/json"
        }

    # ==================== 基础请求 ====================
    def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """
        通用API请求方法

        Args:
            method: HTTP方法
            endpoint: API端点
            **kwargs: 传递给requests的其他参数

        Returns:
            API响应的JSON数据
        """
        url = f"{self.base_url}{endpoint}"
        headers = self.get_headers()

        if "headers" in kwargs:
            headers.update(kwargs.pop("headers"))

        response = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        response.raise_for_status()

        result = response.json()
        if not result.get("success"):
            raise Exception(f"API调用失败: {result.get('msg')} (code: {result.get('code')})")

        return result

    # ==================== 1. 查询机器人任务队列 ====================
    def query_job_list(self, robot_client_uuid: str,
                       cursor_direction: str = "next",
                       cursor_id: Optional[int] = None,
                       size: int = 20) -> Dict[str, Any]:
        """
        查询机器人任务队列

        Args:
            robot_client_uuid: 机器人uuid
            cursor_direction: 游标方向，pre表示往前翻，next表示往后翻
            cursor_id: 游标id，查询第一页时传None
            size: 每页数量（1-100）

        Returns:
            API响应数据，包含任务列表
        """
        endpoint = "/oapi/dispatch/v2/job/list"

        payload = {
            "robotClientUuid": robot_client_uuid,
            "cursorDirection": cursor_direction,
            "size": size
        }

        if cursor_id is not None:
            payload["cursorId"] = cursor_id

        return self._request("POST", endpoint, json=payload)

    def query_all_jobs(self, robot_client_uuid: str, size: int = 50) -> Generator[Dict[str, Any], None, None]:
        """
        查询机器人所有任务（自动分页）

        Args:
            robot_client_uuid: 机器人uuid
            size: 每页数量

        Yields:
            每个任务记录
        """
        cursor_id = None
        has_more = True

        while has_more:
            response = self.query_job_list(
                robot_client_uuid=robot_client_uuid,
                cursor_id=cursor_id,
                cursor_direction="next",
                size=size
            )

            jobs = response.get("data", [])
            if not jobs:
                break

            yield from jobs

            # 获取下一页的游标
            cursor_id = jobs[-1].get("id")
            has_more = len(jobs) >= size

    # ==================== 2. 查询任务&应用运行详情 ====================
    def query_task_process_detail(self, task_uuid: str,
                                  robot_client_uuid: str) -> Dict[str, Any]:
        """
        查询任务&机器人应用运行详情

        Args:
            task_uuid: 任务运行uuid
            robot_client_uuid: 机器人uuid

        Returns:
            包含jobList的应用运行详情
        """
        endpoint = "/oapi/dispatch/v2/task/process/detail"

        payload = {
            "taskUuid": task_uuid,
            "robotClientUuid": robot_client_uuid
        }

        return self._request("POST", endpoint, json=payload)

    # ==================== 3. 查询任务运行结果 ====================
    def query_task_result(self, task_uuid: str) -> Dict[str, Any]:
        """
        查询任务运行结果

        Args:
            task_uuid: 任务运行uuid

        Returns:
            任务运行结果及关联的job数据
        """
        endpoint = "/oapi/dispatch/v2/task/query"

        payload = {
            "taskUuid": task_uuid
        }

        return self._request("POST", endpoint, json=payload)

    def wait_for_task_completion(self, task_uuid: str,
                                 check_interval: int = 5,
                                 timeout: int = 3600) -> Dict[str, Any]:
        """
        等待任务完成（轮询）

        Args:
            task_uuid: 任务运行uuid
            check_interval: 检查间隔（秒）
            timeout: 超时时间（秒）

        Returns:
            最终任务运行结果

        Raises:
            TimeoutError: 超时
        """
        start_time = time.time()

        while True:
            result = self.query_task_result(task_uuid)
            data = result.get("data", {})

            if not data:
                raise Exception("未获取到任务数据")

            status = data.get("status")

            # 检查是否为终态
            if self.TaskStatus.is_terminal(status):
                return result

            # 检查超时
            elapsed = time.time() - start_time
            if elapsed > timeout:
                raise TimeoutError(f"任务等待超时（{timeout}秒）")

            # 等待后重试
            time.sleep(check_interval)

    # ==================== 4. 启动任务（辅助方法） ====================
    def start_task(self, robot_uuid: str, robot_client_uuid: str,
                   params: Optional[Dict[str, Any]] = None,
                   priority: str = "normal") -> str:
        """
        启动任务（快捷方法）

        Args:
            robot_uuid: 应用uuid
            robot_client_uuid: 机器人uuid
            params: 输入参数
            priority: 优先级

        Returns:
            taskUuid（任务运行uuid）
        """
        endpoint = "/oapi/dispatch/v2/task/start"

        payload = {
            "robotUuid": robot_uuid,
            "robotClientUuid": robot_client_uuid,
            "priority": priority
        }

        if params:
            payload["params"] = params

        result = self._request("POST", endpoint, json=payload)
        return result["data"]["taskUuid"]


# ==================== 使用示例 ====================
def demo_full_workflow():
    """
    完整工作流示例：启动任务 -> 轮询结果 -> 查询详情
    """
    # ===== 配置信息（请替换为您的实际值） =====
    CONFIG = {
        "access_key_id": "你的accessKeyId",
        "access_key_secret": "你的accessKeySecret",
        "base_url": "https://api.yingdao.com"  # 专有云请修改地址
    }

    ROBOT_CONFIG = {
        "robot_uuid": "your_robot_uuid",
        "robot_client_uuid": "your_robot_client_uuid"
    }

    # 初始化客户端
    client = YingdaoAPIClient(**CONFIG)

    try:
        # 示例1: 启动任务
        print("=" * 50)
        print("步骤1: 启动任务")
        task_uuid = client.start_task(
            robot_uuid=ROBOT_CONFIG["robot_uuid"],
            robot_client_uuid=ROBOT_CONFIG["robot_client_uuid"],
            params={"key": "value"}
        )
        print(f"任务已启动，taskUuid: {task_uuid}")

        # 示例2: 等待任务完成（轮询）
        print("=" * 50)
        print("步骤2: 等待任务完成...")
        final_result = client.wait_for_task_completion(
            task_uuid=task_uuid,
            check_interval=5,
            timeout=300
        )

        task_data = final_result["data"]
        print(f"任务已完成！")
        print(f"  - 状态: {task_data['status']} ({task_data['statusName']})")
        print(f"  - 开始时间: {task_data['startTime']}")
        print(f"  - 结束时间: {task_data.get('endTime', 'N/A')}")

        # 示例3: 查询应用运行详情
        print("=" * 50)
        print("步骤3: 查询应用运行详情")
        detail = client.query_task_process_detail(
            task_uuid=task_uuid,
            robot_client_uuid=ROBOT_CONFIG["robot_client_uuid"]
        )

        jobs = detail["data"]["jobList"]
        for i, job in enumerate(jobs, 1):
            print(f"应用 {i}: {job['robotName']}")
            print(f"  - 状态: {job['status']}")
            print(f"  - 开始时间: {job.get('startTime', 'N/A')}")
            print(f"  - 调度次数: {job['dispatchCount']}")
            if job.get("remark"):
                print(f"  - 备注: {job['remark']}")

        # 示例4: 查询机器人所有任务（分页）
        print("=" * 50)
        print("步骤4: 查询机器人最近任务")
        jobs = client.query_all_jobs(
            robot_client_uuid=ROBOT_CONFIG["robot_client_uuid"],
            size=10
        )

        print("最近10个任务：")
        for i, job in enumerate(jobs):
            if i >= 5:  # 只显示前5个
                break
            print(f"  - {job['robotName']} ({job['status']}) - {job['triggerTime']}")

        print("\n" + "=" * 50)
        print("✅ 所有操作完成！")

    except Exception as e:
        print(f"❌ 操作失败: {e}")
        raise


def demo_query_job_list():
    """示例：查询机器人任务队列（分页）"""
    client = YingdaoAPIClient(
        access_key_id="your_id",
        access_key_secret="your_secret"
    )

    robot_client_uuid = "your_robot_client_uuid"

    # 方式1: 单页查询
    print("方式1: 查询第一页")
    result = client.query_job_list(
        robot_client_uuid=robot_client_uuid,
        cursor_direction="next",
        size=20
    )

    jobs = result.get("data", [])
    print(f"获取到 {len(jobs)} 个任务")
    for job in jobs:
        print(f"  - {job['robotName']}: {job['status']} (ID: {job['id']})")

    # 方式2: 自动分页查询所有
    print("\n方式2: 自动查询所有任务")
    all_jobs = list(client.query_all_jobs(robot_client_uuid, size=50))
    print(f"总共 {len(all_jobs)} 个任务")


if __name__ == "__main__":
    # demo_full_workflow()
    # demo_query_job_list()
    pass