(function () {
  'use strict';

  async function parseJson(response) {
    const raw = await response.json().catch(() => ({}));
    const data = window.MiniAppUtils?.normalizeResponsePayload
      ? window.MiniAppUtils.normalizeResponsePayload(response, raw) : raw;
    return { ok: response.ok, status: response.status, data };
  }

  async function postForm(path, formData, options) {
    const key = formData.get('client_request_id') || window.MiniAppUtils?.createRequestId?.('order');
    if (!formData.get('client_request_id')) formData.set('client_request_id', key);
    const operation = () => fetch(path, {
      method: 'POST',
      headers: {
        ...(window.MiniAppUtils?.idempotencyHeaders?.(key) || { 'X-Request-ID': key, 'Idempotency-Key': key }),
        ...(window.MiniAppUtils?.messageHeaders?.() || { 'X-MiniApp-Message-Contract': '2' }),
      },
      body: formData,
      signal: options && options.signal,
    });
    const response = await (window.MiniAppUtils?.singleFlight
      ? window.MiniAppUtils.singleFlight(key, operation) : operation());
    return parseJson(response);
  }

  window.OrderApprovalMiniAppApi = {
    postForm,
  };
})();
