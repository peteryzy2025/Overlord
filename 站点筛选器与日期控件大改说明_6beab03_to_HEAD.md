# 站点筛选器与日期控件大改说明（`6beab03` ~ `c6b84a6`）

## 1. 范围与基线

- 起始提交：`6beab037cc85f2217ac9b97bbad8745a2ca70eb4`
- 结束提交：`c6b84a64c4acb63a906736058032aa9a5e8b65d7`（当前 `HEAD`）
- 时间范围：`2026-02-07` ~ `2026-02-09`
- 本文统计口径：仅统计以上 commit 区间内的**已提交改动**，不包含当前工作区未提交文件。

## 2. 总体改造目标（结合本次对话上下文）

本轮大改的核心目标是把全站筛选交互从“页面各自实现”升级为“统一组件 + 统一样式 + 统一接入方式”：

- 年月筛选（`YYYY-MM`）统一为新弹窗样式与交互。
- 年月日筛选（`YYYY-MM-DD`）在年月逻辑上演进，风格一致。
- 日期范围筛选（含“自定义范围”）统一接入器，统一布局与显示控制。
- 普通下拉筛选统一为“可搜索 + 可多选”组件，并支持“全部”与子项互斥。
- 页面逐步替换接入通用 `CSS/JS`，减少页面内联样式/重复逻辑。

---

## 3. 提交时间线与阶段成果

1. `642a54b`：先统一绩效相关页面的筛选/按钮风格，开始支持多选筛选参数。
2. `593b5d8`：在单页面先落地年月筛选框 UI（不含弹窗）。
3. `40a6706`：补齐并重构年月弹窗交互。
4. `3bf488f`：形成“确定版”年月筛选框与弹窗。
5. `6f204f4`：把年月控件样式与逻辑抽离到 `general_style_1.css/js`。
6. `593f780`：`performance_targets` 页面回收内联实现，改为引用通用实现。
7. `e4808cd`：将年月控件推广到考核相关页面。
8. `cd84002`：全站开始应用新的年月日控件（含更多页面接入）。
9. `6feab6e`：修正部分日期筛选框尺寸和布局问题。
10. `762e4a6`：增强通用样式/通用逻辑（包含交互细节修正）。
11. `d2144ba`：统一“全部”选项与子选项互斥逻辑。
12. `c6b84a6`：统一日期范围筛选框接入方式、样式和脚本接口，并同步到 `static/` 镜像文件。

---

## 4. 改动规模

- 改动文件数：`29`
- 代码变更：`6270 insertions`, `633 deletions`

主要改动类型：

- 通用前端库改造（JS/CSS）：
  - `general/static/css/general_style_1.css`
  - `general/static/js/general_style_1.js`
  - `general/static/js/searchable-select.js`
  - `static/css/general_style_1.css`
  - `static/js/general_style_1.js`
  - `static/js/searchable-select.js`
- 页面模板接入（Amazon/Task/General/Theme/Track/Yuser）
- 后端筛选参数适配（支持逗号分隔多选）

---

## 5. 核心通用能力改造（关键代码行）

## 5.1 年月选择器（YM）

关键实现文件：`general/static/js/general_style_1.js`

- 组件定义：`general/static/js/general_style_1.js:427`
  - `const GeneralStyleYearMonthPicker = (() => { ... })`
- 值解析与格式化：`general/static/js/general_style_1.js:428`, `general/static/js/general_style_1.js:437`
  - `parseMonthValue` / `formatMonthValue`
- 弹窗年月渲染与点击选月：`general/static/js/general_style_1.js:483`, `general/static/js/general_style_1.js:545`
  - 动态生成 12 个月按钮并回填输入框。
- 年份可编辑：`general/static/js/general_style_1.js:594`, `general/static/js/general_style_1.js:598`, `general/static/js/general_style_1.js:616`
  - 支持点击年文本进入编辑，键盘确认/失焦提交。
- 解决“编辑后选月需点两次”相关路径：`general/static/js/general_style_1.js:624`, `general/static/js/general_style_1.js:631`
  - 通过 `mousedown + click` 双路径保障选中即时生效。

对应样式文件：`general/static/css/general_style_1.css`

- 组件样式入口：`general/static/css/general_style_1.css:205`
  - `.ym-picker`、输入框、按钮、popover、月份网格等整套样式。

## 5.2 年月日选择器（YMD）

关键实现文件：`general/static/js/general_style_1.js`

- 组件定义：`general/static/js/general_style_1.js:665`
  - `const GeneralStyleDatePicker = (() => { ... })`
- 日期解析与格式化：`general/static/js/general_style_1.js:672`, `general/static/js/general_style_1.js:684`
  - `parseDateValue` / `formatDateParts`
- 月份可编辑与即时选日：`general/static/js/general_style_1.js:864`, `general/static/js/general_style_1.js:1100`, `general/static/js/general_style_1.js:1165`
  - 与 YM 保持一致：月可改、改后点日期即生效。
- 当月快捷按钮：`general/static/js/general_style_1.js:1178`

对应样式文件：`general/static/css/general_style_1.css`

- 组件样式入口：`general/static/css/general_style_1.css:420`
  - `.ymd-picker`、年月头部、日期网格、today 状态、active 状态等。

## 5.3 可搜索下拉（多选/单选）与“全部互斥”

关键实现文件：`general/static/js/searchable-select.js`

- “全部”识别规则：`general/static/js/searchable-select.js:65`, `general/static/js/searchable-select.js:83`
  - `isAllOption` / `isAllValue`
- 多选归一化（保留“全部”默认态，清理冲突）：`general/static/js/searchable-select.js:100`
  - `normalizeMultiSelection`
- 选项切换互斥逻辑：`general/static/js/searchable-select.js:295` ~ `general/static/js/searchable-select.js:317`
  - 选了子项时禁止再选“全部”；选“全部”会清掉子项。
- 全局暴露（供统一适配器调用）：`general/static/js/searchable-select.js:448`
  - `window.SearchableSelect = SearchableSelect`

对应样式文件：`general/static/css/general_style_1.css`

- 通用下拉样式入口：`general/static/css/general_style_1.css:1684`
  - `.searchable-select`、trigger、dropdown、option、checkbox、tag、clear-btn 等。

## 5.4 普通 `<select>` 自动适配为统一下拉组件

关键实现文件：`general/static/js/general_style_1.js`

- 适配器定义：`general/static/js/general_style_1.js:1248`
  - `const GeneralStyleFilterSelectAdapter = (() => { ... })`
- 目标选择器：`general/static/js/general_style_1.js:1250`
  - `TARGET_SELECTOR = 'select.form-select'`
- 多选语义判定：`general/static/js/general_style_1.js:1286`
  - `isSemanticMultiple`（默认按站点需求倾向可搜索多选）。
- 原生值同步：`general/static/js/general_style_1.js:1311`
  - `syncNativeSelect` 解决旧逻辑仍读取 `select.value` 的兼容问题。
- 自动接入与 DOM 监听：`general/static/js/general_style_1.js:1432`, `general/static/js/general_style_1.js:1445`
  - 支持页面动态新增筛选控件时自动转换。

## 5.5 日期范围统一接入口（DateRange Adapter）

关键实现文件：`general/static/js/general_style_1.js`

- 统一入口定义：`general/static/js/general_style_1.js:1478`
  - `const GeneralStyleDateRangeFilter = (() => { ... })`
- 自定义起止组显示控制：`general/static/js/general_style_1.js:1492`
  - `setGroupVisible`
- 初始化参数：`general/static/js/general_style_1.js:1508`
  - `customGroups/customDisplay/startInput/endInput`
- 对外 API：`general/static/js/general_style_1.js:1531` ~ `general/static/js/general_style_1.js:1556`
  - `getValue/isCustom/getStartDate/getEndDate/clearCustomDates/syncVisibility`

对应样式：`general/static/css/general_style_1.css:193`

- `.gs-date-range-custom-group` + `.is-visible`
  - 保证“自定义范围”展开时布局可控（右移优先，不够才换行）。

## 5.6 通用能力自动引导（页面加载自动生效）

关键实现文件：`general/static/js/general_style_1.js`

- 挂载到 `window`：`general/static/js/general_style_1.js:1567` ~ `general/static/js/general_style_1.js:1570`
- 启动器：`general/static/js/general_style_1.js:1572`, `general/static/js/general_style_1.js:1578`
  - `bootDatePicker` + `bootFilterSelectAdapter`

---

## 6. 页面接入改造清单（按业务域）

## 6.1 绩效与考核域

- `general/templates/performance_targets.html`
  - 接入通用样式/脚本：`performance_targets.html:7`, `performance_targets.html:719`, `performance_targets.html:720`
  - 年月控件容器：`performance_targets.html:479`, `performance_targets.html:590`
  - 分组/人员筛选改为统一下拉容器：`performance_targets.html:512`, `performance_targets.html:623`, `performance_targets.html:628`
  - 作用：把页面内联年月弹窗与样式剥离到通用库。

- `yuser/templates/assessment_management_list.html`
  - 通用 CSS/JS 接入：`assessment_management_list.html:7`, `assessment_management_list.html:718`, `assessment_management_list.html:719`
  - 年月容器：`assessment_management_list.html:415`, `assessment_management_list.html:645`
  - 员工/类型/状态统一下拉：`assessment_management_list.html:448`, `assessment_management_list.html:452`, `assessment_management_list.html:456`

- `yuser/templates/assessment_summary.html`
  - 通用 CSS/JS 接入：`assessment_summary.html:7`, `assessment_summary.html:431`
  - 年月容器：`assessment_summary.html:302`

## 6.2 Amazon 业务域

- `amazon/templates/dashboard.html`
  - 通用 CSS/JS 接入：`dashboard.html:7`, `dashboard.html:863`, `dashboard.html:864`
  - 日期范围容器：`dashboard.html:684`
  - 年月日容器：`dashboard.html:689`, `dashboard.html:705`
  - 日期范围统一接口初始化：`dashboard.html:909` ~ `dashboard.html:916`

- `amazon/templates/amazon_order_management.html`
  - 通用 CSS/JS 接入：`amazon_order_management.html:7`, `amazon_order_management.html:1011`, `amazon_order_management.html:1012`
  - 日期范围统一容器：`amazon_order_management.html:837`
  - 多个可搜索多选筛选容器（分组、人员、状态等）：`amazon_order_management.html:852` ~ `amazon_order_management.html:911`
  - 日期范围统一接口初始化：`amazon_order_management.html:1181` ~ `amazon_order_management.html:1182`

- `amazon/templates/amazon_performance_notifications.html`
  - 日期范围与运营人员/状态统一容器：`amazon_performance_notifications.html:222`, `amazon_performance_notifications.html:236`, `amazon_performance_notifications.html:251`
  - 日期范围统一接口初始化：`amazon_performance_notifications.html:434` ~ `amazon_performance_notifications.html:441`

- `amazon/templates/amazon_shop_emails.html`
  - 日期范围与运营/状态统一容器：`amazon_shop_emails.html:354`, `amazon_shop_emails.html:368`, `amazon_shop_emails.html:388`
  - 日期范围统一接口初始化：`amazon_shop_emails.html:680` ~ `amazon_shop_emails.html:687`

- `amazon/templates/amazon_daily_check_report.html`
  - 日期范围统一容器：`amazon_daily_check_report.html:219`
  - 日期范围统一接口初始化：`amazon_daily_check_report.html:525` ~ `amazon_daily_check_report.html:532`

- 其他接入页面
  - `amazon/templates/ranking.html`（接入通用 CSS/JS）
  - `amazon/templates/amazon_listing_management.html`（新增并接入通用体系）

## 6.3 Task / DataReq / Theme / Track

- `task/templates/task_list.html`
  - 状态/创建人多选统一下拉：`task_list.html:500`, `task_list.html:505`
  - 日期范围统一容器与接入：`task_list.html:510`, `task_list.html:762`, `task_list.html:763`

- `task/templates/product/product_list.html`
  - 状态/创建人统一为可搜索多选容器：`product_list.html:448`, `product_list.html:453`
  - 引入统一脚本：`product_list.html:636`, `product_list.html:637`
  - 页面内改为新逻辑加载状态/创建人并回填筛选参数（当前工作树继续演进中）。

- `data_req/templates/data_req/requirement_list.html`
  - 时间范围统一容器：`requirement_list.html:460`
  - 日期范围统一接口初始化：`requirement_list.html:847` ~ `requirement_list.html:856`

- `theme/templates/amazon_products_display.html`
  - 上架日期/数据日期统一日期范围容器：`amazon_products_display.html:901`, `amazon_products_display.html:916`
  - 两套日期范围统一接口初始化：`amazon_products_display.html:1490` ~ `amazon_products_display.html:1513`

- `track/templates/tracking_management.html`
  - 日期范围统一容器：`tracking_management.html:76`
  - 日期范围统一接口初始化：`tracking_management.html:764`, `tracking_management.html:765`

---

## 7. 后端改造（支持前端多选参数）

- `general/views_performance.py`
  - 组目标 `ops_group` 从单值改为多值：`general/views_performance.py:66` ~ `general/views_performance.py:70`
  - 个人目标 `user` 从单值改为逗号分隔多值：`general/views_performance.py:273` ~ `general/views_performance.py:285`
  - 个人目标 `ops_group` 同步支持多值：`general/views_performance.py:287` ~ `general/views_performance.py:291`

- `yuser/view_assessment_management.py`
  - 列表接口 `employee` 支持多值：`view_assessment_management.py:417` ~ `view_assessment_management.py:428`
  - 批量刷新接口 `employee` 支持多值：`view_assessment_management.py:1117` ~ `view_assessment_management.py:1128`

- `api/general/group_and_ops.py`
  - 保持 `platform`、`ops_group` 参数语义（本区间仅有微小文本/格式调整），接口定义位置：
    - `get_ops_groups_api`: `group_and_ops.py:61`
    - `get_operators_api`: `group_and_ops.py:142`

---

## 8. 全量改动文件清单（29）

1. `amazon/templates/amazon_daily_check_report.html`
2. `amazon/templates/amazon_listing_management.html`（新增）
3. `amazon/templates/amazon_order_management.html`
4. `amazon/templates/amazon_performance_notifications.html`
5. `amazon/templates/amazon_shop_emails.html`
6. `amazon/templates/dashboard.html`
7. `amazon/templates/ranking.html`
8. `api/general/group_and_ops.py`
9. `data_req/templates/data_req/requirement_list.html`
10. `general/Y-Project.lnk`（新增）
11. `general/static/css/general_style_1.css`
12. `general/static/js/general_style_1.js`
13. `general/static/js/searchable-select.js`
14. `general/templates/management/amazon_shop_management.html`
15. `general/templates/management/user_operation_management.html`
16. `general/templates/performance_targets.html`
17. `general/views_performance.py`
18. `static/css/general_style_1.css`
19. `static/js/general_style_1.js`
20. `static/js/searchable-select.js`
21. `task/templates/product/product_list.html`
22. `task/templates/task_list.html`
23. `theme/templates/amazon_products_display.html`
24. `theme/templates/trademark_info.html`
25. `theme/templates/tro_table.html`
26. `track/templates/tracking_management.html`
27. `yuser/templates/assessment_management_list.html`
28. `yuser/templates/assessment_summary.html`
29. `yuser/view_assessment_management.py`

---

## 9. 本轮大改的最终效果总结

- 站点形成统一筛选体系：年月、年月日、日期范围、普通下拉均有通用实现。
- 关键复杂交互（年份/月份可编辑、立即生效、弹窗稳定显示）集中在通用库治理，页面负担显著下降。
- 多选筛选链路打通：前端可搜索多选 -> URL 参数逗号拼接 -> 后端 `__in` 过滤。
- “全部 vs 子项”互斥规则统一，避免页面各写各的导致行为不一致。
- 日期范围“自定义范围”显示逻辑统一，支持多个页面快速复用。

---

## 10. 备注

- `static/*` 与 `general/static/*` 在本区间出现同步修改，说明项目在静态资源组织上存在双份维护路径。建议后续明确“唯一源文件目录”，减少重复变更风险。
- `general/Y-Project.lnk` 为非业务代码文件（快捷方式），建议按仓库规范评估是否应纳入版本管理。

---

## 11. 增量更新（自本文档上次更新节点以来）

> 本节记录的是在本文档上次版本之后追加的改造内容，主要是你本轮指出的“筛选项无子选项/未统一接入”问题修复。  
> 这些内容属于**后续增量改造**，不改变第 1 节已记录的原始 commit 区间定义。

### 11.1 `tracking-management`：四个筛选框统一改造为可搜索多选

#### 覆盖项

- 物流商
- 工厂
- 运营分组
- 运营姓名

#### 页面改造（前端）

文件：`track/templates/tracking_management.html`

- 将原 `select + clear 按钮` 或自定义复选下拉，统一替换为 `SearchableSelect` 容器：
  - `track/templates/tracking_management.html:99`
  - `track/templates/tracking_management.html:104`
  - `track/templates/tracking_management.html:139`
  - `track/templates/tracking_management.html:145`
- 新增统一初始化与多选归一化：
  - `initTrackingFilterSelects`：`track/templates/tracking_management.html:511`
  - `normalizeMultiSelectValues`：`track/templates/tracking_management.html:499`
- 数据加载改为接口驱动并写入统一组件：
  - 物流商：`loadCouriersFromAPI` `track/templates/tracking_management.html:595`
  - 工厂：`loadFactories` `track/templates/tracking_management.html:541`
  - 运营分组：`loadOpsGroups`（优先新接口，旧接口兜底）`track/templates/tracking_management.html:630`
  - 运营姓名：`loadOpsNames`（旧接口优先，新接口兜底）`track/templates/tracking_management.html:683`
- 筛选参数收集/重置改造为多选数组语义：
  - `getCurrentFilters`：`track/templates/tracking_management.html:788`
  - `setDefaultFilters`：`track/templates/tracking_management.html:839`
- 页面初始化接入顺序调整（先建组件再拉数据）：
  - `track/templates/tracking_management.html:2104` ~ `track/templates/tracking_management.html:2115`

#### 后端改造（多选参数兼容）

文件：`track/view/view_tracking_management.py`

- 新增通用解析函数（兼容数组/逗号串/全部占位）：
  - `is_all_filter_token`：`track/view/view_tracking_management.py:59`
  - `parse_multi_filter_values`：`track/view/view_tracking_management.py:64`
- 三个核心接口统一支持多选筛选：
  - 列表：`tracking_list`，物流商/工厂/运营分组/运营姓名改为 `__in` 过滤  
    `track/view/view_tracking_management.py:145`, `223`, `227`, `236`
  - 统计：`tracking_stats` 同步多选逻辑  
    `track/view/view_tracking_management.py:395`, `438`, `443`, `448`
  - 导出：`export_tracking_excel` 同步多选逻辑  
    `track/view/view_tracking_management.py:540`, `618`, `622`, `631`

#### 结果

- `/tracking-management/` 上述四项现已统一为“可搜索 + 可多选 + 全部互斥”交互。
- 不再出现“只有全部、没有子选项”或“前端多选但后端按单值过滤”的不一致。

---

### 11.2 `amazon/daily-check-report`：运营分组改为统一多选并接接口

#### 页面改造（前端）

文件：`amazon/templates/amazon_daily_check_report.html`

- 运营分组从原生 `select` 改为统一 `SearchableSelect` 多选容器：
  - `amazon/templates/amazon_daily_check_report.html:239`
- 新增分组组件初始化与接口加载：
  - `initOpsGroupFilter`：`amazon/templates/amazon_daily_check_report.html:599`
  - `loadOpsGroups`（接 `/api/general/ops-groups/?platform=amazon`）：`amazon/templates/amazon_daily_check_report.html:624`
- 筛选入参与重置逻辑改造：
  - `getCurrentFilters` 中 `ops_group` 改为多选值并 `join(",")`：`amazon/templates/amazon_daily_check_report.html:690`
  - `setDefaultFilters` 重置为 `["all"]`：`amazon/templates/amazon_daily_check_report.html:704`, `719`
- 页面初始化时新增分组控件接入：
  - `amazon/templates/amazon_daily_check_report.html:1078` ~ `1086`

#### 后端改造（多选参数兼容）

文件：`amazon/view/views_amazon_daily_check.py`

- `ops_group` 参数由单值扩展为“数组/逗号串/单字符串”兼容，并过滤 `all/*/__all__/不限/全部`：
  - `amazon/view/views_amazon_daily_check.py:135` ~ `155`
- 查询条件改为 `ops_group__in`：
  - `amazon/view/views_amazon_daily_check.py:155`

#### 结果

- `/amazon/daily-check-report/` 的“运营分组”不再依赖单值 `select`，已并入统一可搜索多选体系。

---

### 11.3 运营人员子选项为空的根因修复（通用旧接口兼容）

文件：`general/view/views_general.py`

- 修复 `get_ops_list` 的历史口径不兼容问题（原先仅匹配“运营部门”，导致部分数据返回空）：
  - 引入 `Q`：`general/view/views_general.py:4`
  - 部门条件兼容：`department='operation'` 或包含“运营”  
    `general/view/views_general.py:25`
  - 加入公司隔离：`company=request.user.company`  
    `general/view/views_general.py:23`
  - 平台筛选改为大小写兼容：`platform__iexact`  
    `general/view/views_general.py:31`, `33`

#### 结果

- 旧调用链（例如 `/api/ops/list`）不再因为部门字段历史差异返回空列表，减少“只有全部项”的出现概率。

---

### 11.4 本增量涉及文件清单

1. `track/templates/tracking_management.html`
2. `track/view/view_tracking_management.py`
3. `amazon/templates/amazon_daily_check_report.html`
4. `amazon/view/views_amazon_daily_check.py`
5. `general/view/views_general.py`
