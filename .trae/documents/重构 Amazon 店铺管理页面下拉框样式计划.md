# 恢复 Amazon 店铺管理页面 - 基于“页面备份”版本

## 核心任务
将 `general - 副本/static/页面备份/` 下的 `amazon.html`, `css.css`, `js.js` 整合进当前的 Django 项目，完全恢复之前的页面效果和交互功能。

## 详细步骤

### 1. 恢复核心静态资源
- **CSS 恢复**：将 `页面备份/css.css` 的内容写入 `general/static/css/management-common.css`，并同步更新 `general_style_1.css` 以确保样式覆盖完整。
- **JS 恢复**：将 `页面备份/js.js` 的内容写入 `general/static/js/searchable-select.js`，恢复 `SearchableSelect` 组件。

### 2. 迁移并整合模板 (`amazon_shop_management.html`)
- **结构整合**：以 `页面备份/amazon.html` 的 HTML 结构为核心，整合进 Django 的 `amazon_shop_management.html` 模板。
- **Django 适配**：
  - 使用 `{% extends 'management/base_management.html' %}` 继承基础模板。
  - 将所有静态资源路径（如 `/static/css/...`）替换为 `{% static '...' %}` 标签。
  - 将 `views_amazon_management.py` 传递的变量（如 `user_permissions_json`）正确嵌入到页面 JS 中。

### 3. 下拉框组件适配与初始化
- **筛选器重构**：根据 `amazon.html` 中的结构，将筛选区域的“店铺状态”、“客户”、“运营人员”、“运营分组”全部改为 `SearchableSelect` 格式。
- **逻辑适配**：
  - 确保页面启动时调用 `initAllSearchableSelects()`。
  - 确保 `loadOperatorsFromAPI` 和 `loadGroupsFromAPI` 能够正确调用组件的 `setOptions()` 方法更新下拉选项。

### 4. 验证与优化
- 检查固定列表格（Fixed Columns）是否正常显示。
- 验证多选筛选器是否能正确向后端发送请求。
- 确认“新建/编辑”模态框中的下拉框样式已同步更新。