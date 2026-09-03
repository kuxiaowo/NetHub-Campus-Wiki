const userStateEl = document.querySelector('#userProfileState');
const userProfileEl = document.querySelector('#userProfile');
const viewedUserId = new URLSearchParams(window.location.search).get('id');
let viewedProfile = null;

function publicAvatar(profile) {
  const name = profile.displayName || profile.username;
  return `<div class="public-profile-avatar" data-initial="${escapeHtml(String(name).slice(0, 1).toUpperCase())}">${
    profile.avatarUrl ? `<img src="${escapeHtml(safeExternalUrl(profile.avatarUrl))}" alt="" />` : ''
  }</div>`;
}

function renderPublicProfile(profile, currentUser) {
  const own = Number(profile.id) === Number(currentUser.id);
  const relationship = profile.relationship || {};
  const messagingBlocked = relationship.blocked || relationship.blockedBy;
  userProfileEl.innerHTML = `
    <section class="card public-profile-hero">
      ${publicAvatar(profile)}
      <div class="public-profile-copy">
        <div class="public-profile-name">
          <h1>${escapeHtml(profile.displayName || profile.username)}</h1>
        </div>
        <p class="public-profile-handle">@${escapeHtml(profile.username)}</p>
        <p class="public-profile-bio">${escapeHtml(profile.bio || '这个用户还没有填写个人简介。')}</p>
        <div class="public-profile-stats">
          <span><strong>${escapeHtml(profile.followingCount)}</strong> 关注</span>
          <span><strong>${escapeHtml(profile.followerCount)}</strong> 关注者</span>
        </div>
        <div class="public-profile-actions">
          ${own ? '<a class="button" href="/profile.html">编辑个人资料</a>' : `
            <button class="button ${relationship.following ? 'secondary' : ''}" type="button" data-profile-action="follow">
              ${relationship.following ? '已关注' : '关注'}
            </button>
            ${messagingBlocked
              ? '<span class="blocked-message-tip">黑名单关系下无法私信</span>'
              : `<a class="button secondary" href="/messages.html?targetUserId=${encodeURIComponent(profile.id)}">发私信</a>`}
            <button class="text-button danger" type="button" data-profile-action="block">
              ${relationship.blocked ? '解除拉黑' : '拉黑'}
            </button>
          `}
        </div>
      </div>
    </section>
    <section class="card public-profile-projects">
      <div class="section-title"><div><h2>参与的 CAS 项目</h2><span>${escapeHtml(profile.projects.length)} 个已关联项目</span></div></div>
      <div class="profile-project-list">
        ${profile.projects.length ? profile.projects.map((project) => `
          <a href="/detail.html?id=${encodeURIComponent(project.id)}">
            <span><strong>${escapeHtml(project.name)}</strong><small>${escapeHtml(project.role === 'leader' ? '负责人' : '成员')}</small></span>
            <time>${escapeHtml(project.year)}</time>
          </a>
        `).join('') : '<div class="empty">暂无已关联项目。</div>'}
      </div>
    </section>
  `;
  userProfileEl.classList.remove('is-hidden');
  userStateEl.classList.add('is-hidden');
}

async function reloadProfile(currentUser) {
  const result = await request(`/users/${encodeURIComponent(viewedUserId)}`);
  viewedProfile = result.data;
  document.title = `${viewedProfile.displayName || viewedProfile.username} - NetHub Campus Wiki`;
  renderPublicProfile(viewedProfile, currentUser);
}

async function initUserProfile() {
  const currentUser = await refreshCurrentUser();
  if (!currentUser) {
    userStateEl.innerHTML = '<h1>登录后查看用户主页</h1><p>用户关系和私信入口只对登录用户开放。</p><a class="button" href="/index.html">返回首页登录</a>';
    return;
  }
  if (!viewedUserId) {
    userStateEl.innerHTML = '<h1>缺少用户 ID</h1><a class="button secondary" href="/projects.html">返回项目库</a>';
    return;
  }
  await reloadProfile(currentUser);
  userProfileEl.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-profile-action]');
    if (!button || !viewedProfile) return;
    try {
      if (button.dataset.profileAction === 'follow') {
        await request(`/users/${encodeURIComponent(viewedProfile.id)}/follow`, {
          method: viewedProfile.relationship.following ? 'DELETE' : 'POST',
        });
      }
      if (button.dataset.profileAction === 'block') {
        await request(`/users/${encodeURIComponent(viewedProfile.id)}/block`, {
          method: viewedProfile.relationship.blocked ? 'DELETE' : 'POST',
        });
      }
      await reloadProfile(currentUser);
    } catch (error) {
      window.alert(error.message);
    }
  });
}

initUserProfile().catch((error) => {
  userStateEl.innerHTML = `<h1>用户主页暂时无法显示</h1><p>${escapeHtml(error.message)}</p>`;
});
