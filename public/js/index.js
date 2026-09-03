const notificationList = document.querySelector('#notificationList');
const popularProjectList = document.querySelector('#popularProjectList');
const popularResourceList = document.querySelector('#popularResourceList');

function shortDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit' }).format(date);
}

function projectUpdateMediaUrl(item) {
  if (item && typeof item === 'object') {
    return item.url || item.src || item.href || item.poster || item.cover || item.thumbnail || '';
  }
  return item || '';
}

function latestProjectUpdatePhoto(project) {
  const updates = Array.isArray(project.updates) ? project.updates : [];
  const fallbackDate = project.updatedAt || project.createdAt || '';
  const latest = updates
    .map((update, index) => ({
      update,
      index,
      date: update && typeof update === 'object'
        ? update.createdAt || update.updatedAt || update.date || update.time || fallbackDate
        : fallbackDate,
    }))
    .sort((left, right) => {
      const leftTime = new Date(left.date).getTime();
      const rightTime = new Date(right.date).getTime();
      if (Number.isNaN(leftTime) || Number.isNaN(rightTime) || leftTime === rightTime) {
        return left.index - right.index;
      }
      return rightTime - leftTime;
    })[0]?.update;

  if (!latest || typeof latest !== 'object') return '';
  const media = [latest.images, latest.photos, latest.media]
    .find((items) => Array.isArray(items) && items.length);
  if (!media) return '';

  const imageUrl = safeExternalUrl(projectUpdateMediaUrl(media[0]));
  return imageUrl === '#' ? '' : imageUrl;
}

function popularProjectCard(project, index) {
  const updatePhoto = latestProjectUpdatePhoto(project);
  return `
    <a class="home-popular-card" href="/detail.html?id=${encodeURIComponent(project.id)}">
      <div class="home-popular-media project-media${updatePhoto ? ' has-update-photo' : ''}">
        ${updatePhoto ? `<img class="home-project-update-photo" src="${escapeHtml(updatePhoto)}" alt="" loading="lazy" decoding="async" data-project-update-photo>` : ''}
        <b class="home-popular-rank">${index + 1}</b>
        ${projectIconImage(project)}
      </div>
      <div class="home-popular-body">
        <span class="home-popular-meta"><em>${escapeHtml(project.category)}</em><small>${escapeHtml(project.year)}</small></span>
        <strong>${escapeHtml(project.name)}</strong>
        <span class="home-popular-hot">热度 ${escapeHtml(project.popularity || 0)} <i aria-hidden="true">→</i></span>
      </div>
    </a>
  `;
}

document.addEventListener('error', (event) => {
  const image = event.target;
  if (!(image instanceof HTMLImageElement) || !image.matches('[data-project-update-photo]')) return;
  image.closest('.project-media')?.classList.remove('has-update-photo');
  image.remove();
}, true);

function popularResourceCard(resource, index) {
  const image = safeExternalUrl(resource.image);
  const href = resource.href || (resource.category === 'yearbook'
    ? `/resources.html?yearbook=${encodeURIComponent(resource.id)}`
    : `/resource.html?id=${encodeURIComponent(resource.id)}`);
  const thumbnail = image === '#'
    ? '<span class="home-popular-placeholder" aria-hidden="true"></span>'
    : `<img src="${image}" alt="" loading="lazy" decoding="async">`;

  return `
    <a class="home-popular-card" href="${escapeHtml(href)}">
      <div class="home-popular-media resource-media">
        <b class="home-popular-rank">${index + 1}</b>
        ${thumbnail}
      </div>
      <div class="home-popular-body">
        <span class="home-popular-meta"><em>${escapeHtml(resource.label || '资源')}</em><small>${escapeHtml(resource.year)}</small></span>
        <strong>${escapeHtml(resource.title)}</strong>
        <span class="home-popular-hot">热度 ${escapeHtml(resource.hot || 0)} <i aria-hidden="true">→</i></span>
      </div>
    </a>
  `;
}

async function loadNotifications() {
  const result = await request('/announcements?page=1&pageSize=3');
  notificationList.innerHTML = result.data.length
    ? result.data.map((notification) => `
        <li>
          <a href="/announcement.html?id=${encodeURIComponent(notification.id)}">
            <span>${notification.isPinned ? '<b>置顶</b>' : ''}<strong>${escapeHtml(notification.title)}</strong></span>
            <time>${escapeHtml(shortDate(notification.publishedAt))}</time>
          </a>
        </li>
      `).join('')
    : '<li class="home-notification-empty">暂无通知</li>';
}

async function loadPopularProjects() {
  const result = await request('/projects?sort=popular');
  const projects = result.data.slice(0, 3);
  popularProjectList.innerHTML = projects.length
    ? projects.map(popularProjectCard).join('')
    : '<div class="empty">还没有项目。</div>';
}

async function loadPopularResources() {
  const [resourceResult, photoResult] = await Promise.all([
    request('/resources?sort=hot'),
    request('/photo-activities?sort=hot'),
  ]);
  const resources = [
    ...resourceResult.data,
    ...photoResult.data.map((activity) => ({
      id: activity.id,
      label: '活动照片',
      title: activity.activity,
      year: activity.year,
      hot: activity.hot,
      image: activity.coverThumbSrc || activity.coverSrc || '',
      href: '/resources.html?category=photos',
      createdAt: activity.createdAt,
    })),
  ].sort((left, right) => (right.hot || 0) - (left.hot || 0)).slice(0, 3);
  popularResourceList.innerHTML = resources.length
    ? resources.map(popularResourceCard).join('')
    : '<div class="empty">还没有资源。</div>';
}

loadNotifications().catch(() => {
  notificationList.innerHTML = '<li class="home-notification-empty error">通知暂时无法加载</li>';
});

loadPopularProjects().catch((error) => {
  popularProjectList.innerHTML = `<div class="empty error">${escapeHtml(error.message)}。热门项目暂时无法加载。</div>`;
});

loadPopularResources().catch((error) => {
  popularResourceList.innerHTML = `<div class="empty error">${escapeHtml(error.message)}。热门资源暂时无法加载。</div>`;
});
