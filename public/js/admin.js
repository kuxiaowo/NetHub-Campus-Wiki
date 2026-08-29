const adminState = {
  currentUser: null,
  view: 'users',
  filePath: '',
  fileItems: [],
  picker: null,
  users: [],
  messageReports: [],
  announcements: [],
  commentReports: [],
  projectMetaLoaded: false,
  projectCategory: '',
  projectYear: '',
  projectSort: 'latest',
  projectCategories: [],
  projectYears: [],
  projects: [],
  currentProject: null,
  resourceMetaLoaded: false,
  resourceCategory: '',
  resourceYear: '',
  resourceSort: 'hot',
  resourceSearchDebounce: null,
  resources: [],
  activities: [],
  activePhotoItems: [],
  selectedActivity: null,
  currentActivity: null,
  currentModalPhoto: null,
  currentModalIndex: -1,
  dragState: null,
  modalDragItem: null,
  dragJustEnded: false,
  importDocument: null,
  importPreview: null,
};

const adminEls = {};

function adminQuery(id) {
  return document.querySelector(id);
}

function adminMessage(message, isError = false) {
  adminEls.status.textContent = message;
  adminEls.status.classList.toggle('error-text', isError);
}

function adminText(value) {
  return escapeHtml(value ?? '');
}

function adminNumber(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function adminEndpoint(path, options = {}) {
  return request(path, options);
}

async function downloadAdminJson(path, filename) {
  const documentData = await adminEndpoint(path);
  const blob = new Blob([`${JSON.stringify(documentData, null, 2)}\n`], { type: 'application/json;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

const TRANSFER_SUMMARY_LABELS = {
  projects: 'CAS 项目',
  members: '项目成员',
  updates: '项目动态',
  resources: '普通资源',
  photoActivities: '照片活动',
  photos: '照片条目',
};

function transferSummaryMarkup(summary = {}) {
  return `
    <div class="admin-transfer-summary">
      ${Object.entries(TRANSFER_SUMMARY_LABELS).map(([key, label]) => `
        <span><strong>${adminText(summary[key] || 0)}</strong>${adminText(label)}</span>
      `).join('')}
    </div>
  `;
}

function renderImportPreview(preview) {
  const warnings = Array.isArray(preview.warnings) ? preview.warnings : [];
  adminEls.dataImportResult.innerHTML = `
    ${transferSummaryMarkup(preview.summary)}
    ${warnings.length ? `
      <ul class="admin-transfer-warning">
        ${warnings.map((item) => `<li><strong>${adminText(item.path)}</strong>：${adminText(item.message)}</li>`).join('')}
      </ul>
    ` : '<p class="admin-transfer-success">检查通过，没有发现缺失的站内路径。</p>'}
  `;
  adminEls.confirmDataImportButton.textContent = warnings.length ? '确认预警并导入' : '确认导入';
  adminEls.confirmDataImportButton.classList.remove('is-hidden');
  adminEls.confirmDataImportButton.disabled = false;
}

function resetImportPreview(message = '请选择由本站导出或按照模板编写的 JSON 文件。') {
  adminState.importDocument = null;
  adminState.importPreview = null;
  adminEls.confirmDataImportButton.classList.add('is-hidden');
  adminEls.confirmDataImportButton.disabled = true;
  adminEls.previewDataImportButton.disabled = !adminEls.dataImportInput.files?.length;
  adminEls.dataImportResult.innerHTML = `<p class="admin-muted">${adminText(message)}</p>`;
}

async function previewDataImport() {
  const file = adminEls.dataImportInput.files?.[0];
  if (!file) return;
  if (file.size > 5 * 1024 * 1024) {
    resetImportPreview('JSON 文件不能超过 5 MB。资源文件应通过路径引用，不要写成 Base64。');
    adminEls.previewDataImportButton.disabled = true;
    adminEls.dataImportResult.querySelector('p')?.classList.add('admin-transfer-error');
    return;
  }
  adminEls.previewDataImportButton.disabled = true;
  adminEls.confirmDataImportButton.classList.add('is-hidden');
  adminEls.dataImportResult.innerHTML = '<p class="admin-muted">正在解析并检查 JSON...</p>';
  try {
    const documentData = JSON.parse(await file.text());
    const preview = await adminEndpoint('/admin/data-import/preview', {
      method: 'POST',
      body: JSON.stringify(documentData),
    });
    adminState.importDocument = documentData;
    adminState.importPreview = preview;
    renderImportPreview(preview);
  } catch (error) {
    adminState.importDocument = null;
    adminState.importPreview = null;
    adminEls.dataImportResult.innerHTML = `<p class="admin-transfer-error">${adminText(error.message)}</p>`;
  } finally {
    adminEls.previewDataImportButton.disabled = false;
  }
}

async function confirmDataImport() {
  if (!adminState.importDocument || !adminState.importPreview) return;
  const summary = adminState.importPreview.summary || {};
  const total = Number(summary.projects || 0) + Number(summary.resources || 0) + Number(summary.photoActivities || 0);
  if (!window.confirm(`确认新增 ${total} 条项目/资源记录？再次导入同一文件仍会继续新增。`)) return;
  const hasWarnings = Boolean(adminState.importPreview.warnings?.length);
  adminEls.confirmDataImportButton.disabled = true;
  adminEls.previewDataImportButton.disabled = true;
  adminEls.dataImportResult.insertAdjacentHTML('beforeend', '<p class="admin-muted">正在整批导入...</p>');
  try {
    const result = await adminEndpoint(`/admin/data-import?confirmWarnings=${hasWarnings ? 'true' : 'false'}`, {
      method: 'POST',
      body: JSON.stringify(adminState.importDocument),
    });
    adminEls.dataImportResult.innerHTML = `
      <p class="admin-transfer-success">导入完成。所有记录已作为新数据写入。</p>
      ${transferSummaryMarkup(result.summary)}
      <p class="admin-muted">若需再次导入，请重新点击“检查并预览”。</p>
    `;
    adminState.importPreview = null;
    adminEls.confirmDataImportButton.classList.add('is-hidden');
    adminState.projectMetaLoaded = false;
    adminState.resourceMetaLoaded = false;
  } catch (error) {
    adminEls.dataImportResult.innerHTML = `<p class="admin-transfer-error">${adminText(error.message)}</p>`;
    adminEls.confirmDataImportButton.disabled = false;
  } finally {
    adminEls.previewDataImportButton.disabled = false;
  }
}

function buildQuery(params) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') query.set(key, value);
  });
  const text = query.toString();
  return text ? `?${text}` : '';
}

function sortableButtons(type) {
  return [...document.querySelectorAll(`[data-sortable="${type}"]`)];
}

function sortablePayload(type) {
  return {
    items: sortableButtons(type).map((button, index) => ({
      id: adminNumber(button.dataset.sortableId),
      sortOrder: (index + 1) * 10,
    })),
  };
}

async function persistSortableOrder(type) {
  if (type === 'project-category') {
    await adminEndpoint('/admin/project-categories/reorder', {
      method: 'PATCH',
      body: JSON.stringify(sortablePayload(type)),
    });
    adminState.projectMetaLoaded = false;
    await loadProjectAdminMeta();
    return;
  }
  if (type === 'activity') {
    await adminEndpoint('/admin/photo-activities/reorder', {
      method: 'PATCH',
      body: JSON.stringify(sortablePayload(type)),
    });
    await loadActivities();
  }
}

function moveSortableItem(target) {
  const source = adminState.dragState?.element;
  if (!source || !target || source === target || source.dataset.sortable !== target.dataset.sortable) return;
  const position = source.compareDocumentPosition(target);
  if (position & Node.DOCUMENT_POSITION_FOLLOWING) {
    target.after(source);
  } else {
    target.before(source);
  }
}

function moveModalSortableItem(target) {
  const source = adminState.modalDragItem;
  if (!source || !target || source === target) return;
  const position = source.compareDocumentPosition(target);
  if (position & Node.DOCUMENT_POSITION_FOLLOWING) {
    target.after(source);
  } else {
    target.before(source);
  }
}

function bindSortableLists() {
  document.addEventListener('dragstart', (event) => {
    const item = event.target.closest('[data-sortable-list-item]');
    if (!item) return;
    adminState.modalDragItem = item;
    item.classList.add('is-dragging');
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', 'sortable-item');
  });

  document.addEventListener('dragover', (event) => {
    const item = event.target.closest('[data-sortable-list-item]');
    if (!adminState.modalDragItem || !item) return;
    event.preventDefault();
    moveModalSortableItem(item);
  });

  document.addEventListener('drop', (event) => {
    const item = event.target.closest('[data-sortable-list-item]');
    if (!adminState.modalDragItem || !item) return;
    event.preventDefault();
  });

  document.addEventListener('dragend', () => {
    if (!adminState.modalDragItem) return;
    adminState.modalDragItem.classList.remove('is-dragging');
    adminState.modalDragItem = null;
  });

  document.addEventListener('dragstart', (event) => {
    const item = event.target.closest('[data-sortable]');
    if (!item) return;
    adminState.dragState = { element: item, type: item.dataset.sortable };
    item.classList.add('is-dragging');
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', item.dataset.sortableId || '');
  });

  document.addEventListener('dragover', (event) => {
    const item = event.target.closest('[data-sortable]');
    if (!adminState.dragState || !item || item.dataset.sortable !== adminState.dragState.type) return;
    event.preventDefault();
    moveSortableItem(item);
  });

  document.addEventListener('drop', async (event) => {
    const item = event.target.closest('[data-sortable]');
    if (!adminState.dragState || !item || item.dataset.sortable !== adminState.dragState.type) return;
    event.preventDefault();
    const { type } = adminState.dragState;
    adminState.dragState.dropped = true;
    adminState.dragJustEnded = true;
    try {
      await persistSortableOrder(type);
    } catch (error) {
      window.alert(error.message);
      if (type === 'project-category') {
        adminState.projectMetaLoaded = false;
        await loadProjectAdminMeta();
      }
      if (type === 'activity') await loadActivities();
    } finally {
      window.setTimeout(() => {
        adminState.dragJustEnded = false;
      }, 0);
    }
  });

  document.addEventListener('dragend', async () => {
    const state = adminState.dragState;
    document.querySelectorAll('.is-dragging').forEach((item) => item.classList.remove('is-dragging'));
    adminState.dragState = null;
    if (state && !state.dropped) {
      if (state.type === 'project-category') {
        adminState.projectMetaLoaded = false;
        await loadProjectAdminMeta();
      }
      if (state.type === 'activity') await loadActivities();
    }
  });
}

function renderAdminTable(columns, rows, actions) {
  if (!rows.length) return '<div class="empty">暂无数据</div>';
  return `
    <table class="admin-table">
      <thead>
        <tr>
          ${columns.map((column) => `<th>${adminText(column.label)}</th>`).join('')}
          ${actions ? '<th>操作</th>' : ''}
        </tr>
      </thead>
      <tbody>
        ${rows.map((row) => `
          <tr>
            ${columns.map((column) => `<td>${column.render ? column.render(row) : adminText(row[column.key])}</td>`).join('')}
            ${actions ? `<td>${actions(row)}</td>` : ''}
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

function sortableListItem(fieldName, value = '') {
  return `
    <div class="admin-sortable-list-item" draggable="true" data-sortable-list-item>
      <span class="admin-sortable-list-handle">拖动</span>
      <input class="input" type="text" value="${adminText(value)}" data-sortable-list-input>
      <button class="button secondary compact danger" type="button" data-sortable-list-remove>删除</button>
    </div>
  `;
}

function openAdminModal(title, fields, onSubmit) {
  adminEls.modalTitle.textContent = title;
  adminEls.modalForm.innerHTML = `
    ${fields.map((field) => {
      const value = field.value ?? '';
      if (field.type === 'hidden') {
        return `<input type="hidden" name="${adminText(field.name)}" value="${adminText(value)}">`;
      }
      if (field.type === 'select') {
        return `
          <label>
            <span>${adminText(field.label)}</span>
            <select class="input" name="${adminText(field.name)}" ${field.required ? 'required' : ''}>
              ${(field.options || []).map((option) => `
                <option value="${adminText(option.value)}" ${String(option.value) === String(value) ? 'selected' : ''}>
                  ${adminText(option.label)}
                </option>
              `).join('')}
            </select>
          </label>
        `;
      }
      if (field.type === 'checkbox') {
        return `
          <label class="admin-check">
            <input type="checkbox" name="${adminText(field.name)}" ${value ? 'checked' : ''}>
            <span>${adminText(field.label)}</span>
          </label>
        `;
      }
      if (field.type === 'textarea') {
        const browseButton = field.browse
          ? `<button class="button secondary compact" type="button" data-browse-target="${adminText(field.name)}" data-browse-mode="${adminText(field.browse)}" data-browse-root="${adminText(field.browseRoot || '')}" data-browse-relative-to="${adminText(field.browseRelativeTo || '')}">浏览</button>`
          : '';
        return `
          <label>
            <span>${adminText(field.label)}</span>
            <div class="${browseButton ? 'admin-input-row' : ''}">
              <textarea class="input" name="${adminText(field.name)}" rows="4" ${field.required ? 'required' : ''}>${adminText(value)}</textarea>
              ${browseButton}
            </div>
          </label>
        `;
      }
      if (field.type === 'sortableList') {
        const items = Array.isArray(value) ? value : linesToList(value);
        return `
          <label>
            <span>${adminText(field.label)}</span>
            <div class="admin-sortable-list" data-sortable-list-field="${adminText(field.name)}">
              <div class="admin-sortable-list-items">
                ${items.length ? items.map((item) => sortableListItem(field.name, item)).join('') : sortableListItem(field.name)}
              </div>
              <button class="button secondary compact" type="button" data-sortable-list-add="${adminText(field.name)}">新增</button>
            </div>
          </label>
        `;
      }
      const browseButton = field.browse
        ? `<button class="button secondary compact" type="button" data-browse-target="${adminText(field.name)}" data-browse-mode="${adminText(field.browse)}" data-browse-root="${adminText(field.browseRoot || '')}" data-browse-relative-to="${adminText(field.browseRelativeTo || '')}">浏览</button>`
        : '';
      return `
        <label>
          <span>${adminText(field.label)}</span>
          <div class="admin-input-row">
            <input class="input" name="${adminText(field.name)}" type="${adminText(field.type || 'text')}" value="${adminText(value)}" ${field.required ? 'required' : ''} ${field.minLength ? `minlength="${adminText(field.minLength)}"` : ''} ${field.maxLength ? `maxlength="${adminText(field.maxLength)}"` : ''}>
            ${browseButton}
          </div>
        </label>
      `;
    }).join('')}
    <div id="adminModalMessage" class="auth-message"></div>
    <div class="admin-modal-actions">
      <button class="button secondary" type="button" data-admin-modal-close>取消</button>
      <button class="button" type="submit">保存</button>
    </div>
  `;
  adminEls.modal.classList.add('is-open');
  adminEls.modal.setAttribute('aria-hidden', 'false');
  adminEls.modalForm.onsubmit = async (event) => {
    event.preventDefault();
    const message = adminQuery('#adminModalMessage');
    message.textContent = '正在保存...';
    message.classList.remove('error');
    try {
      const formData = new FormData(adminEls.modalForm);
      const payload = {};
      fields.forEach((field) => {
        if (field.type === 'checkbox') {
          payload[field.name] = formData.has(field.name);
          return;
        }
        if (field.type === 'number') {
          payload[field.name] = adminNumber(formData.get(field.name), 0);
          return;
        }
        if (field.type === 'sortableList') {
          payload[field.name] = [...adminEls.modalForm.querySelectorAll(`[data-sortable-list-field="${field.name}"] [data-sortable-list-input]`)]
            .map((input) => input.value.trim())
            .filter(Boolean);
          return;
        }
        if (field.type !== 'hidden' || field.includeHidden) {
          payload[field.name] = String(formData.get(field.name) ?? '').trim();
        }
      });
      await onSubmit(payload);
      closeAdminModal();
    } catch (error) {
      message.textContent = error.message;
      message.classList.add('error');
    }
  };
}

function closeAdminModal() {
  adminEls.modal.classList.remove('is-open');
  adminEls.modal.setAttribute('aria-hidden', 'true');
  adminEls.modalForm.innerHTML = '';
  adminEls.modalForm.onsubmit = null;
  adminEls.modalForm.onchange = null;
}

function moveSortableListItem(button, direction) {
  const item = button.closest('.admin-sortable-list-item');
  if (!item) return;
  if (direction < 0 && item.previousElementSibling) {
    item.previousElementSibling.before(item);
  }
  if (direction > 0 && item.nextElementSibling) {
    item.nextElementSibling.after(item);
  }
}

function parentPublicPath(path) {
  const parts = String(path || '').split('/').filter(Boolean);
  parts.pop();
  return parts.join('/');
}

function publicPathLabel(path) {
  return `/${String(path || '').replace(/^\/+|\/+$/g, '')}`;
}

function publicFolderUrl(path) {
  const label = publicPathLabel(path);
  return label === '/' ? '/' : `${label}/`;
}

function renderFileRows(items, { selectable = false, mode = 'fileOrFolder' } = {}) {
  const rows = items.map((item) => ({
    ...item,
    displaySize: item.type === 'folder' ? '-' : `${Math.ceil((item.size || 0) / 1024)} KB`,
    displayType: item.type === 'folder' ? '文件夹' : '文件',
  }));
  return renderAdminTable(
    [
      {
        key: 'name',
        label: '名称',
        render: (row) => row.type === 'folder'
          ? `<button class="admin-link-button" type="button" data-open-file-folder="${adminText(row.path)}">${adminText(row.name)}</button>`
          : adminText(row.name),
      },
      { key: 'displayType', label: '类型' },
      { key: 'displaySize', label: '大小' },
      { key: 'url', label: 'URL', render: (row) => `<span class="admin-url-cell">${adminText(row.url)}</span>` },
    ],
    rows,
    (row) => {
      const isSupportedImage = /\.(jpe?g|png|webp|gif|avif)$/i.test(row.name || '');
      const canChoose = selectable && (
        (row.type === 'file' && mode !== 'folder' && (mode !== 'image' || isSupportedImage))
        || (row.type === 'folder' && mode !== 'file' && mode !== 'image')
      );
      return canChoose
        ? `<button class="button secondary compact" type="button" data-pick-file-url="${adminText(row.url)}">选择</button>`
        : '';
    },
  );
}

async function loadFiles(path = adminState.filePath) {
  const query = buildQuery({ path });
  const result = await adminEndpoint(`/admin/files/tree${query}`);
  adminState.filePath = result.path || '';
  adminState.fileItems = result.data;
  adminEls.filePathLabel.textContent = result.url;
  adminEls.uploadTargetLabel.textContent = result.url;
  adminEls.fileTable.innerHTML = renderFileRows(result.data);
}

function setFileActionMessage(text, isError = false) {
  adminEls.uploadMessage.textContent = text;
  adminEls.uploadMessage.classList.toggle('error', isError);
}

async function createFolderInCurrentDirectory() {
  const name = adminEls.folderName.value.trim();
  if (!name) {
    setFileActionMessage('请输入文件夹名称', true);
    adminEls.folderName.focus();
    return;
  }
  adminEls.createFolderButton.disabled = true;
  setFileActionMessage('正在新建文件夹...');
  try {
    const result = await adminEndpoint('/admin/files/folders', {
      method: 'POST',
      body: JSON.stringify({ parentPath: adminState.filePath, name }),
    });
    adminEls.folderName.value = '';
    await loadFiles(adminState.filePath);
    setFileActionMessage(`已新建：${result.data.url}`);
  } catch (error) {
    setFileActionMessage(error.message, true);
  } finally {
    adminEls.createFolderButton.disabled = false;
  }
}

async function uploadToCurrentDirectory() {
  const file = adminEls.uploadInput.files?.[0];
  if (!file) {
    setFileActionMessage('请选择文件', true);
    return;
  }
  adminEls.uploadButton.disabled = true;
  setFileActionMessage('正在上传文件...');
  try {
    const body = new FormData();
    body.append('file', file);
    body.append('targetPath', adminState.filePath);
    const result = await adminEndpoint('/admin/uploads', { method: 'POST', body });
    adminEls.uploadInput.value = '';
    await loadFiles(adminState.filePath);
    setFileActionMessage(`上传完成：${result.url}`);
  } catch (error) {
    setFileActionMessage(error.message, true);
  } finally {
    adminEls.uploadButton.disabled = false;
  }
}

async function uploadFolderToCurrentDirectory() {
  const files = [...(adminEls.folderUploadInput.files || [])];
  if (!files.length) {
    setFileActionMessage('请选择包含文件的文件夹', true);
    return;
  }
  const relativePaths = files.map((file) => file.webkitRelativePath || file.name);
  if (relativePaths.some((path) => !path.includes('/'))) {
    setFileActionMessage('当前浏览器没有提供文件夹相对路径，请改用 Chrome 或 Edge', true);
    return;
  }

  adminEls.folderUploadButton.disabled = true;
  setFileActionMessage(`正在上传文件夹（${files.length} 个文件）...`);
  try {
    const body = new FormData();
    files.forEach((file, index) => {
      body.append('files', file, file.name);
      body.append('relativePaths', relativePaths[index]);
    });
    body.append('targetPath', adminState.filePath);
    const result = await adminEndpoint('/admin/files/folder-upload', { method: 'POST', body });
    adminEls.folderUploadInput.value = '';
    await loadFiles(adminState.filePath);
    setFileActionMessage(`文件夹上传完成：${result.folderUrl}（${result.fileCount} 个文件）`);
  } catch (error) {
    setFileActionMessage(error.message, true);
  } finally {
    adminEls.folderUploadButton.disabled = false;
  }
}

function normalizedPickerPath(path) {
  return String(path || '').replace(/^\/+|\/+$/g, '');
}

async function openFilePicker(inputName, mode, root = '', relativeTo = '') {
  const normalizedRoot = normalizedPickerPath(root);
  adminState.picker = {
    target: adminEls.modalForm.elements[inputName],
    mode,
    path: normalizedRoot,
    root: normalizedRoot,
    relativeTo: publicFolderUrl(normalizedPickerPath(relativeTo)),
    items: [],
  };
  adminEls.filePickerTitle.textContent = mode === 'file'
    ? '选择文件'
    : (mode === 'image' ? '选择项目图片' : (mode === 'folder' ? '选择文件夹' : '选择文件或文件夹'));
  adminEls.pickCurrentFolder.classList.toggle('is-hidden', mode === 'file' || mode === 'image');
  adminEls.filePickerModal.classList.add('is-open');
  adminEls.filePickerModal.setAttribute('aria-hidden', 'false');
  await loadPickerFiles(normalizedRoot);
}

async function loadPickerFiles(path = adminState.picker?.path || '') {
  const query = buildQuery({ path });
  const result = await adminEndpoint(`/admin/files/tree${query}`);
  adminState.picker.path = result.path || '';
  adminState.picker.items = result.data;
  adminQuery('#pickerPathLabel').textContent = result.url;
  adminQuery('#pickerFileTable').innerHTML = renderFileRows(result.data, {
    selectable: true,
    mode: adminState.picker.mode,
  });
}

function chooseFileUrl(url) {
  const target = adminState.picker?.target;
  const relativeTo = adminState.picker?.relativeTo;
  const selectedValue = relativeTo && relativeTo !== '/' && url.startsWith(relativeTo)
    ? url.slice(relativeTo.length)
    : url;
  if (target?.tagName === 'TEXTAREA') {
    const currentValue = target.value.trimEnd();
    target.value = currentValue ? `${currentValue}\n${selectedValue}` : selectedValue;
  } else if (target) {
    target.value = selectedValue;
  }
  adminState.picker = null;
  closeFilePicker();
}

function closeFilePicker() {
  adminEls.filePickerModal.classList.remove('is-open');
  adminEls.filePickerModal.setAttribute('aria-hidden', 'true');
  adminState.picker = null;
}

async function requireAdmin() {
  try {
    const user = await refreshCurrentUser();
    adminState.currentUser = user;
    if (!user || user.role !== 'admin') {
      adminEls.workspace.classList.add('is-hidden');
      adminEls.gate.classList.remove('is-hidden');
      adminMessage('当前账号没有管理员权限。', true);
      return false;
    }
    adminEls.gate.classList.add('is-hidden');
    adminEls.workspace.classList.remove('is-hidden');
    adminMessage(`已登录：${user.displayName || user.username} (${roleLabel(user.role)})`);
    return true;
  } catch (error) {
    adminMessage(error.message, true);
    return false;
  }
}

function switchAdminView(view) {
  adminState.view = view;
  document.querySelectorAll('[data-admin-view]').forEach((item) => {
    const isActive = item.dataset.adminView === view;
    item.classList.toggle('active', isActive);
    item.setAttribute('aria-pressed', String(isActive));
  });
  document.querySelectorAll('[data-admin-panel]').forEach((item) => {
    item.classList.toggle('active', item.dataset.adminPanel === view);
  });
  if (view === 'users') loadUsers();
  if (view === 'files') loadFiles();
  if (view === 'projects') loadProjectManagementView();
  if (view === 'resources') loadResourceManagementView();
  if (view === 'community') loadCommunityAdmin();
}

async function loadUsers() {
  const query = buildQuery({
    search: adminEls.userSearch.value.trim(),
    role: adminEls.userRoleFilter.value,
    isActive: adminEls.userActiveFilter.value,
  });
  const result = await adminEndpoint(`/admin/users${query}`);
  adminState.users = result.data;
  adminEls.usersTable.innerHTML = renderAdminTable(
    [
      { key: 'id', label: 'ID' },
      { key: 'username', label: '昵称' },
      { key: 'displayName', label: '姓名' },
      { key: 'role', label: '角色', render: (row) => adminText(roleLabel(row.role)) },
      { key: 'isActive', label: '状态', render: (row) => row.isActive ? '启用' : '禁用' },
      { key: 'createdAt', label: '创建时间' },
    ],
    adminState.users,
    (row) => `<button class="button secondary compact" type="button" data-edit-user="${adminText(row.id)}">编辑</button>`,
  );
}

function announcementStatusLabel(status) {
  return {
    draft: '草稿',
    published: '已发布',
    archived: '已归档',
  }[status] || status;
}

function commentTargetLink(report) {
  const routes = {
    announcement: '/announcement.html',
    project: '/detail.html',
    resource: '/resource.html',
  };
  const label = {
    announcement: '公告',
    project: '项目',
    resource: '资源',
  }[report.targetType] || report.targetType;
  const route = routes[report.targetType];
  return route
    ? `<a class="admin-table-link" href="${route}?id=${adminText(report.targetId)}" target="_blank" rel="noopener">${adminText(label)} #${adminText(report.targetId)}</a>`
    : `${adminText(label)} #${adminText(report.targetId)}`;
}

async function loadCommunityAdmin() {
  const [announcementResult, reportResult, messageReportResult] = await Promise.all([
    adminEndpoint('/admin/announcements'),
    adminEndpoint('/admin/comment-reports?status=pending'),
    adminEndpoint('/admin/message-reports?status=pending'),
  ]);
  adminState.announcements = announcementResult.data || [];
  adminState.commentReports = reportResult.data || [];
  adminState.messageReports = messageReportResult.data || [];
  adminEls.announcementsTable.innerHTML = renderAdminTable(
    [
      { key: 'title', label: '标题' },
      { key: 'status', label: '状态', render: (row) => `${row.isPinned ? '置顶 · ' : ''}${adminText(announcementStatusLabel(row.status))}` },
      { key: 'viewCount', label: '浏览' },
      { key: 'commentCount', label: '留言' },
      { key: 'publishedAt', label: '发布时间', render: (row) => adminText(row.publishedAt || '—') },
    ],
    adminState.announcements,
    (row) => `
      <div class="admin-inline-actions">
        <button class="button secondary compact" type="button" data-edit-announcement="${adminText(row.id)}">编辑</button>
        ${row.status !== 'archived' ? `<button class="button secondary compact danger" type="button" data-archive-announcement="${adminText(row.id)}">归档</button>` : ''}
      </div>
    `,
  );
  adminEls.commentReportsTable.innerHTML = renderAdminTable(
    [
      { key: 'content', label: '留言内容', render: (row) => adminText(row.content.length > 80 ? `${row.content.slice(0, 80)}…` : row.content) },
      { key: 'targetType', label: '位置', render: commentTargetLink },
      { key: 'authorUsername', label: '作者', render: (row) => `@${adminText(row.authorUsername)}` },
      { key: 'reporterUsername', label: '举报人', render: (row) => `@${adminText(row.reporterUsername)}` },
      { key: 'reason', label: '理由' },
      { key: 'createdAt', label: '时间' },
    ],
    adminState.commentReports,
    (row) => `
      <div class="admin-inline-actions">
        <button class="button compact" type="button" data-review-comment-report="${adminText(row.id)}" data-comment-report-decision="hide">隐藏并处理</button>
        <button class="button secondary compact" type="button" data-review-comment-report="${adminText(row.id)}" data-comment-report-decision="dismiss">忽略</button>
      </div>
    `,
  );
  adminEls.messageReportsTable.innerHTML = renderAdminTable(
    [
      { key: 'messageBody', label: '消息内容' },
      { key: 'senderUsername', label: '发送者', render: (row) => `@${adminText(row.senderUsername)}` },
      { key: 'reporterUsername', label: '举报人', render: (row) => `@${adminText(row.reporterUsername)}` },
      { key: 'reason', label: '举报理由' },
      { key: 'createdAt', label: '举报时间' },
    ],
    adminState.messageReports,
    (row) => `
      <div class="admin-inline-actions">
        <button class="button compact" type="button" data-review-report="${adminText(row.id)}" data-report-decision="resolved">已处理</button>
        <button class="button secondary compact" type="button" data-review-report="${adminText(row.id)}" data-report-decision="dismissed">忽略</button>
      </div>
    `,
  );
}

function announcementFields(announcement = {}) {
  return [
    { name: 'title', label: '标题', value: announcement.title || '', required: true },
    { name: 'summary', label: '摘要（用于首页与列表）', type: 'textarea', value: announcement.summary || '' },
    { name: 'content', label: '正文（空行会分段）', type: 'textarea', value: announcement.content || '', required: true },
    {
      name: 'status',
      label: '状态',
      type: 'select',
      value: announcement.status || 'published',
      options: [
        { value: 'draft', label: '草稿' },
        { value: 'published', label: '发布' },
        { value: 'archived', label: '归档' },
      ],
    },
    { name: 'isPinned', label: '置顶显示', type: 'checkbox', value: Boolean(announcement.isPinned) },
  ];
}

function openAnnouncementModal(announcement = {}) {
  const isEdit = Boolean(announcement.id);
  openAdminModal(isEdit ? '编辑公告' : '新建公告', announcementFields(announcement), async (payload) => {
    await adminEndpoint(isEdit ? `/admin/announcements/${announcement.id}` : '/admin/announcements', {
      method: isEdit ? 'PATCH' : 'POST',
      body: JSON.stringify(payload),
    });
    await loadCommunityAdmin();
  });
}

async function archiveAnnouncement(id) {
  if (!window.confirm('确认归档这条公告？归档后前台将不再显示，但留言数据会保留。')) return;
  await adminEndpoint(`/admin/announcements/${id}`, { method: 'DELETE' });
  await loadCommunityAdmin();
}

function userFields(user = {}) {
  const permissionFields = [
    {
      name: 'role',
      label: '角色',
      type: 'select',
      value: user.role || 'user',
      options: [
        { value: 'user', label: '普通用户' },
        { value: 'admin', label: '管理员' },
      ],
    },
    { name: 'isActive', label: '启用账号', type: 'checkbox', value: user.isActive ?? true },
  ];
  if (user.id) {
    return [
      { name: 'displayName', label: '姓名', value: user.displayName || '' },
      ...permissionFields,
    ];
  }
  return [
    { name: 'username', label: '昵称', value: user.username, required: true },
    { name: 'displayName', label: '姓名', value: user.displayName || '' },
    { name: 'password', label: '密码（8-128 位）', type: 'password', required: true, minLength: 8, maxLength: 128 },
    ...permissionFields,
  ];
}

function openUserModal(user) {
  const isEdit = Boolean(user?.id);
  openAdminModal(isEdit ? '编辑用户' : '新建用户', userFields(user), async (payload) => {
    if (isEdit) {
      await adminEndpoint(`/admin/users/${user.id}`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
      });
    } else {
      await adminEndpoint('/admin/users', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
    }
    await loadUsers();
  });
}

function linesToList(value) {
  return String(value || '')
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

async function loadProjectAdminMeta() {
  if (adminState.projectMetaLoaded) return;
  const [meta, categories] = await Promise.all([
    adminEndpoint('/meta'),
    adminEndpoint('/admin/project-categories'),
  ]);
  adminState.projectCategories = categories.data.filter((category) => category.isActive);
  adminState.projectYears = meta.years;
  adminEls.projectCategoryList.innerHTML = [
    `<button class="category-button ${adminState.projectCategory ? '' : 'active'}" type="button" data-admin-project-category="">全部分类</button>`,
    ...adminState.projectCategories.map((category) => `
      <button
        class="category-button ${category.name === adminState.projectCategory ? 'active' : ''}"
        type="button"
        data-admin-project-category="${adminText(category.name)}"
        data-sortable="project-category"
        data-sortable-id="${adminText(category.id)}"
        draggable="true"
      >
        ${adminText(category.name)}
      </button>
    `),
  ].join('');
  adminEls.projectYear.innerHTML = '<option value="">全部年份</option>' +
    adminState.projectYears.map((year) => `<option value="${adminText(year)}">${adminText(year)}</option>`).join('');
  adminEls.projectYear.value = adminState.projectYear;
  adminState.projectMetaLoaded = true;
}

async function loadProjectManagementView() {
  await loadProjectAdminMeta();
  showProjectListView();
  await loadAdminProjects();
}

function showProjectListView() {
  adminState.currentProject = null;
  adminEls.projectListView.classList.remove('is-hidden');
  adminEls.projectDetailView.classList.add('is-hidden');
  adminEls.projectDetailView.innerHTML = '';
}

function showProjectDetailView(project) {
  adminState.currentProject = project;
  adminEls.projectListView.classList.add('is-hidden');
  adminEls.projectDetailView.classList.remove('is-hidden');
  adminEls.projectDetailView.innerHTML = adminProjectDetail(project);
}

async function openProjectDetail(projectId) {
  adminEls.projectListView.classList.add('is-hidden');
  adminEls.projectDetailView.classList.remove('is-hidden');
  adminEls.projectDetailView.innerHTML = '<div class="empty">正在加载项目详情...</div>';
  try {
    const project = await adminEndpoint(`/admin/projects/${encodeURIComponent(projectId)}`);
    adminState.projects = adminState.projects.map((item) => item.id === project.id ? project : item);
    showProjectDetailView(project);
  } catch (error) {
    showProjectListView();
    throw error;
  }
}

async function loadAdminProjects() {
  adminEls.projectList.innerHTML = '<div class="empty">正在加载项目...</div>';
  const query = buildQuery({
    search: adminEls.projectSearch.value.trim(),
    category: adminState.projectCategory,
    year: adminState.projectYear,
    sort: adminState.projectSort,
  });
  const result = await adminEndpoint(`/admin/projects${query}`);
  adminState.projects = result.data;
  adminEls.projectCount.textContent = `共 ${result.data.length} 个项目`;
  adminEls.projectList.innerHTML = result.data.length
    ? result.data.map(adminProjectRow).join('')
    : '<div class="empty">暂无项目</div>';
}

function adminProjectRow(project) {
  return `
    <article class="project-row admin-project-row">
      <button class="admin-project-main" type="button" data-open-project-detail="${adminText(project.id)}">
        ${projectIconImage(project)}
        <div>
          <h3>${adminText(project.name)}</h3>
          <div class="meta">
            <span class="badge">${adminText(project.category)}</span>
            <span>${adminText(project.year)}</span>
            <span>负责人：${adminText(project.leader || '待确认')}</span>
            <span>成员：${adminText(project.members || '待添加')}</span>
          </div>
          <p>${adminText(project.description)}</p>
          ${casTags(project.cas)}
        </div>
      </button>
      <button class="button compact" type="button" data-open-project-detail="${adminText(project.id)}">管理</button>
    </article>
  `;
}

const PROJECT_CONTACT_LABELS = {
  wechat: '微信',
  phone: '电话',
  email: '邮箱',
  other: '其他',
};

function adminProjectMembers(project) {
  const members = Array.isArray(project.memberList) ? project.memberList : [];
  if (!members.length) return '<div class="empty">暂无成员，负责人尚未确认。请点击“管理成员”添加人员并设置负责人。</div>';
  return `
    <div class="admin-project-member-list">
      ${members.map((member) => {
        const role = member.role === 'leader' ? '负责人' : '成员';
        const contact = member.contactValue
          ? `${PROJECT_CONTACT_LABELS[member.contactType] || '联系方式'}：${adminText(member.contactValue)}`
          : '未填写联系方式';
        return `
          <article class="admin-project-member-card">
            <div>
              <strong>${adminText(member.name)}</strong>
              <span>${role}</span>
            </div>
            <p>${contact}</p>
            <div class="admin-project-member-binding">
              <small>${member.registered ? `已绑定：@${adminText(member.username || member.userId)}` : '未绑定站内账号'}</small>
              <button
                class="button secondary compact"
                type="button"
                data-bind-project-member="${adminText(member.personId)}"
                data-binding-project="${adminText(project.id)}"
              >${member.registered ? '更改绑定' : '绑定账号'}</button>
            </div>
          </article>
        `;
      }).join('')}
    </div>
  `;
}

function normalizeAdminProjectUpdates(rawUpdates) {
  if (!Array.isArray(rawUpdates)) return [];
  return rawUpdates.map((item) => {
    if (item && typeof item === 'object') {
      const rawImages = item.images || item.photos || [];
      return {
        id: String(item.id || '').trim(),
        content: String(item.content || item.text || item.body || '').trim(),
        images: (Array.isArray(rawImages) ? rawImages : linesToList(rawImages))
          .map((image) => String(image || '').trim())
          .filter(Boolean),
      };
    }
    return { id: '', content: String(item || '').trim(), images: [] };
  }).filter((item) => item.content || item.images.length);
}

function projectAssetUrl(project, path) {
  const value = String(path || '').trim();
  if (!value || value.startsWith('/') || /^https?:\/\//i.test(value)) return value;
  const root = String(project.assetDir || '').replace(/\/+$/, '');
  return root ? `${root}/${value}` : value;
}

function adminProjectUpdates(project) {
  const updates = normalizeAdminProjectUpdates(project.updates);
  if (!updates.length) return '<div class="empty">暂无动态</div>';
  return `
    <div class="admin-project-update-list">
      ${updates.map((update) => {
        const visibleImages = update.images.slice(0, 6);
        return `
          <article class="admin-project-update-card">
            <p>${update.content ? adminText(update.content) : '<span>仅照片动态</span>'}</p>
            ${visibleImages.length ? `
              <div class="admin-project-update-photos">
                ${visibleImages.map((image, index) => `
                  <img src="${adminText(safeExternalUrl(projectAssetUrl(project, image)))}" alt="动态照片 ${index + 1}" loading="lazy">
                `).join('')}
                ${update.images.length > visibleImages.length ? `<span>+${update.images.length - visibleImages.length}</span>` : ''}
              </div>
            ` : '<small>无照片</small>'}
          </article>
        `;
      }).join('')}
    </div>
  `;
}

function adminProjectDetail(project) {
  return `
    <div class="admin-detail-head">
      <div>
        <h2>${adminText(project.name)}</h2>
        <p>${adminText(project.category)} · ${adminText(project.year)} · 热度 ${adminText(project.popularity)}</p>
      </div>
      <div class="admin-detail-actions">
        <button class="button secondary compact" type="button" data-back-project-list>返回列表</button>
        <button class="button compact" type="button" data-edit-project="${adminText(project.id)}">编辑基本信息</button>
      </div>
    </div>
    <div class="detail-head">
      ${projectIconImage(project)}
      <div>
        <h1>${adminText(project.name)}</h1>
        <div class="meta">
          <span class="badge">${adminText(project.category)}</span>
          <span>${adminText(project.year)}</span>
          <span>负责人：${adminText(project.leader || '待确认')}</span>
          <span>成员：${adminText(project.members || '待添加')}</span>
        </div>
        ${casTags(project.cas)}
      </div>
    </div>
    <section>
      <h2>项目简介</h2>
      <p>${adminText(project.description)}</p>
      <p class="admin-muted">资源目录：${adminText(project.assetDir || '尚未配置')}</p>
      ${project.assetDirWarning ? `<p class="admin-transfer-warning">${adminText(project.assetDirWarning)}</p>` : ''}
    </section>
    <section>
      <div class="admin-media-toolbar">
        <h2>成员与联系方式</h2>
        <button class="button secondary compact" type="button" data-edit-project-members="${adminText(project.id)}">管理成员资料</button>
      </div>
      ${adminProjectMembers(project)}
    </section>
    <section>
      <div class="admin-media-toolbar">
        <h2>项目动态</h2>
        <button class="button secondary compact" type="button" data-edit-project-updates="${adminText(project.id)}">管理动态与照片</button>
      </div>
      ${adminProjectUpdates(project)}
    </section>
  `;
}

function findAdminProject(projectId) {
  return adminState.projects.find((item) => String(item.id) === String(projectId))
    || (String(adminState.currentProject?.id) === String(projectId) ? adminState.currentProject : null);
}

function projectBasicFields(project = {}) {
  return [
    { name: 'name', label: '项目名称', value: project.name, required: true },
    { name: 'category', label: '分类', value: project.category, required: true },
    { name: 'year', label: '年份', value: project.year || new Date().getFullYear(), type: 'number', required: true },
    {
      name: 'assetDir',
      label: '项目资源目录',
      value: project.assetDir || '',
      required: true,
      browse: 'folder',
      browseRoot: '/CAS/',
    },
    { name: 'description', label: '简介', value: project.description, type: 'textarea', required: true },
    { name: 'casCreativity', label: 'CAS Creativity', value: project.cas?.creativity, type: 'checkbox' },
    { name: 'casActivity', label: 'CAS Activity', value: project.cas?.activity, type: 'checkbox' },
    { name: 'casService', label: 'CAS Service', value: project.cas?.service, type: 'checkbox' },
  ];
}

function updateAdminProjectState(project) {
  adminState.currentProject = project;
  adminState.projects = adminState.projects.map((item) => item.id === project.id ? project : item);
  showProjectDetailView(project);
}

function openProjectModal(project = {}) {
  const isEdit = Boolean(project?.id);
  openAdminModal(isEdit ? '编辑项目基本信息' : '新建 CAS 项目', projectBasicFields(project), async (payload) => {
    const saved = await adminEndpoint(isEdit ? `/admin/projects/${project.id}` : '/admin/projects', {
      method: isEdit ? 'PATCH' : 'POST',
      body: JSON.stringify(payload),
    });
    adminState.projectMetaLoaded = false;
    await loadProjectAdminMeta();
    await loadAdminProjects();
    updateAdminProjectState(saved);
  });
  if (isEdit) {
    const actions = adminEls.modalForm.querySelector('.admin-modal-actions');
    if (actions) {
      actions.insertAdjacentHTML(
        'afterbegin',
        `<button class="button secondary" type="button" data-export-project="${adminText(project.id)}">导出 JSON</button>`,
      );
    }
  }
}

let projectUpdateEditorSequence = 0;

function projectUpdateEditorItem(update = {}, project = adminState.currentProject || {}) {
  const normalized = normalizeAdminProjectUpdates([update])[0] || {
    id: String(update.id || ''),
    content: String(update.content || ''),
    images: Array.isArray(update.images) ? update.images : [],
  };
  projectUpdateEditorSequence += 1;
  const imageFieldName = `projectUpdateImages${projectUpdateEditorSequence}`;
  return `
    <div class="admin-project-update-editor-item admin-sortable-list-item" draggable="true" data-sortable-list-item data-project-update-editor-item data-update-id="${adminText(normalized.id || '')}">
      <span class="admin-sortable-list-handle">拖动</span>
      <div class="admin-project-update-editor-fields">
        <label>
          <span>动态内容</span>
          <textarea class="input" rows="4" data-project-update-content>${adminText(normalized.content)}</textarea>
        </label>
        <label>
          <span>已有照片的相对路径（一行一张）</span>
          <div class="admin-input-row">
            <textarea class="input" rows="3" name="${imageFieldName}" data-project-update-images>${adminText(normalized.images.join('\n'))}</textarea>
            <button class="button secondary compact" type="button" data-browse-target="${imageFieldName}" data-browse-mode="image" data-browse-root="${adminText(project.assetDir || '/CAS/')}" data-browse-relative-to="${adminText(project.assetDir || '')}">浏览</button>
          </div>
        </label>
        <label>
          <span>上传新照片</span>
          <input class="input" type="file" accept="image/jpeg,image/png,image/webp,image/gif,image/avif" multiple data-project-update-photos>
          <small class="admin-muted" data-project-update-photo-count>尚未选择新照片</small>
        </label>
      </div>
      <button class="button secondary compact danger" type="button" data-remove-project-update>删除</button>
    </div>
  `;
}

function openProjectUpdatesModal(project) {
  const updates = normalizeAdminProjectUpdates(project.updates);
  adminEls.modalTitle.textContent = '管理项目动态与照片';
  adminEls.modalForm.innerHTML = `
    <p class="admin-form-note">动态可以只有文字或只有照片。上传的新照片会自动保存到当前项目的 updates/动态ID/ 目录；也可以浏览项目目录内已有图片并记录相对路径。</p>
    <div class="admin-project-update-editor-list" data-project-update-editor>
      ${updates.length ? updates.map((update) => projectUpdateEditorItem(update, project)).join('') : projectUpdateEditorItem({}, project)}
    </div>
    <button class="button secondary compact" type="button" data-add-project-update>新增动态</button>
    <div id="adminModalMessage" class="auth-message"></div>
    <div class="admin-modal-actions">
      <button class="button secondary" type="button" data-admin-modal-close>取消</button>
      <button class="button" type="submit">保存动态</button>
    </div>
  `;
  adminEls.modal.classList.add('is-open');
  adminEls.modal.setAttribute('aria-hidden', 'false');
  adminEls.modalForm.onsubmit = async (event) => {
    event.preventDefault();
    const message = adminQuery('#adminModalMessage');
    message.textContent = '正在保存...';
    message.classList.remove('error');
    try {
      const rows = [...adminEls.modalForm.querySelectorAll('[data-project-update-editor-item]')];
      const existingIds = new Set(updates.map((update) => update.id).filter(Boolean));
      const retainedExistingIds = new Set(
        rows.map((row) => row.dataset.updateId).filter((id) => id && (
          row.querySelector('[data-project-update-content]').value.trim()
          || linesToList(row.querySelector('[data-project-update-images]').value).length
          || row.querySelector('[data-project-update-photos]').files.length
        )),
      );
      let saved = project;
      for (const updateId of existingIds) {
        if (!retainedExistingIds.has(updateId)) {
          saved = await adminEndpoint(`/admin/projects/${project.id}/updates/${encodeURIComponent(updateId)}`, {
            method: 'DELETE',
          });
        }
      }

      const finalIds = [];
      for (const row of rows) {
        const content = row.querySelector('[data-project-update-content]').value.trim();
        const imagePaths = linesToList(row.querySelector('[data-project-update-images]').value);
        const photoFiles = [...row.querySelector('[data-project-update-photos]').files];
        if (!content && !imagePaths.length && !photoFiles.length) continue;
        const body = new FormData();
        body.append('content', content);
        body.append('images', JSON.stringify(imagePaths));
        photoFiles.forEach((file) => body.append('photos', file));
        const currentId = row.dataset.updateId;
        const beforeIds = new Set(normalizeAdminProjectUpdates(saved.updates).map((update) => update.id));
        saved = await adminEndpoint(
          currentId
            ? `/admin/projects/${project.id}/updates/${encodeURIComponent(currentId)}`
            : `/admin/projects/${project.id}/updates`,
          { method: currentId ? 'PATCH' : 'POST', body },
        );
        const savedUpdates = normalizeAdminProjectUpdates(saved.updates);
        const resolvedId = currentId || savedUpdates.find((update) => !beforeIds.has(update.id))?.id;
        if (!resolvedId) throw new Error('新增动态后未返回动态 ID');
        row.dataset.updateId = resolvedId;
        finalIds.push(resolvedId);
      }
      if (finalIds.length > 1) {
        saved = await adminEndpoint(`/admin/projects/${project.id}/updates/reorder`, {
          method: 'PATCH',
          body: JSON.stringify({ updateIds: finalIds }),
        });
      }
      updateAdminProjectState(saved);
      closeAdminModal();
    } catch (error) {
      try {
        const refreshed = await adminEndpoint(`/admin/projects/${project.id}`);
        updateAdminProjectState(refreshed);
      } catch (_) {
        // Preserve the original save error when refresh also fails.
      }
      window.alert(`动态保存未全部完成：${error.message}\n已重新载入服务器上的最新数据。`);
      closeAdminModal();
    }
  };
}

function projectMemberEditorItem(member = {}) {
  const role = member.role === 'leader' ? 'leader' : 'member';
  const contactType = member.contactType || '';
  return `
    <div class="admin-member-editor-item" data-project-member-editor-item data-person-id="${adminText(member.personId || '')}">
      <label>
        <span>姓名</span>
        <input class="input" type="text" value="${adminText(member.name || '')}" data-project-member-name required>
      </label>
      <label>
        <span>身份</span>
        <select class="input" data-project-member-role>
          <option value="leader" ${role === 'leader' ? 'selected' : ''}>负责人</option>
          <option value="member" ${role === 'member' ? 'selected' : ''}>成员</option>
        </select>
      </label>
      <label>
        <span>联系方式</span>
        <select class="input" data-project-member-contact-type>
          <option value="" ${contactType ? '' : 'selected'}>未提供</option>
          <option value="wechat" ${contactType === 'wechat' ? 'selected' : ''}>微信</option>
          <option value="phone" ${contactType === 'phone' ? 'selected' : ''}>电话</option>
          <option value="email" ${contactType === 'email' ? 'selected' : ''}>邮箱</option>
          <option value="other" ${contactType === 'other' ? 'selected' : ''}>其他</option>
        </select>
      </label>
      <label>
        <span>联系值</span>
        <input class="input" type="text" value="${adminText(member.contactValue || '')}" placeholder="微信号、电话、邮箱等" data-project-member-contact-value>
      </label>
      <button class="button secondary compact danger" type="button" data-remove-project-member>删除</button>
    </div>
  `;
}

function openProjectMembersModal(project) {
  const members = Array.isArray(project.memberList) && project.memberList.length
    ? project.memberList
    : [{ name: '', role: 'leader' }];
  adminEls.modalTitle.textContent = '管理成员与联系方式';
  adminEls.modalForm.innerHTML = `
    <p class="admin-form-note">成员逐条维护；负责人尚未确认时可以暂不设置，确认后最多只能有一名负责人。联系方式不公开时可以留空。保存后可在项目详情的成员卡片中绑定站内账号。</p>
    <div class="admin-member-editor-list" data-project-member-editor>
      ${members.map(projectMemberEditorItem).join('')}
    </div>
    <button class="button secondary compact" type="button" data-add-project-member>新增成员</button>
    <div id="adminModalMessage" class="auth-message"></div>
    <div class="admin-modal-actions">
      <button class="button secondary" type="button" data-admin-modal-close>取消</button>
      <button class="button" type="submit">保存成员</button>
    </div>
  `;
  adminEls.modal.classList.add('is-open');
  adminEls.modal.setAttribute('aria-hidden', 'false');
  adminEls.modalForm.onchange = (event) => {
    if (!event.target.matches('[data-project-member-role]') || event.target.value !== 'leader') return;
    adminEls.modalForm.querySelectorAll('[data-project-member-role]').forEach((select) => {
      if (select !== event.target) select.value = 'member';
    });
  };
  adminEls.modalForm.onsubmit = async (event) => {
    event.preventDefault();
    const message = adminQuery('#adminModalMessage');
    message.textContent = '正在保存...';
    message.classList.remove('error');
    try {
      const rows = [...adminEls.modalForm.querySelectorAll('[data-project-member-editor-item]')];
      const memberItems = rows.map((row) => ({
        personId: row.dataset.personId ? adminNumber(row.dataset.personId) : null,
        name: row.querySelector('[data-project-member-name]').value.trim(),
        role: row.querySelector('[data-project-member-role]').value,
        contactType: row.querySelector('[data-project-member-contact-type]').value || null,
        contactValue: row.querySelector('[data-project-member-contact-value]').value.trim() || null,
      }));
      if (!memberItems.length) throw new Error('项目至少需要一名成员');
      if (memberItems.some((member) => !member.name)) throw new Error('成员姓名不能为空');
      if (memberItems.filter((member) => member.role === 'leader').length > 1) {
        throw new Error('项目最多只能有一名负责人');
      }
      const names = memberItems.map((member) => member.name.toLocaleLowerCase());
      if (new Set(names).size !== names.length) throw new Error('成员姓名不能重复');
      const incompleteContact = memberItems.find(
        (member) => Boolean(member.contactType) !== Boolean(member.contactValue),
      );
      if (incompleteContact) throw new Error(`请为 ${incompleteContact.name} 同时填写联系方式类型和联系值`);

      const saved = await adminEndpoint(`/admin/projects/${project.id}/members`, {
        method: 'PATCH',
        body: JSON.stringify({ members: memberItems }),
      });
      updateAdminProjectState(saved);
      closeAdminModal();
    } catch (error) {
      message.textContent = error.message;
      message.classList.add('error');
    }
  };
}

async function openProjectMemberBindingModal(project, member) {
  const result = await adminEndpoint('/admin/users?isActive=true');
  const users = result.data || [];
  adminState.users = users;
  const availableUsers = users.filter(
    (user) => !user.campusVerified || String(user.id) === String(member.userId || ''),
  );
  const options = [
    { value: '', label: '不绑定账号' },
    ...availableUsers.map((user) => ({
      value: user.id,
      label: `${user.displayName || user.username} (@${user.username})${user.role === 'admin' ? ' · 管理员' : ''}`,
    })),
  ];
  openAdminModal(
    `绑定成员账号：${member.name}`,
    [{
      name: 'userId',
      label: '站内用户',
      type: 'select',
      value: member.userId || '',
      options,
    }],
    async (payload) => {
      const userId = payload.userId ? adminNumber(payload.userId) : null;
      await adminEndpoint(
        `/admin/projects/${encodeURIComponent(project.id)}/members/${encodeURIComponent(member.personId)}/binding`,
        {
          method: 'PATCH',
          body: JSON.stringify({ userId }),
        },
      );
      const saved = await adminEndpoint(`/admin/projects/${encodeURIComponent(project.id)}`);
      updateAdminProjectState(saved);
    },
  );
}

async function loadResourceAdminMeta() {
  if (adminState.resourceMetaLoaded) return;
  const [meta, adminCategories] = await Promise.all([
    adminEndpoint('/resources/meta'),
    adminEndpoint('/admin/resource-categories'),
  ]);
  meta.categories = adminCategories.data.filter((category) => category.isActive);
  const categories = [
    { value: '', label: '全部资源' },
    ...meta.categories,
  ];
  adminEls.resourceCategoryList.innerHTML = categories.map((category) => `
    <button
      class="category-button ${category.value === adminState.resourceCategory ? 'active' : ''}"
      type="button"
      data-admin-resource-category="${adminText(category.value)}"
    >
      ${adminText(category.label)}
    </button>
  `).join('');
  adminState.resourceMeta = meta;
  adminState.resourceMetaLoaded = true;
  renderResourceYearOptions();
}

function isPhotoResourceCategory() {
  return adminState.resourceCategory === 'photos';
}

function activeAdminResourceFilterCount() {
  return Number(Boolean(adminState.resourceCategory))
    + Number(Boolean(adminState.resourceYear))
    + Number(adminState.resourceSort !== 'hot');
}

function setAdminResourceFilterPanelOpen(isOpen) {
  adminEls.resourceAdvancedFilters.hidden = !isOpen;
  adminEls.resourceFilterToggle.setAttribute('aria-expanded', String(isOpen));
  adminEls.resourceFilterToggle.setAttribute('aria-label', isOpen ? '收起详细筛选' : '显示详细筛选');
  adminEls.resourceFilterToggle.classList.toggle('is-open', isOpen);
}

function updateAdminResourceFilterIndicator() {
  const count = activeAdminResourceFilterCount();
  adminEls.resourceFilterCount.hidden = count === 0;
  adminEls.resourceFilterCount.textContent = String(count);
  adminEls.resourceFilterToggle.classList.toggle('has-active-filters', count > 0);
  adminEls.clearResourceFilters.disabled = count === 0;
}

function renderResourceYearOptions() {
  const meta = adminState.resourceMeta || { years: [], photoYears: [] };
  const years = isPhotoResourceCategory() ? meta.photoYears : meta.years;
  const currentYear = adminEls.resourceYear?.value || adminState.resourceYear;
  adminEls.resourceYear.innerHTML = '<option value="">全部年份</option>' +
    years.map((year) => `<option value="${adminText(year)}">${adminText(year)}</option>`).join('');
  if ([...adminEls.resourceYear.options].some((option) => option.value === String(currentYear))) {
    adminEls.resourceYear.value = currentYear;
  }
  adminState.resourceYear = adminEls.resourceYear.value;
}

function renderResourceSortOptions() {
  const options = ResourceUI.sortOptions(adminState.resourceCategory);
  const currentSort = adminEls.resourceSort.value || adminState.resourceSort;
  adminEls.resourceSort.innerHTML = options.map((option) => `
    <option value="${adminText(option.value)}">${adminText(option.label)}</option>
  `).join('');
  adminEls.resourceSort.value = options.some((option) => option.value === currentSort) ? currentSort : 'hot';
  adminState.resourceSort = adminEls.resourceSort.value;
}

async function loadResourceManagementView() {
  await loadResourceAdminMeta();
  const isPhotoMode = isPhotoResourceCategory();
  renderResourceSortOptions();
  updateAdminResourceFilterIndicator();
  adminEls.createResourceButton.classList.toggle('is-hidden', isPhotoMode);
  adminEls.createActivityButton.classList.toggle('is-hidden', !isPhotoMode);
  adminEls.photoFilters.classList.toggle('is-visible', isPhotoMode);
  adminEls.resourceView.classList.toggle('is-hidden', isPhotoMode);
  adminEls.photoView.classList.toggle('is-visible', isPhotoMode);
  adminEls.resourceSearch.placeholder = isPhotoMode ? '搜索活动名称' : '搜索名称、内容、简介';
  if (isPhotoMode) {
    await loadActivities();
    return;
  }
  adminState.selectedActivity = null;
  adminState.currentActivity = null;
  await loadResources();
}

async function loadResources() {
  adminEls.resourcesTable.innerHTML = '<div class="empty">正在加载资源...</div>';
  if (!adminState.resourceCategory) {
    const resourceQuery = buildQuery({
      search: adminEls.resourceSearch.value.trim(),
      year: adminState.resourceYear,
      sort: adminState.resourceSort,
    });
    const activityQuery = buildQuery({
      search: adminEls.resourceSearch.value.trim(),
      year: adminState.resourceYear,
      sort: ['hot', 'new', 'old', 'photoCount'].includes(adminState.resourceSort) ? adminState.resourceSort : 'hot',
    });
    const [resourceResult, activityResult] = await Promise.all([
      adminEndpoint(`/resources${resourceQuery}`),
      adminEndpoint(`/photo-activities${activityQuery}`),
    ]);
    adminState.resources = resourceResult.data;
    adminState.activities = activityResult.data;
    const combined = ResourceUI.sortCombinedResources([
      ...adminState.resources.map((item) => ({ kind: 'resource', data: item })),
      ...adminState.activities.map((item) => ({ kind: 'activity', data: item })),
    ], adminState.resourceSort);
    adminEls.resourceCount.textContent = `共 ${combined.length} 个资源`;
    adminEls.resourcesTable.innerHTML = combined.length
      ? combined.map((item) => (item.kind === 'resource' ? resourceAdminCard(item.data) : photoActivityCard(item.data))).join('')
      : '<div class="empty">暂无资源</div>';
    return;
  }
  const query = buildQuery({
    search: adminEls.resourceSearch.value.trim(),
    category: adminState.resourceCategory,
    year: adminState.resourceYear,
    sort: adminState.resourceSort,
  });
  const result = await adminEndpoint(`/resources${query}`);
  adminState.resources = result.data;
  adminEls.resourceCount.textContent = `共 ${result.data.length} 个资源`;
  adminEls.resourcesTable.innerHTML = adminState.resources.length
    ? adminState.resources.map(resourceAdminCard).join('')
    : '<div class="empty">暂无资源</div>';
}

function selectResourceCategory(category) {
  adminState.resourceCategory = category;
  adminState.resourceYear = '';
  adminEls.resourceCategoryList.querySelectorAll('.category-button').forEach((item) => {
    item.classList.toggle('active', item.dataset.adminResourceCategory === category);
  });
  adminEls.resourceYear.value = '';
  renderResourceYearOptions();
  updateAdminResourceFilterIndicator();
}

function resourceAdminCard(resource) {
  const previewUrl = `/resource.html?id=${encodeURIComponent(resource.id)}&preview=admin`;
  return ResourceUI.resourceCard(resource, {
    managed: true,
    newTab: true,
    href: previewUrl,
    editAttribute: 'data-edit-resource',
  });
}

function resourceCategoryOptions() {
  const categories = adminState.resourceMeta?.categories || [];
  return categories
    .map((category) => ({ value: category.value, label: category.label }));
}

function resourceFields(resource = {}) {
  const categoryOptions = resourceCategoryOptions();
  const defaultCategory = categoryOptions[0]?.value || 'other';
  const category = resource.category || defaultCategory;
  const isYearbook = category === 'yearbook';
  const isTeacherVideo = category === 'teacher';
  return [
    { name: 'title', label: isTeacherVideo ? '名称' : '标题', value: resource.title, required: true },
    { name: 'description', label: '简介（选填）', value: resource.description, type: 'textarea' },
    { name: 'year', label: '年份', value: resource.year || new Date().getFullYear(), type: 'number', required: true },
    {
      name: 'category',
      label: '分类',
      value: category,
      type: 'select',
      required: true,
      options: categoryOptions,
    },
    ...(isTeacherVideo ? [] : [
      { name: 'downloads', label: '下载数', value: resource.downloads || 0, type: 'number' },
    ]),
    ...(isYearbook ? [] : [{
      name: 'image',
      label: isTeacherVideo ? '封面 URL（选填）' : '封面 URL',
      value: resource.image,
      required: !isTeacherVideo,
      browse: 'file',
    }]),
    {
      name: 'resourceUrl',
      label: isYearbook ? 'Yearbook 目录' : isTeacherVideo ? '视频文件 / URL' : '资源 URL',
      value: resource.resourceUrl,
      required: true,
      browse: isYearbook ? 'folder' : isTeacherVideo ? 'file' : 'fileOrFolder',
    },
  ];
}

function resourceFormMode(category) {
  if (category === 'yearbook') return 'yearbook';
  if (category === 'teacher') return 'teacher';
  if (category === 'photos') return 'photos';
  return 'resource';
}

function openResourceModal(resource) {
  const isEdit = Boolean(resource?.id);
  openAdminModal(isEdit ? '编辑资源' : '新建资源', resourceFields(resource), async (payload) => {
    if (!isEdit && payload.category === 'photos') {
      selectResourceCategory('photos');
      await loadResourceManagementView();
      setTimeout(() => openActivityModal({}), 0);
      return;
    }
    const selectedCategory = resourceCategoryOptions().find((category) => category.value === payload.category);
    payload.label = selectedCategory?.label || payload.category;
    await adminEndpoint(isEdit ? `/admin/resources/${resource.id}` : '/admin/resources', {
      method: isEdit ? 'PATCH' : 'POST',
      body: JSON.stringify(payload),
    });
    adminState.resourceMetaLoaded = false;
    await loadResourceManagementView();
  });
  const categorySelect = adminEls.modalForm.elements.category;
  if (!isEdit && categorySelect) {
    categorySelect.addEventListener('change', () => {
      const nextCategory = categorySelect.value;
      if (nextCategory === 'photos') {
        closeAdminModal();
        selectResourceCategory('photos');
        loadResourceManagementView()
          .then(() => openActivityModal({}))
          .catch((error) => window.alert(error.message));
        return;
      }
      if (resourceFormMode(nextCategory) === resourceFormMode(category)) return;
      const selectedCategory = resourceCategoryOptions().find((item) => item.value === nextCategory);
      closeAdminModal();
      setTimeout(() => openResourceModal({ category: nextCategory, label: selectedCategory?.label }), 0);
    });
  }
  if (isEdit) {
    const actions = adminEls.modalForm.querySelector('.admin-modal-actions');
    if (actions) {
      actions.insertAdjacentHTML(
        'afterbegin',
        `<button class="button secondary danger" type="button" data-delete-resource-from-modal="${adminText(resource.id)}">删除资源</button>
         <button class="button secondary" type="button" data-export-resource="${adminText(resource.id)}">导出 JSON</button>`,
      );
    }
  }
}

async function deleteResource(id) {
  if (!window.confirm('确认删除这个资源？只会删除数据库记录，不会删除已上传或已引用的文件。')) return false;
  await adminEndpoint(`/admin/resources/${id}`, { method: 'DELETE' });
  await loadResourceManagementView();
  return true;
}

async function loadActivities() {
  adminEls.activitiesTable.innerHTML = '<div class="empty">正在加载活动照片...</div>';
  const query = buildQuery({
    search: adminEls.resourceSearch.value.trim(),
    year: adminState.resourceYear,
    sort: adminState.resourceSort,
  });
  const result = await adminEndpoint(`/photo-activities${query}`);
  adminState.activities = result.data;
  if (adminState.selectedActivity !== null && !result.data.some((item) => item.id === adminState.selectedActivity)) {
    adminState.selectedActivity = null;
  }
  await renderAdminPhotos(result.data);
}

function activityPhotoCount(activity) {
  if (Array.isArray(activity.images)) return activity.images.length;
  return adminNumber(activity.photoCount, 0);
}

function activityCoverImage(activity) {
  if (Array.isArray(activity.images) && activity.images[0]) {
    return activity.images[0].thumbSrc || activity.images[0].src || '';
  }
  return activity.coverThumbSrc || activity.coverSrc || '';
}

async function loadAdminActivityPhotos(activity) {
  if (Array.isArray(activity.images)) return activity.images;
  const result = await adminEndpoint(`/photo-activities/${activity.id}/photos?track=false`);
  activity.images = result.data;
  return activity.images;
}

function renderAdminActivityList(activities) {
  if (!activities.length) {
    adminEls.activityList.innerHTML = '<div class="empty">暂无活动</div>';
    return;
  }
  const totalPhotoCount = activities.reduce((sum, activity) => sum + activityPhotoCount(activity), 0);
  adminEls.activityList.innerHTML = [
    `<button class="category-button ${adminState.selectedActivity === null ? 'active' : ''}" type="button" data-admin-activity-id="">
      全部活动
      <span class="activity-count">${adminText(totalPhotoCount)} 张</span>
    </button>`,
    ...activities.map((activity) => `
      <button
        class="category-button ${activity.id === adminState.selectedActivity ? 'active' : ''}"
        type="button"
        data-admin-activity-id="${adminText(activity.id)}"
        data-sortable="activity"
        data-sortable-id="${adminText(activity.id)}"
        draggable="true"
      >
        ${adminText(activity.activity)}
        <span class="activity-count">${adminText(activityPhotoCount(activity))} 张</span>
      </button>
    `),
  ].join('');
}

function photoButton(item) {
  return ResourceUI.photoItem(item);
}

function photoActivityCard(activity) {
  return ResourceUI.activityCard(activity, {
    managed: true,
    image: activityCoverImage(activity),
    dataAttribute: 'data-admin-activity-card-id',
    editAttribute: 'data-edit-activity',
  });
}

function openAdminPhotoModal(index) {
  const item = adminState.activePhotoItems[index];
  if (!item) return;

  const src = safeExternalUrl(item.src);
  adminState.currentModalIndex = index;
  adminState.currentModalPhoto = { ...item, src };
  adminEls.photoModalTitle.textContent = item.title || '照片详情';
  adminEls.photoModalMeta.textContent = [...[item.activity, item.year].filter(Boolean), `${index + 1}/${adminState.activePhotoItems.length}`].join(' · ');
  adminEls.photoModalImage.src = src;
  adminEls.photoModalImage.alt = item.title || '';
  adminEls.photoModal.classList.add('is-open');
  adminEls.photoModal.setAttribute('aria-hidden', 'false');
}

function shiftAdminPhotoModal(direction) {
  if (!adminEls.photoModal.classList.contains('is-open') || !adminState.activePhotoItems.length) return;
  const nextIndex = (adminState.currentModalIndex + direction + adminState.activePhotoItems.length) % adminState.activePhotoItems.length;
  openAdminPhotoModal(nextIndex);
}

function closeAdminPhotoModal() {
  adminEls.photoModal.classList.remove('is-open');
  adminEls.photoModal.setAttribute('aria-hidden', 'true');
  adminEls.photoModalImage.src = '';
  adminState.currentModalPhoto = null;
  adminState.currentModalIndex = -1;
}

function downloadAdminModalPhoto() {
  const item = adminState.currentModalPhoto;
  if (!item) return;
  if (!requireAuthForDownload()) return;

  const link = document.createElement('a');
  link.href = authenticatedPublicFileUrl(item.src) || item.src;
  link.download = `${item.activity || 'photo'}-${item.title || 'image'}.jpg`;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

async function renderAdminPhotos(activities) {
  renderAdminActivityList(activities);
  if (adminState.selectedActivity === null) {
    const totalPhotoCount = activities.reduce((sum, activity) => sum + activityPhotoCount(activity), 0);
    adminEls.activitiesTable.classList.remove('photo-groups');
    adminEls.activitiesTable.classList.add('photo-activity-cards');
    adminEls.photoTitle.textContent = '全部活动';
    adminEls.photoMeta.textContent = `${activities.length} 个活动 · ${totalPhotoCount} 张照片`;
    adminEls.editCurrentActivityButton.classList.add('is-hidden');
    adminEls.downloadActivity.classList.add('is-hidden');
    adminState.activePhotoItems = [];
    adminState.currentActivity = null;
    adminEls.activitiesTable.innerHTML = activities.length
      ? activities.map(photoActivityCard).join('')
      : '<div class="empty">没有找到匹配的活动。</div>';
    return;
  }

  const current = activities.find((activity) => activity.id === adminState.selectedActivity);
  adminEls.activitiesTable.classList.remove('photo-groups', 'photo-activity-cards');
  adminEls.downloadActivity.classList.remove('is-hidden');
  adminEls.editCurrentActivityButton.classList.remove('is-hidden');
  if (!current) {
    adminEls.photoTitle.textContent = '活动照片';
    adminEls.photoMeta.textContent = '没有找到匹配的活动';
    adminEls.activitiesTable.innerHTML = '';
    adminState.activePhotoItems = [];
    adminState.currentActivity = null;
    return;
  }

  adminState.currentActivity = current;
  adminEls.photoTitle.textContent = current.activity;
  adminEls.photoMeta.textContent = `${current.description} · ${current.year} · ${activityPhotoCount(current)} 张照片 · 热度 ${current.hot} · 下载 ${current.downloads || 0}`;
  adminEls.activitiesTable.innerHTML = '<div class="empty">正在加载活动照片...</div>';
  let photos = [];
  try {
    photos = await loadAdminActivityPhotos(current);
  } catch (error) {
    adminEls.activitiesTable.innerHTML = `<div class="empty error">${adminText(error.message)}</div>`;
    adminState.activePhotoItems = [];
    return;
  }
  if (adminState.selectedActivity !== current.id) return;
  adminEls.photoMeta.textContent = `${current.description} · ${current.year} · ${photos.length} 张照片 · 热度 ${current.hot} · 下载 ${current.downloads || 0}`;
  adminState.activePhotoItems = photos.map((item, index) => ({
    ...item,
    activity: current.activity,
    year: current.year,
    index,
  }));
  adminEls.activitiesTable.innerHTML = adminState.activePhotoItems.length
    ? adminState.activePhotoItems.map(photoButton).join('')
    : '<div class="empty">这个活动还没有照片。</div>';
}

function activityFields(activity = {}, options = {}) {
  const categoryField = {
    name: 'category',
    label: '分类',
    value: 'photos',
    type: 'select',
    required: true,
    options: resourceCategoryOptions(),
  };
  return [
    { name: 'activity', label: '活动名称', value: activity.activity, required: true },
    { name: 'description', label: '活动简介', value: activity.description, type: 'textarea', required: true },
    { name: 'year', label: '年份', value: activity.year || new Date().getFullYear(), type: 'number', required: true },
    ...(options.includeCategory ? [categoryField] : []),
    { name: 'downloads', label: '下载数', value: activity.downloads || 0, type: 'number' },
    { name: 'sortOrder', label: 'sortOrder', value: activity.sortOrder || 0, type: 'number' },
    { name: 'photoDir', label: '照片目录', value: activity.photoDir || '', browse: 'folder' },
  ];
}

function openActivityModal(activity) {
  const isEdit = Boolean(activity?.id);
  openAdminModal(isEdit ? '编辑活动' : '新建活动', activityFields(activity, { includeCategory: !isEdit }), async (payload) => {
    if (!isEdit && payload.category && payload.category !== 'photos') {
      const selectedCategory = resourceCategoryOptions().find((category) => category.value === payload.category);
      selectResourceCategory(payload.category);
      await loadResourceManagementView();
      setTimeout(() => openResourceModal({ category: payload.category, label: selectedCategory?.label }), 0);
      return;
    }
    delete payload.category;
    await adminEndpoint(isEdit ? `/admin/photo-activities/${activity.id}` : '/admin/photo-activities', {
      method: isEdit ? 'PATCH' : 'POST',
      body: JSON.stringify(payload),
    });
    adminState.resourceMetaLoaded = false;
    await loadActivities();
  });
  const categorySelect = adminEls.modalForm.elements.category;
  if (!isEdit && categorySelect) {
    categorySelect.addEventListener('change', () => {
      if (categorySelect.value === 'photos') return;
      const selectedCategory = resourceCategoryOptions().find((category) => category.value === categorySelect.value);
      closeAdminModal();
      selectResourceCategory(categorySelect.value);
      loadResourceManagementView()
        .then(() => openResourceModal({ category: categorySelect.value, label: selectedCategory?.label }))
        .catch((error) => window.alert(error.message));
    });
  }
  if (isEdit) {
    const actions = adminEls.modalForm.querySelector('.admin-modal-actions');
    if (actions) {
      actions.insertAdjacentHTML(
        'afterbegin',
        `<button class="button secondary danger" type="button" data-delete-activity-from-modal="${adminText(activity.id)}">删除活动</button>
         <button class="button secondary" type="button" data-export-photo-activity="${adminText(activity.id)}">导出 JSON</button>`,
      );
    }
  }
}

async function deleteActivity(id) {
  if (!window.confirm('确认删除这个活动？活动下照片记录会一起删除。')) return false;
  await adminEndpoint(`/admin/photo-activities/${id}`, { method: 'DELETE' });
  adminState.selectedActivity = null;
  await loadResourceManagementView();
  return true;
}

function bindAdminEvents() {
  bindSortableLists();
  document.querySelectorAll('[data-admin-view]').forEach((button) => {
    button.addEventListener('click', () => switchAdminView(button.dataset.adminView));
  });
  document.querySelectorAll('[data-admin-modal-close]').forEach((item) => {
    item.addEventListener('click', closeAdminModal);
  });
  document.querySelectorAll('[data-file-picker-close]').forEach((item) => {
    item.addEventListener('click', closeFilePicker);
  });
  adminEls.adminLogout.addEventListener('click', () => {
    clearAuthSession();
    window.location.href = '/index.html';
  });
  adminEls.exportAllDataButton.addEventListener('click', () => {
    downloadAdminJson('/admin/data-export', 'nethub-data.json')
      .catch((error) => window.alert(error.message));
  });
  adminEls.downloadDataTemplateButton.addEventListener('click', () => {
    downloadAdminJson('/admin/data-template', 'nethub-data-template.json')
      .catch((error) => window.alert(error.message));
  });
  adminEls.dataImportInput.addEventListener('change', () => {
    const file = adminEls.dataImportInput.files?.[0];
    resetImportPreview(file ? `已选择：${file.name}。请先检查并预览。` : undefined);
  });
  adminEls.previewDataImportButton.addEventListener('click', previewDataImport);
  adminEls.confirmDataImportButton.addEventListener('click', confirmDataImport);
  adminEls.fileUpButton.addEventListener('click', () => loadFiles(parentPublicPath(adminState.filePath)));
  adminEls.createFolderButton.addEventListener('click', createFolderInCurrentDirectory);
  adminEls.folderName.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') createFolderInCurrentDirectory();
  });
  adminEls.uploadButton.addEventListener('click', uploadToCurrentDirectory);
  adminEls.folderUploadButton.addEventListener('click', uploadFolderToCurrentDirectory);
  adminEls.folderUploadInput.addEventListener('change', () => {
    const files = [...(adminEls.folderUploadInput.files || [])];
    if (!files.length) return;
    const relativePath = files[0].webkitRelativePath || files[0].name;
    const folderName = relativePath.split('/')[0];
    setFileActionMessage(`已选择：${folderName}（${files.length} 个文件）`);
  });

  adminEls.createUserButton.addEventListener('click', () => openUserModal({ isActive: true, role: 'user' }));
  adminEls.refreshUsers.addEventListener('click', loadUsers);
  adminEls.userSearch.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') loadUsers();
  });
  adminEls.userRoleFilter.addEventListener('change', loadUsers);
  adminEls.userActiveFilter.addEventListener('change', loadUsers);
  adminEls.createAnnouncementButton.addEventListener('click', () => openAnnouncementModal({ status: 'published' }));
  adminEls.refreshCommunity.addEventListener('click', loadCommunityAdmin);

  adminEls.createProjectButton.addEventListener('click', () => openProjectModal({}));
  adminEls.projectSearch.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') loadProjectManagementView();
  });
  adminEls.projectYear.addEventListener('change', () => {
    adminState.projectYear = adminEls.projectYear.value;
    loadProjectManagementView();
  });
  adminEls.projectSort.addEventListener('change', () => {
    adminState.projectSort = adminEls.projectSort.value;
    loadProjectManagementView();
  });

  adminEls.createResourceButton.addEventListener('click', () => {
    openResourceModal({ category: adminState.resourceCategory || 'other' });
  });
  adminEls.createActivityButton.addEventListener('click', () => openActivityModal({}));
  adminEls.resourceFilterToggle.addEventListener('click', () => {
    setAdminResourceFilterPanelOpen(adminEls.resourceAdvancedFilters.hidden);
  });
  adminEls.clearResourceFilters.addEventListener('click', () => {
    adminState.resourceCategory = '';
    adminState.resourceYear = '';
    adminState.resourceSort = 'hot';
    adminEls.resourceYear.value = '';
    adminEls.resourceSort.value = 'hot';
    adminEls.resourceCategoryList.querySelectorAll('.category-button').forEach((button) => {
      button.classList.toggle('active', button.dataset.adminResourceCategory === '');
    });
    adminState.selectedActivity = null;
    loadResourceManagementView();
  });
  adminEls.resourceSearch.addEventListener('input', () => {
    clearTimeout(adminState.resourceSearchDebounce);
    adminState.resourceSearchDebounce = setTimeout(loadResourceManagementView, 300);
  });
  adminEls.resourceSearch.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      clearTimeout(adminState.resourceSearchDebounce);
      loadResourceManagementView();
    }
  });
  adminEls.resourceYear.addEventListener('change', () => {
    adminState.resourceYear = adminEls.resourceYear.value;
    loadResourceManagementView();
  });
  adminEls.resourceSort.addEventListener('change', () => {
    adminState.resourceSort = adminEls.resourceSort.value;
    loadResourceManagementView();
  });
  adminEls.editCurrentActivityButton.addEventListener('click', () => {
    if (adminState.currentActivity) openActivityModal(adminState.currentActivity);
  });
  adminEls.downloadActivity.addEventListener('click', () => {
    if (!requireAuthForDownload()) return;

    const archiveUrl = adminState.currentActivity?.archiveUrl;
    if (!archiveUrl) {
      window.alert('当前活动还没有配置压缩文件。');
      return;
    }
    window.open(authenticatedPublicFileUrl(archiveUrl) || safeExternalUrl(archiveUrl), '_blank', 'noopener,noreferrer');
  });
  adminEls.photoModalDownload.addEventListener('click', downloadAdminModalPhoto);
  adminEls.photoModalPrev.addEventListener('click', () => shiftAdminPhotoModal(-1));
  adminEls.photoModalNext.addEventListener('click', () => shiftAdminPhotoModal(1));

  document.addEventListener('click', (event) => {
    const target = event.target.closest('button');
    if (!target) return;
    if (adminState.dragJustEnded) return;

    if (target.dataset.adminModalClose !== undefined) closeAdminModal();
    if (target.dataset.filePickerClose !== undefined) closeFilePicker();
    if (target.dataset.adminPhotoModalClose !== undefined) closeAdminPhotoModal();
    if (target.dataset.browseTarget) {
      openFilePicker(
        target.dataset.browseTarget,
        target.dataset.browseMode,
        target.dataset.browseRoot,
        target.dataset.browseRelativeTo,
      );
    }
    if (target.dataset.openFileFolder) {
      if (adminState.picker) {
        loadPickerFiles(target.dataset.openFileFolder);
      } else {
        loadFiles(target.dataset.openFileFolder);
      }
    }
    if (target.dataset.pickerUp !== undefined && adminState.picker) {
      const parent = parentPublicPath(adminState.picker.path);
      const root = adminState.picker.root || '';
      const nextPath = !root || parent === root || parent.startsWith(`${root}/`) ? parent : root;
      loadPickerFiles(nextPath);
    }
    if (target.dataset.pickCurrentFolder !== undefined && adminState.picker) {
      chooseFileUrl(publicFolderUrl(adminState.picker.path));
    }
    if (target.dataset.pickFileUrl) chooseFileUrl(target.dataset.pickFileUrl);
    if (target.dataset.sortableListAdd) {
      const list = target.closest('[data-sortable-list-field]')?.querySelector('.admin-sortable-list-items');
      if (list) list.insertAdjacentHTML('beforeend', sortableListItem(target.dataset.sortableListAdd));
    }
    if (target.dataset.sortableListRemove !== undefined) {
      const item = target.closest('.admin-sortable-list-item');
      const list = item?.parentElement;
      if (item && list && list.children.length > 1) {
        item.remove();
      } else if (item) {
        const input = item.querySelector('[data-sortable-list-input]');
        if (input) input.value = '';
      }
    }
    if (target.dataset.addProjectMember !== undefined) {
      const list = adminEls.modalForm.querySelector('[data-project-member-editor]');
      if (list) list.insertAdjacentHTML('beforeend', projectMemberEditorItem({ role: 'member' }));
    }
    if (target.dataset.removeProjectMember !== undefined) {
      const item = target.closest('[data-project-member-editor-item]');
      const list = item?.parentElement;
      if (!item || !list) return;
      if (list.children.length <= 1) {
        window.alert('项目至少需要一名成员');
        return;
      }
      item.remove();
    }
    if (target.dataset.addProjectUpdate !== undefined) {
      const list = adminEls.modalForm.querySelector('[data-project-update-editor]');
      if (list) list.insertAdjacentHTML('beforeend', projectUpdateEditorItem({}, adminState.currentProject));
    }
    if (target.dataset.removeProjectUpdate !== undefined) {
      const item = target.closest('[data-project-update-editor-item]');
      const list = item?.parentElement;
      if (!item || !list) return;
      if (list.children.length > 1) {
        item.remove();
      } else {
        const content = item.querySelector('[data-project-update-content]');
        const images = item.querySelector('[data-project-update-images]');
        if (content) content.value = '';
        if (images) images.value = '';
      }
    }
    if (target.dataset.editUser) {
      openUserModal(adminState.users.find((item) => String(item.id) === target.dataset.editUser));
    }
    if (target.dataset.reviewReport) {
      adminEndpoint(`/admin/message-reports/${target.dataset.reviewReport}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: target.dataset.reportDecision }),
      }).then(loadCommunityAdmin).catch((error) => window.alert(error.message));
    }
    if (target.dataset.editAnnouncement) {
      const announcement = adminState.announcements.find(
        (item) => String(item.id) === target.dataset.editAnnouncement,
      );
      if (announcement) openAnnouncementModal(announcement);
    }
    if (target.dataset.archiveAnnouncement) {
      archiveAnnouncement(target.dataset.archiveAnnouncement).catch((error) => window.alert(error.message));
    }
    if (target.dataset.reviewCommentReport) {
      const hideComment = target.dataset.commentReportDecision === 'hide';
      adminEndpoint(`/admin/comment-reports/${target.dataset.reviewCommentReport}`, {
        method: 'PATCH',
        body: JSON.stringify({
          status: hideComment ? 'resolved' : 'dismissed',
          hideComment,
        }),
      }).then(loadCommunityAdmin).catch((error) => window.alert(error.message));
    }
    if (target.dataset.bindProjectMember) {
      const project = findAdminProject(target.dataset.bindingProject);
      const member = project?.memberList?.find(
        (item) => String(item.personId) === String(target.dataset.bindProjectMember),
      );
      if (project && member) {
        openProjectMemberBindingModal(project, member).catch((error) => window.alert(error.message));
      }
    }
    if (target.dataset.adminProjectCategory !== undefined) {
      adminState.projectCategory = target.dataset.adminProjectCategory;
      adminState.projectYear = '';
      adminEls.projectCategoryList.querySelectorAll('.category-button').forEach((item) => item.classList.remove('active'));
      target.classList.add('active');
      adminEls.projectYear.value = '';
      loadProjectManagementView();
    }
    if (target.dataset.openProjectDetail) {
      openProjectDetail(target.dataset.openProjectDetail).catch((error) => window.alert(error.message));
    }
    if (target.dataset.backProjectList !== undefined) {
      showProjectListView();
    }
    if (target.dataset.editProject) {
      const project = findAdminProject(target.dataset.editProject);
      if (project) openProjectModal(project);
    }
    if (target.dataset.editProjectMembers) {
      const project = findAdminProject(target.dataset.editProjectMembers);
      if (project) openProjectMembersModal(project);
    }
    if (target.dataset.editProjectUpdates) {
      const project = findAdminProject(target.dataset.editProjectUpdates);
      if (project) openProjectUpdatesModal(project);
    }
    if (target.dataset.exportProject) {
      downloadAdminJson(
        `/admin/projects/${target.dataset.exportProject}/export`,
        `nethub-project-${target.dataset.exportProject}.json`,
      ).catch((error) => window.alert(error.message));
    }
    if (target.dataset.adminResourceCategory !== undefined) {
      selectResourceCategory(target.dataset.adminResourceCategory);
      loadResourceManagementView();
    }
    if (target.dataset.editResource) {
      openResourceModal(adminState.resources.find((item) => String(item.id) === target.dataset.editResource));
    }
    if (target.dataset.exportResource) {
      downloadAdminJson(
        `/admin/resources/${target.dataset.exportResource}/export`,
        `nethub-resource-${target.dataset.exportResource}.json`,
      ).catch((error) => window.alert(error.message));
    }
    if (target.dataset.deleteResourceFromModal) {
      deleteResource(target.dataset.deleteResourceFromModal)
        .then((deleted) => {
          if (deleted) closeAdminModal();
        })
        .catch((error) => window.alert(error.message));
    }
    if (target.dataset.deleteResource) deleteResource(target.dataset.deleteResource);
    if (target.dataset.deleteActivityFromModal) {
      deleteActivity(target.dataset.deleteActivityFromModal)
        .then((deleted) => {
          if (deleted) closeAdminModal();
        })
        .catch((error) => window.alert(error.message));
    }
    if (target.dataset.adminActivityId !== undefined) {
      adminState.selectedActivity = target.dataset.adminActivityId ? Number(target.dataset.adminActivityId) : null;
      renderAdminPhotos(adminState.activities).catch((error) => window.alert(error.message));
    }
    if (target.dataset.adminActivityCardId) {
      adminState.selectedActivity = Number(target.dataset.adminActivityCardId);
      if (!isPhotoResourceCategory()) {
        selectResourceCategory('photos');
        loadResourceManagementView();
      } else {
        renderAdminPhotos(adminState.activities).catch((error) => window.alert(error.message));
      }
    }
    if (target.dataset.photoIndex) {
      openAdminPhotoModal(Number(target.dataset.photoIndex));
    }
    if (target.dataset.editActivity) {
      openActivityModal(adminState.activities.find((item) => String(item.id) === target.dataset.editActivity));
    }
    if (target.dataset.exportPhotoActivity) {
      downloadAdminJson(
        `/admin/photo-activities/${target.dataset.exportPhotoActivity}/export`,
        `nethub-photo-activity-${target.dataset.exportPhotoActivity}.json`,
      ).catch((error) => window.alert(error.message));
    }
    if (target.dataset.deleteActivity) deleteActivity(target.dataset.deleteActivity);
  });

  document.addEventListener('change', (event) => {
    if (!event.target.matches('[data-project-update-photos]')) return;
    const count = event.target.files?.length || 0;
    const label = event.target.closest('[data-project-update-editor-item]')
      ?.querySelector('[data-project-update-photo-count]');
    if (label) label.textContent = count ? `已选择 ${count} 张新照片` : '尚未选择新照片';
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !adminEls.resourceAdvancedFilters.hidden && !adminEls.photoModal.classList.contains('is-open')) {
      setAdminResourceFilterPanelOpen(false);
      adminEls.resourceFilterToggle.focus();
    }
    if (!adminEls.photoModal.classList.contains('is-open')) return;
    if (event.key === 'Escape') {
      closeAdminPhotoModal();
    }
    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      shiftAdminPhotoModal(-1);
    }
    if (event.key === 'ArrowRight') {
      event.preventDefault();
      shiftAdminPhotoModal(1);
    }
  });
}

async function initAdmin() {
  Object.assign(adminEls, {
    status: adminQuery('#adminStatus'),
    gate: adminQuery('#adminGate'),
    workspace: adminQuery('#adminWorkspace'),
    adminLogout: adminQuery('#adminLogout'),
    modal: adminQuery('#adminModal'),
    modalTitle: adminQuery('#adminModalTitle'),
    modalForm: adminQuery('#adminModalForm'),
    filePickerModal: adminQuery('#filePickerModal'),
    filePickerTitle: adminQuery('#filePickerTitle'),
    pickCurrentFolder: adminQuery('#pickCurrentFolder'),
    fileUpButton: adminQuery('#fileUpButton'),
    filePathLabel: adminQuery('#filePathLabel'),
    fileTable: adminQuery('#fileTable'),
    uploadTargetLabel: adminQuery('#uploadTargetLabel'),
    folderName: adminQuery('#adminFolderName'),
    createFolderButton: adminQuery('#adminCreateFolderButton'),
    uploadInput: adminQuery('#adminUploadInput'),
    uploadButton: adminQuery('#adminUploadButton'),
    folderUploadInput: adminQuery('#adminFolderUploadInput'),
    folderUploadButton: adminQuery('#adminFolderUploadButton'),
    uploadMessage: adminQuery('#adminUploadMessage'),
    exportAllDataButton: adminQuery('#exportAllDataButton'),
    downloadDataTemplateButton: adminQuery('#downloadDataTemplateButton'),
    dataImportInput: adminQuery('#dataImportInput'),
    previewDataImportButton: adminQuery('#previewDataImportButton'),
    confirmDataImportButton: adminQuery('#confirmDataImportButton'),
    dataImportResult: adminQuery('#dataImportResult'),
    createUserButton: adminQuery('#createUserButton'),
    refreshUsers: adminQuery('#refreshUsers'),
    userSearch: adminQuery('#userSearch'),
    userRoleFilter: adminQuery('#userRoleFilter'),
    userActiveFilter: adminQuery('#userActiveFilter'),
    usersTable: adminQuery('#usersTable'),
    messageReportsTable: adminQuery('#messageReportsTable'),
    createAnnouncementButton: adminQuery('#createAnnouncementButton'),
    refreshCommunity: adminQuery('#refreshCommunity'),
    announcementsTable: adminQuery('#announcementsTable'),
    commentReportsTable: adminQuery('#commentReportsTable'),
    createProjectButton: adminQuery('#createProjectButton'),
    projectSearch: adminQuery('#projectAdminSearch'),
    projectYear: adminQuery('#adminProjectYear'),
    projectSort: adminQuery('#adminProjectSort'),
    projectCategoryList: adminQuery('#adminProjectCategoryList'),
    projectCount: adminQuery('#adminProjectCount'),
    projectListView: adminQuery('#adminProjectListView'),
    projectDetailView: adminQuery('#adminProjectDetailView'),
    projectList: adminQuery('#adminProjectList'),
    createResourceButton: adminQuery('#createResourceButton'),
    resourceSearch: adminQuery('#resourceAdminSearch'),
    resourceFilterToggle: adminQuery('#adminResourceFilterToggle'),
    resourceAdvancedFilters: adminQuery('#adminResourceAdvancedFilters'),
    resourceFilterCount: adminQuery('#adminResourceFilterCount'),
    clearResourceFilters: adminQuery('#clearAdminResourceFilters'),
    resourceSort: adminQuery('#adminResourceSort'),
    resourceYear: adminQuery('#adminResourceYear'),
    resourceCategoryList: adminQuery('#adminResourceCategoryList'),
    resourceCount: adminQuery('#adminResourceCount'),
    resourceView: adminQuery('#adminResourceView'),
    resourcesTable: adminQuery('#resourcesTable'),
    createActivityButton: adminQuery('#createActivityButton'),
    photoFilters: adminQuery('#adminPhotoFilters'),
    photoView: adminQuery('#adminPhotoView'),
    activityList: adminQuery('#adminActivityList'),
    photoTitle: adminQuery('#adminPhotoTitle'),
    photoMeta: adminQuery('#adminPhotoMeta'),
    editCurrentActivityButton: adminQuery('#editCurrentActivityButton'),
    downloadActivity: adminQuery('#downloadActivity'),
    activitiesTable: adminQuery('#activitiesTable'),
    photoModal: adminQuery('#adminPhotoModal'),
    photoModalTitle: adminQuery('#adminModalPhotoTitle'),
    photoModalMeta: adminQuery('#adminModalPhotoMeta'),
    photoModalImage: adminQuery('#adminModalPhotoImage'),
    photoModalDownload: adminQuery('#adminModalPhotoDownload'),
    photoModalPrev: adminQuery('#adminModalPhotoPrev'),
    photoModalNext: adminQuery('#adminModalPhotoNext'),
  });
  bindAdminEvents();
  const ok = await requireAdmin();
  if (ok) await loadUsers();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initAdmin);
} else {
  initAdmin();
}
