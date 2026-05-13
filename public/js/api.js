// 统一封装 API 请求，方便后续替换接口前缀或做登录鉴权。
const API_BASE = window.CAMPUS_WIKI_CONFIG?.apiBaseUrl || 'http://127.0.0.1:3100/api';

/**
 * 请求后端 API。
 *
 * path 只传 /api 后面的路径，例如 /projects。真实服务地址由 config.js 提供，
 * 这样前端服务和后端服务可以独立部署。
 */
async function request(path) {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.message || `请求失败：${response.status}`);
  }
  return response.json();
}

/**
 * 转义 HTML 特殊字符。
 *
 * 项目名称、负责人、简介等字段未来可能来自用户提交。渲染到 innerHTML 前统一
 * 转义，避免数据中包含 <script> 或事件属性时被浏览器当作 HTML 执行。
 */
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[char]));
}

/**
 * 截断长文本，避免卡片里简介过长导致布局被撑开。
 */
function truncateText(value, maxLength) {
  const text = String(value ?? '');
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text;
}

/**
 * 过滤外部链接。
 *
 * 媒体链接来自数据库，理论上也可能被用户提交。这里只允许 http/https，
 * 其他协议统一替换为 #，避免 javascript: 这类链接被点击执行。
 */
function safeExternalUrl(value) {
  try {
    const url = new URL(String(value ?? ''), window.location.origin);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : '#';
  } catch {
    return '#';
  }
}

/**
 * 渲染 CAS 三项标记。
 *
 * C/A/S 三个字母固定来自代码，不需要转义；状态来自布尔值，只控制 class。
 */
function casTags(cas) {
  const items = [
    ['C', Boolean(cas?.creativity), 'Creativity'],
    ['A', Boolean(cas?.activity), 'Activity'],
    ['S', Boolean(cas?.service), 'Service'],
  ];
  return `<div class="cas-tags">${items.map(([letter, enabled, title]) =>
    `<span class="cas-tag ${enabled ? 'on' : ''}" title="${title}">${letter}</span>`
  ).join('')}</div>`;
}

/**
 * 首页推荐项目卡片。
 */
function projectCard(project) {
  const projectId = encodeURIComponent(project.id);
  const description = escapeHtml(truncateText(project.description, 86));

  return `
    <a class="project-card" href="/detail.html?id=${projectId}">
      <div class="project-icon">${escapeHtml(project.icon)}</div>
      <h3>${escapeHtml(project.name)}</h3>
      <div class="meta">
        <span class="badge">${escapeHtml(project.category)}</span>
        <span>${escapeHtml(project.year)}</span>
        <span>负责人：${escapeHtml(project.leader)}</span>
      </div>
      <p>${description}</p>
      ${casTags(project.cas)}
    </a>
  `;
}
