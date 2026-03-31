# Task 对外接口文档

本文档说明 `task` 模块当前开放的三个无需登录、可供外部系统调用的接口。

## 接口概览

1. 更新主任务状态
   `POST /api/external/tasks/update-status/`
2. 获取主任务及全部子任务详情
   `GET/POST /api/external/tasks/detail/`
3. 更新子任务状态
   `POST /api/external/tasks/subtasks/update-status/`

代码位置：

- [task_api_views.py](/D:/Y-Project/Overlord/task/view/task_api_views.py)
- [urls.py](/D:/Y-Project/Overlord/task/urls.py)

当前特性：

- 无需登录
- 免 CSRF
- 支持通过 `id` 或 `task_no` 查询任务

当前限制：

- 暂未做 token、签名或 IP 白名单校验

---

## 1. 更新主任务状态接口

### 接口地址

`POST /api/external/tasks/update-status/`

### 接口用途

- 按 `id` 或 `task_no` 查找主任务
- 将主任务 `status` 更新为指定值
- 返回任务编号、任务名称和更新后的状态

### 支持的请求格式

- `application/json`
- `application/x-www-form-urlencoded`
- `multipart/form-data`

### 请求参数

| 参数名 | 必填 | 说明 |
|---|---|---|
| `id` | 否 | 主任务 ID，与 `task_no` 二选一 |
| `task_no` | 否 | 主任务单号，与 `id` 二选一 |
| `status` | 是 | 目标状态 |

说明：

- `id` 和 `task_no` 至少传一个
- 如果两个都传，当前逻辑优先按 `id` 查找

### 允许的状态值

- `draft`
- `pending`
- `in_progress`
- `completed`
- `failed`
- `cancelled`

### 请求示例 1：Python JSON

```python
import requests

url = "http://your-domain/api/external/tasks/update-status/"
payload = {
    "task_no": "TK20260306-001",
    "status": "completed"
}

response = requests.post(url, json=payload, timeout=10)
print(response.status_code)
print(response.json())
```

### 请求示例 2：Python 表单

```python
import requests

url = "http://your-domain/api/external/tasks/update-status/"
payload = {
    "id": 123,
    "status": "in_progress"
}

response = requests.post(url, data=payload, timeout=10)
print(response.status_code)
print(response.json())
```

### 成功响应

```json
{
  "success": true,
  "data": {
    "task_no": "TK20260306-001",
    "task_name": "任务标题",
    "status": "completed"
  }
}
```

### 失败响应示例

缺少 `status`

```json
{
  "success": false,
  "message": "缺少必要参数: status"
}
```

缺少 `id` 和 `task_no`

```json
{
  "success": false,
  "message": "缺少必要参数: id 或 task_no"
}
```

状态值非法

```json
{
  "success": false,
  "message": "无效的状态值，必须是: draft, pending, in_progress, completed, failed, cancelled"
}
```

任务不存在

```json
{
  "success": false,
  "message": "任务不存在"
}
```

### HTTP 状态码

- `200`：成功
- `400`：参数错误
- `404`：任务不存在
- `500`：服务端异常

---

## 2. 获取主任务详情接口

### 接口地址

`GET /api/external/tasks/detail/`

或

`POST /api/external/tasks/detail/`

### 接口用途

- 按 `id` 或 `task_no` 查询主任务
- 返回主任务信息
- 返回全部子任务信息
- 如果子任务类型是 `amazon_upload`，附带该子任务下的文件信息

### 支持的请求格式

- `GET query string`
- `POST application/json`
- `POST form-data`

### 请求参数

| 参数名 | 必填 | 说明 |
|---|---|---|
| `id` | 否 | 主任务 ID，与 `task_no` 二选一 |
| `task_no` | 否 | 主任务单号，与 `id` 二选一 |

### 请求示例 1：Python GET

```python
import requests

url = "http://your-domain/api/external/tasks/detail/"
params = {
    "task_no": "TK20260306-001"
}

response = requests.get(url, params=params, timeout=10)
print(response.status_code)
print(response.json())
```

### 请求示例 2：Python POST JSON

```python
import requests

url = "http://your-domain/api/external/tasks/detail/"
payload = {
    "id": 123
}

response = requests.post(url, json=payload, timeout=10)
print(response.status_code)
print(response.json())
```

### 成功响应结构

```json
{
  "success": true,
  "data": {
    "task": {
      "id": 123,
      "task_no": "TK20260306-001",
      "task_name": "任务标题",
      "title": "任务标题",
      "status": "in_progress",
      "status_display": "进行中",
      "task_type": "standard",
      "task_type_display": "标准任务",
      "created_by_id": 1,
      "created_by_name": "张三",
      "owner_id": 2,
      "owner_name": "李四",
      "created_at": "2026-03-06 10:00:00",
      "updated_at": "2026-03-06 10:30:00",
      "submitted_at": "2026-03-06 10:05:00"
    },
    "subtasks": [
      {
        "id": 11,
        "type": "divi_auto_upload",
        "type_display": "Divi自动上架",
        "status": "pending",
        "status_display": "待执行",
        "order": 0,
        "params": {
          "diwei_account": "测试",
          "operation": "custom",
          "gallery_path": "",
          "local_gallery_path": "",
          "export_rows": [],
          "custom_rows": []
        },
        "is_executed": false,
        "executed_at": null,
        "execution_result": {},
        "created_at": "2026-03-06 10:00:01",
        "updated_at": "2026-03-06 10:00:01"
      },
      {
        "id": 12,
        "type": "amazon_upload",
        "type_display": "Amazon上架",
        "status": "in_progress",
        "status_display": "进行中",
        "order": 1,
        "params": {
          "file_list": [],
          "file_paths": []
        },
        "is_executed": false,
        "executed_at": null,
        "execution_result": {},
        "created_at": "2026-03-06 10:01:00",
        "updated_at": "2026-03-06 10:20:00",
        "files": [
          {
            "id": 1001,
            "shop_name": "Amazon店铺A",
            "shop_name_suffix": "16张三",
            "filename": "16张三_TK20260306-001.xlsx",
            "target_path": "\\\\192.168.110.54\\overlord_555\\自动化\\amazon上货\\待上货文件\\Amazon店铺A\\16张三_TK20260306-001.xlsx",
            "status": "uploading",
            "status_display": "上传中",
            "success_sku": 10,
            "total_sku": 100,
            "progress": "10/100",
            "created_at": "2026-03-06 10:02:00",
            "uploaded_at": null
          }
        ]
      }
    ]
  }
}
```

### `task` 字段说明

| 字段 | 说明 |
|---|---|
| `id` | 主任务 ID |
| `task_no` | 任务单号 |
| `task_name` | 任务标题，便于外部系统直接使用 |
| `title` | 任务标题 |
| `status` | 主任务状态英文值 |
| `status_display` | 主任务状态中文值 |
| `task_type` | 任务类型英文值 |
| `task_type_display` | 任务类型中文值 |
| `created_by_id` | 创建人 ID |
| `created_by_name` | 创建人姓名/用户名 |
| `owner_id` | 负责人 ID |
| `owner_name` | 负责人姓名/用户名 |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |
| `submitted_at` | 提交时间，可能为 `null` |

### `subtasks[]` 字段说明

| 字段 | 说明 |
|---|---|
| `id` | 子任务 ID |
| `type` | 子任务类型英文值 |
| `type_display` | 子任务类型中文值 |
| `status` | 子任务状态英文值 |
| `status_display` | 子任务状态中文值 |
| `order` | 子任务排序 |
| `params` | 子任务原始参数 |
| `is_executed` | 是否已执行 |
| `executed_at` | 执行时间 |
| `execution_result` | 执行结果 |
| `created_at` | 子任务创建时间 |
| `updated_at` | 子任务更新时间 |
| `files` | 仅 `amazon_upload` 子任务存在 |

### `files[]` 字段说明

| 字段 | 说明 |
|---|---|
| `id` | 文件记录 ID |
| `shop_name` | 店铺名 |
| `shop_name_suffix` | 店铺后缀 |
| `filename` | 文件名 |
| `target_path` | 文件目标路径 |
| `status` | 文件状态英文值 |
| `status_display` | 文件状态中文值 |
| `success_sku` | 成功 SKU 数 |
| `total_sku` | 总 SKU 数 |
| `progress` | 进度，如 `10/100` |
| `created_at` | 创建时间 |
| `uploaded_at` | 完成时间 |

### 失败响应示例

缺少 `id` 和 `task_no`

```json
{
  "success": false,
  "message": "缺少必要参数: id 或 task_no"
}
```

任务不存在

```json
{
  "success": false,
  "message": "任务不存在"
}
```

### HTTP 状态码

- `200`：成功
- `400`：参数错误
- `404`：任务不存在
- `500`：服务端异常

---

## 对接建议

1. 外部系统优先使用 `task_no` 作为任务主键。
2. 更新状态时请只传允许的英文状态值，不要传中文。
3. 更新状态成功后，如需校验结果，可再调用详情接口确认。

---

## 安全建议

当前这三个接口都属于公开接口，任何知道地址的人都可以直接访问。

建议尽快至少补一种保护机制：

- 固定 `token`
- `app_key + timestamp + sign`
- Nginx / 网关 IP 白名单
- 上游反向代理访问控制

---

## 3. 更新子任务状态接口

### 接口地址

`POST /api/external/tasks/subtasks/update-status/`

### 接口用途

- 按 `task_id` 和 `subtask_id` 精确定位子任务
- 校验该子任务是否属于指定主任务
- 将子任务 `status` 更新为指定值
- 返回子任务 ID 和更新后的状态

### 支持的请求格式

- `application/json`
- `application/x-www-form-urlencoded`
- `multipart/form-data`

### 请求参数

| 参数名 | 必填 | 说明 |
|---|---|---|
| `task_id` | 是 | 主任务 ID |
| `subtask_id` | 是 | 子任务 ID |
| `status` | 是 | 目标状态 |

### 允许的状态值

- `draft`
- `pending`
- `in_progress`
- `completed`
- `failed`
- `cancelled`

### 状态联动说明

- 当状态更新为 `completed` 或 `failed` 时，会同步将 `is_executed` 设为 `true`
- 当状态首次进入 `completed` 或 `failed` 时，如果 `executed_at` 为空，会自动写入当前时间
- 当状态更新为 `draft`、`pending`、`in_progress` 或 `cancelled` 时，会同步将 `is_executed` 设为 `false`

### 请求示例 1：Python JSON

```python
import requests

url = "http://your-domain/api/external/tasks/subtasks/update-status/"
payload = {
    "task_id": 123,
    "subtask_id": 456,
    "status": "completed"
}

response = requests.post(url, json=payload, timeout=10)
print(response.status_code)
print(response.json())
```

### 请求示例 2：Python 表单

```python
import requests

url = "http://your-domain/api/external/tasks/subtasks/update-status/"
payload = {
    "task_id": 123,
    "subtask_id": 456,
    "status": "in_progress"
}

response = requests.post(url, data=payload, timeout=10)
print(response.status_code)
print(response.json())
```

### 成功响应

```json
{
  "success": true,
  "data": {
    "subtask_id": 456,
    "status": "completed"
  }
}
```

### 失败响应示例

缺少参数

```json
{
  "success": false,
  "message": "缺少必要参数: task_id, subtask_id, status"
}
```

状态值非法

```json
{
  "success": false,
  "message": "无效的状态值，必须是: draft, pending, in_progress, completed, failed, cancelled"
}
```

主任务不存在

```json
{
  "success": false,
  "message": "主任务不存在"
}
```

子任务不存在

```json
{
  "success": false,
  "message": "子任务不存在"
}
```

子任务不属于该主任务

```json
{
  "success": false,
  "message": "子任务不属于该主任务"
}
```

### HTTP 状态码

- `200`：成功
- `400`：参数错误
- `404`：主任务或子任务不存在
- `500`：服务端异常
