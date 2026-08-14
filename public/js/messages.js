const messageState = {
  currentUser: null,
  conversations: [],
  activeConversationId: null,
  messages: [],
  hasMoreMessages: false,
  loadingOlder: false,
  pollTimer: null,
  searchTimer: null,
  loading: false,
};

const messageEls = {};

window.addEventListener('auth:changed', () => window.location.reload());

function messageDisplayName(user) {
  return user?.displayName || user?.username || '未知用户';
}

function messageInitial(user) {
  return String(messageDisplayName(user)).trim().slice(0, 1).toUpperCase() || '私';
}

function formatMessageTime(value) {
  if (!value) return '';
  const parsed = new Date(String(value).replace(' ', 'T'));
  if (Number.isNaN(parsed.getTime())) return String(value);
  const now = new Date();
  const sameDay = parsed.toDateString() === now.toDateString();
  return new Intl.DateTimeFormat('zh-CN', sameDay
    ? { hour: '2-digit', minute: '2-digit' }
    : { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }
  ).format(parsed);
}

function activeConversation() {
  return messageState.conversations.find(
    (item) => String(item.id) === String(messageState.activeConversationId),
  ) || null;
}

function renderConversationList() {
  const list = messageState.conversations;
  if (!list.length) {
    messageEls.conversationList.innerHTML = `
      <div class="conversation-empty">
        <strong>还没有会话</strong>
        <span>搜索一位同学开始聊天。</span>
      </div>
    `;
    return;
  }
  messageEls.conversationList.innerHTML = list.map((conversation) => {
    const other = conversation.otherUser;
    const last = conversation.lastMessage;
    const preview = last ? last.content : '新会话，发送第一条消息吧';
    return `
      <button
        class="conversation-item ${String(conversation.id) === String(messageState.activeConversationId) ? 'active' : ''}"
        type="button"
        data-conversation-id="${escapeHtml(conversation.id)}"
      >
        <span class="message-avatar">${escapeHtml(messageInitial(other))}</span>
        <span class="conversation-copy">
          <span class="conversation-title-row">
            <strong>${escapeHtml(messageDisplayName(other))}</strong>
            <time>${escapeHtml(formatMessageTime(last?.createdAt || conversation.updatedAt))}</time>
          </span>
          <span class="conversation-preview-row">
            <span>${last?.isMine ? '我：' : ''}${escapeHtml(truncateText(preview, 28))}</span>
            ${conversation.unreadCount ? `<b>${conversation.unreadCount > 99 ? '99+' : conversation.unreadCount}</b>` : ''}
          </span>
        </span>
      </button>
    `;
  }).join('');
}

function renderChatHeader() {
  const conversation = activeConversation();
  if (!conversation) return;
  const other = conversation.otherUser;
  messageEls.chatHeader.innerHTML = `
    <span class="message-avatar">${escapeHtml(messageInitial(other))}</span>
    <div>
      <strong>${escapeHtml(messageDisplayName(other))}</strong>
      <span>@${escapeHtml(other.username)}</span>
    </div>
  `;
}

function renderMessages(forceBottom = false) {
  const container = messageEls.messageList;
  const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
  const keepAtBottom = forceBottom || distanceFromBottom < 80;
  if (!messageState.messages.length) {
    container.innerHTML = '<div class="message-thread-empty">还没有消息，打个招呼吧。</div>';
  } else {
    container.innerHTML = `
      ${messageState.hasMoreMessages ? '<button class="load-older-messages" type="button" data-load-older-messages>加载更早消息</button>' : ''}
      ${messageState.messages.map((item) => `
      <article class="message-bubble-row ${item.isMine ? 'mine' : 'theirs'}">
        <div class="message-bubble">
          <p>${escapeHtml(item.content).replace(/\n/g, '<br>')}</p>
          <div>
            <time>${escapeHtml(formatMessageTime(item.createdAt))}</time>
            ${item.isMine ? `<span>${item.readAt ? '已读' : '未读'}</span>` : ''}
          </div>
        </div>
      </article>
      `).join('')}
    `;
  }
  if (keepAtBottom) container.scrollTop = container.scrollHeight;
}

async function refreshConversations() {
  const result = await fetchMessageConversations();
  messageState.conversations = result.data || [];
  renderConversationList();
  if (messageState.activeConversationId && !activeConversation()) {
    messageState.activeConversationId = null;
    showEmptyChat();
  } else if (messageState.activeConversationId) {
    renderChatHeader();
  }
}

async function refreshMessages(forceBottom = false) {
  if (!messageState.activeConversationId) return;
  const selectedId = messageState.activeConversationId;
  const result = await fetchConversationMessages(selectedId, { limit: 100 });
  if (String(selectedId) !== String(messageState.activeConversationId)) return;
  const fetchedMessages = result.data || [];
  if (!messageState.messages.length) {
    messageState.messages = fetchedMessages;
    messageState.hasMoreMessages = fetchedMessages.length === 100;
  } else {
    const merged = new Map(messageState.messages.map((item) => [Number(item.id), item]));
    fetchedMessages.forEach((item) => merged.set(Number(item.id), item));
    messageState.messages = [...merged.values()].sort((a, b) => Number(a.id) - Number(b.id));
  }
  renderMessages(forceBottom);
  const unreadMessages = messageState.messages.filter((item) => !item.isMine && !item.readAt);
  if (unreadMessages.length) {
    const upToId = Math.max(...unreadMessages.map((item) => Number(item.id)));
    await markMessageConversationRead(selectedId, upToId);
    window.dispatchEvent(new CustomEvent('messages:changed'));
    await refreshConversations();
  }
}

function showEmptyChat() {
  messageEls.chatEmpty.classList.remove('is-hidden');
  messageEls.chatActive.classList.add('is-hidden');
}

async function selectConversation(conversationId, forceBottom = true) {
  messageState.activeConversationId = Number(conversationId);
  messageState.messages = [];
  messageState.hasMoreMessages = false;
  messageEls.chatEmpty.classList.add('is-hidden');
  messageEls.chatActive.classList.remove('is-hidden');
  renderConversationList();
  renderChatHeader();
  messageEls.messageList.innerHTML = '<div class="message-thread-empty">正在加载消息...</div>';
  await refreshMessages(forceBottom);
  messageEls.messageContent.focus();
}

async function loadOlderMessages() {
  if (messageState.loadingOlder || !messageState.activeConversationId || !messageState.messages.length) return;
  messageState.loadingOlder = true;
  const oldHeight = messageEls.messageList.scrollHeight;
  const firstId = Math.min(...messageState.messages.map((item) => Number(item.id)));
  try {
    const result = await fetchConversationMessages(messageState.activeConversationId, {
      beforeId: firstId,
      limit: 100,
    });
    const older = result.data || [];
    const merged = new Map([...older, ...messageState.messages].map((item) => [Number(item.id), item]));
    messageState.messages = [...merged.values()].sort((a, b) => Number(a.id) - Number(b.id));
    messageState.hasMoreMessages = older.length === 100;
    renderMessages(false);
    messageEls.messageList.scrollTop += messageEls.messageList.scrollHeight - oldHeight;
  } finally {
    messageState.loadingOlder = false;
  }
}

async function startConversation(userId) {
  const result = await createMessageConversation(userId);
  await refreshConversations();
  await selectConversation(result.data.id);
  messageEls.userSearch.value = '';
  messageEls.userResults.classList.add('is-hidden');
  messageEls.userResults.innerHTML = '';
  window.history.replaceState({}, '', '/messages.html');
}

function renderUserResults(users) {
  messageEls.userResults.classList.remove('is-hidden');
  messageEls.userResults.innerHTML = users.length ? users.map((user) => `
    <button type="button" data-start-message-user="${escapeHtml(user.id)}">
      <span class="message-avatar">${escapeHtml(messageInitial(user))}</span>
      <span>
        <strong>${escapeHtml(messageDisplayName(user))}</strong>
        <small>@${escapeHtml(user.username)}</small>
      </span>
    </button>
  `).join('') : '<div class="message-search-empty">没有找到可私信的用户</div>';
}

async function runUserSearch() {
  const query = messageEls.userSearch.value.trim();
  if (!query) {
    messageEls.userResults.classList.add('is-hidden');
    messageEls.userResults.innerHTML = '';
    return;
  }
  try {
    const result = await searchMessageUsers(query);
    if (query !== messageEls.userSearch.value.trim()) return;
    renderUserResults(result.data || []);
  } catch (error) {
    messageEls.userResults.classList.remove('is-hidden');
    messageEls.userResults.innerHTML = `<div class="message-search-empty error-text">${escapeHtml(error.message)}</div>`;
  }
}

async function submitMessage(event) {
  event.preventDefault();
  if (!messageState.activeConversationId) return;
  const content = messageEls.messageContent.value.trim();
  if (!content) return;
  const button = messageEls.composer.querySelector('button[type="submit"]');
  button.disabled = true;
  messageEls.composerStatus.textContent = '正在发送...';
  try {
    await sendConversationMessage(messageState.activeConversationId, content);
    messageEls.messageContent.value = '';
    messageEls.composerStatus.textContent = '';
    await Promise.all([refreshMessages(true), refreshConversations()]);
    window.dispatchEvent(new CustomEvent('messages:changed'));
  } catch (error) {
    messageEls.composerStatus.textContent = error.message;
  } finally {
    button.disabled = false;
    messageEls.messageContent.focus();
  }
}

async function pollMessages() {
  if (messageState.loading || !messageState.currentUser) return;
  messageState.loading = true;
  try {
    await refreshConversations();
    await refreshMessages(false);
  } catch {
    // 短暂断网时保留当前界面，下一轮轮询会继续尝试。
  } finally {
    messageState.loading = false;
  }
}

async function initMessages() {
  Object.assign(messageEls, {
    loginGate: document.querySelector('#messagesLoginGate'),
    app: document.querySelector('#messagesApp'),
    conversationList: document.querySelector('#conversationList'),
    userSearch: document.querySelector('#messageUserSearch'),
    userResults: document.querySelector('#messageUserResults'),
    chatEmpty: document.querySelector('#chatEmpty'),
    chatActive: document.querySelector('#chatActive'),
    chatHeader: document.querySelector('#chatHeader'),
    messageList: document.querySelector('#messageList'),
    composer: document.querySelector('#messageComposer'),
    messageContent: document.querySelector('#messageContent'),
    composerStatus: document.querySelector('#messageComposerStatus'),
  });

  messageState.currentUser = await refreshCurrentUser();
  if (!messageState.currentUser) {
    messageEls.loginGate.classList.remove('is-hidden');
    return;
  }

  messageEls.app.classList.remove('is-hidden');
  await refreshConversations();

  const requestedUserId = Number(new URLSearchParams(window.location.search).get('user'));
  if (requestedUserId && requestedUserId !== Number(messageState.currentUser.id)) {
    try {
      await startConversation(requestedUserId);
    } catch (error) {
      messageEls.conversationList.insertAdjacentHTML(
        'afterbegin',
        `<div class="conversation-error">${escapeHtml(error.message)}</div>`,
      );
    }
  } else if (messageState.conversations.length) {
    await selectConversation(messageState.conversations[0].id);
  }

  messageEls.conversationList.addEventListener('click', (event) => {
    const button = event.target.closest('[data-conversation-id]');
    if (button) selectConversation(button.dataset.conversationId);
  });
  messageEls.messageList.addEventListener('click', (event) => {
    if (event.target.closest('[data-load-older-messages]')) {
      loadOlderMessages().catch((error) => {
        messageEls.composerStatus.textContent = error.message;
      });
    }
  });
  messageEls.userResults.addEventListener('click', (event) => {
    const button = event.target.closest('[data-start-message-user]');
    if (button) startConversation(button.dataset.startMessageUser).catch((error) => {
      messageEls.userResults.innerHTML = `<div class="message-search-empty error-text">${escapeHtml(error.message)}</div>`;
    });
  });
  messageEls.userSearch.addEventListener('input', () => {
    window.clearTimeout(messageState.searchTimer);
    messageState.searchTimer = window.setTimeout(runUserSearch, 250);
  });
  messageEls.composer.addEventListener('submit', submitMessage);
  messageEls.messageContent.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      messageEls.composer.requestSubmit();
    }
  });

  messageState.pollTimer = window.setInterval(pollMessages, 3000);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initMessages);
} else {
  initMessages();
}
