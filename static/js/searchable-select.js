/**
 * SearchableSelect - 可搜索下拉框组件
 * 支持单选和多选模式，可输入筛选
 * 
 * 使用方法:
 * 1. HTML结构: <div id="mySelect" class="searchable-select" data-placeholder="请选择..."></div>
 * 2. JS初始化: new SearchableSelect('#mySelect', { options: [...], multiple: false })
 * 3. 事件监听: select.onChange = (value) => { ... }
 */
class SearchableSelect {
    constructor(selector, config = {}) {
        this.container = typeof selector === 'string' ? document.querySelector(selector) : selector;
        if (!this.container) {
            console.error('SearchableSelect: 找不到元素', selector);
            return;
        }

        // 绑定实例到元素，方便通过 getInstance 获取
        this.container._searchableSelect = this;

        this.config = {
            multiple: false,           // 是否多选
            searchable: true,          // 是否可搜索
            placeholder: this.container.dataset.placeholder || '请选择...',
            searchPlaceholder: '输入关键字搜索...',
            emptyText: '暂无选项',
            noMatchText: '无匹配结果',
            clearable: true,           // 是否显示清空按钮
            ...config
        };

        this.options = this.config.options || [];
        this.selectedValues = this.config.multiple ? [] : '';
        this.isOpen = false;
        this.searchText = '';

        this.onChange = null;  // 回调函数

        this.init();
    }

    init() {
        this.render();
        this.bindEvents();
        this.updateDisplay();
    }

    render() {
        // 添加基础类名
        this.container.classList.add('searchable-select');
        if (this.config.multiple) {
            this.container.classList.add('multiple');
        } else {
            this.container.classList.add('single');
        }

        // 构建HTML
        this.container.innerHTML = `
            <div class="select-trigger">
                <span class="selected-text placeholder">${this.config.placeholder}</span>
                ${this.config.clearable ? '<span class="clear-btn" title="清空"><i class="fas fa-times-circle"></i></span>' : ''}
            </div>
            <div class="dropdown-panel">
                ${this.config.searchable ? `
                <div class="search-input-wrapper">
                    <input type="text" class="search-input" placeholder="${this.config.searchPlaceholder}">
                </div>
                ` : ''}
                <div class="options-list">
                    ${this.renderOptions()}
                </div>
            </div>
        `;

        this.trigger = this.container.querySelector('.select-trigger');
        this.dropdown = this.container.querySelector('.dropdown-panel');
        this.selectedText = this.container.querySelector('.selected-text');
        this.optionsList = this.container.querySelector('.options-list');
        this.searchInput = this.container.querySelector('.search-input');
        this.clearBtn = this.container.querySelector('.clear-btn');
    }

    renderOptions() {
        if (this.options.length === 0) {
            return `<div class="no-options">${this.config.emptyText}</div>`;
        }

        const filtered = this.getFilteredOptions();
        if (filtered.length === 0) {
            return `<div class="no-options">${this.config.noMatchText}</div>`;
        }

        return filtered.map(opt => {
            const isSelected = this.config.multiple 
                ? this.selectedValues.includes(opt.value) || this.selectedValues.includes(String(opt.value)) || this.selectedValues.includes(Number(opt.value))
                : this.selectedValues == opt.value || String(this.selectedValues) === String(opt.value);
            
            return `
                <div class="option ${isSelected ? 'selected' : ''} ${opt.disabled ? 'disabled' : ''}" 
                     data-value="${opt.value}">
                    ${this.config.multiple ? '<span class="checkbox"></span>' : ''}
                    <span class="option-text">${opt.label}</span>
                </div>
            `;
        }).join('');
    }

    getFilteredOptions() {
        if (!this.searchText) return this.options;
        const text = this.searchText.toLowerCase();
        return this.options.filter(opt => opt.label.toLowerCase().includes(text));
    }

    bindEvents() {
        // 点击触发器打开/关闭下拉框
        this.trigger.addEventListener('click', (e) => {
            if (e.target.closest('.clear-btn')) {
                e.stopPropagation();
                this.clear();
                return;
            }
            this.toggle();
        });

        // 搜索输入
        if (this.searchInput) {
            this.searchInput.addEventListener('input', (e) => {
                this.searchText = e.target.value;
                this.refreshOptions();
            });

            // 防止输入时关闭下拉框
            this.searchInput.addEventListener('click', (e) => {
                e.stopPropagation();
            });

            // 键盘导航
            this.searchInput.addEventListener('keydown', (e) => {
                this.handleKeydown(e);
            });
        }

        // 选项点击
        this.optionsList.addEventListener('click', (e) => {
            e.stopPropagation(); // 防止事件冒泡到 select-trigger
            const option = e.target.closest('.option');
            if (!option || option.classList.contains('disabled')) return;

            const value = option.dataset.value;
            this.selectOption(value);
        });

        // 点击外部关闭
        document.addEventListener('click', (e) => {
            if (!this.container.contains(e.target)) {
                this.close();
            }
        });
    }

    handleKeydown(e) {
        const options = this.optionsList.querySelectorAll('.option:not(.disabled)');
        const currentIndex = Array.from(options).findIndex(opt => opt.classList.contains('highlighted'));

        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                if (currentIndex < options.length - 1) {
                    if (currentIndex >= 0) options[currentIndex].classList.remove('highlighted');
                    options[currentIndex + 1].classList.add('highlighted');
                    options[currentIndex + 1].scrollIntoView({ block: 'nearest' });
                }
                break;
            case 'ArrowUp':
                e.preventDefault();
                if (currentIndex > 0) {
                    options[currentIndex].classList.remove('highlighted');
                    options[currentIndex - 1].classList.add('highlighted');
                    options[currentIndex - 1].scrollIntoView({ block: 'nearest' });
                }
                break;
            case 'Enter':
                e.preventDefault();
                const highlighted = this.optionsList.querySelector('.option.highlighted');
                if (highlighted) {
                    this.selectOption(highlighted.dataset.value);
                }
                break;
            case 'Escape':
                this.close();
                break;
        }
    }

    selectOption(value) {
        if (this.config.multiple) {
            const index = this.selectedValues.indexOf(value);
            const isAllOption = value === '' || value === null || value === undefined;
            
            if (index > -1) {
                // 取消选择
                this.selectedValues.splice(index, 1);
                // 如果取消后没有选中任何项，默认选中"全部"
                if (this.selectedValues.length === 0) {
                    this.selectedValues = [''];
                }
            } else {
                // 新增选择
                if (isAllOption) {
                    // 选择"全部"，清空其他所有选择
                    this.selectedValues = [''];
                } else {
                    // 选择其他选项，去掉"全部"
                    const allIndex = this.selectedValues.indexOf('');
                    if (allIndex > -1) {
                        this.selectedValues.splice(allIndex, 1);
                    }
                    this.selectedValues.push(value);
                    // 如果去掉"全部"后没有选中任何项，重新选中"全部"
                    if (this.selectedValues.length === 0) {
                        this.selectedValues = [''];
                    }
                }
            }
        } else {
            this.selectedValues = value;
            this.close();
        }

        this.updateDisplay();
        this.refreshOptions();

        if (this.onChange) {
            this.onChange(this.config.multiple ? [...this.selectedValues] : this.selectedValues);
        }
    }

    updateDisplay() {
        if (this.config.multiple) {
            // 多选显示 - 显示具体选项名，超出显示+N
            if (this.selectedValues.length === 0 || (this.selectedValues.length === 1 && this.selectedValues[0] === '')) {
                // 只选中了"全部"或什么都没选
                this.selectedText.innerHTML = `<span class="placeholder">${this.config.placeholder}</span>`;
            } else {
                // 获取选中的标签
                const selectedLabels = this.selectedValues
                    .filter(v => v !== '') // 排除"全部"
                    .map(v => {
                        const opt = this.options.find(o => String(o.value) === String(v));
                        return opt ? opt.label : v;
                    });
                
                // 根据容器宽度显示，简单实现：最多显示2个，超出显示+N
                const maxDisplay = 2;
                if (selectedLabels.length <= maxDisplay) {
                    this.selectedText.textContent = selectedLabels.join('、');
                } else {
                    const displayed = selectedLabels.slice(0, maxDisplay).join('、');
                    const remaining = selectedLabels.length - maxDisplay;
                    this.selectedText.textContent = `${displayed} +${remaining}`;
                }
            }
        } else {
            // 单选显示
            if (!this.selectedValues) {
                this.selectedText.innerHTML = `<span class="placeholder">${this.config.placeholder}</span>`;
            } else {
                const opt = this.options.find(o => o.value == this.selectedValues);
                this.selectedText.textContent = opt ? opt.label : this.selectedValues;
            }
        }

        // 显示/隐藏清空按钮（多选模式下不显示清空按钮，因为至少要保留"全部"）
        if (this.clearBtn) {
            if (this.config.multiple) {
                this.clearBtn.style.display = 'none';
            } else {
                const hasValue = !!this.selectedValues;
                this.clearBtn.style.display = hasValue ? 'inline-block' : 'none';
            }
        }
    }

    refreshOptions() {
        this.optionsList.innerHTML = this.renderOptions();
    }

    toggle() {
        if (this.isOpen) {
            this.close();
        } else {
            this.open();
        }
    }

    open() {
        this.isOpen = true;
        this.container.classList.add('open');
        if (this.searchInput) {
            setTimeout(() => this.searchInput.focus(), 0);
        }
    }

    close() {
        this.isOpen = false;
        this.container.classList.remove('open');
        this.searchText = '';
        if (this.searchInput) {
            this.searchInput.value = '';
        }
        this.refreshOptions();
    }

    clear() {
        if (this.config.multiple) {
            this.selectedValues = [];
        } else {
            this.selectedValues = '';
        }
        this.updateDisplay();
        this.refreshOptions();
        if (this.onChange) {
            this.onChange(this.config.multiple ? [] : '');
        }
    }

    // 公共方法
    getValue() {
        return this.config.multiple ? [...this.selectedValues] : this.selectedValues;
    }

    setValue(value) {
        if (this.config.multiple) {
            this.selectedValues = Array.isArray(value) ? [...value] : (value ? [value] : []);
            // 确保多选模式下如果没有选中任何项，默认选中"全部"
            if (this.selectedValues.length === 0) {
                this.selectedValues = [''];
            }
            // 如果选中了"全部"和其他项，去掉"全部"
            if (this.selectedValues.length > 1 && this.selectedValues.includes('')) {
                this.selectedValues = this.selectedValues.filter(v => v !== '');
            }
        } else {
            this.selectedValues = value || '';
        }
        this.updateDisplay();
        this.refreshOptions();
    }

    setOptions(options) {
        this.options = options || [];
        this.refreshOptions();
    }

    destroy() {
        this.container.innerHTML = '';
        this.container.classList.remove('searchable-select', 'multiple', 'single', 'open');
    }
}

/**
 * 快速初始化页面上所有带有 searchable-select 类的元素
 */
function initAllSearchableSelects() {
    document.querySelectorAll('.searchable-select[data-auto-init]').forEach(el => {
        const options = el.dataset.options ? JSON.parse(el.dataset.options) : [];
        const multiple = el.dataset.multiple === 'true';
        const searchable = el.dataset.searchable !== 'false';
        
        new SearchableSelect(el, {
            options,
            multiple,
            searchable,
            placeholder: el.dataset.placeholder || '请选择...'
        });
    });
}

// DOM加载完成后自动初始化
document.addEventListener('DOMContentLoaded', initAllSearchableSelects);


/* ============================================
   静态工具方法
   ============================================ */

/**
 * 批量初始化所有带有 data-auto-init 属性的下拉框
 * 用法: <div class="searchable-select" data-auto-init data-options='[{"value":"1","label":"选项1"}]'></div>
 */
SearchableSelect.initAll = function() {
    document.querySelectorAll('.searchable-select[data-auto-init]').forEach(el => {
        try {
            const options = el.dataset.options ? JSON.parse(el.dataset.options) : [];
            const multiple = el.dataset.multiple === 'true';
            const searchable = el.dataset.searchable !== 'false';
            
            new SearchableSelect(el, {
                options,
                multiple,
                searchable,
                placeholder: el.dataset.placeholder || '请选择...'
            });
        } catch (e) {
            console.error('SearchableSelect auto-init failed:', el, e);
        }
    });
};

/**
 * 获取实例
 * @param {HTMLElement|string} element - 元素或选择器
 * @returns {SearchableSelect|null} 实例
 */
SearchableSelect.getInstance = function(element) {
    const el = typeof element === 'string' ? document.querySelector(element) : element;
    return el ? el._searchableSelect : null;
};

/**
 * 销毁所有实例
 */
SearchableSelect.destroyAll = function() {
    document.querySelectorAll('.searchable-select').forEach(el => {
        if (el._searchableSelect) {
            el._searchableSelect.destroy();
        }
    });
};

/**
 * 显示通知
 * @param {string} message - 消息内容
 * @param {string} type - 类型: success|error|warning|info
 * @param {number} duration - 显示时长(ms)
 */
SearchableSelect.notify = function(message, type = 'info', duration = 3000) {
    // 查找或创建通知容器
    let container = document.getElementById('notificationContainer');
    if (!container) {
        container = document.createElement('div');
        container.id = 'notificationContainer';
        document.body.appendChild(container);
    }
    
    // 避免重复通知
    const existing = Array.from(container.children).find(el => 
        el.textContent.includes(message.substring(0, 20))
    );
    if (existing) return;
    
    const icons = {
        success: 'fa-check-circle',
        error: 'fa-exclamation-circle',
        warning: 'fa-exclamation-triangle',
        info: 'fa-info-circle'
    };
    
    const colors = {
        success: '#48bb78',
        error: '#e53e3e',
        warning: '#dd6b20',
        info: '#3182ce'
    };
    
    const notification = document.createElement('div');
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: var(--bg-primary, #fff);
        color: var(--text-primary, #333);
        padding: 1rem 1.5rem;
        border-radius: 8px;
        box-shadow: 0 10px 25px rgba(0,0,0,0.15);
        border-left: 4px solid ${colors[type]};
        z-index: 10000;
        transform: translateX(100%);
        transition: transform 0.3s ease;
        max-width: 400px;
    `;
    
    notification.innerHTML = `
        <div style="display: flex; align-items: center; gap: 0.75rem;">
            <i class="fas ${icons[type]}" style="color: ${colors[type]};"></i>
            <span>${message}</span>
            <button onclick="this.parentElement.parentElement.remove()" style="
                background: none;
                border: none;
                color: var(--text-secondary, #666);
                cursor: pointer;
                margin-left: auto;
                padding: 0.25rem;
                border-radius: 4px;
            ">
                <i class="fas fa-times"></i>
            </button>
        </div>
    `;
    
    container.appendChild(notification);
    
    // 显示动画
    setTimeout(() => {
        notification.style.transform = 'translateX(0)';
    }, 10);
    
    // 自动关闭
    setTimeout(() => {
        notification.style.transform = 'translateX(100%)';
        setTimeout(() => {
            if (notification.parentElement) notification.remove();
        }, 300);
    }, duration);
};

// DOM加载完成后自动初始化
document.addEventListener('DOMContentLoaded', SearchableSelect.initAll);

/**
 * 通用分页工具函数
 * @param {Object} options - 配置选项
 * @param {number} options.page - 目标页码
 * @param {number} options.currentPage - 当前页码变量（会被修改）
 * @param {number} options.total - 总记录数
 * @param {number} options.pageSize - 每页条数
 * @param {Function} options.loadData - 加载数据的函数（应返回 Promise）
 * @param {string} [options.tableSelector='.table-container'] - 表格容器选择器
 * @param {number} [options.offset=100] - 滚动偏移量
 */
function changePageWithScroll(options) {
    const { page, currentPage, total, pageSize, loadData, tableSelector = '.table-container', offset = 100 } = options;
    
    const totalPages = Math.ceil(total / pageSize);
    if (page < 1 || page > totalPages) return Promise.resolve();
    
    // 记录当前表格位置
    const tableContainer = document.querySelector(tableSelector);
    const scrollOffset = tableContainer 
        ? tableContainer.getBoundingClientRect().top + window.pageYOffset - offset 
        : window.pageYOffset;
    
    // 更新当前页（修改传入的引用）
    options.currentPage.value = page;
    
    return loadData().then(() => {
        // 滚动回之前的位置
        window.scrollTo({
            top: scrollOffset,
            behavior: 'smooth'
        });
    });
}

/**
 * 简化的页码跳转处理
 * @param {number} page - 目标页码
 * @param {Function} callback - 切换页码后的回调函数
 * @param {string} [tableSelector='.table-container'] - 表格容器选择器
 */
function handlePageChange(page, callback, tableSelector = '.table-container') {
    const tableContainer = document.querySelector(tableSelector);
    const scrollOffset = tableContainer 
        ? tableContainer.getBoundingClientRect().top + window.pageYOffset - 100 
        : window.pageYOffset;
    
    Promise.resolve(callback(page)).then(() => {
        window.scrollTo({
            top: scrollOffset,
            behavior: 'smooth'
        });
    });
}
