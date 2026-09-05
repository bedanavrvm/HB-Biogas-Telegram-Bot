(function () {
  'use strict';

  const MESSAGE_CONTRACT_VERSION = '2';
  const handledMessageCodes = Object.freeze(['origination_shared_signer_phone']);
  const closeProtectionReasons = new Set();
  let telegramInstance = null;
  let telegramInitialized = false;
  let closingConfirmationEnabled = null;
  let writeProtectionInstalled = false;

  function miniAppColorScheme(tg) {
    const telegramScheme = String(tg && tg.colorScheme || '').toLowerCase();
    if (telegramScheme === 'dark' || telegramScheme === 'light') return telegramScheme;
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
      ? 'dark'
      : 'light';
  }

  function applyMiniAppTheme(tg) {
    const colorScheme = miniAppColorScheme(tg);
    if (typeof document === 'undefined' || !document.documentElement) return colorScheme;
    const root = document.documentElement;
    root.dataset.miniappColorScheme = colorScheme;
    root.style.colorScheme = colorScheme;
    const theme = tg && tg.themeParams || {};
    const background = String(theme.bg_color || '').trim();
    const bottomBar = String(theme.bottom_bar_bg_color || theme.secondary_bg_color || background).trim();
    try {
      if (background && typeof tg.setHeaderColor === 'function') tg.setHeaderColor(background);
    } catch (error) {}
    try {
      if (background && typeof tg.setBackgroundColor === 'function') tg.setBackgroundColor(background);
    } catch (error) {}
    try {
      if (bottomBar && typeof tg.setBottomBarColor === 'function') tg.setBottomBarColor(bottomBar);
    } catch (error) {}
    return colorScheme;
  }

  function bindMiniAppTheme(tg, onChange) {
    const refresh = function () {
      const colorScheme = applyMiniAppTheme(tg);
      if (typeof onChange === 'function') onChange(colorScheme);
      return colorScheme;
    };
    if (tg && typeof tg.onEvent === 'function') tg.onEvent('themeChanged', refresh);
    if (window.matchMedia) {
      const media = window.matchMedia('(prefers-color-scheme: dark)');
      if (typeof media.addEventListener === 'function') media.addEventListener('change', refresh);
      else if (typeof media.addListener === 'function') media.addListener(refresh);
    }
    return { colorScheme: refresh(), refresh: refresh };
  }

  function telegramWebApp() {
    return window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  }

  function syncClosingConfirmation() {
    const tg = telegramInstance || telegramWebApp();
    if (!tg) return false;
    const shouldEnable = closeProtectionReasons.size > 0;
    if (closingConfirmationEnabled === shouldEnable) return shouldEnable;
    const method = shouldEnable ? 'enableClosingConfirmation' : 'disableClosingConfirmation';
    if (typeof tg[method] === 'function') {
      tg[method]();
      closingConfirmationEnabled = shouldEnable;
    }
    return shouldEnable;
  }

  function setCloseProtection(reason, active) {
    const key = String(reason || '').trim();
    if (!key) throw new Error('Close protection requires a stable reason.');
    if (active) closeProtectionReasons.add(key);
    else closeProtectionReasons.delete(key);
    return syncClosingConfirmation();
  }

  function clearCloseProtection() {
    closeProtectionReasons.clear();
    return syncClosingConfirmation();
  }

  function protectWhile(reason, operation) {
    setCloseProtection(reason, true);
    let result;
    try {
      result = typeof operation === 'function' ? operation() : operation;
    } catch (error) {
      setCloseProtection(reason, false);
      throw error;
    }
    return Promise.resolve(result).finally(function () {
      setCloseProtection(reason, false);
    });
  }

  function installWriteProtection() {
    if (writeProtectionInstalled || typeof window.fetch !== 'function') return;
    const originalFetch = window.fetch;
    window.fetch = function () {
      const args = arguments;
      const input = args[0];
      const options = args[1] || {};
      const method = String(options.method || (input && input.method) || 'GET').toUpperCase();
      const url = String((input && input.url) || input || '');
      if (method === 'GET' || method === 'HEAD' || url.indexOf('/miniapp-diagnostics/') >= 0) {
        return originalFetch.apply(this, args);
      }
      const reason = 'network-write:' + createRequestId('write');
      setCloseProtection(reason, true);
      try {
        return Promise.resolve(originalFetch.apply(this, args)).finally(function () {
          setCloseProtection(reason, false);
        });
      } catch (error) {
        setCloseProtection(reason, false);
        throw error;
      }
    };
    writeProtectionInstalled = true;
  }

  function formSignature(form) {
    if (!form || typeof window.FormData !== 'function') return '';
    const entries = [];
    new FormData(form).forEach(function (value, key) {
      const normalized = value && typeof value === 'object' && 'name' in value
        ? [value.name, value.size, value.type]
        : String(value);
      entries.push([key, normalized]);
    });
    return JSON.stringify(entries);
  }

  function bindFormCloseProtection(form, reason) {
    if (!form) return { markClean: function () {}, markDirty: function () {}, isDirty: function () { return false; } };
    let baseline = formSignature(form);
    function sync() {
      setCloseProtection(reason, formSignature(form) !== baseline);
    }
    function markClean() {
      baseline = formSignature(form);
      setCloseProtection(reason, false);
    }
    function markDirty() {
      setCloseProtection(reason, true);
    }
    function isDirty() {
      return formSignature(form) !== baseline;
    }
    form.addEventListener('input', sync);
    form.addEventListener('change', sync);
    form.addEventListener('reset', function () { window.setTimeout(markClean, 0); });
    return { markClean: markClean, markDirty: markDirty, isDirty: isDirty };
  }

  function initTelegram(options) {
    const tg = telegramWebApp();
    if (!tg) return null;
    telegramInstance = tg;
    if (!telegramInitialized) {
      tg.ready();
      tg.expand();
      if (typeof tg.disableVerticalSwipes === 'function') tg.disableVerticalSwipes();
      installWriteProtection();
      telegramInitialized = true;
      window.MiniAppDiagnostics?.record?.('client_capability', {
        action: 'gesture_policy',
        statusBucket: typeof tg.disableVerticalSwipes === 'function' ? 'ok' : 'unknown',
      });
    }
    if (options && options.closingConfirmation === true) {
      closeProtectionReasons.add('legacy-initialization');
    } else if (options && options.closingConfirmation === false) {
      closeProtectionReasons.delete('legacy-initialization');
    }
    syncClosingConfirmation();
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
    return { 'X-Request-ID': key, 'Idempotency-Key': key, 'X-MiniApp-Message-Contract': MESSAGE_CONTRACT_VERSION };
  }

  const idempotentActionsInFlight = new Map();

  function singleFlight(requestId, operation) {
    const key = String(requestId || '');
    if (key && idempotentActionsInFlight.has(key)) return idempotentActionsInFlight.get(key);
    const promise = Promise.resolve().then(operation);
    if (!key) return promise;
    idempotentActionsInFlight.set(key, promise);
    promise.finally(function () {
      if (idempotentActionsInFlight.get(key) === promise) idempotentActionsInFlight.delete(key);
    }).catch(function () {});
    return promise;
  }

  function setXhrIdempotencyHeaders(xhr, requestId) {
    const headers = idempotencyHeaders(requestId);
    xhr.setRequestHeader('X-Request-ID', headers['X-Request-ID']);
    xhr.setRequestHeader('Idempotency-Key', headers['Idempotency-Key']);
    xhr.setRequestHeader('X-MiniApp-Message-Contract', MESSAGE_CONTRACT_VERSION);
    return headers['X-Request-ID'];
  }

  function messageHeaders(headers) {
    return Object.assign({}, headers || {}, { 'X-MiniApp-Message-Contract': MESSAGE_CONTRACT_VERSION });
  }

  function fallbackMessage(status) {
    if (status === 401) return 'Your Telegram session has expired. Close and reopen the Mini App, then try again.';
    if (status === 403) return 'You do not have access to this action. Contact a JBL administrator if you think this is a mistake.';
    if (status === 404) return 'This item is no longer available. Return to the list and refresh it.';
    if (status === 409) return 'This information was updated elsewhere. Reload the latest version before continuing.';
    if (status === 429) return 'There have been too many attempts. Please wait a short while and try again.';
    if (status >= 500) return 'We cannot complete this right now. Please try again shortly.';
    return 'We could not complete that action. Check the information and try again.';
  }

  function normalizeResponsePayload(response, payload, fallback) {
    const data = payload && typeof payload === 'object' ? payload : {};
    const currentContract = response && response.headers
      ? response.headers.get('X-MiniApp-Message-Contract') === MESSAGE_CONTRACT_VERSION : false;
    const requestId = data.request_id || (response && response.headers ? response.headers.get('X-Request-ID') : '') || '';
    const failed = !response || !response.ok || data.ok === false || data.success === false;
    const suppliedPresentation = data.presentation && typeof data.presentation === 'object'
      ? data.presentation : {};
    data.presentation = {
      tone: suppliedPresentation.tone || (failed ? (response?.status === 409 || response?.status === 429 ? 'warning' : 'error') : 'success'),
      persistence: suppliedPresentation.persistence || (failed ? 'until_resolved' : 'transient'),
      surface_hint: suppliedPresentation.surface_hint || (failed ? 'banner' : 'toast'),
    };
    if (failed) {
      // Raw legacy `error` text is accepted only from a pre-contract server.
      // Current servers must provide reviewed `message` copy.
      const message = data.message || (!currentContract ? data.error : '') || fallback || fallbackMessage(response ? response.status : 0);
      data.message = message;
      // Local compatibility for existing screen code. Version-2 servers do
      // not need to transmit the deprecated mirror to updated clients.
      data.error = message;
    }
    data.request_id = requestId;
    return data;
  }

  function apiError(response, payload, fallback) {
    const data = normalizeResponsePayload(response, payload, fallback);
    const error = new Error(data.message || fallbackMessage(response ? response.status : 0));
    error.code = data.code || '';
    error.status = response ? response.status : 0;
    error.details = data.details || {};
    error.presentation = data.presentation || {};
    error.requestId = data.request_id || '';
    error.payload = data;
    return error;
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
    const requestOptions = Object.assign({}, options || {});
    requestOptions.headers = messageHeaders(requestOptions.headers);
    const method = String(requestOptions.method || 'GET').toUpperCase();
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
      let bodyKey = '';
      if (typeof requestOptions.body === 'string') {
        try {
          const parsed = JSON.parse(requestOptions.body);
          if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
            bodyKey = parsed.client_request_id || parsed.request_id || '';
            const key = bodyKey || requestOptions.headers['Idempotency-Key'] || requestOptions.headers['X-Request-ID'] || createRequestId();
            if (!parsed.client_request_id) parsed.client_request_id = key;
            requestOptions.body = JSON.stringify(parsed);
            bodyKey = key;
          }
        } catch (_) { /* Non-JSON request bodies are still keyed by headers. */ }
      }
      const key = bodyKey || requestOptions.headers['Idempotency-Key'] || requestOptions.headers['X-Request-ID'] || createRequestId();
      Object.assign(requestOptions.headers, idempotencyHeaders(key));
    }
    const response = await fetch(url, requestOptions);
    const data = normalizeResponsePayload(response, await response.json().catch(function () { return {}; }));
    if (!response.ok || data.ok === false) {
      throw apiError(response, data);
    }
    return data;
  }

  async function fetchHtml(url, options) {
    const requestOptions = Object.assign({}, options || {});
    requestOptions.headers = Object.assign({}, requestOptions.headers || {});
    const method = String(requestOptions.method || 'GET').toUpperCase();
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
      const key = requestOptions.headers['Idempotency-Key'] || requestOptions.headers['X-Request-ID'] || createRequestId();
      Object.assign(requestOptions.headers, idempotencyHeaders(key));
    }
    const response = await fetch(url, requestOptions);
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

  function setButtonFeedback(button, state, label) {
    if (!button) return;
    const nextState = state || 'idle';
    if (nextState === 'loading') return setButtonLoading(button, true, label);
    if (nextState === 'success') {
      if (!button.dataset.originalHtml) button.dataset.originalHtml = button.innerHTML;
      button.disabled = true;
      button.removeAttribute('aria-busy');
      button.dataset.feedbackState = 'success';
      button.innerHTML = '<span aria-hidden="true">&#10003;</span><span>' + escapeHtml(label || 'Saved') + '</span>';
      haptic('success');
      return;
    }
    if (nextState === 'error') {
      button.removeAttribute('aria-busy');
      button.dataset.feedbackState = 'error';
      haptic('error');
      return;
    }
    delete button.dataset.feedbackState;
    setButtonLoading(button, false);
  }

  async function runButtonAction(button, action, options) {
    const settings = options || {};
    if (!button || button.disabled) return false;
    setButtonFeedback(button, 'loading', settings.loadingLabel || 'Working');
    try {
      const protectionReason = button._miniAppCloseProtectionReason
        || ('button-action:' + (button.id || createRequestId('button')));
      button._miniAppCloseProtectionReason = protectionReason;
      const result = await protectWhile(protectionReason, action);
      if (result === false) {
        setButtonFeedback(button, 'error');
        setButtonFeedback(button, 'idle');
        return false;
      }
      if (button.isConnected) {
        setButtonFeedback(button, 'success', settings.successLabel || 'Saved');
        await new Promise(function (resolve) { window.setTimeout(resolve, settings.successDuration || 800); });
      }
      return result;
    } catch (error) {
      setButtonFeedback(button, 'error');
      throw error;
    } finally {
      if (button.isConnected) setButtonFeedback(button, 'idle');
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
    if (!feedback) return false;
    try {
      if (kind === 'error' || kind === 'warning' || kind === 'success') {
        feedback.notificationOccurred(kind === 'warning' ? 'warning' : kind);
      } else {
        feedback.impactOccurred(kind || 'light');
      }
      return true;
    } catch (_) {
      // Haptics are an optional Telegram enhancement. Never affect the
      // completed server-side action if a client does not support them.
      return false;
    }
  }

  function impactWithFallback(kind, durationMs) {
    if (haptic(kind || 'medium')) return true;
    try {
      if (typeof window.navigator?.vibrate === 'function') {
        return Boolean(window.navigator.vibrate(Math.max(1, Number(durationMs || 35))));
      }
    } catch (_) {
      // Browser vibration is also best-effort. It must never interrupt the
      // action that requested physical feedback.
    }
    return false;
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
    const closeProtectionReason = 'server-draft:' + (workflow || 'unknown');

    function headers(method) {
      const result = { 'Content-Type': 'application/json', 'X-MiniApp-Message-Contract': MESSAGE_CONTRACT_VERSION };
      if (settings.initData) result['X-Telegram-Init-Data'] = settings.initData();
      if (settings.token) result['X-MiniApp-Context-Token'] = settings.token();
      // Portal applies the same retry-key policy to draft writes as it does to
      // workflow writes. A fresh key is correct here: draft revision locking,
      // rather than a workflow-side effect, is what makes repeated autosaves safe.
      if (!['GET', 'HEAD'].includes(String(method || 'GET').toUpperCase())) {
        const key = settings.requestId ? settings.requestId() : createRequestId('draft');
        Object.assign(result, idempotencyHeaders(key));
      }
      return result;
    }

    async function request(method, payload) {
      const response = await fetch(baseUrl, {
        method: method,
        headers: headers(method),
        body: payload === undefined ? undefined : JSON.stringify(payload),
        credentials: 'same-origin',
      });
      const data = normalizeResponsePayload(
        response,
        await response.json().catch(function () { return {}; }),
        'Draft could not be saved.',
      );
      if (!response.ok || data.ok === false) {
        const error = apiError(response, data, 'Draft could not be saved.');
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
        setCloseProtection(closeProtectionReason, false);
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
      setCloseProtection(closeProtectionReason, true);
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
      setCloseProtection(closeProtectionReason, false);
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

  // Apply Telegram's current palette before application bootstrap. Pages that
  // load this shared utility in <head> avoid a light flash in a dark Telegram
  // session; bindMiniAppTheme adds the live themeChanged subscription later.
  applyMiniAppTheme(telegramWebApp());

  window.MiniAppUtils = {
    apiError: apiError,
    escapeHtml: escapeHtml,
    fetchHtml: fetchHtml,
    fetchJson: fetchJson,
    formatDate: formatDate,
    formatDateTime: formatDateTime,
    formBody: formBody,
    initDataHeader: initDataHeader,
    initTelegram: initTelegram,
    setCloseProtection: setCloseProtection,
    clearCloseProtection: clearCloseProtection,
    protectWhile: protectWhile,
    bindFormCloseProtection: bindFormCloseProtection,
    bindMiniAppTheme: bindMiniAppTheme,
    haptic: haptic,
    impactWithFallback: impactWithFallback,
    skeletonCards: skeletonCards,
    createServerDraft: createServerDraft,
    createUiContext: createUiContext,
    renderSettingsAccount: renderSettingsAccount,
    createRequestId: createRequestId,
    ensureRequestId: ensureRequestId,
    idempotencyHeaders: idempotencyHeaders,
    setXhrIdempotencyHeaders: setXhrIdempotencyHeaders,
    singleFlight: singleFlight,
    handledMessageCodes: handledMessageCodes,
    messageHeaders: messageHeaders,
    normalizeResponsePayload: normalizeResponsePayload,
    runButtonAction: runButtonAction,
    setButtonFeedback: setButtonFeedback,
    setButtonLoading: setButtonLoading,
    showToast: showToast,
  };
})();
