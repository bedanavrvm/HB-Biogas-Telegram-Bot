(function () {
  'use strict';

  function responseError(response, result, utils, fallback) {
    const normalized = utils?.normalizeResponsePayload ? utils.normalizeResponsePayload(response, result, fallback) : result;
    const error = new Error(normalized.message || normalized.error || fallback || 'We could not complete that action.');
    error.code = normalized.code || '';
    error.status = response?.status || 0;
    error.details = normalized.details || {};
    error.presentation = normalized.presentation || {};
    error.requestId = normalized.request_id || response?.headers?.get('X-Request-ID') || '';
    error.payload = normalized;
    return error;
  }

  async function transportFetch(url, options, utils) {
    try {
      return await fetch(url, options);
    } catch (error) {
      if (error?.name === 'AbortError') throw error;
      if (utils?.clientRequestError) throw utils.clientRequestError(error?.name === 'TimeoutError' ? 'timeout' : 'network', options);
      const safe = new Error('The app could not reach JBL. Check your connection and try again.');
      safe.code = 'client_network_unavailable';
      safe.requestId = options?.headers?.['X-Request-ID'] || '';
      safe.presentation = { tone: 'error', persistence: 'until_resolved', surface_hint: 'banner' };
      throw safe;
    }
  }

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
      : transportFetch(`/api/complaints/${path}`, options, utils));
    if (utils && utils.fetchJson) return utils.singleFlight
      ? utils.singleFlight(requestId, operation) : operation();
    const response = await (utils?.singleFlight ? utils.singleFlight(requestId, operation) : operation());
    const result = await response.json().catch(() => ({}));
    if (!response.ok || !result.ok) {
      throw responseError(response, result, utils, 'We could not complete that action.');
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
      : transportFetch(`/api/complaints/${path}`, options, utils));
    if (utils && utils.fetchJson) return utils.singleFlight
      ? utils.singleFlight(requestId, operation) : operation();
    const response = await (utils?.singleFlight ? utils.singleFlight(requestId, operation) : operation());
    const result = await response.json().catch(() => ({}));
    if (!response.ok || !result.ok) {
      throw responseError(response, result, utils, 'We could not complete that action.');
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
        'X-Request-ID': requestSettings?.requestId || (utils?.createRequestId ? utils.createRequestId('complaint-read') : `${Date.now()}-${Math.random().toString(16).slice(2)}`),
      },
    };
    if (requestSettings?.signal) options.signal = requestSettings.signal;
    const queryString = query.toString();
    const url = `/api/complaints/${path}${queryString ? `?${queryString}` : ''}`;
    if (utils && utils.fetchJson) return utils.fetchJson(url, options);
    const response = await transportFetch(url, options, utils);
    let invalidJson = false;
    const result = await response.json().catch(() => { invalidJson = true; return {}; });
    if (response.ok && invalidJson) {
      if (utils?.clientRequestError) throw utils.clientRequestError('invalid_response', options);
      throw responseError(response, {}, utils, 'The server returned an unreadable response. Please try again.');
    }
    if (!response.ok) {
      throw responseError(response, result, utils, 'The complaints report could not be loaded.');
    }
    return result;
  }

  async function postBlob(path, payload, initData, utils) {
    const body = payload || {};
    const requestId = utils && utils.ensureRequestId
      ? utils.ensureRequestId(body, 'complaint-export')
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
    const response = await transportFetch(`/api/complaints/${path}`, options, utils);
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw responseError(response, result, utils, 'The export could not be downloaded.');
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
    const options = {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
        'X-Telegram-Init-Data': initData || '',
        'X-Request-ID': requestId,
        'Idempotency-Key': requestId,
      },
      body: new URLSearchParams(body).toString(),
    };
    const response = await transportFetch(path, options, utils);
    const html = await response.text();
    if (!response.ok) {
      let result = {};
      try { result = JSON.parse(html); } catch (_) { result = {}; }
      throw responseError(response, result, utils, 'Could not load cases.');
    }
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
