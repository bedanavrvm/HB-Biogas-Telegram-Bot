(function () {
  'use strict';

  async function parseJson(response) {
    const raw = await response.json().catch(() => ({}));
    const data = window.MiniAppUtils?.normalizeResponsePayload
      ? window.MiniAppUtils.normalizeResponsePayload(response, raw) : raw;
    return { ok: response.ok, status: response.status, data };
  }

  async function getJson(url) {
    return parseJson(await fetch(url, { headers: window.MiniAppUtils?.messageHeaders?.() || {} }));
  }

  function requestId(payload) {
    const body = payload || {};
    const key = body.client_request_id || (window.MiniAppUtils && window.MiniAppUtils.ensureRequestId
      ? window.MiniAppUtils.ensureRequestId(body, 'spin')
      : `spin-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    if (!body.client_request_id) body.client_request_id = key;
    return key;
  }

  async function postJson(url, payload) {
    const body = payload || {};
    const key = requestId(body);
    const operation = () => fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Request-ID': key, 'Idempotency-Key': key, 'X-MiniApp-Message-Contract': '2' },
      body: JSON.stringify(body),
    });
    const response = await (window.MiniAppUtils?.singleFlight
      ? window.MiniAppUtils.singleFlight(key, operation) : operation());
    return parseJson(response);
  }

  async function postForm(url, formDataOrOptions) {
    if (formDataOrOptions instanceof FormData) {
      const formData = formDataOrOptions;
      const key = formData.get('client_request_id') || (window.MiniAppUtils && window.MiniAppUtils.createRequestId
        ? window.MiniAppUtils.createRequestId('spin') : `spin-${Date.now()}-${Math.random().toString(16).slice(2)}`);
      if (!formData.get('client_request_id')) formData.set('client_request_id', key);
      const operation = () => fetch(url, {
        method: 'POST',
        headers: { 'X-Request-ID': key, 'Idempotency-Key': key, 'X-MiniApp-Message-Contract': '2' },
        body: formData,
      });
      const response = await (window.MiniAppUtils?.singleFlight
        ? window.MiniAppUtils.singleFlight(key, operation) : operation());
      return parseJson(response);
    }
    return parseJson(await fetch(url, formDataOrOptions));
  }

  window.SpinMiniAppApi = {
    getJson,
    postJson,
    postForm,
  };
})();
