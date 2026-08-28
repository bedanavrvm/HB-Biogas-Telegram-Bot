(function () {
  'use strict';

  async function postJson(path, payload, utils) {
    const body = payload || {};
    const requestId = utils && utils.ensureRequestId
      ? utils.ensureRequestId(body, 'tat')
      : (body.client_request_id || body.request_id || `${Date.now()}-${Math.random().toString(16).slice(2)}`);
    if (!body.client_request_id) body.client_request_id = requestId;
    const headers = {
      'Content-Type': 'application/json',
      'X-Request-ID': requestId,
      'Idempotency-Key': requestId,
      'X-MiniApp-Message-Contract': '2',
    };
    if (utils && utils.fetchJson) {
      return utils.fetchJson(path, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
      });
    }
    const response = await fetch(path, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    });
    const raw = await response.json().catch(() => ({}));
    const data = utils?.normalizeResponsePayload ? utils.normalizeResponsePayload(response, raw) : raw;
    if (!response.ok || !data.ok) {
      const error = new Error(data.error || 'Request failed.');
      error.code = data.code || '';
      error.status = response.status;
      throw error;
    }
    return data;
  }

  async function postFragment(path, payload, utils) {
    if (utils && utils.fetchHtml && utils.formBody) {
      return utils.fetchHtml(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
        body: utils.formBody(payload),
      });
    }
    const response = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
      body: new URLSearchParams(payload).toString(),
    });
    const html = await response.text();
    if (!response.ok) throw new Error(html || 'Request failed.');
    return html;
  }

  window.TatMiniAppApi = {
    postJson,
    postFragment,
  };
})();
