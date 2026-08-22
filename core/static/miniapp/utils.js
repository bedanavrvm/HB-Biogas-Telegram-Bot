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

  function createRequestId(prefix) {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') return window.crypto.randomUUID();
    return String(prefix || 'miniapp') + '-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 12);
  }

  function ensureRequestId(payload, prefix) {
    const target = payload && typeof payload === 'object' ? payload : {};
    const existing = target.client_request_id || target.request_id || target.create_request_id;
    const key = existing || createRequestId(prefix);
    if (!target.client_request_id) target.client_request_id = key;
    return key;
  }

  function idempotencyHeaders(requestId) {
    const key = requestId || createRequestId();
    return { 'X-Request-ID': key, 'Idempotency-Key': key };
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
    if (!response.ok || data.ok === false) {
      const error = new Error(data.error || data.message || 'Request failed.');
      error.code = data.code || '';
      error.status = response.status;
      throw error;
    }
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
    if (settings.error || /(?:^|\s)(?:error|danger)-toast(?:\s|$)/.test(toast.className)) haptic('error');
    else if (/(?:^|\s)success(?:-toast)?(?:\s|$)/.test(toast.className)) haptic('success');
    window.clearTimeout(toast._miniAppToastTimer);
    toast._miniAppToastTimer = window.setTimeout(function () {
      toast.className = settings.resetClassName || 'toast';
    }, settings.timeout || 5000);
  }

  function haptic(kind) {
    const feedback = window.Telegram?.WebApp?.HapticFeedback;
    if (!feedback) return;
    try {
      if (kind === 'error' || kind === 'warning' || kind === 'success') {
        feedback.notificationOccurred(kind === 'warning' ? 'warning' : kind);
      } else {
        feedback.impactOccurred(kind || 'light');
      }
    } catch (_) {
      // Haptics are an optional Telegram enhancement. Never affect the
      // completed server-side action if a client does not support them.
    }
  }

  function skeletonCards(count) {
    return Array.from({ length: Math.max(1, count || 3) }, function () {
      return '<article class="mini-skeleton-card" aria-hidden="true"><span></span><span></span><span></span></article>';
    }).join('');
  }

  function createServerDraft(options) {
    const settings = options || {};
    const workflow = String(settings.workflow || '');
    const contextKey = String(settings.contextKey || '');
    const baseUrl = settings.baseUrl || (
      '/api/miniapp-drafts/' + encodeURIComponent(workflow) + '/' + encodeURIComponent(contextKey) + '/'
    );
    let revision = null;
    let timer = null;
    let savePromise = null;
    let pendingPayload = null;

    function headers() {
      const result = { 'Content-Type': 'application/json' };
      if (settings.initData) result['X-Telegram-Init-Data'] = settings.initData();
      if (settings.token) result['X-MiniApp-Context-Token'] = settings.token();
      // Portal applies the same retry-key policy to draft writes as it does to
      // workflow writes. A fresh key is correct here: draft revision locking,
      // rather than a workflow-side effect, is what makes repeated autosaves safe.
      if (settings.requestId) result['X-Request-ID'] = settings.requestId();
      return result;
    }

    async function request(method, payload) {
      const response = await fetch(baseUrl, {
        method: method,
        headers: headers(),
        body: payload === undefined ? undefined : JSON.stringify(payload),
        credentials: 'same-origin',
      });
      const data = await response.json().catch(function () { return {}; });
      if (!response.ok || data.ok === false) {
        const error = new Error(data.error || 'Draft could not be saved.');
        error.conflict = response.status === 409 || Boolean(data.conflict);
        throw error;
      }
      return data;
    }

    async function load() {
      const data = await request('GET');
      if (data.draft) revision = data.draft.revision;
      return data.draft || null;
    }

    async function save(payload) {
      // Keep the newest edit while a previous request is still in flight.
      // Dropping it here would make a fast typist lose their last change until
      // they touch the form again.
      pendingPayload = payload;
      if (savePromise) return savePromise;
      savePromise = (async function () {
        let savedDraft = null;
        while (pendingPayload !== null) {
          const nextPayload = pendingPayload;
          pendingPayload = null;
          const data = await request('POST', { payload: nextPayload, revision: revision });
          revision = data.draft.revision;
          savedDraft = data.draft;
          settings.onSaved?.(savedDraft);
        }
        return savedDraft;
      })()
        .catch(function (error) {
          settings.onError?.(error);
          throw error;
        })
        .finally(function () { savePromise = null; });
      return savePromise;
    }

    function schedule(payload, delay) {
      window.clearTimeout(timer);
      settings.onSaving?.();
      timer = window.setTimeout(function () {
        save(payload).catch(function () { /* surfaced by onError */ });
      }, delay == null ? 700 : delay);
    }

    async function clear() {
      window.clearTimeout(timer);
      pendingPayload = null;
      // Do not let an older autosave recreate a draft immediately after it
      // has been cleared following a successful submission.
      if (savePromise) {
        try { await savePromise; } catch (_) { /* deletion is still safe */ }
      }
      await request('DELETE');
      revision = null;
      settings.onCleared?.();
    }

    return { load: load, save: save, schedule: schedule, clear: clear };
  }

  function createUiContext(key) {
    const storageKey = `miniapp-ui:${String(key || '')}`;
    function read() {
      try {
        const value = JSON.parse(window.sessionStorage.getItem(storageKey) || '{}');
        return value && typeof value === 'object' ? value : {};
      } catch (_) { return {}; }
    }
    function write(value) {
      try { window.sessionStorage.setItem(storageKey, JSON.stringify(value || {})); } catch (_) {}
    }
    return { read: read, write: write };
  }

  function renderSettingsAccount(target, account) {
    if (!target) return;
    target.hidden = false;
    const data = account || {};
    target.replaceChildren();
    const heading = document.createElement('div');
    heading.className = 'miniapp-settings-account-heading';
    const title = document.createElement('strong');
    title.textContent = data.display_name || 'My account';
    const subtitle = document.createElement('span');
    subtitle.textContent = data.workflow_label || 'Mini App access';
    heading.append(title, subtitle);

    const facts = document.createElement('div');
    facts.className = 'miniapp-settings-account-facts';
    const entries = [];
    if (data.telegram_username) entries.push(['Telegram', '@' + String(data.telegram_username).replace(/^@/, '')]);
    else entries.push(['Telegram', data.telegram_linked ? 'Linked' : 'Link pending']);
    if (data.email) entries.push(['Email', data.email]);
    if (data.phone_number) entries.push(['Contact', data.phone_number]);
    if (Array.isArray(data.roles) && data.roles.length) entries.push(['Role', data.roles.map((role) => role.label || role.key).join(', ')]);
    if (Array.isArray(data.branches) && data.branches.length) entries.push(['Branch scope', data.branches.join(', ')]);
    if (Array.isArray(data.products) && data.products.length) entries.push(['Product scope', data.products.join(', ')]);
    entries.forEach(function (entry) {
      const row = document.createElement('div');
      const label = document.createElement('span');
      const value = document.createElement('strong');
      label.textContent = entry[0];
      value.textContent = entry[1];
      row.append(label, value);
      facts.appendChild(row);
    });
    const note = document.createElement('p');
    note.className = 'miniapp-settings-account-note';
    note.textContent = 'Account details and workflow access are managed by JBL administrators. Contact an administrator to correct them.';
    target.append(heading, facts, note);
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
    haptic: haptic,
    skeletonCards: skeletonCards,
    createServerDraft: createServerDraft,
    createUiContext: createUiContext,
    renderSettingsAccount: renderSettingsAccount,
    createRequestId: createRequestId,
    ensureRequestId: ensureRequestId,
    idempotencyHeaders: idempotencyHeaders,
    setButtonLoading: setButtonLoading,
    showToast: showToast,
  };
})();
