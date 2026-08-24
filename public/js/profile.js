const profileEls = {
  gate: document.querySelector('#profileGate'),
  app: document.querySelector('#profileApp'),
  form: document.querySelector('#profileForm'),
  title: document.querySelector('#profileTitle'),
  handle: document.querySelector('#profileHandle'),
  avatar: document.querySelector('#profileAvatarPreview'),
  verified: document.querySelector('#profileVerified'),
  publicLink: document.querySelector('#publicProfileLink'),
  message: document.querySelector('#profileMessage'),
  claims: document.querySelector('#claimList'),
};

let profileUser = null;

function renderProfileSummary(user) {
  const name = user.displayName || user.username;
  profileEls.title.textContent = name;
  profileEls.handle.textContent = `@${user.username}`;
  profileEls.verified.classList.toggle('is-hidden', !user.campusVerified);
  profileEls.publicLink.href = `/user.html?id=${encodeURIComponent(user.id)}`;
  profileEls.avatar.dataset.initial = String(name).slice(0, 1).toUpperCase();
  profileEls.avatar.innerHTML = user.avatarUrl
    ? `<img src="${escapeHtml(safeExternalUrl(user.avatarUrl))}" alt="" />`
    : '';
}

async function loadClaims() {
  const result = await request('/people/me/claims');
  const labels = {
    pending: '等待审核',
    approved: '已通过',
    rejected: '未通过',
    cancelled: '已取消',
  };
  profileEls.claims.innerHTML = result.data.length ? result.data.map((claim) => `
    <article class="claim-item">
      <div><strong>${escapeHtml(claim.displayName)}</strong><p>${escapeHtml(claim.note || '未填写说明')}</p></div>
      <span class="claim-status ${escapeHtml(claim.status)}">${escapeHtml(labels[claim.status] || claim.status)}</span>
    </article>
  `).join('') : '<div class="empty">暂无认领申请。请在 CAS 项目成员列表中发起认领。</div>';
}

async function initProfile() {
  profileUser = await refreshCurrentUser();
  if (!profileUser) {
    profileEls.gate.classList.remove('is-hidden');
    return;
  }
  profileEls.app.classList.remove('is-hidden');
  renderProfileSummary(profileUser);
  profileEls.form.displayName.value = profileUser.displayName || '';
  profileEls.form.avatarUrl.value = profileUser.avatarUrl || '';
  profileEls.form.bio.value = profileUser.bio || '';
  profileEls.form.messagingPermission.value = profileUser.messagingPermission || 'everyone';
  await loadClaims();

  profileEls.form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const submit = profileEls.form.querySelector('[type="submit"]');
    submit.disabled = true;
    profileEls.message.textContent = '正在保存...';
    profileEls.message.classList.remove('error-text');
    try {
      const data = new FormData(profileEls.form);
      profileUser = await request('/users/me/profile', {
        method: 'PATCH',
        body: JSON.stringify({
          displayName: String(data.get('displayName') || '').trim(),
          avatarUrl: String(data.get('avatarUrl') || '').trim(),
          bio: String(data.get('bio') || '').trim(),
          messagingPermission: String(data.get('messagingPermission') || 'everyone'),
        }),
      });
      window.localStorage.setItem(AUTH_USER_KEY, JSON.stringify(profileUser));
      renderProfileSummary(profileUser);
      profileEls.message.textContent = '资料已保存';
    } catch (error) {
      profileEls.message.textContent = error.message;
      profileEls.message.classList.add('error-text');
    } finally {
      submit.disabled = false;
    }
  });
}

initProfile().catch((error) => {
  profileEls.gate.classList.remove('is-hidden');
  profileEls.gate.innerHTML = `<h1>个人中心暂时不可用</h1><p>${escapeHtml(error.message)}</p>`;
});
