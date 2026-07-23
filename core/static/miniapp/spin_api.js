(function () {
  'use strict';

  async function parseJson(response) {
    const data = await response.json().catch(() => ({}));
    return { ok: response.ok, status: response.status, data };
  }

  async function getJson(url) {
    return parseJson(await fetch(url));
  }

  async function postJson(url, payload) {
    return parseJson(await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }));
  }

  async function postForm(url, formDataOrOptions) {
    if (formDataOrOptions instanceof FormData) {
      return parseJson(await fetch(url, { method: 'POST', body: formDataOrOptions }));
    }
    return parseJson(await fetch(url, formDataOrOptions));
  }

  window.SpinMiniAppApi = {
    getJson,
    postJson,
    postForm,
  };
})();
