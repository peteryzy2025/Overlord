const MAX_PATHS = 50;
const NAS_PATH_REGEX = /^\\\\ZT-NAS/i;

function getSettings() {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return { paths: [] };
    try {
        const parsed = JSON.parse(raw);
        if (parsed.savePath && !parsed.paths) {
            return { paths: [parsed.savePath] };
        }
        return { paths: parsed.paths || [] };
    } catch {
        return { paths: [] };
    }
}

function saveSettingsToStorage(settings) {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

function renderPathInputs() {
    const container = document.getElementById('pathInputsContainer');
    const settings = getSettings();
    const paths = settings.paths || [];
    container.innerHTML = '';
    paths.forEach((path, index) => {
        const row = document.createElement('div');
        row.className = 'path-input-row';
        row.innerHTML = `
            <input type="text" class="path-input" data-index="${index}" value="${escapeHtml(path)}" placeholder="例如：\\\\ZT-NAS\\公共区-不可编辑\\靓仔测试">
            <button class="remove-path-btn" onclick="removePathInput(${index})" title="删除">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <line x1="18" y1="6" x2="6" y2="18"></line>
                    <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
            </button>
        `;
        container.appendChild(row);
    });
    const addBtn = document.getElementById('addPathBtn');
    const hint = document.getElementById('pathCountHint');
    const count = paths.length;
    addBtn.disabled = count >= MAX_PATHS;
    hint.textContent = `已添加 ${count}/${MAX_PATHS} 个路径`;
    hint.style.color = count >= MAX_PATHS ? 'var(--danger-color, #ef4444)' : 'var(--text-tertiary)';
}

function addPathInput() {
    const settings = getSettings();
    if (settings.paths.length >= MAX_PATHS) {
        showNotification(`最多只能添加 ${MAX_PATHS} 个路径`, 'warning');
        return;
    }
    settings.paths.push('');
    saveSettingsToStorage(settings);
    renderPathInputs();
    const inputs = document.querySelectorAll('.path-input');
    if (inputs.length > 0) inputs[inputs.length - 1].focus();
}

function removePathInput(index) {
    const settings = getSettings();
    settings.paths.splice(index, 1);
    saveSettingsToStorage(settings);
    renderPathInputs();
}

function openSettingsModal() {
    renderPathInputs();
    document.getElementById('settingsModal').classList.add('visible');
    document.body.style.overflow = 'hidden';
}

function closeSettingsModal() {
    document.getElementById('settingsModal').classList.remove('visible');
    document.body.style.overflow = '';
}

function saveSettings() {
    const inputs = document.querySelectorAll('.path-input');
    const paths = [];
    let hasError = false;
    inputs.forEach(input => {
        const value = input.value.trim();
        if (!value || !NAS_PATH_REGEX.test(value)) {
            input.classList.add('invalid');
            hasError = true;
            return;
        }
        input.classList.remove('invalid');
        paths.push(value);
    });
    if (hasError) {
        showNotification('请检查路径格式，必须是 \\\\ZT-NAS 开头的 NAS 路径', 'warning');
        return;
    }
    if (paths.length === 0) {
        showNotification('请至少添加一个保存路径', 'warning');
        return;
    }
    saveSettingsToStorage({ paths });
    showNotification(`已保存 ${paths.length} 个路径`, 'success');
    closeSettingsModal();
}

function getSavePaths() {
    return getSettings().paths || [];
}

function updateDownloadButton() {
    const btn = document.getElementById('downloadBtn');
    if (selectedImages.size > 0) {
        btn.classList.add('visible');
    } else {
        btn.classList.remove('visible');
    }
}

let selectedDownloadPath = '';

function openDownloadModal() {
    const paths = getSavePaths();
    const list = document.getElementById('pathSelectList');
    selectedDownloadPath = '';
    if (paths.length === 0) {
        list.innerHTML = `
            <div class="path-select-empty">
                <i class="fas fa-folder-open" style="font-size: 2rem; margin-bottom: 0.5rem; display: block;"></i>
                暂无保存路径，请先前往设置添加
            </div>
        `;
    } else {
        list.innerHTML = paths.map((path, index) => `
            <div class="path-select-item" data-path="${escapeHtml(path)}" onclick="selectDownloadPath(this, '${escapeHtml(path)}')">
                <input type="radio" name="downloadPath" value="${escapeHtml(path)}" onchange="selectDownloadPath(this.parentElement, '${escapeHtml(path)}')">
                <span class="path-label">${escapeHtml(path)}</span>
            </div>
        `).join('');
    }
    document.getElementById('downloadModal').classList.add('visible');
    document.body.style.overflow = 'hidden';
}

function closeDownloadModal() {
    document.getElementById('downloadModal').classList.remove('visible');
    document.body.style.overflow = '';
    selectedDownloadPath = '';
}

function selectDownloadPath(element, path) {
    selectedDownloadPath = path;
    document.querySelectorAll('.path-select-item').forEach(item => item.classList.remove('selected'));
    element.classList.add('selected');
    element.querySelector('input[type="radio"]').checked = true;
}

function confirmDownload() {
    if (!selectedDownloadPath) {
        showNotification('请选择一个下载路径', 'warning');
        return;
    }
    closeDownloadModal();
    executeDownload(selectedDownloadPath);
}

async function executeDownload(savePath) {
    if (selectedImages.size === 0) {
        showNotification('请先勾选要下载的图片', 'warning');
        return;
    }
    const btn = document.getElementById('downloadBtn');
    const progressContainer = document.getElementById('downloadProgressContainer');
    const progressFill = document.getElementById('downloadProgressFill');
    const progressText = document.getElementById('downloadProgressText');
    btn.disabled = true;
    progressContainer.classList.add('visible');
    progressFill.style.width = '0%';
    progressText.textContent = '准备下载...';

    const selectedProducts = [];
    selectedImages.forEach(index => {
        if (allImages[index]) selectedProducts.push(allImages[index]);
    });

    try {
        const response = await fetch('/api/amazon-batch-download/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify({
                products: selectedProducts,
                save_path: savePath,
                keyword: currentKeyword
            })
        });
        const data = await response.json();
        if (data.success) {
            progressFill.style.width = '100%';
            progressText.textContent = `下载完成：成功 ${data.success_count} 张，失败 ${data.failed_count} 张`;
            showNotification(`下载完成：成功 ${data.success_count} 张，保存到 ${data.save_dir}`, 'success');
        } else {
            throw new Error(data.message || '下载失败');
        }
    } catch (error) {
        progressText.textContent = '下载失败: ' + error.message;
        progressText.style.color = 'var(--danger-color)';
        showNotification('下载失败：' + (error.message || '请检查网络连接'), 'error');
    } finally {
        btn.disabled = false;
        setTimeout(() => {
            progressContainer.classList.remove('visible');
            progressText.style.color = '';
            progressFill.style.width = '0%';
        }, 3000);
    }
}

async function downloadSelectedImages() {
    const paths = getSavePaths();
    if (paths.length === 0) {
        showNotification('请先设置保存文件路径', 'warning');
        openSettingsModal();
        return;
    }
    if (selectedImages.size === 0) {
        showNotification('请先勾选要下载的图片', 'warning');
        return;
    }
    openDownloadModal();
}
