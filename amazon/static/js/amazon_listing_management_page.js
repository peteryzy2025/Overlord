let shopNameSelect = null;
let groupSelect = null;
let operatorSelect = null;
let infringementSelect = null;
let activeStatusSelect = null;
let allOperators = [];

let currentFilters = {
    shop_names: [],
    ops_groups: [],
    operator_ids: [],
    asin: '',
    infringements: [],
    listing_date_range: 'all',
    active_statuses: []
};

let listPagination = {
    page: 1,
    page_size: 20,
    total: 0,
    total_pages: 0
};

let pageListingIds = new Set();
let selectedListingIds = new Set();
let latestRiskRenderVersion = 0;

const riskLabelMap = {
    high: '高风险',
    medium: '中风险',
    low: '低风险',
    unknown: '未知'
};

const activeStatusLabelMap = {
    active: '在售',
    inactive: '下架'
};

function getCookie(name) {
    const cookieValue = document.cookie
        .split('; ')
        .find(row => row.startsWith(name + '='));
    return cookieValue ? decodeURIComponent(cookieValue.split('=')[1]) : '';
}

async function safeParseJson(response) {
    const contentType = (response.headers.get('content-type') || '').toLowerCase();
    if (!contentType.includes('application/json')) {
        if (response.redirected && response.url && response.url.includes('/login')) {
            throw new Error('Session expired. Please refresh and login again.');
        }
        let snippet = '';
        try {
            snippet = (await response.text()).replace(/\s+/g, ' ').trim().slice(0, 120);
        } catch (e) {
            snippet = '';
        }
        throw new Error(`HTTP ${response.status} returned non-JSON response${snippet ? `: ${snippet}` : ''}`);
    }
    return await response.json();
}

function showLoading(show) {
    const overlay = document.getElementById('listingLoadingOverlay');
    if (!overlay) return;
    overlay.style.display = show ? 'flex' : 'none';
}

function showToast(message, type) {
    if (window.showNotification) {
        window.showNotification(message, type || 'info');
    } else {
        console.log(message);
    }
}

function normalizeMultiValues(values, toLower = false) {
    const source = Array.isArray(values) ? values : [];
    const normalized = [];
    const seen = new Set();

    for (const raw of source) {
        let text = String(raw || '').trim();
        if (!text) continue;
        if (toLower) text = text.toLowerCase();

        const token = text.toLowerCase();
        if (token === 'all' || token === '__all__' || token === '*') {
            return [];
        }

        if (!seen.has(token)) {
            seen.add(token);
            normalized.push(text);
        }
    }

    return normalized;
}

function buildMultiSelectOptions(items, allLabel) {
    const values = Array.isArray(items) ? items : [];
    const deduped = [];
    const seen = new Set();

    for (const value of values) {
        const text = String(value || '').trim();
        if (!text) continue;
        const key = text.toLowerCase();
        if (seen.has(key)) continue;
        seen.add(key);
        deduped.push({ value: text, label: text });
    }

    deduped.sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'));
    return [{ value: 'all', label: allLabel }, ...deduped];
}

function buildLabeledOptions(values, allLabel, labelMap) {
    const result = [{ value: 'all', label: allLabel }];
    for (const value of values || []) {
        if (!labelMap[value]) continue;
        result.push({ value, label: labelMap[value] });
    }
    return result;
}

function buildOperatorOptions(items, allLabel) {
    const values = Array.isArray(items) ? items : [];
    const deduped = [];
    const seen = new Set();

    for (const item of values) {
        const safeId = Number(item && item.value);
        if (!Number.isInteger(safeId) || safeId <= 0 || seen.has(safeId)) continue;
        seen.add(safeId);

        const group = String((item && item.group) || '').trim() || '未分组';
        const label = String((item && item.label) || '').trim()
            || `${safeId} (${group})`;

        deduped.push({
            value: String(safeId),
            label,
            group,
        });
    }

    deduped.sort((a, b) => {
        const byGroup = a.group.localeCompare(b.group, 'zh-CN');
        if (byGroup !== 0) return byGroup;
        return a.label.localeCompare(b.label, 'zh-CN');
    });

    return [{ value: 'all', label: allLabel }, ...deduped];
}

function normalizeMultiNumberValues(values) {
    const source = Array.isArray(values) ? values : [];
    const result = [];
    const seen = new Set();

    for (const raw of source) {
        const text = String(raw || '').trim().toLowerCase();
        if (!text) continue;
        if (text === 'all' || text === '__all__' || text === '*') return [];

        const parsed = Number(text);
        if (!Number.isInteger(parsed) || parsed <= 0 || seen.has(parsed)) continue;
        seen.add(parsed);
        result.push(parsed);
    }

    return result;
}

function updateOperatorSelectByGroups(selectedGroups, resetValue = true) {
    const normalizedGroups = normalizeMultiValues(selectedGroups || []);
    const source = normalizedGroups.length
        ? allOperators.filter(item => normalizedGroups.includes(String(item.group || '').trim()))
        : allOperators;
    const options = buildOperatorOptions(source, '全部人员');

    if (!operatorSelect) return;
    operatorSelect.setOptions(options);
    if (resetValue) {
        operatorSelect.setValue(['all']);
    } else {
        const selected = normalizeMultiNumberValues(operatorSelect.getValue()).map(String);
        const valid = selected.filter(value => options.some(opt => opt.value === value));
        operatorSelect.setValue(valid.length ? valid : ['all']);
    }
}

async function initSearchableSelects() {
    const defaultOptions = {
        shop_names: [],
        ops_groups: [],
        operators: [],
        infringements: ['high', 'medium', 'low', 'unknown'],
        active_statuses: ['active', 'inactive']
    };

    let optionData = { ...defaultOptions };
    try {
        const response = await fetch('/api/amazon-listing-management/filter-options/');
        const result = await safeParseJson(response);
        if (response.ok && result.success && result.data) {
            optionData = {
                shop_names: result.data.shop_names || [],
                ops_groups: result.data.ops_groups || [],
                operators: result.data.operators || [],
                infringements: result.data.infringements || defaultOptions.infringements,
                active_statuses: result.data.active_statuses || defaultOptions.active_statuses
            };
        } else {
            throw new Error(result.message || 'Failed to load filter options');
        }
    } catch (error) {
        showToast('筛选项加载失败，已使用默认选项。', 'warning');
        console.warn('Failed to load listing filter options:', error);
    }

    shopNameSelect = new SearchableSelect('#shopNameFilter', {
        options: buildMultiSelectOptions(optionData.shop_names, '全部店铺'),
        multiple: true,
        placeholder: '选择领星店铺'
    });
    shopNameSelect.setValue(['all']);

    groupSelect = new SearchableSelect('#groupFilter', {
        options: buildMultiSelectOptions(optionData.ops_groups, '全部分组'),
        multiple: true,
        placeholder: '选择运营分组'
    });
    groupSelect.setValue(['all']);

    allOperators = Array.isArray(optionData.operators) ? optionData.operators : [];
    operatorSelect = new SearchableSelect('#operatorFilter', {
        options: buildOperatorOptions(allOperators, '全部人员'),
        multiple: true,
        placeholder: '选择运营人员'
    });
    operatorSelect.setValue(['all']);

    groupSelect.onChange = () => {
        updateOperatorSelectByGroups(groupSelect.getValue(), true);
    };

    infringementSelect = new SearchableSelect('#infringementFilter', {
        options: buildLabeledOptions(optionData.infringements, '全部风险等级', riskLabelMap),
        multiple: true,
        placeholder: '选择风险等级'
    });
    infringementSelect.setValue(['all']);

    activeStatusSelect = new SearchableSelect('#activeStatusFilter', {
        options: buildLabeledOptions(optionData.active_statuses, '全部状态', activeStatusLabelMap),
        multiple: true,
        placeholder: '选择在售状态'
    });
    activeStatusSelect.setValue(['all']);
}

function getFiltersFromUI() {
    return {
        shop_names: normalizeMultiValues(shopNameSelect ? shopNameSelect.getValue() : []),
        ops_groups: normalizeMultiValues(groupSelect ? groupSelect.getValue() : []),
        operator_ids: normalizeMultiNumberValues(operatorSelect ? operatorSelect.getValue() : []),
        asin: document.getElementById('asinFilter').value.trim(),
        infringements: normalizeMultiValues(infringementSelect ? infringementSelect.getValue() : [], true),
        listing_date_range: 'all',
        active_statuses: normalizeMultiValues(activeStatusSelect ? activeStatusSelect.getValue() : [], true)
    };
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}

function renderRiskBadge(level) {
    if (level === 'high') return `<span class="risk-badge risk-high">${riskLabelMap.high}</span>`;
    if (level === 'medium') return `<span class="risk-badge risk-medium">${riskLabelMap.medium}</span>`;
    if (level === 'unknown') return `<span class="risk-badge">${riskLabelMap.unknown}</span>`;
    if (level === 'low') return `<span class="risk-badge risk-low">${riskLabelMap.low}</span>`;
    return '<span class="risk-badge">-</span>';
}

function renderWordTags(words, level) {
    if (!words || words.length === 0) {
        return '<span style="color: var(--text-secondary);">-</span>';
    }
    const css = level === 'high' ? 'high' : 'medium';
    return `<div class="word-tags">${words.map(word => `<span class="word-tag ${css}">${escapeHtml(word)}</span>`).join('')}</div>`;
}

function renderStats(stats) {
    const safeStats = stats || {};
    document.getElementById('totalCount').textContent = safeStats.total_count || 0;
    document.getElementById('highCount').textContent = safeStats.high_count == null ? '-' : safeStats.high_count;
    document.getElementById('mediumCount').textContent = safeStats.medium_count == null ? '-' : safeStats.medium_count;
}

function updateSelectAllCheckboxState() {
    const selectAll = document.getElementById('selectAll');
    if (!selectAll) return;

    const rowCheckboxes = Array.from(document.querySelectorAll('#listingTableBody .row-checkbox'));
    if (rowCheckboxes.length === 0) {
        selectAll.checked = false;
        selectAll.indeterminate = false;
        return;
    }

    const checkedCount = rowCheckboxes.filter(checkbox => checkbox.checked).length;
    selectAll.checked = checkedCount === rowCheckboxes.length;
    selectAll.indeterminate = checkedCount > 0 && checkedCount < rowCheckboxes.length;
}

function toggleSelectAll() {
    const selectAll = document.getElementById('selectAll');
    if (!selectAll) return;

    document.querySelectorAll('#listingTableBody .row-checkbox').forEach((checkbox) => {
        checkbox.checked = selectAll.checked;
        const listingId = Number(checkbox.dataset.listingId || 0);
        if (listingId <= 0) return;
        if (checkbox.checked) {
            selectedListingIds.add(listingId);
        } else {
            selectedListingIds.delete(listingId);
        }
    });

    updateSelectAllCheckboxState();
}

function toggleSelectRow(listingId, checked) {
    const safeId = Number(listingId) || 0;
    if (safeId <= 0) return;

    if (checked) {
        selectedListingIds.add(safeId);
    } else {
        selectedListingIds.delete(safeId);
    }

    updateSelectAllCheckboxState();
}

function renderListingTable(rows) {
    const tbody = document.getElementById('listingTableBody');
    const renderVersion = ++latestRiskRenderVersion;
    tbody.dataset.renderVersion = String(renderVersion);
    pageListingIds = new Set();

    if (!rows || rows.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="10" class="empty-state">
                    <i class="fas fa-inbox"></i>
                    <p>暂无匹配的 Listing</p>
                </td>
            </tr>
        `;
        updateSelectAllCheckboxState();
        return;
    }

    tbody.innerHTML = rows.map(row => {
        const title = row.title || '';
        const listingId = Number(row.id) || 0;
        if (listingId > 0) pageListingIds.add(listingId);

        const rawRiskLevel = String(row.risk_level || '').trim().toLowerCase();
        const displayRiskLevel = ['high', 'medium', 'low', 'unknown'].includes(rawRiskLevel) ? rawRiskLevel : '';
        const checkedAttr = selectedListingIds.has(listingId) ? 'checked' : '';

        return `
        <tr data-listing-id="${listingId}">
            <td class="w-checkbox">
                <input type="checkbox" class="row-checkbox" data-listing-id="${listingId}" ${checkedAttr}
                       onclick="toggleSelectRow(${listingId}, this.checked)">
            </td>
            <td>${escapeHtml(row.amazon_shop_name || '-')}</td>
            <td>${escapeHtml(row.shop_name || '-')}</td>
            <td>
                <div class="ops-info-cell">
                    <span class="ops-group-text">${escapeHtml(row.ops_group || '-')}</span>
                    <span class="ops-operator-text">${escapeHtml(row.operator_name || '-')}</span>
                </div>
            </td>
            <td>${escapeHtml(row.asin || '-')}</td>
            <td class="cell-truncate" title="${escapeHtml(title)}">${escapeHtml(title || '-')}</td>
            <td>${renderRiskBadge(displayRiskLevel)}</td>
            <td><span class="loading-risk-high" data-listing-id="${listingId}" data-render-version="${renderVersion}"><i class="fas fa-spinner fa-spin text-muted"></i></span></td>
            <td><span class="loading-risk-medium" data-listing-id="${listingId}" data-render-version="${renderVersion}"><i class="fas fa-spinner fa-spin text-muted"></i></span></td>
            <td>
                <button class="btn-view" onclick="viewWordSources(${row.id}, event)">
                    <i class="fas fa-eye"></i> 详情
                </button>
            </td>
        </tr>
    `;
    }).join('');

    updateSelectAllCheckboxState();
    if (pageListingIds.size > 0) {
        fetchRiskData(Array.from(pageListingIds), renderVersion);
    }
}

async function fetchRiskData(listingIds, renderVersion) {
    try {
        const csrfToken = getCookie('csrftoken');
        const response = await fetch('/api/amazon-listing-management/batch-risk-check/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({ listing_ids: listingIds })
        });

        const result = await safeParseJson(response);
        if (response.ok && result.success && result.data) {
            const tbody = document.getElementById('listingTableBody');
            if (!tbody || String(renderVersion) !== tbody.dataset.renderVersion) return;
            updateRiskCells(result.data, renderVersion);
        }
    } catch (error) {
        console.error('Batch risk check failed:', error);
    }
}

function updateRiskCells(riskData, renderVersion = null) {
    const renderSelector = renderVersion !== null ? `[data-render-version="${renderVersion}"]` : '';

    document.querySelectorAll(`.loading-risk-high${renderSelector}`).forEach(el => {
        const listingId = String(el.getAttribute('data-listing-id') || '');
        const data = riskData[listingId];
        const words = (data && data.high_risk_words) ? data.high_risk_words : [];
        el.outerHTML = renderWordTags(words, 'high');
    });

    document.querySelectorAll(`.loading-risk-medium${renderSelector}`).forEach(el => {
        const listingId = String(el.getAttribute('data-listing-id') || '');
        const data = riskData[listingId];
        const words = (data && data.medium_risk_words) ? data.medium_risk_words : [];
        el.outerHTML = renderWordTags(words, 'medium');
    });
}

async function loadListings() {
    showLoading(true);
    try {
        const csrfToken = getCookie('csrftoken');
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 20000);

        let response;
        try {
            response = await fetch('/api/amazon-listing-management/list/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                signal: controller.signal,
                body: JSON.stringify({
                    ...currentFilters,
                    page: listPagination.page,
                    page_size: listPagination.page_size
                })
            });
        } finally {
            clearTimeout(timeoutId);
        }

        const result = await safeParseJson(response);
        if (!response.ok || !result.success) {
            throw new Error(result.message || 'Request failed');
        }

        const data = result.data || {};
        listPagination.total = data.total || 0;
        listPagination.total_pages = data.total_pages || 0;
        listPagination.page = data.page || 1;

        const stats = data.stats || {};
        renderStats({
            total_count: stats.total_count == null ? listPagination.total : stats.total_count,
            high_count: stats.high_count == null ? 0 : stats.high_count,
            medium_count: stats.medium_count == null ? 0 : stats.medium_count
        });
        renderListingTable(data.listings || []);
        renderPagination();
    } catch (error) {
        renderListingTable([]);
        renderPagination();
        renderStats({
            total_count: 0,
            high_count: null,
            medium_count: null
        });
        if (error.name === 'AbortError') {
            showToast('Request timeout while loading listings.', 'error');
        } else {
            showToast('Failed to load listings: ' + error.message, 'error');
        }
    } finally {
        showLoading(false);
    }
}

async function applyFilters() {
    currentFilters = getFiltersFromUI();
    listPagination.page = 1;
    selectedListingIds.clear();
    await loadListings();
}

async function refreshData(event) {
    const btn = event.currentTarget;
    const icon = btn.querySelector('i');
    icon.className = 'fas fa-spinner fa-spin';
    await loadListings();
    icon.className = 'fas fa-sync-alt';
}

async function resetFilters(event) {
    event.preventDefault();
    document.getElementById('asinFilter').value = '';
    if (shopNameSelect) shopNameSelect.setValue(['all']);
    if (groupSelect) groupSelect.setValue(['all']);
    if (operatorSelect) {
        updateOperatorSelectByGroups([], false);
        operatorSelect.setValue(['all']);
    }
    if (infringementSelect) infringementSelect.setValue(['all']);
    if (activeStatusSelect) activeStatusSelect.setValue(['all']);

    selectedListingIds.clear();
    currentFilters = {
        shop_names: [],
        ops_groups: [],
        operator_ids: [],
        asin: '',
        infringements: [],
        listing_date_range: 'all',
        active_statuses: []
    };
    listPagination.page = 1;
    await loadListings();
}

async function viewWordSources(listingId, event) {
    const btn = event.currentTarget;
    const icon = btn.querySelector('i');
    icon.className = 'fas fa-spinner fa-spin';
    btn.disabled = true;

    try {
        const response = await fetch(`/api/amazon-listing-management/${listingId}/word-sources/`);
        const result = await safeParseJson(response);
        if (!response.ok || !result.success) {
            throw new Error(result.message || 'Failed to load word sources');
        }
        renderSourceModal(result.data || {});
        document.getElementById('wordSourceModal').style.display = 'flex';
    } catch (error) {
        showToast('Failed to load word sources: ' + error.message, 'error');
    } finally {
        btn.disabled = false;
        icon.className = 'fas fa-eye';
    }
}

function renderSourceBadge(sourceName) {
    if (sourceName === 'tro_words') {
        return '<span class="source-badge tro">来源：侵权词库</span>';
    }
    if (sourceName === 'trademarks') {
        return '<span class="source-badge tm">来源：USPTO</span>';
    }
    return '<span class="source-badge none">来源：未匹配</span>';
}

function renderSourceModal(data) {
    document.getElementById('sourceModalAsin').textContent = data.asin || '-';
    document.getElementById('sourceModalTitle').textContent = data.title || '-';

    const rows = data.word_sources || [];
    const tbody = document.getElementById('sourceTableBody');
    if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="empty-state">该 Listing 暂无风险词。</td></tr>';
        return;
    }

    tbody.innerHTML = rows.map(row => {
        const sources = row.sources && row.sources.length ? row.sources.map(renderSourceBadge).join('') : renderSourceBadge('');
        const level = row.risk_level === 'high'
            ? `<span class="risk-badge risk-high">${riskLabelMap.high}</span>`
            : (row.risk_level === 'medium'
                ? `<span class="risk-badge risk-medium">${riskLabelMap.medium}</span>`
                : `<span class="risk-badge risk-low">${riskLabelMap.low}</span>`);
        return `
            <tr>
                <td>${escapeHtml(row.word || '-')}</td>
                <td>${level}</td>
                <td>${sources}</td>
                <td>${escapeHtml(row.infringement_type || '-')}</td>
            </tr>
        `;
    }).join('');
}

function closeWordSourceModal() {
    document.getElementById('wordSourceModal').style.display = 'none';
    document.getElementById('sourceModalAsin').textContent = '';
    document.getElementById('sourceModalTitle').textContent = '';
    document.getElementById('sourceTableBody').innerHTML = '<tr><td colspan="4" class="empty-state">暂无来源数据</td></tr>';
}

function goToPage(targetPage) {
    if (targetPage < 1 || targetPage > listPagination.total_pages || targetPage === listPagination.page) {
        return;
    }
    listPagination.page = targetPage;
    loadListings();
}

function renderPagination() {
    const container = document.getElementById('paginationContainer');
    const buttonsContainer = document.getElementById('paginationButtons');
    const statsContainer = document.getElementById('paginationStats');
    const jumpContainer = document.getElementById('paginationJump');
    const pageSizeText = document.getElementById('pageSizeText');
    const { page, page_size, total, total_pages } = listPagination;

    if (!total || !total_pages) {
        container.style.display = 'none';
        buttonsContainer.innerHTML = '';
        statsContainer.textContent = '0-0 / 共 0 条';
        if (jumpContainer) jumpContainer.style.display = 'none';
        if (pageSizeText) pageSizeText.textContent = `${page_size}条`;
        return;
    }

    container.style.display = 'flex';
    if (pageSizeText) pageSizeText.textContent = `${page_size}条`;

    document.querySelectorAll('#pageSizeDropdown .page-size-option').forEach(opt => {
        opt.classList.toggle('selected', parseInt(opt.dataset.value, 10) === page_size);
    });

    const start = (page - 1) * page_size + 1;
    const end = Math.min(page * page_size, total);
    statsContainer.textContent = `${start}-${end} / 共 ${total} 条`;

    let html = '';
    html += `<button class="pagination-btn-new" onclick="goToPage(1)" ${page === 1 ? 'disabled' : ''} title="首页">首页</button>`;
    html += `<button class="pagination-btn-new" onclick="goToPage(${page - 1})" ${page === 1 ? 'disabled' : ''}>上一页</button>`;

    const maxButtons = 7;
    let startPage = Math.max(1, page - Math.floor(maxButtons / 2));
    let endPage = Math.min(total_pages, startPage + maxButtons - 1);
    if (endPage - startPage < maxButtons - 1) startPage = Math.max(1, endPage - maxButtons + 1);

    if (startPage > 1) {
        html += `<button class="pagination-btn-new" onclick="goToPage(1)">1</button>`;
        if (startPage > 2) html += '<span class="pagination-ellipsis">...</span>';
    }

    for (let i = startPage; i <= endPage; i++) {
        html += `<button class="pagination-btn-new ${i === page ? 'active' : ''}" onclick="goToPage(${i})">${i}</button>`;
    }

    if (endPage < total_pages) {
        if (endPage < total_pages - 1) html += '<span class="pagination-ellipsis">...</span>';
        html += `<button class="pagination-btn-new" onclick="goToPage(${total_pages})">${total_pages}</button>`;
    }

    html += `<button class="pagination-btn-new" onclick="goToPage(${page + 1})" ${page === total_pages ? 'disabled' : ''}>下一页</button>`;
    html += `<button class="pagination-btn-new" onclick="goToPage(${total_pages})" ${page === total_pages ? 'disabled' : ''} title="尾页">尾页</button>`;
    buttonsContainer.innerHTML = html;

    if (jumpContainer) {
        if (total_pages > 7) {
            jumpContainer.style.display = 'flex';
            const jumpInput = document.getElementById('pageJumpInput');
            jumpInput.max = total_pages;
            jumpInput.value = '';
        } else {
            jumpContainer.style.display = 'none';
        }
    }
}

function togglePageSizeDropdown() {
    const dropdown = document.getElementById('pageSizeDropdown');
    if (!dropdown) return;
    const isOpen = dropdown.style.display === 'block';
    dropdown.style.display = isOpen ? 'none' : 'block';
}

function changePageSize(newSize) {
    const safeSize = Number(newSize) || 20;
    listPagination.page_size = safeSize;
    listPagination.page = 1;

    const pageSizeText = document.getElementById('pageSizeText');
    if (pageSizeText) pageSizeText.textContent = `${safeSize}条`;

    document.querySelectorAll('#pageSizeDropdown .page-size-option').forEach(opt => {
        opt.classList.remove('selected');
        if (parseInt(opt.dataset.value, 10) === safeSize) opt.classList.add('selected');
    });

    const dropdown = document.getElementById('pageSizeDropdown');
    if (dropdown) dropdown.style.display = 'none';

    loadListings();
}

function handlePageJump(event) {
    if (event.key !== 'Enter') return;
    const input = document.getElementById('pageJumpInput');
    const page = parseInt(input.value, 10);
    const maxPage = listPagination.total_pages;

    if (Number.isNaN(page) || page < 1) {
        showToast('请输入有效页码', 'warning');
        return;
    }
    if (page > maxPage) {
        showToast(`最大页码为 ${maxPage}`, 'warning');
        return;
    }
    goToPage(page);
}

document.addEventListener('click', function (event) {
    const wrapper = document.getElementById('pageSizeWrapper');
    const dropdown = document.getElementById('pageSizeDropdown');
    if (wrapper && dropdown && !wrapper.contains(event.target)) {
        dropdown.style.display = 'none';
    }
});

document.addEventListener('DOMContentLoaded', async function () {
    try {
        await initSearchableSelects();
    } catch (error) {
        console.error('initSearchableSelects failed', error);
    }

    document.getElementById('asinFilter').addEventListener('keyup', function (event) {
        if (event.key === 'Enter') applyFilters();
    });

    const modal = document.getElementById('wordSourceModal');
    if (modal) {
        modal.addEventListener('click', function (event) {
            if (event.target === modal) closeWordSourceModal();
        });
    }

    window.toggleSelectAll = toggleSelectAll;
    window.toggleSelectRow = toggleSelectRow;
    loadListings();
});
