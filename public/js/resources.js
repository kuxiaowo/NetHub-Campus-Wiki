const resourceSearch = document.querySelector('#resourceSearch');
const resourceSearchButton = document.querySelector('#resourceSearchButton');
const resourceYear = document.querySelector('#resourceYear');
const resourceSort = document.querySelector('#resourceSort');
const resourceCategoryList = document.querySelector('#resourceCategoryList');
const resourceCount = document.querySelector('#resourceCount');
const resourceGrid = document.querySelector('#resourceGrid');
const resourceView = document.querySelector('#resourceView');
const photoFilters = document.querySelector('#photoFilters');
const photoView = document.querySelector('#photoView');
const yearbookView = document.querySelector('#yearbookView');
const activityList = document.querySelector('#activityList');
const photoTitle = document.querySelector('#photoTitle');
const photoMeta = document.querySelector('#photoMeta');
const photoGrid = document.querySelector('#photoGrid');
const downloadActivity = document.querySelector('#downloadActivity');
const yearbookTitle = document.querySelector('#yearbookTitle');
const yearbookMeta = document.querySelector('#yearbookMeta');
const yearbookPages = document.querySelector('#yearbookPages');
const yearbookPrev = document.querySelector('#yearbookPrev');
const yearbookNext = document.querySelector('#yearbookNext');
const downloadYearbook = document.querySelector('#downloadYearbook');
const backToResources = document.querySelector('#backToResources');
const photoModal = document.querySelector('#photoModal');
const modalTitle = document.querySelector('#modalTitle');
const modalMeta = document.querySelector('#modalMeta');
const modalImage = document.querySelector('#modalImage');
const modalDownload = document.querySelector('#modalDownload');
const modalPrev = document.querySelector('#modalPrev');
const modalNext = document.querySelector('#modalNext');

let selectedResourceCategory = '';
let selectedActivityId = null;
let activePhotoItems = [];
let currentModalPhoto = null;
let currentModalIndex = -1;
let currentActivity = null;
let resourceYears = [];
let photoYears = [];
let currentYearbook = null;
let currentYearbookPage = 0;

const resourceSortOptions = [
  { value: 'hot', label: '最热' },
  { value: 'new', label: '最新' },
  { value: 'download', label: '下载最多' },
  { value: 'old', label: '最早' },
];

const photoSortOptions = [
  { value: 'hot', label: '最热' },
  { value: 'new', label: '最新' },
  { value: 'download', label: '下载最多' },
  { value: 'photoCount', label: '照片最多' },
  { value: 'old', label: '最早' },
];

function setPhotoMode(enabled) {
  photoFilters.classList.toggle('is-visible', enabled);
  photoView.classList.toggle('is-visible', enabled);
  resourceView.classList.toggle('is-hidden', enabled);
  yearbookView.classList.remove('is-visible');
}

function setYearbookMode(enabled) {
  photoFilters.classList.remove('is-visible');
  photoView.classList.remove('is-visible');
  resourceView.classList.toggle('is-hidden', enabled);
  yearbookView.classList.toggle('is-visible', enabled);
}

function renderYearOptions(years) {
  resourceYear.innerHTML = '<option value="">全部年份</option>' +
    years.map((year) => `<option value="${escapeHtml(year)}">${escapeHtml(year)}</option>`).join('');
}

function renderSortOptions(options) {
  resourceSort.innerHTML = options.map((option) => `
    <option value="${escapeHtml(option.value)}">${escapeHtml(option.label)}</option>
  `).join('');
}

function updateFilterScope() {
  const isPhotoCategory = selectedResourceCategory === 'photos';
  const currentYear = resourceYear.value;
  const currentSort = resourceSort.value;
  const sortOptions = isPhotoCategory ? photoSortOptions : resourceSortOptions;

  resourceSearch.placeholder = isPhotoCategory ? '搜索活动名称' : '搜索名称、内容、简介';
  renderYearOptions(isPhotoCategory ? photoYears : resourceYears);
  if ([...resourceYear.options].some((option) => option.value === currentYear)) {
    resourceYear.value = currentYear;
  }

  renderSortOptions(sortOptions);
  resourceSort.value = sortOptions.some((option) => option.value === currentSort) ? currentSort : 'hot';
}

function loadCurrentView() {
  if (selectedResourceCategory === 'photos') {
    return loadPhotoActivities();
  }
  return loadResources();
}

function itemTimestamp(item) {
  const timestamp = Date.parse(item.createdAt || item.updatedAt || '');
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function resourceParams(sort = resourceSort.value) {
  const params = new URLSearchParams();
  if (selectedResourceCategory) params.set('category', selectedResourceCategory);
  if (resourceYear.value) params.set('year', resourceYear.value);
  if (resourceSearch.value.trim()) params.set('search', resourceSearch.value.trim());
  params.set('sort', sort);
  return params;
}

function photoActivityParams(sort = resourceSort.value) {
  const params = new URLSearchParams();
  if (resourceYear.value) params.set('year', resourceYear.value);
  if (resourceSearch.value.trim()) params.set('search', resourceSearch.value.trim());
  params.set('sort', sort);
  return params;
}

function sortCombinedResources(items) {
  const sort = resourceSort.value;
  return [...items].sort((left, right) => {
    if (sort === 'download') {
      return (right.data.downloads || 0) - (left.data.downloads || 0);
    }
    if (sort === 'new') {
      return (right.data.year - left.data.year) || (itemTimestamp(right.data) - itemTimestamp(left.data));
    }
    if (sort === 'old') {
      return (left.data.year - right.data.year) || (itemTimestamp(left.data) - itemTimestamp(right.data));
    }
    return (right.data.hot - left.data.hot) || (itemTimestamp(right.data) - itemTimestamp(left.data));
  });
}

function resourceCard(resource) {
  const image = safeExternalUrl(resource.image);
  const resourceUrl = safeExternalUrl(resource.resourceUrl);
  const isYearbook = resource.category === 'yearbook';
  const thumb = `
    <span class="resource-thumb">
      <img src="${image}" alt="${escapeHtml(resource.title)}" loading="lazy">
      <span class="badge">${escapeHtml(resource.label)}</span>
    </span>
  `;

  return `
    <article class="resource-card">
      ${isYearbook
        ? `<button class="resource-card-link" type="button" data-yearbook-resource-id="${escapeHtml(resource.id)}">${thumb}</button>`
        : `<a class="resource-card-link" href="${resourceUrl}" target="_blank" rel="noopener noreferrer" data-resource-download-id="${escapeHtml(resource.id)}">${thumb}</a>`}
      <div class="resource-body">
        <h2>${escapeHtml(resource.title)}</h2>
        <p>${escapeHtml(resource.description)}</p>
        <div class="meta">
          <span>${escapeHtml(resource.year)}</span>
          <span>${escapeHtml(resource.type)}</span>
          <span>热度 ${escapeHtml(resource.hot)}</span>
          <span>下载 ${escapeHtml(resource.downloads)}</span>
        </div>
      </div>
    </article>
  `;
}

function bindYearbookCards() {
  resourceGrid.querySelectorAll('[data-yearbook-resource-id]').forEach((button) => {
    button.addEventListener('click', () => openYearbook(Number(button.dataset.yearbookResourceId)));
  });
}

function trackResourceDownload(resourceId) {
  if (!resourceId) return Promise.resolve(null);
  return request(`/resources/${resourceId}/download`, { method: 'POST' })
    .then((result) => result.data)
    .catch(() => null);
}

function trackPhotoActivityDownload(activityId) {
  if (!activityId) return Promise.resolve(null);
  return request(`/photo-activities/${activityId}/download`, { method: 'POST' })
    .then((result) => result.data)
    .catch(() => null);
}

function updateCurrentActivityDownloads(activity) {
  if (!activity || !currentActivity || currentActivity.id !== activity.id) return;
  currentActivity = { ...currentActivity, ...activity };
  photoMeta.textContent = `${currentActivity.year} · ${activePhotoItems.length || currentActivity.photoCount} 张照片 · 热度 ${currentActivity.hot} · 下载 ${currentActivity.downloads || 0}`;
}

function updateCurrentYearbookDownloads(resource) {
  if (!resource || !currentYearbook || currentYearbook.resource.id !== resource.id) return;
  currentYearbook.resource = resource;
  renderYearbook();
}

function bindResourceDownloadLinks() {
  resourceGrid.querySelectorAll('[data-resource-download-id]').forEach((link) => {
    link.addEventListener('click', () => {
      trackResourceDownload(Number(link.dataset.resourceDownloadId));
    });
  });
}

function activityResourceCard(activity) {
  const cover = activity.coverThumbSrc || activity.coverSrc || '';
  const image = cover ? `<img src="${safeExternalUrl(cover)}" alt="${escapeHtml(activity.activity)}" loading="lazy">` : '';

  return `
    <button class="resource-card photo-activity-card" type="button" data-resource-activity-id="${escapeHtml(activity.id)}">
      <span class="resource-thumb">
        ${image}
        <span class="badge">活动照片</span>
      </span>
      <span class="resource-body">
        <h2>${escapeHtml(activity.activity)}</h2>
        <p>${escapeHtml(activity.description)}</p>
        <span class="meta">
          <span>${escapeHtml(activity.year)}</span>
          <span>${escapeHtml(activity.photoCount)} 张照片</span>
          <span>热度 ${escapeHtml(activity.hot)}</span>
          <span>下载 ${escapeHtml(activity.downloads || 0)}</span>
        </span>
      </span>
    </button>
  `;
}

function renderCombinedResources(resources, activities) {
  const combined = sortCombinedResources([
    ...resources.map((item) => ({ kind: 'resource', data: item })),
    ...activities.map((item) => ({ kind: 'photoActivity', data: item })),
  ]);

  resourceCount.textContent = `共 ${combined.length} 个资源`;
  resourceGrid.innerHTML = combined.length
    ? combined.map((item) => item.kind === 'resource' ? resourceCard(item.data) : activityResourceCard(item.data)).join('')
    : '<div class="empty">没有找到匹配的资源，换个筛选条件试试。</div>';

  resourceGrid.querySelectorAll('[data-resource-activity-id]').forEach((button) => {
    button.addEventListener('click', () => openActivityFromResourceCard(activities, Number(button.dataset.resourceActivityId)));
  });
  bindYearbookCards();
  bindResourceDownloadLinks();
}

function openActivityFromResourceCard(activities, activityId) {
  selectedResourceCategory = 'photos';
  selectedActivityId = activityId;
  resourceCategoryList.querySelectorAll('.category-button').forEach((item) => {
    item.classList.toggle('active', item.dataset.resourceCategory === 'photos');
  });
  setPhotoMode(true);
  updateFilterScope();
  renderPhotos(activities);
}

async function loadResourceMeta() {
  const meta = await request('/resources/meta');
  resourceYears = meta.years;
  photoYears = meta.photoYears;

  resourceCategoryList.innerHTML = [
    '<button class="category-button active" type="button" data-resource-category="">全部资源</button>',
    ...meta.categories.map((category) => `
      <button class="category-button" type="button" data-resource-category="${escapeHtml(category.value)}">
        ${escapeHtml(category.label)}
      </button>
    `),
  ].join('');

  updateFilterScope();

  resourceCategoryList.addEventListener('click', (event) => {
    const button = event.target.closest('.category-button');
    if (!button) return;

    selectedResourceCategory = button.dataset.resourceCategory;
    resourceCategoryList.querySelectorAll('.category-button').forEach((item) => item.classList.remove('active'));
    button.classList.add('active');
    setPhotoMode(selectedResourceCategory === 'photos');
    updateFilterScope();
    selectedActivityId = null;
    currentYearbook = null;
    loadCurrentView();
  });
}

async function loadResources() {
  resourceGrid.innerHTML = '<div class="empty">正在加载资源...</div>';

  if (!selectedResourceCategory) {
    const [resourceResult, photoResult] = await Promise.all([
      request(`/resources?${resourceParams().toString()}`),
      request(`/photo-activities?${photoActivityParams().toString()}`),
    ]);
    renderCombinedResources(resourceResult.data, photoResult.data);
    return;
  }

  const params = resourceParams();
  const result = await request(`/resources?${params.toString()}`);
  resourceCount.textContent = `共 ${result.data.length} 个资源`;
  resourceGrid.innerHTML = result.data.length
    ? result.data.map(resourceCard).join('')
    : '<div class="empty">没有找到匹配的资源，换个筛选条件试试。</div>';
  bindYearbookCards();
  bindResourceDownloadLinks();
}

function renderActivityList(activities) {
  if (!activities.length) {
    selectedActivityId = null;
    activityList.innerHTML = '<div class="empty">暂无活动</div>';
    return;
  }

  if (selectedActivityId !== null && !activities.some((activity) => activity.id === selectedActivityId)) {
    selectedActivityId = null;
  }

  const totalPhotoCount = activities.reduce((sum, activity) => sum + activity.photoCount, 0);
  activityList.innerHTML = [
    `<button class="category-button ${selectedActivityId === null ? 'active' : ''}" type="button" data-activity-id="">
      全部活动
      <span class="activity-count">${escapeHtml(totalPhotoCount)} 张</span>
    </button>`,
    ...activities.map((activity) => `
      <button class="category-button ${activity.id === selectedActivityId ? 'active' : ''}" type="button" data-activity-id="${escapeHtml(activity.id)}">
        ${escapeHtml(activity.activity)}
        <span class="activity-count">${escapeHtml(activity.photoCount)} 张</span>
      </button>
    `),
  ].join('');

  activityList.querySelectorAll('[data-activity-id]').forEach((button) => {
    button.addEventListener('click', () => {
      selectedActivityId = button.dataset.activityId ? Number(button.dataset.activityId) : null;
      renderPhotos(activities);
    });
  });
}

function photoButton(item) {
  const image = safeExternalUrl(item.thumbSrc || item.src);
  return `
    <button class="photo-item" type="button" data-photo-index="${escapeHtml(item.index)}" aria-label="查看 ${escapeHtml(item.title)}">
      <img src="${image}" alt="${escapeHtml(item.title)}" loading="lazy" decoding="async">
    </button>
  `;
}

function photoActivityCard(activity) {
  const cover = activity.coverThumbSrc || activity.coverSrc || '';
  const image = cover ? `<img src="${safeExternalUrl(cover)}" alt="${escapeHtml(activity.activity)}" loading="lazy">` : '';

  return `
    <button class="resource-card photo-activity-card" type="button" data-activity-card-id="${escapeHtml(activity.id)}">
      <span class="resource-thumb">
        ${image}
        <span class="badge">${escapeHtml(activity.year)}</span>
      </span>
      <span class="resource-body">
        <h2>${escapeHtml(activity.activity)}</h2>
        <p>${escapeHtml(activity.description)}</p>
        <span class="meta">
          <span>${escapeHtml(activity.photoCount)} 张照片</span>
          <span>热度 ${escapeHtml(activity.hot)}</span>
          <span>下载 ${escapeHtml(activity.downloads || 0)}</span>
        </span>
      </span>
    </button>
  `;
}

function renderPhotos(activities) {
  renderActivityList(activities);
  if (selectedActivityId === null) {
    photoGrid.classList.remove('photo-groups');
    photoGrid.classList.add('photo-activity-cards');
    const totalPhotoCount = activities.reduce((sum, activity) => sum + activity.photoCount, 0);
    photoTitle.textContent = '全部活动';
    photoMeta.textContent = `${activities.length} 个活动 · ${totalPhotoCount} 张照片`;
    downloadActivity.classList.add('is-hidden');
    activePhotoItems = [];
    currentActivity = null;

    photoGrid.innerHTML = activities.length
      ? activities.map(photoActivityCard).join('')
      : '<div class="empty">没有找到匹配的活动。</div>';

    photoGrid.querySelectorAll('[data-activity-card-id]').forEach((button) => {
      button.addEventListener('click', () => {
        selectedActivityId = Number(button.dataset.activityCardId);
        renderPhotos(activities);
      });
    });
    return;
  }

  photoGrid.classList.remove('photo-groups');
  photoGrid.classList.remove('photo-activity-cards');
  downloadActivity.classList.remove('is-hidden');
  const current = activities.find((activity) => activity.id === selectedActivityId);

  if (!current) {
    photoTitle.textContent = '活动照片';
    photoMeta.textContent = '没有找到匹配的活动';
    photoGrid.innerHTML = '';
    activePhotoItems = [];
    currentActivity = null;
    return;
  }

  currentActivity = current;
  photoTitle.textContent = current.activity;
  photoMeta.textContent = `${current.year} · ${current.photoCount} 张照片 · 热度 ${current.hot} · 下载 ${current.downloads || 0}`;
  activePhotoItems = [];
  photoGrid.innerHTML = '<div class="empty">正在加载活动照片...</div>';
  loadActivityPhotos(current).catch((error) => {
    photoGrid.innerHTML = `<div class="empty error">${escapeHtml(error.message)}</div>`;
  });
}

async function loadActivityPhotos(activity) {
  if (!activity.loadedImages) {
    const result = await request(`/photo-activities/${activity.id}/photos`);
    activity.loadedImages = result.data;
    if (result.activity) {
      Object.assign(activity, result.activity);
      updateCurrentActivityDownloads(activity);
    }
  }
  activePhotoItems = activity.loadedImages.map((item, index) => ({
    ...item,
    activity: activity.activity,
    year: activity.year,
    index,
    downloadMetric: 'photoActivity',
    downloadMetricId: activity.id,
  }));
  photoMeta.textContent = `${activity.year} · ${activePhotoItems.length} 张照片 · 热度 ${activity.hot} · 下载 ${activity.downloads || 0}`;
  photoGrid.innerHTML = activePhotoItems.length
    ? activePhotoItems.map(photoButton).join('')
    : '<div class="empty">这个活动还没有照片。</div>';
  photoGrid.querySelectorAll('[data-photo-index]').forEach((button) => {
    button.addEventListener('click', () => openPhotoModal(Number(button.dataset.photoIndex)));
  });
}

async function loadPhotoActivities() {
  photoGrid.innerHTML = '<div class="empty">正在加载活动照片...</div>';

  const params = photoActivityParams();
  const result = await request(`/photo-activities?${params.toString()}`);
  renderPhotos(result.data);
}

async function openYearbook(resourceId) {
  setYearbookMode(true);
  currentYearbook = null;
  currentYearbookPage = 0;
  yearbookTitle.textContent = 'Yearbook';
  yearbookMeta.textContent = '正在加载 Yearbook...';
  yearbookPages.innerHTML = '<div class="empty">正在加载 Yearbook...</div>';
  setYearbookDownload(null);
  updateYearbookControls();

  try {
    const result = await request(`/resources/${resourceId}/yearbook`);
    currentYearbook = result.data;
    currentYearbookPage = 0;
    renderYearbook();
  } catch (error) {
    yearbookMeta.textContent = 'Yearbook 加载失败';
    yearbookPages.innerHTML = `<div class="empty error">${escapeHtml(error.message)}</div>`;
  }
}

function setYearbookDownload(pdfUrl) {
  if (!pdfUrl) {
    downloadYearbook.href = '#';
    downloadYearbook.removeAttribute('download');
    downloadYearbook.setAttribute('aria-disabled', 'true');
    downloadYearbook.classList.add('disabled');
    return;
  }

  downloadYearbook.href = safeExternalUrl(pdfUrl);
  downloadYearbook.download = `${currentYearbook?.resource?.title || 'yearbook'}.pdf`;
  downloadYearbook.removeAttribute('aria-disabled');
  downloadYearbook.classList.remove('disabled');
}

function renderYearbook() {
  if (!currentYearbook) return;
  const { resource, pages, pdfUrl } = currentYearbook;
  const visiblePages = pages.slice(currentYearbookPage, currentYearbookPage + 2);

  yearbookTitle.textContent = resource.title;
  yearbookMeta.textContent = `${resource.year} · ${pages.length} 页 · 第 ${currentYearbookPage + 1}-${Math.min(currentYearbookPage + visiblePages.length, pages.length)} 页 · 热度 ${resource.hot} · 下载 ${resource.downloads}`;
  setYearbookDownload(pdfUrl);
  activePhotoItems = pages.map((page, index) => ({
    ...page,
    activity: resource.title,
    year: resource.year,
    index,
    downloadMetric: 'resource',
    downloadMetricId: resource.id,
  }));
  yearbookPages.innerHTML = visiblePages.map((page) => `
    <figure class="yearbook-page">
      <button class="yearbook-page-button" type="button" data-yearbook-page-index="${escapeHtml(page.index - 1)}" aria-label="查看 ${escapeHtml(page.title)}">
        <img src="${safeExternalUrl(page.src)}" alt="${escapeHtml(resource.title)} ${escapeHtml(page.title)}" loading="eager">
      </button>
      <figcaption>${escapeHtml(page.index)} / ${escapeHtml(pages.length)}</figcaption>
    </figure>
  `).join('');
  if (visiblePages.length === 1) {
    yearbookPages.insertAdjacentHTML('beforeend', '<div class="yearbook-page-placeholder">本组只有一页</div>');
  }
  yearbookPages.querySelectorAll('[data-yearbook-page-index]').forEach((button) => {
    button.addEventListener('click', () => openPhotoModal(Number(button.dataset.yearbookPageIndex)));
  });
  updateYearbookControls();
}

function updateYearbookControls() {
  const pageCount = currentYearbook?.pages?.length || 0;
  yearbookPrev.disabled = currentYearbookPage <= 0;
  yearbookNext.disabled = !pageCount || currentYearbookPage + 2 >= pageCount;
}

function shiftYearbook(direction) {
  if (!currentYearbook) return;
  const maxStart = Math.max(0, Math.floor((currentYearbook.pages.length - 1) / 2) * 2);
  currentYearbookPage = Math.min(Math.max(currentYearbookPage + direction * 2, 0), maxStart);
  renderYearbook();
}

function closeYearbook() {
  currentYearbook = null;
  currentYearbookPage = 0;
  setYearbookMode(false);
}

function openPhotoModal(index) {
  const item = activePhotoItems[index];
  if (!item) return;

  const src = safeExternalUrl(item.src);
  currentModalIndex = index;
  currentModalPhoto = { ...item, src };
  modalTitle.textContent = item.title;
  modalMeta.textContent = `${item.activity} · ${item.year} · ${index + 1}/${activePhotoItems.length}`;
  modalImage.src = src;
  modalImage.alt = item.title;
  photoModal.classList.add('is-open');
  photoModal.setAttribute('aria-hidden', 'false');
}

function shiftPhotoModal(direction) {
  if (!photoModal.classList.contains('is-open') || !activePhotoItems.length) return;
  const nextIndex = (currentModalIndex + direction + activePhotoItems.length) % activePhotoItems.length;
  openPhotoModal(nextIndex);
}

function closePhotoModal() {
  photoModal.classList.remove('is-open');
  photoModal.setAttribute('aria-hidden', 'true');
  modalImage.src = '';
  currentModalPhoto = null;
  currentModalIndex = -1;
}

function downloadBlob(url, filename) {
  return fetch(url)
    .then((response) => {
      if (!response.ok) throw new Error(`下载失败：${response.status}`);
      return response.blob();
    })
    .then((blob) => {
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = objectUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(objectUrl);
    });
}

async function downloadModalPhoto() {
  if (!currentModalPhoto) return;

  const filename = `${currentModalPhoto.activity}-${currentModalPhoto.title}.jpg`;
  if (currentModalPhoto.downloadMetric === 'photoActivity') {
    const activity = await trackPhotoActivityDownload(currentModalPhoto.downloadMetricId);
    updateCurrentActivityDownloads(activity);
  }
  if (currentModalPhoto.downloadMetric === 'resource') {
    const resource = await trackResourceDownload(currentModalPhoto.downloadMetricId);
    updateCurrentYearbookDownloads(resource);
  }
  downloadBlob(currentModalPhoto.src, filename).catch(() => {
    const link = document.createElement('a');
    link.href = currentModalPhoto.src;
    link.target = '_blank';
    link.rel = 'noreferrer';
    document.body.appendChild(link);
    link.click();
    link.remove();
  });
}

async function downloadCurrentActivityArchive() {
  if (!currentActivity) return;
  const archiveUrl = currentActivity.archiveUrl;
  if (!archiveUrl) {
    window.alert('当前活动还没有配置压缩文件。');
    return;
  }

  const updated = await trackPhotoActivityDownload(currentActivity.id);
  updateCurrentActivityDownloads(updated);

  const link = document.createElement('a');
  link.href = safeExternalUrl(archiveUrl);
  link.download = `${currentActivity.activity}.rar`;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

[resourceYear, resourceSort].forEach((control) => control.addEventListener('change', loadCurrentView));
resourceSearchButton.addEventListener('click', loadCurrentView);
resourceSearch.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    event.preventDefault();
    loadCurrentView();
  }
});

downloadActivity.addEventListener('click', downloadCurrentActivityArchive);
yearbookPrev.addEventListener('click', () => shiftYearbook(-1));
yearbookNext.addEventListener('click', () => shiftYearbook(1));
backToResources.addEventListener('click', closeYearbook);
downloadYearbook.addEventListener('click', (event) => {
  if (downloadYearbook.getAttribute('aria-disabled') === 'true') {
    event.preventDefault();
    return;
  }
  const resourceId = currentYearbook?.resource?.id;
  trackResourceDownload(resourceId).then(updateCurrentYearbookDownloads);
});
modalDownload.addEventListener('click', downloadModalPhoto);
modalPrev.addEventListener('click', () => shiftPhotoModal(-1));
modalNext.addEventListener('click', () => shiftPhotoModal(1));
document.querySelectorAll('[data-close-modal]').forEach((item) => item.addEventListener('click', closePhotoModal));
document.addEventListener('keydown', (event) => {
  if (!photoModal.classList.contains('is-open') && yearbookView.classList.contains('is-visible')) {
    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      shiftYearbook(-1);
    }
    if (event.key === 'ArrowRight') {
      event.preventDefault();
      shiftYearbook(1);
    }
    return;
  }
  if (!photoModal.classList.contains('is-open')) return;
  if (event.key === 'Escape') {
    closePhotoModal();
  }
  if (event.key === 'ArrowLeft') {
    event.preventDefault();
    shiftPhotoModal(-1);
  }
  if (event.key === 'ArrowRight') {
    event.preventDefault();
    shiftPhotoModal(1);
  }
});

loadResourceMeta()
  .then(loadCurrentView)
  .catch((error) => {
    resourceGrid.innerHTML = `<div class="empty error">${escapeHtml(error.message)}。请确认后端和数据库已启动。</div>`;
    photoGrid.innerHTML = '';
  });
