const announcementDetail = document.querySelector('#announcementDetail');
const announcementBreadcrumb = document.querySelector('#announcementBreadcrumb');
const announcementComments = document.querySelector('#announcementComments');
const announcementId = new URLSearchParams(window.location.search).get('id');

function announcementDetailDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function announcementParagraphs(content) {
  return String(content || '')
    .split(/\n+/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean)
    .map((paragraph) => `<p>${escapeHtml(paragraph)}</p>`)
    .join('');
}

async function loadAnnouncementDetail() {
  if (!announcementId) throw new Error('缺少公告 ID');
  const result = await request(`/announcements/${encodeURIComponent(announcementId)}`);
  const announcement = result.data;
  document.title = `${announcement.title} - NetHub Campus Wiki`;
  announcementBreadcrumb.textContent = announcement.title;
  announcementDetail.innerHTML = `
    <header>
      <div class="announcement-detail-flags">${announcement.isPinned ? '<span class="announcement-pinned">置顶</span>' : ''}<span>校园公告</span></div>
      <h1>${escapeHtml(announcement.title)}</h1>
      <p class="announcement-detail-summary">${escapeHtml(announcement.summary)}</p>
      <div class="announcement-detail-meta">
        <time>发布于 ${escapeHtml(announcementDetailDate(announcement.publishedAt))}</time>
        <span>浏览 ${escapeHtml(announcement.viewCount)}</span>
        <span>留言 ${escapeHtml(announcement.commentCount)}</span>
      </div>
    </header>
    <div class="announcement-content">${announcementParagraphs(announcement.content)}</div>
  `;
  mountCommentSection(announcementComments, 'announcement', announcement.id);
}

loadAnnouncementDetail().catch((error) => {
  announcementDetail.innerHTML = `<div class="empty error">${escapeHtml(error.message)}</div>`;
  announcementComments.classList.add('is-hidden');
});
