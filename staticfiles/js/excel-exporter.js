/**
 * Excel导出工具模块
 * 支持列选择、分组、本地存储等功能
 * 
 * 依赖: SheetJS (XLSX)
 */
class ExcelExporter {
    /**
     * 创建导出器实例
     * @param {Object} config 配置对象
     * @param {string} config.storageKey - localStorage存储键名
     * @param {Array} config.columns - 列定义数组 [{key, label, group, tableVisible, formatter}]
     * @param {string} config.sheetName - Excel工作表名称
     * @param {string} config.fileNamePrefix - 文件名前缀
     * @param {Function} config.fetchData - 获取数据的异步函数，返回Promise<{data: Array}>
     * @param {Function} config.onError - 错误处理回调
     * @param {Function} config.onSuccess - 成功回调
     * @param {Function} config.notify - 通知函数 (message, type, duration)
     */
    constructor(config) {
        this.storageKey = config.storageKey;
        this.columns = config.columns;
        this.sheetName = config.sheetName || '导出数据';
        this.fileNamePrefix = config.fileNamePrefix || '导出';
        this.fetchData = config.fetchData;
        this.onError = config.onError || console.error;
        this.onSuccess = config.onSuccess || (() => {});
        this.notify = config.notify || ((msg) => alert(msg));
    }

    /**
     * 获取保存的选中列
     * @returns {Array} 选中的列key数组
     */
    getSavedSelectedColumns() {
        const saved = localStorage.getItem(this.storageKey);
        if (saved) {
            try {
                return JSON.parse(saved);
            } catch (e) {
                console.warn('解析保存的导出列失败:', e);
            }
        }
        // 默认选中所有tableVisible为true的列
        return this.columns
            .filter(col => col.tableVisible !== false)
            .map(col => col.key);
    }

    /**
     * 保存选中的列
     * @param {Array} selectedKeys 选中的列key数组
     */
    saveSelectedColumns(selectedKeys) {
        localStorage.setItem(this.storageKey, JSON.stringify(selectedKeys));
    }

    /**
     * 执行导出
     * @param {Array} selectedColumnKeys 要导出的列key数组，不传则使用保存的列
     */
    async export(selectedColumnKeys = null) {
        const keys = selectedColumnKeys || this.getSavedSelectedColumns();
        
        try {
            const result = await this.fetchData();
            
            if (!result || !result.data) {
                this.notify('获取数据失败', 'error');
                return;
            }

            const data = result.data;
            if (data.length === 0) {
                this.notify('当前没有可导出的数据', 'warning');
                return;
            }

            await this.generateExcel(data, keys);
            
            this.notify(`导出成功！共 ${data.length} 条记录`, 'success');
            this.onSuccess(data, keys);
            
        } catch (error) {
            console.error('导出失败:', error);
            this.notify('导出失败：' + error.message, 'error');
            this.onError(error);
        }
    }

    /**
     * 生成Excel文件
     * @param {Array} data 数据数组
     * @param {Array} selectedKeys 选中的列key数组
     */
    async generateExcel(data, selectedKeys) {
        const columns = this.columns.filter(col => selectedKeys.includes(col.key));
        
        // 表头
        const headers = columns.map(col => col.label);
        const rows = [headers];

        // 数据行
        data.forEach(item => {
            const row = columns.map(col => {
                let value = item[col.key];
                
                // 使用自定义格式化函数
                if (col.formatter && typeof col.formatter === 'function') {
                    return col.formatter(value, item);
                }
                
                // 处理特殊值
                if (value === null || value === undefined || value === '') {
                    return '-';
                }
                
                return value;
            });
            rows.push(row);
        });

        // 创建工作簿
        const ws = XLSX.utils.aoa_to_sheet(rows);
        const wb = XLSX.utils.book_new();
        XLSX.utils.book_append_sheet(wb, ws, this.sheetName);

        // 设置列宽
        ws['!cols'] = columns.map(col => ({
            wch: Math.max(col.label.length, 10) * 1.5
        }));

        // 生成文件名
        const dateStr = new Date().toLocaleDateString('zh-CN').replace(/\//g, '-');
        const fileName = `${this.fileNamePrefix}_${dateStr}.xlsx`;

        XLSX.writeFile(wb, fileName);
    }

    /**
     * 创建导出模态框的HTML
     * @param {Object} options 选项
     * @param {string} options.modalId - 模态框ID
     * @param {string} options.title - 模态框标题
     * @returns {string} HTML字符串
     */
    static createModalHTML(options = {}) {
        const modalId = options.modalId || 'exportModalOverlay';
        const title = options.title || '选择要导出的列';
        
        return `
        <div class="modal-overlay" id="${modalId}" style="display: none;">
            <div class="modal" style="max-width: 800px; max-height: 80vh;">
                <div class="modal-header">
                    <h2 class="modal-title">${title}</h2>
                    <button class="modal-close" onclick="ExcelExporter.closeModal('${modalId}')">&times;</button>
                </div>
                <div class="modal-body" style="overflow-y: auto; max-height: 60vh;">
                    <div id="${modalId}_columns" class="export-columns-container">
                        <!-- 动态生成列选择 -->
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary" onclick="ExcelExporter.selectAllColumns('${modalId}', false)">全不选</button>
                    <button class="btn btn-secondary" onclick="ExcelExporter.selectAllColumns('${modalId}', true)">全选</button>
                    <button class="btn btn-cancel-modal" onclick="ExcelExporter.closeModal('${modalId}')">取消</button>
                    <button class="btn btn-save-modal" id="${modalId}_confirm">确认导出</button>
                </div>
            </div>
        </div>`;
    }

    /**
     * 渲染列选择列表
     * @param {string} modalId 模态框ID
     * @param {Array} columns 列定义数组
     * @param {Array} selectedKeys 已选中的列key数组
     */
    static renderColumnSelectors(modalId, columns, selectedKeys) {
        const container = document.getElementById(`${modalId}_columns`);
        if (!container) return;

        // 按分组组织列
        const groups = {};
        columns.forEach(col => {
            const group = col.group || '其他';
            if (!groups[group]) groups[group] = [];
            groups[group].push(col);
        });

        let html = '';
        Object.entries(groups).forEach(([groupName, groupColumns]) => {
            html += `
            <div class="export-group" style="margin-bottom: 1.5rem;">
                <h4 style="margin-bottom: 0.75rem; color: var(--text-primary); font-size: 0.95rem; border-bottom: 1px solid var(--border-color); padding-bottom: 0.5rem;">
                    ${groupName}
                </h4>
                <div class="export-columns" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 0.75rem;">
                    ${groupColumns.map(col => `
                        <label class="export-column-item" style="display: flex; align-items: center; gap: 0.5rem; cursor: pointer; padding: 0.25rem;">
                            <input type="checkbox" value="${col.key}" ${selectedKeys.includes(col.key) ? 'checked' : ''} 
                                   style="width: 16px; height: 16px; cursor: pointer;">
                            <span style="font-size: 0.9rem; color: var(--text-primary);">${col.label}</span>
                        </label>
                    `).join('')}
                </div>
            </div>`;
        });

        container.innerHTML = html;
    }

    /**
     * 获取选中的列
     * @param {string} modalId 模态框ID
     * @returns {Array} 选中的列key数组
     */
    static getSelectedColumns(modalId) {
        const container = document.getElementById(`${modalId}_columns`);
        if (!container) return [];
        
        const checkboxes = container.querySelectorAll('input[type="checkbox"]:checked');
        return Array.from(checkboxes).map(cb => cb.value);
    }

    /**
     * 全选/全不选
     * @param {string} modalId 模态框ID
     * @param {boolean} select 是否选中
     */
    static selectAllColumns(modalId, select) {
        const container = document.getElementById(`${modalId}_columns`);
        if (!container) return;
        
        const checkboxes = container.querySelectorAll('input[type="checkbox"]');
        checkboxes.forEach(cb => cb.checked = select);
    }

    /**
     * 关闭模态框
     * @param {string} modalId 模态框ID
     */
    static closeModal(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) modal.style.display = 'none';
    }

    /**
     * 打开模态框
     * @param {string} modalId 模态框ID
     */
    static openModal(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) modal.style.display = 'block';
    }
}

// 兼容旧版浏览器的工具函数
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ExcelExporter;
}
