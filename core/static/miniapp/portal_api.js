(function () {
  'use strict';

  const utils = window.MiniAppUtils || {};

  function apiBase() {
    return '/api/portal';
  }

  function initDataHeader(tg) {
    const raw = tg && tg.initData ? tg.initData : '';
    return utils.initDataHeader ? utils.initDataHeader(raw) : (raw ? { 'X-Telegram-Init-Data': raw } : {});
  }

  async function apiFetch(path, opts, tg) {
    const options = opts || {};
    const headers = {
      'Content-Type': 'application/json',
      ...initDataHeader(tg),
      ...(options.headers || {}),
    };
    const response = await fetch(apiBase() + path, { ...options, headers });
    const data = await response.json().catch(function () { return {}; });
    return { ok: response.ok, status: response.status, data };
  }

  async function postJson(path, payload, tg, extraHeaders) {
    return apiFetch(path, {
      method: 'POST',
      headers: extraHeaders || {},
      body: JSON.stringify(payload || {}),
    }, tg);
  }

  async function postForm(path, formData, tg, extraHeaders) {
    const response = await fetch(apiBase() + path, {
      method: 'POST',
      headers: { ...initDataHeader(tg), ...(extraHeaders || {}) },
      body: formData,
    });
    const data = await response.json().catch(function () { return {}; });
    return { ok: response.ok, status: response.status, data };
  }

  async function fetchHtml(path, opts, tg) {
    const options = opts || {};
    const url = path.startsWith('/api/') ? path : apiBase() + path;
    if (utils.fetchHtml) {
      return utils.fetchHtml(url, {
        ...options,
        headers: { ...initDataHeader(tg), ...(options.headers || {}) },
      });
    }
    const response = await fetch(url, {
      ...options,
      headers: { ...initDataHeader(tg), ...(options.headers || {}) },
    });
    const html = await response.text();
    if (!response.ok) throw new Error(html || 'Request failed.');
    return html;
  }

  window.PortalMiniAppApi = {
    apiBase,
    apiFetch,
    fetchHtml,
    initDataHeader,
    postForm,
    postJson,
  };
})();
