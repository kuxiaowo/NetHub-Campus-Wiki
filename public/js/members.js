// CAS 详情页和关于我们共用的成员渲染器。
const projectMembers = (() => {
function cleanText(value) {
  return String(value ?? '').trim();
}

function firstFilled(...values) {
  return values.map(cleanText).find(Boolean) || '';
}

function tryJson(value) {
  if (typeof value !== 'string') return value;
  const text = value.trim();
  if (!text || !['[', '{'].includes(text[0])) return value;
  try {
    return JSON.parse(text);
  } catch {
    return value;
  }
}

function asArray(value) {
  const parsed = tryJson(value);
  if (Array.isArray(parsed)) return parsed;
  if (parsed && typeof parsed === 'object') return [parsed];
  return cleanText(parsed) ? [parsed] : [];
}

function safeDetailUrl(value) {
  const raw = cleanText(value);
  if (!raw) return null;
  const url = safeExternalUrl(raw);
  return url === '#' ? null : url;
}

function initials(value) {
  const text = cleanText(value) || 'N';
  return escapeHtml(text.slice(0, 2).toUpperCase());
}

function normalizeMembers(project) {
  const parsed = tryJson(project.members);
  const memberSources = [
    project.memberList,
    parsed,
    project.memberContacts,
    project.contacts,
  ].map(tryJson).find((value) => {
    if (Array.isArray(value)) return value.length;
    if (value && typeof value === 'object') return true;
    return cleanText(value);
  });
  let members;
  const memberFromObject = (member) => ({
    name: firstFilled(member.name, member.displayName, member.username),
    role: cleanText(member.role),
    avatar: safeDetailUrl(firstFilled(member.avatarUrl, member.avatar, member.photo, member.image)),
    phone: firstFilled(member.phone, member.tel, member.mobile),
    email: firstFilled(member.email, member.mail),
    contactType: firstFilled(member.contactType, member.contact_type).toLowerCase(),
    contactValue: firstFilled(member.contactValue, member.contact_value, member.contact),
    info: [member.className, member.class, member.grade, member.major, member.school].map(cleanText).filter(Boolean).join(' · '),
    personId: member.personId || null,
    userId: member.userId || null,
    username: cleanText(member.username),
    registered: Boolean(member.registered || member.userId),
  });

  if (Array.isArray(memberSources)) {
    members = memberSources.map((member) => {
      if (member && typeof member === 'object') {
        return memberFromObject(member);
      }
      return { name: cleanText(member), role: '', avatar: null, phone: '', email: '', info: '', personId: null, userId: null, username: '', registered: false };
    });
  } else if (memberSources && typeof memberSources === 'object') {
    const nestedMembers = firstFilled(memberSources.members, memberSources.items, memberSources.list)
      ? asArray(memberSources.members || memberSources.items || memberSources.list)
      : [];
    members = (nestedMembers.length ? nestedMembers : [memberSources]).map((member) => {
      if (member && typeof member === 'object') {
        return memberFromObject(member);
      }
      return { name: cleanText(member), role: '', avatar: null, phone: '', email: '', info: '', personId: null, userId: null, username: '', registered: false };
    });
  } else {
    members = cleanText(memberSources)
      .split(/[,，、\n]/)
      .map((name) => ({ name: cleanText(name), role: '', avatar: null, phone: '', email: '', info: '', personId: null, userId: null, username: '', registered: false }));
  }

  const leader = cleanText(project.leader);
  members = members.filter((member) => member.name);
  if (leader && !members.some((member) => member.name === leader)) {
    members.unshift({ name: leader, role: '负责人', avatar: null, phone: '', email: '', info: '', personId: null, userId: null, username: '', registered: false });
  }

  return members.map((member) => ({
    ...member,
    role: member.role || (leader && member.name === leader ? '负责人' : '成员'),
  }));
}

function renderMemberContact(member) {
  const type = cleanText(member.contactType).toLowerCase();
  const value = cleanText(member.contactValue);
  if (value) {
    const labels = { wechat: '微信', phone: '电话', email: '邮箱', other: '其他联系方式' };
    return `<span>${escapeHtml(labels[type] || '联系方式')} ${escapeHtml(value)}</span>`;
  }
  return `
    ${member.phone ? `<span>电话 ${escapeHtml(member.phone)}</span>` : ''}
    ${member.email ? `<span>邮箱 ${escapeHtml(member.email)}</span>` : ''}
  `;
}

function renderMembers(project) {
  const members = normalizeMembers(project);
  const collapsed = members.length > 5;
  return `
    <aside class="detail-panel member-panel">
      <div class="detail-panel-head">
        <h2><span></span>成员列表 / 联系方式</h2>
      </div>
      ${members.length ? `
        <div class="member-list">
          ${members.map((member, index) => `
            <article class="member-card ${collapsed && index >= 5 ? 'is-collapsed' : ''}">
              <span class="member-avatar" data-initial="${initials(member.name)}">
                ${member.avatar ? `<img src="${escapeHtml(member.avatar)}" alt="${escapeHtml(member.name)}" data-fallback loading="lazy" />` : ''}
              </span>
              <div class="member-body">
                <div class="member-title">
                  ${member.userId
                    ? `<a href="/user.html?id=${encodeURIComponent(member.userId)}"><strong>${escapeHtml(member.name)}</strong></a>`
                    : `<strong>${escapeHtml(member.name)}</strong>`}
                  ${member.role ? `<span>${escapeHtml(member.role === 'leader' ? '负责人' : member.role === 'member' ? '成员' : member.role)}</span>` : ''}
                </div>
                ${member.info ? `<p>${escapeHtml(member.info)}</p>` : ''}
                <div class="member-contact">
                  ${renderMemberContact(member)}
                </div>
              </div>
            </article>
          `).join('')}
        </div>
        ${collapsed ? '<button class="member-more" type="button" data-toggle-members>查看全部成员</button>' : ''}
      ` : '<div class="empty detail-empty">暂无成员信息。</div>'}
    </aside>
  `;
}

function bindMemberInteractions(root = document) {
  root.querySelectorAll('.member-avatar img[data-fallback]').forEach((img) => {
    img.addEventListener('error', () => {
      img.closest('.member-avatar')?.classList.add('is-failed');
      img.remove();
    }, { once: true });
  });
  root.querySelector('[data-toggle-members]')?.addEventListener('click', (event) => {
    const expanded = event.currentTarget.closest('.member-panel').classList.toggle('is-expanded');
    event.currentTarget.textContent = expanded ? '收起成员列表' : '查看全部成员';
  });
}
return { render: renderMembers, bind: bindMemberInteractions };
})();
