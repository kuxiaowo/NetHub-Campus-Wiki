(() => {
  'use strict';
  const reasons = {harassment:'辱骂骚扰与校园霸凌',hate:'仇恨与歧视',sexual:'色情及不当性内容',violence:'暴力威胁与鼓励自伤',privacy:'隐私泄露',fraud:'诈骗与危险行为引导',spam:'广告灌水与恶意刷屏',other:'其他'};
  const siteDateTime = value => formatSiteTimestamp(value, { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const e = (v) => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function api(path, options={}) {
    const headers = new Headers(options.headers);
    if (options.body) headers.set('Content-Type','application/json');
    const response = await fetch(`${window.CAMPUS_WIKI_CONFIG?.apiBaseUrl || '/api'}${path}`,{...options,headers,credentials:'same-origin',cache:'no-store'});
    const result = response.status===204 ? {} : await response.json();
    if (!response.ok) throw new Error(result.detail || '请求失败');
    return result;
  }
  function chooseReasons(selected=[]) {
    return new Promise(resolve=>{
      const dialog=document.createElement('dialog'); dialog.className='mod-dialog';
      dialog.innerHTML=`<form><h2>删除内容</h2><p>删除后向作者发送最终原因，保留正常回复。</p><fieldset><legend>删除原因（可多选）</legend>${Object.entries(reasons).map(([id,label])=>`<label class="mod-check"><input type="checkbox" name="reason" value="${id}" ${selected.includes(id)?'checked':''}>${label}</label>`).join('')}</fieldset><label class="mod-field">补充说明<textarea name="note" maxlength="1000" placeholder="选择其他时必须填写"></textarea></label><p data-error role="alert"></p><div class="mod-actions"><button type="button" data-cancel>取消</button><button type="submit">确认删除</button></div></form>`;
      document.body.append(dialog); dialog.showModal();
      let result=null;
      dialog.addEventListener('close',()=>{dialog.remove();resolve(result);},{once:true});
      dialog.querySelector('[data-cancel]').onclick=()=>dialog.close();
      dialog.querySelector('form').onsubmit=event=>{
        event.preventDefault(); const form=new FormData(event.target); const values=form.getAll('reason'); const note=String(form.get('note')).trim();
        if (!values.length || (values.includes('other')&&!note)) {dialog.querySelector('[data-error]').textContent='请选择原因；选择其他时请填写说明。';return;}
        result={reasons:values,note}; dialog.close();
      };
    });
  }
  async function deleteComment(id,done,selected=[]) {
    const payload=await chooseReasons(selected); if (!payload) return false;
    await api(`/admin/moderation/comments/${encodeURIComponent(id)}/delete`,{method:'POST',body:JSON.stringify(payload)});
    if (done) await done(); return true;
  }
  function renderNotifications(container,result,append=false) {
    const fragment=document.createDocumentFragment();
    result.data.forEach(item=>{
      const card=document.createElement('article'); card.className=`mod-card mod-notification ${item.read?'':'unread'}`;
      if (item.type === 'report') {
        const message = item.audience === 'author'
          ? '你发布的内容已被管理员删除。'
          : item.decision === 'deleted'
            ? '感谢您的举报，内容已删除。'
            : (item.note ? `感谢您的举报，${item.note}` : '感谢您的举报，举报已被管理员驳回。');
        const authorReason = item.audience === 'author' && item.reasonCodes?.length
          ? `<p><strong>处理原因：</strong>${item.reasonCodes.map(code=>e(reasons[code] || '其他')).join('、')}</p>${item.note?`<p>${e(item.note)}</p>`:''}` : '';
        card.innerHTML=`<header><strong>${e(item.title)}</strong><time>${e(siteDateTime(item.createdAt))}</time></header><p class="mod-notification-excerpt">${e(item.excerpt || '原内容已不可见')}</p><p>${e(message)}</p>${authorReason}`;
      } else {
        card.innerHTML=`<header><strong>${e(item.title)}</strong><time>${e(siteDateTime(item.createdAt))}</time></header><p class="mod-notification-excerpt">${e(item.excerpt || '原内容已不可见')}</p><p>你在「${e(item.target.title)}」发表的${item.title.startsWith('回复')?'回复':'评论'}已被管理员删除。</p><p><strong>处理原因：</strong>${item.reasons.map(e).join('、')}</p><details><summary>查看详情</summary><p>${e(item.note || '管理员已确认上述处理原因。')}</p><p>留言编号：${e(item.commentId)}</p>${item.target.available?`<a href="${e(item.target.url)}">查看原页面</a>`:'<p>原页面已不存在或不可访问。</p>'}</details>`;
      }
      fragment.append(card);
    });
    if (!append) container.replaceChildren(); container.append(fragment);
    if (!container.childElementCount) container.textContent='暂无系统消息';
  }
  window.NetHubModeration=Object.freeze({api,chooseReasons,deleteComment,renderNotifications});

  const root=document.querySelector('[data-moderation-app]'); if (!root) return;
  const lists={review:{page:1,data:[],hasMore:false},passed:{page:1,data:[],hasMore:false},other:{page:1,data:[],hasMore:false}};
  let config=null, currentState='failed', loading=false;
  root.innerHTML=`<div class="mod-card"><h2>评论审核</h2><p>两站共用 AI 配置与总并发池。本页复核列表仅显示本站内容。</p><p data-status role="status">正在加载</p><details class="mod-settings"><summary>AI 接口与运行设置</summary><form data-settings><div class="mod-grid"><label class="mod-field">接口格式<select name="provider"><option value="codex">服务器 Codex 额度</option><option value="openai">OpenAI 兼容接口</option></select></label><label class="mod-field">总并发上限<input name="concurrency" type="number" min="1" max="32" required></label><label class="mod-field">Base URL<input name="baseUrl" type="url"></label><label class="mod-field">API Key<input name="apiKey" type="password" autocomplete="new-password" placeholder="留空保留已有密钥"></label><label class="mod-field">模型<select name="model"><option value="">请获取模型列表</option></select></label><label class="mod-field">推理强度<select name="effort"><option value="">模型默认</option></select></label><label class="mod-field">请求超时（秒）<input name="timeout" type="number" min="10" max="600" required></label><label class="mod-field">Codex 程序路径<input name="codexCommand" placeholder="codex"></label></div><label class="mod-check"><input name="enabled" type="checkbox">启用后台审核</label><div class="mod-actions"><button type="button" data-models>获取模型</button><button type="button" data-login>登录 Codex</button><button type="button" data-test>测试接口</button><button type="submit">保存共享配置</button></div><p data-config-message role="status"></p><div data-login-info></div><div data-quota></div></form></details></div><div class="mod-toolbar"><strong>新评论与回复</strong><button type="button" data-refresh>刷新</button></div><div class="mod-columns"><section class="mod-lane" aria-labelledby="mod-review-title"><h3 id="mod-review-title">AI 发现问题 <span data-count="review"></span></h3><p class="mod-lane-hint">内容已暂时隐藏，等待人工复核。</p><div data-cases="review"></div><button type="button" data-more="review" hidden>加载更多</button></section><section class="mod-lane" aria-labelledby="mod-passed-title"><h3 id="mod-passed-title">AI 已通过 <span data-count="passed"></span></h3><p class="mod-lane-hint">内容已公开，可忽略这条审核消息或删除内容。</p><div data-cases="passed"></div><button type="button" data-more="passed" hidden>加载更多</button></section></div><section class="mod-other" aria-labelledby="mod-other-title"><div class="mod-toolbar"><h3 id="mod-other-title">其他状态</h3><label>显示<select data-state><option value="failed">审核失败</option><option value="queued">排队中</option><option value="dispatch">待派发</option><option value="running">审核中</option><option value="history">处理历史</option></select></label></div><div data-cases="other"></div><button type="button" data-more="other" hidden>加载更多</button></section>`;
  const form=root.querySelector('[data-settings]'), message=root.querySelector('[data-config-message]');
  let models=[];
  const payload=()=>({provider:form.provider.value,baseUrl:form.baseUrl.value,apiKey:form.apiKey.value,model:form.model.value,effort:form.effort.value,concurrency:Number(form.concurrency.value),timeout:Number(form.timeout.value),codexCommand:form.codexCommand.value,enabled:form.enabled.checked});
  async function action(fn) { try {message.textContent='正在处理…';await fn();} catch(error){message.textContent=error.message;} }
  function setEfforts() {
    const selected=models.find(m=>(m.model||m.id)===form.model.value);
    const value=form.effort.value || config?.effort || '';
    form.effort.innerHTML='<option value="">模型默认</option>'+(selected?.supportedReasoningEfforts||[]).map(r=>`<option value="${e(r.reasoningEffort)}">${e(r.reasoningEffort)}</option>`).join('');
    form.effort.value=value; if (!form.effort.value) form.effort.value='';
  }
  async function discover() {
    const result=await api('/admin/moderation/models',{method:'POST',body:JSON.stringify(payload())}); models=result.data;
    const value=form.model.value || config?.model || '';
    form.model.innerHTML='<option value="">请选择模型</option>'+models.map(m=>`<option value="${e(m.model||m.id)}">${e(m.displayName||m.id)}</option>`).join('');
    form.model.value=value; setEfforts();
    message.textContent=`已获取 ${models.length} 个模型${result.account?'，服务器账号已登录':''}`;
    if (result.quota) showQuota(result.quota);
  }
  function showQuota(quota) {
    const buckets=quota.rateLimitsByLimitId || {default:quota.rateLimits};
    root.querySelector('[data-quota]').textContent=Object.entries(buckets).filter(([,v])=>v).map(([name,b])=>`${name}：`+['primary','secondary'].filter(k=>b[k]).map(k=>`${b[k].windowDurationMins || '?'} 分钟窗口剩余 ${Math.max(0,100-(b[k].usedPercent||0)).toFixed(1)}%`).join('；')).join(' / ');
  }
  function caseCard(item) {
    const stateName=({review:'待复核',failed:'审核失败',passed:'AI 已通过',dismissed:'已忽略',deleted:'已删除',queued:'排队中',cancelled:'已取消'})[item.state]||item.state;
    const ignoreLabel=item.state==='review'?'忽略并恢复':'忽略';
    return `<article class="mod-card mod-case" data-case="${item.id}"><header><strong>${e(item.author)} · ${e(item.target.title)}</strong><time>${e(siteDateTime(item.createdAt))}</time></header><p class="mod-original">${e(item.content || '正文已删除')}</p>${item.parentContent?`<details><summary>回复上下文</summary><p class="mod-original">${e(item.parentContent)}</p></details>`:''}<p>状态：${e(stateName)}</p>${item.ai.explanation?`<p>AI：${e(item.ai.explanation)}</p><p>判断原因：${(item.ai.categories||[]).map(c=>e(reasons[c])).join('、')||'无'}</p>`:''}${item.ai.evidence?.length?`<details><summary>AI 原文证据</summary><p>${item.ai.evidence.map(e).join('；')}</p></details>`:''}${item.error?`<p>故障：${e(item.error)}；尝试 ${item.attempts} 次</p>`:''}${item.finalReasons?.length?`<p>最终原因：${item.finalReasons.map(c=>e(reasons[c])).join('、')} ${e(item.finalNote)}</p>`:''}<div class="mod-actions">${['review','failed','passed'].includes(item.state)?`<button type="button" data-ignore>${ignoreLabel}</button><button type="button" data-delete>删除内容</button>`:''}${item.state==='failed'?'<button type="button" data-retry>重试审核</button>':''}${item.target.available?`<a href="${e(item.target.url)}">查看原页面</a>`:''}</div></article>`;
  }
  async function loadCases(kind,append=false) {
    const list=lists[kind], state=kind==='other'?currentState:kind;
    const result=await api(`/admin/moderation/cases?state=${state}&page=${list.page}`);
    list.data=append?[...list.data,...result.data]:result.data;list.hasMore=result.hasMore;
    root.querySelector(`[data-cases="${kind}"]`).innerHTML=list.data.map(caseCard).join('')||'<div class="mod-card mod-empty">暂无记录</div>';
    root.querySelector(`[data-more="${kind}"]`).hidden=!list.hasMore;
    if(kind!=='other') root.querySelector(`[data-count="${kind}"]`).textContent=`${result.total} 条`;
  }
  async function loadAllCases() {
    for(const kind of Object.keys(lists)) lists[kind].page=1;
    await Promise.all(Object.keys(lists).map(kind=>loadCases(kind)));
  }
  async function status() {
    const result=await api('/admin/moderation/status'); const queue=Object.entries(result.queue||{}).map(([k,v])=>`${({review:'待复核',failed:'失败',queued:'排队',dispatch:'待派发',running:'运行',passed:'通过',deleted:'删除',dismissed:'忽略'})[k]||k} ${v}`).join(' · ');
    const login=result.codexLogin?` · Codex ${({logged_in:'已登录',logged_out:'未登录',unavailable:'暂不可用'})[result.codexLogin]||result.codexLogin}`:'';
    root.querySelector('[data-status]').textContent=`${result.message}${login} · 活动请求 ${result.active||0}/${result.concurrency||config?.concurrency||2}${queue?' · '+queue:''}`;
    if(result.quota) showQuota(result.quota);
  }
  async function load() {
    if(loading) return;loading=true;
    try {
      config=await api('/admin/moderation/settings');
      for(const key of ['provider','baseUrl','codexCommand','concurrency','timeout']) form[key].value=config[key];
      form.enabled.checked=config.enabled; form.apiKey.value='';form.apiKey.placeholder=config.keyConfigured?'已有密钥；留空保留':'请输入 API Key';
      form.model.innerHTML=config.model?`<option value="${e(config.model)}">${e(config.model)}</option>`:'<option value="">请获取模型列表</option>';
      form.effort.innerHTML='<option value="">模型默认</option>'+(config.effort?`<option selected value="${e(config.effort)}">${e(config.effort)}</option>`:'');
      await status(); await loadAllCases();
      try {await discover();} catch(error){message.textContent=error.message;}
    } catch(error) {root.querySelector('[data-status]').textContent=error.message;await loadAllCases().catch(()=>{});} finally{loading=false;}
  }
  form.onsubmit=event=>{event.preventDefault();action(async()=>{config=await api('/admin/moderation/settings',{method:'PATCH',body:JSON.stringify(payload())});form.apiKey.value='';message.textContent='已保存，配置影响 Wiki 和 CAS 两站。';await status();});};
  form.provider.onchange=()=>action(discover);form.model.onchange=setEfforts;
  root.querySelector('[data-models]').onclick=()=>action(discover);
  root.querySelector('[data-test]').onclick=()=>action(async()=>{await api('/admin/moderation/test',{method:'POST',body:JSON.stringify(payload())});message.textContent='连接及审核结果校验成功';});
  async function login(type='chatgptDeviceCode') {
    const info=await api('/admin/moderation/codex/login',{method:'POST',body:JSON.stringify({type})});
    const url=info.verificationUri || info.verificationUrl || info.authUrl || info.deviceAuthUrl;
    const code=info.userCode || info.user_code || '';
    const container=root.querySelector('[data-login-info]');container.replaceChildren();
    const p=document.createElement('p');p.textContent=`服务器登录验证码：${code || '请打开登录页面'}`;container.append(p);
    if (url && new URL(url).protocol==='https:') {const a=document.createElement('a');a.href=url;a.target='_blank';a.rel='noopener noreferrer';a.textContent='打开官方登录页面';container.append(a);}
    message.textContent=info.requiresSshTunnel?'请先运行 ssh -N -L 1455:127.0.0.1:1455 nethub-server，再打开登录页面；完成后获取模型。':'完成登录后点击获取模型。';
  }
  root.querySelector('[data-login]').onclick=()=>action(()=>login());
  const browserLogin=document.createElement('button');browserLogin.type='button';browserLogin.textContent='浏览器登录';browserLogin.title='设备登录受限时使用；需通过 SSH 转发服务器 1455 端口';
  browserLogin.onclick=()=>action(()=>login('chatgpt'));root.querySelector('[data-login]').after(browserLogin);
  root.querySelector('[data-state]').onchange=event=>{currentState=event.target.value;lists.other.page=1;action(()=>loadCases('other'));};
  root.querySelector('[data-refresh]').onclick=()=>action(async()=>{await status();await loadAllCases();});
  root.querySelectorAll('[data-more]').forEach(button=>button.onclick=()=>action(async()=>{const kind=button.dataset.more;lists[kind].page++;try{await loadCases(kind,true);}catch(error){lists[kind].page--;throw error;}}));
  root.querySelectorAll('[data-cases]').forEach(container=>container.onclick=event=>action(async()=>{
    const card=event.target.closest('[data-case]');if(!card) return;
    const kind=container.dataset.cases;
    const item=lists[kind].data.find(row=>String(row.id)===card.dataset.case);let body;
    if(event.target.matches('[data-delete]')) {body=await chooseReasons(item.ai.categories||[]);if(!body)return;body.action='delete';}
    else if(event.target.matches('[data-ignore]')) body={action:'ignore'};
    else if(event.target.matches('[data-retry]')) {await api(`/admin/moderation/cases/${item.id}/retry`,{method:'POST'});await loadAllCases();await status();return;}
    else return;
    await api(`/admin/moderation/cases/${item.id}/decision`,{method:'POST',body:JSON.stringify(body)});await loadAllCases();await status();message.textContent='处理完成';
  }));
  document.querySelectorAll('[data-admin-view="moderation"]').forEach(button=>button.addEventListener('click',load));
  window.setInterval(()=>{if(!document.hidden && root.getClientRects().length)status().catch(()=>{});},10000);
})();
