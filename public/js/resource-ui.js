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
    { value: 'photoCount', label: '照片最多' },
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

  function cardContent(title, year, image) {
    return `
      <span class="resource-thumb">${thumbnailMarkup(image)}</span>
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
    const content = cardContent(activity.activity, activity.year, image);
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
    const image = safeExternalUrl(item.thumbSrc || item.src);
    return `
      <button class="photo-item" type="button" ${dataAttribute}="${escapeHtml(item.index)}" aria-label="查看 ${escapeHtml(item.title)}">
        <img src="${escapeHtml(image)}" alt="${escapeHtml(item.title)}" loading="lazy" decoding="async">
      </button>
    `;
  }

  global.ResourceUI = Object.freeze({
    activityCard,
    photoItem,
    resourceCard,
    sortCombinedResources,
    sortOptions,
  });
}(window));
