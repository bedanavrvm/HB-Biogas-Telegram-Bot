(function () {
  'use strict';

  async function parseJson(response) {
    const data = await response.json().catch(() => ({}));
    return { ok: response.ok, status: response.status, data };
  }

  async function postForm(path, formData, options) {
    return parseJson(await fetch(path, {
      method: 'POST',
      body: formData,
      signal: options && options.signal,
    }));
  }

  window.OrderApprovalMiniAppApi = {
    postForm,
  };
})();
