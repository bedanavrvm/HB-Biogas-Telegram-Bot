(function () {
  'use strict';

  async function parseJson(response) {
    const raw = await response.json().catch(() => ({}));
    const data = window.MiniAppUtils?.normalizeResponsePayload
      ? window.MiniAppUtils.normalizeResponsePayload(response, raw) : raw;
    return { ok: response.ok, status: response.status, data };
  }

  async function postForm(path, formData, options) {
    return parseJson(await fetch(path, {
      method: 'POST',
      headers: window.MiniAppUtils?.messageHeaders?.() || { 'X-MiniApp-Message-Contract': '2' },
      body: formData,
      signal: options && options.signal,
    }));
  }

  window.OrderApprovalMiniAppApi = {
    postForm,
  };
})();
