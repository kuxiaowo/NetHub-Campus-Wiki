const messageState = {
  user: null,
  conversations: [],
  active: null,
  messages: [],
  otherLastReadMessageId: null,
  socket: null,
  socketPing: null,
  pollTimer: null,
  searchTimer: null,
  sharedProject: null,
  view: 'messages',
  activityKind: null,
  activityItems: [],
  activityPage: 1,
  activityHasMore: false,
  activityLatestId: 0,
};

const messageEls = {
  gate: document.querySelector('#messagesGate'),
  app: document.querySelector('#messagesApp'),
  list: document.querySelector('#conversationList'),
  chatEmpty: document.querySelector('#chatEmpty'),
  chatActive: document.querySelector('#chatActive'),
  chatUserLink: document.querySelector('#chatUserLink'),
  chatAvatar: document.querySelector('#chatAvatar'),
  chatName: document.querySelector('#chatName'),
  chatUsername: document.querySelector('#chatUsername'),
  messageList: document.querySelector('#messageList'),
  composer: document.querySelector('#messageComposer'),
  input: document.querySelector('#messageInput'),
  status: document.querySelector('#messageStatus'),
  searchPanel: document.querySelector('#userSearchPanel'),
  searchInput: document.querySelector('#messageUserSearch'),
  searchResults: document.querySelector('#messageUserResults'),
  hideButton: document.querySelector('#hideConversationButton'),
  backButton: document.querySelector('#backConversationButton'),
  newButton: document.querySelector('#newConversationButton'),
  projectShare: document.querySelector('#projectSharePreview'),
  directView: document.querySelector('#directMessagesView'),
  activityView: document.querySelector('#messageActivityView'),
  activityTitle: document.querySelector('#messageActivityTitle'),
  activityList: document.querySelector('#messageActivityList'),
  activityMore: document.querySelector('#messageActivityMore'),
  viewButtons: [...document.querySelectorAll('[data-message-view]')],
};

function displayUserName(user) {
  return String(user?.displayName || user?.username || '校园用户');
}

function initialsFor(user) {
  return escapeHtml(displayUserName(user).trim().slice(0, 1).toUpperCase() || '用');
}

function avatarMarkup(user, className = 'user-avatar') {
  const url = user?.avatarUrl ? safeExternalUrl(user.avatarUrl) : null;
  return `<span class="${className}" data-initial="${initialsFor(user)}">${url && url !== '#'
    ? `<img src="${escapeHtml(url)}" alt="" loading="lazy" />`
    : ''}</span>`;
}

function messageTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const today = new Date();
  const sameDay = date.toDateString() === today.toDateString();
  return new Intl.DateTimeFormat('zh-CN', sameDay
    ? { hour: '2-digit', minute: '2-digit' }
    : { month: '2-digit', day: '2-digit' }).format(date);
}

function fullMessageTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function activityTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function activityTitle(kind) {
  return kind === 'reply' ? '回复我的' : '收到的赞';
}

function activityEmptyText(kind) {
  return kind === 'reply' ? '还没有人回复你的留言' : '还没有收到留言点赞';
}

function renderActivityItem(item) {
  const actorName = displayUserName(item.actor);
  const unavailable = !item.comment?.available || !item.target?.available || !item.target?.url;
  const action = item.kind === 'reply' ? '回复了你的留言' : '赞了你的留言';
  const missing = item.kind === 'reply' ? '该回复已删除或不存在' : '该留言已删除或不存在';
  const content = unavailable ? missing : (item.comment.content || missing);
  const body = `
    ${avatarMarkup(item.actor)}
    <span class="message-activity-copy">
      <p><strong>${escapeHtml(actorName)}</strong> ${action}</p>
      <small>${escapeHtml(content)}</small>
      <time>${escapeHtml(activityTime(item.createdAt))}</time>
    </span>
    <span class="message-activity-target">${escapeHtml(item.target?.title || '原内容已不存在')}</span>
  `;
  if (unavailable) {
    return `<article class="message-activity-item disabled ${item.read ? '' : 'unread'}">${body}</article>`;
  }
  return `<a class="message-activity-item ${item.read ? '' : 'unread'}" href="${escapeHtml(item.target.url)}">${body}</a>`;
}

function renderActivityList() {
  if (!messageState.activityItems.length) {
    messageEls.activityList.innerHTML = `<div class="message-activity-empty">${activityEmptyText(messageState.activityKind)}</div>`;
  } else {
    messageEls.activityList.innerHTML = messageState.activityItems.map(renderActivityItem).join('');
  }
  messageEls.activityMore.classList.toggle('is-hidden', !messageState.activityHasMore);
  messageEls.activityMore.disabled = false;
}

async function loadActivity(kind, { append = false } = {}) {
  if (!append) {
    messageState.activityKind = kind;
    messageState.activityPage = 1;
    messageState.activityItems = [];
    messageEls.activityList.innerHTML = '<div class="message-activity-empty">正在加载...</div>';
  }
  const query = new URLSearchParams({
    kind,
    page: String(messageState.activityPage),
    pageSize: '20',
  });
  const result = await request(`/comment-notifications?${query}`);
  messageState.activityItems = append
    ? [...messageState.activityItems, ...(result.data || [])]
    : (result.data || []);
  messageState.activityHasMore = Boolean(result.hasMore);
  messageState.activityLatestId = Number(result.latestId || 0);
  renderActivityList();

  if (!append && messageState.activityLatestId) {
    try {
      await request('/comment-notifications/read', {
        method: 'POST',
        body: JSON.stringify({ kind, throughId: messageState.activityLatestId }),
      });
      messageState.activityItems.forEach((item) => { item.read = true; });
      renderActivityList();
      await loadUnreadCounts();
    } catch {
      // 已加载的通知仍然可读；下次进入分类时继续尝试更新已读状态。
    }
  }
}

async function setMessageView(view, { updateHistory = true } = {}) {
  const normalized = ['messages', 'replies', 'likes'].includes(view) ? view : 'messages';
  messageState.view = normalized;
  messageEls.viewButtons.forEach((button) => {
    const active = button.dataset.messageView === normalized;
    button.classList.toggle('active', active);
    if (active) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
  const direct = normalized === 'messages';
  messageEls.directView.classList.toggle('is-hidden', !direct);
  messageEls.activityView.classList.toggle('is-hidden', direct);
  if (!direct) messageEls.app.classList.remove('show-chat');

  if (updateHistory) {
    const url = new URL(window.location.href);
    url.searchParams.delete('targetUserId');
    url.searchParams.delete('projectId');
    if (normalized === 'messages') url.searchParams.delete('view');
    else url.searchParams.set('view', normalized);
    window.history.pushState({ view: normalized }, '', url);
  }

  if (!direct) {
    const kind = normalized === 'replies' ? 'reply' : 'like';
    messageEls.activityTitle.textContent = activityTitle(kind);
    try {
      await loadActivity(kind);
    } catch (error) {
      messageEls.activityList.innerHTML = `<div class="message-activity-empty error-text">${escapeHtml(error.message)}</div>`;
      messageEls.activityMore.classList.add('is-hidden');
    }
  }
}

function renderConversationList() {
  if (!messageState.conversations.length) {
    messageEls.list.innerHTML = '<div class="conversation-empty">还没有私信，点击“＋”找同学聊聊</div>';
    return;
  }
  messageEls.list.innerHTML = messageState.conversations.map((conversation) => {
    const user = conversation.otherUser;
    const active = Number(messageState.active?.id) === Number(conversation.id);
    return `
      <button class="conversation-item ${active ? 'active' : ''}" type="button" data-conversation-id="${escapeHtml(conversation.id)}">
        ${avatarMarkup(user)}
        <span class="conversation-copy">
          <span class="conversation-title">
            <strong>${escapeHtml(displayUserName(user))}</strong>
            <time>${escapeHtml(messageTime(conversation.lastMessageAt))}</time>
          </span>
          <span class="conversation-preview">${escapeHtml(conversation.lastMessage?.body || '开始聊天')}</span>
        </span>
        ${conversation.unreadCount ? `<span class="conversation-unread">${escapeHtml(Math.min(conversation.unreadCount, 99))}</span>` : ''}
      </button>
    `;
  }).join('');
}

async function loadUnreadCounts() {
  try {
    const counts = await request('/message-center/unread-count');
    document.querySelectorAll('.message-nav-badge').forEach((badge) => {
      const total = Number(counts.total || 0);
      badge.textContent = total > 99 ? '99+' : String(total);
      badge.classList.toggle('is-hidden', !total);
      badge.closest('.message-nav-link')?.setAttribute(
        'aria-label',
        total ? `消息中心，${total} 条未读消息` : '消息中心',
      );
    });
    document.querySelectorAll('[data-message-view-badge]').forEach((badge) => {
      const count = Number(counts[badge.dataset.messageViewBadge] || 0);
      badge.textContent = count > 99 ? '99+' : String(count);
      badge.classList.toggle('is-hidden', !count);
    });
  } catch {
    // 页面本身仍可继续工作，角标失败不应打断会话。
  }
}

async function loadConversations({ keepActive = true } = {}) {
  const result = await request('/conversations');
  messageState.conversations = result.data || [];
  if (keepActive && messageState.active) {
    const fresh = messageState.conversations.find((item) => Number(item.id) === Number(messageState.active.id));
    if (fresh) messageState.active = fresh;
  }
  renderConversationList();
  await loadUnreadCounts();
}

function renderChatHeader() {
  const user = messageState.active?.otherUser;
  if (!user) return;
  messageEls.chatUserLink.href = `/user.html?id=${encodeURIComponent(user.id)}`;
  messageEls.chatAvatar.dataset.initial = displayUserName(user).slice(0, 1).toUpperCase();
  messageEls.chatAvatar.innerHTML = user.avatarUrl
    ? `<img src="${escapeHtml(safeExternalUrl(user.avatarUrl))}" alt="" />`
    : '';
  messageEls.chatName.textContent = displayUserName(user);
  messageEls.chatUsername.textContent = `@${user.username || ''}`;
}

function renderMessage(message) {
  const own = Number(message.sender.id) === Number(messageState.user.id);
  const project = message.project ? `
    <a class="message-project-card" href="/detail.html?id=${encodeURIComponent(message.project.id)}">
      <strong>${escapeHtml(message.project.name)}</strong>
      <span>${escapeHtml(message.project.year || '')} · 查看 CAS 项目</span>
    </a>
  ` : '';
  return `
    <article class="message-row ${own ? 'own' : ''}" data-message-id="${escapeHtml(message.id)}">
      ${own ? '' : avatarMarkup(message.sender, 'message-avatar')}
      <div class="message-bubble-wrap">
        <div class="message-bubble ${message.recalled ? 'recalled' : ''}">
          ${message.recalled ? '消息已撤回' : `<p>${escapeHtml(message.body)}</p>${project}`}
        </div>
        <div class="message-meta">
          <time>${escapeHtml(fullMessageTime(message.createdAt))}</time>
          ${own && Number(message.id) <= Number(messageState.otherLastReadMessageId || 0) ? '<span>已读</span>' : ''}
          ${!own && !message.recalled ? `<button type="button" data-report-message="${escapeHtml(message.id)}">举报</button>` : ''}
          ${own && !message.recalled ? `<button type="button" data-recall-message="${escapeHtml(message.id)}">撤回</button>` : ''}
        </div>
      </div>
    </article>
  `;
}

function renderMessages() {
  if (!messageState.messages.length) {
    messageEls.messageList.innerHTML = '<div class="message-day-tip">还没有消息，打个招呼吧。</div>';
    return;
  }
  messageEls.messageList.innerHTML = messageState.messages.map(renderMessage).join('');
  messageEls.messageList.scrollTop = messageEls.messageList.scrollHeight;
}

async function loadMessages(conversation) {
  messageState.active = conversation;
  messageEls.chatEmpty.classList.add('is-hidden');
  messageEls.chatActive.classList.remove('is-hidden');
  renderConversationList();
  renderChatHeader();
  const result = await request(`/conversations/${encodeURIComponent(conversation.id)}/messages`);
  messageState.messages = result.data || [];
  messageState.otherLastReadMessageId = result.otherLastReadMessageId;
  renderMessages();
  const last = messageState.messages.at(-1);
  if (last) {
    await request(`/conversations/${encodeURIComponent(conversation.id)}/read`, {
      method: 'POST',
      body: JSON.stringify({ messageId: last.id }),
    }).catch(() => null);
  }
  await loadUnreadCounts();
  if (window.innerWidth <= 760) messageEls.app.classList.add('show-chat');
}

async function selectConversation(id) {
  const conversation = messageState.conversations.find((item) => Number(item.id) === Number(id));
  if (!conversation) return;
  await loadMessages(conversation);
}

async function openUserConversation(user) {
  const result = await request('/conversations', {
    method: 'POST',
    body: JSON.stringify({ targetUserId: user.id }),
  });
  messageEls.searchPanel.classList.add('is-hidden');
  await loadConversations();
  const conversation = messageState.conversations.find((item) => Number(item.id) === Number(result.data.id)) || {
    id: result.data.id,
    otherUser: user,
    unreadCount: 0,
    lastMessage: null,
  };
  await loadMessages(conversation);
  messageEls.input.focus();
}

async function searchUsers() {
  const keyword = messageEls.searchInput.value.trim();
  if (!keyword) {
    messageEls.searchResults.innerHTML = '<p>输入昵称或姓名开始查找。</p>';
    return;
  }
  try {
    const result = await request(`/users?search=${encodeURIComponent(keyword)}&limit=20`);
    const users = result.data || [];
    messageEls.searchResults.innerHTML = users.length ? users.map((user) => `
      <button class="message-user-result" type="button" data-start-user="${escapeHtml(user.id)}">
        ${avatarMarkup(user)}
        <span><strong>${escapeHtml(displayUserName(user))}</strong><small>@${escapeHtml(user.username)}</small></span>
        ${user.campusVerified ? '<span class="verified-dot" title="已关联校园档案">✓</span>' : ''}
      </button>
    `).join('') : '<p>没有找到匹配的用户。</p>';
    messageEls.searchResults.querySelectorAll('[data-start-user]').forEach((button) => {
      button.addEventListener('click', () => {
        const user = users.find((item) => String(item.id) === button.dataset.startUser);
        if (user) openUserConversation(user).catch((error) => {
          messageEls.searchResults.innerHTML = `<p class="error-text">${escapeHtml(error.message)}</p>`;
        });
      });
    });
  } catch (error) {
    messageEls.searchResults.innerHTML = `<p class="error-text">${escapeHtml(error.message)}</p>`;
  }
}

async function sendCurrentMessage() {
  const body = messageEls.input.value.trim();
  if ((!body && !messageState.sharedProject) || !messageState.active) return;
  const submit = messageEls.composer.querySelector('[type="submit"]');
  submit.disabled = true;
  messageEls.status.textContent = '正在发送...';
  try {
    const result = await request(`/conversations/${encodeURIComponent(messageState.active.id)}/messages`, {
      method: 'POST',
      body: JSON.stringify({
        type: messageState.sharedProject ? 'project' : 'text',
        body,
        projectId: messageState.sharedProject?.id,
        clientMessageId: `${Date.now()}-${crypto.randomUUID?.() || Math.random().toString(36).slice(2)}`,
      }),
    });
    messageEls.input.value = '';
    messageState.sharedProject = null;
    messageEls.projectShare.classList.add('is-hidden');
    messageEls.projectShare.innerHTML = '';
    messageEls.status.textContent = '';
    if (!messageState.messages.some((item) => Number(item.id) === Number(result.data.id))) {
      messageState.messages.push(result.data);
      renderMessages();
    }
    await loadConversations();
  } catch (error) {
    messageEls.status.textContent = error.message;
    messageEls.status.classList.add('error-text');
  } finally {
    submit.disabled = false;
  }
}

async function connectMessageStream() {
  if (!messageState.user) return;
  try {
    const result = await request('/messages/stream-ticket', { method: 'POST' });
    const base = new URL(apiBaseUrl(), window.location.href);
    base.protocol = base.protocol === 'https:' ? 'wss:' : 'ws:';
    base.pathname = `${base.pathname.replace(/\/$/, '')}/messages/ws`;
    base.search = `ticket=${encodeURIComponent(result.ticket)}`;
    const socket = new WebSocket(base.href);
    messageState.socket = socket;
    socket.addEventListener('open', () => {
      messageState.socketPing = window.setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) socket.send('ping');
      }, 30000);
    });
    socket.addEventListener('message', async (event) => {
      const payload = JSON.parse(event.data);
      await loadConversations();
      if (messageState.view === 'messages'
          && messageState.active
          && Number(payload.conversationId) === Number(messageState.active.id)) {
        await loadMessages(messageState.active);
      }
    });
    socket.addEventListener('close', () => {
      window.clearInterval(messageState.socketPing);
      messageState.socketPing = null;
      window.setTimeout(connectMessageStream, 3000);
    });
  } catch {
    // 短轮询仍会保持消息可用。
  }
}

function bindMessageEvents() {
  messageEls.viewButtons.forEach((button) => {
    button.addEventListener('click', () => {
      setMessageView(button.dataset.messageView).catch((error) => {
        messageEls.activityList.innerHTML = `<div class="message-activity-empty error-text">${escapeHtml(error.message)}</div>`;
      });
    });
  });
  messageEls.activityMore.addEventListener('click', async () => {
    messageEls.activityMore.disabled = true;
    messageState.activityPage += 1;
    try {
      await loadActivity(messageState.activityKind, { append: true });
    } catch (error) {
      messageState.activityPage -= 1;
      messageEls.activityMore.disabled = false;
      messageEls.activityList.insertAdjacentHTML(
        'beforeend',
        `<div class="message-activity-empty error-text">${escapeHtml(error.message)}</div>`,
      );
    }
  });
  window.addEventListener('popstate', () => {
    const view = new URLSearchParams(window.location.search).get('view') || 'messages';
    setMessageView(view, { updateHistory: false }).catch(() => null);
  });
  messageEls.list.addEventListener('click', (event) => {
    const button = event.target.closest('[data-conversation-id]');
    if (button) selectConversation(button.dataset.conversationId).catch((error) => {
      messageEls.list.innerHTML = `<div class="conversation-empty error-text">${escapeHtml(error.message)}</div>`;
    });
  });
  messageEls.newButton.addEventListener('click', () => {
    messageEls.searchPanel.classList.toggle('is-hidden');
    if (!messageEls.searchPanel.classList.contains('is-hidden')) {
      messageEls.searchInput.focus();
      searchUsers();
    }
  });
  messageEls.searchInput.addEventListener('input', () => {
    window.clearTimeout(messageState.searchTimer);
    messageState.searchTimer = window.setTimeout(searchUsers, 250);
  });
  messageEls.composer.addEventListener('submit', (event) => {
    event.preventDefault();
    sendCurrentMessage();
  });
  messageEls.input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      messageEls.composer.requestSubmit();
    }
  });
  messageEls.messageList.addEventListener('click', async (event) => {
    const recallButton = event.target.closest('[data-recall-message]');
    const reportButton = event.target.closest('[data-report-message]');
    try {
      if (recallButton) {
        await request(`/messages/${encodeURIComponent(recallButton.dataset.recallMessage)}/recall`, { method: 'POST' });
        await loadMessages(messageState.active);
        await loadConversations();
      }
      if (reportButton) {
        const reason = window.prompt('请简要说明举报原因。', '');
        if (reason === null || !reason.trim()) return;
        await request(`/messages/${encodeURIComponent(reportButton.dataset.reportMessage)}/reports`, {
          method: 'POST',
          body: JSON.stringify({ reason: reason.trim() }),
        });
        messageEls.status.textContent = '举报已提交';
      }
    } catch (error) {
      messageEls.status.textContent = error.message;
      messageEls.status.classList.add('error-text');
    }
  });
  messageEls.hideButton.addEventListener('click', async () => {
    if (!messageState.active) return;
    await request(`/conversations/${encodeURIComponent(messageState.active.id)}`, { method: 'DELETE' });
    messageState.active = null;
    messageEls.chatActive.classList.add('is-hidden');
    messageEls.chatEmpty.classList.remove('is-hidden');
    await loadConversations({ keepActive: false });
  });
  messageEls.backButton.addEventListener('click', () => {
    messageEls.app.classList.remove('show-chat');
  });
  messageEls.projectShare.addEventListener('click', (event) => {
    if (!event.target.closest('[data-remove-shared-project]')) return;
    messageState.sharedProject = null;
    messageEls.projectShare.classList.add('is-hidden');
    messageEls.projectShare.innerHTML = '';
  });
}

async function initMessages() {
  messageState.user = await refreshCurrentUser();
  if (!messageState.user) {
    messageEls.app.classList.add('is-hidden');
    messageEls.gate.classList.remove('is-hidden');
    return;
  }
  messageEls.app.classList.remove('is-hidden');
  bindMessageEvents();
  await loadConversations();

  const pageQuery = new URLSearchParams(window.location.search);
  const targetUserId = pageQuery.get('targetUserId');
  const sharedProjectId = pageQuery.get('projectId');
  const initialView = targetUserId || sharedProjectId ? 'messages' : (pageQuery.get('view') || 'messages');
  await setMessageView(initialView, { updateHistory: false });
  if (targetUserId && Number(targetUserId) !== Number(messageState.user.id)) {
    try {
      const profile = await request(`/users/${encodeURIComponent(targetUserId)}`);
      await openUserConversation(profile.data);
      if (sharedProjectId) {
        const project = await request(`/projects/${encodeURIComponent(sharedProjectId)}`);
        messageState.sharedProject = project.data;
        messageEls.projectShare.innerHTML = `
          <span><strong>${escapeHtml(project.data.name)}</strong><small>将随消息发送 CAS 项目卡片</small></span>
          <button type="button" data-remove-shared-project aria-label="移除项目卡片">×</button>
        `;
        messageEls.projectShare.classList.remove('is-hidden');
      }
    } catch (error) {
      messageEls.list.innerHTML = `<div class="conversation-empty error-text">${escapeHtml(error.message)}</div>`;
    }
  }
  connectMessageStream();
  messageState.pollTimer = window.setInterval(async () => {
    await loadConversations().catch(() => null);
    if (messageState.view === 'messages' && messageState.active) {
      await loadMessages(messageState.active).catch(() => null);
    }
    await loadUnreadCounts().catch(() => null);
  }, 10000);
}

window.addEventListener('campusWikiAuthChange', (event) => {
  const signedIn = Boolean(event.detail?.user);
  if (signedIn !== Boolean(messageState.user)) window.location.reload();
});

initMessages().catch((error) => {
  messageEls.app.classList.add('is-hidden');
  messageEls.gate.classList.remove('is-hidden');
  messageEls.gate.innerHTML = `<h1>消息中心暂时不可用</h1><p>${escapeHtml(error.message)}</p>`;
});
