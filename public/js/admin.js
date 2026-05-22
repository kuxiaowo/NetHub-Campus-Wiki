const adminState = {
  currentUser: null,
  view: 'users',
  filePath: '',
  fileItems: [],
  picker: null,
  users: [],
  resourceMetaLoaded: false,
  resourceCategory: '',
  resourceYear: '',
  resourceSort: 'hot',
  resources: [],
  activities: [],
  activePhotoItems: [],
  selectedActivity: null,
  currentActivity: null,
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
        return `
          <label>
            <span>${adminText(field.label)}</span>
            <textarea class="input" name="${adminText(field.name)}" rows="4" ${field.required ? 'required' : ''}>${adminText(value)}</textarea>
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
  if (adminState.picker?.target) adminState.picker.target.value = url;
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
      { key: 'username', label: '用户名' },
      { key: 'displayName', label: '展示名' },
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
  if (user.id) return permissionFields;
  return [
    { name: 'username', label: '用户名', value: user.username, required: true },
    { name: 'displayName', label: '展示名', value: user.displayName || '' },
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

async function loadResourceAdminMeta() {
  if (adminState.resourceMetaLoaded) return;
  const meta = await adminEndpoint('/resources/meta');
  if (!meta.categories.some((category) => category.value === 'photos')) {
    meta.categories.push({ value: 'photos', label: '活动照片' });
  }
  const categories = [
    { value: '', label: '全部资源' },
    ...meta.categories,
  ];
  adminEls.resourceCategoryList.innerHTML = categories.map((category) => `
    <button class="category-button ${category.value === adminState.resourceCategory ? 'active' : ''}" type="button" data-admin-resource-category="${adminText(category.value)}">
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

function resourceAdminCard(resource) {
  const image = safeExternalUrl(resource.image);
  const resourceUrl = safeExternalUrl(resource.resourceUrl);
  return `
    <article class="resource-card admin-resource-card">
      <a class="resource-thumb" href="${resourceUrl}" target="_blank" rel="noopener noreferrer">
        <img src="${image}" alt="${adminText(resource.title)}" loading="lazy">
        <span class="badge">${adminText(resource.label)}</span>
      </a>
      <div class="resource-body">
        <div class="admin-card-title-row">
          <h2>${adminText(resource.title)}</h2>
          <button class="button compact" type="button" data-edit-resource="${adminText(resource.id)}">编辑</button>
        </div>
        <p>${adminText(resource.description)}</p>
        <div class="meta">
          <span>${adminText(resource.year)}</span>
          <span>${adminText(resource.type)}</span>
          <span>热度 ${adminText(resource.hot)}</span>
          <span>下载 ${adminText(resource.downloads)}</span>
        </div>
      </div>
    </article>
  `;
}

function resourceFields(resource = {}) {
  return [
    { name: 'title', label: '标题', value: resource.title, required: true },
    { name: 'description', label: '简介', value: resource.description, type: 'textarea', required: true },
    { name: 'year', label: '年份', value: resource.year || new Date().getFullYear(), type: 'number', required: true },
    { name: 'category', label: '分类值', value: resource.category || 'other', required: true },
    { name: 'label', label: '分类显示名', value: resource.label || '其他资源', required: true },
    { name: 'type', label: '类型', value: resource.type || '文档', required: true },
    { name: 'hot', label: '热度', value: resource.hot || 0, type: 'number' },
    { name: 'downloads', label: '下载数', value: resource.downloads || 0, type: 'number' },
    { name: 'image', label: '封面 URL', value: resource.image, required: true, browse: 'file' },
    { name: 'resourceUrl', label: '资源 URL', value: resource.resourceUrl, required: true, browse: 'fileOrFolder' },
  ];
}

function openResourceModal(resource) {
  const isEdit = Boolean(resource?.id);
  openAdminModal(isEdit ? '编辑资源' : '新建资源', resourceFields(resource), async (payload) => {
    await adminEndpoint(isEdit ? `/admin/resources/${resource.id}` : '/admin/resources', {
      method: isEdit ? 'PATCH' : 'POST',
      body: JSON.stringify(payload),
    });
    adminState.resourceMetaLoaded = false;
    await loadResourceManagementView();
  });
}

async function deleteResource(id) {
  if (!window.confirm('确认删除这个资源？')) return;
  await adminEndpoint(`/admin/resources/${id}`, { method: 'DELETE' });
  await loadResourceManagementView();
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
  renderAdminPhotos(result.data);
}

function renderAdminActivityList(activities) {
  if (!activities.length) {
    adminEls.activityList.innerHTML = '<div class="empty">暂无活动</div>';
    return;
  }
  const totalPhotoCount = activities.reduce((sum, activity) => sum + activity.images.length, 0);
  adminEls.activityList.innerHTML = [
    `<button class="category-button ${adminState.selectedActivity === null ? 'active' : ''}" type="button" data-admin-activity-id="">
      全部活动
      <span class="activity-count">${adminText(totalPhotoCount)} 张</span>
    </button>`,
    ...activities.map((activity) => `
      <button class="category-button ${activity.id === adminState.selectedActivity ? 'active' : ''}" type="button" data-admin-activity-id="${adminText(activity.id)}">
        ${adminText(activity.activity)}
        <span class="activity-count">${adminText(activity.images.length)} 张</span>
      </button>
    `),
  ].join('');
}

function photoButton(item) {
  return `
    <button class="photo-item" type="button" data-photo-index="${adminText(item.index)}" aria-label="查看 ${adminText(item.title)}">
      <img src="${safeExternalUrl(item.src)}" alt="${adminText(item.title)}" loading="lazy">
    </button>
  `;
}

function photoActivityCard(activity) {
  const cover = activity.images[0]?.src || '';
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
            <span>${adminText(activity.images.length)} 张照片</span>
            <span>热度 ${adminText(activity.hot)}</span>
          </span>
        </span>
      </button>
      <div class="admin-card-edit-row">
        <button class="button compact" type="button" data-edit-activity="${adminText(activity.id)}">编辑</button>
      </div>
    </article>
  `;
}

function renderAdminPhotos(activities) {
  renderAdminActivityList(activities);
  if (adminState.selectedActivity === null) {
    const totalPhotoCount = activities.reduce((sum, activity) => sum + activity.images.length, 0);
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
  adminEls.photoMeta.textContent = `${current.description} · ${current.year} · ${current.images.length} 张照片 · 热度 ${current.hot}`;
  adminState.activePhotoItems = current.images.map((item, index) => ({
    ...item,
    activity: current.activity,
    year: current.year,
    index,
  }));
  adminEls.activitiesTable.innerHTML = adminState.activePhotoItems.length
    ? adminState.activePhotoItems.map(photoButton).join('')
    : '<div class="empty">这个活动还没有照片。</div>';
}

function activityFields(activity = {}) {
  return [
    { name: 'activity', label: '活动名称', value: activity.activity, required: true },
    { name: 'description', label: '活动简介', value: activity.description, type: 'textarea', required: true },
    { name: 'year', label: '年份', value: activity.year || new Date().getFullYear(), type: 'number', required: true },
    { name: 'hot', label: '热度', value: activity.hot || 0, type: 'number' },
    { name: 'photoDir', label: '照片目录', value: activity.photoDir || '', browse: 'folder' },
  ];
}

function openActivityModal(activity) {
  const isEdit = Boolean(activity?.id);
  openAdminModal(isEdit ? '编辑活动' : '新建活动', activityFields(activity), async (payload) => {
    await adminEndpoint(isEdit ? `/admin/photo-activities/${activity.id}` : '/admin/photo-activities', {
      method: isEdit ? 'PATCH' : 'POST',
      body: JSON.stringify(payload),
    });
    adminState.resourceMetaLoaded = false;
    await loadActivities();
  });
}

async function deleteActivity(id) {
  if (!window.confirm('确认删除这个活动？活动下照片记录会一起删除。')) return;
  await adminEndpoint(`/admin/photo-activities/${id}`, { method: 'DELETE' });
  adminState.selectedActivity = null;
  await loadResourceManagementView();
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
    table.style.minWidth = `${adminState.dbSchema.length * 180 + 150}px`;
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
  adminEls.downloadActivity.addEventListener('click', () => {
    if (!adminState.currentActivity?.zipUrl) {
      window.alert('当前活动还没有配置 ZIP 下载文件。');
      return;
    }
    window.open(safeExternalUrl(adminState.currentActivity.zipUrl), '_blank', 'noopener,noreferrer');
  });
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

    if (target.dataset.adminModalClose !== undefined) closeAdminModal();
    if (target.dataset.filePickerClose !== undefined) closeFilePicker();
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
    if (target.dataset.editUser) {
      openUserModal(adminState.users.find((item) => String(item.id) === target.dataset.editUser));
    }
    if (target.dataset.adminResourceCategory !== undefined) {
      adminState.resourceCategory = target.dataset.adminResourceCategory;
      adminState.resourceYear = '';
      adminEls.resourceCategoryList.querySelectorAll('.category-button').forEach((item) => item.classList.remove('active'));
      target.classList.add('active');
      renderResourceYearOptions();
      loadResourceManagementView();
    }
    if (target.dataset.editResource) {
      openResourceModal(adminState.resources.find((item) => String(item.id) === target.dataset.editResource));
    }
    if (target.dataset.deleteResource) deleteResource(target.dataset.deleteResource);
    if (target.dataset.adminActivityId !== undefined) {
      adminState.selectedActivity = target.dataset.adminActivityId ? Number(target.dataset.adminActivityId) : null;
      renderAdminPhotos(adminState.activities);
    }
    if (target.dataset.adminActivityCardId) {
      adminState.selectedActivity = Number(target.dataset.adminActivityCardId);
      renderAdminPhotos(adminState.activities);
    }
    if (target.dataset.photoIndex) {
      const item = adminState.activePhotoItems[Number(target.dataset.photoIndex)];
      if (item) window.open(safeExternalUrl(item.src), '_blank', 'noopener,noreferrer');
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
    createResourceButton: adminQuery('#createResourceButton'),
    refreshResources: adminQuery('#refreshResources'),
    resourceSearch: adminQuery('#resourceAdminSearch'),
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
