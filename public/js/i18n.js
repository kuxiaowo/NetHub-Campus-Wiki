/* UI-only localization. API content is never scanned or translated. */
(function (global) {
  'use strict';
  const dictionary = global.NETHUB_TRANSLATIONS || {};
  const storage = {
    get(key, fallback) { try { return localStorage.getItem(key) || fallback; } catch { return fallback; } },
    set(key, value) { try { localStorage.setItem(key, value); } catch { /* Private browsing still works. */ } },
  };
  let language = storage.get('nethub-language', 'zh') === 'en' ? 'en' : 'zh';
  let theme = storage.get('nethub-theme', 'system');
  if (!['light', 'dark', 'system'].includes(theme)) theme = 'system';
  const darkMedia = global.matchMedia?.('(prefers-color-scheme: dark)');
  const chinese = /[\u3400-\u9fff]/;
  const liveText = new Map();
  const skip = 'script, style, textarea, pre, code, svg, [contenteditable], [data-user-content]';

  function translate(source) {
    const text = String(source ?? '');
    if (language !== 'en') return text;
    const key = text.trim();
    let value = dictionary[key];
    if (value === undefined) return text;
    if (/^\s/.test(text)) value = value.trimStart();
    if (/\s$/.test(text)) value = value.trimEnd();
    return text.replace(key, value);
  }
  function textTemplate(strings, ...values) {
    return strings.reduce((result, part, index) => result + translate(part) + (index < values.length ? String(values[index] ?? '') : ''), '');
  }
  function applyTheme() {
    const resolved = theme === 'system' ? (darkMedia?.matches ? 'dark' : 'light') : theme;
    document.documentElement.dataset.theme = resolved;
    document.documentElement.style.colorScheme = resolved;
    document.querySelectorAll('img[data-nethub-logo]').forEach((image) => {
      image.src = `/assets/brand/nethub-mark${resolved === 'dark' ? '-light' : ''}.svg`;
    });
    document.querySelectorAll('[data-theme-toggle]').forEach((button) => {
      const label = translate(resolved === 'dark' ? '切换浅色主题' : '切换深色主题');
      button.textContent = resolved === 'dark' ? '☀' : '☾';
      button.setAttribute('aria-label', label);
      button.title = label;
      button.dataset.preference = theme;
    });
  }
  function updateMarked(root = document) {
    root.querySelectorAll('[data-ui-text]').forEach((element) => {
      if (element.tagName === 'TITLE' && element.textContent !== element.dataset.uiText && element.textContent !== dictionary[element.dataset.uiText.trim()]) {
        element.removeAttribute('data-ui-text');
        return;
      }
      element.textContent = translate(element.dataset.uiText);
    });
    root.querySelectorAll('[data-ui-attrs]').forEach((element) => {
      const attributes = JSON.parse(element.dataset.uiAttrs);
      Object.entries(attributes).forEach(([name, source]) => element.setAttribute(name, translate(source)));
    });
    root.querySelectorAll('[data-ui-dynamic-attrs]').forEach((element) => {
      const attributes = JSON.parse(element.dataset.uiDynamicAttrs);
      Object.entries(attributes).forEach(([name, parts]) => {
        element.setAttribute(name, parts.map(([literal, value]) => literal ? translate(value) : value).join(''));
      });
    });
  }
  // Only called on authored HTML before its API/page scripts run, or on literal
  // template pieces. Substitutions are kept as opaque markers until afterwards.
  function markAuthored(root, markerPattern = null) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach((node) => {
      if (!chinese.test(node.data) || node.parentElement?.closest(skip)) return;
      const parent = node.parentElement;
      if (!parent) return;
      if (parent.matches('title, option')) {
        if (!markerPattern || !node.data.match(markerPattern)) {
          parent.dataset.uiText = node.data;
          parent.textContent = translate(node.data);
        }
        return;
      }
      const fragment = document.createDocumentFragment();
      const parts = markerPattern ? node.data.split(markerPattern) : [node.data];
      parts.forEach((part) => {
        if (chinese.test(part)) {
          const span = document.createElement('span');
          span.dataset.uiText = part;
          span.textContent = translate(part);
          fragment.append(span);
        } else fragment.append(document.createTextNode(part));
      });
      node.replaceWith(fragment);
    });
    root.querySelectorAll('*').forEach((element) => {
      if (element.closest('script, style, pre, code, svg, [contenteditable], [data-user-content]')) return;
      const attributes = {};
      ['aria-label', 'title', 'placeholder', 'alt'].forEach((name) => {
        const source = element.getAttribute(name);
        if (source && chinese.test(source) && (!markerPattern || !source.match(markerPattern))) {
          attributes[name] = source;
          element.setAttribute(name, translate(source));
        }
      });
      if (Object.keys(attributes).length) element.dataset.uiAttrs = JSON.stringify(attributes);
    });
  }
  function htmlTemplate(strings, ...values) {
    // A random marker prevents user-authored content from being confused with UI.
    const prefix = `NHUI${Math.random().toString(36).slice(2)}X`;
    const pattern = new RegExp(`(${prefix}\\d+END)`, 'g');
    let source = strings.reduce((result, part, index) => result + part + (index < values.length ? `${prefix}${index}END` : ''), '');
    const escape = (value) => value.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const decode = (value) => value.replace(/&(amp|lt|gt|quot|#39);/g, (_, entity) => ({ amp: '&', lt: '<', gt: '>', quot: '"', '#39': "'" }[entity]));
    source = source.replace(/<option([^>]*)>([^<]*)<\/option>/g, (markup, attrs, text) => chinese.test(text) && !text.includes(prefix) ? `<option${attrs} data-ui-text="${escape(text)}">${text}</option>` : markup);
    let position = 0;
    let plainTextElement = false;
    let result = '';
    function literalText(value) {
      return value.split(pattern).map((part) => {
        if (!chinese.test(part)) return part;
        if (plainTextElement) return translate(part);
        return `<span data-ui-text="${escape(part)}">${translate(part)}</span>`;
      }).join('');
    }
    // Keep tag spelling and attribute spreads intact. Parsing the template as
    // DOM here would normalize placeholder attributes and break event hooks.
    for (const match of source.matchAll(/<(?:"[^"]*"|'[^']*'|[^'">])*>/g)) {
      result += literalText(source.slice(position, match.index));
      const attributeSources = {};
      const dynamicAttributes = {};
      let tag = match[0].replace(/(aria-label|title|placeholder|alt)="([^"]*)"/g, (_, name, value) => {
        if (chinese.test(value) && !value.includes(prefix)) attributeSources[name] = value;
        if (chinese.test(value) && value.includes(prefix)) {
          dynamicAttributes[name] = value.split(pattern).map((part) => {
            const marker = part.match(new RegExp(`^${prefix}(\\d+)END$`));
            return marker ? [false, decode(String(values[Number(marker[1])] ?? ''))] : [true, decode(part)];
          });
        }
        return `${name}="${value.split(pattern).map(translate).join('')}"`;
      });
      if (Object.keys(attributeSources).length) tag = tag.replace(/\s*\/?>$/, (ending) => ` data-ui-attrs="${escape(JSON.stringify(attributeSources))}"${ending}`);
      if (Object.keys(dynamicAttributes).length) tag = tag.replace(/\s*\/?>$/, (ending) => ` data-ui-dynamic-attrs="${escape(JSON.stringify(dynamicAttributes))}"${ending}`);
      result += tag;
      if (/^<(option|title|textarea|script|style|pre|code)(?:\s|>)/i.test(match[0])) plainTextElement = true;
      if (/^<\/(option|title|textarea|script|style|pre|code)>/i.test(match[0])) plainTextElement = false;
      position = match.index + match[0].length;
    }
    result += literalText(source.slice(position));
    return result.replace(new RegExp(`${prefix}(\\d+)END`, 'g'), (_, index) => String(values[Number(index)] ?? ''));
  }
  function setText(element, render) {
    if (!element) return;
    const value = String(render() ?? '');
    liveText.set(element, { render, value });
    element.textContent = value;
  }
  function setLanguage(next) {
    language = next === 'en' ? 'en' : 'zh';
    storage.set('nethub-language', language);
    document.documentElement.lang = language === 'en' ? 'en' : 'zh-CN';
    updateMarked();
    liveText.forEach((entry, element) => {
      if (!element.isConnected || element.textContent !== entry.value) { liveText.delete(element); return; }
      entry.value = String(entry.render() ?? '');
      element.textContent = entry.value;
    });
    document.querySelectorAll('[data-language-toggle]').forEach((button) => {
      button.textContent = language === 'en' ? '中文' : 'EN';
      button.setAttribute('aria-label', language === 'en' ? '切换到中文' : 'Switch to English');
    });
    applyTheme();
    global.dispatchEvent(new CustomEvent('nethub-language-change', { detail: { language } }));
  }
  function initialize() {
    const title = document.querySelector('title');
    if (title) { title.dataset.uiText = title.textContent; title.textContent = translate(title.textContent); }
    markAuthored(document.body);
    const navbar = document.querySelector('.navbar');
    if (navbar) {
      const controls = document.createElement('div');
      controls.className = 'site-preferences';
      controls.innerHTML = '<button type="button" data-language-toggle>EN</button><button type="button" data-theme-toggle></button>';
      navbar.append(controls);
      controls.querySelector('[data-language-toggle]').addEventListener('click', () => setLanguage(language === 'en' ? 'zh' : 'en'));
      controls.querySelector('[data-theme-toggle]').addEventListener('click', () => {
        theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
        storage.set('nethub-theme', theme);
        applyTheme();
      });
    }
    setLanguage(language);
  }
  document.documentElement.lang = language === 'en' ? 'en' : 'zh-CN';
  applyTheme();
  darkMedia?.addEventListener?.('change', applyTheme);
  global.addEventListener('storage', (event) => {
    if (event.key === 'nethub-language') setLanguage(event.newValue);
    if (event.key === 'nethub-theme') { theme = ['light', 'dark'].includes(event.newValue) ? event.newValue : 'system'; applyTheme(); }
  });
  global.NetHubI18n = Object.freeze({ translate, html: htmlTemplate, text: textTemplate, setText, setLanguage, initialize, get language() { return language; } });
  global.ui = htmlTemplate;
  global.tr = translate;
  global.ut = textTemplate;
  global.setUiText = setText;
})(window);
