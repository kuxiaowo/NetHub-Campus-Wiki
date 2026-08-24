const announcementList = document.querySelector('#announcementList');
const recommendProjects = document.querySelector('#recommendProjects');
const recommendSort = document.querySelector('#recommendSort');

function homeAnnouncementDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit' }).format(date);
}

// 首页只展示最新三条，完整列表进入全部公告页面。
async function loadAnnouncements() {
  const result = await request('/announcements?page=1&pageSize=3');
  announcementList.classList.remove('skeleton-list');
  announcementList.innerHTML = result.data.map((announcement) => `
    <li>
      <a href="/announcement.html?id=${encodeURIComponent(announcement.id)}">
        <span>${announcement.isPinned ? '<strong>置顶</strong>' : ''}${escapeHtml(announcement.title)}</span>
        <time>${escapeHtml(homeAnnouncementDate(announcement.publishedAt))}</time>
      </a>
    </li>
  `).join('');
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
