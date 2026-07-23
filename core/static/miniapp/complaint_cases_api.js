(function () {
  'use strict';

  async function postJson(path, payload, initData, utils) {
    const options = {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Telegram-Init-Data': initData || '',
      },
      body: JSON.stringify(payload || {}),
    };
    if (utils && utils.fetchJson) return utils.fetchJson(`/api/complaints/${path}`, options);
    const response = await fetch(`/api/complaints/${path}`, options);
    const result = await response.json().catch(() => ({}));
    if (!response.ok || !result.ok) throw new Error(result.error || 'Request failed.');
    return result;
  }

  async function postForm(path, formData, initData, groupId, utils) {
    formData.set('group_id', groupId || '');
    const options = {
      method: 'POST',
      headers: { 'X-Telegram-Init-Data': initData || '' },
      body: formData,
    };
    if (utils && utils.fetchJson) return utils.fetchJson(`/api/complaints/${path}`, options);
    const response = await fetch(`/api/complaints/${path}`, options);
    const result = await response.json().catch(() => ({}));
    if (!response.ok || !result.ok) throw new Error(result.error || 'Request failed.');
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
