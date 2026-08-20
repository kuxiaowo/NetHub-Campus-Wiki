const profileRoot = document.querySelector('#profileRoot');
const profileBreadcrumb = document.querySelector('#profileBreadcrumb');
const profileUserId = Number(new URLSearchParams(window.location.search).get('user'));

function profileDisplayName(profile) {
  return String(profile?.displayName || profile?.username || '校园成员').trim();
}

function profileInitial(profile) {
  return escapeHtml(profileDisplayName(profile).slice(0, 1).toUpperCase() || 'N');
}

function profileMessageIcon() {
  return `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <rect x="3.25" y="5.25" width="17.5" height="13.5" rx="2.5"></rect>
      <path d="m4.5 7 6.1 5a2.2 2.2 0 0 0 2.8 0l6.1-5"></path>
    </svg>
  `;
}

function renderProfileAction(profile, currentUser) {
  if (Number(currentUser?.id) === Number(profile.id)) {
    return '<span class="profile-self-label">这是你的个人主页</span>';
  }
  const label = currentUser ? '发消息' : '登录后发消息';
  return `
    <a class="button profile-message-button" href="/messages.html?user=${encodeURIComponent(profile.id)}">
      ${profileMessageIcon()}
      ${label}
    </a>
  `;
}

function renderProfileProjects(projects) {
  if (!projects.length) {
    return `
      <div class="profile-project-empty">
        <strong>还没有关联项目</strong>
        <span>管理员关联 CAS 成员后，项目经历会显示在这里。</span>
      </div>
    `;
  }
  return `
    <div class="profile-project-list">
      ${projects.map((project) => `
        <a class="profile-project-card" href="/detail.html?id=${encodeURIComponent(project.id)}">
          <div class="profile-project-main">
            <span class="profile-project-year">${escapeHtml(project.year)}</span>
            <div>
              <h2>${escapeHtml(project.name)}</h2>
              <p>${escapeHtml(project.category)}</p>
            </div>
          </div>
          <span class="profile-project-role">${project.memberRole === 'leader' ? '负责人' : '成员'}</span>
        </a>
      `).join('')}
    </div>
  `;
}

function renderProfile(profile, currentUser) {
  const displayName = profileDisplayName(profile);
  document.title = `${displayName} - 个人主页 - NetHub`;
  profileBreadcrumb.innerHTML = `
    <a href="/projects.html">CAS 项目库</a>
    <span>${escapeHtml(displayName)}</span>
  `;
  profileRoot.innerHTML = `
    <section class="card profile-identity-card">
      <div class="profile-avatar" aria-hidden="true">${profileInitial(profile)}</div>
      <div class="profile-identity-copy">
        <p class="eyebrow">Campus Profile</p>
        <h1>${escapeHtml(displayName)}</h1>
        <p class="profile-username">@${escapeHtml(profile.username)}</p>
        <p class="profile-summary">在 NetHub 记录参与过的 CAS 项目，也从这里开始一段校园对话。</p>
      </div>
      <div class="profile-actions">${renderProfileAction(profile, currentUser)}</div>
    </section>

    <section class="card profile-projects-section">
      <div class="profile-section-head">
        <div>
          <p class="eyebrow">CAS Footprint</p>
          <h2>参与的项目</h2>
        </div>
        <span>${profile.projects.length} 个项目</span>
      </div>
      ${renderProfileProjects(profile.projects)}
    </section>
  `;
}

function renderProfileError(message) {
  profileBreadcrumb.innerHTML = '<a href="/projects.html">CAS 项目库</a><span>无法加载</span>';
  profileRoot.innerHTML = `
    <section class="card profile-error-state">
      <h1>个人主页暂时无法显示</h1>
      <p>${escapeHtml(message || '请检查链接后重试。')}</p>
      <a class="button secondary" href="/projects.html">返回项目库</a>
    </section>
  `;
}

async function initProfile() {
  if (!Number.isInteger(profileUserId) || profileUserId < 1) {
    renderProfileError('缺少有效的用户 ID。');
    return;
  }
  try {
    const [result, currentUser] = await Promise.all([
      fetchUserProfile(profileUserId),
      refreshCurrentUser(),
    ]);
    renderProfile(result.data, currentUser);
  } catch (error) {
    renderProfileError(error.message);
  }
}

initProfile();
