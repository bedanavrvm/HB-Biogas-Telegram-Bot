(function () {
  'use strict';

  const tg = window.MiniAppUtils?.initTelegram?.() || window.Telegram?.WebApp;
  window.MiniAppUtils?.installAccessibleForms?.();
  let originationGroupId = new URLSearchParams(window.location.search).get('group_id') || '';
  let originationGroups = [];
  const LEGACY_SECTIONS = [
    { key: 'applicant', label: 'Applicant', hint: 'Identity, contacts and residence' },
    { key: 'business', label: 'Business', hint: 'Enterprise and household finances' },
    { key: 'loan', label: 'Loan', hint: 'Product, purpose and repayment' },
    { key: 'security', label: 'Security', hint: 'Assets pledged for the facility' },
    { key: 'guarantors', label: 'Guarantors', hint: 'Guarantor and relationship details' },
  ];
  const FULL_WIDTH = new Set([
    'applicant_residence_address', 'employer_business_address', 'loan_purpose',
    'security_1_description', 'guarantor_1_business_location', 'guarantor_1_residence_location',
  ]);
  let products = [];
  let allProducts = [];
  let branches = [];
  let locationCatalog = {};
  let applications = [];
  let tabCounts = {};
  let applicationsLabel = 'Applications';
  let statusOptions = [];
  let filterProducts = [];
  let reviewerAlerts = [];
  let listTotal = 0;
  let listScrollY = 0;
  let listRequestGeneration = 0;
  let listSearchTimer = null;
  let commercialQuoteTimer = null;
  let commercialQuoteGeneration = 0;
  let commercialQuoteState = null;
  let capabilities = { can_create: false, can_review: false, can_start_signing: false, can_staff_sign: false };
  let listState = { queue: '', status: '', productKey: '', query: '', page: 1, pages: 1 };
  let current = null;
  let step = 0;
  let saveTimer = null;
  let previewUrl = '';
  let evidencePreviewUrl = '';
  let previewReturnFocus = null;
  let previewPage = 1;
  let previewZoom = 100;
  let previewPageCount = 1;
  let previewRequestId = '';
  let previewDocumentKey = '';
  let previewAllowIncomplete = false;
  let previewedRevision = null;
  let previewSucceeded = false;
  let previewPacketVersion = '';
  let approvalReview = null;
  let signingRefreshTimer = null;
  let signingRefreshGeneration = 0;
  let dirty = false;
  let editGeneration = 0;
  let saveInFlight = null;
  let draftSaveOperation = null;
  let saveInFlightRequestId = '';
  let lastFailedSaveRequestId = '';
  let pendingSaveRequestId = '';
  let syncConflict = false;
  let conflictDraft = null;
  let conflictServerLoaded = false;
  let serverValidationErrorsVisible = false;
  let conflictRefreshInFlight = null;
  let recoveryAvailable = Boolean(window.crypto?.subtle && window.indexedDB);
  const recoveredApplications = new Set();
  const reviewTargets = new Map();
  const completedDraftSections = new Set();
  const unlockedDraftSections = new Set();
  let draftSectionApplicationId = '';
  let reviewDialogMode = '';
  let reviewReturnFocus = null;
  let pendingAuditedReasonAction = null;
  let sheetMode = '';
  let sheetReturnFocus = null;
  let testSignatureStrokes = [];
  let testSignatureActiveStroke = null;
  let testSignatureResizeObserver = null;
  let activeCameraStream = null;
  let cameraDialog = null;
  let sheetCleanup = null;
  let mainActionController = null;
  let lastActivatedButton = null;
  let primaryBusy = false;
  let createInFlight = false;
  let copyDownloadInFlight = false;
  let previewGestures = null;
  let keyboardFocusTimer = null;

  function syncCloseProtection() {
    window.MiniAppUtils?.setCloseProtection?.(
      'origination-unsaved',
      Boolean(dirty || syncConflict),
    );
    window.MiniAppUtils?.setCloseProtection?.(
      'origination-operation',
      Boolean(primaryBusy || createInFlight || saveInFlight),
    );
  }
  let maximumLiveViewportHeight = Math.max(
    Number(window.visualViewport?.height) || 0,
    Number(window.innerHeight) || 0,
    Number(tg?.viewportStableHeight) || 0,
  );
  let keyboardViewportOpen = false;
  let telegramMainSuppressed = false;
  let nativeMainButtonVisible = false;
  const previewPageUrls = new Map();
  const previewPageLoads = new Map();
  const volatileStorage = new Map();

  function storageGet(key) {
    try {
      const value = window.localStorage?.getItem(key);
      return value === null || value === undefined ? (volatileStorage.get(key) ?? null) : value;
    } catch (_) {
      return volatileStorage.get(key) ?? null;
    }
  }

  function storageSet(key, value) {
    volatileStorage.set(key, String(value));
    try { window.localStorage?.setItem(key, String(value)); } catch (_) { /* Memory fallback keeps this session idempotent. */ }
  }

  function storageRemove(key) {
    volatileStorage.delete(key);
    try { window.localStorage?.removeItem(key); } catch (_) { /* Restricted WebViews may deny storage. */ }
  }

  function requestKey(prefix) {
    return `${prefix}-${window.crypto?.randomUUID ? window.crypto.randomUUID() : Date.now()}`;
  }

  function newRowId() {
    if (window.crypto?.randomUUID) return window.crypto.randomUUID();
    const bytes = new Uint8Array(16);
    if (window.crypto?.getRandomValues) window.crypto.getRandomValues(bytes);
    else for (let index = 0; index < bytes.length; index += 1) bytes[index] = Math.floor(Math.random() * 256);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = [...bytes].map(value => value.toString(16).padStart(2, '0')).join('');
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }

  function formatKenyanDate(value) {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ''));
    return match ? `${match[3]}-${match[2]}-${match[1].slice(-2)}` : '';
  }

  function formatWholeKes(value) {
    const amount = Number(String(value ?? '').replaceAll(',', ''));
    return Number.isFinite(amount)
      ? amount.toLocaleString('en-KE', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
      : String(value ?? '');
  }

  function normalizeNumericText(value) {
    return String(value ?? '')
      .trim()
      .replace(/^KES\s*/i, '')
      .replace(/[,\s\u00a0\u202f]/g, '');
  }

  function nativeDateControl(attributes, value, disabled, rules = '') {
    const display = formatKenyanDate(value) || 'dd-mm-yy';
    return `<span class="native-date-control${disabled ? ' is-disabled' : ''}"><span class="native-date-display${value ? '' : ' is-placeholder'}" aria-hidden="true">${escapeHtml(display)}${iconSvg('calendar')}</span><input type="date" lang="en-KE" ${attributes} value="${escapeHtml(value || '')}"${rules}${disabled ? ' disabled' : ''} aria-label="Choose date; displayed as day-month-year"></span>`;
  }

  function syncNativeDateDisplays(scope = document) {
    scope.querySelectorAll?.('.native-date-control input[type="date"]').forEach(input => {
      const display = input.closest('.native-date-control')?.querySelector('.native-date-display');
      if (!display) return;
      display.textContent = formatKenyanDate(input.value) || 'dd-mm-yy';
      display.classList.toggle('is-placeholder', !input.value);
    });
  }

  function repeatableGridStyle(field) {
    const configured = field?.repeatable_layout?.column_widths;
    const widths = Array.isArray(configured)
      ? configured.map(Number).filter(value => Number.isFinite(value) && value > 0)
      : [];
    const total = widths.reduce((sum, value) => sum + value, 0);
    const safe = widths.length && Math.abs(total - 100) <= 0.1 ? widths : [50, 50];
    return `grid-template-columns:${safe.map(value => `minmax(0, ${value}fr)`).join(' ')}`;
  }

  async function apiFetch(path, options) {
    const requestOptions = { ...(options || {}) };
    requestOptions.headers = { ...(requestOptions.headers || {}) };
    const method = String(requestOptions.method || 'GET').toUpperCase();
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
      let body = null;
      if (typeof requestOptions.body === 'string') {
        try { body = JSON.parse(requestOptions.body); } catch (_) { /* Non-JSON writes are header-keyed. */ }
      }
      const key = body?.client_request_id
        || requestOptions.headers['Idempotency-Key']
        || requestOptions.headers['X-Request-ID']
        || requestKey('write');
      if (body && typeof body === 'object' && !Array.isArray(body) && !body.client_request_id) {
        body.client_request_id = key;
        requestOptions.body = JSON.stringify(body);
      }
      requestOptions.headers['Idempotency-Key'] = key;
      requestOptions.headers['X-Request-ID'] = key;
    }
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(`/api/origination/api${path}`, {
        ...requestOptions,
        cache: requestOptions.method ? requestOptions.cache : 'no-store',
        signal: controller.signal,
        headers: {
          'Content-Type': 'application/json',
          'X-MiniApp-Message-Contract': '2',
          ...(originationGroupId ? { 'X-Origination-Group': originationGroupId } : {}),
          ...(tg?.initData ? { 'X-Telegram-Init-Data': tg.initData } : {}),
          ...(requestOptions.headers || {}),
        },
      });
      const contentType = String(response.headers.get('Content-Type') || '');
      if (contentType.startsWith('application/pdf') || contentType.startsWith('image/')) return {
        ok: response.ok,
        status: response.status,
        blob: await response.blob(),
        pageCount: Number(response.headers.get('X-Preview-Page-Count') || 1),
        packetVersion: response.headers.get('X-Signing-Packet-Version') || '',
        previewComplete: response.headers.get('X-Preview-Complete') !== 'false',
      };
      const raw = await response.json().catch(() => ({}));
      const data = window.MiniAppUtils?.normalizeResponsePayload
        ? window.MiniAppUtils.normalizeResponsePayload(response, raw) : raw;
      return { ok: response.ok, status: response.status, data };
    } catch (error) {
      return { ok: false, status: 0, data: { error: error?.name === 'AbortError' ? 'The request timed out. Try again.' : 'Could not connect. Check your signal and try again.' } };
    } finally {
      window.clearTimeout(timeout);
    }
  }

  function postJson(path, payload) {
    const body = { ...(payload || {}) };
    const key = body.client_request_id || requestKey('write');
    body.client_request_id = key;
    return apiFetch(path, { method: 'POST', headers: { 'Idempotency-Key': key, 'X-Request-ID': key }, body: JSON.stringify(body) });
  }

  function openAppStatus() {
    document.getElementById('origination-settings').showModal();
    syncTelegramControls();
    window.MiniAppRecovery?.mount(document.getElementById('origination-recovery'), {
      prefix: '/api/origination/api/',
      load: async page => { const result = await apiFetch(`/settings/recovery/?page=${page}`); if (!result.ok) throw new Error(result.data?.error || 'App status could not be loaded.'); return result.data; },
      request: (endpoint, payload) => postJson(endpoint.slice('/api/origination/api'.length), payload),
      notify: showToast,
    });
  }
  document.getElementById('origination-settings-open')?.addEventListener('click', openAppStatus);
  document.addEventListener('click', event => { if (event.target.closest('[data-open-app-status]')) openAppStatus(); });
  document.getElementById('origination-settings-close')?.addEventListener('click', () => document.getElementById('origination-settings').close());
  document.getElementById('origination-settings')?.addEventListener('close', syncTelegramControls);
  window.addEventListener('miniapp:recovery-dialog-change', syncTelegramControls);

  function escapeHtml(value) {
    const node = document.createElement('div');
    node.textContent = String(value ?? '');
    return node.innerHTML.replaceAll('"', '&quot;').replaceAll("'", '&#39;');
  }

  function root() { return document.getElementById('origination-root'); }
  function draftKey(id) { return `loan-origination-draft:${id}`; }
  function normalizeLabel(field) { return field.label || field.key.replaceAll('_', ' '); }

  function applicationStatusLabel(application) {
    if (application?.status === 'completed') return 'Completed';
    if (application.signing_workspace) return application.signing_workspace.status_label;
    if (application.status_label) return application.status_label;
    if ((application.approval_roles || []).length) return application.status_text || 'Awaiting signatures';
    if (application?.status === 'ready_for_review') {
      return application.review_packet_ready ? 'Final review' : 'Prepare documents';
    }
    if (application?.status === 'signed_pending_approval') return 'Signed - pending JBL approval';
    if (application?.status === 'approved') return 'Approved and locked';
    return String(application?.status || '').replaceAll('_', ' ');
  }

  function iconSvg(name, className = '') {
    const paths = {
      arrowLeft: '<path d="m15 18-6-6 6-6"/>',
      arrowRight: '<path d="m9 18 6-6-6-6"/>',
      chevronDown: '<path d="m6 9 6 6 6-6"/>',
      calendar: '<path d="M7 3v3M17 3v3M4 9h16M5 5h14a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Z"/>',
      close: '<path d="m6 6 12 12M18 6 6 18"/>',
      filter: '<path d="M4 5h16M7 12h10M10 19h4"/>',
      plus: '<path d="M12 5v14M5 12h14"/>',
      refresh: '<path d="M20 11a8 8 0 1 0-2.34 5.66M20 4v7h-7"/>',
      check: '<path d="m5 12 4 4L19 6"/>',
      review: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12M14 2v6h6L14 2Z"/><circle cx="15" cy="15" r="4"/><path d="m18 18 3 3"/>',
      document: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Zm0 0v6h6M8 13h8M8 17h6"/>',
      documents: '<path d="M15 3H8a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Zm0 0v5h5M3 7v13a2 2 0 0 0 2 2h10"/>',
      copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V4H4v12h4"/>',
      phone: '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7l.5 2.8a2 2 0 0 1-.6 1.7L7.7 9.5a16 16 0 0 0 6.8 6.8l1.3-1.3a2 2 0 0 1 1.7-.6l2.8.5a2 2 0 0 1 1.7 2Z"/>',
      camera: '<path d="M14.5 4h-5L7 7H3v13h18V7h-4Z"/><circle cx="12" cy="13" r="4"/>',
      download: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
      undo: '<path d="M3 7v6h6M3 13l4-4a7 7 0 1 1 1 10"/>',
    };
    return `<svg class="${escapeHtml(className)}" aria-hidden="true" viewBox="0 0 24 24">${paths[name] || ''}</svg>`;
  }

  function syncTelegramTheme() {
    const params = tg?.themeParams || {};
    Object.entries(params).forEach(([key, value]) => {
      document.documentElement.style.setProperty(`--tg-theme-${key.replaceAll('_', '-')}`, value);
    });
    const scheme = String(tg?.colorScheme || '').toLowerCase();
    if (scheme === 'dark' || scheme === 'light') document.documentElement.dataset.telegramTheme = scheme;
  }

  function syncViewport() {
    const browserHeight = Number(window.visualViewport?.height) || Number(window.innerHeight) || 640;
    const telegramHeight = Number(tg?.viewportHeight) || browserHeight;
    const visualHeight = Math.min(browserHeight, telegramHeight);
    const stableHeight = Number(tg?.viewportStableHeight) || Number(window.innerHeight) || visualHeight;
    maximumLiveViewportHeight = Math.max(maximumLiveViewportHeight, stableHeight, visualHeight);
    document.documentElement.style.setProperty('--origination-viewport-height', `${Math.round(stableHeight)}px`);
    document.documentElement.style.setProperty('--origination-live-height', `${Math.round(visualHeight)}px`);
    const keyboardOpen = isKeyboardInput(document.activeElement) && visualHeight < maximumLiveViewportHeight - 80;
    setKeyboardViewportOpen(keyboardOpen);
    if (document.body.classList.contains('origination-input-active')) scheduleFocusedInputVisibility();
  }

  function setKeyboardViewportOpen(open) {
    keyboardViewportOpen = Boolean(open);
    document.body.classList.toggle('origination-keyboard-open', keyboardViewportOpen);
    if (keyboardViewportOpen && nativeMainButtonVisible && !telegramMainSuppressed) {
      telegramMainSuppressed = true;
      clearMainButtonHandler();
      document.body.classList.remove('telegram-main-button-active');
      try { tg?.MainButton?.hideProgress?.(); tg?.MainButton?.hide?.(); } catch (_) { /* Telegram owns this surface. */ }
      nativeMainButtonVisible = false;
    } else if (!keyboardViewportOpen && telegramMainSuppressed) {
      telegramMainSuppressed = false;
      syncPrimaryAction();
    }
  }

  function isKeyboardInput(element) {
    if (!element || element.disabled || element.readOnly) return false;
    if (element.matches('textarea')) return true;
    return element.matches('input:not([type]), input[type="text"], input[type="tel"], input[type="email"], input[type="password"], input[type="search"], input[type="url"], input[type="number"]');
  }

  function keepFocusedInputVisible() {
    const input = document.activeElement;
    if (!isKeyboardInput(input)) return;
    const liveHeight = Number(window.visualViewport?.height) || Number(window.innerHeight) || 640;
    const headerBottom = document.querySelector('.origination-header')?.getBoundingClientRect().bottom || 0;
    const rect = input.getBoundingClientRect();
    // Telegram owns its native MainButton. Do not mutate it during a focus
    // transition; reserve its footprint and move the field above it instead.
    const telegramButtonReserve = keyboardViewportOpen ? 0 : (tg?.MainButton ? 64 : 0);
    const lowerLimit = liveHeight - telegramButtonReserve - 14;
    const upperLimit = Math.max(10, headerBottom + 8);
    try {
      if (rect.bottom > lowerLimit) window.scrollBy({ top: rect.bottom - lowerLimit + 10, behavior: 'smooth' });
      else if (rect.top < upperLimit) window.scrollBy({ top: rect.top - upperLimit - 8, behavior: 'smooth' });
    } catch (_) { /* Older Telegram WebViews may reject ScrollToOptions. */ }
  }

  function scheduleFocusedInputVisibility() {
    window.clearTimeout(keyboardFocusTimer);
    keyboardFocusTimer = window.setTimeout(keepFocusedInputVisible, 180);
  }

  function clearMainButtonHandler() {
    mainActionController?.dispose(); mainActionController = null;
  }

  function hideMainButton() {
    clearMainButtonHandler();
    document.body.classList.remove('telegram-main-button-active');
    try { tg?.MainButton?.hideProgress?.(); tg?.MainButton?.hide?.(); } catch (_) { /* Keep the form usable. */ }
    nativeMainButtonVisible = false;
  }

  function syncPrimaryAction() {
    if (!mainActionController) mainActionController = window.MiniAppUtils?.bindMainAction?.({telegram:tg,
      busy:() => primaryBusy, resolve:() => {
        const blocked = keyboardViewportOpen
          || document.querySelector('dialog[open]')
          || !document.getElementById('document-preview-overlay')?.hidden
          || !document.getElementById('origination-review-overlay')?.hidden
          || (sheetMode && sheetMode !== 'create');
        return blocked ? null : [...document.querySelectorAll('[data-primary-action]')]
          .find(item => !item.closest('[hidden]') && item.getClientRects().length) || null;
      }});
    mainActionController?.sync();
    nativeMainButtonVisible = Boolean(document.querySelector('.miniapp-native-action'));
  }

  function setPrimaryBusy(busy, label = '') {
    primaryBusy = Boolean(busy);
    syncCloseProtection();
    document.querySelectorAll('[data-primary-action]').forEach(action => { action.disabled = primaryBusy; });
    if (tg?.MainButton) {
      try {
        if (label) tg.MainButton.setText?.(label);
        if (primaryBusy) {
          tg.MainButton.disable?.();
          tg.MainButton.showProgress?.(false);
        } else {
          tg.MainButton.hideProgress?.();
        }
      } catch (_) { /* Fall back to the in-DOM primary action. */ }
    }
    if (!busy) syncPrimaryAction();
  }

  async function runPrimaryAction(label, action, button = null, successLabel = 'Saved') {
    if (primaryBusy) return false;
    button = button || document.activeElement?.closest?.('button')
      || (lastActivatedButton?.isConnected ? lastActivatedButton : null);
    setPrimaryBusy(true, label);
    window.MiniAppUtils?.setButtonFeedback?.(button, 'loading', label);
    try {
      const result = await action();
      if (result === false) return false;
      if (button?.isConnected) {
        window.MiniAppUtils?.setButtonFeedback?.(button, 'success', successLabel);
        await new Promise(resolve => window.setTimeout(resolve, 800));
      }
      return result;
    } finally {
      if (button?.isConnected) window.MiniAppUtils?.setButtonFeedback?.(button, 'idle');
      setPrimaryBusy(false);
    }
  }

  function syncTelegramControls() {
    if (tg?.BackButton) {
      const previewOpen = !document.getElementById('document-preview-overlay')?.hidden;
      try {
        if (cameraDialog || sheetMode || reviewDialogMode || previewOpen || current || document.querySelector('.recovery-dialog[open]')) tg.BackButton.show?.();
        else tg.BackButton.hide?.();
      } catch (_) { /* The in-DOM navigation remains usable if Telegram's bridge fails. */ }
    }
    syncPrimaryAction();
  }

  function focusableElements(container) {
    return [...container.querySelectorAll('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])')]
      .filter(item => !item.hidden && item.getClientRects().length > 0);
  }

  function trapModalFocus(event, container) {
    if (event.key !== 'Tab') return;
    const items = focusableElements(container);
    if (!items.length) return event.preventDefault();
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first.focus();
    }
  }

  function isoDate(date) {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  }

  const RECOVERY_DB = 'jbl-origination-recovery-v1';
  const RECOVERY_TTL_MS = 24 * 60 * 60 * 1000;
  const recoveryUser = String(tg?.initDataUnsafe?.user?.id || 'local-session');

  function recoveryDb() {
    if (!recoveryAvailable) return Promise.resolve(null);
    if (recoveryDb.promise) return recoveryDb.promise;
    recoveryDb.promise = new Promise((resolve, reject) => {
      const request = indexedDB.open(RECOVERY_DB, 1);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains('meta')) db.createObjectStore('meta');
        if (!db.objectStoreNames.contains('drafts')) db.createObjectStore('drafts');
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    }).catch(() => { recoveryAvailable = false; return null; });
    return recoveryDb.promise;
  }

  function idbRequest(request) {
    return new Promise((resolve, reject) => {
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  async function recoveryKey(db) {
    let transaction = db.transaction('meta', 'readonly');
    let key = await idbRequest(transaction.objectStore('meta').get('aes-key'));
    if (!key) {
      key = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
      transaction = db.transaction('meta', 'readwrite');
      await idbRequest(transaction.objectStore('meta').put(key, 'aes-key'));
    }
    return key;
  }

  async function persistRecoveryDraft(applicationId, value) {
    if (!recoveryAvailable) return false;
    try {
      const db = await recoveryDb();
      if (!db) return false;
      const key = await recoveryKey(db);
      const iv = crypto.getRandomValues(new Uint8Array(12));
      const plaintext = new TextEncoder().encode(JSON.stringify(value));
      const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, plaintext);
      const transaction = db.transaction('drafts', 'readwrite');
      await idbRequest(transaction.objectStore('drafts').put({
        user: recoveryUser,
        expiresAt: Date.now() + RECOVERY_TTL_MS,
        iv: Array.from(iv),
        ciphertext,
      }, draftKey(applicationId)));
      return true;
    } catch (_) {
      recoveryAvailable = false;
      return false;
    }
  }

  async function readRecoveryDraft(applicationId) {
    if (!recoveryAvailable) return null;
    try {
      const db = await recoveryDb();
      if (!db) return null;
      const transaction = db.transaction('drafts', 'readonly');
      const record = await idbRequest(transaction.objectStore('drafts').get(draftKey(applicationId)));
      if (!record || record.user !== recoveryUser || Number(record.expiresAt || 0) <= Date.now()) {
        if (record) await removeRecoveryDraft(applicationId);
        return null;
      }
      const key = await recoveryKey(db);
      const plaintext = await crypto.subtle.decrypt(
        { name: 'AES-GCM', iv: new Uint8Array(record.iv) }, key, record.ciphertext,
      );
      return JSON.parse(new TextDecoder().decode(plaintext));
    } catch (_) {
      return null;
    }
  }

  async function removeRecoveryDraft(applicationId) {
    try {
      const db = await recoveryDb();
      if (!db) return;
      const transaction = db.transaction('drafts', 'readwrite');
      await idbRequest(transaction.objectStore('drafts').delete(draftKey(applicationId)));
    } catch (_) { /* Recovery deletion is best effort. */ }
    storageRemove(draftKey(applicationId));
  }

  function canonicalJson(value) {
    const normalize = item => {
      if (Array.isArray(item)) return item.map(normalize);
      if (item && typeof item === 'object') {
        return Object.keys(item).sort().reduce((result, key) => {
          result[key] = normalize(item[key]);
          return result;
        }, {});
      }
      return item;
    };
    return JSON.stringify(normalize(value));
  }

  function draftMatchesApplication(draft, application) {
    if (!draft || !application) return false;
    const configuration = draft.configuration || {};
    const document = application.document_packet?.documents?.find(item => item.key === draft.documentKey);
    return (!draft.documentKey || (document && Object.entries(draft.documentPayload || {}).every(([key, value]) =>
      canonicalJson(value) === canonicalJson((application.form_schema?.fields || []).some(field => field.key === key)
        ? application.form_payload?.[key] : document.field_payload?.[key]))))
      && canonicalJson(draft.payload || {}) === canonicalJson(application.form_payload || {})
      && canonicalJson(configuration.requirements || {}) === canonicalJson(application.product_requirements || {})
      && canonicalJson(configuration.customValues || {}) === canonicalJson(application.product_custom_values || {})
      && canonicalJson(configuration.selectedFeeKeys || []) === canonicalJson(application.product_selected_fee_keys || []);
  }

  function restoreDocumentDraft(draft) {
    if (!draft?.documentKey) return;
    const document = current?.document_packet?.documents?.find(item => item.key === draft.documentKey && item.selected && item.applicable);
    if (!document) return;
    for (const [key, value] of Object.entries(draft.documentPayload || {})) {
      const field = document.schema?.fields?.find(item => item.key === key);
      if (!field || !documentOwnsInput(field, document)) continue;
      if (current.value_contract_version === 2 && field.value_contract?.scope === 'application') current.form_payload[key] = value;
      else document.field_payload = {...document.field_payload, [key]:value};
    }
    const index = wizardSections().findIndex(section => section.key === `document:${document.key}`);
    if (index >= 0) step = index;
  }

  function renderFreshEditor(application, requestedStep = step) {
    root()?.replaceChildren();
    renderEditor(application, requestedStep);
  }

  async function reconcileSavedDraftConflict(draft, showError = true) {
    if (!draft?.applicationId || !current || String(current.id) !== String(draft.applicationId)) return false;
    syncConflict = true;
    conflictDraft = draft;
    conflictServerLoaded = false;
    dirty = false;
    syncCloseProtection();
    window.clearTimeout(saveTimer);
    setSaveState(recoveryAvailable ? 'Encrypted on phone' : 'Conflict', 'offline');
    renderFreshEditor(current, step);

    if (conflictRefreshInFlight) return conflictRefreshInFlight;
    conflictRefreshInFlight = (async () => {
      const result = await apiFetch(`/applications/${draft.applicationId}/`, {});
      if (!result.ok || !result.data?.ok || !result.data?.application) {
        conflictServerLoaded = false;
        renderFreshEditor(current, step);
        if (showError) showToast(result.data?.error || 'Could not refresh the server draft. Your encrypted phone copy is safe.', true);
        return false;
      }
      if (!current || String(current.id) !== String(draft.applicationId)) return false;
      current = result.data.application;
      conflictServerLoaded = true;
      if (draftMatchesApplication(draft, current)) {
        syncConflict = false;
        conflictDraft = null;
        conflictServerLoaded = false;
        pendingSaveRequestId = '';
        await removeRecoveryDraft(current.id);
        renderFreshEditor(current, step);
        setSaveState('Saved', 'saved');
        return true;
      }
      renderFreshEditor(current, step);
      showToast('The server and encrypted phone drafts differ. Choose which one to keep.', true);
      return false;
    })();
    try {
      return await conflictRefreshInFlight;
    } finally {
      conflictRefreshInFlight = null;
    }
  }

  async function recoverDraft(application) {
    if (recoveredApplications.has(application.id)) return;
    recoveredApplications.add(application.id);
    let local = await readRecoveryDraft(application.id);
    // One-time migration from the previous plaintext recovery format.
    if (!local) {
      try { local = JSON.parse(storageGet(draftKey(application.id)) || 'null'); } catch (_) { local = null; }
      if (local) await persistRecoveryDraft(application.id, local);
      storageRemove(draftKey(application.id));
    }
    if (!local) return;
    if (draftMatchesApplication(local, application)) {
      await removeRecoveryDraft(application.id);
      dirty = false;
      syncCloseProtection();
      pendingSaveRequestId = '';
      return;
    }
    if (Number(local.revision) !== Number(application.revision)) {
      syncConflict = true;
      conflictDraft = local;
      conflictDraft.applicationId = application.id;
      conflictServerLoaded = true;
      showToast('A phone recovery draft and the server revision differ. Your phone copy was kept; choose which version to continue with.', true);
      return;
    }
    current.form_payload = local.payload || current.form_payload;
    restoreDocumentDraft(local);
    current.product_requirements = local.configuration?.requirements || current.product_requirements;
    current.product_custom_values = local.configuration?.customValues || current.product_custom_values;
    current.product_selected_fee_keys = local.configuration?.selectedFeeKeys || current.product_selected_fee_keys;
    pendingSaveRequestId = local.requestId || requestKey('save');
    editGeneration = Number(local.generation || 1);
    dirty = true;
    syncCloseProtection();
    return local.documentKey || '';
  }

  function openSheet({ mode, eyebrow, title, hint = '', body = '', footer = '', trigger = null }) {
    window.OriginationSigningCompletion?.active?.dispose();
    const overlay = document.getElementById('origination-sheet-overlay');
    const toast = document.getElementById('origination-toast');
    window.clearTimeout(showToast.timer);
    if (toast) toast.hidden = true;
    sheetMode = mode;
    sheetReturnFocus = trigger || document.activeElement;
    document.getElementById('origination-sheet-eyebrow').textContent = eyebrow || 'Origination';
    document.getElementById('origination-sheet-eyebrow').hidden = mode === 'downloads';
    document.getElementById('origination-sheet-title').textContent = title;
    document.getElementById('origination-sheet-hint').textContent = hint;
    document.getElementById('origination-sheet-body').innerHTML = body;
    document.getElementById('origination-sheet-footer').innerHTML = footer;
    overlay.hidden = false;
    overlay.setAttribute('aria-hidden', 'false');
    document.body.classList.add('origination-modal-open');
    syncTelegramControls();
    window.requestAnimationFrame(() => {
      focusableElements(document.getElementById('origination-sheet'))[0]?.focus()
        || document.getElementById('origination-sheet')?.focus();
    });
  }

  function closeSheet({ restoreFocus = true } = {}) {
    cameraDialog?.close();
    sheetCleanup?.(); sheetCleanup = null;
    window.OriginationSigningCompletion?.active?.dispose();
    const overlay = document.getElementById('origination-sheet-overlay');
    if (!sheetMode && overlay.hidden) return;
    overlay.hidden = true;
    overlay.setAttribute('aria-hidden', 'true');
    const returnFocus = sheetReturnFocus;
    testSignatureResizeObserver?.disconnect?.();
    testSignatureResizeObserver = null;
    testSignatureStrokes = [];
    testSignatureActiveStroke = null;
    activeCameraStream?.getTracks?.().forEach(track => track.stop());
    activeCameraStream = null;
    sheetMode = '';
    sheetReturnFocus = null;
    document.body.classList.remove('origination-modal-open');
    syncTelegramControls();
    if (restoreFocus) window.requestAnimationFrame(() => returnFocus?.focus?.());
  }

  function redrawTestSignature() {
    const canvas = document.querySelector('[data-test-signature-canvas]');
    if (!canvas) return;
    const bounds = canvas.getBoundingClientRect();
    const scale = Math.min(2, Math.max(1, Number(window.devicePixelRatio) || 1));
    const width = Math.max(1, Math.round(bounds.width * scale));
    const height = Math.max(1, Math.round(bounds.height * scale));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    const context = canvas.getContext('2d');
    if (!context) return;
    context.clearRect(0, 0, width, height);
    context.strokeStyle = '#17231e';
    context.lineWidth = Math.max(2, 2.2 * scale);
    context.lineCap = 'round';
    context.lineJoin = 'round';
    [...testSignatureStrokes, ...(testSignatureActiveStroke ? [testSignatureActiveStroke] : [])].forEach(stroke => {
      if (stroke.length < 2) return;
      context.beginPath();
      context.moveTo(stroke[0][0] * width, stroke[0][1] * height);
      stroke.slice(1).forEach(point => context.lineTo(point[0] * width, point[1] * height));
      context.stroke();
    });
  }

  function testSignaturePoint(canvas, event) {
    const bounds = canvas.getBoundingClientRect();
    return [
      Math.max(0, Math.min(1, (event.clientX - bounds.left) / Math.max(1, bounds.width))),
      Math.max(0, Math.min(1, (event.clientY - bounds.top) / Math.max(1, bounds.height))),
    ];
  }

  function testSignaturePointCount() {
    return testSignatureStrokes.reduce((total, stroke) => total + stroke.length, 0)
      + (testSignatureActiveStroke?.length || 0);
  }

  function updateTestSignatureControls() {
    const drawButton = document.querySelector('[data-test-signature-mode="drawn"]');
    const typedButton = document.querySelector('[data-test-signature-mode="typed"]');
    const drawPanel = document.querySelector('[data-test-signature-draw]');
    const typedPanel = document.querySelector('[data-test-signature-type]');
    if (!drawButton || !typedButton || !drawPanel || !typedPanel) return;
    const drawn = drawButton.getAttribute('aria-selected') === 'true';
    drawPanel.hidden = !drawn;
    typedPanel.hidden = drawn;
    drawButton.setAttribute('aria-selected', String(drawn));
    typedButton.setAttribute('aria-selected', String(!drawn));
    if (drawn) window.requestAnimationFrame(redrawTestSignature);
    else document.querySelector('[data-test-signature-name]')?.focus();
  }

  function openSignatureSheet(button, verified = false) {
    testSignatureStrokes = [];
    testSignatureActiveStroke = null;
    const requestId = requestKey(verified ? 'staff-signature' : 'test-signature');
    const approving = verified && (current.approval_roles || []).includes(button.dataset.signerRole);
    openSheet({
      mode: 'test-signature', eyebrow: verified ? '' : 'Non-production simulator', title: verified ? 'Sign' : 'Capture TEST signature',
      hint: verified ? 'Review the document bundle. Your signature applies to your assigned fields.' : 'Use one synthetic mark for this signer. It will be reused at every signature placement in the TEST document bundle. Do not enter or draw a real signature.', trigger: button,
      body: `${verified ? '' : '<aside class="test-signature-warning" role="note"><strong>TEST ONLY</strong><span>No OTP or identity verification is performed. The output remains watermarked and is not legally signed.</span></aside>'}
        <div class="test-signature-tabs" role="tablist" aria-label="Signature entry method"><button type="button" role="tab" aria-selected="true" data-test-signature-mode="drawn">Draw</button><button type="button" role="tab" aria-selected="false" data-test-signature-mode="typed">Type</button></div>
        <section class="test-signature-panel" role="tabpanel" data-test-signature-draw><canvas data-test-signature-canvas aria-label="Draw a synthetic test signature" tabindex="0"></canvas><div class="test-signature-tools"><small>Draw inside the box using a finger, mouse or stylus.</small><button type="button" class="btn btn-secondary" data-test-signature-clear>Clear</button></div></section>
        <section class="test-signature-panel" role="tabpanel" data-test-signature-type hidden><label class="test-signature-name"><span>Typed TEST signer name</span><input type="text" maxlength="120" autocomplete="off" data-test-signature-name placeholder="Synthetic Test Signer"></label><output class="test-signature-typed-preview" data-test-signature-typed-preview>Synthetic Test Signer</output></section>
        ${verified && current.signing_workspace ? `<label class="staff-signing-consent"><input type="checkbox" data-staff-consent><span>${escapeHtml(current.signing_package?.verified_signing?.consent_text || 'I reviewed these documents and agree to sign them.')}</span></label>` : ''}<p class="test-signature-status" data-test-signature-status aria-live="polite"></p>`,
      footer: `<button type="button" class="btn btn-secondary" data-sheet-cancel>Cancel</button><button type="button" class="btn btn-primary" data-primary-action="${verified ? 'Sign documents' : 'Place TEST signature'}" data-test-signature-confirm>${verified ? 'Sign documents' : 'Place TEST signature'}</button>`,
    });
    if (verified) {
      document.getElementById('origination-sheet-title').textContent = approving ? 'Approve & sign' : 'Sign documents';
      document.getElementById('origination-sheet-hint').textContent = approving
        ? 'Your approval and signature apply to these reviewed documents. The final approver locks the application.'
        : current.signing_workspace ? 'All required signers complete approval. Your signature applies to these documents.' : 'Your signature remains provisional until the configured final approver approves and signs.';
      document.querySelector('[data-test-signature-canvas]').setAttribute('aria-label', 'Draw your signature');
      document.querySelector('[data-test-signature-type] label span').textContent = 'Your full name';
      document.querySelector('[data-test-signature-name]').placeholder = 'Full name';
      document.querySelector('[data-test-signature-name]').autocomplete = 'name';
      document.querySelector('[data-test-signature-typed-preview]').textContent = '';
      document.querySelector('[data-test-signature-confirm]').textContent = approving ? 'Approve & sign' : 'Sign documents';
    }
    const canvas = document.querySelector('[data-test-signature-canvas]');
    const status = document.querySelector('[data-test-signature-status]');
    const setStatus = message => { if (status) status.textContent = message || ''; };
    const finishStroke = event => {
      if (!testSignatureActiveStroke || (event.pointerId != null && canvas.dataset.pointerId !== String(event.pointerId))) return;
      if (testSignatureActiveStroke.length >= 2) testSignatureStrokes.push(testSignatureActiveStroke);
      testSignatureActiveStroke = null;
      delete canvas.dataset.pointerId;
      redrawTestSignature();
    };
    canvas.addEventListener('pointerdown', event => {
      if (event.button !== undefined && event.button !== 0) return;
      if (testSignatureStrokes.length >= 40 || testSignaturePointCount() >= 2000) {
        setStatus(verified ? 'The signature pad is full. Clear it to draw again.' : 'The test signature pad is full. Clear it to draw again.');
        return;
      }
      event.preventDefault();
      canvas.setPointerCapture?.(event.pointerId);
      canvas.dataset.pointerId = String(event.pointerId);
      testSignatureActiveStroke = [testSignaturePoint(canvas, event)];
      setStatus('');
    });
    canvas.addEventListener('pointermove', event => {
      if (!testSignatureActiveStroke || canvas.dataset.pointerId !== String(event.pointerId)) return;
      event.preventDefault();
      if (testSignaturePointCount() >= 2000 || testSignatureActiveStroke.length >= 500) return;
      const point = testSignaturePoint(canvas, event);
      const previous = testSignatureActiveStroke.at(-1);
      if (Math.hypot(point[0] - previous[0], point[1] - previous[1]) < .0025) return;
      testSignatureActiveStroke.push(point);
      redrawTestSignature();
    });
    ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(name => canvas.addEventListener(name, finishStroke));
    document.querySelectorAll('[data-test-signature-mode]').forEach(modeButton => modeButton.onclick = () => {
      document.querySelectorAll('[data-test-signature-mode]').forEach(item => item.setAttribute('aria-selected', String(item === modeButton)));
      setStatus('');
      updateTestSignatureControls();
    });
    document.querySelector('[data-test-signature-clear]').onclick = () => {
      testSignatureStrokes = [];
      testSignatureActiveStroke = null;
      setStatus('Signature pad cleared.');
      redrawTestSignature();
    };
    const typedInput = document.querySelector('[data-test-signature-name]');
    const typedPreview = document.querySelector('[data-test-signature-typed-preview]');
    const typedAppearance = window.OriginationSignatureAppearance.mount({
      input: typedInput, container: typedPreview,
      request: async values => {
        const result = await postJson(`/applications/${current.id}/signature-preview/`, {
          ...values, revision: current.revision, package_id: button.dataset.packageId, test_mode: !verified,
          signer_role: button.dataset.signerRole, participant_id: button.dataset.participantId || '',
        });
        if (!result.ok) throw new Error(result.data?.error || 'Could not load signature preview.');
        return result.data;
      },
    });
    sheetCleanup = () => typedAppearance.dispose();
    document.querySelector('[data-sheet-cancel]').onclick = () => { typedAppearance.dispose(); closeSheet(); };
    document.querySelector('[data-test-signature-confirm]').onclick = () => runPrimaryAction(verified ? 'Saving signature...' : 'Placing TEST signature...', async () => {
      const drawn = document.querySelector('[data-test-signature-mode="drawn"]').getAttribute('aria-selected') === 'true';
      let capture;
      try { capture = drawn ? { method: 'drawn', strokes: testSignatureStrokes } : typedAppearance.capture(); }
      catch (error) { return setStatus(error.message); }
      if (drawn && !testSignatureStrokes.length) return setStatus(verified ? 'Draw your signature before saving.' : 'Draw the TEST signature before confirming.');
      if (!drawn && (capture.name.length < 2 || capture.name.length > 120)) return setStatus(verified ? 'Enter your full name using 2 to 120 characters.' : 'Enter a test signer name using 2 to 120 characters.');
      if (verified && current.signing_workspace && !document.querySelector('[data-staff-consent]')?.checked) return setStatus('Confirm that you reviewed and agree to sign the documents.');
      let result = await postJson(verified ? `/applications/${current.id}/staff-signature/` : `/applications/${current.id}/test-signing/action/`, {
        revision: current.revision, package_id: button.dataset.packageId,
        document_key: button.dataset.documentKey, slot_key: button.dataset.slotKey,
        signer_role: button.dataset.signerRole, participant_id: button.dataset.participantId || '', signature_capture: capture,
        consent: document.querySelector('[data-staff-consent]')?.checked === true,
        reviewed_packet_version: approvalReview?.revision === current.revision && approvalReview?.packageId === button.dataset.packageId ? approvalReview.version : '',
        client_request_id: requestId,
      });
      if (verified && !result.ok && (result.status === 0 || result.status >= 500)) {
        const refreshed = await apiFetch(`/applications/${current.id}/`);
        const app = refreshed.data?.application;
        const participant = app?.signing_package?.verified_signing?.participants?.find(person =>
          button.dataset.participantId ? person.participant_id === button.dataset.participantId : person.role === button.dataset.signerRole);
        const signatures = participant?.slots?.filter(slot => slot.type === 'signature') || [];
        if (refreshed.ok && signatures.length && signatures.every(slot => slot.completed)
            && participant.signature_actor_id === capabilities.user_id) {
          result = { ...refreshed, data: {...refreshed.data, signature_receipt: {signed_at: participant.signed_at}} };
        }
      }
      if (!result.ok) return setStatus(result.data?.error || (verified ? 'Could not save your signature. Try again.' : 'Could not place this TEST signature.'));
      current = result.data.application;
      if (verified) {
        const receipt = result.data.signature_receipt;
        const finish = () => {
          closeSheet({ restoreFocus: false });
          renderEditor(current, wizardSections().length - 1);
          window.requestAnimationFrame(() => root()?.querySelector('h2, h1')?.focus?.());
        };
        document.getElementById('origination-sheet-title').textContent = 'Signing complete';
        document.getElementById('origination-sheet-hint').textContent = '';
        document.getElementById('origination-sheet-footer').replaceChildren();
        window.OriginationSigningCompletion.active = window.OriginationSigningCompletion.show(document.getElementById('origination-sheet-body'), {
          reference: current.reference_number, signedAt: receipt?.signed_at,
          message: window.OriginationSigningCompletion.outcome(current), onClose: finish,
        });
        return;
      }
      closeSheet({ restoreFocus: false });
      renderEditor(current, wizardSections().length - 1);
      showToast(verified ? 'Verified staff signature applied to every configured slot.' : 'TEST signature placed in its configured slot.');
    });
    testSignatureResizeObserver = window.ResizeObserver ? new ResizeObserver(redrawTestSignature) : null;
    testSignatureResizeObserver?.observe(canvas);
    window.requestAnimationFrame(redrawTestSignature);
  }

  function openCreationSheet(trigger) {
    const branchOptions = branches.map(item => `<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`).join('');
    const groupOptions = originationGroups.map(item => `<option value="${escapeHtml(item.id)}"${item.id === originationGroupId ? ' selected' : ''}>${escapeHtml(item.label)}</option>`).join('');
    openSheet({
      mode: 'create', eyebrow: 'Origination', title: 'New application',
      hint: 'Choose a branch, product, Main LAF, and any supporting documents needed for this application.', trigger,
      body: `<form id="origination-create" class="sheet-form"><label><span>Branch</span><select name="branch" id="origination-create-branch" required><option value="">Choose branch</option>${branchOptions}</select></label><label><span>Product</span><select name="product_key" id="origination-create-product" required disabled><option value="">Choose branch first</option></select></label><div id="origination-create-documents" class="packet-document-list"></div></form>`,
      footer: '<button type="submit" form="origination-create" class="btn btn-primary" id="origination-create-submit" data-primary-action="Start application" disabled>Start application</button>',
    });
    document.getElementById('origination-create-branch').onchange = event => loadProductsForBranch(event.target.value);
    if (originationGroups.length) {
      const label = document.createElement('label');
      label.innerHTML = `<span>Origination group</span><select name="group_id" id="origination-create-group" required><option value="">Choose group</option>${groupOptions}</select>`;
      document.getElementById('origination-create').prepend(label);
      label.querySelector('select').onchange = event => {
        originationGroupId = event.target.value;
        loadProductsForBranch(document.getElementById('origination-create-branch').value);
      };
    }
    document.getElementById('origination-create').onsubmit = startApplication;
    syncPrimaryAction();
  }

  async function openDocumentSheet(trigger) {
    if (!current || current.status !== 'draft') return;
    window.clearTimeout(saveTimer);
    const activeSection = wizardSections()[step];
    const saved = activeSection?.key?.startsWith('document:')
      ? await saveSupportingDocument(activeSection.key.slice(9)) : await saveDraft(true);
    if (!saved) return;
    const applicationId = current.id;
    trigger.disabled = true;
    let result;
    try { result = await apiFetch(`/applications/${applicationId}/documents/choices/`, {}); }
    finally { trigger.disabled = false; }
    if (!result.ok) return showToast(result.data?.error || 'Could not load the document choices. Try again.', 'error');
    if (current.id !== applicationId) return;
    const catalogue = result.data;
    const currentPrimaryId = catalogue.primary_template_id;
    const mains = (catalogue.main_lafs || []).map(item => `<label class="packet-document-option"><input type="radio" name="primary_template_id" value="${escapeHtml(item.id)}"${item.selected ? ' checked' : ''} required><span><strong>${escapeHtml(item.name)}</strong><small>Main LAF${item.version ? ` · version ${escapeHtml(item.version)}` : ''}</small></span></label>`).join('');
    const supporting = (catalogue.supporting_documents || []).map(item => `<label class="packet-document-option"><input type="checkbox" name="supporting_template_ids" value="${escapeHtml(item.id)}"${item.selected ? ' checked' : ''}${item.required || !item.available ? ' disabled' : ''}><span><strong>${escapeHtml(item.name)}</strong><small data-document-choice-hint="${escapeHtml(item.id)}">${escapeHtml(item.reason || (item.required ? 'Required' : 'Optional'))}${item.version ? ` · version ${escapeHtml(item.version)}` : ''}</small></span></label>`).join('');
    openSheet({
      mode: 'manage-documents', eyebrow: current.reference_number, title: 'Manage documents',
      hint: 'Choose one Main LAF and any supporting documents.', trigger,
      body: `<form id="origination-documents-form" class="sheet-form"><div class="section-title"><h3>Main LAF</h3></div>${mains}<div class="section-title"><h3>Supporting documents</h3></div>${supporting || '<p class="muted">No supporting documents are available.</p>'}</form>`,
      footer: '<button type="button" class="btn btn-secondary" data-sheet-cancel>Cancel</button><button type="submit" form="origination-documents-form" class="btn btn-primary">Save changes</button>',
    });
    document.querySelector('[data-sheet-cancel]').onclick = () => closeSheet();
    const form = document.getElementById('origination-documents-form');
    const syncChoices = () => {
      const primaryId = form.querySelector('[name="primary_template_id"]:checked')?.value;
      for (const item of catalogue.supporting_documents || []) {
        const input = [...form.querySelectorAll('[name="supporting_template_ids"]')].find(node => node.value === item.id);
        const compatible = item.compatible_main_ids.includes(primaryId);
        // An incompatible selected document must remain removable.
        input.disabled = (item.required && primaryId === currentPrimaryId) || ((!item.available || !compatible) && !input.checked);
        input.setAttribute('aria-invalid', String(input.checked && !compatible));
        const hint = input.closest('label').querySelector('small');
        hint.textContent = `${item.reason || (!compatible ? 'Not compatible with this Main LAF. Remove this choice.' : item.required && primaryId === currentPrimaryId ? 'Required' : 'Optional')}${item.version ? ` · version ${item.version}` : ''}`;
      }
    };
    form.addEventListener('change', syncChoices);
    syncChoices();
    let saving = false;
    form.onsubmit = async event => {
      event.preventDefault();
      if (saving) return;
      const values = new FormData(form);
      const primaryId = values.get('primary_template_id');
      if (!primaryId) return showToast('Choose a Main LAF.', 'error');
      const supportingIds = [...form.querySelectorAll('[name="supporting_template_ids"]:checked')].map(input => input.value);
      if (form.querySelector('[name="supporting_template_ids"][aria-invalid="true"]'))
        return showToast('Remove the documents that are not compatible with this Main LAF.', 'warning');
      const restarting = primaryId !== currentPrimaryId;
      saving = true;
      const submit = document.querySelector('[form="origination-documents-form"]');
      const controls = [...form.querySelectorAll('input'), document.querySelector('[data-sheet-cancel]'), document.getElementById('origination-sheet-close')].filter(Boolean);
      const previousDisabled = controls.map(control => control.disabled);
      controls.forEach(control => { control.disabled = true; });
      submit.disabled = true;
      try {
        if (restarting) {
          const message = 'Changing the Main LAF will cancel this draft and start a blank application. You will need to enter the details and upload documents again.';
          const confirmed = typeof tg?.showPopup === 'function'
            ? await new Promise(resolve => tg.showPopup({title:'Change Main LAF?',message,
              buttons:[{id:'change',type:'destructive',text:'Start new draft'},{type:'cancel'}]}, id => resolve(id === 'change')))
            : window.confirm(message);
          if (!confirmed) return;
        }
        const identity = `${applicationId}:${catalogue.revision}:${primaryId}:${supportingIds.slice().sort().join(',')}:${catalogue.catalogue_revision}`;
        const storageKey = `origination-document-request:${identity}`;
        const key = storageGet(storageKey) || requestKey('documents');
        storageSet(storageKey, key);
        const updated = await postJson(`/applications/${applicationId}/${restarting ? 'restart/' : 'documents/selection/'}`, {
          revision: catalogue.revision,
          ...(restarting ? {primary_template_id:primaryId,confirm_blank_restart:true} : {}),
          supporting_template_ids:supportingIds, catalogue_revision:catalogue.catalogue_revision,
          client_request_id:key, request_id:key,
        });
        if (!updated.ok) return showToast(updated.data?.error || 'Could not save document choices. Your choices are kept; try again.', 'error');
        storageRemove(storageKey);
        closeSheet({restoreFocus:false});
        let targetStep = 0;
        if (!restarting) {
          const previousSection = wizardSections()[step]?.key;
          current = updated.data.application;
          const sections = wizardSections();
          targetStep = sections.findIndex(section => section.key === previousSection);
          if (targetStep < 0) targetStep = Math.min(step, sections.length - 1);
        }
        await openEditor(updated.data.application, targetStep);
        showToast(restarting ? 'New blank application started. Enter the details again.' : 'Documents updated.', 'success');
      } finally {
        saving = false; submit.disabled = false;
        controls.forEach((control, index) => { control.disabled = previousDisabled[index]; });
      }
    };
  }

  function syncCreationPrimary() {
    const branch = document.getElementById('origination-create-branch');
    const product = document.getElementById('origination-create-product');
    const mainLaf = document.querySelector('input[name="primary_template_id"]:checked');
    const submit = document.getElementById('origination-create-submit');
    if (!submit) return;
    const catalogue = products.find(item => item.product_key === product?.value)?.document_catalogue;
    document.querySelectorAll('#origination-create-documents input[name="supporting_template_ids"]').forEach(input => {
      const item = catalogue?.supporting_documents?.find(document => document.id === input.value);
      const compatible = !item?.compatible_main_ids || (mainLaf && item.compatible_main_ids.includes(mainLaf.value));
      input.disabled = !compatible;
      if (!compatible) input.checked = false;
      const hint = input.closest('label')?.querySelector('small');
      if (hint) hint.textContent = compatible ? 'Optional supporting document' : mainLaf ? 'Choose a compatible Main LAF' : 'Choose a Main LAF first';
    });
    submit.disabled = createInFlight || !branch?.value || !product?.value || !mainLaf;
    syncPrimaryAction();
  }

  function filterStatusOptions() {
    return statusOptions.map(item => `<option value="${escapeHtml(item.value)}"${listState.status === item.value ? ' selected' : ''}>${escapeHtml(item.label)}</option>`).join('');
  }

  function openFilterSheet(trigger) {
    const productOptions = filterProducts.map(item => `<option value="${escapeHtml(item.product_key)}"${listState.productKey === item.product_key ? ' selected' : ''}>${escapeHtml(item.name)}</option>`).join('');
    openSheet({
      mode: 'filter', eyebrow: 'Application queue', title: 'Filter applications',
      hint: '', trigger,
      body: `<form id="origination-filter-sheet" class="sheet-form"><label><span>Product</span><select name="product_key"><option value="">All products</option>${productOptions}</select></label><label><span>Status</span><select name="status"><option value="">All statuses</option>${filterStatusOptions()}</select></label></form>`,
      footer: '<button type="button" class="btn btn-secondary" id="origination-filter-reset">Reset</button><button type="submit" form="origination-filter-sheet" class="btn btn-primary">Apply filters</button>',
    });
    document.getElementById('origination-filter-reset').onclick = () => applyListFilters({ productKey: '', status: '' });
    document.getElementById('origination-filter-sheet').onsubmit = event => {
      event.preventDefault();
      const values = new FormData(event.currentTarget);
      applyListFilters({ productKey: String(values.get('product_key') || ''), status: String(values.get('status') || '') });
    };
  }

  function openSectionSheet(trigger) {
    const sections = wizardSections();
    openSheet({
      mode: 'sections', eyebrow: 'Application progress', title: 'Go to section',
      hint: 'Sections come from the approved product schema.', trigger,
      body: `<div class="section-picker">${sections.map((item, index) => `<button type="button" data-section-index="${index}" class="section-picker-item${index === step ? ' active' : ''}"><span>${index < step ? iconSvg('check') : index + 1}</span><strong>${escapeHtml(item.label)}</strong>${index === step ? '<small>Current</small>' : ''}</button>`).join('')}</div>`,
      footer: '<button type="button" class="btn btn-secondary" data-sheet-cancel>Close</button>',
    });
    document.querySelector('[data-sheet-cancel]').onclick = () => closeSheet();
    document.querySelectorAll('[data-section-index]').forEach(button => button.onclick = async () => {
      const editable = ['draft', 'correction_required'].includes(current.status);
      const activeSection = wizardSections()[step];
      if (editable && !(activeSection?.key.startsWith('document:')
        ? await saveSupportingDocument(activeSection.key.slice(9)) : await saveDraft(true))) return;
      const target = Number(button.dataset.sectionIndex);
      closeSheet({ restoreFocus: false });
      renderEditor(current, target);
    });
  }

  async function startApplication(event) {
    event.preventDefault();
    if (createInFlight) return;
    const values = new FormData(event.currentTarget);
    const product = products.find(item => item.product_key === values.get('product_key'));
    const supportingIds = values.getAll('supporting_template_ids');
    const identity = `${values.get('group_id') || originationGroupId}:${values.get('branch')}:${values.get('product_key')}:${values.get('primary_template_id')}:${supportingIds.slice().sort().join(',')}:${product?.document_catalogue?.catalogue_revision || ''}`;
    const storageKey = `origination-create-request:${identity}`;
    const createKey = storageGet(storageKey) || requestKey('create');
    storageSet(storageKey, createKey);
    createInFlight = true;
    setPrimaryBusy(true, 'Starting...');
    let createdApplication = null;
    try {
      const result = await postJson('/applications/', {
        product_key: values.get('product_key'), branch: values.get('branch'),
        group_id: values.get('group_id') || originationGroupId,
        primary_template_id: values.get('primary_template_id'),
        supporting_template_ids: supportingIds,
        catalogue_revision: product?.document_catalogue?.catalogue_revision || '',
        client_request_id: createKey,
      });
      if (!result.ok) return showToast(result.data?.error || 'Could not start the application.', true);
      createdApplication = result.data?.application;
      if (!createdApplication?.id) throw new Error('The application response was incomplete.');
      await openEditor(createdApplication, 0);
      storageRemove(storageKey);
      closeSheet({ restoreFocus: false });
    } catch (_) {
      showToast(
        createdApplication
          ? 'The application was created, but its editor could not open. Refresh and open it from My applications.'
          : 'Could not start the application. Try again.',
        true,
      );
      if (createdApplication) {
        try { await loadApplications(); } catch (_) { /* Keep the safe recovery message visible. */ }
      }
    } finally {
      createInFlight = false;
      setPrimaryBusy(false);
    }
  }

  function applicationListParams() {
    const params = new URLSearchParams({ queue: listState.queue, page: String(listState.page), page_size: '10' });
    if (listState.status) params.set(['draft', 'changes', 'progress', 'completed', 'closed'].includes(listState.status) ? 'status_group' : 'status', listState.status);
    if (listState.productKey) params.set('product_key', listState.productKey);
    if (listState.query) params.set('q', listState.query);
    if (listState.signatureOnly) params.set('signature_only', '1');
    return params;
  }

  async function applyListFilters(updates) {
    if (updates.queue) listState.signatureOnly = false;
    Object.assign(listState, updates, { page: 1 });
    closeSheet({ restoreFocus: false });
    window.scrollTo(0, 0);
    await loadApplications();
  }

  async function exitEditor() {
    if (!current) return;
    const editable = ['draft', 'correction_required'].includes(current.status);
    if (editable && !(await saveDraft(true))) return;
    renderList({ restoreScroll: true });
  }

  async function openEditor(application, requestedStep) {
    const changingApplication = String(current?.id || '') !== String(application.id);
    if (changingApplication) {
      dirty = false;
      pendingSaveRequestId = '';
      window.clearTimeout(commercialQuoteTimer);
      commercialQuoteState = null;
      commercialQuoteGeneration += 1;
    }
    current = application;
    if (draftSectionApplicationId !== String(application.id)) {
      completedDraftSections.clear();
      unlockedDraftSections.clear();
      draftSectionApplicationId = String(application.id);
    }
    reviewTargets.clear();
    syncConflict = false;
    conflictDraft = null;
    conflictServerLoaded = false;
    const recoveredDocumentKey = await recoverDraft(application);
    if (recoveredDocumentKey) {
      const recoveredStep = wizardSections().findIndex(section => section.key === `document:${recoveredDocumentKey}`);
      if (recoveredStep >= 0) requestedStep = recoveredStep;
    }
    if (['ready_for_review', 'reviewed', 'signing_pending', 'partially_signed', 'fully_signed', 'signed_pending_approval', 'approved', 'completed'].includes(application.status)) {
      requestedStep = wizardSections().length - 1;
    }
    // collectPayload reads live inputs during ordinary section navigation. A
    // different application must never inherit the previous form's DOM values.
    if (changingApplication) {
      root()?.replaceChildren();
    }
    renderEditor(current, requestedStep);
  }

  function currentPacketVersion(application = current) {
    return String(application?.signing_package?.verified_signing?.packet_version || '');
  }

  function scheduleSigningRefresh() {
    window.clearTimeout(signingRefreshTimer);
    signingRefreshTimer = null;
    if (!current || document.visibilityState === 'hidden'
        || !['signing_pending', 'partially_signed', 'signed_pending_approval'].includes(current.status)) return;
    signingRefreshTimer = window.setTimeout(() => void refreshCurrentSigning(), 20000);
  }

  async function refreshCurrentSigning({ manual = false } = {}) {
    if (!current || document.visibilityState === 'hidden') return false;
    const applicationId = String(current.id);
    const generation = ++signingRefreshGeneration;
    const oldVersion = currentPacketVersion();
    const result = await apiFetch(`/applications/${applicationId}/`, {});
    if (generation !== signingRefreshGeneration || String(current?.id || '') !== applicationId) return false;
    if (!result.ok || !result.data?.application) {
      if (manual) showToast(result.data?.error || 'Could not refresh signing progress.', true);
      scheduleSigningRefresh();
      return false;
    }
    const next = result.data.application;
    const changed = oldVersion !== currentPacketVersion(next) || current.status !== next.status;
    const previewOutdated = Boolean(
      previewPacketVersion && currentPacketVersion(next)
      && previewPacketVersion !== currentPacketVersion(next),
    );
    current = next;
    if ((changed || previewOutdated) && previewDocumentKey === '__signing_packet__'
        && !document.getElementById('document-preview-overlay')?.hidden) {
      if (hasFinalSignedPacket()) previewDocumentKey = '__signed_packet__';
      const notice = document.getElementById('preview-update-notice');
      if (notice) notice.hidden = false;
    } else if (changed || manual) {
      renderEditor(current, step);
      if (manual) showToast(changed ? 'Signing progress updated.' : 'Signing progress is already current.', 'info');
    }
    scheduleSigningRefresh();
    return true;
  }

  function sectionFor(key) {
    if (key.startsWith('guarantor_')) return 'guarantors';
    if (key.startsWith('security_')) return 'security';
    if (['business_location', 'business_type', 'employer_business_address', 'monthly_income', 'net_income', 'monthly_expenses', 'monthly_household_expenses'].includes(key)) return 'business';
    if (key.startsWith('applicant_') || ['borrower_full_name', 'deponent_full_name', 'deponent_id_number'].includes(key)) return 'applicant';
    if (['loan_product', 'loan_product_other', 'loan_amount', 'loan_purpose', 'own_contribution', 'repayment_period', 'project_cost', 'number_of_weeks', 'installment_amount', 'penalty_rate', 'amount_advanced', 'interest_rate', 'loan_agreement_repayment_period', 'approval_amount', 'acknowledgement_amount', 'acknowledgement_recipient_name'].includes(key)) return 'loan';
    return 'business';
  }

  function wizardSections() {
    const configured = current?.form_schema?.sections;
    let sections = Array.isArray(configured) && configured.length
      ? configured.map(item => ({ key: item.key, label: item.label || item.key, hint: item.help_text || '' }))
      : current?.form_projection_version === 1 ? [] : LEGACY_SECTIONS;
    const facilityKey = current?.form_schema?.commercial_section_key
      || (sections.some(item => item.key === 'loan_details') ? 'loan_details' : '')
      || (sections.some(item => item.key === 'invoice_details') ? 'invoice_details' : '')
      || 'commercial_terms';
    if (!current?.form_projection_version && facilityKey !== 'commercial_terms' && sections.some(item => item.key === 'commercial_terms')) {
      sections = sections.filter(item => item.key !== 'commercial_terms');
    }
    if (current?.form_projection_version === 1 || current?.value_contract_version === 2) sections = sections.filter(section => fieldsFor(section.key).length);
    const terms = current?.product_terms || {};
    const requirements = [...(terms.requirements || []), ...(current?.identity_copies || [])].filter(item => !item.workflow || item.workflow === 'loan_origination');
    const attributes = (terms.custom_attributes || []).filter(item => !(item.workflows || []).length || item.workflows.includes('loan_origination'));
    if (requirements.length || attributes.length || (terms.fees || []).some(item => !item.mandatory)) {
      sections.push({
        key: 'product_requirements',
        label: 'Product requirements',
        hint: 'Capture the evidence and product-specific details required for this facility.',
      });
    }
    const packetDocuments = current?.document_packet?.documents || [];
    const supporting = packetDocuments.filter(item => item.role === 'supporting' && item.applicable);
    if (supporting.length) {
      supporting.filter(item => item.selected).forEach(item => sections.push({
        key: `document:${item.key}`, label: item.name,
        hint: 'Shared application values are filled automatically. Complete only the remaining document details.',
        document: item,
      }));
    }
    return [...sections, { key: 'review', label: 'Review', hint: 'Confirm every selected document before submission' }];
  }

  function fieldsFor(sectionKey) {
    const sections = current?.form_schema?.sections || [];
    const facilityKey = current?.form_schema?.commercial_section_key
      || (sections.some(item => item.key === 'loan_details') ? 'loan_details' : '')
      || (sections.some(item => item.key === 'invoice_details') ? 'invoice_details' : '')
      || 'commercial_terms';
    return (current?.form_schema?.fields || []).filter(field => {
      if (field.input_owner?.kind === 'document') return false;
      const key = field.section_key || sectionFor(field.key);
      return key === sectionKey || (!current?.form_projection_version && sectionKey === facilityKey && key === 'commercial_terms');
    });
  }

  function inputOwner(field) {
    return (current?.form_schema?.fields || []).find(item => item.key === field.key)?.input_owner;
  }

  function documentOwnsInput(field, document) {
    if (current?.value_contract_version !== 2) return field.source_type !== 'system';
    if (field.value_contract?.source !== 'entered') return false;
    return field.value_contract?.scope === 'document'
      || (inputOwner(field)?.kind === 'document' && inputOwner(field).document_key === document.key);
  }

  function inputSectionKey(field) {
    const owner = inputOwner(field);
    return owner?.kind === 'document' ? `document:${owner.document_key}` : owner?.section_key || field.section_key || sectionFor(field.key);
  }

  async function goToSection(key) {
    if (!(await saveDraft(true))) return false;
    const index = wizardSections().findIndex(item => item.key === key);
    if (index < 0) return false;
    renderEditor(current, index);
    return true;
  }

  function correctionAllows(targetType, targetKey) {
    if (current?.status !== 'correction_required') return true;
    return (current?.active_correction?.items || []).some(item => (
      item.target_type === targetType
      && (item.target_key === targetKey || item.target_key.startsWith(`${targetKey}.`))
    ));
  }

  function collectPayload() {
    const payload = { ...(current?.form_payload || {}) };
    if (current?.value_contract_version === 2 || current?.form_projection_version === 1) {
      const keys = new Set((current.form_schema?.fields || []).map(field => field.key));
      for (const key of Object.keys(payload)) {
        if (key !== '_person_role_bindings' && !keys.has(key)) delete payload[key];
      }
    }
    root()?.querySelectorAll('[data-main-repeatable]').forEach(container => {
      const field = (current?.form_schema?.fields || []).find(item => item.key === container.dataset.mainRepeatable);
      const columnTypes = new Map((field?.structure?.columns || []).map(column => [column.key, column.type]));
      payload[container.dataset.mainRepeatable] = [...container.querySelectorAll('[data-repeat-row]')].map(row => {
        const item = { row_id: row.dataset.rowId || newRowId() };
        row.querySelectorAll('[data-repeat-column]').forEach(input => {
          let value = input.value.trim();
          if (['money', 'number'].includes(columnTypes.get(input.dataset.repeatColumn))) {
            value = normalizeNumericText(value);
          }
          if (columnTypes.get(input.dataset.repeatColumn) === 'boolean' && value !== '') value = value === 'true';
          item[input.dataset.repeatColumn] = value;
        });
        return item;
      });
    });
    root()?.querySelectorAll('[data-field]').forEach(input => {
      if (input.value === '') payload[input.dataset.field] = '';
      else if (input.options && ['true', 'false'].includes(input.value)) payload[input.dataset.field] = input.value === 'true';
      else payload[input.dataset.field] = input.value;
    });
    const activeDocument = wizardSections()[step]?.document;
    if (activeDocument && current?.value_contract_version === 2) {
      const shared = new Set((activeDocument.schema?.fields || []).filter(field => field.value_contract?.scope === 'application').map(field => field.key));
      for (const [key, value] of Object.entries(collectSupportingDocumentPayload(activeDocument))) {
        if (shared.has(key)) payload[key] = value;
      }
    }
    if (current?.value_contract_version === 2) {
      const links = {...(payload._person_role_bindings || {})};
      root()?.querySelectorAll('[data-person-link]').forEach(input => {
        if (input.value) links[input.dataset.personLink] = input.value;
        else delete links[input.dataset.personLink];
      });
      if (Object.keys(links).length || payload._person_role_bindings) payload._person_role_bindings = links;
      for (const role of Object.keys(links)) {
        for (const key of Object.values(current.person_role_fields?.[role] || {})) delete payload[key];
      }
    }
    return payload;
  }

  function collectProductConfiguration() {
    const requirements = { ...(current?.product_requirements || {}) };
    const customValues = { ...(current?.product_custom_values || {}) };
    const selectedFeeKeys = [];
    root()?.querySelectorAll('[data-product-requirement]').forEach(input => {
      requirements[input.dataset.productRequirement] = input.type === 'checkbox' ? input.checked : input.value;
    });
    root()?.querySelectorAll('[data-product-custom]').forEach(input => {
      customValues[input.dataset.productCustom] = input.type === 'checkbox' ? input.checked : input.value;
    });
    root()?.querySelectorAll('[data-product-fee]').forEach(input => {
      if (input.checked) selectedFeeKeys.push(input.dataset.productFee);
    });
    return { requirements, customValues, selectedFeeKeys };
  }

  function configurationControl(item, value, dataAttribute, disabled) {
    const key = escapeHtml(item.key);
    const data = `${dataAttribute}="${key}"`;
    const locked = disabled ? ' disabled' : '';
    if (item.type === 'boolean' || item.type === 'checkbox' || item.type === 'eligibility') {
      return `<label class="configuration-check"><input type="checkbox" ${data}${value === true ? ' checked' : ''}${locked}><span>Confirmed</span></label>`;
    }
    if (item.type === 'choice') {
      const options = (item.options || []).map(option => `<option value="${escapeHtml(option)}"${value === option ? ' selected' : ''}>${escapeHtml(option)}</option>`).join('');
      return `<select ${data}${locked}><option value="">Choose</option>${options}</select>`;
    }
    const inputType = item.type === 'date' ? 'date' : item.type === 'datetime' ? 'datetime-local' : 'text';
    const validation = item.validation || {};
    const numeric = ['number', 'money', 'amount'].includes(item.type) ? ` inputmode="${['money', 'amount'].includes(item.type) ? 'numeric' : 'decimal'}" data-numeric-input${['money', 'amount'].includes(item.type) ? ' data-money-input' : ''} data-min="${escapeHtml(validation.min ?? '')}" data-max="${escapeHtml(validation.max ?? '')}"` : '';
    const dateRules = item.type === 'date' ? `${validation.min_date || validation.min ? ` min="${escapeHtml(validation.min_date || validation.min)}"` : ''}${validation.max_date || validation.max ? ` max="${escapeHtml(validation.max_date || validation.max)}"` : ''}` : '';
    const pattern = inputType === 'text' && validation.pattern ? ` pattern="${escapeHtml(validation.pattern)}"` : '';
    const placeholder = item.type === 'document' ? 'Document reference or evidence note' : '';
    return `<input type="${inputType}" ${data} value="${escapeHtml(value ?? '')}"${item.required ? ' required' : ''}${numeric}${dateRules}${pattern}${placeholder ? ` placeholder="${placeholder}"` : ''}${locked}>`;
  }

  function productConfigurationMarkup(editable) {
    const terms = current?.product_terms || {};
    const requirements = [...(terms.requirements || []), ...(current?.identity_copies || [])].filter(item => !item.workflow || item.workflow === 'loan_origination');
    for (const file of current?.requirement_evidence || []) {
      if (['borrower_id_copy','guarantor_1_id_copy','guarantor_2_id_copy'].includes(file.requirement_key)
          && !requirements.some(item => item.key === file.requirement_key)) {
        requirements.push({key:file.requirement_key,label:file.requirement_label || 'Earlier ID copy',type:'document',stale_only:true});
      }
    }
    const attributes = (terms.custom_attributes || []).filter(item => !(item.workflows || []).length || item.workflows.includes('loan_origination'));
    const commercialV2 = Number(current?.form_schema?.commercial_contract_version || 0) >= 2;
    const optionalFees = commercialV2
      ? []
      : (terms.fees || []).filter(item => !item.mandatory);
    const evidenceEditable = editable || (current?.status === 'reviewed' && capabilities.can_start_signing);
    const selected = new Set(current?.product_selected_fee_keys || []);
    const requirementRows = requirements.map(item => {
      const required = item.required ? '<span class="required-mark" aria-label="required">*</span>' : '';
      const stage = item.enforcement_stage ? `<small class="field-help">Required before ${escapeHtml(item.enforcement_stage.replaceAll('_', ' '))}</small>` : '';
      const correction = ['ready_for_review', 'signed_pending_approval'].includes(current.status) ? correctionToggle('requirement', item.key, item.label) : '';
      if (item.type === 'document') {
        const evidence = (current?.requirement_evidence || []).filter(file => file.requirement_key === item.key && file.status !== 'removed');
        const itemEditable = evidenceEditable && !item.stale_only && correctionAllows('requirement', item.key);
        const upload = itemEditable ? item.identity_role
          ? `<div class="evidence-upload-actions"><button type="button" class="evidence-upload" data-id-capture="${escapeHtml(item.key)}">Front &amp; back</button><label class="evidence-upload"><input type="file" accept="application/pdf" data-evidence-upload="${escapeHtml(item.key)}"><span>Choose PDF</span></label></div>`
          : `<div class="evidence-upload-actions"><button type="button" class="evidence-upload evidence-camera" data-evidence-camera="${escapeHtml(item.key)}"><span>Take photo</span></button><label class="evidence-upload"><input type="file" accept="application/pdf,image/jpeg,image/png" data-evidence-upload="${escapeHtml(item.key)}"><span>Choose file</span></label></div>` : '';
        const fileRows = evidence.map(file => `<span class="evidence-row status-${escapeHtml(file.status)}"><span><strong>${escapeHtml(file.filename)}</strong><small>${escapeHtml(file.identity_changed ? 'ID changed · earlier copy' : file.status === 'failed' ? file.error || 'Upload failed' : `${Math.max(1, Math.round(file.byte_size / 1024))} KB · ${file.status}`)}</small></span><span class="evidence-actions">${file.download_url ? `<button type="button" data-evidence-open="${escapeHtml(file.id)}" data-evidence-name="${escapeHtml(file.filename)}" data-evidence-mime="${escapeHtml(file.mime_type || '')}">View</button>` : ''}${itemEditable && file.status === 'uploaded' ? `<button type="button" data-evidence-remove="${escapeHtml(file.id)}">Remove</button>` : ''}</span></span>`).join('');
        return `<div class="laf-field laf-field-wide evidence-field" data-product-wrap="requirement:${escapeHtml(item.key)}"><span>${escapeHtml(item.label)}${required}</span><small class="field-error" aria-live="polite"></small>${item.description ? `<small class="field-help">${escapeHtml(item.description)}</small>` : ''}${stage}${correction}${fileRows || '<small class="field-help">No evidence uploaded.</small>'}${upload}</div>`;
      }
      const signingEditable = current?.status === 'reviewed'
        && capabilities.can_start_signing && item.enforcement_stage === 'signing';
      const itemEditable = (editable && correctionAllows('requirement', item.key)) || signingEditable;
      return `<label class="laf-field" data-product-wrap="requirement:${escapeHtml(item.key)}"><span>${escapeHtml(item.label)}${required}</span><small class="field-error" aria-live="polite"></small>${item.description ? `<small class="field-help">${escapeHtml(item.description)}</small>` : ''}${stage}${correction}${configurationControl(item, current?.product_requirements?.[item.key], 'data-product-requirement', !itemEditable)}</label>`;
    }).join('');
    const attributeRows = attributes.map(item => {
      const required = item.required ? '<span class="required-mark" aria-label="required">*</span>' : '';
      return `<label class="laf-field" data-product-wrap="custom:${escapeHtml(item.key)}"><span>${escapeHtml(item.label)}${required}</span><small class="field-error" aria-live="polite"></small>${item.help_text ? `<small class="field-help">${escapeHtml(item.help_text)}</small>` : ''}${configurationControl(item, current?.product_custom_values?.[item.key] ?? item.default, 'data-product-custom', !editable || current?.status === 'correction_required')}</label>`;
    }).join('');
    const feeRows = optionalFees.map(item => `<div class="laf-field configuration-fee" data-product-wrap="fee:${escapeHtml(item.key)}"><span>${escapeHtml(item.label)}</span><small class="field-error" aria-live="polite"></small><small class="field-help">Optional ${escapeHtml(item.collection_mode)} fee</small><label class="configuration-check"><input type="checkbox" data-product-fee="${escapeHtml(item.key)}"${selected.has(item.key) ? ' checked' : ''}${editable && current?.status !== 'correction_required' ? '' : ' disabled'}><span>Include in quote</span></label></div>`).join('');
    const quote = current?.product_quote || {};
    const quoteMarkup = quote.installment_amount ? `<aside class="notice"><strong>Current quote</strong><span>${escapeHtml(quote.currency)} ${escapeHtml(formatWholeKes(quote.installment_amount))} × ${escapeHtml(quote.installment_count)}; total repayment ${escapeHtml(quote.currency)} ${escapeHtml(formatWholeKes(quote.total_repayment))}${Number(quote.upfront_fees || 0) ? `; upfront fees ${escapeHtml(quote.currency)} ${escapeHtml(formatWholeKes(quote.upfront_fees))}` : ''}</span></aside>` : '';
    return `${quoteMarkup}<div class="laf-grid">${requirementRows}${attributeRows}${feeRows}</div>`;
  }

  function commercialQuoteMarkup() {
    const state = commercialQuoteState;
    const quote = state?.quote || current?.product_quote || {};
    const findings = state?.findings || [];
    if (state?.loading) {
      return '<aside class="commercial-quote" id="commercial-quote" aria-live="polite"><strong>Calculating product quote…</strong></aside>';
    }
    if (!quote.installment_amount) {
      const message = findings[0]?.message || 'Enter the loan amount and repayment tenor to calculate the governed product quote.';
      return `<aside class="commercial-quote" id="commercial-quote" aria-live="polite"><strong>Product-policy quote</strong><span>${escapeHtml(message)}</span></aside>`;
    }
    const terms = quote.terms || current?.product_terms || {};
    const currency = quote.currency || terms.currency || 'KES';
    const feeRows = (quote.fees || []).map(item => `<li><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(currency)} ${escapeHtml(formatWholeKes(item.amount))}</strong></li>`).join('');
    const warning = findings.length
      ? `<p class="commercial-quote-warning">${escapeHtml(findings.map(item => item.message).join(' '))}</p>`
      : '<p class="commercial-quote-ready">Within the published product policy.</p>';
    return `<details class="commercial-quote" id="commercial-quote"><summary><span><strong>Calculated product terms</strong><small>${escapeHtml(terms.interest_rate || '')}% ${escapeHtml(String(terms.interest_method || '').replaceAll('_', ' '))} · ${escapeHtml(String(terms.repayment_frequency || '').replaceAll('_', ' '))}</small></span><strong>${escapeHtml(currency)} ${escapeHtml(formatWholeKes(quote.installment_amount))} × ${escapeHtml(quote.installment_count)}</strong></summary><div class="commercial-quote-body" aria-live="polite"><dl><div><dt>Financed principal</dt><dd>${escapeHtml(currency)} ${escapeHtml(formatWholeKes(quote.financed_principal))}</dd></div><div><dt>Total interest</dt><dd>${escapeHtml(currency)} ${escapeHtml(formatWholeKes(quote.interest))}</dd></div><div><dt>Total repayment</dt><dd>${escapeHtml(currency)} ${escapeHtml(formatWholeKes(quote.total_repayment))}</dd></div><div><dt>Final installment</dt><dd>${escapeHtml(currency)} ${escapeHtml(formatWholeKes(quote.final_installment_amount))}</dd></div><div><dt>Upfront fees</dt><dd>${escapeHtml(currency)} ${escapeHtml(formatWholeKes(quote.upfront_fees))}</dd></div></dl>${feeRows ? `<ul class="commercial-quote-fees">${feeRows}</ul>` : ''}${warning}</div></details>`;
  }

  function facilitySectionKey() {
    const sections = current?.form_schema?.sections || [];
    return current?.form_schema?.commercial_section_key
      || (sections.some(item => item.key === 'loan_details') ? 'loan_details' : '')
      || (sections.some(item => item.key === 'invoice_details') ? 'invoice_details' : '')
      || 'commercial_terms';
  }

  function sectionFieldsMarkup(sectionKey, values, editable) {
    const fields = fieldsFor(sectionKey);
    const linked = current?.form_payload?._person_role_bindings || {};
    const linkedKeys = new Set(Object.keys(linked).flatMap(role => Object.values(current?.person_role_fields?.[role] || {})));
    const rendered = field => fieldInput(
      field,
      values[field.key],
      !editable || linkedKeys.has(field.key) || field.editable === false || !correctionAllows('field', field.key),
    );
    const first = fields.filter(field => String(field.key || '').startsWith('guarantor_1_'));
    const second = fields.filter(field => String(field.key || '').startsWith('guarantor_2_'));
    if (!first.length && !second.length) return `<div class="laf-grid">${fields.map(rendered).join('')}</div>`;
    const other = fields.filter(field => !first.includes(field) && !second.includes(field));
    const card = (title, hint, items, optional) => items.length
      ? `<fieldset class="guarantor-card${optional ? ' is-optional' : ''}"${optional ? ' data-guarantor-two-card' : ''}><legend><span><strong>${title}</strong><small>${hint}</small></span>${optional && editable ? '<button type="button" class="btn btn-secondary" data-clear-guarantor-two>Clear Guarantor 2</button>' : ''}</legend><div class="laf-grid">${items.map(rendered).join('')}</div></fieldset>`
      : '';
    const linkControl = role => {
      if (current?.value_contract_version !== 2 || !editable || current.status !== 'draft' || !current.person_role_fields?.[role]) return '';
      const sources = ['spouse', 'next_of_kin', 'referee'].filter(source => Object.keys(current.person_role_fields?.[source] || {}).length === 3);
      return sources.length ? `<label class="laf-field"><span>${role === 'guarantor_1' ? 'Guarantor 1' : 'Guarantor 2'} is</span><select data-person-link="${role}"><option value="">A separate person</option>${sources.map(source => `<option value="${source}"${linked[role] === source ? ' selected' : ''}>${escapeHtml(source.replaceAll('_', ' '))}</option>`).join('')}</select></label>` : '';
    };
    return `<div class="guarantor-groups">${linkControl('guarantor_1')}${card('Guarantor 1', 'Required guarantor', first, false)}${linkControl('guarantor_2')}${card('Guarantor 2', 'Optional unless any details are entered', second, true)}${other.length ? `<div class="laf-grid">${other.map(rendered).join('')}</div>` : ''}</div>`;
  }

  function updateCommercialQuoteDisplay() {
    const container = document.getElementById('commercial-quote');
    if (!container) return;
    const holder = document.createElement('div');
    holder.innerHTML = commercialQuoteMarkup();
    container.replaceWith(holder.firstElementChild);
  }

  function scheduleCommercialQuotePreview() {
    if (Number(current?.form_schema?.commercial_contract_version || 0) < 2) return;
    window.clearTimeout(commercialQuoteTimer);
    const payload = collectPayload();
    const amount = String(payload.loan_amount ?? '').trim();
    const tenor = String(payload.repayment_tenor ?? '').trim();
    if (!amount || !tenor) {
      commercialQuoteState = null;
      updateCommercialQuoteDisplay();
      return;
    }
    commercialQuoteState = { loading: true, quote: null, findings: [] };
    updateCommercialQuoteDisplay();
    const generation = ++commercialQuoteGeneration;
    commercialQuoteTimer = window.setTimeout(async () => {
      const result = await apiFetch(`/applications/${current.id}/quote-preview/`, {
        method: 'POST',
        body: JSON.stringify({
          revision: current.revision,
          loan_amount: amount,
          repayment_tenor: tenor,
        }),
      });
      if (generation !== commercialQuoteGeneration) return;
      if (!result.ok) {
        commercialQuoteState = {
          loading: false, quote: null,
          findings: [{ message: result.data?.error || 'The quote could not be calculated.' }],
        };
      } else {
        commercialQuoteState = {
          loading: false,
          quote: result.data.quote || {},
          findings: result.data.readiness?.blocking_findings || [],
        };
      }
      updateCommercialQuoteDisplay();
    }, 350);
  }

  function correctionToggle(targetType, targetKey, targetLabel, actionLabel = 'Flag for correction') {
    if (!capabilities.can_review) return '';
    const identity = `${targetType}:${targetKey}`;
    const selected = reviewTargets.get(identity);
    return `<span class="correction-control"><span class="correction-toggle"><input type="checkbox" data-correction-target="${escapeHtml(identity)}" data-target-type="${escapeHtml(targetType)}" data-target-key="${escapeHtml(targetKey)}" data-target-label="${escapeHtml(targetLabel)}"${selected ? ' checked' : ''}><span>${escapeHtml(actionLabel)}</span></span><input class="correction-inline-note" data-correction-instruction="${escapeHtml(identity)}" maxlength="1000" value="${escapeHtml(selected?.instruction || '')}" placeholder="Tell the officer exactly what to correct"${selected ? '' : ' hidden disabled'}></span>`;
  }

  function locationMatch(items, value) {
    const target = String(value ?? '').trim().toLowerCase();
    return (items || []).find(item => [item.code, item.name, ...(item.aliases || [])].some(candidate => String(candidate || '').toLowerCase() === target));
  }

  function originationCounties() {
    const counties = locationCatalog.counties || [];
    const branch = locationMatch(locationCatalog.branches, current?.branch);
    const areas = branch ? (locationCatalog.branch_service_areas?.[branch.code] || []) : [];
    if (!areas.length) return counties;
    return counties.filter(county => areas.includes(county.code) || (county.sub_counties || []).some(item => areas.includes(item.code)));
  }

  function locationSelectOptions(items, value) {
    const selected = locationMatch(items, value);
    return (items || []).map(item => `<option value="${escapeHtml(item.code)}"${selected?.code === item.code ? ' selected' : ''}>${escapeHtml(item.name)}</option>`).join('');
  }

  function syncOriginationSubCountySelect(event) {
    root()?.querySelectorAll('[data-location-type="sub_county"]').forEach(subCountySelect => {
      const parentKey = JSON.parse(subCountySelect.dataset.ruleField || '{}').validation?.parent_field;
      const countySelect = parentKey ? root()?.querySelector(`[data-field="${CSS.escape(parentKey)}"], [data-document-field="${CSS.escape(parentKey)}"]`)
        : root()?.querySelector('[data-location-type="county"]');
      if (!countySelect || event?.target && event.target !== countySelect) return;
      const county = locationMatch(originationCounties(), countySelect.value);
      let items = county?.sub_counties || [];
      const branch = locationMatch(locationCatalog.branches, current?.branch);
      const areas = branch ? (locationCatalog.branch_service_areas?.[branch.code] || []) : [];
      if (areas.length && !areas.includes(county?.code)) items = items.filter(item => areas.includes(item.code));
      subCountySelect.innerHTML = `<option value="">Choose sub-county</option>${locationSelectOptions(items, '')}`;
    });
  }

  function ruleAttributes(field) {
    return ` data-rule-field="${escapeHtml(JSON.stringify({type: field.type, validation: field.validation || {}, options: field.options || []}))}"`;
  }

  function fieldInput(field, value, disabled, documentContext = null, readOnly = false) {
    const key = escapeHtml(field.key);
    const label = escapeHtml(normalizeLabel(field));
    const classes = `laf-field miniapp-aligned-field${field.width === 'full' || FULL_WIDTH.has(field.key) ? ' laf-field-wide' : ''}`;
    const required = field.required ? '<span class="required-mark" aria-label="required">*</span>' : '';
    let control = '';
    if (readOnly && field.type !== 'repeating_group') {
      const prefix = field.type === 'money' ? '<span class="input-prefix">KES</span>' : '';
      control = `<div class="input-wrap${prefix ? ' has-prefix' : ''}">${prefix}<input data-reused-field="${key}" type="text" readonly aria-readonly="true" value="${escapeHtml(readOnlyFieldValue(field,value))}" placeholder="Not entered"></div>`;
    } else if (field.type === 'repeating_group') {
      const structure = field.structure || {};
      const columns = structure.columns || [];
      const rows = Array.isArray(value) ? value : [];
      const maxItems = Number(structure.max_items || 20);
      const policyBound = field.key === 'loan_fees';
      const itemLabel = repeatableItemLabel(field);
      const binding = readOnly ? `data-readonly-repeatable="${key}"` : `data-repeatable-field="${key}" data-main-repeatable="${key}"`;
      control = `<div class="repeatable-field" ${binding} data-repeatable-grid="${escapeHtml(repeatableGridStyle(field))}" data-max-items="${maxItems}" data-item-label="${escapeHtml(itemLabel)}"><div class="repeatable-rows">${rows.map((row, index) => repeatableRowMarkup(columns, row, index, disabled, policyBound, itemLabel, repeatableGridStyle(field))).join('')}</div>${policyBound || readOnly ? '' : `<div class="repeatable-summary"><button type="button" class="btn btn-secondary" data-repeat-add${disabled || rows.length >= maxItems ? ' disabled' : ''}>Add ${escapeHtml(itemLabel.toLowerCase())}</button></div>`}</div>`;
    } else if (field.type === 'branch') {
      const branch = locationMatch(locationCatalog.branches, current?.branch);
      control = `<select data-field="${key}" data-location-type="branch" disabled><option value="">Choose</option>${locationSelectOptions(branch ? [branch] : [], value || current?.branch)}</select>`;
    } else if (field.type === 'county') {
      const counties = originationCounties();
      control = `<select data-field="${key}" data-location-type="county"${disabled ? ' disabled' : ''}><option value="">Choose county</option>${locationSelectOptions(counties, value)}</select>`;
    } else if (field.type === 'sub_county') {
      const schemaFields = documentContext?.schema?.fields || current?.form_schema?.fields || [];
      const parentKey = field.validation?.parent_field;
      const countyField = schemaFields.find(item => item.type === 'county' && (!parentKey || item.key === parentKey));
      const countyValue = root()?.querySelector(`[data-field="${CSS.escape(countyField?.key || '')}"], [data-document-field="${CSS.escape(countyField?.key || '')}"]`)?.value
        ?? documentContext?.field_payload?.[countyField?.key] ?? current?.form_payload?.[countyField?.key];
      const county = locationMatch(originationCounties(), countyValue);
      let items = county?.sub_counties || [];
      const branch = locationMatch(locationCatalog.branches, current?.branch);
      const areas = branch ? (locationCatalog.branch_service_areas?.[branch.code] || []) : [];
      if (areas.length && !areas.includes(county?.code)) items = items.filter(item => areas.includes(item.code));
      control = `<select data-field="${key}" data-location-type="sub_county"${disabled ? ' disabled' : ''}><option value="">Choose sub-county</option>${locationSelectOptions(items, value)}</select>`;
    } else if (field.type === 'choice') {
      const options = (field.options || []).filter(option => option?.active !== false).map(option => {
        const code = option && typeof option === 'object' ? option.code : option;
        const label = option && typeof option === 'object' ? (option.label || option.code) : option;
        return `<option value="${escapeHtml(code)}"${value === code ? ' selected' : ''}>${escapeHtml(label)}</option>`;
      }).join('');
      control = `<select data-field="${key}"${disabled ? ' disabled' : ''}><option value="">Choose</option>${options}</select>`;
    } else if (field.type === 'boolean') {
      control = `<select data-field="${key}"${disabled ? ' disabled' : ''}><option value="">Choose</option><option value="true"${value === true ? ' selected' : ''}>Yes</option><option value="false"${value === false ? ' selected' : ''}>No</option></select>`;
    } else if (field.type === 'textarea') {
      const validation = field.validation || {};
      control = `<textarea data-field="${key}"${validation.min_length != null ? ` minlength="${escapeHtml(validation.min_length)}"` : ''}${validation.max_length != null ? ` maxlength="${escapeHtml(validation.max_length)}"` : ''}${validation.pattern ? ` pattern="${escapeHtml(validation.pattern)}"` : ''}${disabled ? ' disabled' : ''}>${escapeHtml(value ?? '')}</textarea>`;
    } else {
      const type = field.type === 'phone' ? 'tel' : field.validation?.format === 'email' ? 'email' : field.type === 'date' ? 'date' : field.type === 'datetime' ? 'datetime-local' : 'text';
      const prefix = field.type === 'money' ? '<span class="input-prefix">KES</span>' : '';
      const validation = field.validation || {};
      const numeric = field.type === 'money' ? ` inputmode="numeric" data-numeric-input${field.source_type === 'system' ? '' : ' data-money-input'} data-min="${escapeHtml(validation.min ?? '')}" data-max="${escapeHtml(validation.max ?? '')}"` : field.type === 'number' ? ` inputmode="${validation.integer ? 'numeric' : 'decimal'}" data-numeric-input data-min="${escapeHtml(validation.min ?? '')}" data-max="${escapeHtml(validation.max ?? '')}"` : '';
      const identifierRules = field.type === 'national_id'
        ? ' maxlength="9" pattern="[0-9]{1,9}" inputmode="numeric"'
        : field.type === 'phone' ? ' inputmode="tel"' : '';
      const textRules = ['text', 'textarea', 'phone', 'national_id'].includes(field.type) ? `${validation.min_length != null ? ` minlength="${escapeHtml(validation.min_length)}"` : ''}${validation.max_length != null && field.type !== 'national_id' ? ` maxlength="${escapeHtml(validation.max_length)}"` : ''}${validation.pattern && field.type !== 'national_id' ? ` pattern="${escapeHtml(validation.pattern)}"` : ''}${identifierRules}` : '';
      const dobMin = field.key === 'applicant_dob' ? isoDate(new Date(new Date().getFullYear() - 120, 0, 1)) : '';
      const dobMax = field.key === 'applicant_dob' || validation.no_future ? (window.OriginationFieldRules?.today() || isoDate(new Date())) : '';
      const dateRules = field.type === 'date' ? `${validation.min_date || dobMin ? ` min="${escapeHtml(validation.min_date || dobMin)}"` : ''}${validation.max_date || dobMax ? ` max="${escapeHtml(validation.max_date || dobMax)}"` : ''}` : '';
      const input = field.type === 'date'
        ? nativeDateControl(`data-field="${key}"${field.required ? ' required' : ''}`, value, disabled, dateRules)
        : `<input data-field="${key}" type="${type}" value="${escapeHtml(value ?? '')}"${field.required ? ' required' : ''}${numeric}${textRules}${disabled ? ' disabled' : ''}>`;
      control = `<div class="input-wrap${prefix ? ' has-prefix' : ''}">${prefix}${input}</div>`;
    }
    if (field.type !== 'repeating_group' && !readOnly) {
      control = control.replace(/<(input|select|textarea)\b/g, match => match + ruleAttributes(field) + (field.required ? ' aria-required="true"' : ''));
    }
    const identifierHelp = field.type === 'national_id' ? '' : '';
    const otherRequired = (field.required_by || []).includes('primary') ? [] : (field.required_by || []);
    const requiredDocuments = (current.document_packet?.documents || [])
      .filter(document => otherRequired.includes(document.key)).map(document => document.name).filter(Boolean);
    const requirementHelp = otherRequired.length
      ? requiredDocuments.length === 1 && requiredDocuments[0].length <= 50
        ? `Required for ${requiredDocuments[0]}` : 'Required by a supporting document'
      : '';
    const helpText = readOnly ? '' : [field.help_text, identifierHelp, requirementHelp].filter(Boolean).join(' ');
    const help = helpText ? `<small class="field-help">${escapeHtml(helpText)}</small>` : '';
    const correction = !readOnly && ['ready_for_review', 'signed_pending_approval'].includes(current.status)
      ? documentContext ? correctionToggle('document_field', `${documentContext.key}.${field.key}`, `${documentContext.name}: ${field.label || field.key}`)
        : correctionToggle('field', field.key, normalizeLabel(field)) : '';
    const wrapperTag = field.type === 'repeating_group' ? 'div' : 'label';
    const fieldId = `laf-${documentContext?.key || 'main'}-${key}`;
    if (field.type !== 'repeating_group') control = control.replace(/<(input|select|textarea)\b/, match => `${match} id="${fieldId}" aria-describedby="${fieldId}-feedback"`);
    return `<${wrapperTag} class="${classes}" ${readOnly ? 'data-reused-wrap' : 'data-field-wrap'}="${key}"><span class="field-label miniapp-field-caption">${label}${required}</span><div class="field-control">${control}</div><div class="field-feedback miniapp-field-feedback" id="${fieldId}-feedback">${help}${correction}</div></${wrapperTag}>`;
  }

  function readOnlyFieldValue(field, value) {
    const empty = value === '' || value == null;
    let display = empty ? '' : value;
    if (field.type === 'choice') {
      const option = (field.options || []).find(item => String(item?.code ?? item) === String(value));
      display = option?.label || option?.code || display;
    } else if (field.type === 'boolean' && !empty) display = value === true || value === 'true' ? 'Yes' : 'No';
    else if (field.type === 'date' && !empty) display = formatKenyanDate(value);
    else if (field.type === 'datetime' && !empty) display = new Date(value).toLocaleString('en-KE', {timeZone:'Africa/Nairobi'});
    return display;
  }

  function numericInputError(input) {
    if (input?.dataset?.ruleField && input.value !== '') {
      const field = JSON.parse(input.dataset.ruleField);
      const value = field.type === 'boolean' ? input.value === 'true'
        : ['money', 'number'].includes(field.type) ? normalizeNumericText(input.value) : input.value;
      const message = window.OriginationFieldRules?.validate(field, value) || '';
      if (message) return message;
    }
    if (!input?.matches?.('[data-numeric-input]') || input.value === '') return '';
    const normalized = normalizeNumericText(input.value);
    if (!/^-?(?:\d+|\d*\.\d+)$/.test(normalized)) return 'Enter a valid number.';
    if (input.hasAttribute('data-money-input') && !/^-?\d+$/.test(normalized)) return 'Enter a whole KES amount without decimal places.';
    const value = Number(normalized);
    const min = input.dataset.min === '' ? null : Number(input.dataset.min);
    const max = input.dataset.max === '' ? null : Number(input.dataset.max);
    if (min != null && value < min) return `Enter ${min} or more.`;
    if (max != null && value > max) return `Enter ${max} or less.`;
    return '';
  }

  function visibleDraftNumericErrors() {
    const errors = {};
    root()?.querySelectorAll('[data-numeric-input], [data-rule-field]').forEach(input => {
      const message = numericInputError(input);
      if (!message) return;
      const wrapper = input.closest('[data-field-wrap], [data-product-wrap]');
      const key = wrapper?.dataset.fieldWrap || wrapper?.dataset.productWrap;
      if (!key || errors[key]) return;
      const row = input.closest('[data-repeat-row]');
      const rows = row ? [...row.parentElement.querySelectorAll(':scope > [data-repeat-row]')] : [];
      const rowNumber = row ? rows.indexOf(row) + 1 : 0;
      errors[key] = rowNumber > 0 ? `${message} Row ${rowNumber}.` : message;
    });
    return errors;
  }

  function sectionErrors(sectionKey) {
    if (sectionKey.startsWith('document:')) {
      const document = (current?.document_packet?.documents || []).find(
        item => item.key === sectionKey.slice('document:'.length),
      );
      const errors = {};
      (document?.schema?.fields || []).filter(field => field.source_type !== 'system'
        && documentOwnsInput(field, document)
        && field.editable !== false).forEach(field => {
        if (field.type === 'repeating_group') {
          const container = root()?.querySelector(`[data-repeatable-field="${CSS.escape(field.key)}"]`);
          const rows = container ? [...container.querySelectorAll('[data-repeat-row]')] : (document.field_payload?.[field.key] || []);
          const structure = field.structure || {};
          const minimum = Number(structure.min_items || 0);
          const maximum = Number(structure.max_items || 0);
          if (field.required && rows.length < Math.max(minimum, 1)) errors[field.key] = `Add at least ${Math.max(minimum, 1)} asset`;
          if (maximum && rows.length > maximum) errors[field.key] = `Add no more than ${maximum} assets`;
          rows.forEach((row, index) => container ? row.querySelectorAll('[data-repeat-column]').forEach(input => {
            if (!errors[field.key] && input.required && !input.value.trim()) errors[field.key] = `Complete row ${index + 1}`;
            if (!errors[field.key] && numericInputError(input)) errors[field.key] = `${numericInputError(input)} Row ${index + 1}.`;
          }) : (structure.columns || []).forEach(column => {
            if (!errors[field.key] && column.required && (row[column.key] === undefined || row[column.key] === '')) errors[field.key] = `Complete row ${index + 1}`;
            const message = window.OriginationFieldRules?.validate(column,row[column.key]);
            if (!errors[field.key] && message) errors[field.key] = `${message} Row ${index + 1}.`;
          }));
          return;
        }
        const input = root()?.querySelector(`[data-document-field="${CSS.escape(field.key)}"]`);
        const value = input?.value ?? document.field_payload?.[field.key] ?? current.form_payload?.[field.key];
        if (field.required && (value === undefined || value === null || value === '')) errors[field.key] = 'Required';
        if (!errors[field.key] && numericInputError(input)) errors[field.key] = numericInputError(input);
        if (!errors[field.key] && input && !input.checkValidity()) errors[field.key] = input.validationMessage || 'Enter a valid value.';
      });
      return errors;
    }
    if (sectionKey === 'product_requirements') {
      const terms = current?.product_terms || {};
      const values = collectProductConfiguration();
      const errors = {};
      (terms.requirements || []).filter(item => item.required && item.enforcement_stage === 'review' && (!item.workflow || item.workflow === 'loan_origination')).forEach(item => {
        if (item.type === 'document') {
          const uploaded = (current?.requirement_evidence || []).some(file => file.requirement_key === item.key && file.status === 'uploaded');
          if (!uploaded) errors[`requirement:${item.key}`] = 'Upload required evidence';
        } else {
          const value = values.requirements[item.key];
          if (value === undefined || value === null || value === '' || value === false) errors[`requirement:${item.key}`] = 'Required';
        }
      });
      (terms.custom_attributes || []).filter(item => item.required && (!(item.workflows || []).length || item.workflows.includes('loan_origination'))).forEach(item => {
        const value = values.customValues[item.key];
        if (value === undefined || value === null || value === '') errors[`custom:${item.key}`] = 'Required';
      });
      root()?.querySelectorAll('[data-product-requirement], [data-product-custom]').forEach(input => {
        const key = input.dataset.productRequirement
          ? `requirement:${input.dataset.productRequirement}`
          : `custom:${input.dataset.productCustom}`;
        const numericError = numericInputError(input);
        if (numericError) { errors[key] ||= numericError; return; }
        if (input.checkValidity()) return;
        errors[key] ||= input.validationMessage || 'Enter a valid value.';
      });
      return errors;
    }
    const payload = collectPayload();
    const errors = {};
    fieldsFor(sectionKey).forEach(field => {
      const value = payload[field.key];
      if (field.type === 'repeating_group') {
        const rows = Array.isArray(value) ? value : [];
        const structure = field.structure || {};
        const minimum = Number(structure.min_items || 0);
        const maximum = Number(structure.max_items || 0);
        if (field.required && rows.length < Math.max(1, minimum)) errors[field.key] = `Add at least ${Math.max(1, minimum)} item`;
        if (maximum && rows.length > maximum) errors[field.key] = `Add no more than ${maximum} items`;
        rows.forEach((row, index) => (structure.columns || []).forEach(column => {
          if (!errors[field.key] && column.required && !String(row?.[column.key] ?? '').trim()) errors[field.key] = `Complete ${column.label || column.key} in row ${index + 1}`;
          const message = window.OriginationFieldRules?.validate(column, row?.[column.key]);
          if (!errors[field.key] && message) errors[field.key] = `${message} Row ${index + 1}.`;
        }));
        const container = root()?.querySelector(`[data-main-repeatable="${CSS.escape(field.key)}"]`);
        [...(container?.querySelectorAll('[data-repeat-column]') || [])].forEach((input, index) => {
          if (!errors[field.key] && numericInputError(input)) errors[field.key] = `${numericInputError(input)} Row ${Math.floor(index / Math.max((structure.columns || []).length, 1)) + 1}.`;
        });
        return;
      }
      if (field.required && (value === undefined || value === null || value === '')) errors[field.key] = 'Required';
      const input = root()?.querySelector(`[data-field="${CSS.escape(field.key)}"]`);
      const numericError = numericInputError(input);
      if (!errors[field.key] && numericError) errors[field.key] = numericError;
      if (!errors[field.key] && input && !input.checkValidity()) {
        errors[field.key] = input.validationMessage || 'Enter a valid value.';
      }
    });
    return errors;
  }

  function originationErrorControl(key) {
    const activeDocument = wizardSections()[step]?.document;
    if (activeDocument && key.startsWith(`${activeDocument.key}.`)) key = key.slice(activeDocument.key.length + 1);
    const wrappers = [...(root()?.querySelectorAll('[data-field-wrap], [data-product-wrap]') || [])];
    const wrapper = wrappers.find(item => item.dataset.fieldWrap === key || item.dataset.productWrap === key
      || key.startsWith(`${item.dataset.fieldWrap}.`));
    if (!wrapper) return null;
    const rowIndex = key.match(/\.(\d+)\./);
    const row = rowIndex ? wrapper.querySelectorAll('[data-repeat-row]')[Number(rowIndex[1])] : null;
    const column = key.split('.').at(-1);
    return (row && [...row.querySelectorAll('[data-repeat-column]')].find(input => input.dataset.repeatColumn === column))
      || (row || wrapper).querySelector('input,select,textarea,button');
  }

  function showErrors(errors, focus = true) {
    const controller = window.MiniAppUtils?.bindAccessibleForm?.(root(), {
      resolveField: originationErrorControl,
      isFieldError: key => originationErrorSection(key) >= 0,
      validate: () => sectionErrors(wizardSections()[step]?.key || ''),
      focusField: key => {
        const index = originationErrorSection(key);
        if (index < 0) return false;
        current.form_payload = collectPayload();
        const configuration = collectProductConfiguration();
        current.product_requirements = configuration.requirements;
        current.product_custom_values = configuration.customValues;
        if (root().querySelector('[data-product-fee]')) current.product_selected_fee_keys = configuration.selectedFeeKeys;
        const activeDocument = wizardSections()[step]?.document;
        if (activeDocument) activeDocument.field_payload = collectSupportingDocumentPayload(activeDocument);
        renderEditor(current, index);
        showErrors(errors, false);
        originationErrorControl(key)?.focus();
        return true;
      },
    });
    if (!controller) return;
    const readable = Object.fromEntries(Object.entries(errors || {}).map(([key, message]) => {
      const control = originationErrorControl(key);
      const wrapper = control?.closest('[data-field-wrap], [data-product-wrap]');
      const label = wrapper?.firstElementChild?.textContent?.replace(/\*/g, '').trim() || 'this field';
      return [key, message === 'Required' ? `Complete ${label.toLowerCase()}.` : message];
    }));
    controller.show(readable, focus);
  }

  function validateSubmission() {
    const errors = {};
    for (const section of wizardSections()) {
      if (section.key !== 'review') Object.assign(errors, sectionErrors(section.key));
    }
    if (!Object.keys(errors).length) return true;
    const first = Object.keys(errors)[0];
    const index = originationErrorSection(first);
    if (index >= 0 && index !== step) {
      current.form_payload = collectPayload();
      renderEditor(current,index);
    }
    showErrors(errors);
    showToast('Check the highlighted fields before submitting.', 'warning');
    return false;
  }

  function originationErrorSection(key) {
    const sharedField = (current?.form_schema?.fields || []).find(field => key === field.key || key.startsWith(`${field.key}.`));
    if (sharedField) return wizardSections().findIndex(section => section.key === inputSectionKey(sharedField));
    return wizardSections().findIndex(section => {
      if (key.startsWith('requirement:') || key.startsWith('custom:')) return section.key === 'product_requirements';
      if (section.document && key.startsWith(`${section.document.key}.`)) return true;
      const fields = section.document ? section.document.schema.fields.filter(field => documentOwnsInput(field, section.document)) : fieldsFor(section.key);
      return fields.some(field => key === field.key || key.startsWith(`${field.key}.`));
    });
  }

  function showServerErrors(errors) {
    if (!errors || typeof errors !== 'object') return;
    const firstKey = Object.keys(errors)[0];
    if (!firstKey) return;
    serverValidationErrorsVisible = true;
    const sections = wizardSections();
    let targetStep = originationErrorSection(firstKey);
    if (firstKey.startsWith('requirement:') || firstKey.startsWith('custom:')) {
      targetStep = sections.findIndex(section => section.key === 'product_requirements');
    }
    if (targetStep >= 0 && targetStep !== step) renderEditor(current, targetStep);
    showErrors(errors);
  }

  async function saveDraft(showError) {
    if (draftSaveOperation) {
      const saved = await draftSaveOperation;
      return saved && dirty ? saveDraft(showError) : saved;
    }
    draftSaveOperation = performDraftSave(showError);
    try { return await draftSaveOperation; }
    finally { draftSaveOperation = null; }
  }

  async function performDraftSave(showError) {
    if (!current || !['draft', 'correction_required'].includes(current.status)) return true;
    if (!dirty) return true;
    if (syncConflict) {
      if (showError) showToast('Resolve the saved-draft conflict before continuing.', true);
      return false;
    }
    if (saveInFlight) {
      const waitingForRequestId = saveInFlightRequestId;
      await saveInFlight;
      if (waitingForRequestId && lastFailedSaveRequestId === waitingForRequestId) return false;
      return dirty ? performDraftSave(showError) : true;
    }
    const applicationId = current.id;
    const revision = current.revision;
    const generation = editGeneration;
    const payload = collectPayload();
    const activeDocument = wizardSections()[step]?.document;
    const documentKey = activeDocument?.key || '';
    const documentPayload = activeDocument ? collectSupportingDocumentPayload(activeDocument) : null;
    const configuration = collectProductConfiguration();
    const numericErrors = visibleDraftNumericErrors();
    if (Object.keys(numericErrors).length) {
      setSaveState(recoveryAvailable ? 'Waiting for a valid value - encrypted on phone' : 'Waiting for a valid value', 'dirty');
      if (showError) showErrors(numericErrors);
      return false;
    }
    pendingSaveRequestId ||= requestKey('save');
    const key = pendingSaveRequestId;
    const attemptedDraft = {
      applicationId,
      revision, payload, configuration, documentKey, documentPayload, requestId: key,
      generation, savedAt: Date.now(),
    };
    await persistRecoveryDraft(applicationId, attemptedDraft);
    setSaveState('Saving…', 'saving');
    saveInFlightRequestId = key;
    saveInFlight = apiFetch(documentKey ? `/applications/${applicationId}/documents/${encodeURIComponent(documentKey)}/fields/` : `/applications/${applicationId}/`, {
      method: documentKey ? 'POST' : 'PATCH', headers: { 'Idempotency-Key': key, 'X-Request-ID': key },
      body: JSON.stringify(documentKey ? {revision, payload:documentPayload, request_id:key} : {
        revision,
        form_payload: payload,
        product_requirement_evidence: configuration.requirements,
        product_custom_values: configuration.customValues,
        product_selected_fee_keys: configuration.selectedFeeKeys,
        request_id: key,
      }),
    });
    syncCloseProtection();
    const result = await saveInFlight;
    saveInFlight = null;
    saveInFlightRequestId = '';
    syncCloseProtection();
    if (!result.ok || !result.data?.ok) {
      if (result.status === 409 || result.data?.code === 'revision_conflict' || result.data?.conflict) {
        let phoneDraft = attemptedDraft;
        if (editGeneration !== generation) {
          pendingSaveRequestId = requestKey('save');
          phoneDraft = {
            applicationId,
            revision, documentKey,
            documentPayload: activeDocument ? collectSupportingDocumentPayload(activeDocument) : null,
            payload: collectPayload(),
            configuration: collectProductConfiguration(),
            requestId: pendingSaveRequestId,
            generation: editGeneration,
            savedAt: Date.now(),
            attemptedSnapshot: attemptedDraft,
          };
          await persistRecoveryDraft(applicationId, phoneDraft);
        }
        return reconcileSavedDraftConflict(phoneDraft, showError);
      }
      lastFailedSaveRequestId = key;
      pendingSaveRequestId = requestKey('save');
      setSaveState(recoveryAvailable ? 'Encrypted on phone' : 'Not saved offline', 'offline');
      if (result.data?.errors) showServerErrors(result.data.errors);
      if (showError) showToast(
        result.data?.error || (recoveryAvailable
          ? 'Draft remains encrypted on this phone. Reconnect and try again.'
          : 'Could not save. Keep this screen open and retry.'),
        true,
      );
      return false;
    }
    const changedWhileSaving = editGeneration !== generation;
    const latestPayload = changedWhileSaving ? collectPayload() : null;
    const latestDocumentPayload = changedWhileSaving && activeDocument ? collectSupportingDocumentPayload(activeDocument) : null;
    const latestConfiguration = changedWhileSaving ? collectProductConfiguration() : null;
    current = result.data.application;
    previewedRevision = null;
    lastFailedSaveRequestId = '';
    if (serverValidationErrorsVisible) {
      showErrors({});
      serverValidationErrorsVisible = false;
    }
    if (changedWhileSaving) {
      current.form_payload = latestPayload;
      restoreDocumentDraft({documentKey, documentPayload:latestDocumentPayload});
      current.product_requirements = latestConfiguration.requirements;
      current.product_custom_values = latestConfiguration.customValues;
      current.product_selected_fee_keys = latestConfiguration.selectedFeeKeys;
      dirty = true;
      syncCloseProtection();
      setSaveState('Saving newer changes…', 'saving');
      return performDraftSave(showError);
    }
    pendingSaveRequestId = '';
    dirty = false;
    syncCloseProtection();
    await removeRecoveryDraft(applicationId);
    setSaveState('Saved', 'saved');
    refreshHeaderContacts();
    if (showError) showToast('Changes saved.', 'success');
    return true;
  }

  function setSaveState(text, state) {
    const element = document.getElementById('origination-save-status');
    if (element) {
      element.textContent = state === 'saved' ? 'Saved' : state === 'dirty' ? 'Not saved'
        : state === 'offline' ? 'Not saved · retry' : text.startsWith('Uploading') ? text : 'Saving…';
      element.dataset.state = state;
    }
  }

  function scheduleSave() {
    dirty = true;
    syncCloseProtection();
    editGeneration += 1;
    if (saveInFlight) pendingSaveRequestId = requestKey('save');
    else pendingSaveRequestId ||= requestKey('save');
    setSaveState('Unsaved changes', 'dirty');
    window.clearTimeout(saveTimer);
    saveTimer = window.setTimeout(() => saveDraft(false), 900);
    const payload = collectPayload();
    const activeDocument = wizardSections()[step]?.document;
    const configuration = collectProductConfiguration();
    void persistRecoveryDraft(current.id, {
      revision: current.revision,
      payload,
      documentKey:activeDocument?.key || '',
      documentPayload:activeDocument ? collectSupportingDocumentPayload(activeDocument) : null,
      configuration,
      requestId: pendingSaveRequestId,
      generation: editGeneration,
      savedAt: Date.now(),
    }).then(saved => {
      if (!saved && dirty) setSaveState('Server-only draft', 'offline');
    });
  }

  function preserveDraftOnExit() {
    if (!current || !dirty || syncConflict || !['draft', 'correction_required'].includes(current.status)) return;
    window.clearTimeout(saveTimer);
    pendingSaveRequestId ||= requestKey('save');
    const payload = collectPayload();
    const activeDocument = wizardSections()[step]?.document;
    const configuration = collectProductConfiguration();
    const key = pendingSaveRequestId;
    void persistRecoveryDraft(current.id, {
      revision: current.revision,
      payload,
      documentKey:activeDocument?.key || '',
      documentPayload:activeDocument ? collectSupportingDocumentPayload(activeDocument) : null,
      configuration,
      requestId: key,
      generation: editGeneration,
      savedAt: Date.now(),
    });
    setSaveState('Saved on device', 'offline');
  }

  async function resumeDraftSynchronization() {
    if (document.visibilityState === 'hidden') return false;
    if (!current) {
      await loadApplications();
      return true;
    }
    if (!dirty || syncConflict || !['draft', 'correction_required'].includes(current.status)) return true;
    return saveDraft(false);
  }

  function progressMarkup() {
    const sections = wizardSections();
    const section = sections[step];
    const percent = Math.round(((step + 1) / sections.length) * 100);
    return `<div class="wizard-progress-compact"><div class="wizard-section-row"><button type="button" class="icon-button" id="section-previous" aria-label="Previous section" ${step === 0 ? 'disabled' : ''}>${iconSvg('arrowLeft')}</button><button type="button" id="origination-section-picker" class="wizard-progress-trigger" aria-label="Choose application section"><span><small>${step + 1} / ${sections.length}</small><strong>${escapeHtml(section.label)}</strong></span>${iconSvg('chevronDown')}</button><button type="button" class="icon-button" id="section-next" aria-label="Next section" ${step === sections.length - 1 ? 'disabled' : ''}>${iconSvg('arrowRight')}</button></div><div class="wizard-progress-track" role="progressbar" aria-label="Application progress" aria-valuemin="1" aria-valuemax="${sections.length}" aria-valuenow="${step + 1}"><span style="width:${percent}%"></span></div></div>`;
  }

  function hasFinalSignedPacket() {
    const packageData = current?.signing_package;
    return ['fully_signed', 'signed_pending_approval', 'approved'].includes(current?.status)
      && Boolean(packageData?.id)
      && Boolean(packageData?.verified_signing?.signed_packet_available);
  }

  function hasCurrentSigningPacket() {
    return ['signing_pending', 'partially_signed'].includes(current?.status)
      && Boolean(current?.signing_package?.id)
      && !current?.signing_package?.test_signing?.test_mode;
  }

  function latestPreviewLabel(fallback) {
    if (hasFinalSignedPacket()) return 'Preview signed application';
    if (hasCurrentSigningPacket()) return 'Preview current documents';
    if (current?.review_packet_ready && ['ready_for_review', 'reviewed'].includes(current?.status)) {
      return current.status === 'reviewed' ? 'Preview documents' : 'Preview documents';
    }
    return fallback;
  }

  function resolveLatestPreviewKey(documentKey) {
    if (documentKey && !documentKey.startsWith('__') && hasFinalSignedPacket()) return documentKey;
    if (hasFinalSignedPacket()) return '__signed_packet__';
    if (hasCurrentSigningPacket()) return '__signing_packet__';
    if (current?.review_packet_ready && ['ready_for_review', 'reviewed'].includes(current?.status)) {
      return '__review_packet__';
    }
    return documentKey;
  }

  function reviewWorkflowMarkup() {
    if (!['ready_for_review', 'reviewed'].includes(current?.status)) return '';
    const packageData = current?.signing_package || {};
    if (current.status === 'ready_for_review' && !current.review_packet_ready) {
      return '<aside class="workflow-readiness is-waiting"><div><p class="eyebrow">Operations preparation</p><strong>Documents awaiting preparation</strong><span>The documents need to be prepared before review.</span></div></aside>';
    }
    if (current.status === 'ready_for_review') {
      return `<aside class="workflow-readiness is-ready"><div><p class="eyebrow">Checker final review</p><strong>Review the documents</strong><span>Review this saved copy before approving it for signing.</span></div><button type="button" class="btn btn-primary" id="origination-review-packet-preview">Preview documents</button></aside>`;
    }
    return `<aside class="workflow-readiness is-approved"><div><p class="eyebrow">Documents approved</p><strong>Approved by ${escapeHtml(packageData.reviewed_by_name || 'an authorized checker')}</strong><span>Operations may now start signing. Editing requires another review.</span></div><button type="button" class="btn btn-secondary" id="origination-review-packet-preview">Preview documents</button></aside>`;
  }

  function reviewMarkup(values) {
    const hasPacket = (current?.document_packet?.documents || []).filter(item => item.selected).length > 1;
    const signed = ['fully_signed', 'signed_pending_approval', 'approved'].includes(current?.status);
    const sectionAction = ['draft', 'correction_required'].includes(current?.status) ? 'Edit' : 'View';
    const reviewCards = ['fully_signed', 'approved'].includes(current?.status) ? '' : `<div class="review-sections">${wizardSections().slice(0, -1).map((section, index) => {
      if (section.key.startsWith('document:')) {
        const document = section.document;
        return `<button type="button" class="review-card" data-edit-step="${index}"><span><strong>${escapeHtml(document.name)}</strong><small>${document.complete ? 'Fields complete' : `${document.missing_fields?.length || 0} fields missing`} · ${document.previewed ? 'Previewed' : 'Preview required'}</small></span><span>Open ${iconSvg('arrowRight')}</span></button>`;
      }
      if (section.key === 'product_requirements') {
        const configuration = collectProductConfiguration();
        const completed = Object.values(configuration.requirements).filter(value => value !== '' && value != null && value !== false).length
          + Object.values(configuration.customValues).filter(value => value !== '' && value != null).length;
        const total = (current?.product_terms?.requirements || []).length + (current?.product_terms?.custom_attributes || []).length;
        return `<button type="button" class="review-card" data-edit-step="${index}"><span><strong>${escapeHtml(section.label)}</strong><small>${completed} of ${total} details completed</small></span><span>${sectionAction} ${iconSvg('arrowRight')}</span></button>`;
      }
      const fields = fieldsFor(section.key);
      const completed = fields.filter(field => values[field.key] !== '' && values[field.key] != null).length;
      return `<button type="button" class="review-card" data-edit-step="${index}"><span><strong>${escapeHtml(section.label)}</strong><small>${completed} of ${fields.length} fields completed</small></span><span>${sectionAction} ${iconSvg('arrowRight')}</span></button>`;
    }).join('')}</div>`;
    return `${reviewWorkflowMarkup()}<div class="review-intro"><div><p class="eyebrow">${signed ? 'Completed application' : 'Final check'}</p><h3>${signed ? 'Signed application' : 'Review the application'}</h3><p>${signed ? 'View the signed application below.' : current?.approval_roles?.length && sectionAction === 'View' ? 'Check the application and current signatures before approving.' : current?.review_packet_ready ? 'Review the documents and application details.' : 'Check the details, then preview the document bundle.'}</p></div><div class="review-preview-actions"><button type="button" class="btn btn-primary" id="origination-preview">${latestPreviewLabel(hasPacket ? 'Preview document bundle' : 'Preview main LAF')}</button></div></div>
      ${reviewCards}${signingTestMarkup()}`;
  }

  function signingTestMarkup() {
    const packageData = current?.signing_package;
    if (!packageData || !['signing_pending', 'partially_signed', 'fully_signed', 'signed_pending_approval', 'approved'].includes(current?.status)) return '';
    const test = packageData.test_signing || {};
    if (!test.enabled || !test.test_mode) {
      const verified = packageData.verified_signing || {};
      if (!verified.enabled || verified.test_mode) return '<aside class="notice"><strong>Signing package prepared</strong><span>Verified signing is disabled or not configured for this environment.</span></aside>';
      const stampOptions = (verified.production_stamps || []).map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)} v${escapeHtml(item.version)} · ${escapeHtml(item.scope)}</option>`).join('');
      const participants = (verified.participants || []).map(participant => {
        const signatures = (participant.slots || []).filter(slot => slot.type === 'signature');
        const stamps = (participant.slots || []).filter(slot => slot.type === 'stamp');
        const signaturesComplete = signatures.length && signatures.every(slot => slot.completed);
        const accessMode = participant.access_mode || 'self_service';
        const modeLabel = accessMode === 'assisted' ? 'Assisted signing' : 'Remote signing';
        const assistedFallback = `<details class="assisted-signing-fallback"><summary>In-person assisted signing</summary><p>Use only when the signer is physically present and personally controls the officer device and OTP.</p><button type="button" class="btn btn-secondary" data-create-signer-session data-access-mode="assisted" data-package-id="${escapeHtml(packageData.id)}" data-signer-role="${escapeHtml(participant.role)}">Sign on this officer device</button></details>`;
        const staffRoleAllowed = (capabilities.staff_signer_roles || []).includes(participant.role);
        const canDispatch = capabilities.can_create && (String(current.officer_id) === String(capabilities.user_id) || capabilities.is_superuser);
        const canStamp = current.approval_roles?.length ? capabilities.can_staff_sign && staffRoleAllowed : capabilities.can_start_signing;
        const approval = current.approval_sequence || {};
        const isApprover = (current.approval_roles || []).includes(participant.role);
        const canApprove = approval.approval_ready && approval.next_approver === participant.role;
        const reviewed = approvalReview?.packageId === packageData.id && approvalReview?.revision === current.revision && approvalReview?.version === verified.packet_version;
        const externalAction = participant.staff && capabilities.can_staff_sign && staffRoleAllowed
          ? isApprover && !canApprove
            ? '<span class="status-chip">Awaiting signatures</span>'
            : isApprover && !reviewed
              ? '<button type="button" class="btn btn-primary" data-approval-preview>Review documents</button>'
              : `<button type="button" class="btn ${isApprover ? 'btn-primary' : 'btn-secondary'}" data-staff-sign data-package-id="${escapeHtml(packageData.id)}" data-signer-role="${escapeHtml(participant.role)}">${isApprover ? 'Approve &amp; sign' : 'Sign documents'}</button>`
          : participant.staff
            ? '<span class="status-chip">Awaiting authorized staff</span>'
          : current.approval_roles?.length && !canDispatch
            ? `<span class="status-chip">${escapeHtml((participant.session_status || 'Awaiting signer').replaceAll('_', ' '))}</span>`
          : participant.session_status
            ? `<div class="signing-session-actions"><span class="signing-mode-chip ${escapeHtml(accessMode)}">${escapeHtml(modeLabel)}</span><span class="status-chip">${escapeHtml(participant.session_status.replaceAll('_', ' '))}</span>${participant.session_status === 'verified' ? '' : `<button type="button" class="btn btn-secondary" data-reset-signer-session data-session-id="${escapeHtml(participant.session_id)}" data-access-mode="${escapeHtml(accessMode)}" data-target-access-mode="${escapeHtml(accessMode)}">Reset / reissue</button>${accessMode === 'assisted' ? `<button type="button" class="btn btn-primary" data-reset-signer-session data-switch-mode="true" data-session-id="${escapeHtml(participant.session_id)}" data-access-mode="assisted" data-target-access-mode="self_service">Send remotely instead</button>` : `<details class="assisted-signing-fallback"><summary>Need in-person assistance?</summary><button type="button" class="btn btn-secondary" data-reset-signer-session data-switch-mode="true" data-session-id="${escapeHtml(participant.session_id)}" data-access-mode="self_service" data-target-access-mode="assisted">Switch to officer device</button></details>`}`}</div>`
            : `<div class="signing-primary-actions"><button type="button" class="btn btn-primary" data-create-signer-session data-access-mode="self_service" data-package-id="${escapeHtml(packageData.id)}" data-signer-role="${escapeHtml(participant.role)}">Send to signer's phone</button><small>The signer can review, sign and enter their OTP from any location.</small>${assistedFallback}</div>`;
        const correctionSlot = signatures.find(slot => slot.completed);
        const signatureCorrections = current.status === 'signed_pending_approval' && correctionSlot
          ? correctionToggle(
            'signature_slot', `${correctionSlot.document_key}.${correctionSlot.key}`,
            `${participant.label} holistic signature`, 'Flag signature for correction',
          )
          : '';
        const signatureDate = signaturesComplete && participant.signed_at ? `<small>${escapeHtml(new Date(participant.signed_at).toLocaleString('en-KE', {timeZone:'Africa/Nairobi', day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'}))}</small>` : '';
        const signatureRow = signatures.length ? `<div class="signing-test-slot participant-row ${signaturesComplete ? 'is-complete' : ''}"><span class="participant-person"><strong>${escapeHtml(participant.name || participant.label)}</strong>${participant.name ? `<small>${escapeHtml(participant.label)}</small>` : ''}${participant.phone_mapped || participant.staff ? '' : '<small>Phone number needed</small>'}${signatureDate}${signatureCorrections}</span><div class="participant-actions">${signaturesComplete ? '<span class="status-chip completed">Signed</span>' : externalAction}</div></div>` : '';
        const stampRows = stamps.map(slot => `<div class="signing-test-slot ${slot.completed ? 'is-complete' : ''}"><span><strong>${escapeHtml(slot.label || slot.key)}</strong><small>${escapeHtml(participant.label)} · ${escapeHtml(slot.document_key)}</small></span>${slot.completed ? '<span class="status-chip">Stamped</span>' : !canStamp ? '<span class="status-chip">Awaiting stamp</span>' : `<select data-production-stamp-select><option value="">Choose production stamp</option>${stampOptions}</select><button type="button" class="btn btn-secondary" data-production-stamp data-package-id="${escapeHtml(packageData.id)}" data-document-key="${escapeHtml(slot.document_key)}" data-slot-key="${escapeHtml(slot.key)}" data-signer-role="${escapeHtml(participant.role)}">Apply stamp</button>`}</div>`).join('');
        return signatureRow + stampRows;
      }).join('');
      const archive = ['fully_signed', 'approved'].includes(current.status) && verified.archive_status !== 'uploaded'
        ? `<aside class="notice"><strong>${verified.archive_status === 'failed' ? 'Documents need saving' : 'Saving documents'}</strong>${verified.archive_status === 'failed' ? `<button type="button" class="btn btn-primary" id="origination-archive-signed" data-package-id="${escapeHtml(packageData.id)}">Retry saving</button>` : ''}</aside>` : '';
      const signedPacket = verified.signed_packet_available
        ? `<aside class="signed-packet-access"><div><strong>Signed application</strong><span>${verified.archive_status === 'uploaded' ? 'Documents saved.' : 'Ready to view.'}</span></div><div><button type="button" class="btn btn-secondary" id="origination-view-signed" data-package-id="${escapeHtml(packageData.id)}">View documents</button><button type="button" class="btn btn-primary" id="origination-open-signed-pdf" data-package-id="${escapeHtml(packageData.id)}">Open PDF</button></div></aside>`
        : '';
      const signingComplete = ['fully_signed', 'signed_pending_approval', 'approved'].includes(current.status);
      const signingHeading = current.status === 'signed_pending_approval' ? 'Signed — pending JBL approval' : current.status === 'approved' ? 'Approved and locked' : signingComplete ? 'Signing complete' : current.approval_roles?.length ? 'Signatures and approval' : 'Send each signer their secure link';
      const signingDetail = current.status === 'signed_pending_approval'
        ? 'Signatures complete. Final approval is still needed.'
        : current.status === 'approved'
          ? 'Signed application ready.'
          : signingComplete ? 'All required signatures and stamps are saved.' : current.approval_roles?.length ? 'The final approver signs after the other participants.' : 'Each signer reviews the documents and verifies the code sent to their phone.';
      return `<section class="signing-verified-panel"><div class="signing-panel-heading"><div><h3>${signingHeading}</h3></div><button type="button" class="icon-button" id="origination-refresh-signing" aria-label="Refresh signing progress" title="Refresh signing progress">${iconSvg('refresh')}</button></div><p>${signingDetail}</p>${participants || '<div class="empty-state">No signers were configured.</div>'}${signedPacket}${archive}</section>`;
    }
    const stamps = packageData.test_stamps || [];
    const slots = test.slots || [];
    const signatureRoles = new Map();
    slots.filter(slot => slot.type === 'signature').forEach(slot => {
      const grouped = signatureRoles.get(slot.role) || [];
      grouped.push(slot);
      signatureRoles.set(slot.role, grouped);
    });
    const signatureRows = [...signatureRoles.entries()].map(([role, roleSlots]) => {
      const complete = roleSlots.every(slot => slot.completed);
      const first = roleSlots.find(slot => !slot.completed) || roleSlots[0];
      const label = String(role || 'signer').replaceAll('_', ' ').replace(/\b\w/g, value => value.toUpperCase());
      const method = roleSlots.find(slot => slot.capture_method)?.capture_method || '';
      return `<div class="signing-test-slot${complete ? ' is-complete' : ''}"><span><strong>${escapeHtml(label)} holistic signature</strong><small>${roleSlots.length} placement${roleSlots.length === 1 ? '' : 's'} across the complete packet${method ? ` · ${escapeHtml(method)}` : ''}</small></span>${complete ? '<span class="status-chip">TEST complete</span>' : `<button type="button" class="btn btn-secondary" data-test-sign-slot data-package-id="${escapeHtml(packageData.id)}" data-document-key="${escapeHtml(first.document_key)}" data-slot-key="${escapeHtml(first.key)}" data-signer-role="${escapeHtml(role)}" data-slot-type="signature">Capture one TEST signature</button>`}</div>`;
    }).join('');
    const otherRows = slots.filter(slot => slot.type !== 'signature').map(slot => {
      const label = slot.label || `${slot.role} ${slot.key}`.replaceAll('_', ' ');
      if (slot.completed) {
        const method = slot.type === 'signature' && slot.capture_method ? ` · ${slot.capture_method}` : '';
        return `<div class="signing-test-slot is-complete"><span><strong>${escapeHtml(label)}</strong><small>${escapeHtml(slot.type)}${escapeHtml(method)} · completed by ${escapeHtml(slot.actor_name || 'authorized tester')}</small></span><span class="status-chip">TEST complete</span></div>`;
      }
      if (slot.type === 'date_signed') {
        return `<div class="signing-test-slot"><span><strong>${escapeHtml(label)}</strong><small>Filled automatically with the signer's holistic signature</small></span><span class="status-chip">Awaiting signer</span></div>`;
      }
      const stampSelect = slot.type === 'stamp'
        ? `<select data-test-stamp-select><option value="">Choose test stamp</option>${stamps.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)} v${escapeHtml(item.version)} · ${escapeHtml(item.scope)}</option>`).join('')}</select>`
        : '';
      return `<div class="signing-test-slot"><span><strong>${escapeHtml(label)}</strong><small>${escapeHtml(slot.role.replaceAll('_', ' '))} · ${escapeHtml(slot.document_key)}</small></span>${stampSelect}<button type="button" class="btn btn-secondary" data-test-sign-slot data-package-id="${escapeHtml(packageData.id)}" data-document-key="${escapeHtml(slot.document_key)}" data-slot-key="${escapeHtml(slot.key)}" data-signer-role="${escapeHtml(slot.role)}" data-slot-type="${escapeHtml(slot.type)}">${slot.type === 'stamp' ? 'Apply TEST stamp' : 'Capture TEST signature'}</button></div>`;
    }).join('');
    const rows = signatureRows + otherRows;
    return `<section class="signing-test-panel"><p class="eyebrow">Non-production simulator</p><h3>Test holistic signing and stamp placement</h3><p>Each signer supplies one capture for the complete packet. These actions do not use OTP and cannot create a legally signed application. Every page remains watermarked.</p>${rows || '<div class="empty-state">No signing slots were configured.</div>'}<button type="button" class="btn btn-primary" id="origination-test-signing-preview">Preview TEST signed packet</button></section>`;
  }

  function actionMarkup(editable) {
    if (current.signing_workspace && !editable) return '';
    if (!editable) {
      const officerOwnsApplication = capabilities.can_create
        && String(current.officer_id) === String(capabilities.user_id);
      const recall = current.can_recall && officerOwnsApplication
        ? '<button class="btn btn-secondary" id="origination-recall">Edit application</button>' : '';
      if (current.status === 'signed_pending_approval' && capabilities.can_review) {
        const assignedElsewhere = current.recheck_assigned_to_id
          && String(current.recheck_assigned_to_id) !== String(capabilities.user_id);
        if (assignedElsewhere) return '<button class="btn btn-secondary" id="origination-takeover-review">Take over re-check</button>';
        return '<button class="btn btn-secondary" data-final-review="request_correction">Request correction</button><button class="btn btn-danger" data-final-review="decline">Decline</button><button class="btn btn-primary" data-final-review="approve">Approve and lock</button>';
      }
      if ((capabilities.can_confirm_signing || current.short_acknowledgement && capabilities.can_create) && officerOwnsApplication && ['ready_for_review', 'reviewed'].includes(current.status)) {
        return `${recall}<button class="btn btn-primary" id="origination-confirm-signing">Continue to signing</button>`;
      }
      if (current.status === 'ready_for_review' && !current.review_packet_ready) {
        const prepare = capabilities.can_start_signing
          ? '<button class="btn btn-primary" id="origination-prepare-review" data-primary-action="Prepare documents">Prepare documents</button>' : '';
        return `${recall}${prepare}`;
      }
      if (current.status === 'ready_for_review' && current.review_packet_ready && capabilities.can_review) {
        const assignedElsewhere = current.recheck_assigned_to_id
          && String(current.recheck_assigned_to_id) !== String(capabilities.user_id);
        if (assignedElsewhere) return `${recall}<button class="btn btn-secondary" id="origination-takeover-review">Take over re-check</button>`;
        return `${recall}<button class="btn btn-secondary" data-review="request_correction">Request correction</button><button class="btn btn-danger" data-review="decline">Decline</button><button class="btn btn-primary" data-review="approve">Approve documents</button>`;
      }
      if (current.status === 'reviewed' && capabilities.can_start_signing) return `${recall}<button class="btn btn-primary" id="origination-start-signing" data-primary-action="Start signing">Start signing</button>`;
      return recall;
    }
    const finalAction = current.completion_without_signing
      ? '<button class="btn btn-primary" id="origination-submit" data-primary-action="Complete application">Complete application</button>'
      : current.signing_workspace || (current.approval_roles || []).length
      ? '<button class="btn btn-primary" id="origination-confirm-signing" data-primary-action="Submit for signing">Submit for signing</button>'
      : capabilities.can_confirm_signing
      ? '<button class="btn btn-primary" id="origination-confirm-signing" data-primary-action="Confirm and start signing">Confirm and start signing</button>'
      : '<button class="btn btn-primary" id="origination-submit" data-primary-action="Submit application">Submit application</button>';
    return step === wizardSections().length - 1 ? finalAction : '';
  }

  function correctionChecklistMarkup() {
    const correction = current?.active_correction;
    if (!correction) return '';
    const items = (correction.items || []).map(item => `<button type="button" class="correction-item" data-correction-jump="${escapeHtml(`${item.target_type}:${item.target_key}`)}"><span><strong>${escapeHtml(item.target_label)}</strong>${item.instruction ? `<small>${escapeHtml(item.instruction)}</small>` : ''}</span><span>Open ${iconSvg('arrowRight')}</span></button>`).join('');
    const checker = current?.recheck_assigned_to_name
      ? `<small class="correction-checker">Re-check assigned to ${escapeHtml(current.recheck_assigned_to_name)}</small>`
      : '';
    return `<aside class="correction-checklist"><p class="eyebrow">Correction required</p><strong>${escapeHtml(correction.summary)}</strong>${checker}${items ? `<div>${items}</div>` : '<small>Review the application and address the reviewer note.</small>'}</aside>`;
  }

  function recheckAssignmentMarkup() {
    if (!['ready_for_review', 'signed_pending_approval'].includes(current?.status) || !current?.recheck_assigned_to_name) return '';
    const assignedHere = String(current.recheck_assigned_to_id) === String(capabilities.user_id);
    const detail = assignedHere
      ? 'You are the original checker responsible for this re-check.'
      : 'Another authorized checker must record a takeover reason before reviewing it.';
    return `<aside class="notice"><strong>Correction re-check</strong><span>Assigned to ${escapeHtml(current.recheck_assigned_to_name)}. ${detail}</span></aside>`;
  }

  function recoveryConflictMarkup() {
    if (!syncConflict || !conflictDraft) return '';
    if (!conflictServerLoaded) {
      return '<aside class="notice recovery-conflict"><strong>Could not load the saved draft</strong><span>Your changes are kept.</span><button type="button" class="btn btn-secondary" id="recovery-retry-refresh">Retry</button></aside>';
    }
    return '<aside class="notice recovery-conflict"><strong>A newer draft was saved</strong><div><button type="button" class="btn btn-secondary" id="recovery-use-server">Load saved</button><button type="button" class="btn btn-primary" id="recovery-restore-phone">Keep my changes</button></div></aside>';
  }

  function persistentStateFeedbackMarkup() {
    if (current?.status === 'signed_pending_approval') {
      return '<aside class="notice feedback-banner success" role="status"><strong>Signed — pending JBL approval</strong><span>All required signatures are present. The application still needs final approval.</span></aside>';
    }
    return '';
  }

  function signingWorkspaceMarkup() {
    const workspace = current.signing_workspace;
    const packageData = current.signing_package || {};
    const verified = packageData.verified_signing || {};
    if (current.status === 'draft') return `<div class="section-title"><h3>Draft</h3></div><p>${escapeHtml(current.officer_name || 'The assigned officer')} is completing this application.</p>`;
    if (verified.test_mode) return signingTestMarkup();
    if (!verified.enabled && current.status !== 'approved') return '<aside class="notice"><strong>Signing is unavailable</strong><span>Your application is saved.</span><button type="button" class="btn btn-secondary" data-open-app-status>App status</button></aside>';
    const dispatch = capabilities.can_create && (String(current.officer_id) === String(capabilities.user_id) || capabilities.is_superuser);
    const stampOptions = (verified.production_stamps || []).map(stamp => `<option value="${escapeHtml(stamp.id)}">${escapeHtml(stamp.name)}</option>`).join('');
    let primaryChosen = false;
    const rows = (verified.participants || []).map(participant => {
      const permitted = workspace.participants.find(row => row.id === participant.participant_id);
      const complete = permitted?.complete;
      const attributes = `data-package-id="${escapeHtml(packageData.id)}" data-signer-role="${escapeHtml(participant.role)}" data-participant-id="${escapeHtml(participant.participant_id)}"`;
      let action = '<span class="status-chip">Awaiting signer</span>';
      if (complete) action = '<span class="status-chip completed">Signed</span>';
      else if (permitted?.can_sign) {
        const primary = primaryChosen ? '' : 'data-primary-action="Sign"';
        primaryChosen = true;
        action = `<button type="button" class="btn btn-primary" data-staff-sign ${attributes} ${primary}>Sign</button>`;
      } else if (!participant.staff && dispatch && current.status !== 'approved') {
        action = participant.session_id
          ? `<span class="status-chip">${escapeHtml(participant.session_status.replaceAll('_', ' '))}</span><button type="button" class="btn btn-secondary" data-reset-signer-session data-session-id="${escapeHtml(participant.session_id)}" data-access-mode="${escapeHtml(participant.access_mode)}" data-target-access-mode="${escapeHtml(participant.access_mode)}">Replace link</button>`
          : `<button type="button" class="btn btn-secondary" data-create-signer-session data-access-mode="self_service" ${attributes}>Send link</button><details class="signer-assistance"><summary>In person</summary><button type="button" class="btn btn-secondary" data-create-signer-session data-access-mode="assisted" ${attributes}>Assisted signing</button></details>`;
      }
      const stamps = permitted?.can_sign ? (participant.slots || []).filter(slot => slot.type === 'stamp' && !slot.completed).map(slot => `<div class="signer-stamp"><label><span>Required stamp</span><select data-production-stamp-select><option value="">Choose stamp</option>${stampOptions}</select></label><button type="button" class="btn btn-secondary" data-production-stamp ${attributes} data-document-key="${escapeHtml(slot.document_key)}" data-slot-key="${escapeHtml(slot.key)}">Apply</button></div>`).join('') : '';
      const date = participant.signed_at ? `<small class="participant-date">${escapeHtml(new Date(participant.signed_at).toLocaleString('en-KE', {timeZone:'Africa/Nairobi', day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'}))}</small>` : '';
      return `<div class="participant-row"><div class="participant-person"><strong>${escapeHtml(participant.name || participant.label)}</strong>${participant.name ? `<small>${escapeHtml(participant.label)}</small>` : ''}${date}</div><div class="participant-actions">${action}</div>${stamps}</div>`;
    }).sort((a,b) => Number(b.includes('data-staff-sign')) - Number(a.includes('data-staff-sign'))).join('');
    const approved = current.status === 'approved';
    const preview = approved ? `<button type="button" class="icon-button" aria-label="View signed documents" title="View signed documents" id="origination-view-signed" data-package-id="${escapeHtml(packageData.id)}">${iconSvg('review')}</button>` : `<button type="button" class="icon-button" aria-label="Review documents" title="Review documents" data-approval-preview>${iconSvg('review')}</button>`;
    const archive = approved && verified.archive_status !== 'uploaded' ? `<aside class="notice"><strong>${verified.archive_status === 'failed' ? 'Documents need saving' : 'Saving documents'}</strong>${verified.archive_status === 'failed' ? `<button type="button" class="btn btn-secondary" id="origination-archive-signed" data-package-id="${escapeHtml(packageData.id)}">Retry saving</button>` : ''}</aside>` : '';
    const details = (current.form_schema?.sections || []).map(section => `<details><summary>${escapeHtml(section.label)}</summary>${sectionFieldsMarkup(section.key, current.form_payload || {}, false)}</details>`).join('');
    const history = (current.activity || []).map(event => `<p><strong>${escapeHtml(event.label)}</strong><small>${escapeHtml(event.actor)} · ${escapeHtml(new Date(event.at).toLocaleString('en-KE'))}</small></p>`).join('') || '<p>No activity yet.</p>';
    return `<section class="signing-workspace"><header><div><h3>${approved ? 'Signatures complete' : 'Signatures'}</h3><p>${workspace.completed_count} of ${workspace.required_count} signers complete</p></div><nav class="signing-tools" aria-label="Application actions">${preview}${workspace.can_recall ? `<button type="button" class="icon-button" id="origination-recall" aria-label="Withdraw for changes" title="Withdraw for changes">${iconSvg('undo')}</button>` : ''}</nav></header><div class="participant-list">${rows}</div>${archive}<details class="workspace-details"><summary>Application details</summary>${details}</details><details class="workspace-details"><summary>Documents</summary>${(current.document_packet?.documents || []).filter(doc => doc.selected).map(doc => `<p>${escapeHtml(doc.name)}</p>`).join('')}</details><details class="workspace-details"><summary>History</summary>${history}</details></section>`;
  }

  function headerContactsMarkup() {
    if (current?.presentation === 'masked') return '';
    const targets = current?.phone_id_checks?.allowed ? current.phone_id_checks.targets || [] : [];
    const fields = current?.form_schema?.fields || [];
    const primary = targets.find(item => item.target === 'primary')?.field_key;
    const alternate = targets.find(item => item.target === 'alternate')?.field_key
      || fields.find(field => ['applicant_other_phone', 'applicant_alternative_phone', 'applicant_alternate_phone'].includes(field.key))?.key;
    const phones = [{label:'Phone',target:'primary',value:current.applicant_summary?.phone || current.form_payload?.[primary]},
      {label:'Alternative phone',target:'alternate',value:current.form_payload?.[alternate]}];
    const rows = phones.filter(item => item.value).map(item =>
      `<div class="editor-contact" aria-label="${item.label}">${iconSvg('phone')}${window.MiniAppUtils?.phoneLink?.(item.value) || escapeHtml(item.value)}${targets.some(target => target.target === item.target) ? `<div data-phone-id-target="${item.target}" data-phone-id-compact hidden></div>` : ''}</div>`);
    const id = current.applicant_summary?.national_id;
    if (id) rows.push(`<div class="editor-contact"><button type="button" class="contact-copy" data-copy-applicant-id aria-label="Copy National ID">${iconSvg('copy')} ${escapeHtml(id)}</button></div>`);
    return rows.join('');
  }

  function refreshHeaderContacts() {
    const host = root()?.querySelector('.editor-contacts');
    if (!host) return;
    host.innerHTML = headerContactsMarkup();
    host.hidden = !host.childElementCount;
    const identity = root().querySelector('.editor-identity>strong');
    if (identity) identity.textContent = current.applicant_summary?.name || 'New applicant';
    host.querySelector('[data-copy-applicant-id]')?.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(current.applicant_summary.national_id);
        showToast('National ID copied.', 'success');
      } catch (_) { showToast('Could not copy the National ID. Try again or copy it from Applicant details.', 'error'); }
    });
    window.OriginationPhoneIdentity?.mount(root(), {
      current:() => current, save:() => saveDraft(true), get:apiFetch, post:postJson,
      requestKey, toast:showToast,
    });
  }

  function renderEditor(application, requestedStep) {
    window.MiniAppUtils?.bindAccessibleForm?.(root())?.dispose();
    document.body.classList.add('origination-editor-open');
    current = application;
    step = Number.isInteger(requestedStep) ? requestedStep : step;
    const values = collectPayload();
    const editable = ['draft', 'correction_required'].includes(application.status) && (!application.signing_workspace || application.signing_workspace.can_submit);
    const sections = wizardSections();
    step = Math.max(0, Math.min(step, sections.length - 1));
    const section = sections[step];
    const sectionLocked = false;
    const sectionEditable = editable && !sectionLocked && !syncConflict;
    let content;
    if (application.status === 'completed') content = '<div class="section-title"><div><h3>Application completed</h3><p>No e-signatures were required. This does not approve the loan.</p></div></div><button type="button" class="btn btn-primary" id="origination-completed-download">Download application</button>';
    else if (application.signing_workspace && !editable) content = signingWorkspaceMarkup();
    else if (section.key === 'review') content = reviewMarkup(values);
    else if (section.key.startsWith('document:')) content = supportingDocumentMarkup(section.document, sectionEditable);
    else {
      const fields = section.key === 'product_requirements'
        ? productConfigurationMarkup(sectionEditable)
        : sectionFieldsMarkup(section.key, values, sectionEditable);
      const quote = section.key === facilitySectionKey() && Number(application.form_schema?.commercial_contract_version || 0) >= 2
        ? commercialQuoteMarkup() : '';
      content = `<div class="section-title"><div><h3>${escapeHtml(section.label)}</h3>${section.hint ? `<p>${escapeHtml(section.hint)}</p>` : ''}</div></div>${fields}${quote}`;
    }
    if (sectionLocked) {
      content = `<aside class="completed-section-lock"><span><strong>Section saved</strong><small>Values are locked while you continue. Unlock only when you need to change this section.</small></span><button type="button" class="btn btn-secondary" id="origination-edit-section">Edit section</button></aside>${content}`;
    }
    const recoveryState = syncConflict ? ['Choose draft', 'offline'] : dirty ? ['Not saved', 'offline'] : ['Saved', 'saved'];
    const actions = actionMarkup(editable);
    const actionFooter = (editable ? `<footer class="wizard-actions"><span id="origination-save-status" data-state="${recoveryState[1]}">${recoveryState[0]}</span></footer>` : '')
      + (actions ? `<div class="wizard-submit-actions">${actions}</div>` : '');
    const statusHasPersistentBanner = application.status === 'signed_pending_approval';
    const contextStatus = statusHasPersistentBanner || application.signing_workspace
      ? '' : `<small class="editor-status-text">${escapeHtml(application.status_text || applicationStatusLabel(application))}</small>`;
    const contextChip = statusHasPersistentBanner
      ? '' : `<span class="status-chip status-${escapeHtml(application.status)}">${escapeHtml(applicationStatusLabel(application))}</span>`;
    const restartAction = editable && application.status === 'draft'
      ? '<button type="button" class="icon-button" id="origination-restart-laf" title="Manage documents" aria-label="Manage documents"><svg aria-hidden="true" viewBox="0 0 24 24"><path d="M4 7h15l-4-4m5 14H5l4 4"/></svg></button>' : '';
    root().innerHTML = `<header class="editor-summary"><div class="editor-context"><button type="button" class="icon-button" id="origination-back" aria-label="Back to applications">${iconSvg('arrowLeft')}</button><div class="editor-identity"><strong>${escapeHtml(application.applicant_summary?.name || 'New applicant')}</strong><div class="editor-identity-meta"><small>${escapeHtml(application.product_name)}</small>${contextChip || contextStatus}</div></div><div class="editor-document-actions">${restartAction}<button type="button" class="icon-button" id="origination-preview-early" title="Preview application" aria-label="Preview application"><svg aria-hidden="true" viewBox="0 0 24 24"><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg></button></div></div><div class="editor-contacts" aria-label="Applicant contacts"></div></header>${application.signing_workspace && !editable ? '' : persistentStateFeedbackMarkup()}${recoveryConflictMarkup()}${correctionChecklistMarkup()}${recheckAssignmentMarkup()}${editable ? progressMarkup() : ''}<section class="wizard-card">${content}</section>${actionFooter}`;
    syncNativeDateDisplays(root());
    bindEditor(sectionEditable);
    refreshHeaderContacts();
    root().querySelectorAll('.preview-link').forEach(button => {
      const label = button.textContent.trim();
      button.setAttribute('aria-label',label);button.title=label;
      button.classList.add('icon-button');
      button.innerHTML='<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg>';
    });
    if (!['declined', 'expired', 'cancelled'].includes(application.status) && application.presentation !== 'masked' && application.download_ready !== false) {
      const context = root().querySelector('.editor-context');
      const download = document.createElement('button');
      download.type = 'button'; download.className = 'icon-button';
      download.id = 'origination-download'; download.setAttribute('aria-label', 'Download application');
      download.title = application.status === 'approved' ? 'Download signed application' : 'Download unsigned application';
      download.innerHTML = '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
      context?.querySelector('.editor-document-actions')?.appendChild(download);
      download.onclick = () => { if (!copyDownloadInFlight) openDownloadSheet(download); };
      document.getElementById('origination-completed-download')?.addEventListener('click', event => {
        if (!copyDownloadInFlight) openDownloadSheet(event.currentTarget);
      });
    }
    window.MiniAppUtils?.bindAccessibleForm?.(root());
    document.getElementById('origination-restart-laf')?.addEventListener('click', event => openDocumentSheet(event.currentTarget));
    root().querySelectorAll('[data-manage-documents]').forEach(button => button.addEventListener('click', event => openDocumentSheet(event.currentTarget)));
    syncTelegramControls();
    scheduleSigningRefresh();
    window.requestAnimationFrame(() => window.scrollTo(0, 0));
  }


  function repeatableItemLabel(field) {
    const configured = String(field?.structure?.item_label || '').trim();
    if (configured) return configured;
    const identity = `${field?.key || ''} ${field?.label || ''}`.toLowerCase();
    if (identity.includes('loan')) return 'Loan';
    if (identity.includes('security') || identity.includes('securit') || identity.includes('pledged') || identity.includes('asset')) return 'Security';
    if (identity.includes('fee')) return 'Fee';
    return 'Item';
  }

  function repeatableRowMarkup(columns, row, index, disabled, lockRow = false, itemLabel = 'Item', gridStyle = 'grid-template-columns:minmax(0, 50fr) minmax(0, 50fr)') {
    return `<fieldset class="repeatable-row" data-repeat-row data-row-id="${escapeHtml(row?.row_id || newRowId())}"><legend><span>${escapeHtml(itemLabel)} ${index + 1}</span>${lockRow ? '' : `<button type="button" class="icon-button repeatable-remove" data-repeat-remove aria-label="Remove ${escapeHtml(itemLabel.toLowerCase())} ${index + 1}"${disabled ? ' disabled' : ''}>${iconSvg('close')}</button>`}</legend><span class="repeatable-row-number" aria-hidden="true">${index + 1}</span><div class="repeatable-row-fields" style="${escapeHtml(gridStyle)}">${columns.map(column => {
      const columnValue = row?.[column.key] ?? '';
      const numeric = column.type === 'money' || column.type === 'number';
      const columnDisabled = disabled || column.editable === false;
      if (column.type === 'boolean') {
        return `<label><span>${escapeHtml(column.label || column.key)}</span><select${ruleAttributes(column)} data-repeat-column="${escapeHtml(column.key)}"${column.required ? ' required' : ''}${columnDisabled ? ' disabled' : ''}><option value="">Choose</option><option value="true"${columnValue === true ? ' selected' : ''}>Yes</option><option value="false"${columnValue === false ? ' selected' : ''}>No</option></select></label>`;
      }
      if (column.type === 'choice') {
        const options = (column.options || []).filter(option => option?.active !== false).map(option => {
          const code = option && typeof option === 'object' ? option.code : option;
          const label = option && typeof option === 'object' ? (option.label || option.code) : option;
          return `<option value="${escapeHtml(code)}"${columnValue === code ? ' selected' : ''}>${escapeHtml(label)}</option>`;
        }).join('');
        return `<label><span>${escapeHtml(column.label || column.key)}${column.required ? '<span class="required-mark" aria-label="required">*</span>' : ''}</span><select${ruleAttributes(column)} data-repeat-column="${escapeHtml(column.key)}"${column.required ? ' required' : ''}${columnDisabled ? ' disabled' : ''}><option value="">Choose</option>${options}</select></label>`;
      }
      if (column.type === 'date') {
        const rules = column.validation || {};
        const maximum = rules.max_date || (rules.no_future ? window.OriginationFieldRules?.today() : '');
        return `<label><span>${escapeHtml(column.label || column.key)}${column.required ? '<span class="required-mark" aria-label="required">*</span>' : ''}</span>${nativeDateControl(`${ruleAttributes(column)} data-repeat-column="${escapeHtml(column.key)}"${column.required ? ' required' : ''}`, columnValue, columnDisabled, `${rules.min_date ? ` min="${escapeHtml(rules.min_date)}"` : ''}${maximum ? ` max="${escapeHtml(maximum)}"` : ''}`)}</label>`;
      }
      const validation = column.validation || {};
      const numericRules = numeric ? ` inputmode="${column.type === 'money' || validation.integer ? 'numeric' : 'decimal'}" data-numeric-input${column.type === 'money' && !lockRow ? ' data-money-input' : ''} data-min="${escapeHtml(validation.min ?? '')}" data-max="${escapeHtml(validation.max ?? '')}"` : '';
      const inputType = validation.format === 'email' ? 'email' : column.type === 'phone' ? 'tel' : 'text';
      return `<label><span>${escapeHtml(column.label || column.key)}${column.required ? '<span class="required-mark" aria-label="required">*</span>' : ''}</span><input${ruleAttributes(column)} data-repeat-column="${escapeHtml(column.key)}" type="${inputType}" value="${escapeHtml(columnValue)}"${numericRules}${column.required ? ' required' : ''}${columnDisabled ? ' disabled' : ''}></label>`;
    }).join('')}</div></fieldset>`;
  }

  function refreshRepeatableField(container) {
    const rows = [...container.querySelectorAll('[data-repeat-row]')];
    const itemLabel = container.dataset.itemLabel || 'Item';
    rows.forEach((row, index) => {
      row.querySelector('.repeatable-row-number').textContent = String(index + 1);
      const legend = row.querySelector('legend > span');
      if (legend) legend.textContent = `${itemLabel} ${index + 1}`;
      const remove = row.querySelector('[data-repeat-remove]');
      if (remove) remove.setAttribute('aria-label', `Remove ${itemLabel.toLowerCase()} ${index + 1}`);
    });
    let total = 0;
    rows.forEach(row => {
      const input = row.querySelector('[data-repeat-column="estimated_value"]');
      const value = Number(input?.value || 0);
      if (Number.isFinite(value)) total += value;
    });
    const output = container.querySelector('[data-repeat-total]');
    if (output) output.textContent = total.toLocaleString('en-KE', { maximumFractionDigits: 0 });
    const add = container.querySelector('[data-repeat-add]');
    if (add) add.disabled = rows.length >= Number(container.dataset.maxItems || 11);
  }

  function supportingDocumentField(field, document, editable) {
    const shared = current.form_payload?.[field.key];
    const isShared = current.value_contract_version === 2 && field.value_contract?.scope === 'application';
    const value = isShared ? shared ?? '' : document.field_payload?.[field.key] ?? '';
    const locked = field.source_type === 'system';
    const correctionKey = `${document.key}.${field.key}`;
    const disabled = !editable || locked || field.editable === false || !correctionAllows(isShared ? 'field' : 'document_field', isShared ? field.key : correctionKey);
    return fieldInput(field, value, disabled, document)
      .replaceAll('data-field="', 'data-document-field="')
      .replaceAll('data-main-repeatable=', 'data-document-repeatable=');
  }

  function supportingDocumentMarkup(document, editable) {
    const sharedValues = current?.value_contract_version === 2;
    const fields = (document?.schema?.fields || []).map(field =>
      sharedValues && field.value_contract?.scope === 'application'
        ? {...field, ...(current.form_schema.fields.find(item => item.key === field.key) || {}), section_key:field.section_key} : field);
    const configured = document?.schema?.sections || [];
    const sectionKeys = [...new Set([...configured.map(section => section.key), ...fields.map(field => field.section_key || '')])];
    const sections = sectionKeys.map(key => {
      const items = fields.filter(field => (field.section_key || '') === key);
      if (!items.length) return '';
      const section = configured.find(item => item.key === key);
      const heading = section ? `<div class="section-title"><div><h4>${escapeHtml(section.label || key)}</h4>${section.help_text ? `<p>${escapeHtml(section.help_text)}</p>` : ''}</div></div>` : '';
      return `<section class="supporting-form-section">${heading}<div class="laf-grid">${items.map(field => {
        if (documentOwnsInput(field, document)) return supportingDocumentField(field, document, editable);
        const value = field.value_contract?.source === 'entered'
          ? current.form_payload?.[field.key] : document.resolved_values?.[field.key];
        return fieldInput(field, value, true, document, true);
      }).join('')}</div></section>`;
    }).join('');
    return `<div class="section-title"><div><h3>${escapeHtml(document.name)}</h3></div><button type="button" class="preview-link" data-support-preview="${escapeHtml(document.key)}">${latestPreviewLabel('Preview document')}</button></div>${sections || '<p class="field-help">No additional details needed. Preview this document above.</p>'}`;
  }

  function correctionTargetStep(identity) {
    const [targetType, targetKey] = String(identity || '').split(':', 2);
    const sections = wizardSections();
    if (targetType === 'requirement') return sections.findIndex(item => item.key === 'product_requirements');
    if (targetType === 'document_field') {
      const documentKey = targetKey.split('.', 1)[0];
      return sections.findIndex(item => item.key === `document:${documentKey}`);
    }
    return originationErrorSection(targetKey);
  }

  function openReviewDialog(mode) {
    if (mode === 'request_correction' && !reviewTargets.size) {
      return showToast('Flag at least one field or requirement before requesting correction.', true);
    }
    reviewDialogMode = mode;
    reviewReturnFocus = document.activeElement;
    const overlay = document.getElementById('origination-review-overlay');
    document.getElementById('review-dialog-eyebrow').textContent = 'Application review';
    const title = document.getElementById('review-dialog-title');
    const hint = document.getElementById('review-dialog-hint');
    const targets = document.getElementById('review-dialog-targets');
    const summary = document.getElementById('review-dialog-summary');
    title.textContent = mode === 'decline' ? 'Decline application' : mode === 'takeover' ? 'Take over correction re-check' : 'Request corrections';
    hint.textContent = mode === 'decline'
      ? 'Record the reason. The decision is retained in the application audit history.'
      : mode === 'takeover'
        ? 'Explain why the original checker is unavailable. The reassignment is audited.'
      : 'Give the officer an overall instruction for the flagged items.';
    targets.innerHTML = mode === 'request_correction'
      ? [...reviewTargets.entries()].map(([identity, item]) => `<label><span>${escapeHtml(item.target_label)}</span><input data-review-instruction="${escapeHtml(identity)}" maxlength="1000" value="${escapeHtml(item.instruction || '')}" placeholder="Optional item-specific instruction"></label>`).join('')
      : '';
    summary.value = '';
    overlay.hidden = false;
    overlay.setAttribute('aria-hidden', 'false');
    document.body.classList.add('origination-modal-open');
    syncTelegramControls();
    summary.focus();
  }

  function openAuditedReasonDialog({ title, hint, submitLabel, onSubmit, returnFocus, eyebrow = 'Audited action' }) {
    reviewDialogMode = 'audited_reason';
    reviewReturnFocus = returnFocus || document.activeElement;
    pendingAuditedReasonAction = onSubmit;
    const overlay = document.getElementById('origination-review-overlay');
    document.getElementById('review-dialog-eyebrow').textContent = eyebrow;
    document.getElementById('review-dialog-title').textContent = title;
    document.getElementById('review-dialog-hint').textContent = hint;
    document.getElementById('review-dialog-targets').innerHTML = '';
    document.getElementById('review-dialog-summary').value = '';
    document.getElementById('review-dialog-submit').textContent = submitLabel;
    overlay.hidden = false;
    overlay.setAttribute('aria-hidden', 'false');
    document.body.classList.add('origination-modal-open');
    syncTelegramControls();
    document.getElementById('review-dialog-summary').focus();
  }

  function closeReviewDialog() {
    const overlay = document.getElementById('origination-review-overlay');
    overlay.hidden = true;
    overlay.setAttribute('aria-hidden', 'true');
    reviewDialogMode = '';
    pendingAuditedReasonAction = null;
    document.getElementById('review-dialog-submit').textContent = 'Record decision';
    document.body.classList.remove('origination-modal-open');
    syncTelegramControls();
    const returnFocus = reviewReturnFocus;
    reviewReturnFocus = null;
    window.requestAnimationFrame(() => returnFocus?.focus?.());
  }

  async function submitReviewDialog() {
    const reason = document.getElementById('review-dialog-summary').value.trim();
    if (!reason) return showToast('Enter the review reason.', true);
    const decision = reviewDialogMode;
    if (decision === 'audited_reason') {
      const button = document.getElementById('review-dialog-submit');
      const action = pendingAuditedReasonAction;
      if (!action) return closeReviewDialog();
      button.disabled = true;
      const completed = await action(reason);
      button.disabled = false;
      if (completed !== false) closeReviewDialog();
      return;
    }
    if (decision === 'takeover') {
      const button = document.getElementById('review-dialog-submit');
      button.disabled = true;
      const result = await postJson(`/applications/${current.id}/correction/takeover/`, {
        revision: current.revision, reason,
      });
      button.disabled = false;
      if (!result.ok) return showToast(result.data?.error || 'Could not take over this review.', true);
      closeReviewDialog();
      current = result.data.application;
      renderEditor(current, step);
      return showToast('Correction re-check assigned to you.');
    }
    if (decision === 'request_correction') {
      document.querySelectorAll('[data-review-instruction]').forEach(input => {
        const item = reviewTargets.get(input.dataset.reviewInstruction);
        if (item) item.instruction = input.value.trim();
      });
    }
    const correctionItems = decision === 'request_correction' ? [...reviewTargets.values()] : undefined;
    const button = document.getElementById('review-dialog-submit');
    button.disabled = true;
    const finalReview = current.status === 'signed_pending_approval';
    const result = await postJson(`/applications/${current.id}/${finalReview ? 'final-review' : 'review'}/`, {
      ...(finalReview ? finalReviewPayload() : reviewPacketPayload()),
      decision,
      reason,
      ...(correctionItems ? { correction_items: correctionItems } : {}),
    });
    button.disabled = false;
    if (!result.ok) return showToast(result.data?.error || 'Could not record the review.', true);
    closeReviewDialog();
    await load();
  }

  function reviewPacketPayload() {
    const packageData = current?.signing_package || {};
    return {
      revision: current?.revision,
      package_id: packageData.id,
      unsigned_document_hash: packageData.unsigned_document_hash,
      review_scope_sha256: packageData.review_scope_sha256,
    };
  }

  function finalReviewPayload() {
    const packageData = current?.signing_package || {};
    return {
      revision: current?.revision,
      package_id: packageData.id,
      signed_document_hash: packageData.signed_document_hash,
    };
  }

  async function submitInlineCorrections() {
    if (!reviewTargets.size) return showToast('Flag at least one field or requirement.', true);
    const items = [...reviewTargets.values()];
    if (items.some(item => !String(item.instruction || '').trim())) {
      return showToast('Add a clear instruction beside every flagged item.', true);
    }
    await runPrimaryAction('Returning...', async () => {
      const finalReview = current.status === 'signed_pending_approval';
      const result = await postJson(`/applications/${current.id}/${finalReview ? 'final-review' : 'review'}/`, {
        ...(finalReview ? finalReviewPayload() : reviewPacketPayload()), decision: 'request_correction',
        reason: finalReview ? 'Correct the flagged signed-packet items.' : '', correction_items: items,
      });
      if (!result.ok) return showToast(result.data?.error || 'Could not request the corrections.', true);
      reviewTargets.clear();
      showToast('Application returned with targeted correction instructions.');
      await load();
    });
  }

  async function recallApplication(confirmation = {}) {
    const result = await postJson(`/applications/${current.id}/recall/`, {
      revision: current.revision,
      ...confirmation,
    });
    if (result.status === 409 && result.data?.confirmation_required) {
      const details = result.data;
      openSheet({
        mode: 'recall-confirmation',
        eyebrow: details.approval_invalidated ? 'Approval will be invalidated' : 'Documents will be replaced',
        title: 'Withdraw for changes?',
        hint: 'Your answers and uploads stay saved. Previous links and signatures no longer apply; everyone must sign again.',
        body: '',
        footer: '<button type="button" class="btn btn-secondary" id="origination-recall-cancel">Keep current documents</button><button type="button" class="btn btn-danger" id="origination-recall-confirm">Withdraw and edit</button>',
        trigger: document.getElementById('origination-recall'),
      });
      if ((current.approval_roles || []).length) {
        document.getElementById('origination-sheet-hint').textContent = 'The old links and signatures will be cancelled. Your fields and evidence stay saved. Everyone must sign again after you resubmit.';
      }
      document.getElementById('origination-recall-cancel').onclick = () => closeSheet();
      document.getElementById('origination-recall-confirm').onclick = () => runPrimaryAction('Recalling...', async () => {
        const confirmed = await recallApplication({
          confirmed_package_id: details.package_id,
          confirmed_package_hash: details.package_hash,
        });
        if (confirmed) closeSheet({ restoreFocus: false });
      });
      return false;
    }
    if (!result.ok) {
      showToast(result.data?.error || 'Could not return the application to Draft.', true);
      return false;
    }
    closeSheet({ restoreFocus: false });
    current = result.data.application;
    showToast('Ready to edit. Resubmit when your changes are complete.');
    renderEditor(current, 0);
    return true;
  }

  async function uploadEvidenceFile(file, requirementKey, control = null) {
    if (!(await saveDraft(true))) return;
    if (!file) return;
    const requestId = requestKey('evidence');
    const formData = new FormData();
    formData.append('revision', String(current.revision));
    formData.append('request_id', requestId);
    formData.append('file', file);
    if (control) control.disabled = true;
    setSaveState('Uploading evidence…', 'saving');
    const uploadPromise = new Promise(resolve => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `/api/origination/api/applications/${current.id}/requirements/${encodeURIComponent(requirementKey)}/evidence/`);
      xhr.timeout = 60000;
      if (tg?.initData) xhr.setRequestHeader('X-Telegram-Init-Data', tg.initData);
      if (window.MiniAppUtils?.setXhrIdempotencyHeaders) {
        window.MiniAppUtils.setXhrIdempotencyHeaders(xhr, requestId);
      } else {
        xhr.setRequestHeader('Idempotency-Key', requestId);
        xhr.setRequestHeader('X-Request-ID', requestId);
      }
      xhr.upload.onprogress = event => {
        if (event.lengthComputable) setSaveState(`Uploading ${Math.round(event.loaded * 100 / event.total)}%`, 'saving');
      };
      xhr.onload = () => {
        let data = {};
        try { data = JSON.parse(xhr.responseText || '{}'); } catch (_) { /* Safe fallback below. */ }
        resolve({ ok: xhr.status >= 200 && xhr.status < 300, status: xhr.status, data });
      };
      xhr.onerror = () => resolve({ ok: false, status: 0, data: { error: 'Could not connect while uploading. Select the file again to retry.' } });
      xhr.ontimeout = () => resolve({ ok: false, status: 0, data: { error: 'The upload timed out. Select the file again to retry.' } });
      xhr.send(formData);
    });
    const result = await (window.MiniAppUtils?.protectWhile
      ? window.MiniAppUtils.protectWhile('origination-evidence-upload', uploadPromise)
      : uploadPromise);
    if (control) control.disabled = false;
    if (result.data?.application) current = result.data.application;
    if (!result.ok) {
      renderEditor(current, step);
      return showToast(result.data?.error || 'Evidence was not uploaded. Select the file again to retry.', true);
    }
    renderEditor(current, step);
    showToast('Evidence uploaded securely.');
  }

  async function uploadEvidence(input) {
    const file = input.files?.[0];
    const requirementKey = input.dataset.evidenceUpload;
    input.value = '';
    return uploadEvidenceFile(file, requirementKey, input);
  }

  async function openIdentityCapture(requirementKey, trigger) {
    const option = current.identity_copies?.find(item => item.key === requirementKey);
    if (!option) return;
    const photos = {}; const urls = {};
    let uploadKey = requestKey('id-copy');
    openSheet({mode: 'id-capture', title: option.label, eyebrow: '',
      hint: 'Optional. Add both sides to save one PDF.', trigger,
      body: `<div class="identity-capture-pair">${['front','back'].map(side => `<div><strong>${side === 'front' ? 'Front' : 'Back'}</strong><img data-id-image="${side}" alt="${side} of ID" hidden><button type="button" class="btn btn-secondary" data-id-camera="${side}" aria-label="Take ${side} photo">${iconSvg('camera')}<span data-id-caption="${side}">Take photo</span></button><label class="btn btn-secondary"><input type="file" accept="image/jpeg,image/png,image/webp" data-id-side="${side}" hidden><span>Choose photo</span></label></div>`).join('')}</div><p role="status" data-id-status></p>`,
      footer: '<button type="button" class="btn btn-secondary" data-id-cancel>Cancel</button><button type="button" class="btn btn-primary" data-id-upload>Save ID copy</button>',
    });
    const cleanup = () => Object.values(urls).forEach(url => URL.revokeObjectURL(url));
    sheetCleanup = cleanup;
    document.querySelector('[data-id-cancel]').onclick = () => {cleanup();closeSheet();};
    const setPhoto = (side, file) => {
      if (!file) return;
      if (urls[side]) URL.revokeObjectURL(urls[side]);
      photos[side] = file; urls[side] = URL.createObjectURL(file);
      uploadKey = requestKey('id-copy');
      const image = document.querySelector(`[data-id-image="${side}"]`);
      image.src = urls[side];image.hidden = false;
      image.onclick = () => {
        const dialog = document.createElement('dialog');dialog.className = 'identity-photo-preview';
        dialog.innerHTML = '<header><strong>ID photo</strong><button type="button" aria-label="Close photo preview">×</button></header><nav class="identity-photo-controls" aria-label="Photo navigation"><button type="button" aria-label="Previous photo">‹</button><span></span><button type="button" aria-label="Next photo">›</button></nav><div tabindex="0"><img alt="ID photo preview"></div>';
        document.body.append(dialog);
        let active = side;
        const stage = dialog.querySelector('div'), preview = dialog.querySelector('img');
        const display = () => {preview.src=urls[active];dialog.querySelector('span').textContent=active==='front'?'Front':'Back';};
        const navigate = () => {const next=active==='front'?'back':'front';if(urls[next]){active=next;display();gestures?.reset();}};
        const gestures = window.SecureMediaViewer?.bindImageGestures(stage,preview,{navigateAtEdges:true,onNavigate:navigate});
        dialog.querySelector('[aria-label="Previous photo"]').onclick = navigate;
        dialog.querySelector('[aria-label="Next photo"]').onclick = navigate;
        dialog.querySelector('[aria-label="Close photo preview"]').onclick = () => dialog.close();
        dialog.addEventListener('close',()=>{gestures?.dispose?.();dialog.remove();image.focus?.();},{once:true});
        display();dialog.showModal();
      };
      document.querySelector(`[data-id-caption="${side}"]`).textContent = 'Retake';
      tg?.HapticFeedback?.notificationOccurred?.('success');
      showToast(`${side === 'front' ? 'Front' : 'Back'} photo ready.`, 'success');
    };
    document.querySelectorAll('[data-id-side]').forEach(input => input.onchange = () => setPhoto(input.dataset.idSide, input.files?.[0]));
    document.querySelectorAll('[data-id-camera]').forEach(button => button.onclick = () =>
      openEvidenceCamera(requirementKey, button, file => setPhoto(button.dataset.idCamera, file)));
    document.querySelector('[data-id-upload]').onclick = async event => {
      const status = document.querySelector('[data-id-status]');
      if (!photos.front || !photos.back) {status.textContent = 'Add both the front and back.';return;}
      await window.MiniAppUtils.runButtonAction(event.currentTarget, async () => {
        if (!await saveDraft(true)) {status.textContent = 'Your photos are kept. Save the application, then retry.';return;}
        if (current.form_payload?.[option.identity_field] !== undefined && !current.identity_copies?.some(item => item.key === requirementKey && item.subject_sha256 === option.subject_sha256)) {
          status.textContent = 'This person’s ID changed. Cancel and open their ID copy again.';return;
        }
        const data = new FormData();data.append('front', photos.front);data.append('back',photos.back);
        data.append('revision',String(current.revision));data.append('request_id',uploadKey);
        const response = await fetch(`/api/origination/api/applications/${current.id}/requirements/${encodeURIComponent(requirementKey)}/evidence/`, {
          method:'POST',headers:{'X-Telegram-Init-Data':tg?.initData || ''},body:data,
        });
        const result = await response.json();
        if (result.application) current = result.application;
        if (!response.ok || !result.ok) {
          if (result.evidence?.status === 'failed') uploadKey = requestKey('id-copy-retry');
          status.textContent = result.error || 'Could not save. Your photos are kept; retry.';showToast(status.textContent,result.pending?'info':'error');return;
        }
        cleanup();closeSheet();renderEditor(current,step);showToast('ID copy saved.');
      }, {loadingLabel:'Saving…'}).catch(() => {status.textContent='Could not connect. Your photos are kept; retry.';showToast(status.textContent,'error');});
    };
  }

  async function openEvidenceCamera(requirementKey, trigger, onCapture = null) {
    if (!navigator.mediaDevices?.getUserMedia) {
      return showToast('This Telegram WebView cannot open the camera directly. Use Choose file instead.', true);
    }
    cameraDialog?.close();
    const dialog = document.createElement('dialog');
    dialog.className = 'camera-capture-dialog';
    dialog.setAttribute('aria-labelledby', 'camera-capture-title');
    dialog.innerHTML = '<header><h2 id="camera-capture-title">Take photo</h2><button type="button" class="icon-button" data-camera-cancel aria-label="Close camera">'+iconSvg('close')+'</button></header><p>Keep the whole document in the frame.</p><div class="evidence-camera-stage"><video autoplay playsinline muted></video><canvas hidden></canvas></div><footer><button type="button" class="btn btn-secondary" data-camera-cancel>Cancel</button><button type="button" class="btn btn-primary" id="evidence-camera-capture" disabled>Use photo</button></footer>';
    document.body.append(dialog);
    cameraDialog = dialog;
    let stream = null, closed = false;
    const cleanup = () => {
      if (closed) return;
      closed = true;
      stream?.getTracks().forEach(track => track.stop());
      if (activeCameraStream === stream) activeCameraStream = null;
      if (cameraDialog === dialog) cameraDialog = null;
      dialog.remove();
      syncTelegramControls();
      if (trigger?.isConnected) trigger.focus();
    };
    dialog.addEventListener('close', cleanup, {once:true});
    dialog.querySelectorAll('[data-camera-cancel]').forEach(button => button.onclick = () => {dialog.close();cleanup();});
    const capture = dialog.querySelector('#evidence-camera-capture');
    const video = dialog.querySelector('video');
    dialog.showModal();syncTelegramControls();
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' } }, audio: false,
      });
      if (closed || !dialog.isConnected) {stream.getTracks().forEach(track => track.stop());return;}
      activeCameraStream = stream;
      video.srcObject = stream;
      await video.play();
      if (!closed) capture.disabled = false;
    } catch (_) {
      dialog.close();cleanup();
      return showToast('Camera access was unavailable. Allow camera permission or use Choose file.', true);
    }
    capture.onclick = async () => {
      if (!video.videoWidth || !video.videoHeight) return showToast('The camera is still starting. Try again.', true);
      capture.disabled = true;
      const canvas = dialog.querySelector('canvas');
      const maximum = 2000;
      const scale = Math.min(1, maximum / Math.max(video.videoWidth, video.videoHeight));
      canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
      canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
      canvas.getContext('2d')?.drawImage(video, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.88));
      if (closed) return;
      if (!blob) { capture.disabled = false; return showToast('The photo could not be captured. Try again.', true); }
      const file = new File([blob], `evidence-${Date.now()}.jpg`, { type: 'image/jpeg' });
      dialog.close();cleanup();
      if (onCapture) onCapture(file);
      else await uploadEvidenceFile(file, requirementKey, trigger);
    };
  }

  async function removeEvidence(evidenceId) {
    if (!(await saveDraft(true))) return;
    const result = await postJson(`/evidence/${evidenceId}/remove/`, { revision: current.revision });
    if (!result.ok) return showToast(result.data?.error || 'Could not remove the evidence.', true);
    current = result.data.application;
    renderEditor(current, step);
    showToast('Evidence removed from the active requirement.');
  }

  async function openEvidence(evidenceId, filename = 'Evidence', mimeType = '') {
    const pdfViewer = mimeType === 'application/pdf' ? window.open('', '_blank', 'noopener') : null;
    if (pdfViewer) {
      try { pdfViewer.document.title = 'Loading evidence'; pdfViewer.document.body.textContent = 'Loading evidence…'; } catch (_) { /* Cross-window access may be restricted. */ }
    }
    const key = requestKey('evidence-read');
    const result = await apiFetch(`/evidence/${evidenceId}/download/`, {
      headers: { 'X-Request-ID': key },
    });
    if (!result.ok || !result.blob) {
      pdfViewer?.close?.();
      return showToast(result.data?.error || 'Could not open the evidence.', true);
    }
    const url = URL.createObjectURL(result.blob);
    if (result.blob.type.startsWith('image/')) {
      const overlay = document.getElementById('document-preview-overlay');
      previewReturnFocus = document.activeElement;
      document.getElementById('preview-title').textContent = filename || 'Evidence image';
      document.getElementById('preview-page').textContent = 'Uploaded evidence';
      document.getElementById('document-preview-image').src = url;
      document.querySelector('.preview-toolbar').hidden = true;
      previewUrl = url;
      evidencePreviewUrl = url;
      overlay.hidden = false;
      overlay.setAttribute('aria-hidden', 'false');
      document.body.classList.add('origination-modal-open');
      bindPreviewPinch();
      previewGestures?.reset();
      syncTelegramControls();
      return;
    }
    const viewer = pdfViewer || window.open('', '_blank', 'noopener');
    if (viewer) viewer.location.replace(url);
    else {
      const link = document.createElement('a');
      link.href = url; link.target = '_blank'; link.rel = 'noopener'; link.download = filename || 'evidence.pdf';
      document.body.append(link); link.click(); link.remove();
    }
    window.setTimeout(() => URL.revokeObjectURL(url), 120000);
  }

  async function saveSigningRequirements() {
    const signingRequirements = (current?.product_terms?.requirements || []).filter(item =>
      item.enforcement_stage === 'signing' && item.type !== 'document'
      && (!item.workflow || item.workflow === 'loan_origination')
    );
    if (!signingRequirements.length) return true;
    const configuration = collectProductConfiguration();
    const result = await postJson(`/applications/${current.id}/signing-requirements/`, {
      revision: current.revision,
      product_requirement_evidence: configuration.requirements,
    });
    if (!result.ok) {
      if (result.data?.errors) showServerErrors(result.data.errors);
      showToast(result.data?.error || 'Could not save signing requirements.', true);
      return false;
    }
    current = result.data.application;
    return true;
  }


  function collectSupportingDocumentPayload(document) {
    const payload = { ...(document?.field_payload || {}) };
    if (current?.form_projection_version === 1 || current?.value_contract_version === 2) {
      const active = new Set((document?.schema?.fields || []).filter(field => documentOwnsInput(field, document) && field.value_contract?.scope !== 'application').map(field => field.key));
      for (const key of Object.keys(payload)) if (!active.has(key)) delete payload[key];
    }
    root().querySelectorAll('[data-repeatable-field]').forEach(container => {
      payload[container.dataset.repeatableField] = [...container.querySelectorAll('[data-repeat-row]')].map(row => {
        const item = { row_id: row.dataset.rowId || newRowId() };
        row.querySelectorAll('[data-repeat-column]').forEach(input => {
          const column = (document?.schema?.fields || []).find(field => field.key === container.dataset.repeatableField)?.structure?.columns?.find(field => field.key === input.dataset.repeatColumn);
          item[input.dataset.repeatColumn] = column?.type === 'boolean' && input.value !== '' ? input.value === 'true' : input.value.trim();
        });
        return item;
      });
    });
    root().querySelectorAll('[data-document-field]').forEach(input => {
      if (input.disabled) return;
      if (input.options && ['true', 'false'].includes(input.value)) payload[input.dataset.documentField] = input.value === 'true';
      else payload[input.dataset.documentField] = input.value;
    });
    return payload;
  }

  async function saveSupportingDocument(documentKey) {
    if (wizardSections()[step]?.document?.key !== documentKey) return false;
    return saveDraft(true);
  }

  async function openSupportingPreview(documentKey, allowIncomplete = false) {
    await openPreview(documentKey, allowIncomplete);
  }

  async function openPacketPreview() {
    await openPreview('__packet__');
  }

  function bindEditor(editable) {
    root().querySelectorAll('[data-id-capture]').forEach(button => button.onclick = () => openIdentityCapture(button.dataset.idCapture,button));
    const browseSection = async direction => {
      if (syncConflict) return showToast('Choose which draft to keep first.', 'warning');
      const target = wizardSections()[step + direction];
      if (target) await goToSection(target.key);
    };
    document.getElementById('section-previous')?.addEventListener('click', () => browseSection(-1));
    document.getElementById('section-next')?.addEventListener('click', () => browseSection(1));
    document.getElementById('origination-refresh-signing')?.addEventListener('click', event => {
      void runPrimaryAction('Refreshing...', () => refreshCurrentSigning({ manual: true }), event.currentTarget, 'Updated');
    });
    document.getElementById('recovery-retry-refresh')?.addEventListener('click', () => {
      if (conflictDraft) void reconcileSavedDraftConflict(conflictDraft, true);
    });
    document.getElementById('recovery-use-server')?.addEventListener('click', async () => {
      if (!conflictServerLoaded) return;
      await removeRecoveryDraft(current.id);
      syncConflict = false; conflictDraft = null; conflictServerLoaded = false; dirty = false; pendingSaveRequestId = '';
      syncCloseProtection();
      renderFreshEditor(current, step);
    });
    document.getElementById('recovery-restore-phone')?.addEventListener('click', () => {
      if (!conflictServerLoaded || !conflictDraft) return;
      const phoneDraft = conflictDraft;
      current.form_payload = phoneDraft.payload || current.form_payload;
      restoreDocumentDraft(phoneDraft);
      current.product_requirements = phoneDraft.configuration?.requirements || current.product_requirements;
      current.product_custom_values = phoneDraft.configuration?.customValues || current.product_custom_values;
      current.product_selected_fee_keys = phoneDraft.configuration?.selectedFeeKeys || current.product_selected_fee_keys;
      syncConflict = false; conflictDraft = null; conflictServerLoaded = false; dirty = true; editGeneration += 1;
      syncCloseProtection();
      pendingSaveRequestId = requestKey('save');
      renderFreshEditor(current, step);
      void saveDraft(true);
    });
    document.getElementById('origination-back').onclick = exitEditor;
    document.getElementById('origination-section-picker')?.addEventListener('click', event => openSectionSheet(event.currentTarget));
    root().querySelectorAll('[data-edit-step]').forEach(button => button.onclick = async () => {
      const targetStep = Number(button.dataset.editStep);
      const targetSection = wizardSections()[targetStep];
      if (current.status === 'draft' && targetSection) unlockedDraftSections.add(targetSection.key);
      if (targetSection) await goToSection(targetSection.key);
    });
    document.getElementById('origination-edit-section')?.addEventListener('click', () => {
      const section = wizardSections()[step];
      if (section) unlockedDraftSections.add(section.key);
      renderEditor(current, step);
    });
    root().querySelectorAll('[data-correction-jump]').forEach(button => button.onclick = () => {
      const targetStep = correctionTargetStep(button.dataset.correctionJump);
      if (targetStep >= 0) renderEditor(current, targetStep);
    });
    root().querySelectorAll('[data-correction-target]').forEach(input => input.onchange = () => {
      const instruction = root().querySelector(`[data-correction-instruction="${CSS.escape(input.dataset.correctionTarget)}"]`);
      if (input.checked) reviewTargets.set(input.dataset.correctionTarget, {
        target_type: input.dataset.targetType,
        target_key: input.dataset.targetKey,
        target_label: input.dataset.targetLabel,
        instruction: instruction?.value?.trim() || '',
      });
      else reviewTargets.delete(input.dataset.correctionTarget);
      if (instruction) {
        instruction.hidden = !input.checked;
        instruction.disabled = !input.checked;
        if (input.checked) instruction.focus();
      }
    });
    root().querySelectorAll('[data-correction-instruction]').forEach(input => input.oninput = () => {
      const item = reviewTargets.get(input.dataset.correctionInstruction);
      if (item) item.instruction = input.value;
    });
    root().querySelectorAll('[data-evidence-upload]').forEach(input => input.onchange = () => uploadEvidence(input));
    root().querySelectorAll('[data-evidence-camera]').forEach(button => button.onclick = () => openEvidenceCamera(button.dataset.evidenceCamera, button));
    root().querySelectorAll('[data-evidence-remove]').forEach(button => button.onclick = () => removeEvidence(button.dataset.evidenceRemove));
    root().querySelectorAll('[data-evidence-open]').forEach(button => button.onclick = () => openEvidence(button.dataset.evidenceOpen, button.dataset.evidenceName, button.dataset.evidenceMime));
    root().querySelectorAll('[data-support-preview]').forEach(button => button.onclick = async () => {
      if (editable && !(await saveSupportingDocument(button.dataset.supportPreview))) return;
      const sectionKey = wizardSections()[step]?.key || '';
      const errors = sectionErrors(sectionKey); showErrors(errors);
      const selected = current.document_packet?.documents?.find(item => item.key === button.dataset.supportPreview);
      const incomplete = Object.keys(errors).length > 0 || Boolean(selected?.missing_fields?.length);
      if (incomplete && !window.confirm('Some details are missing. Preview this document as it is?')) return;
      await openSupportingPreview(button.dataset.supportPreview, incomplete);
    });
    root().querySelectorAll('[data-repeatable-field]').forEach(container => {
      refreshRepeatableField(container);
      container.querySelector('[data-repeat-add]')?.addEventListener('click', () => {
        const document = wizardSections()[step]?.document;
        const field = container.dataset.mainRepeatable
          ? (current?.form_schema?.fields || []).find(item => item.key === container.dataset.mainRepeatable)
          : (document?.schema?.fields || []).find(item => item.key === container.dataset.repeatableField);
        const rows = container.querySelectorAll('[data-repeat-row]');
        if (!field || rows.length >= Number(container.dataset.maxItems || 11)) return;
        container.querySelector('.repeatable-rows').insertAdjacentHTML(
          'beforeend', repeatableRowMarkup(field.structure?.columns || [], {}, rows.length, false, false, container.dataset.itemLabel || repeatableItemLabel(field), container.dataset.repeatableGrid || repeatableGridStyle(field)),
        );
        syncNativeDateDisplays(container);
        refreshRepeatableField(container);
        if (editable) scheduleSave();
      });
      container.addEventListener('click', event => {
        const remove = event.target.closest('[data-repeat-remove]');
        if (!remove) return;
        remove.closest('[data-repeat-row]')?.remove();
        refreshRepeatableField(container);
        if (editable) scheduleSave();
      });
      container.addEventListener('input', () => {
        refreshRepeatableField(container);
        if (editable) scheduleSave();
      });
      container.addEventListener('change', event => {
        if (event.target.matches?.('.native-date-control input[type="date"]')) {
          syncNativeDateDisplays(event.target.closest('.native-date-control'));
        }
      });
    });
    document.getElementById('origination-packet-preview')?.addEventListener('click', openPacketPreview);
    if (editable && !wizardSections()[step]?.key?.startsWith('document:')) {
      root().querySelectorAll('.laf-grid').forEach(grid => grid.addEventListener('input', scheduleSave));
      if (wizardSections()[step]?.key === facilitySectionKey()) {
        root().querySelectorAll('.laf-grid').forEach(grid => grid.addEventListener('input', scheduleCommercialQuotePreview));
      }
    }
    else if (editable) {
      root().querySelectorAll('.laf-grid').forEach(grid => grid.addEventListener('input', scheduleSave));
    } else if (current.status === 'reviewed' && capabilities.can_start_signing) {
      root().querySelector('.laf-grid')?.addEventListener('input', () => {
        const configuration = collectProductConfiguration();
        current.product_requirements = configuration.requirements;
        setSaveState('Signing requirements not saved', 'dirty');
      });
    }
    root().querySelectorAll('.native-date-control input[type="date"]').forEach(input => input.addEventListener('change', () => {
      syncNativeDateDisplays(input.closest('.native-date-control'));
      if (input.dataset.field || input.dataset.documentField) scheduleSave();
      if (wizardSections()[step]?.key === facilitySectionKey()) scheduleCommercialQuotePreview();
    }));
    root().querySelector('[data-clear-guarantor-two]')?.addEventListener('click', event => runPrimaryAction('Clearing...', async () => {
      const keys = (current.form_schema?.fields || []).filter(field => field.key.startsWith('guarantor_2_')).map(field => field.key);
      if (!editable || keys.some(key => !correctionAllows('field', key))) return showToast('Only the requested corrections can be changed.', 'warning');
      window.clearTimeout(saveTimer);
      const payload = collectPayload();
      const links = {...payload._person_role_bindings};
      delete links.guarantor_2;
      payload._person_role_bindings = links;
      keys.forEach(key => { payload[key] = ''; });
      current.form_payload = payload;
      const select = root().querySelector('[data-person-link="guarantor_2"]');
      if (select) select.value = '';
      for (const key of keys) root().querySelectorAll(`[data-field="${CSS.escape(key)}"]`).forEach(input => {
        if (input.type === 'checkbox' || input.type === 'radio') input.checked = false;
        else input.value = '';
      });
      syncNativeDateDisplays(root());
      scheduleSave();
      if (!(await saveDraft(false))) { showToast('Could not save the cleared guarantor. Keep this page open and retry.', 'error'); return false; }
      renderFreshEditor(current, step);
      showToast('Guarantor 2 cleared.', 'success');
      return true;
    }, event.currentTarget));
    root().querySelectorAll('[data-location-type="county"]').forEach(input => input.addEventListener('change', syncOriginationSubCountySelect));
    root().querySelectorAll('[data-person-link]').forEach(input => input.addEventListener('change', () => runPrimaryAction('Saving...', async () => {
      const previous = current?.form_payload?._person_role_bindings?.[input.dataset.personLink] || '';
      if (input.value && !window.confirm('Use this person’s name, ID and phone for this guarantor? They will stay linked.')) {input.value=previous; return;}
      scheduleSave();
      if (await saveDraft(true)) renderEditor(current, step);
    })));
    document.getElementById('origination-preview')?.addEventListener('click', () => {
      const selectedDocuments = (current?.document_packet?.documents || []).filter(item => item.selected);
      if (wizardSections()[step]?.key === 'review' && selectedDocuments.length > 1 && !current?.review_packet_ready && !hasFinalSignedPacket()) {
        return openPacketPreview();
      }
      return openPreview();
    });
    document.getElementById('origination-preview-early')?.addEventListener('click', () =>
      (current.document_packet?.documents || []).filter(item => item.selected).length > 1 ? openPacketPreview() : openPreview());
    document.getElementById('origination-confirm-signing')?.addEventListener('click', () => runPrimaryAction('Preparing documents...', async () => {
      if (['draft','correction_required'].includes(current.status) && !validateSubmission()) return;
      if (['draft', 'correction_required'].includes(current.status) && !(await saveDraft(true))) return;
      if (['draft', 'correction_required'].includes(current.status) && previewedRevision !== current.revision) {
        return showToast('Preview the saved document bundle before continuing.', true);
      }
      const result = await postJson(`/applications/${current.id}/confirm-signing/`, { revision: current.revision });
      if (!result.ok) {
        if (result.data?.errors) showServerErrors(result.data.errors);
        return showToast(result.data?.error || 'Could not prepare the documents for signing.', true);
      }
      current = result.data.application;
      showToast('Documents ready. Signing can begin.');
      renderEditor(current, wizardSections().length - 1);
    }));
    document.getElementById('origination-submit')?.addEventListener('click', () => runPrimaryAction('Submitting...', async () => {
      if (!validateSubmission()) return;
      if (!(await saveDraft(true))) return;
      if (previewedRevision !== current.revision) return showToast('Preview the filled document for this saved revision before submitting.', true);
      const result = await postJson(`/applications/${current.id}/submit/`, { revision: current.revision });
      if (!result.ok) {
        if (result.data?.errors) showServerErrors(result.data.errors);
        return showToast(result.data?.error || 'Could not submit the application.', true);
      }
      current = result.data.application;
      showToast(current.status === 'completed' ? 'Application completed.' : 'Application submitted.');
      if (current.status === 'completed') renderEditor(current, wizardSections().length - 1);
      else await load();
    }));
    root().querySelectorAll('[data-review]').forEach(button => button.onclick = async () => {
      const decision = button.dataset.review;
      if (decision === 'request_correction') return submitInlineCorrections();
      if (decision !== 'approve') return openReviewDialog(decision);
      await runPrimaryAction('Recording...', async () => {
        const result = await postJson(`/applications/${current.id}/review/`, {
          ...reviewPacketPayload(), decision, reason: '',
        });
        if (!result.ok) return showToast(result.data?.error || 'Could not record the review.', true);
        showToast('Documents approved. Signing can begin.');
        await load();
      });
    });
    root().querySelectorAll('[data-final-review]').forEach(button => button.onclick = async () => {
      const decision = button.dataset.finalReview;
      if (decision === 'request_correction') return submitInlineCorrections();
      if (decision === 'decline') return openReviewDialog('decline');
      await runPrimaryAction('Approving...', async () => {
        const result = await postJson(`/applications/${current.id}/final-review/`, {
          ...finalReviewPayload(), decision: 'approve', reason: '', correction_items: [],
        });
        if (!result.ok) return showToast(result.data?.error || 'Could not approve the signed application.', true);
        showToast('Signed application approved.');
        await load();
      });
    });
    document.getElementById('origination-takeover-review')?.addEventListener('click', () => openReviewDialog('takeover'));
    document.getElementById('origination-prepare-review')?.addEventListener('click', () => runPrimaryAction('Preparing documents...', async () => {
      if (!(await saveSigningRequirements())) return;
      const result = await postJson(`/applications/${current.id}/prepare-review-packet/`, { revision: current.revision });
      if (!result.ok) {
        if (result.data?.errors) showServerErrors(result.data.errors);
        return showToast(result.data?.error || 'Could not prepare the documents for review.', true);
      }
      current = result.data.application;
      showToast('Documents ready for review.');
      renderEditor(current, wizardSections().length - 1);
    }));
    document.getElementById('origination-start-signing')?.addEventListener('click', () => runPrimaryAction('Starting signing...', async () => {
      const result = await postJson(`/applications/${current.id}/prepare-signing/`, {
        ...reviewPacketPayload(), revision: current.revision,
      });
      if (!result.ok) return showToast(result.data?.error || 'Could not start signing.', true);
      current = result.data.application;
      showToast('Documents ready for signing links.');
      renderEditor(current, wizardSections().length - 1);
    }));
    document.getElementById('origination-review-packet-preview')?.addEventListener('click', () => openPreview('__review_packet__'));
    document.getElementById('origination-recall')?.addEventListener('click', () => runPrimaryAction('Checking...', () => recallApplication()));
    root().querySelectorAll('[data-test-sign-slot]').forEach(button => button.addEventListener('click', async () => {
      if (button.dataset.slotType === 'signature') return openSignatureSheet(button);
      const stampAssetId = button.dataset.slotType === 'stamp'
        ? button.parentElement.querySelector('[data-test-stamp-select]')?.value || '' : '';
      if (button.dataset.slotType === 'stamp' && !stampAssetId) return showToast('Choose an approved test stamp.', true);
      await runPrimaryAction('Recording TEST action...', async () => {
        const result = await postJson(`/applications/${current.id}/test-signing/action/`, {
          revision: current.revision, package_id: button.dataset.packageId,
          document_key: button.dataset.documentKey, slot_key: button.dataset.slotKey,
          signer_role: button.dataset.signerRole, participant_id: button.dataset.participantId || '', stamp_asset_id: stampAssetId,
        });
        if (!result.ok) return showToast(result.data?.error || 'Could not simulate this signing slot.', true);
        current = result.data.application;
        renderEditor(current, wizardSections().length - 1);
        showToast('TEST signing action recorded.');
      });
    }));
    root().querySelectorAll('[data-create-signer-session]').forEach(button => button.addEventListener('click', async () => {
      await runPrimaryAction('Creating signer session...', async () => {
        const result = await postJson(`/applications/${current.id}/signer-sessions/`, {
          package_id: button.dataset.packageId, signer_role: button.dataset.signerRole, participant_id: button.dataset.participantId || '',
          access_mode: button.dataset.accessMode,
        });
        if (!result.ok && result.data?.code === 'origination_shared_signer_phone' && capabilities.is_superuser) {
          const shared = result.data?.details || {};
          openAuditedReasonDialog({
            eyebrow: 'Security confirmation',
            title: 'Confirm shared signer phone',
            hint: `${shared.roles || 'Multiple signers'} use the same phone${shared.phone_last4 ? ` ending ${shared.phone_last4}` : ''}. Explain why this is intentional. Your reason is saved with this application and these signer roles.`,
            submitLabel: 'Confirm and send',
            returnFocus: button,
            onSubmit: async overrideReason => runPrimaryAction('Creating signer session...', async () => {
              const overrideResult = await postJson(`/applications/${current.id}/signer-sessions/`, {
                package_id: button.dataset.packageId, signer_role: button.dataset.signerRole, participant_id: button.dataset.participantId || '',
                access_mode: button.dataset.accessMode, shared_phone_override_reason: overrideReason,
              });
              if (!overrideResult.ok) {
                showToast(overrideResult.data?.error || 'Could not create the signer session.', true);
                return false;
              }
              if (button.dataset.accessMode === 'assisted' && overrideResult.data.signer_session?.url) {
                window.open(overrideResult.data.signer_session.url, '_blank', 'noopener');
              }
              await load();
              showToast(button.dataset.accessMode === 'assisted' ? 'Assisted signing session opened.' : 'Signing invitation sent.');
              return true;
            }),
          });
          return;
        }
        if (!result.ok) return showToast(result.data?.error || 'Could not create the signer session.', true);
        if (button.dataset.accessMode === 'assisted' && result.data.signer_session?.url) window.open(result.data.signer_session.url, '_blank', 'noopener');
        await load();
        showToast(button.dataset.accessMode === 'assisted' ? 'Assisted signing session opened.' : 'Signing invitation sent.');
      });
    }));
    root().querySelectorAll('[data-reset-signer-session]').forEach(button => button.addEventListener('click', async () => {
      const targetMode = button.dataset.targetAccessMode || button.dataset.accessMode || 'self_service';
      const switching = button.dataset.switchMode === 'true' && targetMode !== button.dataset.accessMode;
      openAuditedReasonDialog({
        title: switching ? `Switch to ${targetMode === 'assisted' ? 'assisted' : 'remote'} signing` : 'Reset signing link',
        hint: switching
          ? 'The previous link will be revoked and the mode change will be retained in the audit trail.'
          : 'The previous link will be revoked. Record why this signer needs a new link.',
        submitLabel: switching ? 'Revoke and switch' : 'Revoke and reissue',
        returnFocus: button,
        onSubmit: async reason => runPrimaryAction('Resetting signer session...', async () => {
          const result = await postJson(`/applications/${current.id}/signer-sessions/reset/`, {
            session_id: button.dataset.sessionId, reason, access_mode: targetMode,
          });
          if (!result.ok) {
            showToast(result.data?.error || 'Could not reset the signer session.', true);
            return false;
          }
          const resultMode = result.data.signer_session?.access_mode || targetMode;
          if (resultMode === 'assisted' && result.data.signer_session?.url) {
            window.open(result.data.signer_session.url, '_blank', 'noopener');
          }
          await load();
          showToast(resultMode === 'assisted' ? 'Assisted signing opened on this device.' : 'Remote signing invitation sent.');
          return true;
        }),
      });
    }));
    root().querySelectorAll('[data-staff-sign]').forEach(button => button.addEventListener('click', () => openSignatureSheet(button, true)));
    root().querySelectorAll('[data-approval-preview]').forEach(button => button.addEventListener('click', () => openPreview('__signing_packet__')));
    root().querySelectorAll('[data-production-stamp]').forEach(button => button.addEventListener('click', () => runPrimaryAction('Applying production stamp...', async () => {
      const stampAssetId = button.parentElement.querySelector('[data-production-stamp-select]')?.value || '';
      if (!stampAssetId) return showToast('Choose an active production stamp.', true);
      const result = await postJson(`/applications/${current.id}/production-stamp/`, {
        revision: current.revision, package_id: button.dataset.packageId,
        document_key: button.dataset.documentKey, slot_key: button.dataset.slotKey,
        signer_role: button.dataset.signerRole, participant_id: button.dataset.participantId || '', stamp_asset_id: stampAssetId,
      });
      if (!result.ok) return showToast(result.data?.error || 'Could not apply the production stamp.', true);
      await load(); showToast('Production stamp applied.');
    })));
    document.getElementById('origination-archive-signed')?.addEventListener('click', event => runPrimaryAction('Saving signed documents...', async () => {
      const result = await postJson(`/applications/${current.id}/archive-signed/`, {package_id:event.currentTarget.dataset.packageId});
      if (!result.ok) return showToast(result.data?.error || 'Could not save the signed documents.', true);
      await load(); showToast('Signed documents saved.');
    }));
    document.getElementById('origination-view-signed')?.addEventListener('click', () => openPreview('__signed_packet__'));
    document.getElementById('origination-open-signed-pdf')?.addEventListener('click', event => openSignedPacketPdf(event.currentTarget.dataset.packageId));
    document.getElementById('origination-test-signing-preview')?.addEventListener('click', () => openPreview('__test_signing__'));
  }

  async function openSignedPacketPdf(packageId) {
    const viewer = window.open('', '_blank');
    const key = requestKey('signed-packet-open');
    const result = await apiFetch(`/applications/${current.id}/signed-packet/?package_id=${encodeURIComponent(packageId)}`, {
      headers: { 'X-Request-ID': key },
    });
    if (!result.ok || !result.blob) {
      try { viewer?.close?.(); } catch (_) { /* Ignore a browser-owned viewer failure. */ }
      return showToast(result.data?.error || 'Could not open the signed application.', true);
    }
    const url = URL.createObjectURL(result.blob);
    if (viewer && !viewer.closed) viewer.location.replace(url);
    else {
      const link = document.createElement('a');
      link.href = url;
      link.target = '_blank';
      link.rel = 'noopener';
      document.body.appendChild(link);
      link.click();
      link.remove();
    }
    window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    showToast('Opening the signed PDF.');
  }

  function openDownloadSheet(trigger) {
    const choices = current.download_choices || [{document_key:'',label:'All documents',description:'Combined PDF',available:true}];
    openSheet({mode:'downloads',eyebrow:'',title:'Download',trigger,
      body:`<div class="document-download-list">${choices.map((choice,index) => `<button type="button" class="document-download-choice" data-download-choice="${index}" aria-label="Download ${escapeHtml(choice.label)}"${choice.available === false ? ' disabled' : ''}>
        ${iconSvg(choice.document_key ? 'document' : 'documents')}<span><strong>${escapeHtml(choice.label)}</strong><small>${escapeHtml(choice.available === false ? choice.reason || 'Unavailable' : choice.description || 'PDF')}</small></span>${iconSvg('download')}
      </button>`).join('')}</div>`});
    document.querySelectorAll('[data-download-choice]').forEach(button => button.onclick = async () => {
      if (copyDownloadInFlight) return;
      const choice = choices[Number(button.dataset.downloadChoice)];
      if (!choice || choice.available === false) return;
      copyDownloadInFlight = true;
      closeSheet();
      const control = document.getElementById('origination-download');
      if (control) {control.disabled=true;control.setAttribute('aria-busy','true');}
      showToast('Preparing PDF…','info');
      try {await downloadApplication(choice.document_key || '');}
      catch (_) {showToast('Could not prepare this document. Please try again.','error');}
      finally {
        copyDownloadInFlight=false;
        const currentControl=document.getElementById('origination-download');
        if (currentControl) {currentControl.disabled=false;currentControl.removeAttribute('aria-busy');}
      }
    });
  }

  async function downloadApplication(documentKey = '') {
    if (!await saveDraft(true)) return;
    const revision = current.revision;
    const selection = {revision,document_key:documentKey};
    let result = await postJson(`/applications/${current.id}/download/`, selection);
    if (result.data?.code === 'incomplete_copy_confirmation_required') {
      const message = result.data.error;
      const telegram = window.Telegram?.WebApp;
      const confirmed = typeof telegram?.showPopup === 'function'
        ? await new Promise(resolve => telegram.showPopup({title:'Download application', message,
          buttons:[{id:'download',type:'default',text:'Download'},{type:'cancel'}]}, id => resolve(id === 'download')))
        : window.confirm(message);
      if (!confirmed) {showToast('Download cancelled.','info');return;}
      result = await postJson(`/applications/${current.id}/download/`, {...selection, allow_incomplete:true});
    }
    if (!result.ok) {
      if (result.data?.errors) showServerErrors(result.data.errors);
      return showToast(result.data?.error || 'Could not prepare this application.', 'error');
    }
    const {download_url:url, filename} = result.data;
    if (!url || !filename) return showToast('The download is unavailable. Please try again.', 'error');
    const fallback = () => {
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = filename;
      anchor.rel = 'noopener'; anchor.target = '_blank'; document.body.appendChild(anchor); anchor.click(); anchor.remove();
      showToast(`Download requested: ${filename}`, 'info');
    };
    const tg = window.Telegram?.WebApp;
    if (typeof tg?.downloadFile === 'function' && (!tg.isVersionAtLeast || tg.isVersionAtLeast('8.0'))) {
      try {
        tg.downloadFile({url, file_name:filename}, accepted => {
          showToast(accepted ? `Download requested: ${filename}` : 'Download cancelled.', 'info');
        });
      } catch (_) { fallback(); }
    } else fallback();
  }

  async function openPreview(documentKey = '', allowIncomplete = false) {
    // Event listeners must call this through a wrapper. Keep a defensive
    // fallback too, so a future direct binding cannot turn a PointerEvent into
    // a document-key URL segment.
    if (typeof documentKey !== 'string') documentKey = '';
    documentKey = resolveLatestPreviewKey(documentKey);
    if (['draft', 'correction_required'].includes(current.status) && !(await saveDraft(true))) return;
    previewDocumentKey = documentKey;
    previewAllowIncomplete = allowIncomplete;
    previewSucceeded = false;
    clearPreviewPageCache();
    previewPage = 1; previewZoom = 100; previewPageCount = 1;
    previewRequestId = requestKey('preview');
    document.querySelector('.preview-toolbar').hidden = false;
    const overlay = document.getElementById('document-preview-overlay');
    const title = document.getElementById('preview-title');
    if (title) title.textContent = documentKey === '__signed_packet__'
      ? 'Signed application'
      : documentKey === '__signing_packet__' ? 'Document bundle'
      : documentKey === '__review_packet__' ? 'Document bundle for review'
      : documentKey === '__packet__' ? 'Document bundle'
      : documentKey === '__test_signing__' ? 'TEST signed application'
      : 'Filled loan document';
    previewReturnFocus = document.activeElement;
    overlay.hidden = false;
    overlay.setAttribute('aria-hidden', 'false');
    document.body.classList.add('origination-modal-open');
    bindPreviewPinch();
    previewGestures?.reset();
    syncTelegramControls();
    window.requestAnimationFrame(() => document.getElementById('preview-close')?.focus());
    await loadPreviewPage();
  }

  async function fetchPreviewPage(pageNumber) {
    if (previewPageUrls.has(pageNumber)) {
      const cached = previewPageUrls.get(pageNumber);
      previewPageUrls.delete(pageNumber);
      previewPageUrls.set(pageNumber, cached);
      return cached;
    }
    if (previewPageLoads.has(pageNumber)) return previewPageLoads.get(pageNumber);
    let key = previewRequestId || requestKey('preview');
    const applicationId = current.id;
    const revision = current.revision;
    const individualSigned = hasFinalSignedPacket() && previewDocumentKey && !previewDocumentKey.startsWith('__');
    const signedPacketPreview = individualSigned || ['__signed_packet__', '__signing_packet__'].includes(previewDocumentKey);
    const previewPath = signedPacketPreview
      ? `/applications/${applicationId}/${previewDocumentKey === '__signing_packet__' ? 'current-signing-packet' : 'signed-packet'}/?package_id=${encodeURIComponent(current?.signing_package?.id || '')}&preview_format=image&page=${pageNumber}${individualSigned ? `&document_key=${encodeURIComponent(previewDocumentKey)}` : ''}`
      : previewDocumentKey === '__review_packet__'
      ? `/applications/${applicationId}/review-packet/preview/`
      : previewDocumentKey === '__test_signing__'
      ? `/applications/${applicationId}/test-signing/preview/`
      : previewDocumentKey === '__packet__'
      ? `/applications/${applicationId}/packet/preview/`
      : previewDocumentKey
      ? `/applications/${applicationId}/documents/${encodeURIComponent(previewDocumentKey)}/preview/`
      : `/applications/${applicationId}/preview/`;
    const requestPreview = () => apiFetch(previewPath, signedPacketPreview ? {
      headers: { 'X-Request-ID': key },
    } : {
      method: 'POST', headers: { 'Idempotency-Key': key, 'X-Request-ID': key }, body: JSON.stringify({
        revision, request_id: key, preview_format: 'image', page: pageNumber, allow_incomplete:previewAllowIncomplete,
        package_id: ['__test_signing__', '__review_packet__'].includes(previewDocumentKey) ? current?.signing_package?.id : undefined,
        unsigned_document_hash: previewDocumentKey === '__review_packet__' ? current?.signing_package?.unsigned_document_hash : undefined,
        review_scope_sha256: previewDocumentKey === '__review_packet__' ? current?.signing_package?.review_scope_sha256 : undefined,
      }),
    });
    const pending = (async () => {
      let result = await requestPreview();
      if (pageNumber === 1 && !previewAllowIncomplete && result.data?.code === 'incomplete_preview_confirmation_required'
          && key === previewRequestId && current?.id === applicationId && current?.revision === revision) {
        if (!window.confirm('Some required details are missing. Preview this copy as it is? It will not be ready for submission.')) return {cancelled:true};
        previewAllowIncomplete = true;
        key = previewRequestId = requestKey('incomplete-preview');
        result = await requestPreview();
      }
      return result;
    })().then(result => {
      if (key !== previewRequestId || current?.id !== applicationId || current?.revision !== revision) return { stale: true };
      if (result.cancelled) return {cancelled:true};
      if (!result.ok || !result.blob) return { error: result.data?.error || 'Could not generate the filled document.' };
      const entry = { url: URL.createObjectURL(result.blob), pageCount: Math.max(1, result.pageCount || 1), packetVersion: result.packetVersion || '' };
      if (signedPacketPreview && result.packetVersion) previewPacketVersion = result.packetVersion;
      if (previewDocumentKey === '__signing_packet__' && pageNumber === 1 && result.packetVersion) {
        approvalReview = { packageId: current.signing_package.id, revision, version: result.packetVersion };
      }
      previewPageUrls.set(pageNumber, entry);
      if (!previewDocumentKey && pageNumber === 1) {
        previewedRevision = current.revision;
        previewSucceeded = true;
      }
      if (previewDocumentKey === '__packet__' && pageNumber === 1 && result.previewComplete) {
        previewedRevision = current.revision;
        previewSucceeded = true;
        (current?.document_packet?.documents || []).filter(item => item.selected).forEach(item => {
          item.previewed = true;
        });
        if (current?.document_packet) current.document_packet.primary_ready = true;
      }
      if (previewDocumentKey && !['__packet__', '__review_packet__', '__test_signing__', '__signed_packet__', '__signing_packet__'].includes(previewDocumentKey) && pageNumber === 1) {
        const document = current?.document_packet?.documents?.find(item => item.key === previewDocumentKey);
        if (document && result.previewComplete) document.previewed = true;
      }
      while (previewPageUrls.size > 3) {
        const discardPage = [...previewPageUrls.keys()].find(item => item !== previewPage);
        if (discardPage == null) break;
        URL.revokeObjectURL(previewPageUrls.get(discardPage).url);
        previewPageUrls.delete(discardPage);
      }
      return entry;
    }).finally(() => {
      if (previewPageLoads.get(pageNumber) === pending) previewPageLoads.delete(pageNumber);
    });
    previewPageLoads.set(pageNumber, pending);
    return pending;
  }

  async function loadPreviewPage() {
    const requestedPage = previewPage;
    const wasCached = previewPageUrls.has(requestedPage);
    if (!wasCached) showToast('Generating filled PDF…');
    const entry = await fetchPreviewPage(requestedPage);
    if (entry?.cancelled) {dismissPreviewProgressToast();closePreview();return;}
    if (entry?.error) { return showToast(entry.error + ' Use Refresh to try again.', true); }
    if (!entry || entry.stale || requestedPage !== previewPage) return;
    previewUrl = entry.url;
    previewPageCount = entry.pageCount;
    updatePreviewFrame();
    dismissPreviewProgressToast();
    [requestedPage - 1, requestedPage + 1]
      .filter(pageNumber => pageNumber >= 1 && pageNumber <= previewPageCount)
      .forEach(pageNumber => { void fetchPreviewPage(pageNumber); });
  }

  function dismissPreviewProgressToast() {
    // The shared runtime owns the visible toast; do not dismiss unrelated feedback.
    ['origination-toast', 'miniapp-shared-toast'].forEach(id => {
      const toast = document.getElementById(id);
      if (!toast || toast.textContent !== 'Generating filled PDF…') return;
      if (id === 'miniapp-shared-toast') toast.classList.remove('is-visible');
      else toast.hidden = true;
    });
  }

  function clearPreviewPageCache() {
    previewPageUrls.forEach(entry => URL.revokeObjectURL(entry.url));
    previewPageUrls.clear();
    previewPageLoads.clear();
    previewUrl = '';
  }

  function updatePreviewFrame() {
    const image = document.getElementById('document-preview-image');
    if (image && previewUrl) image.src = previewUrl;
    const page = document.getElementById('preview-page'); if (page) page.textContent = `Page ${previewPage} of ${previewPageCount}`;
    const zoom = document.getElementById('preview-zoom'); if (zoom) zoom.textContent = `${previewZoom}%`;
    const previous = document.getElementById('preview-previous'); if (previous) previous.disabled = previewPage <= 1;
    const next = document.getElementById('preview-next'); if (next) next.disabled = previewPage >= previewPageCount;
  }

  function setPreviewZoom(value, focalPoint) {
    bindPreviewPinch();
    previewGestures?.zoom(value / 100, focalPoint);
  }

  function bindPreviewPinch() {
    const stage = document.getElementById('document-preview-stage');
    const image = document.getElementById('document-preview-image');
    if (!stage || !image || previewGestures) return;
    previewGestures = window.SecureMediaViewer?.bindImageGestures(stage, image, {
      navigateAtEdges: true,
      onNavigate: direction => { if (!evidencePreviewUrl) void navigatePreviewPage(direction); },
      onZoom: scale => {
        previewZoom = Math.round(scale * 100);
        document.getElementById('preview-zoom').textContent = `${previewZoom}%`;
      },
    });
  }

  async function navigatePreviewPage(direction) {
    const requestedPage = previewPage + direction;
    if (requestedPage < 1 || requestedPage > previewPageCount) return;
    previewPage = requestedPage;
    previewGestures?.reset();
    await loadPreviewPage();
    const stage = document.getElementById('document-preview-stage');
    if (stage) { stage.scrollLeft = 0; stage.scrollTop = 0; }
  }

  function closePreview() {
    dismissPreviewProgressToast();
    const wasApprovalPreview = previewDocumentKey === '__signing_packet__' && (current?.approval_roles || []).length;
    const overlay = document.getElementById('document-preview-overlay');
    if (overlay) { overlay.hidden = true; overlay.setAttribute('aria-hidden', 'true'); }
    const image = document.getElementById('document-preview-image'); if (image) image.removeAttribute('src');
    if (evidencePreviewUrl) URL.revokeObjectURL(evidencePreviewUrl);
    evidencePreviewUrl = '';
    document.querySelector('.preview-toolbar').hidden = false;
    clearPreviewPageCache();
    previewRequestId = '';
    previewPacketVersion = '';
    const updateNotice = document.getElementById('preview-update-notice');
    if (updateNotice) updateNotice.hidden = true;
    previewGestures?.dispose();
    previewGestures = null;
    document.body.classList.remove('origination-modal-open');
    syncTelegramControls();
    const returnFocus = previewReturnFocus;
    previewReturnFocus = null;
    previewDocumentKey = '';
    previewSucceeded = false;
    if (wasApprovalPreview) {
      renderEditor(current, step);
      window.requestAnimationFrame(() => root()?.querySelector('[data-staff-sign]')?.focus());
      return;
    }
    window.requestAnimationFrame(() => returnFocus?.focus?.());
  }

  function showToast(message, presentation = 'success') {
    const toast = document.getElementById('origination-toast');
    const settings = typeof presentation === 'object' && presentation
      ? presentation : { tone: presentation === true ? 'error' : String(presentation || 'success') };
    const tone = ['info', 'success', 'warning', 'error'].includes(settings.tone) ? settings.tone : 'info';
    if (window.MiniAppRuntime?.showToast) {
      const shared = window.MiniAppRuntime.showToast(message, { tone, timeout: settings.timeout });
      if (shared) {
        shared.style.zIndex = '30000'; shared.style.bottom = 'auto';
        shared.style.top = 'calc(10px + env(safe-area-inset-top))';
      }
      window.MiniAppUtils?.haptic?.(tone);
      return tone !== 'error';
    }
    if (!toast) return tone !== 'error';
    toast.textContent = message;
    toast.className = `origination-toast ${tone}`;
    toast.setAttribute('role', tone === 'error' ? 'alert' : 'status');
    toast.hidden = false;
    window.MiniAppUtils?.haptic?.(tone);
    window.clearTimeout(showToast.timer);
    if (settings.persistence !== 'until_resolved') {
      showToast.timer = window.setTimeout(() => { toast.hidden = true; }, Number(settings.timeout || 3500));
    }
    return tone !== 'error';
  }

  function renderList({ restoreScroll = false, focusSearch = false } = {}) {
    document.body.classList.remove('origination-editor-open');
    current = null;
    window.clearTimeout(signingRefreshTimer);
    signingRefreshTimer = null;
    step = 0;
    dirty = false;
    syncCloseProtection();
    window.clearTimeout(saveTimer);
    closePreview();
    if (sheetMode) closeSheet({ restoreFocus: false });
    const queueCount = key => {
      return tabCounts[key] ?? '';
    };
    const cards = applications.map(item => {
      const identity = item.applicant_summary || {};
      const applicantName = identity.name || 'Applicant details pending';
      const identifiers = `<span><small>ID</small><span data-card-id-value>${escapeHtml(identity.national_id || 'Not provided')}</span></span><span><small>Phone</small>${identity.phone ? `<span data-miniapp-phone>${escapeHtml(identity.phone)}</span>` : '<span>Not provided</span>'}</span>`;
      return `<article class="application-card" data-application-id="${escapeHtml(item.id)}">
        <div class="application-card-header"><strong>${escapeHtml(applicantName)}</strong><span class="status-chip status-${escapeHtml(item.status)}">${escapeHtml(applicationStatusLabel(item))}</span></div>
        <div class="application-card-meta"><span>${escapeHtml(item.product_name)}</span><span>${escapeHtml(item.branch || 'No branch')}</span><span class="application-reference">${escapeHtml(item.display_reference || item.reference_number)}</span></div>
        <div class="application-card-identifiers">${identifiers}</div>
        <div class="application-card-footer">${capabilities.can_review && item.officer_name ? `<small class="application-officer">${escapeHtml(item.officer_name)}</small>` : ''}<span class="application-card-state"><small class="application-status-text">${escapeHtml(item.next_action || 'View application')}</small>${iconSvg('arrowRight')}</span></div>
        <button type="button" class="application-card-open" data-application-open="${escapeHtml(item.id)}" aria-label="Open application for ${escapeHtml(applicantName)}"></button>
      </article>`;
    }).join('');
    const alerts = ''; // Alerts belong to their application card, never a duplicate list.
    const queueTabs = [
      ['action', 'Needs your action'], ['applications', applicationsLabel],
    ].map(([key, label]) => {
      const count = queueCount(key);
      return `<button type="button" data-queue="${key}" class="queue-tab${listState.queue === key ? ' active' : ''}"><span>${label}</span>${count !== '' ? `<strong>${count}</strong>` : ''}</button>`;
    }).join('');
    const activeChips = [
      ...(listState.signatureOnly ? [{key:'signatureOnly',label:'Awaiting my signature'}] : []),
      ...(listState.productKey ? [{ key: 'productKey', label: filterProducts.find(item => item.product_key === listState.productKey)?.name || listState.productKey }] : []),
      ...(listState.status ? [{ key: 'status', label: statusOptions.find(item => item.value === listState.status)?.label || listState.status }] : []),
    ].map(item => `<button type="button" class="filter-chip" data-remove-filter="${item.key}"><span>${escapeHtml(item.label)}</span>${iconSvg('close')}</button>`).join('');
    const pagination = listState.pages > 1 ? `<div class="pagination-actions"><button type="button" class="btn btn-secondary" id="origination-page-previous"${listState.page <= 1 ? ' disabled' : ''}>Previous</button><span>Page ${listState.page} of ${listState.pages}</span><button type="button" class="btn btn-secondary" id="origination-page-next"${listState.page >= listState.pages ? ' disabled' : ''}>Next</button></div>` : '';
    const startAction = capabilities.can_create ? `<button type="button" class="btn btn-primary compact-start" id="origination-start">${iconSvg('plus')} Start application</button>` : '';
    root().innerHTML = `<section class="list-toolbar"><div><p class="eyebrow">Paperless lending</p><h2>Applications</h2></div><div>${startAction}<button type="button" class="icon-button" id="origination-list-refresh" aria-label="Refresh applications">${iconSvg('refresh')}</button></div></section>${alerts ? `<section class="reviewer-alerts" aria-label="Reviewer alerts"><p class="eyebrow">Attention</p>${alerts}</section>` : ''}<nav class="queue-tabs" aria-label="Origination queues">${queueTabs}</nav><form class="list-search" id="origination-search"><input name="q" value="${escapeHtml(listState.query)}" placeholder="Search applicant, ID, telephone or reference" aria-label="Search applications"><button type="button" class="filter-button${activeChips ? ' active' : ''}" id="origination-open-filters">${iconSvg('filter')}<span>Filters</span>${activeChips ? '<b></b>' : ''}</button></form>${activeChips ? `<div class="active-filters" aria-label="Active filters">${activeChips}</div>` : ''}<div class="list-heading"><h3>${escapeHtml(listState.queue ? listState.queue.replaceAll('_', ' ') : 'Applications')}</h3><span>${listTotal} ${listTotal === 1 ? 'application' : 'applications'}</span></div><div class="application-list">${cards || '<div class="empty-state"><strong>No applications in this queue</strong><span>Change the filters or refresh.</span></div>'}</div>${pagination}`;
    const heading = root().querySelector('.list-heading');
    heading.classList.add('sr-only');
    heading.setAttribute('aria-live', 'polite');
    heading.querySelector('h3').remove();
    root().querySelectorAll('[data-queue]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.queue === listState.queue)));
    for (const item of applications) {
      const card = root().querySelector(`[data-application-id="${CSS.escape(item.id)}"]`);
      if (item.review_alert_id && card) card.dataset.reviewerAlert = item.review_alert_id;
      if (item.review_alert && card) {
        const alert = document.createElement('small');
        alert.className = 'application-review-alert';
        alert.textContent = item.review_alert;
        card.append(alert);
      }
    }
    if (!applications.length) {
      const empty = root().querySelector('.application-list .empty-state');
      if (activeChips || listState.query) {
        empty.innerHTML = '<strong>No matching applications</strong><button type="button" class="btn btn-secondary" id="origination-clear-filters">Clear filters</button>';
        document.getElementById('origination-clear-filters').onclick = () => applyListFilters({status:'', productKey:'', query:'', signatureOnly:false});
      } else if (listState.queue === 'action') {
        empty.innerHTML = '<strong>You’re caught up</strong><button type="button" class="btn btn-secondary" id="origination-view-applications"></button>';
        const button = document.getElementById('origination-view-applications');
        button.textContent = applicationsLabel;
        button.onclick = () => applyListFilters({queue:'applications'});
      }
    }
    root().querySelectorAll('[data-application-open]').forEach(button => button.onclick = async () => {
      const card = button.closest('.application-card');
      listScrollY = window.scrollY;
      button.disabled = true;
      card.setAttribute('aria-busy', 'true');
      const result = await apiFetch(`/applications/${button.dataset.applicationOpen}/`, {});
      button.disabled = false;
      card.removeAttribute('aria-busy');
      if (!result.ok) return showToast(result.data?.error || 'Could not open this application.', true);
      if (card.dataset.reviewerAlert) {
        const seen = await postJson(`/reviewer-notices/${card.dataset.reviewerAlert}/seen/`, {});
        if (seen.ok) reviewerAlerts = reviewerAlerts.filter(item => item.id !== card.dataset.reviewerAlert);
      }
      await openEditor(result.data.application, 0);
    });
    root().querySelectorAll('[data-queue]').forEach(button => button.onclick = () => applyListFilters({ queue: button.dataset.queue }));
    root().querySelectorAll('[data-remove-filter]').forEach(button => button.onclick = () => applyListFilters({ [button.dataset.removeFilter]: '' }));
    document.getElementById('origination-start')?.addEventListener('click', event => openCreationSheet(event.currentTarget));
    document.getElementById('origination-open-filters').onclick = event => openFilterSheet(event.currentTarget);
    document.getElementById('origination-list-refresh').onclick = () => loadApplications();
    const searchForm = document.getElementById('origination-search');
    const searchInput = searchForm.querySelector('input[name="q"]');
    searchInput.oninput = event => {
      window.clearTimeout(listSearchTimer);
      listState.query = String(event.currentTarget.value || '').trim();
      listState.page = 1;
      listRequestGeneration += 1;
      if (!listState.query) return void loadApplications({ focusSearch: true });
      listSearchTimer = window.setTimeout(() => void loadApplications({ focusSearch: true }), 250);
    };
    searchForm.onsubmit = event => {
      event.preventDefault();
      window.clearTimeout(listSearchTimer);
      listState.query = String(new FormData(event.currentTarget).get('q') || '').trim();
      listState.page = 1;
      void loadApplications({ focusSearch: true });
    };
    document.getElementById('origination-page-previous')?.addEventListener('click', async () => { if (listState.page > 1) { listState.page -= 1; window.scrollTo(0, 0); await loadApplications(); } });
    document.getElementById('origination-page-next')?.addEventListener('click', async () => { if (listState.page < listState.pages) { listState.page += 1; window.scrollTo(0, 0); await loadApplications(); } });
    syncTelegramControls();
    if (focusSearch) window.requestAnimationFrame(() => {
      const input = document.querySelector('#origination-search input[name="q"]');
      input?.focus?.();
      input?.setSelectionRange?.(input.value.length, input.value.length);
    });
    else if (restoreScroll) window.requestAnimationFrame(() => window.scrollTo(0, listScrollY));
    else window.requestAnimationFrame(() => window.scrollTo(0, 0));
  }

  async function loadProductsForBranch(branch) {
    const select = document.getElementById('origination-create-product');
    if (!select) return;
    if (!branch) { select.innerHTML = '<option value="">Choose branch first</option>'; select.disabled = true; syncCreationPrimary(); return; }
    select.innerHTML = '<option value="">Loading products…</option>'; select.disabled = true;
    const result = await apiFetch(`/products/?branch=${encodeURIComponent(branch)}`, {});
    if (!result.ok) { select.innerHTML = '<option value="">Could not load products</option>'; syncCreationPrimary(); return showToast(result.data?.error || 'Could not load branch products.', true); }
    products = result.data.products || [];
    select.innerHTML = `<option value="">Choose product</option>${products.map(item => `<option value="${escapeHtml(item.product_key)}"${item.template_ready ? '' : ' disabled'}>${escapeHtml(item.name)}${item.template_ready ? '' : ' — documents unavailable'}</option>`).join('')}`;
    select.disabled = !products.length;
    select.onchange = () => { renderCreationDocuments(); syncCreationPrimary(); };
    renderCreationDocuments();
    syncCreationPrimary();
    if (!products.length) showToast('No active origination product is available for this branch.', true);
  }

  function renderCreationDocuments() {
    const productKey = document.getElementById('origination-create-product')?.value;
    const container = document.getElementById('origination-create-documents');
    if (!container) return;
    const product = products.find(item => item.product_key === productKey);
    if (!product) { container.innerHTML = ''; return; }
    const catalogue = product.document_catalogue || {};
    if (!catalogue.ready) {
      container.innerHTML = `<aside class="notice"><strong>Documents unavailable</strong><span>${escapeHtml((catalogue.reasons || ['This product is not ready for new applications.']).join(' '))}</span></aside>`;
      return;
    }
    const mains = (catalogue.main_lafs || []).map(item => `<label class="packet-document-option"><input type="radio" name="primary_template_id" value="${escapeHtml(item.id)}" required><span><strong>${escapeHtml(item.name)}</strong><small>Main LAF · version ${escapeHtml(item.version)}</small></span></label>`).join('');
    const supporting = (catalogue.supporting_documents || []).map(item => `<label class="packet-document-option"><input type="checkbox" name="supporting_template_ids" value="${escapeHtml(item.id)}"><span><strong>${escapeHtml(item.name)}</strong><small>Optional supporting document · version ${escapeHtml(item.version)}</small></span></label>`).join('');
    container.innerHTML = `<div class="section-title"><div><h3>Main LAF</h3><p>Choose your application form.</p></div></div>${mains}<div class="section-title"><div><h3>Supporting documents</h3><p>Select only the additional documents required for this application.</p></div></div>${supporting || '<div class="empty-state">No supporting documents are available.</div>'}`;
    container.querySelectorAll('input').forEach(input => input.addEventListener('change', syncCreationPrimary));
  }

  async function loadApplications({ focusSearch = false } = {}) {
    const generation = ++listRequestGeneration;
    const result = await apiFetch(`/applications/?${applicationListParams()}`, {});
    if (generation !== listRequestGeneration) return;
    if (!result.ok) return showToast(result.data?.error || 'Could not load applications.', true);
    applications = (result.data.applications || []).map(item => ({...item, status_text: item.next_action || item.status_text}));
    tabCounts = result.data.tab_counts || {};
    statusOptions = result.data.status_group_options || result.data.status_options || statusOptions;
    if (result.data.filter_options) {
      filterProducts = result.data.filter_options.products || [];
      statusOptions = result.data.filter_options.statuses || statusOptions;
    } else filterProducts = allProducts;
    if (!statusOptions.length) statusOptions = [
      {value:'draft',label:'Draft'}, {value:'changes',label:'Needs changes'},
      {value:'progress',label:'In progress'}, {value:'completed',label:'Completed'}, {value:'closed',label:'Closed'}];
    applicationsLabel = result.data.applications_label || 'Applications';
    reviewerAlerts = result.data.reviewer_alerts || [];
    capabilities = result.data.capabilities || capabilities;
    listState.page = result.data.pagination?.page || 1;
    listState.pages = result.data.pagination?.pages || 1;
    listTotal = result.data.pagination?.total ?? applications.length;
    renderList({ focusSearch });
  }

  async function load() {
    root().setAttribute('aria-busy', 'true');
    const productResult = await apiFetch('/products/', {});
    if (!productResult.ok) { root().innerHTML = `<div class="notice error">${escapeHtml(productResult.data?.error || 'Could not load Origination.')} <button class="btn btn-secondary" id="load-retry">Retry</button></div>`; document.getElementById('load-retry').onclick = load; return; }
    allProducts = productResult.data.products || [];
    originationGroups = productResult.data.groups || [];
    if (!originationGroupId && originationGroups.length === 1) originationGroupId = originationGroups[0].id;
    products = allProducts;
    branches = productResult.data.branches || [];
    locationCatalog = productResult.data.location_catalog || {};
    capabilities = productResult.data.capabilities || capabilities;
    const homeParams = new URLSearchParams(window.location.search);
    const requestedQueue = homeParams.get('queue');
    if (!listState.queue) {
      const legacyStatuses = {corrections:'correction_required', review:'ready_for_review', prepare:'ready_for_review', final_review:'signed_pending_approval'};
      listState.queue = ['mine', 'signing', 'applications'].includes(requestedQueue) ? 'applications' : 'action';
      listState.status = homeParams.get('status') || legacyStatuses[requestedQueue] || '';
      if (requestedQueue === 'my_signatures') listState.signatureOnly = true;
    }
    await loadApplications();
    const requestedApplication = homeParams.get('application');
    if (requestedApplication && /^[0-9a-f-]{36}$/i.test(requestedApplication)) {
      const result = await apiFetch(`/applications/${requestedApplication}/`, {});
      if (result.ok && result.data?.application) await openEditor(result.data.application, 0);
      else showToast(result.data?.error || 'This application is not available to you.', 'error');
    }
    root().setAttribute('aria-busy', 'false');
  }

  document.addEventListener('click', event => {
    const button = event.target.closest?.('button');
    if (button) lastActivatedButton = button;
  }, true);
  document.getElementById('preview-close').onclick = closePreview;
  document.getElementById('preview-previous').onclick = () => navigatePreviewPage(-1);
  document.getElementById('preview-next').onclick = () => navigatePreviewPage(1);
  document.getElementById('preview-regenerate').onclick = async () => {
    if (['draft', 'correction_required'].includes(current?.status) && !(await saveDraft(true))) return;
    clearPreviewPageCache();
    previewRequestId = requestKey('preview');
    await loadPreviewPage();
  };
  document.getElementById('preview-update-now').onclick = async event => {
    window.MiniAppUtils?.setButtonFeedback?.(event.currentTarget, 'loading', 'Refreshing');
    clearPreviewPageCache();
    previewRequestId = requestKey('preview');
    await loadPreviewPage();
    document.getElementById('preview-update-notice').hidden = true;
    window.MiniAppUtils?.setButtonFeedback?.(event.currentTarget, 'success', 'Updated');
    window.setTimeout(() => window.MiniAppUtils?.setButtonFeedback?.(event.currentTarget, 'idle'), 800);
  };
  document.getElementById('preview-zoom-out').onclick = () => setPreviewZoom(previewZoom - 25);
  document.getElementById('preview-zoom-in').onclick = () => setPreviewZoom(previewZoom + 25);
  document.getElementById('preview-zoom').onclick = () => setPreviewZoom(100);
  document.getElementById('origination-review-dialog').onsubmit = event => { event.preventDefault(); submitReviewDialog(); };
  document.getElementById('review-dialog-close').onclick = closeReviewDialog;
  document.getElementById('review-dialog-cancel').onclick = closeReviewDialog;
  document.getElementById('origination-sheet-close').onclick = () => closeSheet();
  document.getElementById('origination-sheet-overlay').addEventListener('click', event => {
    if (event.target === event.currentTarget) closeSheet();
  });
  document.getElementById('origination-sheet').addEventListener('keydown', event => trapModalFocus(event, event.currentTarget));
  document.getElementById('origination-review-dialog').addEventListener('keydown', event => trapModalFocus(event, event.currentTarget));
  document.getElementById('document-preview-overlay').addEventListener('keydown', event => trapModalFocus(event, event.currentTarget));
  bindPreviewPinch();
  window.addEventListener('beforeunload', () => { preserveDraftOnExit(); closePreview(); });
  window.addEventListener('pagehide', () => {preserveDraftOnExit();cameraDialog?.close();activeCameraStream?.getTracks().forEach(track => track.stop());});
  window.addEventListener('pageshow', () => { void resumeDraftSynchronization(); });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') preserveDraftOnExit();
    else {
      void resumeDraftSynchronization();
      void refreshCurrentSigning();
    }
  });
  window.addEventListener('online', () => { void resumeDraftSynchronization(); });
  window.addEventListener('resize', syncViewport);
  window.visualViewport?.addEventListener('resize', syncViewport);
  document.addEventListener('focusin', event => {
    if (!isKeyboardInput(event.target)) return;
    document.body.classList.add('origination-input-active');
    scheduleFocusedInputVisibility();
  });
  document.addEventListener('focusout', () => {
    window.setTimeout(() => {
      if (isKeyboardInput(document.activeElement)) return;
      document.body.classList.remove('origination-input-active');
      setKeyboardViewportOpen(false);
    }, 120);
  });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    if (cameraDialog) {cameraDialog.close();return;}
    if (sheetMode) closeSheet();
    else if (reviewDialogMode) closeReviewDialog();
    else if (!document.getElementById('document-preview-overlay').hidden) closePreview();
  });
  try {
    tg?.onEvent?.('themeChanged', syncTelegramTheme);
    tg?.onEvent?.('viewportChanged', () => { syncViewport(); scheduleFocusedInputVisibility(); });
  } catch (_) { /* Ignore an unavailable or partially initialized Telegram bridge. */ }
  syncTelegramTheme();
  syncViewport();
  try {
    tg?.BackButton?.onClick?.(async () => {
      if (window.MiniAppRecovery?.closeTop()) return;
      if (cameraDialog) return cameraDialog.close();
      if (sheetMode) return closeSheet();
      if (reviewDialogMode) return closeReviewDialog();
      if (!document.getElementById('document-preview-overlay').hidden) return closePreview();
      if (current) await exitEditor();
    });
  } catch (_) { /* In-DOM controls remain available. */ }
  load();
})();
