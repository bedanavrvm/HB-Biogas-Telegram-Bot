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

  function requestId(options) {
    const headers = options && options.headers ? options.headers : {};
    return headers['X-Request-ID'] || headers['x-request-id'] || options?.request_id || (
      window.crypto?.randomUUID ? window.crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`
    );
  }

  async function apiFetch(path, opts, tg) {
    const options = opts || {};
    const headers = {
      'Content-Type': 'application/json',
      ...initDataHeader(tg),
      ...(options.headers || {}),
    };
    headers['X-Request-ID'] = requestId(options);
    const requestOptions = { ...options, headers };
    if (!requestOptions.method || String(requestOptions.method).toUpperCase() === 'GET') {
      requestOptions.cache = 'no-store';
    }
    const response = await fetch(apiBase() + path, requestOptions);
    const data = await response.json().catch(function () { return {}; });
    return { ok: response.ok, status: response.status, data, requestId: response.headers.get('X-Request-ID') || headers['X-Request-ID'] };
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
      headers: { ...initDataHeader(tg), ...(extraHeaders || {}), 'X-Request-ID': requestId({headers: extraHeaders || {}}) },
      body: formData,
    });
    const data = await response.json().catch(function () { return {}; });
    return { ok: response.ok, status: response.status, data, requestId: response.headers.get('X-Request-ID') };
  }

  async function fetchHtml(path, opts, tg) {
    const options = opts || {};
    const url = path.startsWith('/api/') ? path : apiBase() + path;
    const headers = { ...initDataHeader(tg), ...(options.headers || {}) };
    headers['X-Request-ID'] = requestId(options);
    if (utils.fetchHtml) {
      return utils.fetchHtml(url, {
        ...options,
        headers,
      });
    }
    const response = await fetch(url, {
      ...options,
      cache: 'no-store',
      headers,
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
