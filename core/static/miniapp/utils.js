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

  function parseDisplayDate(value) {
    if (!value) return null;
    const text = String(value).trim();
    const iso = text.match(/^(\d{4})-(\d{2})-(\d{2})(.*)$/);
    if (iso) {
      const date = new Date(Number(iso[1]), Number(iso[2]) - 1, Number(iso[3]));
      return Number.isNaN(date.getTime()) ? null : date;
    }
    const date = new Date(text);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function formatDate(value) {
    const date = parseDisplayDate(value);
    if (!date) return value ? String(value) : '-';
    const day = String(date.getDate()).padStart(2, '0');
    const month = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'][date.getMonth()];
    return day + '-' + month + '-' + date.getFullYear();
  }

  function formatDateTime(value) {
    const date = parseDisplayDate(value);
    if (!date) return value ? String(value) : '-';
    const time = String(value).match(/(?:T|\s)(\d{1,2}):(\d{2})/);
    return formatDate(value) + (time ? ' ' + String(time[1]).padStart(2, '0') + ':' + time[2] : '');
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
    formatDate: formatDate,
    formatDateTime: formatDateTime,
    formBody: formBody,
    initDataHeader: initDataHeader,
    initTelegram: initTelegram,
    setButtonLoading: setButtonLoading,
    showToast: showToast,
  };
})();
