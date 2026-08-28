(function () {
  'use strict';

  const utils = window.MiniAppUtils || {};
  // A Portal queue must never leave a staff member staring at a permanent
  // loader when an Android WebView network request stalls.  This is deliberately
  // short enough to return a retry state, while still allowing ordinary mobile
  // requests to complete without treating them as failures.
  const REQUEST_TIMEOUT_MS = 20000;

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

  function requestFailureMessage(error) {
    if (error?.name === 'AbortError') {
      return 'The request took too long. Check your connection and try again.';
    }
    if (navigator.onLine === false) {
      return 'You appear to be offline. Reconnect, then try again.';
    }
    return 'Could not reach the Portal. Check your connection and try again.';
  }

  async function fetchWithTimeout(url, options) {
    const requestOptions = options || {};
    if (!window.AbortController) return fetch(url, requestOptions);

    const controller = new AbortController();
    const callerSignal = requestOptions.signal;
    const abortForCaller = function () { controller.abort(); };
    const timeout = window.setTimeout(function () { controller.abort(); }, REQUEST_TIMEOUT_MS);
    if (callerSignal) {
      if (callerSignal.aborted) controller.abort();
      else callerSignal.addEventListener('abort', abortForCaller, { once: true });
    }
    try {
      return await fetch(url, { ...requestOptions, signal: controller.signal });
    } finally {
      window.clearTimeout(timeout);
      if (callerSignal) callerSignal.removeEventListener('abort', abortForCaller);
    }
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
      'X-MiniApp-Message-Contract': '2',
      ...initDataHeader(tg),
      ...(options.headers || {}),
    };
    headers['X-Request-ID'] = requestId(options);
    const requestOptions = { ...options, headers };
    if (!requestOptions.method || String(requestOptions.method).toUpperCase() === 'GET') {
      requestOptions.cache = 'no-store';
    }
    try {
      const response = await fetchWithTimeout(apiBase() + path, requestOptions);
      const raw = await response.json().catch(function () { return {}; });
      const data = window.MiniAppUtils?.normalizeResponsePayload
        ? window.MiniAppUtils.normalizeResponsePayload(response, raw) : raw;
      if (
        data?.ok && path !== '/publication/attempt/'
        && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(String(requestOptions.method || 'GET').toUpperCase())
      ) {
        if (data.publication) schedulePublication(data.publication, tg);
        (Array.isArray(data.publications) ? data.publications : []).forEach(item => schedulePublication(item, tg));
      }
      return { ok: response.ok, status: response.status, data, requestId: response.headers.get('X-Request-ID') || headers['X-Request-ID'] };
    } catch (error) {
      return {
        ok: false,
        status: 0,
        data: { ok: false, error: requestFailureMessage(error) },
        requestId: headers['X-Request-ID'],
      };
    }
  }

  async function postJson(path, payload, tg, extraHeaders, requestOptions) {
    const body = payload || {};
    const key = body.client_request_id || body.request_id || requestId({ headers: extraHeaders || {} });
    if (!body.client_request_id) body.client_request_id = key;
    return apiFetch(path, {
      ...(requestOptions || {}),
      method: 'POST',
      headers: { ...(extraHeaders || {}), 'X-Request-ID': key, 'Idempotency-Key': key },
      body: JSON.stringify(body),
    }, tg);
  }

  async function postForm(path, formData, tg, extraHeaders) {
    const key = formData.get('client_request_id') || requestId({headers: extraHeaders || {}});
    if (!formData.get('client_request_id')) formData.set('client_request_id', key);
    const response = await fetchWithTimeout(apiBase() + path, {
      method: 'POST',
      headers: { ...initDataHeader(tg), ...(extraHeaders || {}), 'X-Request-ID': key, 'Idempotency-Key': key, 'X-MiniApp-Message-Contract': '2' },
      body: formData,
    });
    const raw = await response.json().catch(function () { return {}; });
    const data = window.MiniAppUtils?.normalizeResponsePayload
      ? window.MiniAppUtils.normalizeResponsePayload(response, raw) : raw;
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
    const response = await fetchWithTimeout(url, {
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
    fetchWithTimeout,
    schedulePublication,
    postForm,
    postJson,
  };
})();
