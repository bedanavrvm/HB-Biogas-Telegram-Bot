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
    if (utils && utils.fetchJson) return utils.fetchJson(`/api/complaints/${path}`, options);
    const response = await fetch(`/api/complaints/${path}`, options);
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
    if (utils && utils.fetchJson) return utils.fetchJson(`/api/complaints/${path}`, options);
    const response = await fetch(`/api/complaints/${path}`, options);
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

  async function postFragment(path, payload, initData, utils) {
    if (utils && utils.fetchHtml && utils.formBody) {
      return utils.fetchHtml(path, {
        method: 'POST',
        headers: Object.assign(
          { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
          utils.initDataHeader ? utils.initDataHeader(initData || '') : { 'X-Telegram-Init-Data': initData || '' }
        ),
        body: utils.formBody(payload || {}),
      });
    }
    const response = await fetch(path, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
        'X-Telegram-Init-Data': initData || '',
      },
      body: new URLSearchParams(payload || {}).toString(),
    });
    const html = await response.text();
    if (!response.ok) throw new Error(html || 'Could not load cases.');
    return html;
  }

  window.ComplaintCasesMiniAppApi = {
    postJson,
    postForm,
    postFragment,
  };
})();
