const resourceDetail = document.querySelector('#resourceDetail');
const resourceBreadcrumb = document.querySelector('#resourceBreadcrumb');
const resourceComments = document.querySelector('#resourceComments');
const resourceParams = new URLSearchParams(window.location.search);
const resourceId = resourceParams.get('id');
const isAdminPreview = resourceParams.get('preview') === 'admin';

async function loadResourceDetail() {
  if (!resourceId) throw new Error('缺少资源 ID');
  const result = await request(`/resources/${encodeURIComponent(resourceId)}${isAdminPreview ? '?track=false' : ''}`);
  const resource = result.data;
  document.title = `${resource.title} - NetHub Campus Wiki`;
  resourceBreadcrumb.textContent = resource.title;
  const image = safeExternalUrl(resource.image);
  const isTeacherVideo = resource.category === 'teacher';
  const videoUrl = safeExternalUrl(resource.resourceUrl);
  if (isTeacherVideo) {
    document.querySelectorAll('.teacher-nav-link').forEach((link) => {
      link.classList.add('active');
      link.setAttribute('aria-current', 'page');
    });
    document.querySelectorAll('.nav-links a[href="/resources.html"]').forEach((link) => {
      link.classList.remove('active');
      link.removeAttribute('aria-current');
    });
  }
  const media = isTeacherVideo
    ? `<div class="resource-detail-video-frame">
        <video id="resourceDetailVideo" class="resource-detail-video" controls preload="metadata" playsinline aria-label="${escapeHtml(resource.title)}">
          <source src="${videoUrl}">
          您的浏览器不支持 HTML5 视频。
        </video>
        <a id="resourceDetailVideoFallback" class="resource-video-fallback is-hidden" href="${videoUrl}" target="_blank" rel="noopener noreferrer">无法播放？打开视频</a>
      </div>`
    : `<div class="resource-detail-cover"><img src="${escapeHtml(image)}" alt="${escapeHtml(resource.title)}" /></div>`;
  const openAction = resource.category === 'yearbook'
    ? `<a class="button" href="/resources.html?yearbook=${encodeURIComponent(resource.id)}">打开 Yearbook</a>`
    : isTeacherVideo
      ? ''
      : `<a id="openResourceFile" class="button" href="${escapeHtml(authenticatedPublicFileUrl(resource.resourceUrl) || safeExternalUrl(resource.resourceUrl))}" target="_blank" rel="noopener noreferrer">打开资源</a>`;
  resourceDetail.innerHTML = `
    ${media}
    <div class="resource-detail-copy">
      <div class="resource-detail-tags"><span class="badge">${escapeHtml(resource.label)}</span><span>${escapeHtml(resource.year)}</span></div>
      <h1>${escapeHtml(resource.title)}</h1>
      <p>${escapeHtml(resource.description)}</p>
      ${isTeacherVideo ? '' : `<div class="resource-detail-stats"><span>热度 ${escapeHtml(resource.hot)}</span><span>下载 ${escapeHtml(resource.downloads)}</span></div>`}
      <div class="resource-detail-actions">${openAction}<a class="button secondary" href="${isTeacherVideo ? '/resources.html?category=teacher' : '/resources.html'}">返回资源中心</a></div>
    </div>
  `;
  resourceDetail.classList.toggle('is-video-resource', isTeacherVideo);
  const detailVideo = document.querySelector('#resourceDetailVideo');
  const detailVideoFallback = document.querySelector('#resourceDetailVideoFallback');
  const showVideoFallback = () => detailVideoFallback?.classList.remove('is-hidden');
  detailVideo?.addEventListener('error', showVideoFallback);
  if (detailVideo?.error) showVideoFallback();
  const openFile = document.querySelector('#openResourceFile');
  openFile?.addEventListener('click', (event) => {
    if (!requireAuthForDownload()) {
      event.preventDefault();
      return;
    }
    request(`/resources/${encodeURIComponent(resource.id)}/download`, { method: 'POST' }).catch(() => null);
  });
  mountCommentSection(resourceComments, 'resource', resource.id);
}

loadResourceDetail().catch((error) => {
  resourceDetail.innerHTML = `<div class="empty error">${escapeHtml(error.message)}</div>`;
  resourceComments.classList.add('is-hidden');
});
