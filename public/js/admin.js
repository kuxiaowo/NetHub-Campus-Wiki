const adminState = {
  currentUser: null,
  view: 'users',
  filePath: '',
  fileItems: [],
  picker: null,
  users: [],
  projectMetaLoaded: false,
  projectCategory: '',
  projectYear: '',
  projectSort: 'latest',
  projectCategories: [],
  projectYears: [],
  projects: [],
  currentProject: null,
  projectMediaDragItem: null,
  projectMediaOrderChanged: false,
  resourceMetaLoaded: false,
  resourceCategory: '',
  resourceYear: '',
  resourceSort: 'hot',
  resources: [],
  activities: [],
  activePhotoItems: [],
  selectedActivity: null,
  currentActivity: null,
  currentYearbook: null,
  currentYearbookPage: 0,
  currentModalPhoto: null,
  currentModalIndex: -1,
  dragState: null,
  modalDragItem: null,
  dragJustEnded: false,
  dbTables: [],
  dbTable: null,
  dbSchema: [],
  dbRows: [],
  dbPage: 1,
  dbPageSize: 50,
  dbTotal: 0,
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

function dbDisplayValue(value) {
  if (value === null || value === undefined || value === '') return 'NULL';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function dbCellValue(value) {
  return dbDisplayValue(value);
}

function adminNumber(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function adminEndpoint(path, options = {}) {
  return request(path, options);
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
  if (type === 'resource-category') {
    await adminEndpoint('/admin/resource-categories/reorder', {
      method: 'PATCH',
      body: JSON.stringify(sortablePayload(type)),
    });
    adminState.resourceMetaLoaded = false;
    await loadResourceAdminMeta();
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

function moveProjectMediaItem(target) {
  const source = adminState.projectMediaDragItem;
  if (!source || !target || source === target) return;
  const position = source.compareDocumentPosition(target);
  if (position & Node.DOCUMENT_POSITION_FOLLOWING) {
    target.after(source);
  } else {
    target.before(source);
  }
  adminState.projectMediaOrderChanged = true;
}

function bindSortableLists() {
  document.addEventListener('dragstart', (event) => {
    const item = event.target.closest('[data-project-media-item]');
    if (!item) return;
    adminState.projectMediaDragItem = item;
    adminState.projectMediaOrderChanged = false;
    item.classList.add('is-dragging');
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', item.dataset.projectMediaUrl || '');
  });

  document.addEventListener('dragover', (event) => {
    const item = event.target.closest('[data-project-media-item]');
    if (!adminState.projectMediaDragItem || !item) return;
    event.preventDefault();
    moveProjectMediaItem(item);
  });

  document.addEventListener('drop', (event) => {
    const item = event.target.closest('[data-project-media-item]');
    if (!adminState.projectMediaDragItem || !item) return;
    event.preventDefault();
  });

  document.addEventListener('dragend', () => {
    if (!adminState.projectMediaDragItem) return;
    adminState.projectMediaDragItem.classList.remove('is-dragging');
    adminState.projectMediaDragItem = null;
    if (adminState.projectMediaOrderChanged) saveProjectMediaOrder();
  });

  document.addEventListener('dragstart', (event) => {
    const item = event.target.closest('[data-sortable-list-item]');
    if (!item) return;
    adminState.modalDragItem = item;
    item.classList.add('is-dragging');
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', 'media');
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
      if (type === 'resource-category') {
        adminState.resourceMetaLoaded = false;
        await loadResourceAdminMeta();
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
      if (state.type === 'resource-category') {
        adminState.resourceMetaLoaded = false;
        await loadResourceAdminMeta();
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
          ? `<button class="button secondary compact" type="button" data-browse-target="${adminText(field.name)}" data-browse-mode="${adminText(field.browse)}">浏览</button>`
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
        ? `<button class="button secondary compact" type="button" data-browse-target="${adminText(field.name)}" data-browse-mode="${adminText(field.browse)}">浏览</button>`
        : '';
      return `
        <label>
          <span>${adminText(field.label)}</span>
          <div class="admin-input-row">
            <input class="input" name="${adminText(field.name)}" type="${adminText(field.type || 'text')}" value="${adminText(value)}" ${field.required ? 'required' : ''}>
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
      const canChoose = selectable
        && ((row.type === 'file' && mode !== 'folder') || (row.type === 'folder' && mode !== 'file'));
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

async function uploadToCurrentDirectory() {
  const file = adminEls.uploadInput.files?.[0];
  const message = adminEls.uploadMessage;
  if (!file) {
    message.textContent = '请选择文件';
    message.classList.add('error');
    return;
  }
  message.textContent = '正在上传...';
  message.classList.remove('error');
  try {
    const body = new FormData();
    body.append('file', file);
    body.append('targetPath', adminState.filePath);
    const result = await adminEndpoint('/admin/uploads', { method: 'POST', body });
    message.textContent = `上传完成：${result.url}`;
    adminEls.uploadInput.value = '';
    await loadFiles(adminState.filePath);
  } catch (error) {
    message.textContent = error.message;
    message.classList.add('error');
  }
}

async function openFilePicker(inputName, mode) {
  adminState.picker = {
    target: adminEls.modalForm.elements[inputName],
    mode,
    path: '',
    items: [],
  };
  adminEls.filePickerTitle.textContent = mode === 'file'
    ? '选择文件'
    : (mode === 'folder' ? '选择文件夹' : '选择文件或文件夹');
  adminEls.pickCurrentFolder.classList.toggle('is-hidden', mode === 'file');
  adminEls.filePickerModal.classList.add('is-open');
  adminEls.filePickerModal.setAttribute('aria-hidden', 'false');
  await loadPickerFiles('');
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
  if (target?.tagName === 'TEXTAREA') {
    const currentValue = target.value.trimEnd();
    target.value = currentValue ? `${currentValue}\n${url}` : url;
  } else if (target) {
    target.value = url;
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
    item.classList.toggle('active', item.dataset.adminView === view);
  });
  document.querySelectorAll('[data-admin-panel]').forEach((item) => {
    item.classList.toggle('active', item.dataset.adminPanel === view);
  });
  if (view === 'users') loadUsers();
  if (view === 'files') loadFiles();
  if (view === 'projects') loadProjectManagementView();
  if (view === 'resources') loadResourceManagementView();
  if (view === 'database') loadDbTables();
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
    { name: 'password', label: '密码', type: 'password', required: true },
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
            <span>负责人：${adminText(project.leader)}</span>
            <span>成员：${adminText(project.members)}</span>
          </div>
          <p>${adminText(project.description)}</p>
          ${casTags(project.cas)}
        </div>
      </button>
      <button class="button compact" type="button" data-edit-project="${adminText(project.id)}">编辑</button>
    </article>
  `;
}

function adminProjectMediaItem(url) {
  const safeUrl = safeExternalUrl(url);
  const escapedUrl = adminText(url);
  const isImage = /\.(png|jpe?g|webp|gif)$/i.test(url) || url.includes('picsum.photos');
  const media = isImage
    ? `<img src="${adminText(safeUrl)}" alt="项目媒体" loading="lazy">`
    : `<a class="link-card" href="${adminText(safeUrl)}" target="_blank" rel="noreferrer">打开媒体链接：${escapedUrl}</a>`;
  return `
    <div class="admin-project-media-item" draggable="true" data-project-media-item data-project-media-url="${escapedUrl}">
      <span class="admin-sortable-list-handle">拖动</span>
      ${media}
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
        <button class="button compact" type="button" data-edit-project="${adminText(project.id)}">编辑项目</button>
      </div>
    </div>
    <div class="detail-head">
      ${projectIconImage(project)}
      <div>
        <h1>${adminText(project.name)}</h1>
        <div class="meta">
          <span class="badge">${adminText(project.category)}</span>
          <span>${adminText(project.year)}</span>
          <span>负责人：${adminText(project.leader)}</span>
          <span>成员：${adminText(project.members)}</span>
        </div>
        ${casTags(project.cas)}
      </div>
    </div>
    <section>
      <h2>项目简介</h2>
      <p>${adminText(project.description)}</p>
    </section>
    <section>
      <div class="admin-media-toolbar">
        <h2>照片 / 视频</h2>
        <span class="admin-media-note">拖动后自动保存</span>
      </div>
      <div id="adminProjectMediaList" class="media-grid admin-project-media-grid">
        ${(project.media || []).length ? project.media.map(adminProjectMediaItem).join('') : '<div class="empty">暂无媒体资料</div>'}
      </div>
      <div id="adminProjectMediaMessage" class="auth-message" aria-live="polite"></div>
    </section>
    <section>
      <h2>项目动态</h2>
      <ul class="update-list">
        ${(project.updates || []).map((item) => `<li>${adminText(item)}</li>`).join('') || '<li>暂无动态</li>'}
      </ul>
    </section>
  `;
}

function findAdminProject(projectId) {
  return adminState.projects.find((item) => String(item.id) === String(projectId))
    || (String(adminState.currentProject?.id) === String(projectId) ? adminState.currentProject : null);
}

async function saveProjectMediaOrder() {
  if (!adminState.currentProject) return;
  const media = [...adminEls.projectDetailView.querySelectorAll('[data-project-media-item]')]
    .map((item) => item.dataset.projectMediaUrl)
    .filter(Boolean);
  const message = adminQuery('#adminProjectMediaMessage');
  if (message) {
    message.textContent = '正在保存媒体顺序...';
    message.classList.remove('error');
  }
  try {
    const updated = await adminEndpoint(`/admin/projects/${adminState.currentProject.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ media }),
    });
    adminState.projectMediaOrderChanged = false;
    adminState.currentProject = updated;
    adminState.projects = adminState.projects.map((item) => item.id === updated.id ? updated : item);
    showProjectDetailView(updated);
    const nextMessage = adminQuery('#adminProjectMediaMessage');
    if (nextMessage) nextMessage.textContent = '媒体顺序已自动保存';
  } catch (error) {
    if (message) {
      message.textContent = error.message;
      message.classList.add('error');
    }
  }
}

function projectFields(project = {}) {
  return [
    { name: 'name', label: '项目名称', value: project.name, required: true },
    { name: 'leader', label: '负责人', value: project.leader, required: true },
    { name: 'members', label: '成员', value: project.members, required: true },
    { name: 'category', label: '分类', value: project.category, required: true },
    { name: 'year', label: '年份', value: project.year || new Date().getFullYear(), type: 'number', required: true },
    { name: 'icon', label: '图标 URL', value: project.icon || '', browse: 'file' },
    { name: 'description', label: '简介', value: project.description, type: 'textarea', required: true },
    { name: 'media', label: '媒体 URL（一行一个）', value: (project.media || []).join('\n'), type: 'textarea', browse: 'file' },
    { name: 'casCreativity', label: 'CAS Creativity', value: project.cas?.creativity, type: 'checkbox' },
    { name: 'casActivity', label: 'CAS Activity', value: project.cas?.activity, type: 'checkbox' },
    { name: 'casService', label: 'CAS Service', value: project.cas?.service, type: 'checkbox' },
    { name: 'popularity', label: '热度', value: project.popularity || 0, type: 'number' },
    { name: 'updates', label: '动态（一行一个）', value: (project.updates || []).join('\n'), type: 'textarea' },
  ];
}

function openProjectModal(project = {}) {
  const isEdit = Boolean(project?.id);
  openAdminModal(isEdit ? '编辑 CAS 项目' : '新建 CAS 项目', projectFields(project), async (payload) => {
    payload.media = linesToList(payload.media);
    payload.updates = linesToList(payload.updates);
    const saved = await adminEndpoint(isEdit ? `/admin/projects/${project.id}` : '/admin/projects', {
      method: isEdit ? 'PATCH' : 'POST',
      body: JSON.stringify(payload),
    });
    adminState.projectMetaLoaded = false;
    await loadProjectAdminMeta();
    await loadAdminProjects();
    if (isEdit) {
      showProjectDetailView(saved);
    } else {
      showProjectListView();
    }
  });
}

async function loadResourceAdminMeta() {
  if (adminState.resourceMetaLoaded) return;
  const [meta, adminCategories] = await Promise.all([
    adminEndpoint('/resources/meta'),
    adminEndpoint('/admin/resource-categories'),
  ]);
  meta.categories = adminCategories.data.filter((category) => category.isActive);
  if (!meta.categories.some((category) => category.value === 'photos')) {
    meta.categories.push({ value: 'photos', label: '活动照片', sortOrder: 20 });
  }
  const categories = [
    { value: '', label: '全部资源' },
    ...meta.categories,
  ];
  adminEls.resourceCategoryList.innerHTML = categories.map((category) => `
    <button
      class="category-button ${category.value === adminState.resourceCategory ? 'active' : ''}"
      type="button"
      data-admin-resource-category="${adminText(category.value)}"
      ${category.id ? `data-sortable="resource-category" data-sortable-id="${adminText(category.id)}" draggable="true"` : ''}
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
  const options = isPhotoResourceCategory()
    ? [
      { value: 'hot', label: '最热' },
      { value: 'new', label: '最新' },
      { value: 'photoCount', label: '照片最多' },
      { value: 'old', label: '最早' },
    ]
    : [
      { value: 'hot', label: '最热' },
      { value: 'new', label: '最新' },
      { value: 'download', label: '下载最多' },
      { value: 'old', label: '最早' },
    ];
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
  adminEls.createResourceButton.classList.toggle('is-hidden', isPhotoMode);
  adminEls.createActivityButton.classList.toggle('is-hidden', !isPhotoMode);
  adminEls.photoFilters.classList.toggle('is-visible', isPhotoMode);
  adminEls.resourceView.classList.toggle('is-hidden', isPhotoMode);
  adminEls.photoView.classList.toggle('is-visible', isPhotoMode);
  adminEls.yearbookView.classList.remove('is-visible');
  adminEls.resourceSearch.placeholder = isPhotoMode ? '搜索活动名称' : '搜索名称、内容、简介';
  if (isPhotoMode) {
    await loadActivities();
    return;
  }
  adminState.selectedActivity = null;
  adminState.currentActivity = null;
  adminState.currentYearbook = null;
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
    const combined = [
      ...adminState.resources.map((item) => ({ kind: 'resource', data: item })),
      ...adminState.activities.map((item) => ({ kind: 'activity', data: item })),
    ];
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
}

function resourceAdminCard(resource) {
  const image = safeExternalUrl(resource.image);
  const resourceUrl = safeExternalUrl(resource.resourceUrl);
  const isYearbook = resource.category === 'yearbook';
  const thumb = `
    <span class="resource-thumb">
      <img src="${image}" alt="${adminText(resource.title)}" loading="lazy">
      <span class="badge">${adminText(resource.label)}</span>
    </span>
  `;
  return `
    <article class="resource-card admin-resource-card">
      ${isYearbook
        ? `<button class="resource-card-link" type="button" data-admin-yearbook-resource-id="${adminText(resource.id)}">${thumb}</button>`
        : `<a class="resource-card-link" href="${resourceUrl}" target="_blank" rel="noopener noreferrer">${thumb}</a>`}
      <div class="resource-body">
        <div class="admin-card-title-row">
          <h2>${adminText(resource.title)}</h2>
          <button class="button compact" type="button" data-edit-resource="${adminText(resource.id)}">编辑</button>
        </div>
        <p>${adminText(resource.description)}</p>
        <div class="meta">
          <span>${adminText(resource.year)}</span>
          <span>热度 ${adminText(resource.hot)}</span>
          <span>下载 ${adminText(resource.downloads)}</span>
        </div>
      </div>
    </article>
  `;
}

async function openAdminYearbook(resourceId) {
  adminEls.resourceView.classList.add('is-hidden');
  adminEls.photoView.classList.remove('is-visible');
  adminEls.yearbookView.classList.add('is-visible');
  adminState.currentYearbook = null;
  adminState.currentYearbookPage = 0;
  adminEls.yearbookTitle.textContent = 'Yearbook';
  adminEls.yearbookMeta.textContent = '正在加载 Yearbook...';
  adminEls.yearbookPages.innerHTML = '<div class="empty">正在加载 Yearbook...</div>';
  setAdminYearbookDownload(null);
  updateAdminYearbookControls();

  try {
    const result = await adminEndpoint(`/resources/${resourceId}/yearbook?track=false`);
    adminState.currentYearbook = result.data;
    adminState.currentYearbookPage = 0;
    renderAdminYearbook();
  } catch (error) {
    adminEls.yearbookMeta.textContent = 'Yearbook 加载失败';
    adminEls.yearbookPages.innerHTML = `<div class="empty error">${adminText(error.message)}</div>`;
  }
}

function setAdminYearbookDownload(pdfUrl) {
  if (!pdfUrl) {
    adminEls.yearbookDownload.href = '#';
    adminEls.yearbookDownload.removeAttribute('download');
    adminEls.yearbookDownload.setAttribute('aria-disabled', 'true');
    adminEls.yearbookDownload.classList.add('disabled');
    return;
  }
  adminEls.yearbookDownload.href = authenticatedPublicFileUrl(pdfUrl) || safeExternalUrl(pdfUrl);
  adminEls.yearbookDownload.download = `${adminState.currentYearbook?.resource?.title || 'yearbook'}.pdf`;
  adminEls.yearbookDownload.removeAttribute('aria-disabled');
  adminEls.yearbookDownload.classList.remove('disabled');
}

function renderAdminYearbook() {
  const yearbook = adminState.currentYearbook;
  if (!yearbook) return;
  const { resource, pages, pdfUrl } = yearbook;
  const start = adminState.currentYearbookPage;
  const visiblePages = pages.slice(start, start + 2);

  adminEls.yearbookTitle.textContent = resource.title;
  adminEls.yearbookMeta.textContent = `${resource.year} · ${pages.length} 页 · 第 ${start + 1}-${Math.min(start + visiblePages.length, pages.length)} 页 · 热度 ${resource.hot} · 下载 ${resource.downloads}`;
  setAdminYearbookDownload(pdfUrl);
  adminState.activePhotoItems = pages.map((page, index) => ({
    ...page,
    activity: resource.title,
    year: resource.year,
    index,
  }));
  adminEls.yearbookPages.innerHTML = visiblePages.map((page) => `
    <figure class="yearbook-page">
      <button class="yearbook-page-button" type="button" data-admin-yearbook-page-index="${adminText(page.index - 1)}" aria-label="查看 ${adminText(page.title)}">
        <img src="${safeExternalUrl(page.thumbSrc || page.src)}" alt="${adminText(resource.title)} ${adminText(page.title)}" loading="eager">
      </button>
      <figcaption>${adminText(page.index)} / ${adminText(pages.length)}</figcaption>
    </figure>
  `).join('');
  if (visiblePages.length === 1) {
    adminEls.yearbookPages.insertAdjacentHTML('beforeend', '<div class="yearbook-page-placeholder">本组只有一页</div>');
  }
  updateAdminYearbookControls();
}

function updateAdminYearbookControls() {
  const pageCount = adminState.currentYearbook?.pages?.length || 0;
  adminEls.yearbookPrev.disabled = adminState.currentYearbookPage <= 0;
  adminEls.yearbookNext.disabled = !pageCount || adminState.currentYearbookPage + 2 >= pageCount;
}

function shiftAdminYearbook(direction) {
  if (!adminState.currentYearbook) return;
  const maxStart = Math.max(0, Math.floor((adminState.currentYearbook.pages.length - 1) / 2) * 2);
  adminState.currentYearbookPage = Math.min(Math.max(adminState.currentYearbookPage + direction * 2, 0), maxStart);
  renderAdminYearbook();
}

function closeAdminYearbook() {
  adminState.currentYearbook = null;
  adminState.currentYearbookPage = 0;
  adminEls.yearbookView.classList.remove('is-visible');
  adminEls.resourceView.classList.remove('is-hidden');
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
  return [
    { name: 'title', label: '标题', value: resource.title, required: true },
    { name: 'description', label: '简介', value: resource.description, type: 'textarea' },
    { name: 'year', label: '年份', value: resource.year || new Date().getFullYear(), type: 'number', required: true },
    {
      name: 'category',
      label: '分类',
      value: category,
      type: 'select',
      required: true,
      options: categoryOptions,
    },
    { name: 'hot', label: '热度', value: resource.hot || 0, type: 'number' },
    { name: 'downloads', label: '下载数', value: resource.downloads || 0, type: 'number' },
    ...(isYearbook ? [] : [{ name: 'image', label: '封面 URL', value: resource.image, required: true, browse: 'file' }]),
    {
      name: 'resourceUrl',
      label: isYearbook ? 'Yearbook 目录' : '资源 URL',
      value: resource.resourceUrl,
      required: true,
      browse: isYearbook ? 'folder' : 'fileOrFolder',
    },
  ];
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
      if (categorySelect.value === 'yearbook') {
        const selectedCategory = resourceCategoryOptions().find((category) => category.value === categorySelect.value);
        closeAdminModal();
        setTimeout(() => openResourceModal({ category: categorySelect.value, label: selectedCategory?.label }), 0);
        return;
      }
      if (categorySelect.value !== 'photos') return;
      closeAdminModal();
      selectResourceCategory('photos');
      loadResourceManagementView()
        .then(() => openActivityModal({}))
        .catch((error) => window.alert(error.message));
    });
  }
  if (isEdit) {
    const actions = adminEls.modalForm.querySelector('.admin-modal-actions');
    if (actions) {
      actions.insertAdjacentHTML(
        'afterbegin',
        `<button class="button secondary danger" type="button" data-delete-resource-from-modal="${adminText(resource.id)}">删除资源</button>`,
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
  const image = safeExternalUrl(item.thumbSrc || item.src);
  return `
    <button class="photo-item" type="button" data-photo-index="${adminText(item.index)}" aria-label="查看 ${adminText(item.title)}">
      <img src="${image}" alt="${adminText(item.title)}" loading="lazy" decoding="async">
    </button>
  `;
}

function photoActivityCard(activity) {
  const cover = activityCoverImage(activity);
  const image = cover ? `<img src="${safeExternalUrl(cover)}" alt="${adminText(activity.activity)}" loading="lazy">` : '';
  return `
    <article class="resource-card photo-activity-card admin-photo-activity-card">
      <button class="admin-photo-activity-open" type="button" data-admin-activity-card-id="${adminText(activity.id)}">
        <span class="resource-thumb">
          ${image}
          <span class="badge">${adminText(activity.year)}</span>
        </span>
        <span class="resource-body">
          <h2>${adminText(activity.activity)}</h2>
          <p>${adminText(activity.description)}</p>
          <span class="meta">
            <span>${adminText(activityPhotoCount(activity))} 张照片</span>
            <span>热度 ${adminText(activity.hot)}</span>
            <span>下载 ${adminText(activity.downloads || 0)}</span>
          </span>
        </span>
      </button>
      <div class="admin-card-edit-row">
        <button class="button compact" type="button" data-edit-activity="${adminText(activity.id)}">编辑</button>
      </div>
    </article>
  `;
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
    { name: 'hot', label: '热度', value: activity.hot || 0, type: 'number' },
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
        `<button class="button secondary danger" type="button" data-delete-activity-from-modal="${adminText(activity.id)}">删除活动</button>`,
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

async function loadDbTables() {
  if (adminState.dbTables.length) return;
  const result = await adminEndpoint('/admin/db/tables');
  adminState.dbTables = result.data;
  adminEls.dbTableList.innerHTML = result.data.map((table) => `
    <button class="category-button" type="button" data-db-table="${adminText(table.name)}">${adminText(table.name)}</button>
  `).join('');
}

async function selectDbTable(table) {
  adminState.dbTable = table;
  adminState.dbPage = 1;
  document.querySelectorAll('[data-db-table]').forEach((item) => {
    item.classList.toggle('active', item.dataset.dbTable === table);
  });
  const schema = await adminEndpoint(`/admin/db/tables/${encodeURIComponent(table)}/schema`);
  adminState.dbSchema = schema.data;
  adminEls.createDbRowButton.disabled = table === 'users';
  await loadDbRows();
}

async function loadDbRows() {
  if (!adminState.dbTable) return;
  const query = buildQuery({ page: adminState.dbPage, pageSize: adminState.dbPageSize });
  const result = await adminEndpoint(`/admin/db/tables/${encodeURIComponent(adminState.dbTable)}/rows${query}`);
  adminState.dbRows = result.data;
  adminState.dbTotal = result.total;
  adminEls.dbTableMeta.textContent = `${adminState.dbTable} · 第 ${result.page} 页 · 共 ${result.total} 行`;
  const columns = adminState.dbSchema.map((column) => ({
    key: column.name,
    label: column.readonly ? `${column.name} *` : column.name,
    render: (row) => {
      const value = dbCellValue(row[column.name]);
      return `
        <button
          class="admin-db-cell"
          type="button"
          title="${adminText(value)}"
          data-db-cell-row="${adminText(row.id)}"
          data-db-cell-column="${adminText(column.name)}"
        >
          <span>${adminText(value)}</span>
        </button>
      `;
    },
  }));
  adminEls.dbRowsTable.innerHTML = `<div class="admin-db-table-scroll">${
    renderAdminTable(
    columns,
    adminState.dbRows,
    (row) => `
      <button class="button secondary compact" type="button" data-edit-db-row="${adminText(row.id)}">编辑</button>
      <button class="button secondary compact danger" type="button" data-delete-db-row="${adminText(row.id)}">删除</button>
    `,
    )
  }</div>`;
  const table = adminEls.dbRowsTable.querySelector('.admin-table');
  if (table) {
    table.classList.add('admin-db-table');
    table.style.minWidth = `${adminState.dbSchema.length * 120 + 100}px`;
  }
}

function dbFields(row = {}) {
  return adminState.dbSchema
    .filter((column) => !column.readonly)
    .map((column) => ({
      name: column.name,
      label: `${column.name} (${column.columnType})`,
      value: row[column.name] ?? '',
      type: ['text', 'varchar', 'enum', 'timestamp'].includes(column.dataType) ? 'text' : 'textarea',
    }));
}

function openDbRowModal(row) {
  const isEdit = Boolean(row?.id);
  openAdminModal(isEdit ? '编辑记录' : '新增记录', dbFields(row), async (payload) => {
    const body = {};
    Object.entries(payload).forEach(([key, value]) => {
      body[key] = value === '' ? null : value;
    });
    await adminEndpoint(
      isEdit
        ? `/admin/db/tables/${encodeURIComponent(adminState.dbTable)}/rows/${row.id}`
        : `/admin/db/tables/${encodeURIComponent(adminState.dbTable)}/rows`,
      {
        method: isEdit ? 'PATCH' : 'POST',
        body: JSON.stringify(body),
      },
    );
    await loadDbRows();
  });
}

function openDbCellModal(rowId, columnName) {
  const row = adminState.dbRows.find((item) => String(item.id) === String(rowId));
  const column = adminState.dbSchema.find((item) => item.name === columnName);
  if (!row || !column) return;

  const rawValue = row[column.name];
  const value = rawValue ?? '';
  const readonly = Boolean(column.readonly);
  adminEls.modalTitle.textContent = `${adminState.dbTable}.${column.name}`;
  adminEls.modalForm.innerHTML = `
    <div class="admin-db-cell-detail">
      <div>
        <span>字段类型</span>
        <strong>${adminText(column.columnType || column.dataType || 'unknown')}</strong>
      </div>
      <div>
        <span>记录 ID</span>
        <strong>${adminText(row.id)}</strong>
      </div>
    </div>
    <label>
      <span>${readonly ? '详细内容（只读）' : '详细内容（可编辑）'}</span>
      <textarea class="input admin-db-cell-editor" name="value" rows="12" ${readonly ? 'readonly' : ''}>${adminText(value)}</textarea>
    </label>
    <div id="adminModalMessage" class="auth-message"></div>
    <div class="admin-modal-actions">
      <button class="button secondary" type="button" data-admin-modal-close>取消</button>
      ${readonly ? '' : '<button class="button" type="submit">保存</button>'}
    </div>
  `;
  adminEls.modal.classList.add('is-open');
  adminEls.modal.setAttribute('aria-hidden', 'false');
  adminEls.modalForm.onsubmit = async (event) => {
    event.preventDefault();
    if (readonly) return;
    const formData = new FormData(adminEls.modalForm);
    const nextValue = formData.get('value');
    await adminEndpoint(`/admin/db/tables/${encodeURIComponent(adminState.dbTable)}/rows/${row.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ [column.name]: nextValue === '' ? null : nextValue }),
    });
    closeAdminModal();
    await loadDbRows();
  };
}

async function deleteDbRow(id) {
  if (!window.confirm('确认删除这条数据库记录？')) return;
  await adminEndpoint(`/admin/db/tables/${encodeURIComponent(adminState.dbTable)}/rows/${id}`, {
    method: 'DELETE',
  });
  await loadDbRows();
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
  adminEls.fileUpButton.addEventListener('click', () => loadFiles(parentPublicPath(adminState.filePath)));
  adminEls.uploadButton.addEventListener('click', uploadToCurrentDirectory);

  adminEls.createUserButton.addEventListener('click', () => openUserModal({ isActive: true, role: 'user' }));
  adminEls.refreshUsers.addEventListener('click', loadUsers);
  adminEls.userSearch.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') loadUsers();
  });
  adminEls.userRoleFilter.addEventListener('change', loadUsers);
  adminEls.userActiveFilter.addEventListener('change', loadUsers);

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
  adminEls.refreshResources.addEventListener('click', loadResourceManagementView);
  adminEls.resourceSearch.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') loadResourceManagementView();
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
  adminEls.backToResourcesButton.addEventListener('click', closeAdminYearbook);
  adminEls.editCurrentYearbookButton.addEventListener('click', () => {
    if (adminState.currentYearbook?.resource) openResourceModal(adminState.currentYearbook.resource);
  });
  adminEls.yearbookPrev.addEventListener('click', () => shiftAdminYearbook(-1));
  adminEls.yearbookNext.addEventListener('click', () => shiftAdminYearbook(1));
  adminEls.yearbookDownload.addEventListener('click', (event) => {
    if (adminEls.yearbookDownload.getAttribute('aria-disabled') === 'true') {
      event.preventDefault();
      return;
    }
    if (!requireAuthForDownload()) {
      event.preventDefault();
    }
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
  adminEls.createDbRowButton.addEventListener('click', () => openDbRowModal({}));
  adminEls.dbPrevPage.addEventListener('click', () => {
    if (adminState.dbPage > 1) {
      adminState.dbPage -= 1;
      loadDbRows();
    }
  });
  adminEls.dbNextPage.addEventListener('click', () => {
    if (adminState.dbPage * adminState.dbPageSize < adminState.dbTotal) {
      adminState.dbPage += 1;
      loadDbRows();
    }
  });

  document.addEventListener('click', (event) => {
    const target = event.target.closest('button');
    if (!target) return;
    if (adminState.dragJustEnded) return;

    if (target.dataset.adminModalClose !== undefined) closeAdminModal();
    if (target.dataset.filePickerClose !== undefined) closeFilePicker();
    if (target.dataset.adminPhotoModalClose !== undefined) closeAdminPhotoModal();
    if (target.dataset.browseTarget) openFilePicker(target.dataset.browseTarget, target.dataset.browseMode);
    if (target.dataset.openFileFolder) {
      if (adminState.picker) {
        loadPickerFiles(target.dataset.openFileFolder);
      } else {
        loadFiles(target.dataset.openFileFolder);
      }
    }
    if (target.dataset.pickerUp !== undefined && adminState.picker) {
      loadPickerFiles(parentPublicPath(adminState.picker.path));
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
    if (target.dataset.editUser) {
      openUserModal(adminState.users.find((item) => String(item.id) === target.dataset.editUser));
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
      const project = findAdminProject(target.dataset.openProjectDetail);
      if (project) showProjectDetailView(project);
    }
    if (target.dataset.backProjectList !== undefined) {
      showProjectListView();
    }
    if (target.dataset.saveProjectMediaOrder !== undefined) {
      saveProjectMediaOrder();
    }
    if (target.dataset.editProject) {
      const project = findAdminProject(target.dataset.editProject);
      if (project) openProjectModal(project);
    }
    if (target.dataset.adminResourceCategory !== undefined) {
      selectResourceCategory(target.dataset.adminResourceCategory);
      loadResourceManagementView();
    }
    if (target.dataset.editResource) {
      openResourceModal(adminState.resources.find((item) => String(item.id) === target.dataset.editResource));
    }
    if (target.dataset.adminYearbookResourceId) {
      openAdminYearbook(Number(target.dataset.adminYearbookResourceId));
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
    if (target.dataset.adminYearbookPageIndex) {
      openAdminPhotoModal(Number(target.dataset.adminYearbookPageIndex));
    }
    if (target.dataset.editActivity) {
      openActivityModal(adminState.activities.find((item) => String(item.id) === target.dataset.editActivity));
    }
    if (target.dataset.deleteActivity) deleteActivity(target.dataset.deleteActivity);
    if (target.dataset.dbTable) selectDbTable(target.dataset.dbTable);
    if (target.dataset.dbCellRow && target.dataset.dbCellColumn) {
      openDbCellModal(target.dataset.dbCellRow, target.dataset.dbCellColumn);
    }
    if (target.dataset.editDbRow) {
      openDbRowModal(adminState.dbRows.find((item) => String(item.id) === target.dataset.editDbRow));
    }
    if (target.dataset.deleteDbRow) deleteDbRow(target.dataset.deleteDbRow);
  });

  document.addEventListener('keydown', (event) => {
    if (!adminEls.photoModal.classList.contains('is-open') && adminEls.yearbookView.classList.contains('is-visible')) {
      if (event.key === 'ArrowLeft') {
        event.preventDefault();
        shiftAdminYearbook(-1);
      }
      if (event.key === 'ArrowRight') {
        event.preventDefault();
        shiftAdminYearbook(1);
      }
      return;
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
    uploadInput: adminQuery('#adminUploadInput'),
    uploadButton: adminQuery('#adminUploadButton'),
    uploadMessage: adminQuery('#adminUploadMessage'),
    createUserButton: adminQuery('#createUserButton'),
    refreshUsers: adminQuery('#refreshUsers'),
    userSearch: adminQuery('#userSearch'),
    userRoleFilter: adminQuery('#userRoleFilter'),
    userActiveFilter: adminQuery('#userActiveFilter'),
    usersTable: adminQuery('#usersTable'),
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
    refreshResources: adminQuery('#refreshResources'),
    resourceSearch: adminQuery('#resourceAdminSearch'),
    resourceSort: adminQuery('#adminResourceSort'),
    resourceYear: adminQuery('#adminResourceYear'),
    resourceCategoryList: adminQuery('#adminResourceCategoryList'),
    resourceCount: adminQuery('#adminResourceCount'),
    resourceView: adminQuery('#adminResourceView'),
    resourcesTable: adminQuery('#resourcesTable'),
    yearbookView: adminQuery('#adminYearbookView'),
    yearbookTitle: adminQuery('#adminYearbookTitle'),
    yearbookMeta: adminQuery('#adminYearbookMeta'),
    yearbookPages: adminQuery('#adminYearbookPages'),
    yearbookPrev: adminQuery('#adminYearbookPrev'),
    yearbookNext: adminQuery('#adminYearbookNext'),
    yearbookDownload: adminQuery('#adminDownloadYearbook'),
    backToResourcesButton: adminQuery('#backToAdminResources'),
    editCurrentYearbookButton: adminQuery('#editCurrentYearbookButton'),
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
    createDbRowButton: adminQuery('#createDbRowButton'),
    dbTableList: adminQuery('#dbTableList'),
    dbTableMeta: adminQuery('#dbTableMeta'),
    dbRowsTable: adminQuery('#dbRowsTable'),
    dbPrevPage: adminQuery('#dbPrevPage'),
    dbNextPage: adminQuery('#dbNextPage'),
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
