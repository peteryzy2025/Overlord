---
name: overlord-design-system
description: |
  当用户要求修改、新建或调整 Overlord 项目管理后台的前端页面时触发。
  适用于任何涉及 Django 模板、HTML 结构、CSS 样式、表格、筛选区、分页、模态框、按钮、下拉框等前端一致性任务。
  强制要求使用统一的 .data-card 组件系统和标准类名，禁止自创类名或覆盖通用结构。
---

# Overlord 管理后台设计系统

## 核心原则

- **任何前端改动**（无论新建页面还是加一列/加一个按钮）都必须先遵循此规范。
- 所有通用样式已写入 `general/static/css/general_style_1.css`，**禁止**在页面内联 `<style>` 中重写 `.data-card`、`.table`、`.pagination-container`、`.btn` 的结构或颜色。
- 如果页面缺少 `.data-card` 结构，**必须**整体迁移到标准结构，禁止局部拼凑。
- **缓存版本**：页面引用 `general_style_1.css` 时必须带版本参数（如 `?v=20260417`）。若修改了 `general_style_1.css`，**必须同步更新**所有引用页面中的版本号，否则浏览器会加载旧缓存。

## 文件定位

| 用途 | 路径 |
|------|------|
| 主样式表 | `general/static/css/general_style_1.css` |
| 下拉框组件 | `general/static/js/searchable-select.js` |
| 参考实现 | `general/templates/management/user_management.html` |
| 新建页面模板 | `assets/management-page-template.html`（本 skill） |

## 页面继承链（强制）

所有管理后台列表页必须按以下顺序继承：

```
xxx.html
  ↓ extends
base/base_xxx.html（业务模块三级 Base，定义侧边栏菜单）
  ↓ extends
base/base_r.html（带侧边栏的二级 Base）
  ↓ extends
base/base.html（顶部导航一级 Base）
```

示例：
- `management/user_management.html` → `base/base_management.html` → `base/base_r.html` → `base/base.html`
- `amazon/xxx.html` → `base/base_amazon.html` → `base/base_r.html` → `base/base.html`

## 标准页面结构（强制）

每个管理后台列表页推荐采用 **页面标题 + 筛选卡片 + 数据卡片** 的三层结构，以增强层次感：

- **`.page-header`** — 页面大标题 + 可选的统计信息/创建按钮
  - 标题在左，统计居中，按钮在右
  - 若页面筛选条件复杂或有 Tab 切换，建议把标题从 `.data-card` 里提出来放这里
- **`.filter-card`** — 筛选条件容器，内部从上到下依次为：
  1. **`.filter-card-header`** — 二级 Tab 导航（如 热门搜索词/新词榜），必须独占第一行
  2. **`.filter-row`** — 具体筛选项（搜索框、下拉框、日期等），可折行
  3. **`.quick-filter-row`** — 点选式快速筛选 pills（如 全部/持续增长词/爆发词），必须独占新行
- **`.data-card`** — 数据主卡片，内部包含：
  1. **`.data-card-header`** — 可选。当标题已放在 `.page-header` 时，这里可只保留操作按钮或统计；若筛选条件极少，也可直接省略
  2. **`.data-quick-filter`** — 切换式快速筛选（如 噪声/去噪后/全部），放在表格上方
  3. **`.bulk-action-bar`** — 批量操作条（默认隐藏，选中后显示）
  4. **`.table-container.table-bordered`** — 带独立细边框+圆角的表格区
  5. **`.pagination-container`** — 分页

**新建页面时**：直接复制 `assets/management-page-template.html`，在此基础上修改业务逻辑。

## 页面标题规范

当页面需要把标题从数据卡片中剥离出来时，使用 `.page-header`：

```html
<div class="page-header">
    <h1 class="page-title"><i class="fas fa-tasks"></i> 页面标题</h1>
    <div class="header-stats" style="margin: 0 auto;">
        <span class="stat-item">总任务数：<b>0</b></span>
        <span class="stat-item">运行中：<b>0</b></span>
    </div>
    <button class="btn btn-primary" onclick="createNewTask()">
        <i class="fas fa-plus"></i> 创建新任务
    </button>
</div>
```

- `.page-title` 固定在左侧
- `.header-stats` 通过 `margin: 0 auto;` 居中
- 操作按钮固定在右侧
- **禁止**在 `.page-header` 内添加副标题、描述文字或 `.page-subtitle` 等元素

## 按钮规范（禁止自创类名）

只允许使用以下已定义的类名：

| 类名 | 样式 | 用途 |
|------|------|------|
| `.btn-primary` / `.btn-create` | `#3B82F6` 实底、白字、圆角 6px | 主操作：新建、保存 |
| `.btn-secondary` | `#F1F5F9` 灰底、黑字、细边框 | 次要操作：导出、取消 |
| `.btn-ghost` | 透明底、灰字、细边框 | 辅助操作 |
| `.btn-save-modal` | 蓝色保存按钮（模态框专用） | 模态框确认/保存 |
| `.btn-danger` | 红色危险按钮 | 删除等不可逆操作 |
| `.gs-btn-search` | 42×42 图标按钮，放大镜图标 | 筛选区搜索 |
| `.gs-btn-reset` | 42×42 图标按钮，刷新图标 | 筛选区重置 |

**筛选区按钮写法（必须原样使用）**：
```html
<div class="filter-actions">
    <button class="btn gs-btn-search gs-btn-iconized gs-btn-icon-only" onclick="filterData()" title="筛选"></button>
    <button class="btn btn-secondary gs-btn-reset gs-btn-iconized gs-btn-icon-only" onclick="resetFilters()" title="重置"></button>
</div>
```

**模态框底部按钮**：
- 取消统一用 `.btn-secondary`
- 保存/确认统一用 `.btn-save-modal`
- 删除统一用 `.btn-danger`
- **禁止**自创 `.btn-cancel-modal` 等类名

## Tab 导航位置（强制）

如果页面存在二级页面切换（如 热门搜索词/新词榜），**Tab 导航必须放在 `.filter-card-header` 内**，独占第一行，与具体筛选项上下分离：

```html
<div class="filter-card">
    <div class="filter-card-header">
        <div class="tab-nav">
            <div class="tab-nav-item active" onclick="switchTab('a')">
                <i class="fas fa-chart-line"></i> Tab A
            </div>
            <div class="tab-nav-item" onclick="switchTab('b')">
                <i class="fas fa-bolt"></i> Tab B
            </div>
        </div>
    </div>
    <div class="filter-row">...具体筛选项...</div>
</div>
```

**禁止**把 Tab 导航放在 `.data-card-header` 里与标题同行。

## 筛选区规范

### 基础筛选行
标准写法：
```html
<div class="filter-row">
    <div class="filter-group"><label class="filter-label">状态</label>...select...</div>
    <div class="filter-group"><input class="form-control" placeholder="关键词"></div>
    <div class="filter-actions">
        <button class="btn gs-btn-search gs-btn-iconized gs-btn-icon-only"></button>
        <button class="btn btn-secondary gs-btn-reset gs-btn-iconized gs-btn-icon-only"></button>
    </div>
</div>
```

### 搜索框加宽
当搜索框需要更宽时，使用 `.filter-group.longsearch`：
```html
<div class="filter-group longsearch">
    <label class="filter-label">搜索</label>
    <input type="text" class="form-control" placeholder="关键词">
</div>
```

### 日期范围
**禁止**把"开始日期~结束日期"挤在一个 `.filter-group` 里。推荐拆成两个独立的 `.filter-group`：

```html
<div class="filter-row">
    <div class="filter-group">
        <label class="filter-label">开始日期</label>
        <input type="date" class="form-control" id="startDate">
    </div>
    <div class="filter-group">
        <label class="filter-label">结束日期</label>
        <input type="date" class="form-control" id="endDate">
    </div>
</div>
```

### 点选式快速筛选（pill）
当需要 pill 快速筛选时，**必须独占新行并放在 `.filter-card` 内部**：

```html
<div class="filter-card">
    <div class="filter-row">...基础筛选...</div>
    <div class="quick-filter-row">
        <span class="quick-filter-label">快速筛选</span>
        <div class="quick-filter-options">
            <button class="quick-filter-chip active">全部</button>
            <button class="quick-filter-chip">条件1</button>
        </div>
    </div>
</div>
```

### 更多筛选项（展开/收起）
当筛选项过多时，可在 `.filter-card` 内使用 `.filter-row-secondary` 作为第二行，默认隐藏，通过 `.expand-toggle` 按钮展开：

```html
<div class="filter-card">
    <div class="filter-row filter-row-main">
        <div class="filter-group">...核心筛选项...</div>
        <div class="filter-actions">
            <button class="btn gs-btn-search gs-btn-iconized gs-btn-icon-only" title="筛选"></button>
            <button class="btn btn-secondary gs-btn-reset gs-btn-iconized gs-btn-icon-only" title="重置"></button>
        </div>
        <button class="expand-toggle" onclick="toggleSecondaryFilters()">
            <i class="fas fa-chevron-down"></i>
        </button>
    </div>
    <div class="filter-row-secondary" id="secondaryFilters">
        <div class="filter-group">...更多筛选项...</div>
    </div>
</div>
```

- 搜索/重置按钮**始终固定在第一行**，禁止通过 JS 把按钮搬到第二行
- `.expand-toggle` 放在第一行末尾，用于控制 `.filter-row-secondary` 的显隐

### 切换式快速筛选（tri-state toggle）
当需要 噪声/去噪后/全部 这类切换式筛选时，**放在 `.data-card` 内部、表格上方**，使用 `.data-quick-filter`：

```html
<div class="data-card">
    <div class="data-card-header">...标题...</div>
    <div class="data-quick-filter">
        <span class="quick-filter-label">显示模式</span>
        <div class="tri-state-toggle">
            <div class="toggle-indicator"></div>
            <div class="toggle-option active">状态A</div>
            <div class="toggle-option">状态B</div>
            <div class="toggle-option">全部</div>
        </div>
    </div>
    <div class="table-container table-bordered">...</div>
</div>
```

快速筛选两种形态：

| 类型 | 类名 | 位置 | 说明 |
|------|------|------|------|
| **点选式** | `.quick-filter-chip` | `.filter-card` 内 | 圆角 pill 按钮，active 状态为主题蓝色 |
| **切换式** | `.tri-state-toggle` + `.toggle-option` | `.data-card` 内（`.data-quick-filter`） | 互斥状态，滑块背景跟随（背景色由业务 JS 自定义） |

## 表格规范

- **风格**：传统横线表格。每行必须有 `border-bottom: 1px solid var(--border-color)`，包括最后一行。
- **表头**：背景 `var(--bg-tertiary)`，**禁止**使用任何 `linear-gradient` 渐变。
  - 表头 `padding: 1.25rem 1.5rem`
  - 表头字号 `1rem`，字重 600
  - 表头文字颜色 `var(--text-secondary)`
  - 表头文字居中 `text-align: center`
  - 表头 `cursor: default`（只有明确可排序的列才额外加 `.sortable`）
- **单元格**：`padding: 1rem 1.5rem`，字号 `14px`，颜色 `var(--text-primary)`，文字默认居中。
- **操作列**：**禁止**使用带边框/底色的按钮。统一使用 `<span class="link">` 或 `<a class="link">` 蓝色纯文字链接。
- **斑马纹**：Light 模式由 Bootstrap `.table-striped` 控制；Dark 模式已覆盖，禁止重写。
- **固定列**：第一列、第二列、最后一列在 `.table-container` 中为 `position: sticky`；Dark 模式下阴影已覆盖。
- **复选框列宽度**：第一列表头必须用 `<th class="w-checkbox">`（样式已锁定 45px）。
- **表格容器边框**：推荐在 `.table-container` 上加 `.table-bordered`，形成独立的 `1px solid var(--border-color)` 圆角边框（`border-radius: 12px`），增强卡片内的层次感。
- **主样式来源**：所有表格样式统一由 `general/static/css/general_style_1.css` 控制。**禁止**再引用 `amazon/static/css/amazon_css.css` 作为通用表格样式；如发现页面仍引用该文件，应逐步移除并验证。

## 下拉框（Searchable Select）

- 统一使用 `searchable-select.js` 组件。
- HTML 结构：`<div id="xxxFilter" class="searchable-select single" data-placeholder="请选择..."></div>`
- 初始化：在页面 JS 中 `new SearchableSelect('#xxxFilter', { options: [...] })`。
- 多选模式下返回值是数组，提交前如需字符串需自行处理。

## 模态框规范

**强制要求：禁止点击外部关闭。**

必须加上拦截属性：
```html
<div class="modal-overlay" id="xxxModalOverlay" onclick="if(event.target === this) return;">
```

模态框底部按钮：
```html
<div class="modal-footer">
    <button type="button" class="btn btn-secondary" onclick="closeModal()">取消</button>
    <button type="button" class="btn btn-save-modal" onclick="saveData()">保存</button>
</div>
```

## 分页规范

在 `.data-card` 内部时：
- 背景透明、无阴影、无圆角
- **顶部必须有 `border-top: 1px solid var(--border-color)`** 与表格分隔
- 每页条数选择器 + 页码按钮区 + 跳转输入区 三件套必须齐全
- 具体实现参见 `assets/management-page-template.html`

## 权限判断规范

使用权限表中的 `code` 字段，**不是** user 模型里的权限字段。

- `555` = 超级管理员
- `551` = 普通管理员

模板中判断示例：
```html
{% if '555' in user_permissions or '551' in user_permissions %}
    <button class="btn btn-create" onclick="openCreateModal()">新建</button>
{% endif %}
```

## 红线（禁止事项）

- 禁止自创 CSS 类名替代已有规范类名（如把 `.btn-create` 改成 `.my-btn-blue`）。
- 禁止在页面 `<style>` 中重写 `.data-card`、`.table`、`.pagination-container`、`.btn` 的结构或颜色。
- 禁止在表头使用渐变背景。
- 禁止表格操作列使用 `.btn-sm` 按钮，必须用 `.link`。
- 禁止模态框点击外部关闭。
- 禁止重复写入 Dark Mode 样式（已在 `general_style_1.css` 中全局覆盖）。
- **禁止**把 Tab 导航放在 `.data-card-header` 里；有 Tab 切换时必须放在 `.filter-card-header` 独占第一行。
- **禁止**使用 `.btn-cancel-modal` 等非标准按钮类名。
- **禁止**引用 `amazon/static/css/amazon_css.css` 作为通用表格样式。

## 工作流（修改页面时）

1. 打开目标模板，确认继承链正确。
2. 检查是否已有 `.data-card`；如果没有，用 `assets/management-page-template.html` 整体替换结构。
3. 检查 3 大区块顺序是否正确（`.page-header` → `.filter-card` → `.data-card`，尤其 Tab 是否在 `.filter-card-header`）。
4. 检查按钮类名是否符合规范。
5. 检查表格操作列是否使用 `.link`。
6. 检查模态框是否有 `onclick="if(event.target === this) return;"`。
