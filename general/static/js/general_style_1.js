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
const GeneralStyleYearMonthPicker = (() => {
    const parseMonthValue = (value) => {
        const match = String(value || '').match(/^(\d{4})-(\d{2})$/);
        if (!match) return null;
        const year = Number(match[1]);
        const month = Number(match[2]);
        if (!year || month < 1 || month > 12) return null;
        return { year, month };
    };

    const formatMonthValue = (year, month) => `${year}-${String(month).padStart(2, '0')}`;

    const getCurrentMonthValue = () => {
        const now = new Date();
        return formatMonthValue(now.getFullYear(), now.getMonth() + 1);
    };

    const shiftMonthValue = (value, step) => {
        const parsed = parseMonthValue(value);
        if (!parsed) return '';
        const dt = new Date(parsed.year, parsed.month - 1 + step, 1);
        return formatMonthValue(dt.getFullYear(), dt.getMonth() + 1);
    };

    const role = (container, name) => container.querySelector(`[data-ym-role="${name}"]`);

    const initOne = (container) => {
        if (!container || container.dataset.ymInitialized === '1') return null;

        const input = role(container, 'input');
        const prevBtn = role(container, 'prev');
        const nextBtn = role(container, 'next');
        const clearBtn = role(container, 'clear');
        const popover = role(container, 'popover');
        const yearLabel = role(container, 'year-label');
        const yearInput = role(container, 'year-input');
        const yearPrevBtn = role(container, 'year-prev');
        const yearNextBtn = role(container, 'year-next');
        const monthGrid = role(container, 'month-grid');
        const todayBtn = role(container, 'today');

        if (!input || !prevBtn || !nextBtn || !clearBtn || !popover || !yearLabel || !yearInput || !yearPrevBtn || !yearNextBtn || !monthGrid || !todayBtn) {
            return null;
        }

        container.dataset.ymInitialized = '1';
        let viewYear = parseMonthValue(input.value)?.year || new Date().getFullYear();
        let yearEditing = false;
        let yearBlurTimer = null;

        const clampYear = (year) => Math.min(9999, Math.max(1, year));

        const renderGrid = () => {
            yearLabel.textContent = `${viewYear}`;
            yearInput.value = String(viewYear);
            const selected = parseMonthValue(input.value);
            monthGrid.innerHTML = Array.from({ length: 12 }, (_, index) => {
                const month = index + 1;
                const active = selected && selected.year === viewYear && selected.month === month ? 'active' : '';
                return `<button type="button" class="ym-picker-month-btn ${active}" data-ym-month="${month}">${String(month).padStart(2, '0')}</button>`;
            }).join('');
        };

        const finishYearEdit = (applyChange, config = {}) => {
            const shouldRender = config.render !== false;
            if (!yearEditing) return;
            if (applyChange) {
                const raw = yearInput.value.trim();
                if (/^\d{1,4}$/.test(raw)) {
                    viewYear = clampYear(Number(raw));
                    yearLabel.textContent = `${viewYear}`;
                    yearInput.value = String(viewYear);
                    if (shouldRender) renderGrid();
                } else if (shouldRender) {
                    renderGrid();
                }
            }
            yearInput.hidden = true;
            yearLabel.hidden = false;
            yearEditing = false;
        };

        const startYearEdit = () => {
            if (yearBlurTimer) {
                clearTimeout(yearBlurTimer);
                yearBlurTimer = null;
            }
            yearEditing = true;
            yearLabel.hidden = true;
            yearInput.hidden = false;
            yearInput.value = String(viewYear);
            yearInput.focus();
            yearInput.select();
        };

        const openPopover = () => {
            const selectedYear = parseMonthValue(input.value)?.year;
            if (selectedYear) viewYear = selectedYear;
            if (yearBlurTimer) {
                clearTimeout(yearBlurTimer);
                yearBlurTimer = null;
            }
            finishYearEdit(false);
            renderGrid();
            popover.hidden = false;
            container.classList.add('open');
        };

        const closePopover = () => {
            if (yearBlurTimer) {
                clearTimeout(yearBlurTimer);
                yearBlurTimer = null;
            }
            finishYearEdit(true);
            popover.hidden = true;
            container.classList.remove('open');
        };

        const pickMonth = (month) => {
            if (yearBlurTimer) {
                clearTimeout(yearBlurTimer);
                yearBlurTimer = null;
            }
            finishYearEdit(true, { render: false });
            input.value = formatMonthValue(viewYear, month);
            closePopover();
        };

        prevBtn.addEventListener('click', () => {
            input.value = shiftMonthValue(input.value || getCurrentMonthValue(), -1);
            if (!popover.hidden) renderGrid();
        });

        nextBtn.addEventListener('click', () => {
            input.value = shiftMonthValue(input.value || getCurrentMonthValue(), 1);
            if (!popover.hidden) renderGrid();
        });

        clearBtn.addEventListener('click', () => {
            input.value = '';
            input.focus();
            if (!popover.hidden) renderGrid();
        });

        input.addEventListener('click', () => {
            openPopover();
        });

        input.addEventListener('focus', () => {
            if (popover.hidden) openPopover();
        });

        yearPrevBtn.addEventListener('click', () => {
            viewYear = clampYear(viewYear - 1);
            renderGrid();
        });

        yearNextBtn.addEventListener('click', () => {
            viewYear = clampYear(viewYear + 1);
            renderGrid();
        });

        yearLabel.addEventListener('click', (event) => {
            event.stopPropagation();
            startYearEdit();
        });

        yearInput.addEventListener('click', (event) => {
            event.stopPropagation();
        });

        yearInput.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                if (yearBlurTimer) {
                    clearTimeout(yearBlurTimer);
                    yearBlurTimer = null;
                }
                finishYearEdit(true);
            } else if (event.key === 'Escape') {
                event.preventDefault();
                if (yearBlurTimer) {
                    clearTimeout(yearBlurTimer);
                    yearBlurTimer = null;
                }
                finishYearEdit(false);
            }
        });

        yearInput.addEventListener('blur', () => {
            if (yearBlurTimer) clearTimeout(yearBlurTimer);
            yearBlurTimer = setTimeout(() => {
                finishYearEdit(true);
                yearBlurTimer = null;
            }, 0);
        });

        monthGrid.addEventListener('mousedown', (event) => {
            const target = event.target.closest('.ym-picker-month-btn');
            if (!target) return;
            event.preventDefault();
            pickMonth(Number(target.dataset.ymMonth));
        });

        monthGrid.addEventListener('click', (event) => {
            const target = event.target.closest('.ym-picker-month-btn');
            if (!target) return;
            pickMonth(Number(target.dataset.ymMonth));
        });

        todayBtn.addEventListener('click', () => {
            input.value = getCurrentMonthValue();
            viewYear = parseMonthValue(input.value)?.year || viewYear;
            closePopover();
        });

        document.addEventListener('click', (event) => {
            if (!container.contains(event.target)) closePopover();
        });

        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') closePopover();
        });

        return {
            open: openPopover,
            close: closePopover
        };
    };

    const initAll = (root = document) => {
        const containers = root.querySelectorAll('[data-ym-picker]');
        containers.forEach((container) => initOne(container));
    };

    return { initOne, initAll };
})();

const GeneralStyleDatePicker = (() => {
    const WEEKDAY_LABELS = ['日', '一', '二', '三', '四', '五', '六'];
    const AUTO_INPUT_SELECTOR = 'input[type="date"]';
    let autoObserver = null;

    const createDate = (year, month, day) => new Date(year, month - 1, day);

    const parseDateValue = (value) => {
        const match = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})$/);
        if (!match) return null;
        const year = Number(match[1]);
        const month = Number(match[2]);
        const day = Number(match[3]);
        if (!year || month < 1 || month > 12 || day < 1 || day > 31) return null;
        const dt = createDate(year, month, day);
        if (dt.getFullYear() !== year || dt.getMonth() + 1 !== month || dt.getDate() !== day) return null;
        return { year, month, day };
    };

    const formatDateParts = (year, month, day) =>
        `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;

    const formatDateValue = (date) => {
        return formatDateParts(date.getFullYear(), date.getMonth() + 1, date.getDate());
    };

    const getCurrentDateValue = () => formatDateValue(new Date());

    const daysInMonth = (year, month) => new Date(year, month, 0).getDate();

    const shiftMonth = (year, month, step) => {
        const dt = new Date(year, month - 1 + step, 1);
        return { year: dt.getFullYear(), month: dt.getMonth() + 1 };
    };

    const shiftDateValue = (value, stepDays) => {
        const parsed = parseDateValue(value);
        if (!parsed) return '';
        const dt = new Date(parsed.year, parsed.month - 1, parsed.day);
        dt.setDate(dt.getDate() + stepDays);
        return formatDateValue(dt);
    };

    const role = (container, name) => container.querySelector(`[data-ymd-role="${name}"]`);

    const emitChange = (input) => {
        input.dispatchEvent(new Event('change', { bubbles: true }));
    };

    const NAV_ICON_HTML = {
        prev: '<i class="fas fa-chevron-left"></i>',
        next: '<i class="fas fa-chevron-right"></i>'
    };

    const createControlButton = (roleName, className, title, text, html = null) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `ymd-picker-btn ${className}`;
        button.title = title;
        button.dataset.ymdRole = roleName;
        if (html) {
            button.innerHTML = html;
        } else {
            button.textContent = text;
        }
        return button;
    };

    const ensureControls = (container, input) => {
        if (!container || !input) return null;

        input.dataset.ymdRole = 'input';
        input.classList.add('ymd-picker-input');

        let prevBtn = role(container, 'prev-day') || container.querySelector('.ymd-picker-btn--prev');
        if (!prevBtn) {
            prevBtn = createControlButton(
                'prev-day',
                'ymd-picker-btn--nav ymd-picker-btn--prev',
                '上一天',
                '',
                NAV_ICON_HTML.prev
            );
            container.insertBefore(prevBtn, input);
        } else {
            prevBtn.dataset.ymdRole = 'prev-day';
            prevBtn.type = 'button';
            if (prevBtn.children.length === 0) {
                const raw = (prevBtn.textContent || '').trim();
                if (raw === '<' || raw === '‹' || raw === '') {
                    prevBtn.innerHTML = NAV_ICON_HTML.prev;
                }
            }
        }

        let nextBtn = role(container, 'next-day') || container.querySelector('.ymd-picker-btn--next');
        if (!nextBtn) {
            nextBtn = createControlButton(
                'next-day',
                'ymd-picker-btn--nav ymd-picker-btn--next',
                '下一天',
                '',
                NAV_ICON_HTML.next
            );
            container.appendChild(nextBtn);
        } else {
            nextBtn.dataset.ymdRole = 'next-day';
            nextBtn.type = 'button';
            if (nextBtn.children.length === 0) {
                const raw = (nextBtn.textContent || '').trim();
                if (raw === '>' || raw === '›' || raw === '') {
                    nextBtn.innerHTML = NAV_ICON_HTML.next;
                }
            }
        }

        let clearBtn = role(container, 'clear') || container.querySelector('.ymd-picker-btn--clear');
        if (!clearBtn) {
            clearBtn = createControlButton('clear', 'ymd-picker-btn--clear', '清空日期', '×');
            container.appendChild(clearBtn);
        } else {
            clearBtn.dataset.ymdRole = 'clear';
            clearBtn.type = 'button';
            if (clearBtn.children.length === 0) {
                const raw = (clearBtn.textContent || '').trim();
                if (!raw || raw.toLowerCase() === 'x') {
                    clearBtn.textContent = '×';
                }
            }
        }

        return container;
    };

    const wrapInputToContainer = (input) => {
        if (!input || !input.parentNode) return null;
        const container = document.createElement('div');
        container.className = 'ymd-picker';
        container.dataset.ymdPicker = '';
        container.dataset.ymdAuto = '1';
        input.parentNode.insertBefore(container, input);
        container.appendChild(input);
        return ensureControls(container, input);
    };

    const ensureContainerForInput = (input) => {
        if (!input || input.type !== 'date') return null;
        const existingContainer = input.closest('[data-ymd-picker]');
        if (existingContainer) {
            return ensureControls(existingContainer, input);
        }
        return wrapInputToContainer(input);
    };

    const buildPopover = (container) => {
        const popover = document.createElement('div');
        popover.className = 'ymd-picker-popover';
        popover.hidden = true;
        popover.dataset.ymdRole = 'popover';
        popover.innerHTML = `
            <div class="ymd-picker-header">
                <button type="button" class="ymd-picker-period-btn" data-ymd-role="month-prev" aria-label="上月">‹</button>
                <div class="ymd-picker-period">
                    <button type="button" class="ymd-picker-year-label" data-ymd-role="year-label" aria-label="编辑年份"></button>
                    <input type="text" class="ymd-picker-year-input" data-ymd-role="year-input" inputmode="numeric" maxlength="4" hidden>
                    <button type="button" class="ymd-picker-month-label" data-ymd-role="month-label" aria-label="编辑月份"></button>
                    <input type="text" class="ymd-picker-month-input" data-ymd-role="month-input" inputmode="numeric" maxlength="2" hidden>
                </div>
                <button type="button" class="ymd-picker-period-btn" data-ymd-role="month-next" aria-label="下月">›</button>
            </div>
            <div class="ymd-picker-weekdays">
                ${WEEKDAY_LABELS.map((label) => `<span class="ymd-picker-weekday">${label}</span>`).join('')}
            </div>
            <div class="ymd-picker-grid" data-ymd-role="day-grid"></div>
            <div class="ymd-picker-actions">
                <button type="button" class="ymd-picker-today-btn" data-ymd-role="today">今天</button>
            </div>
        `;
        container.appendChild(popover);
        return popover;
    };

    const isSameYmd = (left, right) => {
        if (!left || !right) return false;
        return left.year === right.year && left.month === right.month && left.day === right.day;
    };

    const initOne = (container) => {
        if (!container || container.dataset.ymdInitialized === '1') return null;

        const input = role(container, 'input');
        const prevBtn = role(container, 'prev-day');
        const nextBtn = role(container, 'next-day');
        const clearBtn = role(container, 'clear');
        if (!input || !prevBtn || !nextBtn || !clearBtn) return null;

        const popover = role(container, 'popover') || buildPopover(container);
        const yearLabel = role(container, 'year-label');
        const yearInput = role(container, 'year-input');
        const monthLabel = role(container, 'month-label');
        const monthInput = role(container, 'month-input');
        const monthPrevBtn = role(container, 'month-prev');
        const monthNextBtn = role(container, 'month-next');
        const dayGrid = role(container, 'day-grid');
        const todayBtn = role(container, 'today');
        if (!popover || !yearLabel || !yearInput || !monthLabel || !monthInput || !monthPrevBtn || !monthNextBtn || !dayGrid || !todayBtn) {
            return null;
        }

        container.dataset.ymdInitialized = '1';
        const current = parseDateValue(getCurrentDateValue());
        let viewYear = parseDateValue(input.value)?.year || current.year;
        let viewMonth = parseDateValue(input.value)?.month || current.month;
        let yearEditing = false;
        let monthEditing = false;
        let yearBlurTimer = null;
        let monthBlurTimer = null;

        const clampYear = (year) => Math.min(9999, Math.max(1, year));
        const clampMonth = (month) => Math.min(12, Math.max(1, month));

        const renderGrid = () => {
            const selected = parseDateValue(input.value);
            const today = parseDateValue(getCurrentDateValue());

            yearLabel.textContent = `${viewYear}年`;
            yearInput.value = String(viewYear);
            monthLabel.textContent = `${String(viewMonth).padStart(2, '0')}月`;
            monthInput.value = String(viewMonth);

            const firstWeekday = createDate(viewYear, viewMonth, 1).getDay();
            const currentMonthDays = daysInMonth(viewYear, viewMonth);

            const prev = shiftMonth(viewYear, viewMonth, -1);
            const prevMonthDays = daysInMonth(prev.year, prev.month);
            const cells = [];

            for (let i = 0; i < firstWeekday; i += 1) {
                const day = prevMonthDays - firstWeekday + i + 1;
                cells.push({ year: prev.year, month: prev.month, day, muted: true });
            }

            for (let day = 1; day <= currentMonthDays; day += 1) {
                cells.push({ year: viewYear, month: viewMonth, day, muted: false });
            }

            const next = shiftMonth(viewYear, viewMonth, 1);
            while (cells.length < 42) {
                const day = cells.length - (firstWeekday + currentMonthDays) + 1;
                cells.push({ year: next.year, month: next.month, day, muted: true });
            }

            dayGrid.innerHTML = cells.map((cell) => {
                const value = formatDateParts(cell.year, cell.month, cell.day);
                const parsed = parseDateValue(value);
                const classes = ['ymd-picker-day-btn'];
                if (cell.muted) classes.push('muted');
                if (isSameYmd(parsed, today)) classes.push('today');
                if (isSameYmd(parsed, selected)) classes.push('active');
                return `<button type="button" class="${classes.join(' ')}" data-ymd-date="${value}">${cell.day}</button>`;
            }).join('');
        };

        const finishYearEdit = (applyChange, config = {}) => {
            const shouldRender = config.render !== false;
            if (!yearEditing) return;
            if (applyChange) {
                const raw = yearInput.value.trim();
                if (/^\d{1,4}$/.test(raw)) {
                    viewYear = clampYear(Number(raw));
                }
            }
            yearInput.hidden = true;
            yearLabel.hidden = false;
            yearEditing = false;
            if (shouldRender && !popover.hidden) renderGrid();
        };

        const finishMonthEdit = (applyChange, config = {}) => {
            const shouldRender = config.render !== false;
            if (!monthEditing) return;
            if (applyChange) {
                const raw = monthInput.value.trim();
                if (/^\d{1,2}$/.test(raw)) {
                    viewMonth = clampMonth(Number(raw));
                }
            }
            monthInput.hidden = true;
            monthLabel.hidden = false;
            monthEditing = false;
            if (shouldRender && !popover.hidden) renderGrid();
        };

        const startYearEdit = () => {
            if (yearBlurTimer) {
                clearTimeout(yearBlurTimer);
                yearBlurTimer = null;
            }
            finishMonthEdit(true, { render: false });
            yearEditing = true;
            yearLabel.hidden = true;
            yearInput.hidden = false;
            yearInput.value = String(viewYear);
            yearInput.focus();
            yearInput.select();
        };

        const startMonthEdit = () => {
            if (monthBlurTimer) {
                clearTimeout(monthBlurTimer);
                monthBlurTimer = null;
            }
            finishYearEdit(true, { render: false });
            monthEditing = true;
            monthLabel.hidden = true;
            monthInput.hidden = false;
            monthInput.value = String(viewMonth);
            monthInput.focus();
            monthInput.select();
        };

        const syncViewFromInput = () => {
            const selected = parseDateValue(input.value);
            if (!selected) return;
            viewYear = selected.year;
            viewMonth = selected.month;
        };

        const openPopover = () => {
            syncViewFromInput();
            if (yearBlurTimer) {
                clearTimeout(yearBlurTimer);
                yearBlurTimer = null;
            }
            if (monthBlurTimer) {
                clearTimeout(monthBlurTimer);
                monthBlurTimer = null;
            }
            finishYearEdit(false);
            finishMonthEdit(false);
            renderGrid();
            popover.hidden = false;
            container.classList.add('open');
        };

        const closePopover = () => {
            if (yearBlurTimer) {
                clearTimeout(yearBlurTimer);
                yearBlurTimer = null;
            }
            if (monthBlurTimer) {
                clearTimeout(monthBlurTimer);
                monthBlurTimer = null;
            }
            finishYearEdit(true);
            finishMonthEdit(true);
            popover.hidden = true;
            container.classList.remove('open');
        };

        const pickDate = (value) => {
            if (yearBlurTimer) {
                clearTimeout(yearBlurTimer);
                yearBlurTimer = null;
            }
            if (monthBlurTimer) {
                clearTimeout(monthBlurTimer);
                monthBlurTimer = null;
            }
            finishYearEdit(true, { render: false });
            finishMonthEdit(true, { render: false });
            if (!parseDateValue(value)) return;
            input.value = value;
            emitChange(input);
            closePopover();
        };

        prevBtn.addEventListener('click', () => {
            const base = input.value || getCurrentDateValue();
            input.value = shiftDateValue(base, -1);
            emitChange(input);
            if (!popover.hidden) {
                syncViewFromInput();
                renderGrid();
            }
        });

        nextBtn.addEventListener('click', () => {
            const base = input.value || getCurrentDateValue();
            input.value = shiftDateValue(base, 1);
            emitChange(input);
            if (!popover.hidden) {
                syncViewFromInput();
                renderGrid();
            }
        });

        clearBtn.addEventListener('click', () => {
            input.value = '';
            emitChange(input);
            input.focus();
            if (!popover.hidden) renderGrid();
        });

        input.addEventListener('click', () => {
            openPopover();
        });

        input.addEventListener('focus', () => {
            if (popover.hidden) openPopover();
        });

        monthPrevBtn.addEventListener('click', () => {
            finishYearEdit(true, { render: false });
            finishMonthEdit(true, { render: false });
            const shifted = shiftMonth(viewYear, viewMonth, -1);
            viewYear = shifted.year;
            viewMonth = shifted.month;
            renderGrid();
        });

        monthNextBtn.addEventListener('click', () => {
            finishYearEdit(true, { render: false });
            finishMonthEdit(true, { render: false });
            const shifted = shiftMonth(viewYear, viewMonth, 1);
            viewYear = shifted.year;
            viewMonth = shifted.month;
            renderGrid();
        });

        yearLabel.addEventListener('click', (event) => {
            event.stopPropagation();
            startYearEdit();
        });

        monthLabel.addEventListener('click', (event) => {
            event.stopPropagation();
            startMonthEdit();
        });

        yearInput.addEventListener('click', (event) => {
            event.stopPropagation();
        });

        monthInput.addEventListener('click', (event) => {
            event.stopPropagation();
        });

        yearInput.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                if (yearBlurTimer) {
                    clearTimeout(yearBlurTimer);
                    yearBlurTimer = null;
                }
                finishYearEdit(true);
            } else if (event.key === 'Escape') {
                event.preventDefault();
                if (yearBlurTimer) {
                    clearTimeout(yearBlurTimer);
                    yearBlurTimer = null;
                }
                finishYearEdit(false);
            }
        });

        monthInput.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                if (monthBlurTimer) {
                    clearTimeout(monthBlurTimer);
                    monthBlurTimer = null;
                }
                finishMonthEdit(true);
            } else if (event.key === 'Escape') {
                event.preventDefault();
                if (monthBlurTimer) {
                    clearTimeout(monthBlurTimer);
                    monthBlurTimer = null;
                }
                finishMonthEdit(false);
            }
        });

        yearInput.addEventListener('blur', () => {
            if (yearBlurTimer) clearTimeout(yearBlurTimer);
            yearBlurTimer = setTimeout(() => {
                finishYearEdit(true);
                yearBlurTimer = null;
            }, 0);
        });

        monthInput.addEventListener('blur', () => {
            if (monthBlurTimer) clearTimeout(monthBlurTimer);
            monthBlurTimer = setTimeout(() => {
                finishMonthEdit(true);
                monthBlurTimer = null;
            }, 0);
        });

        dayGrid.addEventListener('mousedown', (event) => {
            const target = event.target.closest('.ymd-picker-day-btn');
            if (!target) return;
            event.preventDefault();
            pickDate(target.dataset.ymdDate);
        });

        dayGrid.addEventListener('click', (event) => {
            const target = event.target.closest('.ymd-picker-day-btn');
            if (!target) return;
            pickDate(target.dataset.ymdDate);
        });

        todayBtn.addEventListener('click', () => {
            input.value = getCurrentDateValue();
            emitChange(input);
            syncViewFromInput();
            closePopover();
        });

        document.addEventListener('click', (event) => {
            if (!container.contains(event.target)) closePopover();
        });

        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') closePopover();
        });

        return {
            input,
            open: openPopover,
            close: closePopover
        };
    };

    const initAll = (root = document) => {
        if (!root || typeof root.querySelectorAll !== 'function') return;

        const containers = new Set();
        const dateInputs = root.querySelectorAll(AUTO_INPUT_SELECTOR);
        dateInputs.forEach((input) => {
            const container = ensureContainerForInput(input);
            if (container) containers.add(container);
        });

        const pickerContainers = root.querySelectorAll('[data-ymd-picker]');
        pickerContainers.forEach((container) => {
            const input = role(container, 'input') || container.querySelector(AUTO_INPUT_SELECTOR);
            if (!input) return;
            const normalized = ensureControls(container, input);
            if (normalized) containers.add(normalized);
        });

        containers.forEach((container) => initOne(container));
    };

    const observe = () => {
        if (typeof MutationObserver === 'undefined' || autoObserver || typeof document === 'undefined') return;
        if (!document.body) return;

        autoObserver = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                mutation.addedNodes.forEach((node) => {
                    if (!(node instanceof Element)) return;

                    if (node.matches(AUTO_INPUT_SELECTOR) || node.matches('[data-ymd-picker]')) {
                        initAll(node.parentElement || document);
                        return;
                    }

                    if (node.querySelector(AUTO_INPUT_SELECTOR) || node.querySelector('[data-ymd-picker]')) {
                        initAll(node);
                    }
                });
            });
        });

        autoObserver.observe(document.body, { childList: true, subtree: true });
    };

    return { initOne, initAll, observe };
})();

const GeneralStyleFilterSelectAdapter = (() => {
    const FILTER_ROOT_SELECTOR = '.filter-section, .control-panel, .filter-row, .filter-row-main, .filter-row-secondary';
    const TARGET_SELECTOR = 'select.form-select';
    let observer = null;
    const adaptedEntries = [];
    let syncTimer = null;

    const toArray = (nodeList) => Array.from(nodeList || []);

    const getLabelText = (select) => {
        const group = select.closest('.filter-group');
        const label = group?.querySelector('.filter-label');
        return (label?.textContent || '').trim();
    };

    const getPlaceholder = (select) => {
        const selected = toArray(select.options).find((opt) => opt.selected);
        const emptyOpt = toArray(select.options).find((opt) => String(opt.value || '') === '');
        return (
            select.dataset.placeholder ||
            selected?.textContent?.trim() ||
            emptyOpt?.textContent?.trim() ||
            getLabelText(select) ||
            '请选择'
        );
    };

    const shouldSkip = (select) => {
        if (!select || select.dataset.gsSelectAdapted === '1') return true;
        if (select.closest('[data-ym-picker], [data-ymd-picker]')) return true;
        if (!select.closest(FILTER_ROOT_SELECTOR)) return true;
        if (select.closest('.modal-overlay, .modal-content, .modal-body, .modal-footer')) return true;
        if (select.closest('.pagination-container, .pagination-controls, .page-size-wrapper')) return true;
        if ((select.id || '').toLowerCase().includes('pagesize')) return true;
        if (select.dataset.noSearchable === '1') return true;
        return false;
    };

    const isSemanticMultiple = (select) => {
        if (!select) return false;
        if (select.multiple) return true;
        if (select.dataset.searchableMultiple === 'true') return true;
        if (select.dataset.searchableMultiple === 'false') return false;
        // 默认保持单选，避免旧接口未支持多值导致筛选结果异常
        return false;
    };

    const mapOptions = (select) => {
        return toArray(select.options).map((opt) => ({
            value: String(opt.value ?? ''),
            label: String(opt.textContent || '').trim(),
            disabled: !!opt.disabled
        }));
    };

    const getSelectValues = (select, multiple) => {
        if (!multiple) return String(select.value ?? '');
        const selected = toArray(select.selectedOptions).map((opt) => String(opt.value ?? ''));
        if (selected.length === 0) return [''];
        if (selected.includes('')) return [''];
        return selected;
    };

    const syncNativeSelect = (select, value, multiple) => {
        if (!multiple) {
            const text = String(value ?? '');
            select.multiple = false;
            select.value = text;
            select.dataset.multiValue = '';
            return;
        }

        const values = Array.isArray(value)
            ? value.map((v) => String(v ?? ''))
            : String(value ?? '').split(',').map((v) => v.trim()).filter(Boolean);

        const normalized = values.filter((v) => v !== '');
        select.multiple = true;

        toArray(select.options).forEach((opt) => {
            const optValue = String(opt.value ?? '');
            opt.selected = normalized.includes(optValue) || (normalized.length === 0 && optValue === '');
        });

        // 兼容仍读取 select.value 的旧逻辑
        select.dataset.multiValue = normalized.join(',');
    };

    const readNativeValue = (select, multiple) => {
        if (!multiple) return String(select.value ?? '');
        const selected = toArray(select.selectedOptions).map((opt) => String(opt.value ?? ''));
        const normalized = selected.filter((v) => v !== '');
        return normalized.length > 0 ? normalized : [''];
    };

    const modelKey = (value, multiple) => {
        if (!multiple) return String(value ?? '');
        return JSON.stringify(Array.isArray(value) ? value : []);
    };

    const ensureSyncLoop = () => {
        if (syncTimer || typeof window === 'undefined') return;
        syncTimer = window.setInterval(() => {
            adaptedEntries.forEach((entry) => {
                if (!entry || entry.syncing) return;
                const current = readNativeValue(entry.select, entry.multiple);
                const key = modelKey(current, entry.multiple);
                if (key === entry.lastModelKey) return;
                entry.syncing = true;
                entry.instance.setValue(current);
                entry.lastModelKey = key;
                entry.syncing = false;
            });
        }, 400);
    };

    const adaptOne = (select) => {
        if (shouldSkip(select)) return null;
        if (typeof window === 'undefined' || typeof window.SearchableSelect !== 'function') return null;

        const multiple = isSemanticMultiple(select);
        const placeholder = getPlaceholder(select);
        const options = mapOptions(select);

        const holder = document.createElement('div');
        holder.className = `searchable-select ${multiple ? 'multiple' : 'single'}`;
        holder.dataset.placeholder = placeholder;
        holder.dataset.gsSelectHolder = '1';
        holder.dataset.sourceSelectId = select.id || '';
        const wrapper = select.closest('.select-wrapper');
        const sameGroupWrapped = wrapper && wrapper.closest('.filter-group') === select.closest('.filter-group');
        if (sameGroupWrapped) {
            wrapper.insertAdjacentElement('afterend', holder);
            wrapper.style.display = 'none';
            wrapper.dataset.gsSelectWrapped = '1';
            select.style.display = 'none';
        } else {
            select.insertAdjacentElement('afterend', holder);
            select.style.display = 'none';
        }
        select.dataset.gsSelectAdapted = '1';

        const instance = new window.SearchableSelect(holder, {
            options,
            multiple,
            placeholder,
            searchable: true
        });

        const initialValue = getSelectValues(select, multiple);
        instance.setValue(initialValue);
        syncNativeSelect(select, initialValue, multiple);
        const entry = {
            select,
            instance,
            multiple,
            syncing: false,
            lastModelKey: modelKey(initialValue, multiple)
        };
        adaptedEntries.push(entry);
        ensureSyncLoop();

        instance.onChange = (newValue) => {
            entry.syncing = true;
            syncNativeSelect(select, newValue, multiple);
            entry.lastModelKey = modelKey(newValue, multiple);
            entry.syncing = false;
            select.dispatchEvent(new Event('change', { bubbles: true }));
        };

        select.addEventListener('change', () => {
            if (entry.syncing) return;
            const current = readNativeValue(select, multiple);
            const key = modelKey(current, multiple);
            if (key === entry.lastModelKey) return;
            entry.syncing = true;
            instance.setValue(current);
            entry.lastModelKey = key;
            entry.syncing = false;
        });

        return entry;
    };

    const initAll = (root = document) => {
        if (!root || typeof root.querySelectorAll !== 'function') return [];
        if (typeof window === 'undefined' || typeof window.SearchableSelect !== 'function') return [];

        const selects = toArray(root.querySelectorAll(TARGET_SELECTOR));
        const adapted = [];
        selects.forEach((select) => {
            const result = adaptOne(select);
            if (result) adapted.push(result);
        });
        return adapted;
    };

    const observeDom = () => {
        if (typeof MutationObserver === 'undefined' || observer || typeof document === 'undefined') return;
        if (!document.body) return;

        observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                mutation.addedNodes.forEach((node) => {
                    if (!(node instanceof Element)) return;
                    if (node.matches(TARGET_SELECTOR)) {
                        adaptOne(node);
                        return;
                    }
                    if (node.querySelector(TARGET_SELECTOR)) {
                        initAll(node);
                    }
                });
            });
        });

        observer.observe(document.body, { childList: true, subtree: true });
    };

    const getValue = (selectId) => {
        const select = typeof selectId === 'string' ? document.getElementById(selectId) : selectId;
        if (!select) return '';
        const multiValue = (select.dataset.multiValue || '').trim();
        if (multiValue) return multiValue.split(',').filter(Boolean);
        return String(select.value ?? '');
    };

    return { initAll, observeDom, getValue };
})();

if (typeof window !== 'undefined') {
    window.GeneralStyleYearMonthPicker = GeneralStyleYearMonthPicker;
    window.GeneralStyleDatePicker = GeneralStyleDatePicker;
    window.GeneralStyleFilterSelectAdapter = GeneralStyleFilterSelectAdapter;

    const bootDatePicker = () => {
        if (!window.GeneralStyleDatePicker) return;
        window.GeneralStyleDatePicker.initAll(document);
        window.GeneralStyleDatePicker.observe();
    };

    const bootFilterSelectAdapter = () => {
        if (!window.GeneralStyleFilterSelectAdapter) return;
        if (typeof window.SearchableSelect !== 'function') return;
        window.GeneralStyleFilterSelectAdapter.initAll(document);
        window.GeneralStyleFilterSelectAdapter.observeDom();
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bootDatePicker);
        document.addEventListener('DOMContentLoaded', bootFilterSelectAdapter);
    } else {
        bootDatePicker();
        bootFilterSelectAdapter();
    }
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        Pagination,
        BulkActions,
        PageSizeSelector,
        Utils,
        TableDataManager,
        ModalManager,
        GeneralStyleYearMonthPicker,
        GeneralStyleDatePicker,
        GeneralStyleFilterSelectAdapter
    };
}
