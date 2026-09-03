const allAnnouncementList = document.querySelector('#allAnnouncementList');
const announcementSearch = document.querySelector('#announcementSearch');
const announcementPrev = document.querySelector('#announcementPrev');
const announcementNext = document.querySelector('#announcementNext');
const announcementPageMeta = document.querySelector('#announcementPageMeta');
let announcementPage = 1;
let announcementSearchTimer = null;

function announcementListDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(date);
}

async function loadAllAnnouncements() {
  allAnnouncementList.innerHTML = '<div class="empty">正在加载公告...</div>';
  const query = new URLSearchParams({ page: String(announcementPage), pageSize: '10' });
  const search = announcementSearch.value.trim();
  if (search) query.set('search', search);
  try {
    const result = await request(`/announcements?${query}`);
    allAnnouncementList.innerHTML = result.data.length ? result.data.map((announcement) => `
      <a class="announcement-list-card" href="/announcement.html?id=${encodeURIComponent(announcement.id)}">
        <div class="announcement-card-meta">
          ${announcement.isPinned ? '<span class="announcement-pinned">置顶</span>' : ''}
          <time>${escapeHtml(announcementListDate(announcement.publishedAt))}</time>
        </div>
        <h2>${escapeHtml(announcement.title)}</h2>
        <p>${escapeHtml(announcement.summary)}</p>
        <footer><span>浏览 ${escapeHtml(announcement.viewCount)}</span><span>留言 ${escapeHtml(announcement.commentCount)}</span><strong>查看公告 →</strong></footer>
      </a>
    `).join('') : '<div class="empty">没有找到匹配的公告。</div>';
    const totalPages = Math.max(1, Math.ceil(result.total / result.pageSize));
    announcementPageMeta.textContent = `第 ${result.page} / ${totalPages} 页`;
    announcementPrev.disabled = result.page <= 1;
    announcementNext.disabled = !result.hasMore;
  } catch (error) {
    allAnnouncementList.innerHTML = `<div class="empty error">${escapeHtml(error.message)}</div>`;
  }
}

announcementPrev.addEventListener('click', () => {
  if (announcementPage > 1) {
    announcementPage -= 1;
    loadAllAnnouncements();
  }
});
announcementNext.addEventListener('click', () => {
  announcementPage += 1;
  loadAllAnnouncements();
});
announcementSearch.addEventListener('input', () => {
  window.clearTimeout(announcementSearchTimer);
  announcementSearchTimer = window.setTimeout(() => {
    announcementPage = 1;
    loadAllAnnouncements();
  }, 250);
});

loadAllAnnouncements();
