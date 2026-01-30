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
