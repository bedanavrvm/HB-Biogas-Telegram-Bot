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
    return headers['Idempotency-Key'] || headers['idempotency-key'] || headers['X-Request-ID'] || headers['x-request-id'] || options?.request_id || (
      window.crypto?.randomUUID ? window.crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`
    );
  }

  const pendingPublicationOperations = [];
  const publicationOperationIds = new Set();
  let publicationAttemptRunning = false;

  function publishEvent(detail) {
    window.dispatchEvent(new CustomEvent('portal:publication-updated', { detail }));
  }

  function schedulePublication(publication, tg) {
    const ids = Array.isArray(publication?.pending_operation_ids)
      ? publication.pending_operation_ids : [];
    ids.forEach(id => {
      const normalized = String(id || '').trim();
      if (normalized && !publicationOperationIds.has(normalized)) {
        publicationOperationIds.add(normalized);
        pendingPublicationOperations.push(normalized);
      }
    });
    if (!publicationAttemptRunning && pendingPublicationOperations.length) {
      window.setTimeout(() => drainPublicationQueue(tg), 0);
    }
  }

  async function drainPublicationQueue(tg) {
    if (publicationAttemptRunning) return;
    publicationAttemptRunning = true;
    try {
      while (pendingPublicationOperations.length) {
        const operationId = pendingPublicationOperations.shift();
        publicationOperationIds.delete(operationId);
        const key = requestId({});
        try {
          const response = await fetch(apiBase() + '/publication/attempt/', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              ...initDataHeader(tg),
              'X-Request-ID': key,
              'Idempotency-Key': key,
            },
            body: JSON.stringify({ operation_id: operationId, automatic: true, client_request_id: key }),
          });
          const data = await response.json().catch(() => ({}));
          publishEvent({ operationId, ok: response.ok && data.ok, publication: data.publication || null });
        } catch (_) {
          // The operation is durable and will be resumed after its persisted
          // retry time on a later relevant Mini App visit.
          publishEvent({ operationId, ok: false, publication: null });
        }
      }
    } finally {
      publicationAttemptRunning = false;
    }
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
    if (
      data?.ok && path !== '/publication/attempt/'
      && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(String(requestOptions.method || 'GET').toUpperCase())
    ) {
      if (data.publication) schedulePublication(data.publication, tg);
      (Array.isArray(data.publications) ? data.publications : []).forEach(item => schedulePublication(item, tg));
    }
    return { ok: response.ok, status: response.status, data, requestId: response.headers.get('X-Request-ID') || headers['X-Request-ID'] };
  }

  async function postJson(path, payload, tg, extraHeaders) {
    const body = payload || {};
    const key = body.client_request_id || body.request_id || requestId({ headers: extraHeaders || {} });
    if (!body.client_request_id) body.client_request_id = key;
    return apiFetch(path, {
      method: 'POST',
      headers: { ...(extraHeaders || {}), 'X-Request-ID': key, 'Idempotency-Key': key },
      body: JSON.stringify(body),
    }, tg);
  }

  async function postForm(path, formData, tg, extraHeaders) {
    const key = formData.get('client_request_id') || requestId({headers: extraHeaders || {}});
    if (!formData.get('client_request_id')) formData.set('client_request_id', key);
    const response = await fetch(apiBase() + path, {
      method: 'POST',
      headers: { ...initDataHeader(tg), ...(extraHeaders || {}), 'X-Request-ID': key, 'Idempotency-Key': key },
      body: formData,
    });
    const data = await response.json().catch(function () { return {}; });
    if (data?.ok) {
      if (data.publication) schedulePublication(data.publication, tg);
      (Array.isArray(data.publications) ? data.publications : []).forEach(item => schedulePublication(item, tg));
    }
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
    schedulePublication,
    postForm,
    postJson,
  };
})();
