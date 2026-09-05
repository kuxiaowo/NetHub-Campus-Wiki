// 统一封装 API 请求，方便后续替换接口前缀或做登录鉴权。
const API_BASE = window.CAMPUS_WIKI_CONFIG?.apiBaseUrl || '/api';

/**
 * 请求后端 API。
 *
 * path 只传 /api 后面的路径，例如 /projects。真实服务地址由 config.js 提供，
 * 这样前端服务和后端服务可以独立部署。
 */
const AUTH_USER_KEY = 'campusWikiAuthUser';
const PROTECTED_FILE_EXTENSIONS = new Set([
  '.jpg', '.jpeg', '.png', '.webp', '.gif',
  '.pdf', '.zip', '.rar', '.7z',
  '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
]);
const PROTECTED_FILE_DIRS = new Set(['photos', 'yearbook']);

async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    credentials: 'include',
    headers,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    let detail = error.detail;
    if (Array.isArray(detail)) {
      detail = detail.map((item) => item.msg).filter(Boolean).join('；');
    } else if (detail && typeof detail === 'object') {
      const issueItems = Array.isArray(detail.errors) ? detail.errors : detail.warnings;
      const issueText = Array.isArray(issueItems)
        ? issueItems.map((item) => `${item.path || 'document'}：${item.message || '格式不正确'}`).join('\n')
        : '';
      detail = [detail.message, issueText].filter(Boolean).join('\n');
    }
    throw new Error(detail || error.message || `请求失败：${response.status}`);
  }
  if (response.status === 204) return null;
  return response.json();
}

function getAuthToken() {
  // Compatibility name used by page modules. The real credential is an
  // HttpOnly cookie and is deliberately unavailable to JavaScript.
  return getStoredUser() ? 'cookie-session' : null;
}

function getStoredUser() {
  try {
    return JSON.parse(window.localStorage.getItem(AUTH_USER_KEY) || 'null');
  } catch {
    return null;
  }
}

function saveAuthSession(_token, user) {
  window.localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user));
  window.dispatchEvent(new CustomEvent('campusWikiAuthChange', { detail: { user } }));
}

function clearAuthSession() {
  window.localStorage.removeItem(AUTH_USER_KEY);
  window.dispatchEvent(new CustomEvent('campusWikiAuthChange', { detail: { user: null } }));
}

function roleLabel(role) {
  return role === 'admin' ? '管理员' : '普通用户';
}

function userInitial(user) {
  const name = String(user?.displayName || user?.username || '登').trim();
  return (name[0] || '登').toUpperCase();
}

function userAvatarImage(user) {
  const avatarUrl = user?.avatarUrl ? safeExternalUrl(user.avatarUrl) : null;
  return avatarUrl && avatarUrl !== '#'
    ? `<img src="${escapeHtml(avatarUrl)}" alt="" />`
    : '';
}

let globalMessageBadgeTimer = null;

function ensureSocialNav() {
  const navLinks = document.querySelector('.nav-links');
  navLinks?.querySelectorAll('a[href="/messages.html"]').forEach((link) => link.remove());
}

function messageNavMarkup() {
  const isCurrentPage = window.location.pathname === '/messages.html';
  return `
    <a class="message-nav-link${isCurrentPage ? ' active' : ''}" href="/messages.html"
      aria-label="消息中心"${isCurrentPage ? ' aria-current="page"' : ''}>
      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path d="M4 6.5h16v11H4z"></path>
        <path d="m4.5 7 7.5 6 7.5-6"></path>
      </svg>
      <span class="message-nav-badge is-hidden">0</span>
    </a>
  `;
}

async function refreshGlobalMessageBadge() {
  const badges = document.querySelectorAll('.message-nav-badge');
  if (!badges.length) return;
  if (!getAuthToken()) {
    badges.forEach((badge) => {
      badge.classList.add('is-hidden');
      badge.closest('.message-nav-link')?.setAttribute('aria-label', '消息中心');
    });
    return;
  }
  try {
    const result = await request('/message-center/unread-count');
    const total = Number(result.total || 0);
    badges.forEach((badge) => {
      badge.textContent = total > 99 ? '99+' : String(total);
      badge.classList.toggle('is-hidden', !total);
      badge.closest('.message-nav-link')?.setAttribute(
        'aria-label',
        total ? `消息中心，${total} 条未读消息` : '消息中心',
      );
    });
  } catch {
    badges.forEach((badge) => {
      badge.classList.add('is-hidden');
      badge.closest('.message-nav-link')?.setAttribute('aria-label', '消息中心');
    });
  }
}

function loginUser({ silent = false } = {}) {
  const returnTo = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (!silent) {
    window.sessionStorage.removeItem('campus-wiki-sso-probe');
    window.localStorage.removeItem('campus-wiki-sso-suppressed-until');
  }
  const prompt = silent ? '&prompt=none' : '';
  const loginUrl = `${apiBaseUrl()}/auth/login?returnTo=${encodeURIComponent(returnTo)}${prompt}`;
  if (silent) {
    window.location.assign(loginUrl);
    return;
  }
  window.open(loginUrl, '_blank', 'noopener,noreferrer');
}

function changeCurrentUserPassword() {
  const accountsBaseUrl = window.CAMPUS_WIKI_CONFIG?.accountsBaseUrl || 'https://auth.nethub.wiki';
  window.open(`${accountsBaseUrl.replace(/\/$/, '')}/account`, '_blank', 'noopener,noreferrer');
}

async function updateCurrentUsername(username) {
  return request('/auth/me', {
    method: 'PATCH',
    body: JSON.stringify({ username }),
  });
}

async function refreshCurrentUser() {
  try {
    const user = await request('/auth/me');
    window.localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user));
    return user;
  } catch (error) {
    clearAuthSession();
    return null;
  }
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

function apiBaseUrl() {
  return String(API_BASE).replace(/\/$/, '');
}

function publicFilePath(value) {
  const rawValue = String(value ?? '').trim();
  if (!rawValue) return null;

  let url;
  try {
    url = new URL(rawValue, window.location.origin);
  } catch {
    return null;
  }

  if (!['http:', 'https:'].includes(url.protocol)) return null;
  const localHostnames = new Set(['localhost', '127.0.0.1']);
  const sameLocalFrontend = localHostnames.has(url.hostname)
    && localHostnames.has(window.location.hostname)
    && url.port === window.location.port;
  if (url.origin !== window.location.origin && !rawValue.startsWith('/') && !sameLocalFrontend) return null;
  if (url.pathname.startsWith('/api/')) return null;

  let path;
  try {
    path = decodeURIComponent(url.pathname).replace(/^\/+/, '').replace(/\\/g, '/');
  } catch {
    return null;
  }
  const parts = path.split('/').filter(Boolean);
  if (!parts.length || parts.includes('..')) return null;

  const lowerParts = parts.map((part) => part.toLowerCase());
  const extensionMatch = path.toLowerCase().match(/\.[a-z0-9]+$/);
  const extension = extensionMatch ? extensionMatch[0] : '';
  if (!lowerParts.some((part) => PROTECTED_FILE_DIRS.has(part)) && !PROTECTED_FILE_EXTENSIONS.has(extension)) {
    return null;
  }
  return parts.map((part) => encodeURIComponent(part)).join('/');
}

function authenticatedPublicFileUrl(value) {
  const path = publicFilePath(value);
  if (!path) return null;

  return `${apiBaseUrl()}/files/${path}`;
}

function requireAuthForDownload() {
  if (getAuthToken()) return true;
  window.alert('抱歉，需要登陆');
  return false;
}

function safeLocalFileName(value, fallback = 'file') {
  const cleaned = String(value ?? '')
    .replace(/[\u0000-\u001f<>:"/\\|?*]/g, '_')
    .replace(/[. ]+$/g, '')
    .trim();
  const name = cleaned && cleaned !== '.' && cleaned !== '..' ? cleaned : fallback;
  const windowsReservedName = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i;
  return (windowsReservedName.test(name) ? `_${name}` : name).slice(0, 180);
}

function localFileNameFromUrl(value, fallback = 'photo') {
  try {
    const url = new URL(String(value ?? ''), window.location.origin);
    const encodedName = url.pathname.split('/').filter(Boolean).pop() || '';
    return safeLocalFileName(decodeURIComponent(encodedName), fallback);
  } catch {
    return safeLocalFileName('', fallback);
  }
}

function uniqueLocalFileName(filename, usedNames) {
  const safeName = safeLocalFileName(filename);
  const extensionIndex = safeName.lastIndexOf('.');
  const hasExtension = extensionIndex > 0;
  const stem = hasExtension ? safeName.slice(0, extensionIndex) : safeName;
  const extension = hasExtension ? safeName.slice(extensionIndex) : '';
  let candidate = safeName;
  let suffix = 2;
  while (usedNames.has(candidate.toLocaleLowerCase())) {
    candidate = `${stem} (${suffix})${extension}`;
    suffix += 1;
  }
  usedNames.add(candidate.toLocaleLowerCase());
  return candidate;
}

async function createUniqueLocalDirectory(parentHandle, requestedName) {
  const baseName = safeLocalFileName(requestedName, '活动照片');
  for (let suffix = 1; suffix <= 999; suffix += 1) {
    const candidate = suffix === 1 ? baseName : `${baseName} (${suffix})`;
    try {
      await parentHandle.getDirectoryHandle(candidate);
    } catch (error) {
      if (error?.name === 'NotFoundError') {
        return {
          handle: await parentHandle.getDirectoryHandle(candidate, { create: true }),
          name: candidate,
        };
      }
      if (error?.name === 'TypeMismatchError') continue;
      throw error;
    }
  }
  throw new Error('无法创建活动照片文件夹，请选择其他下载位置。');
}

async function writeResponseToLocalFile(directoryHandle, filename, response) {
  const fileHandle = await directoryHandle.getFileHandle(filename, { create: true });
  const writable = await fileHandle.createWritable();
  try {
    if (!response.body) throw new Error('浏览器无法读取下载数据。');
    await response.body.pipeTo(writable);
  } catch (error) {
    try {
      await writable.abort();
    } catch {
      // 浏览器可能已经在 pipeTo 失败时自动中止写入。
    }
    try {
      await directoryHandle.removeEntry(filename);
    } catch {
      // 清理不完整文件失败不应覆盖原始下载错误。
    }
    throw error;
  }
}

function prepareLocalDownloads(files) {
  const usedNames = new Set();
  return files.map((file, index) => ({
    url: file.url,
    filename: uniqueLocalFileName(
      file.filename || localFileNameFromUrl(file.url, `photo-${String(index + 1).padStart(4, '0')}.jpg`),
      usedNames,
    ),
  }));
}

function triggerBrowserDownload(file) {
  const link = document.createElement('a');
  link.href = file.url;
  link.download = file.filename;
  link.rel = 'noreferrer';
  document.body.appendChild(link);
  link.click();
  link.remove();
}

async function downloadFilesToDefaultDirectory(preparedFiles, options = {}) {
  const confirmed = window.confirm(
    '当前浏览器或访问方式不支持选择下载文件夹，只能将照片批量下载到浏览器的默认下载目录。\n\n'
    + '浏览器可能会询问是否允许多个文件下载；请选择“允许”。是否继续？',
  );
  if (!confirmed) throw new DOMException('用户取消批量下载', 'AbortError');

  const result = {
    deliveryMode: 'default-directory',
    folderName: null,
    total: preparedFiles.length,
    completed: 0,
    succeeded: 0,
    failed: [],
  };
  const batchSize = 4;
  options.onProgress?.({ ...result });

  for (let offset = 0; offset < preparedFiles.length; offset += batchSize) {
    const batch = preparedFiles.slice(offset, offset + batchSize);
    batch.forEach((file) => {
      triggerBrowserDownload(file);
      result.completed += 1;
      result.succeeded += 1;
    });
    options.onProgress?.({ ...result });
    if (offset + batchSize < preparedFiles.length) {
      await new Promise((resolve) => window.setTimeout(resolve, 200));
    }
  }
  return result;
}

async function downloadFilesToSelectedDirectory(files, options = {}) {
  const preparedFiles = prepareLocalDownloads(files);
  if (!window.isSecureContext || typeof window.showDirectoryPicker !== 'function') {
    return downloadFilesToDefaultDirectory(preparedFiles, options);
  }

  const parentHandle = await window.showDirectoryPicker({
    id: 'nethub-photo-downloads',
    mode: 'readwrite',
    startIn: 'downloads',
  });
  const directory = await createUniqueLocalDirectory(parentHandle, options.folderName);
  const result = {
    deliveryMode: 'selected-directory',
    folderName: directory.name,
    total: preparedFiles.length,
    completed: 0,
    succeeded: 0,
    failed: [],
  };
  let nextIndex = 0;
  const concurrency = Math.max(1, Math.min(Number(options.concurrency) || 3, 6, preparedFiles.length || 1));
  options.onProgress?.({ ...result });

  async function worker() {
    while (nextIndex < preparedFiles.length) {
      const currentIndex = nextIndex;
      nextIndex += 1;
      const file = preparedFiles[currentIndex];
      try {
        const response = await fetch(file.url, { credentials: 'include' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        await writeResponseToLocalFile(directory.handle, file.filename, response);
        result.succeeded += 1;
      } catch (error) {
        result.failed.push({ filename: file.filename, message: error?.message || '下载失败' });
      } finally {
        result.completed += 1;
        options.onProgress?.({ ...result, failed: [...result.failed] });
      }
    }
  }

  await Promise.all(Array.from({ length: concurrency }, () => worker()));
  return result;
}

/**
 * 渲染 CAS 三项标记。
 *
 * C/A/S 三个字母固定来自代码，不需要转义；状态来自布尔值，只控制 class。
 */
function casTags(cas) {
  const items = [
    ['C', Boolean(cas?.creativity), 'Creativity', 'creativity'],
    ['A', Boolean(cas?.activity), 'Activity', 'activity'],
    ['S', Boolean(cas?.service), 'Service', 'service'],
  ];
  return `<div class="cas-tags" aria-label="CAS 类型">${items.map(([letter, enabled, title, type]) =>
    `<span class="cas-tag ${type} ${enabled ? 'on' : ''}" title="${title}${enabled ? ' 已启用' : ' 未启用'}">${letter}</span>`
  ).join('')}</div>`;
}

function authDialogTemplate() {
  return `
    <div class="auth-modal" id="authModal" aria-hidden="true" role="dialog" aria-label="账号">
      <div class="auth-backdrop" data-auth-close></div>
      <section id="authPanel" class="auth-panel">
        <div id="authHead" class="auth-head">
          <h2>注册或登录</h2>
          <p id="authHint">登录后可参与更多校园互动。</p>
        </div>
        <div id="authAccountState"></div>
        <form id="authLoginForm" class="auth-form">
          <p>本网站使用 NetHub 账号登录，请前往账号管理界面</p>
          <button class="button auth-submit" type="submit">登录或注册 NetHub 账号后继续</button>
        </form>
        <form id="authPasswordForm" class="auth-form is-hidden">
          <p>密码由 NetHub Accounts 统一管理。</p>
          <button class="button auth-submit" type="submit">打开统一账号设置</button>
        </form>
        <form id="authUsernameForm" class="auth-form is-hidden">
          <label>
            <span class="sr-only">新昵称</span>
            <input class="input" name="username" autocomplete="username" placeholder="新昵称" required minlength="3" maxlength="32" />
          </label>
          <button class="button auth-submit" type="submit">保存昵称</button>
        </form>
        <div id="authMessage" class="auth-message" aria-live="polite"></div>
      </section>
    </div>
  `;
}

function initAuthNav() {
  const navbar = document.querySelector('.navbar');
  if (!navbar || document.querySelector('.auth-area')) return;

  ensureSocialNav();
  const authArea = document.createElement('div');
  authArea.className = 'auth-area';
  navbar.appendChild(authArea);
  document.body.insertAdjacentHTML('beforeend', authDialogTemplate());

  const modal = document.querySelector('#authModal');
  const authPanel = document.querySelector('#authPanel');
  const authHead = document.querySelector('#authHead');
  const loginForm = document.querySelector('#authLoginForm');
  const passwordForm = document.querySelector('#authPasswordForm');
  const usernameForm = document.querySelector('#authUsernameForm');
  const hint = document.querySelector('#authHint');
  const accountState = document.querySelector('#authAccountState');
  const message = document.querySelector('#authMessage');
  let currentUser = getStoredUser();
  let passwordFormOpen = false;
  let usernameFormOpen = false;

  function renderUser(user) {
    currentUser = user;
    if (!user) {
      authArea.innerHTML = `
        ${messageNavMarkup()}
        <button class="auth-avatar logged-out" type="button" data-open-auth aria-label="打开账号面板">登</button>
      `;
      authArea.querySelector('[data-open-auth]').addEventListener('click', (event) => openAuthModal('login', event.currentTarget));
      refreshGlobalMessageBadge();
      return;
    }

    authArea.innerHTML = `
      ${messageNavMarkup()}
      <button class="auth-avatar" type="button" data-open-auth aria-label="打开账号菜单">
        <span>${escapeHtml(userInitial(user))}</span>
        ${userAvatarImage(user)}
      </button>
    `;
    authArea.querySelector('[data-open-auth]').addEventListener('click', (event) => openAuthModal('login', event.currentTarget));
    refreshGlobalMessageBadge();
    if (!globalMessageBadgeTimer) {
      globalMessageBadgeTimer = window.setInterval(refreshGlobalMessageBadge, 30000);
    }
  }

  function renderAccountState() {
    if (!currentUser) {
      authPanel.classList.remove('is-account-menu');
      authHead.classList.remove('is-hidden');
      message.classList.remove('is-hidden');
      accountState.innerHTML = '';
      hint.textContent = '登录后可参与更多校园互动。';
      loginForm.classList.remove('is-hidden');
      passwordForm.classList.add('is-hidden');
      usernameForm.classList.add('is-hidden');
      return;
    }

    authPanel.classList.add('is-account-menu');
    authHead.classList.add('is-hidden');
    message.classList.toggle('is-hidden', !passwordFormOpen && !usernameFormOpen);
    loginForm.classList.add('is-hidden');
    passwordForm.classList.toggle('is-hidden', !passwordFormOpen);
    usernameForm.classList.toggle('is-hidden', !usernameFormOpen);
    accountState.innerHTML = `
      <div class="auth-profile-summary">
        <span class="auth-profile-avatar" data-initial="${escapeHtml(userInitial(currentUser))}">
          ${userAvatarImage(currentUser)}
        </span>
        <span class="auth-profile-copy">
          <strong>${escapeHtml(currentUser.displayName || currentUser.username)}</strong>
          <small>@${escapeHtml(currentUser.username)} · ${escapeHtml(roleLabel(currentUser.role))}</small>
        </span>
      </div>
      <nav class="auth-account-menu" aria-label="账户菜单">
      ${currentUser.role === 'admin'
        ? `<a class="auth-menu-item" href="/admin.html">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 5 6v5c0 4.6 2.9 8 7 10 4.1-2 7-5.4 7-10V6l-7-3Z"></path><path d="m9 12 2 2 4-4"></path></svg>
            <span>管理员后台</span><span class="auth-menu-arrow" aria-hidden="true">›</span>
          </a>`
        : ''}
        <a class="auth-menu-item" href="/profile.html">
          <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"></circle><path d="M4.5 21a7.5 7.5 0 0 1 15 0"></path></svg>
          <span>个人中心</span><span class="auth-menu-arrow" aria-hidden="true">›</span>
        </a>
        <button class="auth-menu-item" type="button" data-account-center>
          <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle><path d="M3 12h18M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18"></path></svg>
          <span>前往账户中心</span><span class="auth-menu-arrow" aria-hidden="true">›</span>
        </button>
        <button class="auth-menu-item auth-menu-logout" type="button" data-logout>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 5H5v14h5"></path><path d="M13 8l4 4-4 4"></path><path d="M8 12h9"></path></svg>
          <span>退出账号</span>
        </button>
      </nav>
      <div class="auth-account-actions">
        <button class="auth-password-toggle" type="button" data-toggle-username>
          ${usernameFormOpen ? '收起修改昵称' : '修改昵称'}
        </button>
        <button class="auth-password-toggle" type="button" data-toggle-password>
          ${passwordFormOpen ? '收起修改密码' : '修改密码'}
        </button>
      </div>
    `;
    accountState.querySelector('[data-account-center]')?.addEventListener('click', changeCurrentUserPassword);
    accountState.querySelector('[data-toggle-username]')?.addEventListener('click', () => {
      usernameFormOpen = !usernameFormOpen;
      if (usernameFormOpen) {
        passwordFormOpen = false;
        usernameForm.username.value = currentUser.username || '';
      } else {
        usernameForm.reset();
      }
      message.textContent = '登录后可保存你的项目资料与校园互动状态。';
      message.classList.remove('error');
      renderAccountState();
      updateAuthPanelPosition();
      if (usernameFormOpen) usernameForm.username.focus();
    });
    accountState.querySelector('[data-toggle-password]')?.addEventListener('click', () => {
      passwordFormOpen = !passwordFormOpen;
      if (passwordFormOpen) usernameFormOpen = false;
      if (!passwordFormOpen) passwordForm.reset();
      message.textContent = '登录后可保存你的项目资料与校园互动状态。';
      message.classList.remove('error');
      renderAccountState();
      updateAuthPanelPosition();
      if (passwordFormOpen) passwordForm.querySelector('button')?.focus();
    });
    accountState.querySelector('[data-logout]')?.addEventListener('click', async () => {
      await request('/auth/logout', { method: 'POST' }).catch(() => null);
      clearAuthSession();
      window.localStorage.setItem(
        'campus-wiki-sso-suppressed-until',
        String(Date.now() + 10 * 60 * 1000),
      );
      window.clearInterval(globalMessageBadgeTimer);
      globalMessageBadgeTimer = null;
      passwordFormOpen = false;
      usernameFormOpen = false;
      renderUser(null);
      setMode('login');
    });
  }

  function setMode() {
    renderAccountState();
    message.textContent = '登录后可保存你的项目资料与校园互动状态。';
    message.classList.remove('error');
  }

  function updateAuthPanelPosition(trigger) {
    const anchor = trigger || authArea.querySelector('[data-open-auth]');
    if (!anchor) return;

    const rect = anchor.getBoundingClientRect();
    const panelWidth = Math.min(currentUser ? 340 : 380, window.innerWidth - 32);
    const left = Math.min(
      Math.max(16, rect.right - panelWidth),
      Math.max(16, window.innerWidth - panelWidth - 16),
    );
    modal.style.setProperty('--auth-panel-top', `${Math.round(rect.bottom + 10)}px`);
    modal.style.setProperty('--auth-panel-left', `${Math.round(left)}px`);
    modal.style.setProperty('--auth-panel-width', `${Math.round(panelWidth)}px`);
  }

  function openAuthModal(nextMode, trigger) {
    if (currentUser) {
      passwordFormOpen = false;
      usernameFormOpen = false;
    }
    setMode(nextMode);
    updateAuthPanelPosition(trigger);
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
    if (currentUser) {
      accountState.querySelector('.auth-menu-item')?.focus();
      return;
    }
    loginForm.querySelector('button')?.focus();
  }

  function closeAuthModal() {
    modal.classList.remove('is-open');
    modal.setAttribute('aria-hidden', 'true');
    loginForm.reset();
    passwordForm.reset();
    usernameForm.reset();
    passwordFormOpen = false;
    usernameFormOpen = false;
    message.textContent = '登录后可保存你的项目资料与校园互动状态。';
    message.classList.remove('error');
  }

  document.querySelectorAll('[data-auth-close]').forEach((item) => item.addEventListener('click', closeAuthModal));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && modal.classList.contains('is-open')) closeAuthModal();
  });
  window.addEventListener('resize', () => {
    if (modal.classList.contains('is-open')) updateAuthPanelPosition();
  });

  loginForm.addEventListener('submit', (event) => {
    event.preventDefault();
    loginUser();
  });

  passwordForm.addEventListener('submit', (event) => {
    event.preventDefault();
    changeCurrentUserPassword();
  });

  usernameForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    message.textContent = '正在修改昵称...';
    message.classList.remove('error');
    const submit = usernameForm.querySelector('[type="submit"]');
    submit.disabled = true;

    try {
      const formData = new FormData(usernameForm);
      const username = String(formData.get('username') || '').trim();
      const user = await updateCurrentUsername(username);
      window.localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user));
      usernameFormOpen = false;
      renderUser(user);
      renderAccountState();
      usernameForm.reset();
      message.textContent = '昵称已修改';
      message.classList.remove('error');
    } catch (error) {
      message.textContent = error.message;
      message.classList.add('error');
    } finally {
      submit.disabled = false;
    }
  });

  renderUser(getStoredUser());
  refreshCurrentUser().then((user) => {
    renderUser(user);
    if (user) {
      window.sessionStorage.removeItem('campus-wiki-sso-probe');
      window.localStorage.removeItem('campus-wiki-sso-suppressed-until');
      return;
    }
    const alreadyProbed = window.sessionStorage.getItem('campus-wiki-sso-probe') === '1';
    const suppressedUntil = Number(
      window.localStorage.getItem('campus-wiki-sso-suppressed-until') || 0,
    );
    if (!alreadyProbed && Date.now() >= suppressedUntil) {
      window.sessionStorage.setItem('campus-wiki-sso-probe', '1');
      loginUser({ silent: true });
      return;
    }
    openAuthModal('login');
  });
}

const PROJECT_LOGO_FALLBACK_MAX_LENGTH = 8;

function projectLogoFallbackText(value) {
  const compactName = String(value || '项目')
    .trim()
    .replace(/[\s._·•—–-]+/g, '');
  return Array.from(compactName || '项目')
    .slice(0, PROJECT_LOGO_FALLBACK_MAX_LENGTH)
    .join('')
    .toLocaleUpperCase('en-US');
}

function projectLogoTextClass(value) {
  const length = Array.from(value).length;
  if (length <= 4) return 'logo-text-short';
  if (length <= 6) return 'logo-text-medium';
  return 'logo-text-long';
}

function projectIconImage(project, options = {}) {
  const rawIcon = String(project.icon || '');
  const iconSource = /^(https?:|\/)/i.test(rawIcon) ? rawIcon : '';
  const iconUrl = safeExternalUrl(iconSource);
  const hasIcon = Boolean(iconSource && iconUrl !== '#');
  const fallbackText = projectLogoFallbackText(project.name);
  const frameClass = String(options.className || 'project-icon').trim() || 'project-icon';
  return `
    <div class="${frameClass} project-logo-frame ${projectLogoTextClass(fallbackText)}${hasIcon ? ' has-image' : ''}" data-project-logo data-logo-text="${escapeHtml(fallbackText)}">
      ${hasIcon ? `<img src="${iconUrl}" alt="${escapeHtml(project.name)}" loading="lazy" data-project-icon>` : ''}
    </div>
  `;
}

document.addEventListener('error', (event) => {
  const image = event.target;
  if (!(image instanceof HTMLImageElement) || !image.matches('[data-project-icon]')) return;
  const frame = image.closest('[data-project-logo]');
  frame?.classList.remove('has-image');
  frame?.classList.add('is-failed');
  image.remove();
}, true);

/**
 * 首页推荐项目卡片。
 */
function projectCard(project) {
  const projectId = encodeURIComponent(project.id);
  const description = escapeHtml(truncateText(project.description, 86));

  return `
    <a class="project-card" href="/detail.html?id=${projectId}">
      ${projectIconImage(project)}
      <h3>${escapeHtml(project.name)}</h3>
      <div class="meta">
        <span class="badge">${escapeHtml(project.category)}</span>
        <span>${escapeHtml(project.year)}</span>
        <span>负责人：${escapeHtml(project.leader || '待确认')}</span>
      </div>
      <p>${description}</p>
      ${casTags(project.cas)}
    </a>
  `;
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initAuthNav);
} else {
  initAuthNav();
}
