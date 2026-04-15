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

每个管理后台列表页必须采用 `.data-card` 一体化卡片，以下 **5 个区块必须按顺序出现**：

1. **`.data-card-header`** — 标题 + 新建按钮
2. **`.data-card-filter`** — 筛选条件 + 搜索/重置按钮
3. **`.bulk-action-bar`** — 批量操作条（即使业务暂无批量功能，也必须预留 DOM 结构）
4. **`.table-container` → `table.table`** — 表格
5. **`.pagination-container`** — 分页

**新建页面时**：直接复制 `assets/management-page-template.html`，在此基础上修改业务逻辑。

## 按钮规范（禁止自创类名）

只允许使用以下已定义的类名：

| 类名 | 样式 | 用途 |
|------|------|------|
| `.btn-primary` / `.btn-create` | `#3B82F6` 实底、白字、圆角 6px | 主操作：新建、保存 |
| `.btn-secondary` | `#F1F5F9` 灰底、黑字、细边框 | 次要操作：导出、取消 |
| `.btn-ghost` | 透明底、灰字、细边框 | 辅助操作 |
| `.btn-save-modal` | 蓝色保存按钮（模态框专用） | 模态框确认/保存 |
| `.gs-btn-search` | 42×42 图标按钮，放大镜图标 | 筛选区搜索 |
| `.gs-btn-reset` | 42×42 图标按钮，刷新图标 | 筛选区重置 |

**筛选区按钮写法（必须原样使用）**：
```html
<div class="filter-actions">
    <button class="btn gs-btn-search gs-btn-iconized gs-btn-icon-only" onclick="filterData()" title="筛选"></button>
    <button class="btn btn-secondary gs-btn-reset gs-btn-iconized gs-btn-icon-only" onclick="resetFilters()" title="重置"></button>
</div>
```

## 表格规范

- **风格**：传统横线表格。每行必须有 `border-bottom: 1px solid var(--border-color)`，包括最后一行。
- **表头**：背景 `var(--bg-secondary)`，**禁止**使用任何 `linear-gradient` 渐变。表头字号 `1rem`，字重 600，必须比内容大一档。
- **单元格**：`padding: 1rem 1.5rem`，字号 `14px`。
- **操作列**：**禁止**使用带边框/底色的按钮。统一使用 `<span class="link">` 或 `<a class="link">` 蓝色纯文字链接。
- **斑马纹**：Light 模式由 Bootstrap `.table-striped` 控制；Dark 模式已覆盖，禁止重写。
- **固定列**：第一列、第二列、最后一列在 `.table-container` 中为 `position: sticky`；Dark 模式下阴影已覆盖。
- **复选框列宽度**：第一列表头必须用 `<th class="w-checkbox">`（样式已锁定 45px）。

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

## 工作流（修改页面时）

1. 打开目标模板，确认继承链正确。
2. 检查是否已有 `.data-card`；如果没有，用 `assets/management-page-template.html` 整体替换结构。
3. 检查 5 大区块顺序是否正确。
4. 检查按钮类名是否符合规范。
5. 检查表格操作列是否使用 `.link`。
6. 检查模态框是否有 `onclick="if(event.target === this) return;"`。
7. 检查权限判断是否使用 `code=555/551`。
8. 完成修改后，用 `Ctrl+F5` 硬刷新验证（`searchable-select.js` 和 `general_style_1.css` 有强缓存）。
