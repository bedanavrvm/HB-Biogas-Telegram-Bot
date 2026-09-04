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
    const operation = () => {
      if (utils && utils.fetchJson) return utils.fetchJson(path, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
      });
      return fetch(path, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      });
    };
    if (utils && utils.fetchJson) return utils.singleFlight
      ? utils.singleFlight(requestId, operation) : operation();
    const response = await (utils?.singleFlight ? utils.singleFlight(requestId, operation) : operation());
    const raw = await response.json().catch(() => ({}));
    const data = utils?.normalizeResponsePayload ? utils.normalizeResponsePayload(response, raw) : raw;
    if (!response.ok || !data.ok) {
      const error = new Error(data.message || data.error || 'Request failed.');
      error.code = data.code || '';
      error.status = response.status;
      error.requestId = data.request_id || response.headers.get('X-Request-ID') || requestId;
      throw error;
    }
    return data;
  }

  async function postFragment(path, payload, utils) {
    const body = payload || {};
    const requestId = utils?.ensureRequestId
      ? utils.ensureRequestId(body, 'tat-fragment')
      : (body.client_request_id || body.request_id || `${Date.now()}-${Math.random().toString(16).slice(2)}`);
    const headers = {
      'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
      'X-Request-ID': requestId,
      'Idempotency-Key': requestId,
    };
    if (utils && utils.fetchHtml && utils.formBody) {
      return utils.fetchHtml(path, {
        method: 'POST',
        headers,
        body: utils.formBody(body),
      });
    }
    const response = await fetch(path, {
      method: 'POST',
      headers,
      body: new URLSearchParams(body).toString(),
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
