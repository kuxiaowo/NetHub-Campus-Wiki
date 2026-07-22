const projectDetail = document.querySelector('#projectDetail');
const params = new URLSearchParams(window.location.search);
const id = params.get('id');

function parseFlexibleJson(value, fallback) {
  if (value == null || value === '') return fallback;
  if (Array.isArray(value) || typeof value === 'object') return value;
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

function splitLegacyMembers(value) {
  return String(value || '')
    .split(/[,，、]/)
    .map((name) => name.trim())
    .filter(Boolean);
}

function memberName(member) {
  return member?.name || member?.displayName || member?.username || '';
}

function avatarInitial(name) {
  const text = String(name || '同学').trim();
  return (text[0] || '同').toUpperCase();
}

function normalizeMembers(project) {
  const rawMembers = Array.isArray(project.memberDetails)
    ? project.memberDetails
    : parseFlexibleJson(project.members, null);
  const members = Array.isArray(rawMembers)
    ? rawMembers.map((member) => (typeof member === 'string' ? { name: member } : member))
    : splitLegacyMembers(project.members).map((name) => ({ name }));

  if (project.leader && !members.some((member) => memberName(member) === project.leader)) {
    members.unshift({ name: project.leader, role: '负责人' });
  }

  return members.map((member, index) => ({
    name: memberName(member) || `成员 ${index + 1}`,
    role: member.role || (memberName(member) === project.leader ? '负责人' : '成员'),
    avatar: member.avatar || member.image || '',
    className: member.className || member.class || member.grade || member.major || '',
    phone: member.phone || member.tel || '',
    email: member.email || '',
  }));
}

function mediaType(item) {
  const value = typeof item === 'string' ? item : item?.url || item?.src || '';
  const type = typeof item === 'object' ? item?.type : '';
  if (type === 'video') return 'video';
  if (type === 'image') return 'image';
  if (/\.(mp4|webm|ogg|mov)(\?.*)?$/i.test(value)) return 'video';
  return 'image';
}

function normalizeMedia(items) {
  return (items || [])
    .map((item) => {
      const url = typeof item === 'string' ? item : item?.url || item?.src || '';
      if (!url) return null;
      return {
        type: mediaType(item),
        url,
        poster: typeof item === 'object' ? item?.poster || item?.cover || item?.thumbnail || '' : '',
        duration: typeof item === 'object' ? item?.duration || '' : '',
        alt: typeof item === 'object' ? item?.alt || item?.title || '动态媒体' : '动态媒体',
      };
    })
    .filter(Boolean);
}

function normalizeUpdates(project, members) {
  const rawUpdates = parseFlexibleJson(project.updates, []);
  const legacyMedia = normalizeMedia(project.media);
  const fallbackAuthor = members[0] || { name: project.leader || '项目成员', role: '负责人' };
  const updates = Array.isArray(rawUpdates) ? rawUpdates : [];

  return updates.map((item, index) => {
    const isObject = item && typeof item === 'object' && !Array.isArray(item);
    const author = isObject ? item.author || item.publisher || item.user || {} : {};
    const authorName = author.name || author.displayName || item?.authorName || fallbackAuthor.name;
    const date = isObject
      ? item.publishedAt || item.createdAt || item.time || item.date || project.updatedAt || project.createdAt
      : project.updatedAt || project.createdAt;
    const media = isObject
      ? normalizeMedia([
        ...(item.images || []),
        ...(item.media || []),
        ...(item.video ? [item.video] : []),
        ...(item.videos || []),
      ])
      : (index === 0 ? legacyMedia : []);

    return {
      id: isObject ? item.id || index : index,
      authorName,
      authorRole: author.role || item?.authorRole || (authorName === project.leader ? '负责人' : fallbackAuthor.role),
      authorAvatar: author.avatar || item?.authorAvatar || fallbackAuthor.avatar || '',
      text: isObject ? item.text || item.content || item.body || '' : String(item || ''),
      date,
      media,
      likes: isObject ? item.likes || item.likeCount || 0 : 0,
      comments: isObject ? item.comments || item.commentCount || 0 : 0,
    };
  }).sort((a, b) => new Date(b.date || 0) - new Date(a.date || 0));
}

function formatPostDate(value) {
  if (!value) return '刚刚';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return escapeHtml(value);
  const datePart = date.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' });
  const timePart = date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
  return `${datePart} ${timePart}`;
}

function renderAvatar(url, name) {
  const safeUrl = safeExternalUrl(url);
  if (url && safeUrl !== '#') {
    return `<img class="avatar-image" src="${safeUrl}" alt="${escapeHtml(name)}" loading="lazy">`;
  }
  return `<span class="avatar-fallback">${escapeHtml(avatarInitial(name))}</span>`;
}

function renderActivityMedia(media) {
  const images = media.filter((item) => item.type === 'image').slice(0, 9);
  const videos = media.filter((item) => item.type === 'video');
  const parts = [];

  if (images.length) {
    const gridClass = images.length === 1
      ? 'single'
      : images.length <= 4
        ? 'compact'
        : 'dense';
    parts.push(`
      <div class="activity-image-grid ${gridClass}">
        ${images.map((item) => `
          <img src="${safeExternalUrl(item.url)}" alt="${escapeHtml(item.alt)}" loading="lazy">
        `).join('')}
      </div>
    `);
  }

  videos.forEach((item) => {
    parts.push(`
      <a class="activity-video" href="${safeExternalUrl(item.url)}" target="_blank" rel="noreferrer">
        ${item.poster ? `<img src="${safeExternalUrl(item.poster)}" alt="${escapeHtml(item.alt)}" loading="lazy">` : ''}
        <span class="activity-video-play" aria-hidden="true">▶</span>
        ${item.duration ? `<span class="activity-video-duration">${escapeHtml(item.duration)}</span>` : ''}
      </a>
    `);
  });

  return parts.length ? `<div class="activity-post-media">${parts.join('')}</div>` : '';
}

function renderActivityPost(post) {
  return `
    <article class="activity-post">
      <header class="activity-post-header">
        <div class="member-avatar">
          ${renderAvatar(post.authorAvatar, post.authorName)}
        </div>
        <div class="activity-post-author">
          <div>
            <strong>${escapeHtml(post.authorName)}</strong>
            <span class="role-tag">${escapeHtml(post.authorRole)}</span>
          </div>
          <time>${formatPostDate(post.date)}</time>
        </div>
      </header>
      ${post.text ? `<p class="activity-post-text">${escapeHtml(post.text)}</p>` : ''}
      ${renderActivityMedia(post.media)}
      <footer class="activity-post-actions" aria-label="动态操作">
        <button type="button">赞 ${escapeHtml(post.likes || '')}</button>
        <button type="button">评论 ${escapeHtml(post.comments || '')}</button>
        <button type="button">分享</button>
      </footer>
    </article>
  `;
}

function renderMemberCard(member) {
  const className = member.className ? `<span>${escapeHtml(member.className)}</span>` : '';
  const phone = member.phone
    ? `<a href="tel:${escapeHtml(member.phone)}">☎ ${escapeHtml(member.phone)}</a>`
    : '';
  const email = member.email
    ? `<a href="mailto:${escapeHtml(member.email)}">✉ ${escapeHtml(member.email)}</a>`
    : '';

  return `
    <article class="member-card">
      <div class="member-avatar">
        ${renderAvatar(member.avatar, member.name)}
      </div>
      <div class="member-card-body">
        <div class="member-card-title">
          <strong>${escapeHtml(member.name)}</strong>
          <span class="role-tag">${escapeHtml(member.role)}</span>
        </div>
        ${className ? `<div class="member-meta">${className}</div>` : ''}
        ${phone || email ? `<div class="member-contact">${phone}${email}</div>` : ''}
      </div>
    </article>
  `;
}

function renderProjectDetail(project) {
  const members = normalizeMembers(project);
  const posts = normalizeUpdates(project, members);
  const feedContent = posts.length
    ? posts.map(renderActivityPost).join('')
    : '<div class="empty">暂无 CAS 动态，新的项目进展会显示在这里。</div>';

  document.title = `${project.name} - 项目详情`;
  projectDetail.innerHTML = `
    <section class="card project-hero">
      ${projectIconImage(project)}
      <div class="project-hero-body">
        <h1>${escapeHtml(project.name)}</h1>
        <div class="meta">
          <span class="badge">${escapeHtml(project.category)}</span>
          <span>${escapeHtml(project.year)}</span>
        </div>
        ${casTags(project.cas)}
      </div>
    </section>

    <section class="card project-intro">
      <h2>项目简介</h2>
      <p>${escapeHtml(project.description)}</p>
    </section>

    <div class="project-detail-layout">
      <section class="project-feed">
        <div class="section-title">
          <h2>CAS 动态</h2>
        </div>
        ${feedContent}
      </section>

      <aside class="card member-sidebar">
        <h2>成员列表 / 联系方式</h2>
        <div class="member-list">
          ${members.length ? members.map(renderMemberCard).join('') : '<div class="empty">暂无成员信息</div>'}
        </div>
      </aside>
    </div>
  `;
}

async function loadDetail() {
  if (!id) throw new Error('缺少项目 ID');
  const result = await request(`/projects/${id}`);
  renderProjectDetail(result.data);
}

loadDetail().catch((error) => {
  projectDetail.innerHTML = `
    <div class="card detail-card">
      <div class="empty error">${escapeHtml(error.message)}。请确认后端和数据库已启动。</div>
    </div>
  `;
});
