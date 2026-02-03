/**
 * 通用组件JS库
 * 提供各管理页面的通用功能
 */

// ============================================
// 1. 分页组件
// ============================================
class Pagination {
    constructor(options = {}) {
        this.currentPage = options.currentPage || 1;
        this.pageSize = options.pageSize || 20;
        this.total = options.total || 0;
        this.onPageChange = options.onPageChange || (() => {});
        this.onPageSizeChange = options.onPageSizeChange || (() => {});
    }

    // 渲染分页按钮
    render(containerId) {
        const container = document.getElementById(containerId);
        if (!container) return;

        const totalPages = Math.ceil(this.total / this.pageSize);
        const paginationHtml = [];

        if (totalPages <= 1) {
            container.innerHTML = '';
            return;
        }

        // 上一页按钮
        const prevDisabled = this.currentPage === 1 ? 'disabled' : '';
        paginationHtml.push(`
            <button class="pagination-btn-new" onclick="pagination.goToPage(${this.currentPage - 1})" ${prevDisabled}>
                <i class="fas fa-chevron-left"></i> 上一页
            </button>
        `);

        // 页码计算
        let startPage = Math.max(1, this.currentPage - 2);
        let endPage = Math.min(totalPages, startPage + 4);

        if (endPage - startPage < 4) {
            startPage = Math.max(1, endPage - 4);
        }

        // 首页
        if (startPage > 1) {
            paginationHtml.push(`<button class="pagination-btn-new" onclick="pagination.goToPage(1)">1</button>`);
            if (startPage > 2) {
                paginationHtml.push(`<span class="pagination-btn-new ellipsis">...</span>`);
            }
        }

        // 页码
        for (let i = startPage; i <= endPage; i++) {
            const active = i === this.currentPage ? 'active' : '';
            paginationHtml.push(`<button class="pagination-btn-new ${active}" onclick="pagination.goToPage(${i})">${i}</button>`);
        }

        // 尾页
        if (endPage < totalPages) {
            if (endPage < totalPages - 1) {
                paginationHtml.push(`<span class="pagination-btn-new ellipsis">...</span>`);
            }
            paginationHtml.push(`<button class="pagination-btn-new" onclick="pagination.goToPage(${totalPages})">${totalPages}</button>`);
        }

        // 下一页按钮
        const nextDisabled = this.currentPage === totalPages ? 'disabled' : '';
        paginationHtml.push(`
            <button class="pagination-btn-new" onclick="pagination.goToPage(${this.currentPage + 1})" ${nextDisabled}>
                下一页 <i class="fas fa-chevron-right"></i>
            </button>
        `);

        container.innerHTML = paginationHtml.join('');
    }

    // 跳转到指定页
    goToPage(page) {
        const totalPages = Math.ceil(this.total / this.pageSize);
        if (page < 1 || page > totalPages) return;
        
        this.currentPage = page;
        this.onPageChange(page);
    }

    // 更新分页大小
    setPageSize(size) {
        this.pageSize = parseInt(size);
        this.currentPage = 1;
        this.onPageSizeChange(this.pageSize);
    }

    // 更新总数
    setTotal(total) {
        this.total = total;
    }
}

// ============================================
// 2. 批量操作组件
// ============================================
class BulkActions {
    constructor(options = {}) {
        this.checkboxClass = options.checkboxClass || 'row-checkbox';
        this.selectAllId = options.selectAllId || 'selectAll';
        this.barId = options.barId || 'bulkActionBar';
        this.countId = options.countId || 'selectedCount';
        this.onSelectionChange = options.onSelectionChange || (() => {});
        this.selectedIds = new Set();
    }

    // 初始化事件监听
    init() {
        // 全选按钮
        const selectAll = document.getElementById(this.selectAllId);
        if (selectAll) {
            selectAll.addEventListener('change', (e) => {
                this.toggleSelectAll(e.target.checked);
            });
        }

        // 监听表格点击事件（事件委托）
        document.addEventListener('change', (e) => {
            if (e.target.classList.contains(this.checkboxClass)) {
                this.handleCheckboxChange(e.target);
            }
        });
    }

    // 全选/全不选
    toggleSelectAll(checked) {
        const checkboxes = document.querySelectorAll(`.${this.checkboxClass}`);
        checkboxes.forEach(cb => {
            cb.checked = checked;
            const id = parseInt(cb.value);
            if (checked) {
                this.selectedIds.add(id);
            } else {
                this.selectedIds.delete(id);
            }
        });
        this.updateUI();
    }

    // 单个复选框变化
    handleCheckboxChange(checkbox) {
        const id = parseInt(checkbox.value);
        if (checkbox.checked) {
            this.selectedIds.add(id);
        } else {
            this.selectedIds.delete(id);
        }
        this.updateUI();
        this.updateSelectAllState();
    }

    // 更新全选按钮状态
    updateSelectAllState() {
        const selectAll = document.getElementById(this.selectAllId);
        if (!selectAll) return;

        const checkboxes = document.querySelectorAll(`.${this.checkboxClass}`);
        const checkedBoxes = document.querySelectorAll(`.${this.checkboxClass}:checked`);

        if (checkboxes.length > 0 && checkedBoxes.length === checkboxes.length) {
            selectAll.checked = true;
            selectAll.indeterminate = false;
        } else if (checkedBoxes.length > 0) {
            selectAll.checked = false;
            selectAll.indeterminate = true;
        } else {
            selectAll.checked = false;
            selectAll.indeterminate = false;
        }
    }

    // 更新UI
    updateUI() {
        const bar = document.getElementById(this.barId);
        const countEl = document.getElementById(this.countId);
        
        if (bar && countEl) {
            countEl.textContent = `已选择 ${this.selectedIds.size} 个`;
            
            if (this.selectedIds.size > 0) {
                bar.classList.add('visible');
            } else {
                bar.classList.remove('visible');
            }
        }

        this.onSelectionChange(Array.from(this.selectedIds));
    }

    // 获取选中的ID列表
    getSelectedIds() {
        return Array.from(this.selectedIds);
    }

    // 清空选择
    clear() {
        this.selectedIds.clear();
        const checkboxes = document.querySelectorAll(`.${this.checkboxClass}`);
        checkboxes.forEach(cb => cb.checked = false);
        this.updateUI();
        this.updateSelectAllState();
    }
}

// ============================================
// 3. 页码大小选择器
// ============================================
class PageSizeSelector {
    constructor(options = {}) {
        this.triggerId = options.triggerId || 'pageSizeTrigger';
        this.dropdownId = options.dropdownId || 'pageSizeDropdown';
        this.textId = options.textId || 'pageSizeText';
        this.currentSize = options.currentSize || 20;
        this.options = options.options || [20, 50, 100, 200];
        this.onChange = options.onChange || (() => {});
    }

    // 初始化
    init() {
        const trigger = document.getElementById(this.triggerId);
        if (trigger) {
            trigger.addEventListener('click', () => {
                this.toggle();
            });
        }

        // 点击外部关闭
        document.addEventListener('click', (e) => {
            const wrapper = document.getElementById(this.triggerId)?.closest('.page-size-wrapper');
            if (wrapper && !wrapper.contains(e.target)) {
                this.close();
            }
        });
    }

    // 切换下拉框
    toggle() {
        const dropdown = document.getElementById(this.dropdownId);
        if (dropdown) {
            dropdown.classList.toggle('open');
        }
    }

    // 关闭下拉框
    close() {
        const dropdown = document.getElementById(this.dropdownId);
        if (dropdown) {
            dropdown.classList.remove('open');
        }
    }

    // 设置选中的大小
    setSize(size) {
        this.currentSize = parseInt(size);
        
        // 更新显示文本
        const textEl = document.getElementById(this.textId);
        if (textEl) {
            textEl.textContent = size + '条';
        }

        // 更新选中状态
        document.querySelectorAll('.page-size-option').forEach(opt => {
            opt.classList.remove('selected');
            if (opt.textContent === size + '条') {
                opt.classList.add('selected');
            }
        });

        this.close();
        this.onChange(this.currentSize);
    }
}

// ============================================
// 4. 通用工具函数
// ============================================
const Utils = {
    // 格式化多选参数
    formatMultiSelect(values) {
        if (!values) return '';
        if (Array.isArray(values)) {
            const nonEmpty = values.filter(v => v !== '');
            return nonEmpty.length > 0 ? nonEmpty.join(',') : '';
        }
        return values;
    },

    // 防抖函数
    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    },

    // 获取CSRF Token
    getCSRFToken() {
        const cookieValue = document.cookie
            .split('; ')
            .find(row => row.startsWith('csrftoken='))
            ?.split('=')[1];
        return cookieValue || '';
    },

    // 显示通知（使用base.html中的showNotification）
    showNotification(message, type = 'info', duration = 3000) {
        if (typeof showNotification === 'function') {
            showNotification(message, type, duration);
        } else {
            console.log(`[${type}] ${message}`);
        }
    },

    // 确认对话框
    confirm(message, onConfirm, onCancel) {
        if (confirm(message)) {
            onConfirm && onConfirm();
        } else {
            onCancel && onCancel();
        }
    }
};

// ============================================
// 5. 表格数据管理
// ============================================
class TableDataManager {
    constructor(options = {}) {
        this.apiUrl = options.apiUrl || '';
        this.onDataLoaded = options.onDataLoaded || (() => {});
        this.onError = options.onError || (() => {});
        this.currentPage = 1;
        this.pageSize = 20;
        this.total = 0;
    }

    // 加载数据
    async load(params = {}) {
        try {
            const queryParams = new URLSearchParams({
                page: this.currentPage,
                page_size: this.pageSize,
                ...params
            });

            const response = await fetch(`${this.apiUrl}?${queryParams}`);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            const result = await response.json();
            if (result.success) {
                this.total = result.total;
                this.onDataLoaded(result.data, result.total, result.page, result.page_size);
                return result;
            } else {
                throw new Error(result.error || '加载数据失败');
            }
        } catch (error) {
            console.error('加载数据错误:', error);
            this.onError(error.message);
            return { data: [], total: 0 };
        }
    }

    // 设置页码
    setPage(page) {
        this.currentPage = page;
    }

    // 设置每页大小
    setPageSize(size) {
        this.pageSize = parseInt(size);
        this.currentPage = 1;
    }
}

// ============================================
// 6. 模态框管理
// ============================================
class ModalManager {
    constructor(options = {}) {
        this.overlayId = options.overlayId || 'modalOverlay';
        this.contentId = options.contentId || 'modalContent';
        this.onOpen = options.onOpen || (() => {});
        this.onClose = options.onClose || (() => {});
    }

    // 打开模态框
    open(content = null) {
        const overlay = document.getElementById(this.overlayId);
        if (overlay) {
            if (content) {
                const contentEl = document.getElementById(this.contentId);
                if (contentEl) contentEl.innerHTML = content;
            }
            overlay.style.display = 'block';
            this.onOpen();
        }
    }

    // 关闭模态框
    close() {
        const overlay = document.getElementById(this.overlayId);
        if (overlay) {
            overlay.style.display = 'none';
            this.onClose();
        }
    }
}

// ============================================
// 导出组件
// ============================================
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { Pagination, BulkActions, PageSizeSelector, Utils, TableDataManager, ModalManager };
}
