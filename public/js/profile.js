const profileEls = {
  gate: document.querySelector('#profileGate'),
  app: document.querySelector('#profileApp'),
  form: document.querySelector('#profileForm'),
  title: document.querySelector('#profileTitle'),
  handle: document.querySelector('#profileHandle'),
  avatar: document.querySelector('#profileAvatarPreview'),
  accountLink: document.querySelector('#avatarAccountLink'),
  publicLink: document.querySelector('#publicProfileLink'),
  message: document.querySelector('#profileMessage'),
};

let profileUser = null;

function renderProfileSummary(user) {
  const name = user.displayName || user.username;
  profileEls.title.textContent = name;
  profileEls.handle.textContent = `@${user.username}`;
  profileEls.publicLink.href = `/user.html?id=${encodeURIComponent(user.id)}`;
  profileEls.accountLink.href = user.accountUrl || profileEls.accountLink.href;
  profileEls.avatar.dataset.initial = String(name).slice(0, 1).toUpperCase();
  profileEls.avatar.innerHTML = user.avatarUrl
    ? `<img src="${escapeHtml(safeExternalUrl(user.avatarUrl))}" alt="" />`
    : '';
}

function saveProfileUser(user) {
  profileUser = user;
  window.localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user));
  renderProfileSummary(user);
}

function setProfileMessage(message, isError = false) {
  profileEls.message.textContent = message;
  profileEls.message.classList.toggle('error-text', isError);
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
  profileEls.form.bio.value = profileUser.bio || '';
  profileEls.form.messagingPermission.value = profileUser.messagingPermission || 'everyone';
  profileEls.form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const submit = profileEls.form.querySelector('[type="submit"]');
    submit.disabled = true;
    setProfileMessage('正在保存...');
    try {
      const data = new FormData(profileEls.form);
      profileUser = await request('/users/me/profile', {
        method: 'PATCH',
        body: JSON.stringify({
          displayName: String(data.get('displayName') || '').trim(),
          bio: String(data.get('bio') || '').trim(),
          messagingPermission: String(data.get('messagingPermission') || 'everyone'),
        }),
      });
      saveProfileUser(profileUser);
      setProfileMessage('资料已保存');
    } catch (error) {
      setProfileMessage(error.message, true);
    } finally {
      submit.disabled = false;
    }
  });
}

initProfile().catch((error) => {
  profileEls.gate.classList.remove('is-hidden');
  profileEls.gate.innerHTML = `<h1>个人中心暂时不可用</h1><p>${escapeHtml(error.message)}</p>`;
});
