(function () {
  'use strict';

  async function postJson(path, payload, initData, utils) {
    const body = payload || {};
    const requestId = utils && utils.ensureRequestId
      ? utils.ensureRequestId(body, 'complaint')
      : (body.client_request_id || `${Date.now()}-${Math.random().toString(16).slice(2)}`);
    const options = {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Telegram-Init-Data': initData || '',
        'X-Request-ID': requestId,
        'Idempotency-Key': requestId,
        'X-MiniApp-Message-Contract': '2',
      },
      body: JSON.stringify(body),
    };
    const operation = () => (utils && utils.fetchJson
      ? utils.fetchJson(`/api/complaints/${path}`, options)
      : fetch(`/api/complaints/${path}`, options));
    if (utils && utils.fetchJson) return utils.singleFlight
      ? utils.singleFlight(requestId, operation) : operation();
    const response = await (utils?.singleFlight ? utils.singleFlight(requestId, operation) : operation());
    const result = await response.json().catch(() => ({}));
    if (!response.ok || !result.ok) {
      const normalized = utils?.normalizeResponsePayload ? utils.normalizeResponsePayload(response, result) : result;
      const error = new Error(normalized.message || normalized.error || 'We could not complete that action.');
      error.status = response.status;
      error.payload = normalized;
      throw error;
    }
    return result;
  }

  async function postForm(path, formData, initData, groupId, utils) {
    formData.set('group_id', groupId || '');
    const requestId = formData.get('client_request_id') || (utils && utils.createRequestId
      ? utils.createRequestId('complaint') : `${Date.now()}-${Math.random().toString(16).slice(2)}`);
    if (!formData.get('client_request_id')) formData.set('client_request_id', requestId);
    const options = {
      method: 'POST',
      headers: {
        'X-Telegram-Init-Data': initData || '',
        'X-Request-ID': requestId,
        'Idempotency-Key': requestId,
        'X-MiniApp-Message-Contract': '2',
      },
      body: formData,
    };
    const operation = () => (utils && utils.fetchJson
      ? utils.fetchJson(`/api/complaints/${path}`, options)
      : fetch(`/api/complaints/${path}`, options));
    if (utils && utils.fetchJson) return utils.singleFlight
      ? utils.singleFlight(requestId, operation) : operation();
    const response = await (utils?.singleFlight ? utils.singleFlight(requestId, operation) : operation());
    const result = await response.json().catch(() => ({}));
    if (!response.ok || !result.ok) {
      const normalized = utils?.normalizeResponsePayload ? utils.normalizeResponsePayload(response, result) : result;
      const error = new Error(normalized.message || normalized.error || 'We could not complete that action.');
      error.status = response.status;
      error.payload = normalized;
      throw error;
    }
    return result;
  }

  async function getJson(path, params, initData, utils, requestSettings) {
    const query = new URLSearchParams();
    Object.entries(params || {}).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') query.set(key, String(value));
    });
    const options = {
      method: 'GET',
      headers: {
        'X-Telegram-Init-Data': initData || '',
        'X-MiniApp-Message-Contract': '2',
      },
    };
    if (requestSettings?.signal) options.signal = requestSettings.signal;
    const queryString = query.toString();
    const url = `/api/complaints/${path}${queryString ? `?${queryString}` : ''}`;
    if (utils && utils.fetchJson) return utils.fetchJson(url, options);
    const response = await fetch(url, options);
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      const normalized = utils?.normalizeResponsePayload ? utils.normalizeResponsePayload(response, result) : result;
      const error = new Error(normalized.message || normalized.error || 'The complaints report could not be loaded.');
      error.status = response.status;
      error.payload = normalized;
      throw error;
    }
    return result;
  }

  async function postBlob(path, payload, initData, utils) {
    const body = payload || {};
    const requestId = utils && utils.ensureRequestId
      ? utils.ensureRequestId(body, 'complaint-export')
      : (body.client_request_id || `${Date.now()}-${Math.random().toString(16).slice(2)}`);
    const response = await fetch(`/api/complaints/${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Telegram-Init-Data': initData || '',
        'X-Request-ID': requestId,
        'Idempotency-Key': requestId,
        'X-MiniApp-Message-Contract': '2',
      },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      const normalized = utils?.normalizeResponsePayload ? utils.normalizeResponsePayload(response, result) : result;
      const error = new Error(normalized.message || normalized.error || 'The export could not be downloaded.');
      error.status = response.status;
      error.payload = normalized;
      throw error;
    }
    const disposition = response.headers.get('Content-Disposition') || '';
    const match = disposition.match(/filename="?([^";]+)"?/i);
    return { blob: await response.blob(), filename: match ? match[1] : 'Complaint-Cases.xlsx' };
  }

  async function postFragment(path, payload, initData, utils) {
    const body = payload || {};
    const requestId = utils?.ensureRequestId
      ? utils.ensureRequestId(body, 'complaint-fragment')
      : (body.client_request_id || `${Date.now()}-${Math.random().toString(16).slice(2)}`);
    if (utils && utils.fetchHtml && utils.formBody) {
      return utils.fetchHtml(path, {
        method: 'POST',
        headers: Object.assign(
          { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
          utils.initDataHeader ? utils.initDataHeader(initData || '') : { 'X-Telegram-Init-Data': initData || '' },
          utils.idempotencyHeaders ? utils.idempotencyHeaders(requestId) : { 'X-Request-ID': requestId, 'Idempotency-Key': requestId }
        ),
        body: utils.formBody(body),
      });
    }
    const response = await fetch(path, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
        'X-Telegram-Init-Data': initData || '',
        'X-Request-ID': requestId,
        'Idempotency-Key': requestId,
      },
      body: new URLSearchParams(body).toString(),
    });
    const html = await response.text();
    if (!response.ok) throw new Error(html || 'Could not load cases.');
    return html;
  }

  window.ComplaintCasesMiniAppApi = {
    getJson,
    postJson,
    postForm,
    postBlob,
    postFragment,
  };
})();
