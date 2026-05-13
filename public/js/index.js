const announcementList = document.querySelector('#announcementList');
const recommendProjects = document.querySelector('#recommendProjects');
const recommendSort = document.querySelector('#recommendSort');

// 加载首页公告。公告数据目前来自后端内存常量，后续可改成数据库表。
async function loadAnnouncements() {
  const result = await request('/announcements');
  announcementList.classList.remove('skeleton-list');
  announcementList.innerHTML = result.data.map((text) => `<li>${escapeHtml(text)}</li>`).join('');
}

// 加载推荐项目。首页只展示前三个，完整列表在项目库页面。
async function loadRecommendedProjects() {
  recommendProjects.innerHTML = '<div class="empty">正在加载推荐项目...</div>';
  const sort = recommendSort.value;
  const result = await request(`/projects?sort=${encodeURIComponent(sort)}`);
  recommendProjects.innerHTML = result.data.slice(0, 3).map(projectCard).join('');
}

recommendSort.addEventListener('change', loadRecommendedProjects);

// 首页有两个独立数据源；任意一个失败时都给出可操作的错误提示。
Promise.all([loadAnnouncements(), loadRecommendedProjects()]).catch((error) => {
  recommendProjects.innerHTML = `<div class="empty error">${escapeHtml(error.message)}。请确认后端和数据库已启动。</div>`;
});
