# 审批系统模型设计说明

## 一、整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                        审批系统架构                          │
└─────────────────────────────────────────────────────────────┘

【核心流程】
申请人创建审批 → 生成审批步骤（1级/2级/...） → 逐级审批 → 通过/驳回
                              ↓
                    通过后创建执行配置（店铺+ASIN）
                              ↓
                    RPA按组独立执行（每组独立状态追踪）
```

---

## 二、模型关系图

```
┌─────────────────────────────────────────────────────────────────┐
│                        NegativeKeywordLibrary                    │
│                         否定词库（官方/个人）                     │
│  ┌────────────────┐  ┌────────────────┐                        │
│  │   官方词库     │  │   个人词库     │                        │
│  │  lib_type=official│ │ lib_type=personal│                      │
│  └────────────────┘  └────────────────┘                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ 被引用
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                          Approval                               │
│                        审批主表（通用）                          │
├─────────────────────────────────────────────────────────────────┤
│  approval_no    : 审批单号（唯一）                               │
│  approval_type  : 审批类型（amazon_ad）                          │
│  applicant      : 申请人（外键→User）                            │
│  status         : 状态（draft/pending/approved/rejected）       │
│  current_step_sequence : 当前步骤序号                            │
│  total_steps    : 总步骤数                                       │
│  original_approval     : 原审批单（驳回后重提时关联）             │
└─────────────────────────────────────────────────────────────────┘
       │                    │                    │
       │ 1:N                │ 1:1                │ 1:N
       ▼                    ▼                    ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────────────┐
│ ApprovalStep  │   │AmazonAdApproval│   │ AmazonAdShopConfig   │
│   审批步骤     │   │  开广告详情    │   │   店铺-ASIN组        │
├───────────────┤   ├───────────────┤   ├───────────────────────┤
│sequence       │   │approval (1:1) │   │amazon_ad (FK)         │
│step_name      │   │remark         │   │lingxing_shop (FK)     │
│approver (FK)  │   └───────────────┘   │asins (M:N)            │
│status         │                        │negative_keyword_lib   │
└───────────────┘                        │exec_status            │
       │ 1:N                             │webhook_task_id        │
       ▼                                  └───────────────────────┘
┌───────────────┐
│ApprovalRecord │
│   审批记录     │
├───────────────┤
│step (FK)      │
│approver (FK)  │
│result         │
│comment        │
└───────────────┘
```

---

## 三、各模型详细说明

### 1. NegativeKeywordLibrary（否定词库）

**用途**：存储官方和个人否定词库

| 字段 | 说明 | 示例 |
|------|------|------|
| company | 所属公司 | 数据隔离 |
| lib_type | 词库类型 | `official`官方 / `personal`个人 |
| name | 词库名称 | "标准否定词库" |
| keywords | 否定词列表 | `["free", "cheap", "wholesale"]` |
| created_by | 创建人 | 官方词库为空 |

**场景**：
- 官方词库：运营管理人员统一维护，全公司通用
- 个人词库：运营人员自己创建，仅自己使用

---

### 2. Approval（审批主表）

**用途**：所有审批流程的统一入口

| 字段 | 说明 |
|------|------|
| approval_no | 唯一单号，如 "AP20250401001" |
| status | 整体状态：草稿/审批中/已通过/已驳回 |
| current_step_sequence | 当前进行到哪一步（从1开始） |
| total_steps | 总共有多少步（如2级审批=2） |
| original_approval | 驳回后重新提交时，指向原审批单 |

**多级审批流转示例**：
```
创建审批 → status=draft, current_step_sequence=0
提交审批 → status=pending, current_step_sequence=1
组长通过 → current_step_sequence=2
主管通过 → status=approved, current_step_sequence=2
```

---

### 3. ApprovalStep（审批步骤）

**用途**：定义审批流程的每一步

**特点**：
- 创建审批时，根据规则生成（如2级就生成2条记录）
- 每步都有指定的审批人（approver）
- 支持任意级数（1级、2级、3级...）

**状态流转**：
```
pending（待审批） → completed（已完成）
                              ↓
                       触发下一步/结束
```

---

### 4. ApprovalRecord（审批记录）

**用途**：记录实际的审批操作

**设计原因**：
- 一个步骤可能有多个记录（如驳回后重提）
- 记录谁、什么时候、什么结果、什么意见

**示例记录**：
```
步骤1：组长审批
  ├─ Record1: 组长A通过（2024-04-01 10:00）
  └─ Record2: 组长B通过（2024-04-01 11:00）[重提后的记录]
```

---

### 5. AmazonAdApproval（开广告审批详情）

**用途**：开广告业务的特有字段

**关系**：与 Approval 一对一

| 字段 | 说明 |
|------|------|
| approval | 关联审批主表 |
| remark | 备注信息 |

**为什么拆表**：
- 审批主表是通用的（以后可能有FBA发仓、价格调整等审批）
- 每种业务有自己的详情表

---

### 6. AmazonAdShopConfig（店铺-ASIN组）

**用途**：一个审批可以有多组"店铺+ASIN+否定词库"配置

**核心设计**：
- **多店铺**：一个审批可以开多个店铺的广告
- **同店铺多ASIN组**：同一店铺可多次出现（只要ASIN不同）
- **独立执行**：每组独立追踪执行状态

**示例配置**：
```
审批单：开广告申请-001
├─ 组1：店铺A + ASIN[1,2,3] + 词库X → 待执行
├─ 组2：店铺A + ASIN[4,5] + 词库Y → 执行中
└─ 组3：店铺B + ASIN[6,7] + 词库X → 执行成功
```

| 字段 | 说明 |
|------|------|
| lingxing_shop | 领星店铺（外键） |
| asins | ASIN列表（多对多→AmazonListingV2） |
| negative_keyword_lib | 选用的否定词库 |
| exec_status | 执行状态（pending/executing/completed/failed） |
| webhook_task_id | RPA任务ID，用于匹配回调 |
| sequence | 执行顺序（控制RPA执行先后） |

---

## 四、业务流程示例

### 场景：运营申请开广告（2级审批）

```
【步骤1】运营创建申请
├─ 创建 Approval（status=draft）
├─ 创建 AmazonAdApproval（关联详情）
├─ 创建 2个 ApprovalStep：
│   ├─ Step1: sequence=1, approver=组长ID, step_name="组长审批"
│   └─ Step2: sequence=2, approver=主管ID, step_name="主管审批"
└─ 创建 2个 AmazonAdShopConfig：
    ├─ Config1: 店铺A + ASIN[1,2] + 词库X
    └─ Config2: 店铺B + ASIN[3,4] + 词库Y

【步骤2】运营提交申请
└─ Approval.status → pending
└─ Approval.current_step_sequence → 1

【步骤3】组长审批
├─ 创建 ApprovalRecord（step=Step1, result=approved）
├─ Step1.status → completed
└─ Approval.current_step_sequence → 2

【步骤4】主管审批
├─ 创建 ApprovalRecord（step=Step2, result=approved）
├─ Step2.status → completed
├─ Approval.status → approved
└─ AmazonAdShopConfig.exec_status → pending（等待RPA执行）

【步骤5】RPA执行
├─ Config1: exec_status → executing → completed（回调成功）
└─ Config2: exec_status → executing → failed（回调失败）
```

### 场景：审批被驳回后重提

```
【步骤1】原审批被驳回
├─ 创建 ApprovalRecord（result=rejected）
└─ Approval.status → rejected

【步骤2】运营复制申请
├─ 创建新 Approval（所有字段复制）
├─ Approval.original_approval = 原审批单ID
├─ 重新生成 ApprovalStep
├─ 复制 AmazonAdApproval
└─ 复制 AmazonAdShopConfig

【步骤3】重新提交
└─ 重新走审批流程
```

---

## 五、查询示例

### 1. 查看我的待审批列表
```python
# 我作为审批人，且步骤状态为 pending 的审批
Approval.objects.filter(
    steps__approver=current_user,
    steps__status='pending',
    status='pending'
).distinct()
```

### 2. 查看审批进度
```python
approval = Approval.objects.get(approval_no='AP20250401001')

# 总进度
print(f"当前第{approval.current_step_sequence}步 / 共{approval.total_steps}步")

# 详细步骤
for step in approval.steps.order_by('sequence'):
    print(f"{step.step_name}: {step.get_status_display()}")
    # 显示审批记录
    for record in step.records.all():
        print(f"  - {record.approver}: {record.get_result_display()}")
```

### 3. 查看执行状态
```python
# 某开广告审批的所有店铺配置及执行状态
ad_approval = AmazonAdApproval.objects.get(approval__approval_no='AP20250401001')

for config in ad_approval.shop_configs.all():
    print(f"{config.lingxing_shop.name}: {config.get_exec_status_display()}")
    print(f"  ASINs: {list(config.asins.values_list('asin', flat=True))}")
```

---

## 六、扩展性说明

### 1. 新增审批类型（如FBA发仓）

只需新增详情表，无需改审批主表：

```python
class FBAWarehouseApproval(models.Model):
    approval = models.OneToOneField(Approval, on_delete=models.CASCADE)
    plan_name = models.CharField(max_length=200)
    skus = models.JSONField()  # [{"sku": "ABC", "qty": 100}]
    destination = models.CharField(max_length=100)
```

### 2. 支持3级、4级审批

无需改模型，创建时多生成几个 Step 即可：

```python
# 3级审批
ApprovalStep.objects.create(approval=approval, sequence=1, approver=组长)
ApprovalStep.objects.create(approval=approval, sequence=2, approver=经理)
ApprovalStep.objects.create(approval=approval, sequence=3, approver=总监)
approval.total_steps = 3
approval.save()
```

### 3. 不同业务不同审批流

可以在 Approval 上加 `workflow_template` 字段，预先定义审批模板。

---

## 七、注意事项

1. **公司隔离**：所有表都有 `company` 字段，查询时默认过滤
2. **ASIN验证**：业务层需验证 ASIN 是否属于对应的领星店铺（模型不强制校验）
3. **词库选择**：只能是官方词库或个人词库，二选一
4. **执行状态**：RPA按组执行，每组独立回调更新状态
