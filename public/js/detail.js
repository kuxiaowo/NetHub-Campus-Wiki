const projectDetail = document.querySelector('#projectDetail');
const params = new URLSearchParams(window.location.search);
const id = params.get('id');

/**
 * 渲染项目媒体资源。
 * 图片直接展示，其他链接作为外部资源打开。URL 也需要转义后再进入 HTML。
 */
function renderMedia(media) {
  if (!media || media.length === 0) return '<p>暂无媒体资料。</p>';
  return `<div class="media-grid">${media.map((url) => {
    const safeUrl = escapeHtml(safeExternalUrl(url));
    const isImage = /\.(png|jpe?g|webp|gif)$/i.test(url) || url.includes('picsum.photos');
    return isImage
      ? `<img src="${safeUrl}" alt="项目媒体" loading="lazy" />`
      : `<a class="link-card" href="${safeUrl}" target="_blank" rel="noreferrer">打开媒体链接：${safeUrl}</a>`;
  }).join('')}</div>`;
}

// 从 URL 查询参数读取 id，然后请求后端详情接口。
async function loadDetail() {
  if (!id) throw new Error('缺少项目 ID');
  const result = await request(`/projects/${id}`);
  const project = result.data;
  document.title = `${project.name} - 项目详情`;

  projectDetail.innerHTML = `
    <div class="detail-head">
      ${projectIconImage(project)}
      <div>
        <h1>${escapeHtml(project.name)}</h1>
        <div class="meta">
          <span class="badge">${escapeHtml(project.category)}</span>
          <span>${escapeHtml(project.year)}</span>
          <span>负责人：${escapeHtml(project.leader)}</span>
          <span>成员：${escapeHtml(project.members)}</span>
        </div>
        ${casTags(project.cas)}
      </div>
    </div>

    <section>
      <h2>项目简介</h2>
      <p>${escapeHtml(project.description)}</p>
    </section>

    <section>
      <h2>照片 / 视频</h2>
      ${renderMedia(project.media)}
    </section>

    <section>
      <h2>项目动态</h2>
      <ul class="update-list">
        ${(project.updates || []).map((item) => `<li>${escapeHtml(item)}</li>`).join('') || '<li>暂无动态</li>'}
      </ul>
    </section>
  `;
}

loadDetail().catch((error) => {
  projectDetail.innerHTML = `<div class="empty error">${escapeHtml(error.message)}</div>`;
});
