const notificationList = document.querySelector('#notificationList');
const popularProjectList = document.querySelector('#popularProjectList');
const popularResourceList = document.querySelector('#popularResourceList');

function shortDate(value) {
  return formatSiteTimestamp(value, { month: '2-digit', day: '2-digit' });
}

function projectUpdateMediaUrl(item) {
  if (item && typeof item === 'object') {
    return item.url || item.src || item.href || item.poster || item.cover || item.thumbnail || '';
  }
  return item || '';
}

function latestProjectUpdatePhoto(project) {
  const updates = Array.isArray(project.updates) ? project.updates : [];
  const latest = updates
    .map((update, index) => ({
      update,
      index,
      date: update && typeof update === 'object'
        ? update.createdAt || update.date || update.time || ''
        : '',
    }))
    .sort((left, right) => {
      const leftTime = projectUpdateTimestamp(left.date)?.getTime();
      const rightTime = projectUpdateTimestamp(right.date)?.getTime();
      if (leftTime === undefined || rightTime === undefined || leftTime === rightTime) {
        return left.index - right.index;
      }
      return rightTime - leftTime;
    })[0]?.update;

  if (!latest || typeof latest !== 'object') return '';
  const media = [latest.images, latest.photos, latest.media]
    .find((items) => Array.isArray(items) && items.length);
  if (!media) return '';

  const imageUrl = safeExternalUrl(projectUpdateMediaUrl(media[0]));
  return imageUrl === '#' ? '' : imageUrl;
}

function popularProjectCard(project, index) {
  const updatePhoto = latestProjectUpdatePhoto(project);
  return `
    <a class="home-popular-card" href="/detail.html?id=${encodeURIComponent(project.id)}">
      <div class="home-popular-media project-media${updatePhoto ? ' has-update-photo' : ''}">
        ${updatePhoto ? `<img class="home-project-update-photo" src="${escapeHtml(updatePhoto)}" alt="" loading="lazy" decoding="async" data-project-update-photo>` : ''}
        <b class="home-popular-rank">${index + 1}</b>
        ${projectIconImage(project)}
      </div>
      <div class="home-popular-body">
        <span class="home-popular-meta"><em>${escapeHtml(project.category)}</em><small>${escapeHtml(project.year)}</small></span>
        <strong>${escapeHtml(project.name)}</strong>
        <p class="home-popular-description">${escapeHtml(project.description || '')}</p>
        <div class="home-popular-tags" aria-label="CAS 类型">${project.cas?.creativity ? '<span>C</span>' : ''}${project.cas?.activity ? '<span>A</span>' : ''}${project.cas?.service ? '<span>S</span>' : ''}</div>
        <span class="home-popular-hot">热度 ${escapeHtml(project.popularity || 0)} <i aria-hidden="true">→</i></span>
      </div>
    </a>
  `;
}

document.addEventListener('error', (event) => {
  const image = event.target;
  if (!(image instanceof HTMLImageElement) || !image.matches('[data-project-update-photo]')) return;
  image.closest('.project-media')?.classList.remove('has-update-photo');
  image.remove();
}, true);

function popularResourceCard(resource, index) {
  const image = safeExternalUrl(resource.image);
  const href = resource.href || (resource.category === 'yearbook'
    ? `/resources.html?yearbook=${encodeURIComponent(resource.id)}`
    : `/resource.html?id=${encodeURIComponent(resource.id)}`);
  const thumbnail = image === '#'
    ? '<span class="home-popular-placeholder" aria-hidden="true"></span>'
    : `<img src="${image}" alt="" loading="lazy" decoding="async">`;

  return `
    <a class="home-popular-card" href="${escapeHtml(href)}">
      <div class="home-popular-media resource-media">
        <b class="home-popular-rank">${index + 1}</b>
        ${thumbnail}
      </div>
      <div class="home-popular-body">
        <span class="home-popular-meta"><em>${escapeHtml(resource.label || '资源')}</em><small>${escapeHtml(resource.year)}</small></span>
        <strong>${escapeHtml(resource.title)}</strong>
        <p class="home-popular-description">${escapeHtml(resource.description || '')}</p>
        <span class="home-popular-hot">热度 ${escapeHtml(resource.hot || 0)} <i aria-hidden="true">→</i></span>
      </div>
    </a>
  `;
}

async function loadNotifications() {
  const result = await request('/announcements?page=1&pageSize=3');
  notificationList.innerHTML = result.data.length
    ? result.data.map((notification) => `
        <li>
          <a href="/announcement.html?id=${encodeURIComponent(notification.id)}">
            <span>${notification.isPinned ? '<b>置顶</b>' : ''}<strong>${escapeHtml(notification.title)}</strong></span>
            <time>${escapeHtml(shortDate(notification.publishedAt))}</time>
          </a>
        </li>
      `).join('')
    : '<li class="home-notification-empty">暂无通知</li>';
}

async function loadPopularProjects() {
  const result = await request('/projects?sort=popular&limit=3');
  const projects = result.data;
  popularProjectList.innerHTML = projects.length
    ? projects.map(popularProjectCard).join('')
    : '<div class="empty">还没有项目。</div>';
}

async function loadPopularResources() {
  const [resourceResult, photoResult] = await Promise.all([
    request('/resources?sort=hot&limit=3'),
    request('/photo-activities?sort=hot&limit=3'),
  ]);
  const resources = [
    ...resourceResult.data,
    ...photoResult.data.map((activity) => ({
      id: activity.id,
      label: '活动照片',
      title: activity.activity,
      year: activity.year,
      hot: activity.hot,
      image: activity.coverThumbSrc || activity.coverSrc || '',
      href: '/resources.html?category=photos',
      createdAt: activity.createdAt,
    })),
  ].sort((left, right) => (right.hot || 0) - (left.hot || 0)).slice(0, 3);
  popularResourceList.innerHTML = resources.length
    ? resources.map(popularResourceCard).join('')
    : '<div class="empty">还没有资源。</div>';
}

loadNotifications().catch(() => {
  notificationList.innerHTML = '<li class="home-notification-empty error">通知暂时无法加载</li>';
});

loadPopularProjects().catch((error) => {
  popularProjectList.innerHTML = `<div class="empty error">${escapeHtml(error.message)}。热门项目暂时无法加载。</div>`;
});

loadPopularResources().catch((error) => {
  popularResourceList.innerHTML = `<div class="empty error">${escapeHtml(error.message)}。热门资源暂时无法加载。</div>`;
});

let homePageTransitionTarget = null;

function initHomeMotion() {
  if (!('IntersectionObserver' in window) || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  const sections = document.querySelectorAll(
    '.home-showcase-section, .home-projects-section, .home-resources-section, .home-cta-section',
  );
  let observerResponded = false;
  const observer = new IntersectionObserver((entries) => {
    observerResponded = true;
    entries.forEach((entry) => {
      if (entry.intersectionRatio >= 0.2 && entry.target !== homePageTransitionTarget) {
        entry.target.classList.add('is-visible');
      } else if (entry.intersectionRatio <= 0.05) {
        entry.target.classList.remove('is-visible');
      }
    });
  }, { threshold: [0, 0.05, 0.2, 0.4] });

  sections.forEach((section) => observer.observe(section));
  document.documentElement.classList.add('home-motion-ready');
  window.setTimeout(() => {
    if (!observerResponded) document.documentElement.classList.remove('home-motion-ready');
  }, 1500);
}

initHomeMotion();

function initHomePageTransitions() {
  const sections = [...document.querySelectorAll(
    '.home-hero-section, .home-showcase-section, .home-projects-section, .home-resources-section, .home-cta-section',
  )];
  const footer = document.querySelector('.site-footer');
  if (sections.length !== 5 || !footer || !window.requestAnimationFrame) return;

  const desktop = window.matchMedia('(min-width: 901px)');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const duration = 720;
  const wheelThreshold = 80;
  let wheelAccumulator = 0;
  let lastWheelTime = 0;
  let cooldownUntil = 0;
  let isPageTransitioning = false;
  let pageFrame = 0;
  let cleanupTimer = 0;
  let sourceSection = null;
  let targetSection = null;

  function pageEase(progress) {
    let low = 0;
    let high = 1;
    for (let index = 0; index < 12; index += 1) {
      const parameter = (low + high) / 2;
      const inverse = 1 - parameter;
      const x = 3 * inverse * inverse * parameter * .76
        + 3 * inverse * parameter * parameter * .24
        + parameter * parameter * parameter;
      if (x < progress) low = parameter;
      else high = parameter;
    }
    const parameter = (low + high) / 2;
    return 3 * (1 - parameter) * parameter * parameter + parameter ** 3;
  }

  function clearPageClasses() {
    [sourceSection, targetSection].forEach((section) => {
      section?.classList.remove('is-page-leaving', 'is-page-entering', 'is-page-arriving', 'page-up');
    });
    sourceSection = null;
    targetSection = null;
  }

  function cancelPageTransition() {
    window.cancelAnimationFrame(pageFrame);
    window.clearTimeout(cleanupTimer);
    isPageTransitioning = false;
    wheelAccumulator = 0;
    homePageTransitionTarget = null;
    if (targetSection) {
      const bounds = targetSection.getBoundingClientRect();
      if (bounds.top < window.innerHeight * .8 && bounds.bottom > window.innerHeight * .2) {
        targetSection.classList.add('is-visible');
      }
    }
    clearPageClasses();
  }

  function pageTargetY(section) {
    const maximum = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
    return Math.min(section.offsetTop, maximum);
  }

  function startPageTransition(current, next, direction) {
    window.clearTimeout(cleanupTimer);
    clearPageClasses();
    sourceSection = current;
    targetSection = next;
    homePageTransitionTarget = next;
    next.classList.remove('is-visible');
    current.classList.add('is-page-leaving');
    next.classList.add('is-page-entering');
    if (direction < 0) {
      current.classList.add('page-up');
      next.classList.add('page-up');
    }

    isPageTransitioning = true;
    wheelAccumulator = 0;
    const startY = window.scrollY;
    const startedAt = performance.now();
    let arriving = false;

    function frame(now) {
      try {
        if (!desktop.matches || reducedMotion.matches || document.hidden) {
          cancelPageTransition();
          return;
        }
        const progress = Math.min(1, (now - startedAt) / duration);
        window.scrollTo(0, startY + (pageTargetY(next) - startY) * pageEase(progress));
        if (!arriving && progress >= .65) {
          next.classList.add('is-page-arriving');
          arriving = true;
        }
        if (progress < 1) {
          pageFrame = window.requestAnimationFrame(frame);
          return;
        }
        window.scrollTo(0, pageTargetY(next));
        homePageTransitionTarget = null;
        next.classList.add('is-visible');
        isPageTransitioning = false;
        cooldownUntil = performance.now() + 260;
        cleanupTimer = window.setTimeout(clearPageClasses, 260);
      } catch {
        cancelPageTransition();
      }
    }

    pageFrame = window.requestAnimationFrame(frame);
  }

  function activeSectionIndex() {
    const probe = window.scrollY + window.innerHeight * .25;
    for (let index = sections.length - 1; index >= 0; index -= 1) {
      if (sections[index].offsetTop <= probe) return index;
    }
    return 0;
  }

  function canTurnPage(direction) {
    if (!desktop.matches || reducedMotion.matches || document.hidden) return null;
    if (footer.getBoundingClientRect().top < window.innerHeight) return null;
    const index = activeSectionIndex();
    const nextIndex = index + direction;
    if (nextIndex < 0 || nextIndex >= sections.length) return null;
    const current = sections[index];
    const next = sections[nextIndex];
    if (current.scrollHeight > window.innerHeight + 2 || next.scrollHeight > window.innerHeight + 2) return null;
    return { current, next };
  }

  function hasInteractiveFocus() {
    const active = document.activeElement;
    return active && active !== document.body && active !== document.documentElement
      && active.matches('a, button, input, textarea, select, [contenteditable]')
      && active.getClientRects().length > 0;
  }

  function overScrollableRegion(event) {
    return event.composedPath().some((item) => {
      if (!(item instanceof Element) || item === document.body) return false;
      const overflow = window.getComputedStyle(item).overflowY;
      return /^(auto|scroll)$/.test(overflow) && item.scrollHeight > item.clientHeight + 1;
    });
  }

  window.addEventListener('wheel', (event) => {
    if (event.defaultPrevented || event.ctrlKey || event.metaKey || hasInteractiveFocus() || overScrollableRegion(event)) {
      if (isPageTransitioning) cancelPageTransition();
      return;
    }
    if (!desktop.matches || reducedMotion.matches || document.hidden) return;
    if (!isPageTransitioning && footer.getBoundingClientRect().top < window.innerHeight) return;
    const now = performance.now();
    if (isPageTransitioning || now < cooldownUntil) {
      event.preventDefault();
      if (!isPageTransitioning) cooldownUntil = now + 260;
      return;
    }
    const multiplier = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? window.innerHeight : 1;
    const delta = event.deltaY * multiplier;
    if (!delta) return;
    if (now - lastWheelTime > 220 || Math.sign(delta) !== Math.sign(wheelAccumulator)) wheelAccumulator = 0;
    lastWheelTime = now;
    wheelAccumulator += delta;
    if (Math.abs(wheelAccumulator) < wheelThreshold) return;
    const direction = Math.sign(wheelAccumulator);
    wheelAccumulator = 0;
    const page = canTurnPage(direction);
    if (!page) return;
    event.preventDefault();
    startPageTransition(page.current, page.next, direction);
  }, { passive: false });

  window.addEventListener('keydown', (event) => {
    if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || hasInteractiveFocus()) return;
    const direction = event.key === 'PageDown' || event.key === 'ArrowDown' ? 1
      : event.key === 'PageUp' || event.key === 'ArrowUp' ? -1 : 0;
    if (!direction || !desktop.matches || reducedMotion.matches) return;
    if (isPageTransitioning) {
      event.preventDefault();
      return;
    }
    const page = canTurnPage(direction);
    if (!page) return;
    event.preventDefault();
    startPageTransition(page.current, page.next, direction);
  });

  desktop.addEventListener('change', cancelPageTransition);
  reducedMotion.addEventListener('change', cancelPageTransition);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden && isPageTransitioning) cancelPageTransition();
  });
}

initHomePageTransitions();
