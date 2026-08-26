(function () {
  'use strict';

  const config = window.MINIAPP_DIAGNOSTICS_CONFIG || {};
  const noop = function () {};
  const fallbackClose = function () {
    try {
      const telegram = window.Telegram && window.Telegram.WebApp;
      if (telegram && typeof telegram.close === 'function') telegram.close();
    } catch (_) {}
  };
  const fallbackApi = { record: noop, recordRequest: noop, intentionalClose: fallbackClose, flush: noop };
  window.MiniAppDiagnostics = fallbackApi;
  if (config.enabled === false) return;

  try {
    const STORAGE_KEY = 'jbl-miniapp-diagnostics-v1';
    const MAX_SESSIONS = 3;
    const MAX_EVENTS = 30;
    const RETRY_DELAYS = [2000, 5000, 15000, 30000, 60000];
    const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
    const started = Date.now();
    let memoryStore = { sessions: [] };
    let flushTimer = null;
    let flushInFlight = false;
    let retryIndex = 0;
    let heartbeatTimer = null;

    function uuid() {
      try {
        if (window.crypto && typeof window.crypto.randomUUID === 'function') return window.crypto.randomUUID();
      } catch (_) {}
      return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (character) {
        const value = Math.random() * 16 | 0;
        return (character === 'x' ? value : (value & 0x3 | 0x8)).toString(16);
      });
    }

    function surfaceFromPath() {
      const path = String(window.location && window.location.pathname || '').toLowerCase();
      if (path.indexOf('/complaints') >= 0) return 'complaint_cases';
      if (path.indexOf('/tat-tracker') >= 0) return 'tat_tracker';
      if (path.indexOf('/spin') >= 0) return 'spin';
      if (path.indexOf('/origination') >= 0) return 'loan_origination';
      if (path.indexOf('/order-approval') >= 0) return 'order_approval';
      if (path.indexOf('/fca') >= 0) return 'fca_review';
      if (path.indexOf('/jawabu-farmers') >= 0) return 'jawabu_farmers';
      return 'portal';
    }

    function platformBucket() {
      const value = String(tg && tg.platform || '').toLowerCase();
      if (value === 'android' || value === 'android_x') return 'android';
      if (value === 'ios') return 'ios';
      if (['tdesktop', 'macos', 'weba', 'webk', 'web'].indexOf(value) >= 0) return 'desktop';
      return 'other';
    }

    function networkBucket() {
      try {
        if (navigator.onLine === false) return 'offline';
        const connection = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
        const type = String(connection && connection.type || '').toLowerCase();
        const effective = String(connection && connection.effectiveType || '').toLowerCase();
        if (effective === 'slow-2g' || effective === '2g') return 'slow';
        if (type === 'wifi' || type === 'ethernet') return 'wifi';
        if (type === 'cellular' || effective === '3g' || effective === '4g') return 'cellular';
      } catch (_) {}
      return 'unknown';
    }

    function memoryBucket() {
      try {
        const value = Number(navigator.deviceMemory || 0);
        if (!value) return 'unknown';
        if (value <= 2) return 'low';
        if (value <= 4) return 'medium';
        return 'high';
      } catch (_) {
        return 'unknown';
      }
    }

    function readStore() {
      try {
        const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '{}');
        if (parsed && Array.isArray(parsed.sessions)) return parsed;
      } catch (_) {}
      return memoryStore;
    }

    function writeStore(store) {
      try {
        memoryStore = store;
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
      } catch (_) {
        memoryStore = store;
      }
    }

    function trimStore(store, currentUuid) {
      store.sessions.forEach(function (session) {
        if (session.events.length > MAX_EVENTS) {
          session.dropped = Number(session.dropped || 0) + session.events.length - MAX_EVENTS;
          session.events = session.events.slice(-MAX_EVENTS);
        }
      });
      if (store.sessions.length > MAX_SESSIONS) {
        store.sessions = store.sessions
          .sort(function (left, right) {
            if (left.session_uuid === currentUuid) return 1;
            if (right.session_uuid === currentUuid) return -1;
            return Number(left.created_at || 0) - Number(right.created_at || 0);
          })
          .slice(-MAX_SESSIONS);
      }
    }

    const store = readStore();
    const priorSessions = store.sessions.slice();
    priorSessions.forEach(function (session) {
      if (!session.recovery_event_added) {
        const last = session.events[session.events.length - 1];
        const lastVisibility = String(session.last_visibility || (last && last.visibility) || 'visible');
        session.events.push({
          event_uuid: uuid(), event_type: 'recovery_complete', action: 'recovery',
          elapsed_ms: Number(last && last.elapsed_ms || 0),
          visibility: lastVisibility === 'hidden' ? 'hidden' : 'visible',
          online: navigator.onLine !== false, network_bucket: networkBucket(), status_bucket: '', request_id: ''
        });
        session.recovery_event_added = true;
      }
    });
    const current = {
      session_uuid: uuid(),
      surface: surfaceFromPath(),
      release: String(config.release || '').slice(0, 80),
      platform: platformBucket(),
      network_bucket: networkBucket(),
      device_memory_bucket: memoryBucket(),
      created_at: Date.now(),
      signal_token: '',
      server_started: false,
      recovery_event_added: false,
      last_visibility: document.visibilityState === 'hidden' ? 'hidden' : 'visible',
      events: [],
      dropped: 0
    };
    store.sessions.push(current);
    trimStore(store, current.session_uuid);
    writeStore(store);

    function findSession(sessionUuid) {
      return store.sessions.find(function (item) { return item.session_uuid === sessionUuid; });
    }

    function addEvent(eventType, options, sessionUuid) {
      try {
        const target = findSession(sessionUuid || current.session_uuid);
        if (!target) return null;
        const settings = options || {};
        const event = {
          event_uuid: uuid(),
          event_type: String(eventType || ''),
          elapsed_ms: Math.max(0, Date.now() - (target.created_at || started)),
          action: String(settings.action || ''),
          visibility: settings.visibility || (document.visibilityState === 'hidden' ? 'hidden' : 'visible'),
          online: navigator.onLine !== false,
          network_bucket: networkBucket(),
          status_bucket: String(settings.statusBucket || ''),
          request_id: String(settings.requestId || '').slice(0, 128)
        };
        target.events.push(event);
        target.last_visibility = event.visibility;
        trimStore(store, current.session_uuid);
        // Persist every milestone synchronously. No teardown callback is
        // required for recovery after an abrupt WebView process loss.
        writeStore(store);
        scheduleFlush(0);
        return event;
      } catch (_) {
        return null;
      }
    }

    function safeSentryInit() {
      try {
        if (!config.sentryDsn || !window.Sentry || typeof window.Sentry.init !== 'function') return;
        const integrations = function (defaults) {
          const safeDefaults = (defaults || []).filter(function (integration) {
            return integration && integration.name !== 'Breadcrumbs';
          });
          if (typeof window.Sentry.browserTracingIntegration === 'function') {
            safeDefaults.push(window.Sentry.browserTracingIntegration());
          }
          return safeDefaults;
        };
        window.Sentry.init({
          dsn: String(config.sentryDsn),
          environment: String(config.environment || 'production'),
          release: String(config.release || '') || undefined,
          sendDefaultPii: false,
          sampleRate: 1.0,
          replaysSessionSampleRate: 0,
          replaysOnErrorSampleRate: 0,
          integrations: integrations,
          tracesSampleRate: Math.max(0, Math.min(Number(config.tracesSampleRate || 0.05), 1)),
          tracePropagationTargets: [/^\//],
          beforeBreadcrumb: function () { return null; },
          beforeSend: function (event) {
            try {
              delete event.user; delete event.breadcrumbs; delete event.extra;
              delete event.request; delete event.message; delete event.contexts;
              if (event.exception && Array.isArray(event.exception.values)) {
                event.exception.values.forEach(function (value) { if (value) delete value.value; });
              }
              event.tags = {
                miniapp_session: current.session_uuid,
                miniapp_surface: current.surface,
                miniapp_platform: current.platform
              };
              return event;
            } catch (_) { return null; }
          },
          beforeSendTransaction: function (event) {
            try {
              event.transaction = current.surface;
              delete event.request; delete event.breadcrumbs; delete event.transaction_info;
              const trace = event.contexts && event.contexts.trace;
              event.contexts = trace ? { trace: {
                trace_id: trace.trace_id, span_id: trace.span_id,
                parent_span_id: trace.parent_span_id, op: trace.op, status: trace.status
              } } : {};
              event.tags = {
                miniapp_session: current.session_uuid,
                miniapp_surface: current.surface,
                miniapp_platform: current.platform
              };
              (event.spans || []).forEach(function (span) {
                delete span.description;
                const requestId = span.data && span.data['miniapp.request_id'];
                span.data = /^[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}$/.test(String(requestId || ''))
                  ? { 'miniapp.request_id': String(requestId) }
                  : {};
              });
              return event;
            } catch (_) { return null; }
          }
        });
      } catch (_) {}
    }

    function initHeaders() {
      const headers = { 'Content-Type': 'application/json' };
      try { if (tg && tg.initData) headers['X-Telegram-Init-Data'] = tg.initData; } catch (_) {}
      return headers;
    }

    async function ensureServerSession(session) {
      if (session.server_started && session.signal_token) return true;
      const response = await window.fetch('/api/miniapp-diagnostics/sessions/start/', {
        method: 'POST', credentials: 'same-origin', headers: initHeaders(),
        body: JSON.stringify({
          session_uuid: session.session_uuid, surface: session.surface, release: session.release,
          platform: session.platform, network_bucket: session.network_bucket,
          device_memory_bucket: session.device_memory_bucket
        })
      });
      const data = await response.json().catch(function () { return {}; });
      if (response.status === 409 || response.status === 403) {
        // A shared phone may now belong to another actor. Never retry or leak a
        // prior staff member's pending diagnostic session under the new actor.
        session.discard = true;
        return false;
      }
      if (!response.ok || data.ok === false) throw new Error('diagnostic_start_failed');
      session.server_started = true;
      session.signal_token = String(data.signal_token || '');
      writeStore(store);
      return true;
    }

    async function uploadEvents(session) {
      while (session.events.length) {
        const batch = session.events.slice(0, 20);
        const response = await window.fetch(
          '/api/miniapp-diagnostics/sessions/' + encodeURIComponent(session.session_uuid) + '/signals/',
          {
            method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ signal_token: session.signal_token, events: batch })
          }
        );
        const data = await response.json().catch(function () { return {}; });
        if (!response.ok || data.ok === false) throw new Error('diagnostic_signal_failed');
        const acknowledged = new Set(Array.isArray(data.acknowledged) ? data.acknowledged : []);
        if (!acknowledged.size) throw new Error('diagnostic_ack_missing');
        session.events = session.events.filter(function (event) { return !acknowledged.has(event.event_uuid); });
        writeStore(store);
      }
    }

    async function flushAll() {
      if (flushInFlight || navigator.onLine === false) return;
      flushInFlight = true;
      try {
        const sessions = store.sessions.slice();
        for (const session of sessions) {
          if (!(await ensureServerSession(session))) continue;
          await uploadEvents(session);
          if (session.session_uuid !== current.session_uuid && !session.events.length) session.discard = true;
        }
        store.sessions = store.sessions.filter(function (session) { return !session.discard; });
        retryIndex = 0;
        writeStore(store);
      } catch (_) {
        const delay = RETRY_DELAYS[Math.min(retryIndex, RETRY_DELAYS.length - 1)];
        retryIndex += 1;
        scheduleFlush(delay);
      } finally {
        flushInFlight = false;
      }
    }

    function scheduleFlush(delay) {
      try {
        window.clearTimeout(flushTimer);
        flushTimer = window.setTimeout(function () { flushAll().catch(noop); }, Number(delay || 0));
      } catch (_) {}
    }

    function sendCloseBeacon(event) {
      try {
        if (!current.signal_token) return false;
        const url = '/api/miniapp-diagnostics/sessions/' + encodeURIComponent(current.session_uuid) + '/signals/';
        const payload = JSON.stringify({ signal_token: current.signal_token, events: [event] });
        const body = new Blob([payload], {
          type: 'application/json'
        });
        if (navigator.sendBeacon && navigator.sendBeacon(url, body)) return true;
        window.fetch(url, {
          method: 'POST', credentials: 'same-origin', keepalive: true,
          headers: { 'Content-Type': 'application/json' }, body: payload
        }).catch(noop);
        return true;
      } catch (_) {
        return false;
      }
    }

    function recordRequest(requestId, statusBucket) {
      addEvent('api_request', {
        action: 'api_request', requestId: requestId, statusBucket: statusBucket || ''
      });
    }

    function intentionalClose(reason) {
      try {
        const allowed = ['submit_success', 'completed_batch', 'empty_queue', 'user_back', 'native_close'];
        const action = allowed.indexOf(String(reason || '')) >= 0 ? String(reason) : 'unknown';
        const event = addEvent('intentional_close', { action: action });
        if (event) sendCloseBeacon(event);
        const close = function () { try { if (tg && typeof tg.close === 'function') tg.close(); } catch (_) {} };
        try {
          if (window.Sentry && typeof window.Sentry.flush === 'function') {
            Promise.race([
              window.Sentry.flush(250),
              new Promise(function (resolve) { window.setTimeout(resolve, 250); })
            ]).then(close).catch(close);
            return;
          }
        } catch (_) {}
        window.setTimeout(close, 0);
      } catch (_) {
        try { if (tg && typeof tg.close === 'function') tg.close(); } catch (_ignored) {}
      }
    }

    function requestIdFromHeaders(input, options) {
      try {
        const headers = new Headers((options && options.headers) || (input && input.headers) || {});
        return String(headers.get('X-Request-ID') || headers.get('Idempotency-Key') || '');
      } catch (_) { return ''; }
    }

    function instrumentFetch() {
      try {
        const originalFetch = window.fetch.bind(window);
        window.fetch = function (input, options) {
          const url = String((input && input.url) || input || '');
          const requestId = requestIdFromHeaders(input, options);
          const isDiagnostic = url.indexOf('/miniapp-diagnostics/') >= 0;
          if (requestId && !isDiagnostic) recordRequest(requestId, '');
          const performFetch = function () { return originalFetch(input, options); };
          let diagnosticSpan = null;
          try {
            diagnosticSpan = requestId && !isDiagnostic && window.Sentry && typeof window.Sentry.startInactiveSpan === 'function'
              ? window.Sentry.startInactiveSpan({
                  name: 'business_api', op: 'http.client',
                  attributes: { 'miniapp.request_id': requestId }
                })
              : null;
          } catch (_) {}
          const requestPromise = performFetch();
          return requestPromise.then(function (response) {
            try { if (diagnosticSpan) diagnosticSpan.end(); } catch (_) {}
            if (requestId && !isDiagnostic) {
              recordRequest(requestId, response.ok ? 'ok' : (response.status >= 500 ? 'server_error' : 'client_error'));
            }
            return response;
          }, function (error) {
            try { if (diagnosticSpan) diagnosticSpan.end(); } catch (_) {}
            if (requestId && !isDiagnostic) recordRequest(requestId, navigator.onLine === false ? 'offline' : 'unknown');
            throw error;
          });
        };
      } catch (_) {}
    }

    function instrumentXhr() {
      try {
        const originalOpen = XMLHttpRequest.prototype.open;
        const originalSetHeader = XMLHttpRequest.prototype.setRequestHeader;
        const originalSend = XMLHttpRequest.prototype.send;
        XMLHttpRequest.prototype.open = function (method, url) {
          this.__miniappDiagnosticUrl = String(url || '');
          return originalOpen.apply(this, arguments);
        };
        XMLHttpRequest.prototype.setRequestHeader = function (name, value) {
          if (String(name).toLowerCase() === 'x-request-id' || String(name).toLowerCase() === 'idempotency-key') {
            this.__miniappDiagnosticRequestId = String(value || '');
          }
          return originalSetHeader.apply(this, arguments);
        };
        XMLHttpRequest.prototype.send = function () {
          const xhr = this;
          const requestId = xhr.__miniappDiagnosticRequestId;
          if (requestId && String(xhr.__miniappDiagnosticUrl || '').indexOf('/miniapp-diagnostics/') < 0) {
            recordRequest(requestId, '');
            xhr.addEventListener('loadend', function () {
              const status = Number(xhr.status || 0);
              recordRequest(requestId, status >= 200 && status < 400 ? 'ok' : (status >= 500 ? 'server_error' : (status ? 'client_error' : 'unknown')));
            }, { once: true });
          }
          return originalSend.apply(this, arguments);
        };
      } catch (_) {}
    }

    safeSentryInit();
    instrumentFetch();
    instrumentXhr();
    window.MiniAppDiagnostics = {
      record: function (eventType, options) { addEvent(eventType, options || {}); },
      recordRequest: recordRequest,
      intentionalClose: intentionalClose,
      flush: function () { scheduleFlush(0); }
    };

    addEvent('session_started', { action: 'boot' });
    window.addEventListener('error', function () { addEvent('client_error', { statusBucket: 'client_error' }); });
    window.addEventListener('unhandledrejection', function () { addEvent('client_error', { statusBucket: 'client_error' }); });
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'hidden') {
        addEvent('backgrounded', { action: 'visibility_change', visibility: 'hidden' });
        window.clearInterval(heartbeatTimer);
      } else {
        addEvent('resumed', { action: 'visibility_change', visibility: 'visible' });
        startHeartbeat();
      }
    });
    window.addEventListener('pagehide', function () {
      addEvent('page_hidden', { action: 'page_lifecycle', visibility: 'hidden' });
    });
    window.addEventListener('pageshow', function (event) {
      if (event && event.persisted) addEvent('page_restored', { action: 'page_lifecycle', visibility: 'visible' });
    });
    window.addEventListener('online', function () { scheduleFlush(0); });

    function startHeartbeat() {
      try {
        window.clearInterval(heartbeatTimer);
        if (document.visibilityState === 'hidden') return;
        const seconds = Math.max(15, Number(config.heartbeatSeconds || 60));
        heartbeatTimer = window.setInterval(function () {
          if (document.visibilityState !== 'hidden') addEvent('heartbeat', { action: 'periodic' });
        }, seconds * 1000);
      } catch (_) {}
    }
    startHeartbeat();
    scheduleFlush(0);
  } catch (_) {
    // Diagnostics must remain a no-op when storage, browser APIs, SDK setup,
    // or our own implementation fails. Host workflow exceptions are never
    // caused or propagated by this client.
    window.MiniAppDiagnostics = fallbackApi;
  }
})();
