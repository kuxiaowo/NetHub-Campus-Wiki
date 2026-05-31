// 统一封装 API 请求，方便后续替换接口前缀或做登录鉴权。
const API_BASE = window.CAMPUS_WIKI_CONFIG?.apiBaseUrl || '/api';

/**
 * 请求后端 API。
 *
 * path 只传 /api 后面的路径，例如 /projects。真实服务地址由 config.js 提供，
 * 这样前端服务和后端服务可以独立部署。
 */
const AUTH_TOKEN_KEY = 'campusWikiAuthToken';
const AUTH_USER_KEY = 'campusWikiAuthUser';
const PROTECTED_FILE_EXTENSIONS = new Set([
  '.jpg', '.jpeg', '.png', '.webp', '.gif',
  '.pdf', '.zip', '.rar', '.7z',
  '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
]);
const PROTECTED_FILE_DIRS = new Set(['photos', 'yearbook']);

async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = getAuthToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    const detail = Array.isArray(error.detail)
      ? error.detail.map((item) => item.msg).filter(Boolean).join('；')
      : error.detail;
    throw new Error(detail || error.message || `请求失败：${response.status}`);
  }
  return response.json();
}

function getAuthToken() {
  return window.localStorage.getItem(AUTH_TOKEN_KEY);
}

function getStoredUser() {
  try {
    return JSON.parse(window.localStorage.getItem(AUTH_USER_KEY) || 'null');
  } catch {
    return null;
  }
}

function saveAuthSession(token, user) {
  window.localStorage.setItem(AUTH_TOKEN_KEY, token);
  window.localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user));
}

function clearAuthSession() {
  window.localStorage.removeItem(AUTH_TOKEN_KEY);
  window.localStorage.removeItem(AUTH_USER_KEY);
}

function roleLabel(role) {
  return role === 'admin' ? '管理员' : '普通用户';
}

function userInitial(user) {
  const name = String(user?.username || user?.displayName || '登').trim();
  return (name[0] || '登').toUpperCase();
}

async function loginUser(username, password) {
  const result = await request('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });
  saveAuthSession(result.accessToken, result.user);
  return result.user;
}

async function registerUser(username, password, displayName) {
  return request('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ username, password, displayName: displayName || null }),
  });
}

async function changeCurrentUserPassword(currentPassword, newPassword) {
  return request('/auth/password', {
    method: 'PATCH',
    body: JSON.stringify({ currentPassword, newPassword }),
  });
}

async function refreshCurrentUser() {
  if (!getAuthToken()) return null;
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

  const token = getAuthToken();
  const query = token ? `?token=${encodeURIComponent(token)}` : '';
  return `${apiBaseUrl()}/files/${path}${query}`;
}

function requireAuthForDownload() {
  if (getAuthToken()) return true;
  window.alert('抱歉，需要登陆');
  return false;
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

function authDialogTemplate() {
  return `
    <div class="auth-modal" id="authModal" aria-hidden="true" role="dialog" aria-label="账号">
      <div class="auth-backdrop" data-auth-close></div>
      <section class="auth-panel">
        <div class="auth-head">
          <h2>账号</h2>
          <p id="authHint">未登录：可浏览内容，登录后可参与更多校园互动。</p>
        </div>
        <div id="authAccountState"></div>
        <div class="auth-tabs" role="tablist" aria-label="账号操作">
          <button id="authLoginTab" class="auth-tab active" type="button">登录</button>
          <button id="authRegisterTab" class="auth-tab" type="button">注册</button>
        </div>
        <form id="authLoginForm" class="auth-form">
          <label>
            <span class="sr-only">昵称</span>
            <input class="input" name="username" autocomplete="username" placeholder="昵称" required minlength="3" maxlength="32" />
          </label>
          <label>
            <span class="sr-only">密码</span>
            <input class="input" name="password" type="password" autocomplete="current-password" placeholder="密码" required minlength="8" />
          </label>
          <button class="button auth-submit" type="submit">登录</button>
        </form>
        <form id="authRegisterForm" class="auth-form is-hidden">
          <label>
            <span class="sr-only">姓名</span>
            <input class="input" name="displayName" autocomplete="name" placeholder="姓名" maxlength="80" />
          </label>
          <label>
            <span class="sr-only">昵称</span>
            <input class="input" name="username" autocomplete="username" placeholder="昵称" required minlength="3" maxlength="32" />
          </label>
          <label>
            <span class="sr-only">密码</span>
            <input class="input" name="password" type="password" autocomplete="new-password" placeholder="密码（至少 8 位）" required minlength="8" />
          </label>
          <button class="button auth-submit" type="submit">注册并登录</button>
        </form>
        <form id="authPasswordForm" class="auth-form is-hidden">
          <label>
            <span class="sr-only">原密码</span>
            <input class="input" name="currentPassword" type="password" autocomplete="current-password" placeholder="原密码" required minlength="8" />
          </label>
          <label>
            <span class="sr-only">新密码</span>
            <input class="input" name="newPassword" type="password" autocomplete="new-password" placeholder="新密码（至少 8 位）" required minlength="8" />
          </label>
          <label>
            <span class="sr-only">确认新密码</span>
            <input class="input" name="confirmPassword" type="password" autocomplete="new-password" placeholder="确认新密码" required minlength="8" />
          </label>
          <button class="button auth-submit" type="submit">修改密码</button>
        </form>
        <div id="authMessage" class="auth-message" aria-live="polite"></div>
      </section>
    </div>
  `;
}

function initAuthNav() {
  const navbar = document.querySelector('.navbar');
  if (!navbar || document.querySelector('.auth-area')) return;

  const authArea = document.createElement('div');
  authArea.className = 'auth-area';
  navbar.appendChild(authArea);
  document.body.insertAdjacentHTML('beforeend', authDialogTemplate());

  const modal = document.querySelector('#authModal');
  const loginForm = document.querySelector('#authLoginForm');
  const registerForm = document.querySelector('#authRegisterForm');
  const passwordForm = document.querySelector('#authPasswordForm');
  const hint = document.querySelector('#authHint');
  const accountState = document.querySelector('#authAccountState');
  const message = document.querySelector('#authMessage');
  const loginTab = document.querySelector('#authLoginTab');
  const registerTab = document.querySelector('#authRegisterTab');
  let mode = 'login';
  let currentUser = getStoredUser();
  let passwordFormOpen = false;

  function renderUser(user) {
    currentUser = user;
    if (!user) {
      authArea.innerHTML = `
        <button class="auth-avatar logged-out" type="button" data-open-auth aria-label="打开账号面板">登</button>
      `;
      authArea.querySelector('[data-open-auth]').addEventListener('click', (event) => openAuthModal('login', event.currentTarget));
      return;
    }

    authArea.innerHTML = `
      <button class="auth-avatar" type="button" data-open-auth aria-label="打开账号面板">
        ${escapeHtml(userInitial(user))}
      </button>
    `;
    authArea.querySelector('[data-open-auth]').addEventListener('click', (event) => openAuthModal('login', event.currentTarget));
  }

  function renderAccountState() {
    if (!currentUser) {
      accountState.innerHTML = '';
      hint.textContent = '未登录：可浏览内容，登录后可参与更多校园互动。';
      loginForm.classList.toggle('is-hidden', mode !== 'login');
      registerForm.classList.toggle('is-hidden', mode !== 'register');
      passwordForm.classList.add('is-hidden');
      loginTab.classList.remove('is-hidden');
      registerTab.classList.remove('is-hidden');
      return;
    }

    hint.innerHTML = `已登录：${escapeHtml(currentUser.displayName || currentUser.username)}
      <span>(${escapeHtml(currentUser.username)})</span>`;
    loginForm.classList.add('is-hidden');
    registerForm.classList.add('is-hidden');
    passwordForm.classList.toggle('is-hidden', !passwordFormOpen);
    loginTab.classList.add('is-hidden');
    registerTab.classList.add('is-hidden');
    accountState.innerHTML = `
      ${currentUser.role === 'admin'
        ? '<button class="button auth-admin-button" type="button" data-admin-entry>进入管理员后台</button>'
        : ''}
      <button class="button secondary auth-logout-button" type="button" data-logout>退出账号，重新登录</button>
      <button class="auth-password-toggle" type="button" data-toggle-password>
        ${passwordFormOpen ? '收起修改密码' : '修改密码'}
      </button>
    `;
    accountState.querySelector('[data-toggle-password]')?.addEventListener('click', () => {
      passwordFormOpen = !passwordFormOpen;
      if (!passwordFormOpen) passwordForm.reset();
      message.textContent = '登录后可保存你的项目资料与校园互动状态。';
      message.classList.remove('error');
      renderAccountState();
      updateAuthPanelPosition();
      if (passwordFormOpen) passwordForm.currentPassword.focus();
    });
    accountState.querySelector('[data-logout]')?.addEventListener('click', () => {
      clearAuthSession();
      passwordFormOpen = false;
      renderUser(null);
      setMode('login');
    });
    accountState.querySelector('[data-admin-entry]')?.addEventListener('click', () => {
      window.location.href = '/admin.html';
    });
  }

  function setMode(nextMode) {
    mode = nextMode;
    const isRegister = mode === 'register';
    renderAccountState();
    loginTab.classList.toggle('active', !isRegister);
    registerTab.classList.toggle('active', isRegister);
    message.textContent = '登录后可保存你的项目资料与校园互动状态。';
    message.classList.remove('error');
  }

  function updateAuthPanelPosition(trigger) {
    const anchor = trigger || authArea.querySelector('[data-open-auth]');
    if (!anchor) return;

    const rect = anchor.getBoundingClientRect();
    const panelWidth = Math.min(380, window.innerWidth - 32);
    const left = Math.min(
      Math.max(16, rect.right - panelWidth),
      Math.max(16, window.innerWidth - panelWidth - 16),
    );
    modal.style.setProperty('--auth-panel-top', `${Math.round(rect.bottom + 10)}px`);
    modal.style.setProperty('--auth-panel-left', `${Math.round(left)}px`);
    modal.style.setProperty('--auth-panel-width', `${Math.round(panelWidth)}px`);
  }

  function openAuthModal(nextMode, trigger) {
    if (currentUser) passwordFormOpen = false;
    setMode(nextMode);
    updateAuthPanelPosition(trigger);
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
    if (currentUser) {
      accountState.querySelector('[data-toggle-password]')?.focus();
      return;
    }
    const activeForm = mode === 'register' ? registerForm : loginForm;
    activeForm.username.focus();
  }

  function closeAuthModal() {
    modal.classList.remove('is-open');
    modal.setAttribute('aria-hidden', 'true');
    loginForm.reset();
    registerForm.reset();
    passwordForm.reset();
    passwordFormOpen = false;
    message.textContent = '登录后可保存你的项目资料与校园互动状态。';
    message.classList.remove('error');
  }

  loginTab.addEventListener('click', () => setMode('login'));
  registerTab.addEventListener('click', () => setMode('register'));
  document.querySelectorAll('[data-auth-close]').forEach((item) => item.addEventListener('click', closeAuthModal));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && modal.classList.contains('is-open')) closeAuthModal();
  });
  window.addEventListener('resize', () => {
    if (modal.classList.contains('is-open')) updateAuthPanelPosition();
  });

  loginForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    message.textContent = '正在登录...';
    message.classList.remove('error');
    const submit = loginForm.querySelector('[type="submit"]');
    submit.disabled = true;

    try {
      const formData = new FormData(loginForm);
      const username = String(formData.get('username') || '');
      const password = String(formData.get('password') || '');

      const user = await loginUser(username, password);
      renderUser(user);
      closeAuthModal();
    } catch (error) {
      message.textContent = error.message;
      message.classList.add('error');
    } finally {
      submit.disabled = false;
    }
  });

  registerForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    message.textContent = '正在注册...';
    message.classList.remove('error');
    const submit = registerForm.querySelector('[type="submit"]');
    submit.disabled = true;

    try {
      const formData = new FormData(registerForm);
      const username = String(formData.get('username') || '');
      const password = String(formData.get('password') || '');
      const displayName = String(formData.get('displayName') || '').trim();

      await registerUser(username, password, displayName);
      const user = await loginUser(username, password);
      renderUser(user);
      closeAuthModal();
    } catch (error) {
      message.textContent = error.message;
      message.classList.add('error');
    } finally {
      submit.disabled = false;
    }
  });

  passwordForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    message.textContent = '正在修改密码...';
    message.classList.remove('error');
    const submit = passwordForm.querySelector('[type="submit"]');
    submit.disabled = true;

    try {
      const formData = new FormData(passwordForm);
      const currentPassword = String(formData.get('currentPassword') || '');
      const newPassword = String(formData.get('newPassword') || '');
      const confirmPassword = String(formData.get('confirmPassword') || '');

      if (newPassword !== confirmPassword) {
        throw new Error('两次输入的新密码不一致');
      }

      const user = await changeCurrentUserPassword(currentPassword, newPassword);
      window.localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user));
      passwordFormOpen = false;
      renderUser(user);
      renderAccountState();
      passwordForm.reset();
      message.textContent = '密码已修改';
      message.classList.remove('error');
    } catch (error) {
      message.textContent = error.message;
      message.classList.add('error');
    } finally {
      submit.disabled = false;
    }
  });

  renderUser(getStoredUser());
  refreshCurrentUser().then(renderUser);
}

function projectIconImage(project) {
  const rawIcon = String(project.icon || '');
  const iconSource = /^(https?:|\/)/i.test(rawIcon) ? rawIcon : project.media?.[0];
  const iconUrl = safeExternalUrl(iconSource);
  return `
    <div class="project-icon">
      <img src="${iconUrl}" alt="${escapeHtml(project.name)}" loading="lazy">
    </div>
  `;
}

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
        <span>负责人：${escapeHtml(project.leader)}</span>
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
