# Divi智管 设计系统规范 v1.0

> 本文档规定了管理后台列表页的统一实现标准。所有 AI 在新增/修改管理后台页面时，必须严格遵循以下规范，确保视觉和交互风格完全一致。

---

## 一、页面继承链

所有管理后台的具体页面必须按以下链条继承：

```
xxx.html
  ↓ extends
base/base_xxx.html（该业务模块的三级 Base，定义侧边栏菜单）
  ↓ extends
base/base_r.html（带侧边栏的二级 Base）
  ↓ extends
base/base.html（顶部导航一级 Base）
```

**示例**：
- `management/user_management.html` → `base/base_management.html` → `base/base_r.html` → `base/base.html`
- `amazon/xxx.html` → `base/base_amazon.html` → `base/base_r.html` → `base/base.html`

---

## 二、主题色与交互色

| 模式 | 主色 | Hover/Active 背景 | 文字色 | 说明 |
|------|------|-------------------|--------|------|
| Light | `#3b82f6` | `#eff6ff` | `#3b82f6` | 导航、侧边栏、按钮、高亮 |
| Dark | `#60a5fa` | `rgba(59, 130, 246, 0.18)` | `#60a5fa` | 导航、侧边栏、按钮、高亮 |

**禁止**：使用橙色（`#ed8936`、`#dd6b20`、`#c05621`）作为任何交互色。

---

## 三、标准页面结构（强制）

每个管理后台列表页必须采用 **`.data-card` 一体化卡片** 结构，以下 5 个区块必须按顺序出现：

1. **卡片头部** `.data-card-header`：标题 + 操作按钮
2. **筛选区** `.data-card-filter`：筛选条件 + 搜索/重置按钮
3. **批量操作栏** `.bulk-action-bar`：全选后出现的操作条（即使当前业务暂无批量功能，也必须预留 DOM 结构）
4. **表格区** `.table-container` → `table.table`
5. **分页区** `.pagination-container`

### 3.1 最小可复用 HTML 骨架

```html
{% extends 'base/base_xxx.html' %}
{% load static %}

{% block title %}页面标题 - Overlord{% endblock %}

{% block extra_css %}
    <style>
        /* 仅保留本页面特有样式，禁止重写 .data-card、.table、.pagination 等通用结构 */
        .table-container table {
            min-width: 1000px;
        }
    </style>
{% endblock %}

{% block content %}
    <div class="tab-content">
        <div class="data-card">
            <!-- 1. 头部 -->
            <div class="data-card-header">
                <div class="data-card-title">
                    <i class="fas fa-users" style="color: var(--accent-color); margin-right: 0.5rem;"></i>页面标题
                </div>
                {% if '555' in user_permissions or '551' in user_permissions %}
                <button class="btn btn-create" onclick="openCreateModal()">
                    <i class="fas fa-plus" style="margin-right: 0.5rem;"></i>新建
                </button>
                {% endif %}
            </div>

            <!-- 2. 筛选区 -->
            <div class="data-card-filter">
                <div class="filter-row">
                    <div class="filter-group">
                        <label class="filter-label">状态</label>
                        <div id="statusFilter" class="searchable-select single" data-placeholder="全部状态"></div>
                    </div>
                    <div class="filter-group">
                        <label class="filter-label">搜索</label>
                        <input type="text" class="form-control" id="keywordSearch" placeholder="关键词">
                    </div>
                    <div class="filter-actions">
                        <button class="btn gs-btn-search gs-btn-iconized gs-btn-icon-only" onclick="filterData()" title="筛选"></button>
                        <button class="btn btn-secondary gs-btn-reset gs-btn-iconized gs-btn-icon-only" onclick="resetFilters()" title="重置"></button>
                    </div>
                </div>
            </div>

            <!-- 3. 批量操作栏（强制预留） -->
            {% if '555' in user_permissions or '551' in user_permissions %}
            <div class="bulk-action-bar" id="bulkActionBar">
                <span class="selected-count" id="selectedCountText">已选择 0 项</span>
                <button class="btn btn-secondary" onclick="clearSelection()">
                    <i class="fas fa-times"></i><span>取消选择</span>
                </button>
                <button class="btn btn-create" onclick="bulkAction1()">
                    <i class="fas fa-building"></i><span>批量操作1</span>
                </button>
            </div>
            {% endif %}

            <!-- 4. 表格区 -->
            <div class="table-container">
                <table class="table" id="dataTable">
                    <thead>
                        <tr>
                            <th class="w-checkbox"><input type="checkbox" id="selectAll" onclick="toggleSelectAll()"></th>
                            <th>名称</th>
                            <th>状态</th>
                            <th>操作</th>
                        </tr>
                    </thead>
                    <tbody id="dataTableBody">
                        <!-- 动态生成 -->
                    </tbody>
                </table>
            </div>

            <!-- 5. 分页区 -->
            <div class="pagination-container" id="paginationContainer">
                <div class="pagination-info" data-total="0">
                    <div class="page-size-wrapper" id="pageSizeWrapper">
                        <span class="page-size-label">每页显示：</span>
                        <div class="page-size-dropdown-wrapper" style="position: relative;">
                            <button class="page-size-trigger" id="pageSizeTrigger" onclick="togglePageSizeDropdown()">
                                <span id="pageSizeText">20条</span>
                                <i class="fas fa-chevron-down"></i>
                            </button>
                            <div class="page-size-dropdown" id="pageSizeDropdown">
                                <div class="page-size-option selected" onclick="changePageSize(20)">20条</div>
                                <div class="page-size-option" onclick="changePageSize(50)">50条</div>
                                <div class="page-size-option" onclick="changePageSize(100)">100条</div>
                                <div class="page-size-option" onclick="changePageSize(200)">200条</div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="pagination-new" id="paginationNew">
                    <!-- 动态生成 -->
                </div>
                <div class="pagination-jump">
                    <span>跳至</span>
                    <input type="number" id="pageJumpInput" class="page-jump-input" min="1" placeholder="页码" onkeypress="handlePageJump(event)">
                    <span>页</span>
                </div>
            </div>
        </div>
    </div>

    <!-- 模态框（禁止点击框以外的地方关闭） -->
    <div class="modal-overlay" id="exampleModalOverlay" onclick="if(event.target === this) return;">
        <div class="modal-content">
            <div class="modal-header">
                <h2 class="modal-title">标题</h2>
                <button class="modal-close" onclick="closeModal()">&times;</button>
            </div>
            <div class="modal-body">
                <!-- 内容 -->
            </div>
            <div class="modal-footer">
                <button type="button" class="btn btn-secondary" onclick="closeModal()">取消</button>
                <button type="button" class="btn btn-save-modal" onclick="saveData()">保存</button>
            </div>
        </div>
    </div>
{% endblock %}

{% block extra_js %}
    <script>
        // ==================== 全局变量 ====================
        let currentPage = 1;
        let pageSize = 20;
        let totalItems = 0;
        let totalPages = 1;
        let selectedIds = new Set();
        let allData = [];

        // ==================== 初始化 ====================
        document.addEventListener('DOMContentLoaded', function() {
            initSearchableSelects();
            loadData();
        });

        function initSearchableSelects() {
            // 初始化筛选器...
        }

        async function loadData() {
            // 加载数据并 renderTable / renderPagination / updatePaginationStats
        }

        function renderTable(data) {
            const tbody = document.getElementById('dataTableBody');
            tbody.innerHTML = data.map(item => `
                <tr data-id="${item.id}">
                    <td class="w-checkbox">
                        <input type="checkbox" class="row-checkbox"
                               ${selectedIds.has(item.id) ? 'checked' : ''}
                               onchange="toggleSelectItem(${item.id})">
                    </td>
                    <td>${item.name}</td>
                    <td>${item.status}</td>
                    <td>
                        <button class="btn btn-sm" onclick="openViewModal(${item.id})">查看</button>
                        <button class="btn btn-sm btn-edit" onclick="openEditModal(${item.id})">编辑</button>
                    </td>
                </tr>
            `).join('');
            updateSelectAllCheckbox();
            updateBulkActionBar();
        }

        function renderPagination() {
            const pagination = document.getElementById('paginationNew');
            let html = '';
            html += `<button class="pagination-btn-new ${currentPage === 1 ? 'disabled' : ''}" onclick="goToPage(${currentPage - 1})" ${currentPage === 1 ? 'disabled' : ''}><i class="fas fa-chevron-left"></i></button>`;
            // ... 页码逻辑
            html += `<button class="pagination-btn-new ${currentPage === totalPages ? 'disabled' : ''}" onclick="goToPage(${currentPage + 1})" ${currentPage === totalPages ? 'disabled' : ''}><i class="fas fa-chevron-right"></i></button>`;
            pagination.innerHTML = html;
        }

        function updatePaginationStats() {
            const start = (currentPage - 1) * pageSize + 1;
            const end = Math.min(currentPage * pageSize, totalItems);
            document.getElementById('pageSizeText').textContent = pageSize + '条';
            const pageSizeWrapper = document.getElementById('pageSizeWrapper');
            let statsEl = pageSizeWrapper.querySelector('.pagination-stats');
            if (!statsEl) {
                statsEl = document.createElement('span');
                statsEl.className = 'pagination-stats';
                statsEl.style.marginLeft = '1rem';
                statsEl.style.color = 'var(--text-secondary)';
                pageSizeWrapper.appendChild(statsEl);
            }
            statsEl.textContent = totalItems === 0 ? '0' : `${start}-${end} / 共 ${totalItems} 条`;
        }

        // ==================== 选择操作 ====================
        function toggleSelectItem(id) {
            selectedIds.has(id) ? selectedIds.delete(id) : selectedIds.add(id);
            updateBulkActionBar();
            updateSelectAllCheckbox();
        }

        function toggleSelectAll() {
            const checkbox = document.getElementById('selectAll');
            document.querySelectorAll('.row-checkbox').forEach((cb, index) => {
                const id = allData[index].id;
                cb.checked = checkbox.checked;
                checkbox.checked ? selectedIds.add(id) : selectedIds.delete(id);
            });
            updateBulkActionBar();
        }

        function updateSelectAllCheckbox() {
            const checkbox = document.getElementById('selectAll');
            const visibleIds = allData.map(d => d.id);
            checkbox.checked = visibleIds.length > 0 && visibleIds.every(id => selectedIds.has(id));
        }

        function updateBulkActionBar() {
            const bar = document.getElementById('bulkActionBar');
            const countText = document.getElementById('selectedCountText');
            if (!bar || !countText) return;
            countText.textContent = `已选择 ${selectedIds.size} 项`;
            bar.classList.toggle('visible', selectedIds.size > 0);
        }

        function clearSelection() {
            selectedIds.clear();
            document.getElementById('selectAll').checked = false;
            renderTable(allData);
            updateBulkActionBar();
        }

        // ==================== 分页操作 ====================
        function goToPage(page) {
            if (page < 1 || page > totalPages) return;
            currentPage = page;
            loadData();
        }

        function changePageSize(size) {
            pageSize = size;
            currentPage = 1;
            document.getElementById('pageSizeText').textContent = size + '条';
            document.getElementById('pageSizeDropdown').classList.remove('open');
            document.querySelectorAll('.page-size-option').forEach(option => option.classList.remove('selected'));
            const selectedOption = document.querySelector(`.page-size-option[onclick="changePageSize(${size})"]`);
            if (selectedOption) selectedOption.classList.add('selected');
            loadData();
        }

        function togglePageSizeDropdown() {
            document.getElementById('pageSizeDropdown').classList.toggle('open');
        }

        function handlePageJump(event) {
            if (event.key === 'Enter') {
                const page = parseInt(event.target.value);
                if (page && page >= 1 && page <= totalPages) goToPage(page);
                event.target.value = '';
            }
        }

        // ==================== 模态框（禁止点击外部关闭） ====================
        function openCreateModal() {
            document.getElementById('exampleModalOverlay').classList.add('active');
        }

        function closeModal() {
            document.getElementById('exampleModalOverlay').classList.remove('active');
        }
    </script>
{% endblock %}
```

---

## 四、CSS 类名规范（禁止自创）

以下类名已在 `general/static/css/general_style_1.css` 中统一定义，必须原样使用：

| 层级 | 类名 | 用途 |
|------|------|------|
| 卡片 | `.data-card` | 一体化卡片容器（圆角 16px、阴影、边框） |
| 卡片 | `.data-card-header` | 头部 Flex 区（标题 + 按钮），**底部自带分隔线** |
| 卡片 | `.data-card-title` | 标题文字（`1.5rem`，支持左侧图标），**左侧自带 accent 色竖条** |
| 卡片 | `.data-card-filter` | 筛选区（内部 Grid 布局），**底部自带分隔线** |
| 表格 | `.table-container` | 表格外层 |
| 表格 | `.table` | 表格本体 |
| 批量 | `.bulk-action-bar` | 批量操作条（默认隐藏，轻量样式） |
| 批量 | `.bulk-action-bar.visible` | 显示状态 |
| 批量 | `.selected-count` | 已选择数量文字 |
| 分页 | `.pagination-container` | 分页容器（在 `.data-card` 内部时**顶部自带分隔线**） |
| 分页 | `.pagination-new` | 页码按钮区 |
| 分页 | `.pagination-info` | 左侧统计信息 |
| 分页 | `.pagination-jump` | 跳转输入区 |
| 分页 | `.page-size-wrapper` | 每页条数选择器 |

**表格第一列复选框宽度固定类**：`.w-checkbox`（已在通用样式中锁定 `45px`）

---

## 五、表格样式强制规范（已写入通用样式）

### 5.1 卡片行表格（`.data-card` 内部）

在 `.data-card` 内部的 `.table` 采用**卡片行**风格，禁止传统横线表格：

- **行间距**：`border-spacing: 0 8px`，行与行之间有 8px 间隙
- **每行卡片化**：`border-radius: 10px`、`box-shadow: 0 0 0 1px var(--border-color)`、白色背景
- **悬浮效果**：轻微抬升 `translateY(-1px)` + 柔和阴影
- **无横线**：卡片行内部**没有** `border-bottom`
- **表头**：纯色透明背景、底部 2px 边框线、文字颜色 `var(--text-secondary)`、无渐变

### 5.2 表头
- **背景**：透明（`background-color: transparent`），通过底部 2px 边框与内容区分
- **禁止**：使用任何 `linear-gradient` 渐变背景
- **圆角**：在 `.data-card` 内部时，表头无圆角
- **字体**：表头及单元格文字统一使用系统默认字体，**无特殊说明不准加特殊字体**（如 `monospace`、自定义艺术字体等）
- **尺寸**：表头 `padding: 1rem 1.5rem`，`font-size: 14px`，字重 600

### 5.3 单元格
- 在 `.data-card` 内部时，`padding: 0.875rem 1.5rem`
- 每一行卡片条内的 `td` **无 border**
- 卡片行左右端自带圆角（`:first-child` 和 `:last-child`）

### 5.4 斑马纹
- Light 模式：默认由 Bootstrap `.table-striped` 控制
- Dark 模式：奇数行使用 `rgba(255,255,255,0.03)` 极淡白条纹

### 5.5 固定列
- 第一列、第二列、最后一列在 `.table-container` 中为 `position: sticky`
- Dark 模式下固定列阴影加深为 `rgba(0,0,0,0.35)`，确保边界清晰

### 5.6 轻量按钮与标签（卡片行内部）
- `.btn-sm`：透明背景、细边框、`border-radius: 6px`、hover 变蓝色
- `.permission-tag`：**药丸形**（`border-radius: 999px`）、半透明蓝底、蓝色文字、更小更轻量

---

## 六、分页样式规范（已写入通用样式）

在 `.data-card` 内部：
- 背景透明、无阴影、无圆角
- **顶部有 `border-top: 1px solid var(--border-color)`** 与表格分隔
- `padding: 1.25rem 0 0 0`

---

## 七、模态框规范

**强制要求：所有模态框禁止点击外部关闭。**

实现方式：
```html
<div class="modal-overlay" id="xxxModalOverlay" onclick="if(event.target === this) return;">
```

或使用 JS 拦截：
```javascript
document.getElementById('xxxModalOverlay').addEventListener('click', function(e) {
    if (e.target === this) {
        // 不做任何关闭操作
        return;
    }
});
```

---

## 八、字体规范

- **基准字体**：`14px`（`.tab-content` 已统一设置）
- **标题字体**：`.data-card-title` 为 `1.5rem`
- **表格内无特殊说明不准加特殊字体**

---

## 九、Dark Mode 已覆盖清单

以下组件的 Dark 模式样式已在 `general_style_1.css` 和 `table-fullscreen.css` 中完整覆盖，**禁止重复写入**：

- [x] 导航栏 active/hover（`base.html` 中通过 CSS var 覆盖）
- [x] 侧边栏 active/hover（`base_r.html` 中通过 CSS var 覆盖）
- [x] `.btn` hover / `.btn-secondary`
- [x] `.ym-picker-input` / `.ymd-picker-input` 背景
- [x] `.table` 斑马纹、固定列阴影、表头/单元格背景
- [x] `.pagination-container` 在 `.data-card` 内部的透明化处理

---

## 十、参考样例

**第一个完全标准化的页面**：`general/templates/management/user_management.html`

该页面已实现：
- `.data-card` 一体化卡片
- `.data-card-header` 头部（带图标、带底部横线）
- `.data-card-filter` 筛选区
- `.bulk-action-bar` 批量操作条
- 第一列复选框 + 全选逻辑
- **卡片行表格**风格
- 标准分页组件
- 模态框禁止外部关闭
- Dark Mode 完全适配

---

## 十一、快速检查清单（页面上线前必查）

- [ ] HTML 按顺序包含：`.data-card-header` → `.data-card-filter` → `.bulk-action-bar` → `.table-container` → `.pagination-container`
- [ ] 表格第一列是 `<th class="w-checkbox">` 的复选框
- [ ] 表格采用卡片行风格（行之间有 gap，每行圆角，无横线 border-bottom）
- [ ] 分页区无独立白底卡片感，顶部有横线
- [ ] 模态框点击外部不关闭
- [ ] 未在内联 `<style>` 中重写 `.data-card`、`.table`、`.pagination-container` 的结构样式
- [ ] Dark 模式下无明显亮块或看不清的文字
