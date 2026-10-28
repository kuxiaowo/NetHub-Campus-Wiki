/* Submission status and explicit governance actions; all content is textContent. */
(() => {
  'use strict';
  const element = (tag, text = '') => {
    const node = document.createElement(tag);
    if (typeof text === 'function') setUiText(node, text);
    else node.textContent = text;
    return node;
  };
  function button(label, action) {
    const node = element('button', label);
    node.type = 'button'; node.className = 'button compact secondary';
    node.addEventListener('click', async () => {
      node.disabled = true;
      try { await action(); } catch (error) { window.alert(error.message); }
      finally { node.disabled = false; }
    });
    return node;
  }
  const labels = {pending:'待审核',review:'待人工复核',published:'已公开',rejected:'未通过',withdrawn:'已撤回'};
  function submission(row, admin, refresh) {
    const node = element('article'); node.className = 'card';
    node.append(element('h3', () => `${tr(({profile:'个人简介',update:'项目动态',comment:'评论'})[row.kind] || row.kind)} · ${tr(labels[row.status] || row.status)}`));
    if (admin) {
      node.append(element('p', ut`提交者：${row.author || row.author_username || tr('未知')} · 用户 ID ${row.user_id}`));
      if (row.kind === 'update') node.append(element('p', ut`项目：${row.target_title || tr('已删除项目')} · ID ${row.target_id}`));
    }
    if (row.created_at) node.append(element('p', () => tr('提交时间：') + formatSiteTimestamp(row.created_at, {year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})));
    node.append(element('p', row.content || tr('仅图片内容')));
    if (row.error_code) node.append(element('p', () => tr('审核服务异常，内容保持待审：') + row.error_code));
    if (row.ai?.explanation) node.append(element('p', () => tr('审核结论：') + row.ai.explanation));
    if (row.decision_note) node.append(element('p', () => tr('处理说明：') + row.decision_note));
    for (const id of row.mediaIds || []) {
      const image = element('img'); image.src = `${String(API_BASE).replace(/\/$/, '')}/content-media/${encodeURIComponent(id)}`;
      image.alt = tr('投稿图片'); image.loading = 'lazy'; image.style.maxWidth = '240px'; node.append(image);
    }
    if (['pending','review'].includes(row.status)) {
      if (admin) {
        for (const [action,label] of [['approve',tr('人工批准')],['reject',tr('拒绝公开')],['retry',tr('重新 AI 审核')]]) {
          node.append(button(label, async () => {
            const note = window.prompt(tr('填写处理原因（必填，最多 500 字）'));
            if (!note?.trim()) return;
            await request(`/admin/content-review/${encodeURIComponent(row.id)}/decision`, {method:'POST',body:JSON.stringify({action,note})});
            await refresh();
          }));
        }
      } else {
        node.append(button(tr('撤回提交'), async () => {
          const path = row.kind === 'comment' ? `/comments/${row.id.split(':')[1]}` : `/content-submissions/${encodeURIComponent(row.id)}`;
          await request(path,{method:'DELETE'}); await refresh();
        }));
      }
    }
    return node;
  }
  async function personal() {
    const root = document.querySelector('[data-my-submissions]');
    if (!root) return;
    const user = await refreshCurrentUser(); if (!user) return;
    const status = document.querySelector('[data-community-status]');
    status.replaceChildren(element('p', () => ut`邮箱：${user.emailVerified ? tr('已验证') : tr('未验证，请到账号中心验证')}`));
    if (user.isMuted) status.append(element('p', ut`本站禁言：${user.muteReason}；${user.mutedUntil ? '至 ' + new Date(user.mutedUntil*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}) : tr('永久')}`));
    const link = element('a',tr('管理邮箱、邀请及微信申诉')); link.href = (user.accountUrl || 'https://auth.nethub.wiki/account').replace(/\/account$/, '/account/community'); status.append(link);
    let page = 1;
    async function load() {
      const result = await request(`/content-submissions?page=${page}`);
      root.replaceChildren(...result.data.map(row=>submission(row,false,load)));
      if (!result.data.length) root.append(element('p',tr('暂无提交记录。')));
      if(page>1)root.append(button(tr('上一页'),async()=>{page--;await load();}));
      if(result.data.length===20)root.append(button(tr('下一页'),async()=>{page++;await load();}));
    }
    document.addEventListener('profile-saved', () => {
      page = 1;
      load().catch(error => { root.textContent = error.message; });
    });
    root.before(button(tr('刷新审核状态'),load)); await load();
  }
  function admin() {
    const root = document.querySelector('[data-content-review]'); if (!root) return;
    const nav = element('div'); const list = element('div'); const feedback = element('p');feedback.setAttribute('role','status');
    let state='review', page=1, loadVersion=0;
    async function load() {
      const version = ++loadVersion;
      try {
        const result=await request(`/admin/content-review?state=${state}&page=${page}`);
        if (version !== loadVersion) return;
        list.replaceChildren(...result.data.map(row=>submission(row,true,load)));
        if(!result.data.length)list.append(element('p',tr('当前没有记录。')));
        if(page>1)list.append(button(tr('上一页'),async()=>{page--;await load();}));
        if(result.data.length===20)list.append(button(tr('下一页'),async()=>{page++;await load();}));
        feedback.textContent='';
      }catch(error){if (version === loadVersion) feedback.textContent=error.message;}
    }
    for (const name of Object.keys(labels)) {
      const filter = button(() => tr(labels[name]), async () => {
        state=name; page=1;
        for (const control of nav.children) control.setAttribute('aria-pressed', String(control.dataset.state === state));
        await load();
      });
      filter.dataset.state = name;
      filter.setAttribute('aria-pressed', String(name === state));
      nav.append(filter);
    }
    root.append(element('h2',tr('动态与个人简介审核')),nav,feedback,list);
    const users=document.createElement('form');users.className='card';
    const userFeedback=element('p');userFeedback.setAttribute('role','status');
    const id=element('input');id.type='number';id.min='1';id.required=true;id.placeholder=tr('Wiki 用户 ID');id.setAttribute('aria-label',tr('Wiki 用户 ID'));
    const action=element('select');for(const [value,label]of[['mute',tr('本站禁言')],['unmute',tr('解除禁言')]]){const option=element('option',label);option.value=value;action.append(option);}action.setAttribute('aria-label',tr('处罚操作'));
    const days=element('select');for(const [value,label]of[[0,tr('永久')],[1,tr('1 天')],[7,tr('7 天')],[30,tr('30 天')]]){const option=element('option',label);option.value=value;days.append(option);}days.setAttribute('aria-label',tr('处罚期限'));
    const reason=element('input');reason.required=true;reason.maxLength=500;reason.placeholder=tr('处罚或解除原因');reason.setAttribute('aria-label',tr('处罚或解除原因'));
    const submit=element('button',tr('执行本站限制'));submit.type='submit';submit.className='button';
    users.append(element('h3',tr('本站禁言')),id,action,days,reason,submit,userFeedback);
    const account=element('a',tr('全站封禁与暂停邀请：进入账号中心管理'));account.href='https://auth.nethub.wiki/admin';users.append(account);
    users.addEventListener('submit',async event=>{event.preventDefault();submit.disabled=true;try{await request(`/admin/users/${Number(id.value)}/mute`,{method:'POST',body:JSON.stringify({action:action.value,days:Number(days.value),reason:reason.value})});setUiText(userFeedback, () => tr('本站限制已更新'));document.getElementById('refreshUsers')?.click();}catch(error){userFeedback.textContent=error.message;}finally{submit.disabled=false;}});
    const target=document.querySelector('[data-admin-panel="users"]')||root;target.append(users);
    document.querySelector('[data-admin-view="moderation"]')?.addEventListener('click',()=>{load();});
  }
  if(document.querySelector('[data-my-submissions]'))personal().catch(error=>{document.querySelector('[data-my-submissions]').textContent=error.message;});
  admin();
})();
