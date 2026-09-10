(function createResourceUi(global) {
  'use strict';

  const resourceSortOptions = Object.freeze([
    { value: 'hot', label: '最热' },
    { value: 'new', label: '最新' },
    { value: 'download', label: '下载最多' },
    { value: 'old', label: '最早' },
  ]);
  const photoSortOptions = Object.freeze([
    { value: 'hot', label: '最热' },
    { value: 'new', label: '最新' },
    { value: 'download', label: '下载最多' },
    { value: 'photoCount', label: '内容最多' },
    { value: 'old', label: '最早' },
  ]);

  function itemTimestamp(item) {
    const timestamp = Date.parse(item.createdAt || item.updatedAt || '');
    return Number.isFinite(timestamp) ? timestamp : 0;
  }

  function sortOptions(category) {
    return category === 'photos' ? photoSortOptions : resourceSortOptions;
  }

  function sortCombinedResources(items, sort) {
    return [...items].sort((left, right) => {
      if (sort === 'download') {
        return (right.data.downloads || 0) - (left.data.downloads || 0);
      }
      if (sort === 'new') {
        return (right.data.year - left.data.year) || (itemTimestamp(right.data) - itemTimestamp(left.data));
      }
      if (sort === 'old') {
        return (left.data.year - right.data.year) || (itemTimestamp(left.data) - itemTimestamp(right.data));
      }
      return (right.data.hot - left.data.hot) || (itemTimestamp(right.data) - itemTimestamp(left.data));
    });
  }

  function thumbnailMarkup(source) {
    const image = source ? safeExternalUrl(source) : '#';
    return image && image !== '#'
      ? `<img src="${escapeHtml(image)}" alt="" loading="lazy" decoding="async">`
      : '<span class="resource-thumb-placeholder" aria-hidden="true"></span>';
  }

  const playMarker = '<span class="media-play-marker" aria-hidden="true">▶</span>';

  function cardContent(title, year, image, isVideo = false) {
    return `
      <span class="resource-thumb">${thumbnailMarkup(image)}${isVideo ? playMarker : ''}</span>
      <span class="resource-body">
        <h2>${escapeHtml(title)}</h2>
        <span class="resource-year">${escapeHtml(year)}</span>
      </span>
    `;
  }

  function managementAction(attribute, id, label = '编辑') {
    if (!attribute) return '';
    return `
      <span class="resource-card-admin-actions">
        <button class="button compact" type="button" ${attribute}="${escapeHtml(id)}">${escapeHtml(label)}</button>
      </span>
    `;
  }

  function resourceCard(resource, options = {}) {
    const defaultHref = resource.category === 'yearbook'
      ? `/resources.html?yearbook=${encodeURIComponent(resource.id)}`
      : `/resource.html?id=${encodeURIComponent(resource.id)}`;
    const href = options.href || defaultHref;
    const content = cardContent(resource.title, resource.year, resource.image);
    if (!options.managed) {
      return `
        <a class="resource-card resource-summary-card" href="${escapeHtml(href)}" aria-label="查看 ${escapeHtml(resource.title)}（${escapeHtml(resource.year)}）">
          ${content}
        </a>
      `;
    }
    return `
      <article class="resource-card resource-summary-card managed-resource-card">
        <a class="resource-card-main" href="${escapeHtml(href)}" ${options.newTab ? 'target="_blank" rel="noopener noreferrer"' : ''} aria-label="预览 ${escapeHtml(resource.title)}（${escapeHtml(resource.year)}）">
          ${content}
        </a>
        ${managementAction(options.editAttribute, resource.id, options.editLabel)}
      </article>
    `;
  }

  function activityCard(activity, options = {}) {
    const image = options.image || activity.coverThumbSrc || activity.coverSrc || '';
    const content = cardContent(activity.activity, activity.year, image, activity.coverType === 'video');
    const dataAttribute = options.dataAttribute || 'data-resource-activity-id';
    if (!/^[a-z0-9-]+$/i.test(dataAttribute)) throw new Error('非法的活动卡片属性');
    if (!options.managed) {
      return `
        <button class="resource-card resource-summary-card photo-activity-card" type="button" ${dataAttribute}="${escapeHtml(activity.id)}" aria-label="查看 ${escapeHtml(activity.activity)}（${escapeHtml(activity.year)}）">
          ${content}
        </button>
      `;
    }
    return `
      <article class="resource-card resource-summary-card photo-activity-card managed-resource-card">
        <button class="resource-card-main" type="button" ${dataAttribute}="${escapeHtml(activity.id)}" aria-label="查看 ${escapeHtml(activity.activity)}（${escapeHtml(activity.year)}）">
          ${content}
        </button>
        ${managementAction(options.editAttribute, activity.id, options.editLabel)}
      </article>
    `;
  }

  function photoItem(item, options = {}) {
    const dataAttribute = options.dataAttribute || 'data-photo-index';
    if (!/^[a-z0-9-]+$/i.test(dataAttribute)) throw new Error('非法的照片属性');
    const isVideo = item.type === 'video';
    const image = isVideo ? item.thumbSrc : (item.thumbSrc || item.src);
    return `
      <button class="photo-item${isVideo ? ' is-video' : ''}" type="button" ${dataAttribute}="${escapeHtml(item.index)}" aria-label="查看${isVideo ? '视频' : '照片'} ${escapeHtml(item.title)}">
        ${thumbnailMarkup(image)}
        ${isVideo ? playMarker : ''}
      </button>
    `;
  }

  function mediaCounts(value) {
    if (Array.isArray(value)) {
      const videoCount = value.filter((item) => item.type === 'video').length;
      return { photoCount: value.length - videoCount, videoCount };
    }
    return { photoCount: value.photoCount, videoCount: value.videoCount };
  }

  function mediaCountText(value) {
    const counts = mediaCounts(value);
    return `${counts.photoCount} 张照片 · ${counts.videoCount} 个视频`;
  }

  function activityTotalText(activities) {
    return mediaCountText(activities.reduce((total, activity) => ({
      photoCount: total.photoCount + activity.photoCount,
      videoCount: total.videoCount + activity.videoCount,
    }), { photoCount: 0, videoCount: 0 }));
  }

  function clearModalMedia(image) {
    const stage = image.closest('.photo-modal-stage');
    const video = stage.querySelector('video');
    video.onerror = null;
    if (video.hasAttribute('src')) {
      video.pause();
      video.removeAttribute('src');
      video.load();
    }
    video.removeAttribute('poster');
    video.hidden = true;
    stage.querySelector('.media-playback-error').hidden = true;
    image.removeAttribute('src');
    image.hidden = true;
  }

  function showModalMedia(image, item) {
    clearModalMedia(image);
    if (item.type !== 'video') {
      image.src = safeExternalUrl(item.src);
      image.alt = item.title || '';
      image.hidden = false;
      return;
    }
    const stage = image.closest('.photo-modal-stage');
    const video = stage.querySelector('video');
    video.setAttribute('aria-label', item.title || '活动视频');
    video.onerror = () => { stage.querySelector('.media-playback-error').hidden = false; };
    if (item.thumbSrc) video.poster = safeExternalUrl(item.thumbSrc);
    video.src = safeExternalUrl(item.src);
    video.hidden = false;
  }

  global.ResourceUI = Object.freeze({
    activityCard,
    photoItem,
    resourceCard,
    sortCombinedResources,
    sortOptions,
    mediaCountText,
    activityTotalText,
    showModalMedia,
    clearModalMedia,
  });
}(window));
