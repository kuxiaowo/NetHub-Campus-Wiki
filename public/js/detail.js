const projectDetail = document.querySelector('#projectDetail');
const detailBreadcrumb = document.querySelector('#detailBreadcrumb');
const params = new URLSearchParams(window.location.search);
const id = params.get('id');
const projectUpdateModal = document.querySelector('#projectUpdateModal');
const projectUpdateForm = document.querySelector('#projectUpdateForm');
const projectUpdateContent = document.querySelector('#projectUpdateContent');
const projectUpdatePhotos = document.querySelector('#projectUpdatePhotos');
const projectUpdatePhotoSummary = document.querySelector('#projectUpdatePhotoSummary');
const projectUpdateMessage = document.querySelector('#projectUpdateMessage');
const projectUpdateSubmit = document.querySelector('#projectUpdateSubmit');
let currentProject = null;
let projectUpdateSubmitting = false;
const MAX_PROJECT_UPDATE_PHOTO_BYTES = 5 * 1024 * 1024;

const CAS_LABELS = [
  ['creativity', 'Creativity'],
  ['activity', 'Activity'],
  ['service', 'Service'],
];

function cleanText(value) {
  return String(value ?? '').trim();
}

function firstFilled(...values) {
  return values.map(cleanText).find(Boolean) || '';
}

function tryJson(value) {
  if (typeof value !== 'string') return value;
  const text = value.trim();
  if (!text || !['[', '{'].includes(text[0])) return value;
  try {
    return JSON.parse(text);
  } catch {
    return value;
  }
}

function asArray(value) {
  const parsed = tryJson(value);
  if (Array.isArray(parsed)) return parsed;
  if (parsed && typeof parsed === 'object') return [parsed];
  return cleanText(parsed) ? [parsed] : [];
}

function safeDetailUrl(value) {
  const raw = cleanText(value);
  if (!raw) return null;
  const url = safeExternalUrl(raw);
  return url === '#' ? null : url;
}

function isImageUrl(value) {
  const url = cleanText(value).toLowerCase();
  return /\.(png|jpe?g|webp|gif|avif)(\?|#|$)/i.test(url)
    || url.includes('picsum.photos')
    || url.includes('images.unsplash.com');
}

function isVideoUrl(value) {
  return /\.(mp4|webm|ogg|mov)(\?|#|$)/i.test(cleanText(value).toLowerCase());
}

function initials(value) {
  const text = cleanText(value) || 'N';
  return escapeHtml(text.slice(0, 2).toUpperCase());
}

function formatDate(value) {
  const raw = cleanText(value);
  if (!raw) return '';
  return formatProjectUpdateDate(raw);
}

function renderBreadcrumb(project) {
  const category = cleanText(project.category);
  detailBreadcrumb.innerHTML = ui`
    <a href="/projects.html">项目库</a>
    ${category ? ui`<a href="/projects.html?category=${encodeURIComponent(category)}">${escapeHtml(category)}</a>` : ''}
    <span>${escapeHtml(project.name || tr('项目详情'))}</span>
  `;
}

function enabledCasTags(cas) {
  const tags = CAS_LABELS.filter(([key]) => Boolean(cas?.[key]));
  if (!tags.length) return ui`<span class="detail-chip muted">未标注 CAS</span>`;
  return tags.map(([key, label]) => (
    ui`<span class="detail-chip cas-${key}">${escapeHtml(label)}</span>`
  )).join('');
}

function mediaUrl(item) {
  return typeof item === 'object' && item !== null
    ? firstFilled(item.url, item.src, item.href, item.poster, item.cover, item.thumbnail)
    : cleanText(item);
}

function mediaKind(item) {
  if (typeof item !== 'object' || item === null) return '';
  return firstFilled(item.type, item.kind, item.mediaType).toLowerCase();
}

function renderHero(project) {
  const summary = truncateText(project.description || '', 128);
  const year = cleanText(project.year);
  const category = cleanText(project.category);

  return ui`
    <section class="card detail-hero">
      ${projectIconImage(project, { className: 'detail-hero-visual project-visual' })}
      <div class="detail-hero-copy">
        <h1>${escapeHtml(project.name || tr('未命名项目'))}</h1>
        <div class="detail-hero-meta">
          ${category ? ui`<span class="detail-chip primary">${escapeHtml(category)}</span>` : ''}
          ${year ? ui`<span class="detail-chip">${escapeHtml(year)}</span>` : ''}
        </div>
        ${summary ? ui`<p>${escapeHtml(summary)}</p>` : ''}
        <div class="detail-cas-tags">${enabledCasTags(project.cas)}</div>
      </div>
    </section>
  `;
}

function renderIntro(project) {
  return ui`
    <section class="card detail-intro">
      <div class="detail-section-copy">
        <h2><span></span>项目简介</h2>
        <p>${escapeHtml(project.description || tr('暂无项目简介。'))}</p>
      </div>
    </section>
  `;
}

function normalizeImages(value) {
  return asArray(value)
    .map((item) => ({ url: safeDetailUrl(mediaUrl(item)), kind: mediaKind(item) }))
    .filter((item) => item.url && (item.kind === 'image' || item.kind === 'photo' || isImageUrl(item.url)))
    .map((item) => item.url);
}

function normalizeVideos(value) {
  return asArray(value).map((item) => {
    if (typeof item === 'object' && item !== null) {
      const src = safeDetailUrl(firstFilled(item.url, item.src, item.href));
      if (!src) return null;
      return {
        src,
        poster: safeDetailUrl(firstFilled(item.poster, item.cover, item.thumbnail)),
        duration: cleanText(item.duration),
        title: cleanText(item.title),
      };
    }
    const src = safeDetailUrl(item);
    return src ? { src, poster: null, duration: '', title: '' } : null;
  }).filter(Boolean).filter((item) => {
    const source = asArray(value).find((candidate) => safeDetailUrl(mediaUrl(candidate)) === item.src);
    const kind = mediaKind(source);
    return kind.startsWith('video') || isVideoUrl(item.src) || item.poster;
  });
}

function metricValue(...values) {
  const value = values.find((item) => item !== undefined && item !== null && item !== '');
  if (value === undefined) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function normalizeUpdates(project) {
  const rawUpdates = asArray(project.updates);

  const updates = rawUpdates.map((item, index) => {
    if (item && typeof item === 'object') {
      const publisher = item.publisher || item.author || item.user || {};
      const boundMember = asArray(project.memberList).find(
        (member) => String(member?.personId || '') === String(item.authorPersonId || ''),
      ) || asArray(project.memberList).find(
        (member) => String(member?.userId || '') === String(item.authorUserId || ''),
      ) || {};
      const content = firstFilled(item.content, item.text, item.body, item.title, item.message);
      const images = [
        ...normalizeImages(item.images),
        ...normalizeImages(item.photos),
        ...normalizeImages(item.media),
      ];
      const videos = [
        ...normalizeVideos(item.video),
        ...normalizeVideos(item.videos),
        ...normalizeVideos(item.media),
      ];
      const metrics = item.metrics || {};
      const actions = item.actions || {};

      return {
        index,
        id: cleanText(item.id),
        author: firstFilled(boundMember.name, item.authorName, publisher.name, publisher.displayName, project.leader, tr('项目成员')),
        avatar: safeDetailUrl(firstFilled(boundMember.avatarUrl, publisher.avatar, item.avatar)),
        role: firstFilled(boundMember.role, item.authorRole, publisher.role, item.role, item.isLeader ? 'leader' : ''),
        date: firstFilled(item.createdAt, item.date, item.time),
        content,
        images,
        videos,
        likes: metricValue(item.likes, item.likeCount, item.likesCount, metrics.likes, metrics.likeCount, actions.likes, actions.likeCount),
        comments: metricValue(item.comments, item.commentCount, item.commentsCount, metrics.comments, metrics.commentCount, actions.comments, actions.commentCount),
        shares: metricValue(item.shares, item.shareCount, item.sharesCount, metrics.shares, metrics.shareCount, actions.shares, actions.shareCount),
        canDelete: Boolean(item.canDelete),
      };
    }

    return {
      index,
      id: '',
      author: firstFilled(project.leader, tr('项目成员')),
      avatar: null,
      role: index === 0 && project.leader ? 'leader' : 'member',
      date: '',
      content: cleanText(item),
      images: [],
      videos: [],
      likes: null,
      comments: null,
      shares: null,
      canDelete: false,
    };
  }).filter((item) => item.content || item.images.length || item.videos.length);

  return updates.sort((a, b) => {
    const timeA = projectUpdateTimestamp(a.date)?.getTime();
    const timeB = projectUpdateTimestamp(b.date)?.getTime();
    if (timeA === undefined || timeB === undefined || timeA === timeB) return a.index - b.index;
    return timeB - timeA;
  });
}

function renderMediaImages(images, title) {
  if (!images.length) return '';
  const visible = images.slice(0, 9);
  const more = images.length - visible.length;
  const mode = visible.length === 1 ? 'single' : visible.length <= 4 ? 'few' : 'many';
  return ui`
    <div class="feed-media-grid ${mode}">
      ${visible.map((url, index) => ui`
        <div class="feed-image image-frame">
          <img src="${escapeHtml(url)}" alt="${escapeHtml(title)} 动态图片 ${index + 1}" data-fallback loading="lazy" />
          ${more > 0 && index === visible.length - 1 ? ui`<span class="feed-more">+${more}</span>` : ''}
        </div>
      `).join('')}
    </div>
  `;
}

function renderVideos(videos, title) {
  if (!videos.length) return '';
  return ui`<div class="feed-video-list">${videos.map((video) => {
    if (isVideoUrl(video.src)) {
      return ui`
        <div class="feed-video">
          <video controls preload="metadata" ${video.poster ? `poster="${escapeHtml(video.poster)}"` : ''}>
            <source src="${escapeHtml(video.src)}" />
          </video>
          ${video.duration ? ui`<span>${escapeHtml(video.duration)}</span>` : ''}
        </div>
      `;
    }
    return ui`
      <a class="feed-video-link image-frame" href="${escapeHtml(video.src)}" target="_blank" rel="noreferrer">
        ${video.poster ? ui`<img src="${escapeHtml(video.poster)}" alt="${escapeHtml(video.title || title)} 视频封面" data-fallback loading="lazy" />` : ''}
        <span class="play-mark">▶</span>
        ${video.duration ? ui`<small>${escapeHtml(video.duration)}</small>` : ''}
      </a>
    `;
  }).join('')}</div>`;
}

function renderUpdateActions(item) {
  const actions = [
    item.likes !== null ? [tr('赞'), item.likes] : null,
    item.comments !== null ? [tr('评论'), item.comments] : null,
    item.shares !== null ? [tr('分享'), item.shares] : null,
  ].filter(Boolean);
  if (!actions.length) return '';
  return ui`<div class="feed-actions">${actions.map(([label, value]) => ui`<span>${label} ${escapeHtml(value)}</span>`).join('')}</div>`;
}

function renderFeed(project) {
  const updates = normalizeUpdates(project);
  const canCreateUpdate = Boolean(project.viewerPermissions?.canCreateUpdate);
  return ui`
    <section class="detail-panel feed-panel">
      <div class="detail-panel-head">
        <h2><span></span>CAS 动态</h2>
        <div class="detail-panel-actions">
          ${updates.length ? ui`<small>最新动态</small>` : ''}
          ${canCreateUpdate ? ui`<button class="button compact" type="button" data-open-project-update>提交动态</button>` : ''}
        </div>
      </div>
      ${updates.length ? ui`
        <div class="feed-list">
          ${updates.map((item) => ui`
            <article class="feed-card">
              <header class="feed-card-head">
                <span class="member-avatar feed-avatar" data-initial="${initials(item.author)}">
                  ${item.avatar ? ui`<img src="${escapeHtml(item.avatar)}" alt="${escapeHtml(item.author)}" data-fallback loading="lazy" />` : ''}
                </span>
                <div>
                  <strong>${escapeHtml(item.author)}</strong>
                  <div class="feed-meta">
                    ${item.role ? ui`<span>${memberRoleMarkup(item.role)}</span>` : ''}
                    <time>${item.date ? escapeHtml(formatDate(item.date)) : tr('发布时间未记录')}</time>
                  </div>
                </div>
                ${item.canDelete && item.id ? ui`
                  <button class="feed-delete-button" type="button" data-delete-project-update="${escapeHtml(item.id)}">删除</button>
                ` : ''}
              </header>
              ${item.content ? ui`<p>${escapeHtml(item.content)}</p>` : ''}
              ${renderMediaImages(item.images, project.name || tr('项目'))}
              ${renderVideos(item.videos, project.name || tr('项目'))}
              ${renderUpdateActions(item)}
            </article>
          `).join('')}
        </div>
      ` : ui`<div class="empty detail-empty">暂无项目动态。</div>`}
    </section>
  `;
}

function bindDetailInteractions() {
  document.querySelectorAll('img[data-fallback]:not(.member-avatar img)').forEach((img) => {
    img.addEventListener('error', () => {
      const frame = img.closest('.image-frame, .project-visual, .member-avatar');
      frame?.classList.remove('has-image');
      frame?.classList.add('is-failed');
      img.remove();
    }, { once: true });
  });

  projectMembers.bind(projectDetail);

  document.querySelector('[data-open-project-update]')?.addEventListener('click', openProjectUpdateModal);
  document.querySelectorAll('[data-delete-project-update]').forEach((button) => {
    button.addEventListener('click', deleteProjectUpdate);
  });

}

function renderProject(project) {
  currentProject = project;
  document.querySelector('#projectComments')?.classList.remove('is-hidden');
  document.title = `${project.name || tr('项目详情')} - NetHub Campus Wiki`;
  renderBreadcrumb(project);
  projectDetail.innerHTML = ui`
    ${renderHero(project)}
    ${renderIntro(project)}
    <div class="detail-main-grid">
      ${renderFeed(project)}
      ${projectMembers.render(project)}
    </div>
  `;
  bindDetailInteractions();
  mountCommentSection(document.querySelector('#projectComments'), 'project', project.id);
}

function setProjectUpdateMessage(message, isError = false) {
  projectUpdateMessage.textContent = message;
  projectUpdateMessage.classList.toggle('error', isError);
}

function resetProjectUpdateForm() {
  projectUpdateForm.reset();
  setUiText(projectUpdatePhotoSummary, () => tr('可一次多选，最多 9 张，单张不超过 5MB。'));
  setProjectUpdateMessage('');
}

function openProjectUpdateModal() {
  if (!currentProject?.viewerPermissions?.canCreateUpdate || projectUpdateSubmitting) return;
  resetProjectUpdateForm();
  projectUpdateModal.classList.add('is-open');
  projectUpdateModal.setAttribute('aria-hidden', 'false');
  document.body.classList.add('modal-open');
  window.setTimeout(() => projectUpdateContent.focus(), 0);
}

function closeProjectUpdateModal() {
  if (projectUpdateSubmitting) return;
  projectUpdateModal.classList.remove('is-open');
  projectUpdateModal.setAttribute('aria-hidden', 'true');
  document.body.classList.remove('modal-open');
  resetProjectUpdateForm();
}

function updateProjectPhotoSummary() {
  const count = projectUpdatePhotos.files.length;
  setUiText(projectUpdatePhotoSummary, () => count
    ? ut`已选择 ${count} 张照片${count > 9 ? tr('，超过 9 张上限') : ''}`
    : tr('可一次多选，最多 9 张，单张不超过 5MB。'));
}

async function deleteProjectUpdate(event) {
  const button = event.currentTarget;
  const updateId = cleanText(button.dataset.deleteProjectUpdate);
  if (!currentProject || !updateId) return;
  if (!window.confirm(tr('确定删除这条动态吗？动态照片也会从服务器永久删除。'))) return;

  const oldText = button.textContent;
  button.disabled = true;
  setUiText(button, () => tr('删除中……'));
  try {
    const result = await request(
      `/projects/${encodeURIComponent(currentProject.id)}/updates/${encodeURIComponent(updateId)}`,
      { method: 'DELETE' },
    );
    if (result.data?.moderationStatus === 'published') {
      const latest = await request(`/projects/${encodeURIComponent(currentProject.id)}?track=false`);
      renderProject(latest.data);
    } else {
      window.alert(tr('动态已提交审核，通过后公开。可在个人中心查看状态或撤回。'));
      renderProject(currentProject);
    }
  } catch (error) {
    button.disabled = false;
    button.textContent = oldText;
    window.alert(error.message);
  }
}

async function submitProjectUpdate(event) {
  event.preventDefault();
  if (projectUpdateSubmitting || !currentProject) return;

  const content = projectUpdateContent.value.trim();
  const photos = [...projectUpdatePhotos.files];
  if (!content && !photos.length) {
    setProjectUpdateMessage(tr('动态内容和照片不能同时为空。'), true);
    return;
  }
  if (photos.length > 9) {
    setProjectUpdateMessage(tr('每条动态最多上传 9 张照片。'), true);
    return;
  }
  const oversizedPhoto = photos.find((photo) => photo.size > MAX_PROJECT_UPDATE_PHOTO_BYTES);
  if (oversizedPhoto) {
    setProjectUpdateMessage(ut`照片“${oversizedPhoto.name}”超过 5MB。`, true);
    return;
  }

  const body = new FormData();
  body.append('content', content);
  photos.forEach((photo) => body.append('photos', photo));
  projectUpdateSubmitting = true;
  projectUpdateModal.classList.add('is-submitting');
  projectUpdateSubmit.disabled = true;
  setProjectUpdateMessage(tr('正在提交审核……'));
  try {
    const result = await request(`/projects/${encodeURIComponent(currentProject.id)}/updates`, {
      method: 'POST',
      body,
    });
    projectUpdateSubmitting = false;
    projectUpdateModal.classList.remove('is-submitting');
    projectUpdateSubmit.disabled = false;
    closeProjectUpdateModal();
    renderProject(result.data || currentProject);
    document.querySelector('.feed-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) {
    projectUpdateSubmitting = false;
    projectUpdateModal.classList.remove('is-submitting');
    projectUpdateSubmit.disabled = false;
    setProjectUpdateMessage(error.message, true);
  }
}

function bindProjectUpdateComposer() {
  projectUpdateForm?.addEventListener('submit', submitProjectUpdate);
  projectUpdatePhotos?.addEventListener('change', updateProjectPhotoSummary);
  document.querySelectorAll('[data-project-update-close]').forEach((item) => {
    item.addEventListener('click', closeProjectUpdateModal);
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && projectUpdateModal?.classList.contains('is-open')) {
      closeProjectUpdateModal();
    }
  });
}

function renderError(message) {
  document.querySelector('#projectComments')?.classList.add('is-hidden');
  detailBreadcrumb.innerHTML = ui`<a href="/projects.html">项目库</a><span>无法加载</span>`;
  projectDetail.innerHTML = ui`
    <section class="card detail-state">
      <h1>项目暂时无法显示</h1>
      <p>${escapeHtml(message || tr('请稍后重试。'))}</p>
      <a class="button secondary" href="/projects.html">返回项目库</a>
    </section>
  `;
}

async function loadDetail() {
  if (!id) {
    renderError(tr('缺少项目 ID。'));
    return;
  }

  try {
    const result = await request(`/projects/${encodeURIComponent(id)}`);
    renderProject(result.data || {});
  } catch (error) {
    renderError(error.message);
  }
}

bindProjectUpdateComposer();
loadDetail();
