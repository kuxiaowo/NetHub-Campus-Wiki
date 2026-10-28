const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Test the localization boundary without a browser: values from APIs must stay
// opaque, while authored labels and accessibility strings can change language.
function runtime(initial = {}) {
  const saved = new Map(Object.entries(initial));
  const document = {
    documentElement: { dataset: {}, style: {} },
    querySelectorAll: () => [],
  };
  const context = {
    document,
    localStorage: { getItem: key => saved.get(key), setItem: (key, value) => saved.set(key, value) },
    matchMedia: () => ({ matches: true, addEventListener() {} }),
    addEventListener() {}, dispatchEvent() {}, CustomEvent: class {},
    console, Intl,
  };
  context.window = context;
  vm.createContext(context);
  for (const name of ['translations.js', 'translations-static.js', 'i18n.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../public/js', name), 'utf8'), context);
  }
  return { context, saved, run: expression => vm.runInContext(expression, context) };
}

const zh = runtime();
assert.equal(zh.run('NetHubI18n.language'), 'zh');
assert.equal(zh.context.document.documentElement.lang, 'zh-CN');
assert.equal(zh.context.document.documentElement.dataset.theme, 'dark');
assert.equal(zh.run('tr("保存")'), '保存');

const en = runtime({ 'nethub-language': 'en', 'nethub-theme': 'light' });
assert.equal(en.context.document.documentElement.lang, 'en');
assert.equal(en.context.document.documentElement.dataset.theme, 'light');
assert.equal(en.run('tr("保存")'), 'Save');
assert.equal(en.run('ut`负责人：${"保存"}`'), 'Leader: 保存');

const card = en.run('ui`<article><h2>${"保存"}</h2><button>保存</button></article>`');
assert.match(card, /<h2>保存<\/h2>/, 'User titles matching a dictionary key must not be translated');
assert.match(card, />Save<\/span>/);
assert.match(card, /data-ui-text="保存"/);

const spread = en.run('ui`<button ${"data-item-id"}="${"12"}" ${"disabled"}>编辑</button>`');
assert.match(spread, /data-item-id="12" disabled>/, 'Dynamic attributes must not be normalized or corrupt');
assert.doesNotMatch(spread, /NHUI|nhui/);
assert.match(spread, />Edit<\/span>/);

const option = en.run('ui`<option value="${"最热"}">全部年份</option>`');
assert.match(option, /value="最热"/);
assert.match(option, />All years<\/option>/);
assert.doesNotMatch(option, /<span/);

const input = en.run('ui`<input placeholder="搜索活动名称" value="${"保存"}">`');
assert.match(input, /placeholder="Search activities"/);
assert.match(input, /value="保存"/);
assert.match(input, /data-ui-attrs=/);

const escaping = en.run('ui`<p>${"&lt;img src=x onerror=alert(1)&gt;"}</p>`');
assert.equal(escaping, '<p>&lt;img src=x onerror=alert(1)&gt;</p>');
assert.equal(en.run('ui`<textarea>${"保存"}</textarea>`'), '<textarea>保存</textarea>');

en.context.count = { isConnected: true, textContent: '' };
en.run('setUiText(count, () => ut`共 ${3} 个项目`)');
assert.match(en.context.count.textContent, /3.*projects/);
en.run('NetHubI18n.setLanguage("zh")');
assert.equal(en.context.count.textContent, '共 3 个项目');
assert.equal(en.saved.get('nethub-language'), 'zh');
en.context.count.textContent = 'Status cleared by application';
en.run('NetHubI18n.setLanguage("en")');
assert.equal(en.context.count.textContent, 'Status cleared by application');

const attrs = runtime();
const attributeHtml = attrs.run('ui`<a aria-label="查看 ${"保存 &amp; &quot;原文&quot; &lt;b&gt;"}（${2026}）">查看</a>`');
const decode = value => value.replace(/&(amp|lt|gt|quot|#39);/g, (_, name) => ({ amp: '&', lt: '<', gt: '>', quot: '"', '#39': "'" }[name]));
const descriptor = decode(attributeHtml.match(/data-ui-dynamic-attrs="([^"]*)"/)[1]);
assert.doesNotThrow(() => JSON.parse(descriptor));
const link = { dataset: { uiDynamicAttrs: descriptor }, attributes: {}, setAttribute(key, value) { this.attributes[key] = value; } };
const title = { tagName: 'TITLE', textContent: '用户项目标题 - NetHub', dataset: { uiText: '项目详情 - NetHub Campus Wiki' }, removeAttribute(key) { this.removed = key; } };
attrs.context.document.querySelectorAll = selector => selector === '[data-ui-dynamic-attrs]' ? [link] : selector === '[data-ui-text]' ? [title] : [];
attrs.run('NetHubI18n.setLanguage("en")');
assert.equal(link.attributes['aria-label'], 'View 保存 & "原文" <b>（2026）');
assert.equal(title.textContent, '用户项目标题 - NetHub');
assert.equal(title.removed, 'data-ui-text');
attrs.run('NetHubI18n.setLanguage("zh")');
assert.equal(link.attributes['aria-label'], '查看 保存 & "原文" <b>（2026）');

const derived = runtime({ 'nethub-language': 'en' });
derived.context.escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const apiSource = fs.readFileSync(path.join(__dirname, '../public/js/api.js'), 'utf8');
vm.runInContext(apiSource.slice(apiSource.indexOf('const BUILTIN_CATEGORY_LABELS'), apiSource.indexOf('/**', apiSource.indexOf('const BUILTIN_CATEGORY_LABELS'))), derived.context);
const homeSource = fs.readFileSync(path.join(__dirname, '../public/js/index.js'), 'utf8');
vm.runInContext(homeSource.slice(homeSource.indexOf('function photoActivityResource('), homeSource.indexOf('async function loadPopularResources(')), derived.context);
derived.context.activity = { id: 1, activity: '保存', year: 2026, hot: 4 };
assert.equal(derived.run('photoActivityResource(activity).label'), '活动照片');
assert.equal(derived.run('photoActivityResource(activity).title'), '保存');
assert.match(derived.run('categoryMarkup(photoActivityResource(activity).label)'), /data-ui-text="活动照片"/);
const category = { dataset: { uiText: '活动照片' }, textContent: derived.run('tr("活动照片")') };
const role = { dataset: { uiText: '负责人' }, textContent: derived.run('tr("负责人")') };
assert.match(derived.run('memberRoleMarkup("leader")'), /data-ui-text="负责人"/);
assert.equal(derived.run('memberRoleMarkup("保存")'), '保存');
derived.context.document.querySelectorAll = selector => selector === '[data-ui-text]' ? [category, role] : [];
derived.run('NetHubI18n.setLanguage("zh")');
assert.equal(category.textContent, '活动照片');
assert.equal(role.textContent, '负责人');
derived.run('NetHubI18n.setLanguage("en")');
assert.equal(category.textContent, derived.run('tr("活动照片")'));
assert.equal(role.textContent, 'Leader');

const htmlFiles = fs.readdirSync(path.join(__dirname, '../public')).filter(name => name.endsWith('.html') && name !== 'r2-player-test.html');
for (const name of htmlFiles) {
  const html = fs.readFileSync(path.join(__dirname, '../public', name), 'utf8');
  assert.ok(html.indexOf('/js/translations.js') < html.indexOf('/js/translations-static.js'), name);
  assert.ok(html.indexOf('/js/translations-static.js') < html.indexOf('/js/i18n.js'), name);
  assert.ok(html.indexOf('NetHubI18n.initialize()') < html.indexOf('/js/api.js'), name);
  assert.ok(html.includes('/assets/brand/favicon.svg'), name);
}
console.log('Frontend localization tests passed (content boundaries, markup, preferences, and page wiring).');
