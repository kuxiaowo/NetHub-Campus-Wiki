const announcementList = document.querySelector('#announcementList');
const recommendProjects = document.querySelector('#recommendProjects');
const recommendSort = document.querySelector('#recommendSort');

// 加载首页公告。公告数据目前来自后端内存常量，后续可改成数据库表。
async function loadAnnouncements() {
  announcementList.classList.add('skeleton-list');
  const result = await request('/announcements');
  announcementList.classList.remove('skeleton-list');
  announcementList.innerHTML = result.data.length
    ? result.data.map((text) => `<li>${escapeHtml(text)}</li>`).join('')
    : '<li class="empty">暂时还没有公告。</li>';
}

// 加载推荐项目。首页只展示前三个，完整列表在项目库页面。
async function loadRecommendedProjects() {
  recommendProjects.innerHTML = '<div class="empty">正在加载推荐项目...</div>';
  const sort = recommendSort.value;
  const result = await request(`/projects?sort=${encodeURIComponent(sort)}`);
  recommendProjects.innerHTML = result.data.length
    ? result.data.slice(0, 3).map(projectCard).join('')
    : '<div class="empty">暂时还没有推荐项目。</div>';
}

function loadAnnouncementsSafely() {
  loadAnnouncements().catch(() => {
    announcementList.classList.remove('skeleton-list');
    announcementList.innerHTML = '<li class="empty error">暂时无法加载公告。<br><button class="button secondary compact" type="button" data-retry-announcements>重新加载</button></li>';
  });
}

function loadRecommendedProjectsSafely() {
  loadRecommendedProjects().catch(() => {
    recommendProjects.innerHTML = '<div class="empty error">暂时无法加载推荐项目。<br><button class="button secondary compact" type="button" data-retry-recommendations>重新加载</button></div>';
  });
}

recommendSort.addEventListener('change', loadRecommendedProjectsSafely);
announcementList.addEventListener('click', (event) => {
  if (event.target.closest('[data-retry-announcements]')) loadAnnouncementsSafely();
});
recommendProjects.addEventListener('click', (event) => {
  if (event.target.closest('[data-retry-recommendations]')) loadRecommendedProjectsSafely();
});

// 两个区域独立加载，单个请求失败不会影响另一区域。
loadAnnouncementsSafely();
loadRecommendedProjectsSafely();
