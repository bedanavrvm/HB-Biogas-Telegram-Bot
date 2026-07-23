(function () {
  'use strict';

  function initTelegram(options) {
    const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
    if (!tg) return null;
    tg.ready();
    tg.expand();
    if (!options || options.closingConfirmation !== false) {
      if (typeof tg.enableClosingConfirmation === 'function') tg.enableClosingConfirmation();
    }
    return tg;
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (character) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character];
    });
  }

  function initDataHeader(initData) {
    return initData ? { 'X-Telegram-Init-Data': initData } : {};
  }

  function formBody(payload) {
    return new URLSearchParams(payload || {}).toString();
  }

  async function fetchJson(url, options) {
    const response = await fetch(url, options || {});
    const data = await response.json().catch(function () { return {}; });
    if (!response.ok || data.ok === false) throw new Error(data.error || data.message || 'Request failed.');
    return data;
  }

  async function fetchHtml(url, options) {
    const response = await fetch(url, options || {});
    const html = await response.text();
    if (!response.ok) throw new Error(html || 'Request failed.');
    return html;
  }

  function setButtonLoading(button, loading, label) {
    if (!button) return;
    if (loading) {
      if (!button.dataset.originalHtml) button.dataset.originalHtml = button.innerHTML;
      button.disabled = true;
      button.setAttribute('aria-busy', 'true');
      button.innerHTML = '<span class="spinner-inline" aria-hidden="true"></span><span>' + escapeHtml(label || 'Working') + '</span>';
    } else {
      button.disabled = false;
      button.removeAttribute('aria-busy');
      if (button.dataset.originalHtml) {
        button.innerHTML = button.dataset.originalHtml;
        delete button.dataset.originalHtml;
      }
    }
  }

  function showToast(toast, message, options) {
    if (!toast) return;
    const settings = options || {};
    toast.textContent = message || '';
    toast.className = settings.className || ('toast visible' + (settings.error ? ' error' : ''));
    window.clearTimeout(toast._miniAppToastTimer);
    toast._miniAppToastTimer = window.setTimeout(function () {
      toast.className = settings.resetClassName || 'toast';
    }, settings.timeout || 5000);
  }

  window.MiniAppUtils = {
    escapeHtml: escapeHtml,
    fetchHtml: fetchHtml,
    fetchJson: fetchJson,
    formBody: formBody,
    initDataHeader: initDataHeader,
    initTelegram: initTelegram,
    setButtonLoading: setButtonLoading,
    showToast: showToast,
  };
})();
