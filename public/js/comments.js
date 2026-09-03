(function commentModule() {
  const mountedSections = new WeakMap();
  const activeStates = new Set();

  function commentDate(value) {
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

  function commentDisplayName(user) {
    return String(user?.displayName || user?.username || '校园用户');
  }

  function commentAvatar(user, className = 'comment-avatar') {
    const name = commentDisplayName(user);
    const avatar = user?.avatarUrl ? safeExternalUrl(user.avatarUrl) : null;
    return `
      <span class="${className}" data-initial="${escapeHtml(name.slice(0, 1).toUpperCase())}">
        ${avatar && avatar !== '#' ? `<img src="${escapeHtml(avatar)}" alt="" loading="lazy" />` : ''}
      </span>
    `;
  }

  function canDeleteComment(state, comment) {
    return state.currentUser
      && (Number(state.currentUser.id) === Number(comment.author.id) || state.currentUser.role === 'admin');
  }

  function renderCommentBody(comment) {
    if (comment.status === 'deleted') return '<p class="comment-deleted">该留言已删除</p>';
    const replyTo = comment.replyToUser
      ? comment.replyToUser.deleted
        ? `<span class="comment-reply-to">回复 ${escapeHtml(commentDisplayName(comment.replyToUser))}</span>`
        : `<a class="comment-reply-to" href="/user.html?id=${encodeURIComponent(comment.replyToUser.id)}">回复 @${escapeHtml(commentDisplayName(comment.replyToUser))}</a>`
      : '';
    return `<p class="comment-content">${replyTo}${replyTo ? '：' : ''}${escapeHtml(comment.content)}</p>`;
  }

  function renderCommentActions(state, comment) {
    if (comment.status === 'deleted') return '';
    const likeLabel = comment.liked ? '取消点赞' : '点赞';
    return `
      <div class="comment-actions">
        <button class="comment-like-button ${comment.liked ? 'liked' : ''}" type="button"
          data-comment-action="like" data-comment-id="${escapeHtml(comment.id)}"
          data-liked="${comment.liked ? 'true' : 'false'}" aria-label="${likeLabel}" title="${likeLabel}">
          <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path d="M7.5 10.2 11 3.7c.35-.65 1.15-.9 1.82-.58.6.29.9.98.72 1.62l-.9 3.26h4.78a2.4 2.4 0 0 1 2.34 2.95l-1.65 7A2.65 2.65 0 0 1 15.53 20H7.5V10.2Z"></path>
            <path d="M3.5 9.5h4v10h-4z"></path>
          </svg>
          ${comment.likeCount ? `<span>${escapeHtml(comment.likeCount)}</span>` : ''}
        </button>
        <button type="button" data-comment-action="reply" data-comment-id="${escapeHtml(comment.id)}" data-comment-author="${escapeHtml(commentDisplayName(comment.author))}">回复</button>
        ${canDeleteComment(state, comment)
          ? `<button type="button" data-comment-action="delete" data-comment-id="${escapeHtml(comment.id)}">删除</button>`
          : `<button type="button" data-comment-action="report" data-comment-id="${escapeHtml(comment.id)}">举报</button>`}
      </div>
    `;
  }

  function renderSingleComment(state, comment, reply = false) {
    return `
      <article id="comment-${escapeHtml(comment.id)}" class="${reply ? 'comment-reply' : 'comment-root'}" data-comment-item="${escapeHtml(comment.id)}">
        ${commentAvatar(comment.author, reply ? 'comment-avatar small' : 'comment-avatar')}
        <div class="comment-main">
          <header class="comment-author-line">
            ${comment.author.deleted
              ? `<span>${escapeHtml(commentDisplayName(comment.author))}</span>`
              : `<a href="/user.html?id=${encodeURIComponent(comment.author.id)}">${escapeHtml(commentDisplayName(comment.author))}</a>`}
            ${comment.author.campusVerified ? '<span class="comment-verified" title="已关联校园档案">✓</span>' : ''}
            <time>${escapeHtml(commentDate(comment.createdAt))}</time>
          </header>
          ${renderCommentBody(comment)}
          ${renderCommentActions(state, comment)}
          <div class="comment-reply-slot" data-reply-slot-for="${escapeHtml(comment.id)}"></div>
        </div>
      </article>
    `;
  }

  function renderThread(state, root) {
    return `
      <section class="comment-thread">
        ${renderSingleComment(state, root)}
        ${root.replies?.length ? `
          <div class="comment-replies">
            ${root.replies.map((reply) => renderSingleComment(state, reply, true)).join('')}
          </div>
        ` : ''}
      </section>
    `;
  }

  function renderComposer(state) {
    if (!state.currentUser) {
      return `
        <div class="comment-login-tip">
          <span>登录后可以留言、回复和点赞。</span>
          <button class="button compact" type="button" data-comment-login>去登录</button>
        </div>
      `;
    }
    return `
      <form class="comment-composer" data-comment-composer>
        ${commentAvatar(state.currentUser)}
        <div>
          <textarea maxlength="1000" placeholder="友善交流，说说你的看法..." required></textarea>
          <footer>
            <span data-comment-message aria-live="polite"></span>
            <button class="button compact" type="submit">发布留言</button>
          </footer>
        </div>
      </form>
    `;
  }

  function renderShell(state) {
    state.element.innerHTML = `
      <header class="comments-head">
        <div>
          <p class="home-section-kicker">Discussion</p>
          <h2>留言与讨论 <span data-comment-total></span></h2>
        </div>
        <div class="comment-sort" role="group" aria-label="留言排序">
          <button class="${state.sort === 'hot' ? 'active' : ''}" type="button" data-comment-sort="hot">热门</button>
          <button class="${state.sort === 'latest' ? 'active' : ''}" type="button" data-comment-sort="latest">最新</button>
        </div>
      </header>
      ${renderComposer(state)}
      <div class="comment-list" data-comment-list><div class="empty">正在加载留言...</div></div>
      <div class="comment-more-wrap"><button class="button secondary compact is-hidden" type="button" data-comment-more>加载更多</button></div>
    `;
  }

  function renderComments(state, response, append) {
    const list = state.element.querySelector('[data-comment-list]');
    const markup = response.data.map((comment) => renderThread(state, comment)).join('');
    if (append) {
      list.insertAdjacentHTML('beforeend', markup);
    } else {
      list.innerHTML = markup || '<div class="empty">还没有留言，来做第一个发言的人吧。</div>';
    }
    state.element.querySelector('[data-comment-total]').textContent = response.total ? `(${response.total})` : '';
    const more = state.element.querySelector('[data-comment-more]');
    more.classList.toggle('is-hidden', !response.hasMore);
    more.disabled = false;
  }

  async function revealFocusedComment(state) {
    if (!state.focusCommentId) return;
    const selector = `[data-comment-item="${CSS.escape(String(state.focusCommentId))}"]`;
    let focused = state.element.querySelector(selector);
    if (!focused) {
      const response = await request(`/comments/${encodeURIComponent(state.focusCommentId)}/context`);
      const list = state.element.querySelector('[data-comment-list]');
      list.insertAdjacentHTML(
        'afterbegin',
        `<div class="comment-focus-context">${renderThread(state, response.data)}</div>`,
      );
      focused = state.element.querySelector(selector);
    }
    if (!focused) return;
    focused.classList.add('comment-focused');
    window.requestAnimationFrame(() => {
      focused.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  }

  async function loadComments(state, { append = false } = {}) {
    const query = new URLSearchParams({
      targetType: state.targetType,
      targetId: String(state.targetId),
      sort: state.sort,
      page: String(state.page),
      pageSize: '10',
    });
    const response = await request(`/comments?${query}`);
    renderComments(state, response, append);
    if (!append) await revealFocusedComment(state);
  }

  async function submitComment(state, content, parentId = null) {
    await request('/comments', {
      method: 'POST',
      body: JSON.stringify({
        targetType: state.targetType,
        targetId: state.targetId,
        content,
        parentId,
      }),
    });
    state.page = 1;
    await loadComments(state);
  }

  function openReplyForm(state, button) {
    if (!state.currentUser) {
      window.alert('请先登录再回复。');
      return;
    }
    const commentId = button.dataset.commentId;
    const slot = state.element.querySelector(`[data-reply-slot-for="${CSS.escape(commentId)}"]`);
    if (!slot) return;
    state.element.querySelectorAll('.inline-reply-form').forEach((form) => form.remove());
    slot.innerHTML = `
      <form class="inline-reply-form" data-inline-reply data-parent-id="${escapeHtml(commentId)}">
        <textarea maxlength="1000" placeholder="回复 @${escapeHtml(button.dataset.commentAuthor || '')}" required></textarea>
        <div>
          <button class="text-button" type="button" data-comment-action="cancel-reply">取消</button>
          <button class="button compact" type="submit">回复</button>
        </div>
      </form>
    `;
    slot.querySelector('textarea').focus();
  }

  function bindCommentEvents(state) {
    state.element.addEventListener('submit', async (event) => {
      const composer = event.target.closest('[data-comment-composer]');
      const replyForm = event.target.closest('[data-inline-reply]');
      if (!composer && !replyForm) return;
      event.preventDefault();
      const form = composer || replyForm;
      const textarea = form.querySelector('textarea');
      const content = textarea.value.trim();
      if (!content) return;
      const submit = form.querySelector('[type="submit"]');
      submit.disabled = true;
      try {
        await submitComment(state, content, replyForm?.dataset.parentId || null);
        textarea.value = '';
      } catch (error) {
        const message = composer?.querySelector('[data-comment-message]');
        if (message) {
          message.textContent = error.message;
          message.classList.add('error-text');
        } else {
          window.alert(error.message);
        }
      } finally {
        submit.disabled = false;
      }
    });

    state.element.addEventListener('click', async (event) => {
      const loginButton = event.target.closest('[data-comment-login]');
      if (loginButton) {
        document.querySelector('[data-open-auth]')?.click();
        return;
      }
      const sortButton = event.target.closest('[data-comment-sort]');
      if (sortButton) {
        state.sort = sortButton.dataset.commentSort;
        state.page = 1;
        state.element.querySelectorAll('[data-comment-sort]').forEach((item) => item.classList.toggle('active', item === sortButton));
        try {
          await loadComments(state);
        } catch (error) {
          window.alert(error.message);
        }
        return;
      }
      const moreButton = event.target.closest('[data-comment-more]');
      if (moreButton) {
        moreButton.disabled = true;
        state.page += 1;
        try {
          await loadComments(state, { append: true });
        } catch (error) {
          state.page -= 1;
          moreButton.disabled = false;
          window.alert(error.message);
        }
        return;
      }
      const action = event.target.closest('[data-comment-action]');
      if (!action) return;
      if (action.dataset.commentAction === 'cancel-reply') {
        action.closest('.inline-reply-form')?.remove();
        return;
      }
      if (action.dataset.commentAction === 'reply') {
        openReplyForm(state, action);
        return;
      }
      if (!state.currentUser) {
        window.alert('请先登录再进行操作。');
        return;
      }
      const commentId = action.dataset.commentId;
      try {
        if (action.dataset.commentAction === 'like') {
          await request(`/comments/${encodeURIComponent(commentId)}/like`, {
            method: action.dataset.liked === 'true' ? 'DELETE' : 'POST',
          });
        }
        if (action.dataset.commentAction === 'delete') {
          if (!window.confirm('确认删除这条留言？回复关系会保留。')) return;
          await request(`/comments/${encodeURIComponent(commentId)}`, { method: 'DELETE' });
        }
        if (action.dataset.commentAction === 'report') {
          const reason = window.prompt('请填写举报理由。', '');
          if (reason === null || !reason.trim()) return;
          await request(`/comments/${encodeURIComponent(commentId)}/reports`, {
            method: 'POST',
            body: JSON.stringify({ reason: reason.trim() }),
          });
          window.alert('举报已提交');
        }
        state.page = 1;
        await loadComments(state);
      } catch (error) {
        window.alert(error.message);
      }
    });
  }

  async function mountCommentSection(element, targetType, targetId) {
    if (!element || !targetType || !targetId) return;
    const existing = mountedSections.get(element);
    if (existing && existing.targetType === targetType && Number(existing.targetId) === Number(targetId)) return;
    const state = {
      element,
      targetType,
      targetId: Number(targetId),
      currentUser: getStoredUser(),
      sort: 'hot',
      page: 1,
      focusCommentId: (() => {
        const raw = Number(new URLSearchParams(window.location.search).get('commentId'));
        return Number.isInteger(raw) && raw > 0 ? raw : null;
      })(),
    };
    mountedSections.set(element, state);
    activeStates.add(state);
    renderShell(state);
    bindCommentEvents(state);
    try {
      await loadComments(state);
    } catch (error) {
      element.querySelector('[data-comment-list]').innerHTML = `<div class="empty error">${escapeHtml(error.message)}</div>`;
    }
  }

  window.mountCommentSection = mountCommentSection;
  window.addEventListener('campusWikiAuthChange', (event) => {
    activeStates.forEach((state) => {
      state.currentUser = event.detail?.user || null;
      state.page = 1;
      renderShell(state);
      loadComments(state).catch((error) => {
        state.element.querySelector('[data-comment-list]').innerHTML = `<div class="empty error">${escapeHtml(error.message)}</div>`;
      });
    });
  });
  document.querySelectorAll('[data-comments-target-type][data-comments-target-id]').forEach((element) => {
    mountCommentSection(
      element,
      element.dataset.commentsTargetType,
      element.dataset.commentsTargetId,
    );
  });
}());
