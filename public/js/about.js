const aboutAccountCards = [...document.querySelectorAll('[data-account-member]')];
const aboutContactLabels = {
  wechat: '微信',
  phone: '电话',
  email: '邮箱',
  other: '联系方式',
};

function aboutMemberMatches(member, alias) {
  const normalizedAlias = String(alias || '').trim().toLowerCase();
  const searchable = [member?.name, member?.username, member?.displayName]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
  return normalizedAlias && searchable.includes(normalizedAlias);
}

async function bindAboutMemberAccounts() {
  if (!aboutAccountCards.length) return;

  const projects = await request('/projects?search=NetHub');
  const nethubProject = (projects.data || []).find(
    (project) => String(project.name || '').trim().toLowerCase() === 'nethub',
  );
  if (!nethubProject) return;

  const result = await request(`/projects/${encodeURIComponent(nethubProject.id)}`);
  const members = result.data?.memberList || [];

  aboutAccountCards.forEach((card) => {
    const alias = card.dataset.accountMember;
    const member = members.find((item) => aboutMemberMatches(item, alias));
    if (!member) return;

    const name = card.querySelector('[data-member-name]');
    if (name && member.name) name.textContent = member.name;

    const contact = card.querySelector('[data-member-contact]');
    if (contact) {
      contact.textContent = member.contactValue
        ? `${aboutContactLabels[member.contactType] || '联系方式'}：${member.contactValue}`
        : '联系方式：未提供';
    }

    if (!member?.userId) return;

    card.href = `/user.html?id=${encodeURIComponent(member.userId)}`;
    card.classList.add('is-account-bound');
    card.setAttribute('aria-label', `${member.name || alias}，查看站内主页`);
    card.title = '查看站内主页';
  });
}

bindAboutMemberAccounts().catch(() => {
  // 后端暂不可用时保留静态联系卡片，不影响关于页其他内容。
});
