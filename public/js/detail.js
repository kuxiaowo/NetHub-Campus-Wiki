const projectDetail = document.querySelector('#projectDetail');
const detailBreadcrumb = document.querySelector('#detailBreadcrumb');
const params = new URLSearchParams(window.location.search);
const id = params.get('id');

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
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return escapeHtml(raw);
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function renderBreadcrumb(project) {
  const category = cleanText(project.category);
  detailBreadcrumb.innerHTML = `
    <a href="/projects.html">项目库</a>
    ${category ? `<a href="/projects.html?category=${encodeURIComponent(category)}">${escapeHtml(category)}</a>` : ''}
    <span>${escapeHtml(project.name || '项目详情')}</span>
  `;
}

function enabledCasTags(cas) {
  const tags = CAS_LABELS.filter(([key]) => Boolean(cas?.[key]));
  if (!tags.length) return '<span class="detail-chip muted">未标注 CAS</span>';
  return tags.map(([key, label]) => (
    `<span class="detail-chip cas-${key}">${escapeHtml(label)}</span>`
  )).join('');
}

function collectProjectMedia(project) {
  return asArray(project.media)
    .map((item) => mediaUrl(item))
    .map(safeDetailUrl)
    .filter(Boolean);
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

function firstProjectImage(project) {
  const mediaImage = collectProjectMedia(project).find(isImageUrl);
  const icon = safeDetailUrl(project.icon);
  return icon || mediaImage || null;
}

function renderHero(project) {
  const image = firstProjectImage(project);
  const summary = truncateText(project.description || '', 128);
  const year = cleanText(project.year);
  const category = cleanText(project.category);

  return `
    <section class="card detail-hero">
      <div class="detail-hero-visual project-visual" data-initial="${initials(project.name)}">
        ${image ? `<img src="${escapeHtml(image)}" alt="${escapeHtml(project.name)}" data-fallback loading="lazy" />` : ''}
      </div>
      <div class="detail-hero-copy">
        <h1>${escapeHtml(project.name || '未命名项目')}</h1>
        <div class="detail-hero-meta">
          ${category ? `<span class="detail-chip primary">${escapeHtml(category)}</span>` : ''}
          ${year ? `<span class="detail-chip">${escapeHtml(year)}</span>` : ''}
        </div>
        ${summary ? `<p>${escapeHtml(summary)}</p>` : ''}
        <div class="detail-cas-tags">${enabledCasTags(project.cas)}</div>
      </div>
    </section>
  `;
}

function renderIntro(project) {
  return `
    <section class="card detail-intro">
      <div class="detail-section-copy">
        <h2><span></span>项目简介</h2>
        <p>${escapeHtml(project.description || '暂无项目简介。')}</p>
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
  const projectMedia = asArray(project.media);
  const fallbackDate = firstFilled(project.updatedAt, project.createdAt);

  const updates = rawUpdates.map((item, index) => {
    if (item && typeof item === 'object') {
      const publisher = item.publisher || item.author || item.user || {};
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
        author: firstFilled(publisher.name, publisher.displayName, item.authorName, project.leader, '项目成员'),
        avatar: safeDetailUrl(firstFilled(publisher.avatar, item.avatar)),
        role: firstFilled(publisher.role, item.authorRole, item.role, item.isLeader ? '负责人' : ''),
        date: firstFilled(item.createdAt, item.updatedAt, item.date, item.time, fallbackDate),
        content,
        images,
        videos,
        likes: metricValue(item.likes, item.likeCount, item.likesCount, metrics.likes, metrics.likeCount, actions.likes, actions.likeCount),
        comments: metricValue(item.comments, item.commentCount, item.commentsCount, metrics.comments, metrics.commentCount, actions.comments, actions.commentCount),
        shares: metricValue(item.shares, item.shareCount, item.sharesCount, metrics.shares, metrics.shareCount, actions.shares, actions.shareCount),
      };
    }

    return {
      index,
      author: firstFilled(project.leader, '项目成员'),
      avatar: null,
      role: index === 0 && project.leader ? '负责人' : '成员',
      date: fallbackDate,
      content: cleanText(item),
      images: [],
      videos: [],
      likes: null,
      comments: null,
      shares: null,
    };
  }).filter((item) => item.content || item.images.length || item.videos.length);

  const legacyMediaImages = normalizeImages(projectMedia);
  const legacyMediaVideos = normalizeVideos(projectMedia);
  if (legacyMediaImages.length || legacyMediaVideos.length) {
    updates.push({
      index: rawUpdates.length,
      author: firstFilled(project.leader, '项目成员'),
      avatar: null,
      role: project.leader ? '负责人' : '成员',
      date: fallbackDate,
      content: '',
      images: legacyMediaImages,
      videos: legacyMediaVideos,
      likes: null,
      comments: null,
      shares: null,
      isMediaOnly: true,
    });
  }

  return updates.sort((a, b) => {
    const timeA = new Date(a.date).getTime();
    const timeB = new Date(b.date).getTime();
    if (Number.isNaN(timeA) || Number.isNaN(timeB) || timeA === timeB) return a.index - b.index;
    return timeB - timeA;
  });
}

function renderMediaImages(images, title) {
  if (!images.length) return '';
  const visible = images.slice(0, 9);
  const more = images.length - visible.length;
  const mode = visible.length === 1 ? 'single' : visible.length <= 4 ? 'few' : 'many';
  return `
    <div class="feed-media-grid ${mode}">
      ${visible.map((url, index) => `
        <div class="feed-image image-frame">
          <img src="${escapeHtml(url)}" alt="${escapeHtml(title)} 动态图片 ${index + 1}" data-fallback loading="lazy" />
          ${more > 0 && index === visible.length - 1 ? `<span class="feed-more">+${more}</span>` : ''}
        </div>
      `).join('')}
    </div>
  `;
}

function renderVideos(videos, title) {
  if (!videos.length) return '';
  return `<div class="feed-video-list">${videos.map((video) => {
    if (isVideoUrl(video.src)) {
      return `
        <div class="feed-video">
          <video controls preload="metadata" ${video.poster ? `poster="${escapeHtml(video.poster)}"` : ''}>
            <source src="${escapeHtml(video.src)}" />
          </video>
          ${video.duration ? `<span>${escapeHtml(video.duration)}</span>` : ''}
        </div>
      `;
    }
    return `
      <a class="feed-video-link image-frame" href="${escapeHtml(video.src)}" target="_blank" rel="noreferrer">
        ${video.poster ? `<img src="${escapeHtml(video.poster)}" alt="${escapeHtml(video.title || title)} 视频封面" data-fallback loading="lazy" />` : ''}
        <span class="play-mark">▶</span>
        ${video.duration ? `<small>${escapeHtml(video.duration)}</small>` : ''}
      </a>
    `;
  }).join('')}</div>`;
}

function renderUpdateActions(item) {
  const actions = [
    item.likes !== null ? ['赞', item.likes] : null,
    item.comments !== null ? ['评论', item.comments] : null,
    item.shares !== null ? ['分享', item.shares] : null,
  ].filter(Boolean);
  if (!actions.length) return '';
  return `<div class="feed-actions">${actions.map(([label, value]) => `<span>${label} ${escapeHtml(value)}</span>`).join('')}</div>`;
}

function renderFeed(project) {
  const updates = normalizeUpdates(project);
  return `
    <section class="detail-panel feed-panel">
      <div class="detail-panel-head">
        <h2><span></span>CAS 动态</h2>
        ${updates.length ? '<small>最新动态</small>' : ''}
      </div>
      ${updates.length ? `
        <div class="feed-list">
          ${updates.map((item) => `
            <article class="feed-card">
              <header class="feed-card-head">
                <span class="member-avatar feed-avatar" data-initial="${initials(item.author)}">
                  ${item.avatar ? `<img src="${escapeHtml(item.avatar)}" alt="${escapeHtml(item.author)}" data-fallback loading="lazy" />` : ''}
                </span>
                <div>
                  <strong>${escapeHtml(item.author)}</strong>
                  <div class="feed-meta">
                    ${item.role ? `<span>${escapeHtml(item.role)}</span>` : ''}
                    ${item.date ? `<time>${formatDate(item.date)}</time>` : ''}
                  </div>
                </div>
              </header>
              ${item.content ? `<p>${escapeHtml(item.content)}</p>` : ''}
              ${renderMediaImages(item.images, project.name || '项目')}
              ${renderVideos(item.videos, project.name || '项目')}
              ${renderUpdateActions(item)}
            </article>
          `).join('')}
        </div>
      ` : '<div class="empty detail-empty">暂无项目动态。</div>'}
    </section>
  `;
}

function normalizeMembers(project) {
  const parsed = tryJson(project.members);
  const memberSources = [
    parsed,
    project.memberList,
    project.memberContacts,
    project.contacts,
  ].map(tryJson).find((value) => {
    if (Array.isArray(value)) return value.length;
    if (value && typeof value === 'object') return true;
    return cleanText(value);
  });
  let members;
  const memberFromObject = (member) => ({
    name: firstFilled(member.name, member.displayName, member.username),
    role: cleanText(member.role),
    avatar: safeDetailUrl(firstFilled(member.avatar, member.photo, member.image)),
    phone: firstFilled(member.phone, member.tel, member.mobile),
    email: firstFilled(member.email, member.mail),
    info: [member.className, member.class, member.grade, member.major, member.school].map(cleanText).filter(Boolean).join(' · '),
  });

  if (Array.isArray(memberSources)) {
    members = memberSources.map((member) => {
      if (member && typeof member === 'object') {
        return memberFromObject(member);
      }
      return { name: cleanText(member), role: '', avatar: null, phone: '', email: '', info: '' };
    });
  } else if (memberSources && typeof memberSources === 'object') {
    const nestedMembers = firstFilled(memberSources.members, memberSources.items, memberSources.list)
      ? asArray(memberSources.members || memberSources.items || memberSources.list)
      : [];
    members = (nestedMembers.length ? nestedMembers : [memberSources]).map((member) => {
      if (member && typeof member === 'object') {
        return memberFromObject(member);
      }
      return { name: cleanText(member), role: '', avatar: null, phone: '', email: '', info: '' };
    });
  } else {
    members = cleanText(memberSources)
      .split(/[,，、\n]/)
      .map((name) => ({ name: cleanText(name), role: '', avatar: null, phone: '', email: '', info: '' }));
  }

  const leader = cleanText(project.leader);
  members = members.filter((member) => member.name);
  if (leader && !members.some((member) => member.name === leader)) {
    members.unshift({ name: leader, role: '负责人', avatar: null, phone: '', email: '', info: '' });
  }

  return members.map((member) => ({
    ...member,
    role: member.role || (leader && member.name === leader ? '负责人' : '成员'),
  }));
}

function renderMembers(project) {
  const members = normalizeMembers(project);
  const collapsed = members.length > 5;
  return `
    <aside class="detail-panel member-panel">
      <div class="detail-panel-head">
        <h2><span></span>成员列表 / 联系方式</h2>
      </div>
      ${members.length ? `
        <div class="member-list">
          ${members.map((member, index) => `
            <article class="member-card ${collapsed && index >= 5 ? 'is-collapsed' : ''}">
              <span class="member-avatar" data-initial="${initials(member.name)}">
                ${member.avatar ? `<img src="${escapeHtml(member.avatar)}" alt="${escapeHtml(member.name)}" data-fallback loading="lazy" />` : ''}
              </span>
              <div class="member-body">
                <div class="member-title">
                  <strong>${escapeHtml(member.name)}</strong>
                  ${member.role ? `<span>${escapeHtml(member.role)}</span>` : ''}
                </div>
                ${member.info ? `<p>${escapeHtml(member.info)}</p>` : ''}
                <div class="member-contact">
                  ${member.phone ? `<a href="tel:${escapeHtml(member.phone)}">电话 ${escapeHtml(member.phone)}</a>` : ''}
                  ${member.email ? `<a href="mailto:${escapeHtml(member.email)}">邮箱 ${escapeHtml(member.email)}</a>` : ''}
                </div>
              </div>
            </article>
          `).join('')}
        </div>
        ${collapsed ? '<button class="member-more" type="button" data-toggle-members>查看全部成员</button>' : ''}
      ` : '<div class="empty detail-empty">暂无成员信息。</div>'}
    </aside>
  `;
}

function bindDetailInteractions() {
  document.querySelectorAll('img[data-fallback]').forEach((img) => {
    img.addEventListener('error', () => {
      const frame = img.closest('.image-frame, .project-visual, .member-avatar');
      frame?.classList.add('is-failed');
      img.remove();
    }, { once: true });
  });

  document.querySelector('[data-toggle-members]')?.addEventListener('click', (event) => {
    const panel = event.currentTarget.closest('.member-panel');
    const expanded = panel.classList.toggle('is-expanded');
    event.currentTarget.textContent = expanded ? '收起成员列表' : '查看全部成员';
  });
}

function renderProject(project) {
  document.title = `${project.name || '项目详情'} - NetHub Campus Wiki`;
  renderBreadcrumb(project);
  projectDetail.innerHTML = `
    ${renderHero(project)}
    ${renderIntro(project)}
    <div class="detail-main-grid">
      ${renderFeed(project)}
      ${renderMembers(project)}
    </div>
  `;
  bindDetailInteractions();
}

function renderError(message) {
  detailBreadcrumb.innerHTML = '<a href="/projects.html">项目库</a><span>无法加载</span>';
  projectDetail.innerHTML = `
    <section class="card detail-state">
      <h1>项目暂时无法显示</h1>
      <p>${escapeHtml(message || '请稍后重试。')}</p>
      <a class="button secondary" href="/projects.html">返回项目库</a>
    </section>
  `;
}

async function loadDetail() {
  if (!id) {
    renderError('缺少项目 ID。');
    return;
  }

  try {
    const result = await request(`/projects/${encodeURIComponent(id)}`);
    renderProject(result.data || {});
  } catch (error) {
    renderError(error.message);
  }
}

loadDetail();
