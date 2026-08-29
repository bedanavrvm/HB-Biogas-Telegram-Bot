(function () {
  'use strict';

  const tg = window.MiniAppUtils?.initTelegram?.() || window.Telegram?.WebApp;
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
  let listCounts = {};
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
  let previewedRevision = null;
  let previewSucceeded = false;
  let previewPacketVersion = '';
  let signingRefreshTimer = null;
  let signingRefreshGeneration = 0;
  let dirty = false;
  let editGeneration = 0;
  let saveInFlight = null;
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
  let mainButtonHandler = null;
  let lastActivatedButton = null;
  let primaryBusy = false;
  let createInFlight = false;
  let previewPinch = null;
  let previewSwipe = null;
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
  const previewPointers = new Map();
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

  function pointDistance(points) {
    const x = points[0].x - points[1].x;
    const y = points[0].y - points[1].y;
    return Math.hypot(x, y);
  }

  function pointMidpoint(points) {
    return {
      x: (points[0].x + points[1].x) / 2,
      y: (points[0].y + points[1].y) / 2,
    };
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
    const requestOptions = options || {};
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

  function escapeHtml(value) {
    const node = document.createElement('div');
    node.textContent = String(value ?? '');
    return node.innerHTML;
  }

  function root() { return document.getElementById('origination-root'); }
  function draftKey(id) { return `loan-origination-draft:${id}`; }
  function normalizeLabel(field) { return field.label || field.key.replaceAll('_', ' '); }

  function applicationStatusLabel(application) {
    if (application?.status === 'ready_for_review') {
      return application.review_packet_ready ? 'Final review' : 'Prepare packet';
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
    if (mainButtonHandler && tg?.MainButton) {
      try { tg.MainButton.offClick?.(mainButtonHandler); } catch (_) { /* Do not let bridge errors break the form. */ }
    }
    mainButtonHandler = null;
  }

  function hideMainButton() {
    clearMainButtonHandler();
    document.body.classList.remove('telegram-main-button-active');
    try { tg?.MainButton?.hideProgress?.(); tg?.MainButton?.hide?.(); } catch (_) { /* Keep the form usable. */ }
    nativeMainButtonVisible = false;
  }

  function syncPrimaryAction() {
    const actions = [...document.querySelectorAll('[data-primary-action]')];
    actions.forEach(action => {
      action.hidden = false;
      action.removeAttribute('aria-hidden');
    });
    clearMainButtonHandler();
    document.body.classList.remove('telegram-main-button-active');
    // The native Telegram button is useful in the short creation sheet, but
    // in the editor it competes with the software keyboard. Keep editor
    // actions in the document so they can disappear with the keyboard state.
    if (current) {
      if (nativeMainButtonVisible) hideMainButton();
      return;
    }
    if (keyboardViewportOpen) {
      try { tg?.MainButton?.hideProgress?.(); tg?.MainButton?.hide?.(); } catch (_) { /* Keep the form usable. */ }
      return;
    }
    if (!tg?.MainButton) return;
    const blockedByOverlay = !document.getElementById('document-preview-overlay')?.hidden
      || !document.getElementById('origination-review-overlay')?.hidden
      || (sheetMode && sheetMode !== 'create');
    const action = blockedByOverlay ? null : actions.find(item => item.getClientRects().length > 0);
    actions.forEach(item => {
      item.hidden = true;
      item.setAttribute('aria-hidden', 'true');
    });
    if (!action) return hideMainButton();
    try {
      document.body.classList.add('telegram-main-button-active');
      tg.MainButton.setText?.(action.dataset.primaryAction || action.textContent.trim() || 'Continue');
      if (primaryBusy || action.disabled) tg.MainButton.disable?.();
      else tg.MainButton.enable?.();
      mainButtonHandler = () => {
        if (!primaryBusy && !action.disabled) action.click();
      };
      tg.MainButton.onClick?.(mainButtonHandler);
      tg.MainButton.show?.();
      nativeMainButtonVisible = true;
    } catch (_) {
      clearMainButtonHandler();
      document.body.classList.remove('telegram-main-button-active');
      actions.forEach(item => {
        item.hidden = false;
        item.removeAttribute('aria-hidden');
      });
      nativeMainButtonVisible = false;
    }
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
        if (sheetMode || reviewDialogMode || previewOpen || current) tg.BackButton.show?.();
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
    return canonicalJson(draft.payload || {}) === canonicalJson(application.form_payload || {})
      && canonicalJson(configuration.requirements || {}) === canonicalJson(application.product_requirements || {})
      && canonicalJson(configuration.customValues || {}) === canonicalJson(application.product_custom_values || {})
      && canonicalJson(configuration.selectedFeeKeys || []) === canonicalJson(application.product_selected_fee_keys || []);
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
    current.product_requirements = local.configuration?.requirements || current.product_requirements;
    current.product_custom_values = local.configuration?.customValues || current.product_custom_values;
    current.product_selected_fee_keys = local.configuration?.selectedFeeKeys || current.product_selected_fee_keys;
    pendingSaveRequestId = local.requestId || requestKey('save');
    editGeneration = Number(local.generation || 1);
    dirty = true;
    syncCloseProtection();
  }

  function openSheet({ mode, eyebrow, title, hint = '', body = '', footer = '', trigger = null }) {
    const overlay = document.getElementById('origination-sheet-overlay');
    const toast = document.getElementById('origination-toast');
    window.clearTimeout(showToast.timer);
    if (toast) toast.hidden = true;
    sheetMode = mode;
    sheetReturnFocus = trigger || document.activeElement;
    document.getElementById('origination-sheet-eyebrow').textContent = eyebrow || 'Origination';
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
    openSheet({
      mode: 'test-signature', eyebrow: verified ? 'Authenticated staff signing' : 'Non-production simulator', title: verified ? 'Capture staff signature' : 'Capture TEST signature',
      hint: verified ? 'Review the complete packet. This signature will be applied to all slots assigned to your staff role.' : 'Use one synthetic mark for this signer. It will be reused at every signature placement in the TEST packet. Do not enter or draw a real signature.', trigger: button,
      body: `${verified ? '<aside class="notice" role="note"><strong>Verified staff action</strong><span>Your Telegram identity, role and application scope will be recorded with this signature.</span></aside>' : '<aside class="test-signature-warning" role="note"><strong>TEST ONLY</strong><span>No OTP or identity verification is performed. The output remains watermarked and is not legally signed.</span></aside>'}
        <div class="test-signature-tabs" role="tablist" aria-label="Signature entry method"><button type="button" role="tab" aria-selected="true" data-test-signature-mode="drawn">Draw</button><button type="button" role="tab" aria-selected="false" data-test-signature-mode="typed">Type</button></div>
        <section class="test-signature-panel" role="tabpanel" data-test-signature-draw><canvas data-test-signature-canvas aria-label="Draw a synthetic test signature" tabindex="0"></canvas><div class="test-signature-tools"><small>Draw inside the box using a finger, mouse or stylus.</small><button type="button" class="btn btn-secondary" data-test-signature-clear>Clear</button></div></section>
        <section class="test-signature-panel" role="tabpanel" data-test-signature-type hidden><label class="test-signature-name"><span>Typed TEST signer name</span><input type="text" maxlength="120" autocomplete="off" data-test-signature-name placeholder="Synthetic Test Signer"></label><output class="test-signature-typed-preview" data-test-signature-typed-preview>Synthetic Test Signer</output></section>
        <p class="test-signature-status" data-test-signature-status aria-live="polite"></p>`,
      footer: `<button type="button" class="btn btn-secondary" data-sheet-cancel>Cancel</button><button type="button" class="btn btn-primary" data-primary-action="${verified ? 'Sign packet' : 'Place TEST signature'}" data-test-signature-confirm>${verified ? 'Sign complete packet' : 'Place TEST signature'}</button>`,
    });
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
        setStatus('The test signature pad is full. Clear it to draw again.');
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
    typedInput.addEventListener('input', () => { typedPreview.textContent = typedInput.value.trim() || 'Synthetic Test Signer'; });
    document.querySelector('[data-sheet-cancel]').onclick = () => closeSheet();
    document.querySelector('[data-test-signature-confirm]').onclick = () => runPrimaryAction(verified ? 'Signing packet...' : 'Placing TEST signature...', async () => {
      const drawn = document.querySelector('[data-test-signature-mode="drawn"]').getAttribute('aria-selected') === 'true';
      const capture = drawn
        ? { method: 'drawn', strokes: testSignatureStrokes }
        : { method: 'typed', name: typedInput.value.trim() };
      if (drawn && !testSignatureStrokes.length) return setStatus('Draw the TEST signature before confirming.');
      if (!drawn && (capture.name.length < 2 || capture.name.length > 120)) return setStatus('Enter a test signer name using 2 to 120 characters.');
      const result = await postJson(verified ? `/applications/${current.id}/staff-signature/` : `/applications/${current.id}/test-signing/action/`, {
        revision: current.revision, package_id: button.dataset.packageId,
        document_key: button.dataset.documentKey, slot_key: button.dataset.slotKey,
        signer_role: button.dataset.signerRole, signature_capture: capture,
        client_request_id: requestId,
      });
      if (!result.ok) return setStatus(result.data?.error || 'Could not place this TEST signature.');
      current = result.data.application;
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
    openSheet({
      mode: 'create', eyebrow: 'Origination', title: 'New application',
      hint: 'Choose a branch, then select a product available there.', trigger,
      body: `<form id="origination-create" class="sheet-form"><label><span>Branch</span><select name="branch" id="origination-create-branch" required><option value="">Choose branch</option>${branchOptions}</select></label><label><span>Product</span><select name="product_key" id="origination-create-product" required disabled><option value="">Choose branch first</option></select></label></form>`,
      footer: '<button type="submit" form="origination-create" class="btn btn-primary" id="origination-create-submit" data-primary-action="Start application" disabled>Start application</button>',
    });
    document.getElementById('origination-create-branch').onchange = event => loadProductsForBranch(event.target.value);
    document.getElementById('origination-create').onsubmit = startApplication;
    syncPrimaryAction();
  }

  function syncCreationPrimary() {
    const branch = document.getElementById('origination-create-branch');
    const product = document.getElementById('origination-create-product');
    const submit = document.getElementById('origination-create-submit');
    if (!submit) return;
    submit.disabled = createInFlight || !branch?.value || !product?.value;
    syncPrimaryAction();
  }

  function filterStatusOptions() {
    return ['draft', 'ready_for_review', 'correction_required', 'reviewed', 'signing_pending', 'partially_signed', 'fully_signed', 'signed_pending_approval', 'approved', 'declined', 'expired', 'cancelled']
      .map(status => `<option value="${status}"${listState.status === status ? ' selected' : ''}>${status.replaceAll('_', ' ')}</option>`).join('');
  }

  function openFilterSheet(trigger) {
    const productOptions = allProducts.map(item => `<option value="${escapeHtml(item.product_key)}"${listState.productKey === item.product_key ? ' selected' : ''}>${escapeHtml(item.name)}</option>`).join('');
    openSheet({
      mode: 'filter', eyebrow: 'Application queue', title: 'Filter applications',
      hint: 'Narrow this queue without changing your access scope.', trigger,
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
      if (editable && !(await saveDraft(true))) return;
      const target = Number(button.dataset.sectionIndex);
      closeSheet({ restoreFocus: false });
      renderEditor(current, target);
    });
  }

  async function startApplication(event) {
    event.preventDefault();
    if (createInFlight) return;
    const values = new FormData(event.currentTarget);
    const identity = `${values.get('branch')}:${values.get('product_key')}`;
    const storageKey = `origination-create-request:${identity}`;
    const createKey = storageGet(storageKey) || requestKey('create');
    storageSet(storageKey, createKey);
    createInFlight = true;
    setPrimaryBusy(true, 'Starting...');
    let createdApplication = null;
    try {
      const result = await postJson('/applications/', {
        product_key: values.get('product_key'), branch: values.get('branch'), client_request_id: createKey,
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
    if (listState.status) params.set('status', listState.status);
    if (listState.productKey) params.set('product_key', listState.productKey);
    if (listState.query) params.set('q', listState.query);
    return params;
  }

  async function applyListFilters(updates) {
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
    if (String(current?.id || '') !== String(application.id)) {
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
    await recoverDraft(application);
    if (['ready_for_review', 'reviewed', 'signing_pending', 'partially_signed', 'fully_signed', 'signed_pending_approval', 'approved'].includes(application.status)) {
      requestedStep = wizardSections().length - 1;
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
      : LEGACY_SECTIONS;
    const facilityKey = current?.form_schema?.commercial_section_key
      || (sections.some(item => item.key === 'loan_details') ? 'loan_details' : '')
      || (sections.some(item => item.key === 'invoice_details') ? 'invoice_details' : '')
      || 'commercial_terms';
    if (facilityKey !== 'commercial_terms' && sections.some(item => item.key === 'commercial_terms')) {
      sections = sections.filter(item => item.key !== 'commercial_terms');
    }
    const terms = current?.product_terms || {};
    const requirements = (terms.requirements || []).filter(item => !item.workflow || item.workflow === 'loan_origination');
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
      sections.push({
        key: 'document_selection', label: 'Supporting documents',
        hint: 'Choose the additional documents that apply after saving and previewing the main LAF.',
      });
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
      const key = field.section_key || sectionFor(field.key);
      return key === sectionKey || (sectionKey === facilityKey && key === 'commercial_terms');
    });
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
    const requirements = (terms.requirements || []).filter(item => !item.workflow || item.workflow === 'loan_origination');
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
        const itemEditable = evidenceEditable && correctionAllows('requirement', item.key);
        const upload = itemEditable ? `<div class="evidence-upload-actions"><button type="button" class="evidence-upload evidence-camera" data-evidence-camera="${escapeHtml(item.key)}"><span>Take photo</span></button><label class="evidence-upload"><input type="file" accept="application/pdf,image/jpeg,image/png" data-evidence-upload="${escapeHtml(item.key)}"><span>Choose file</span></label></div>` : '';
        const fileRows = evidence.map(file => `<span class="evidence-row status-${escapeHtml(file.status)}"><span><strong>${escapeHtml(file.filename)}</strong><small>${escapeHtml(file.status === 'failed' ? file.error || 'Upload failed' : `${Math.max(1, Math.round(file.byte_size / 1024))} KB · ${file.status}`)}</small></span><span class="evidence-actions">${file.download_url ? `<button type="button" data-evidence-open="${escapeHtml(file.id)}" data-evidence-name="${escapeHtml(file.filename)}" data-evidence-mime="${escapeHtml(file.mime_type || '')}">View</button>` : ''}${itemEditable && file.status === 'uploaded' ? `<button type="button" data-evidence-remove="${escapeHtml(file.id)}">Remove</button>` : ''}</span></span>`).join('');
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
    const feeRows = optionalFees.map(item => `<label class="laf-field configuration-fee" data-product-wrap="fee:${escapeHtml(item.key)}"><span>${escapeHtml(item.label)}</span><small class="field-error" aria-live="polite"></small><small class="field-help">Optional ${escapeHtml(item.collection_mode)} fee</small><label class="configuration-check"><input type="checkbox" data-product-fee="${escapeHtml(item.key)}"${selected.has(item.key) ? ' checked' : ''}${editable && current?.status !== 'correction_required' ? '' : ' disabled'}><span>Include in quote</span></label></label>`).join('');
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
    const rendered = field => fieldInput(
      field,
      values[field.key],
      !editable || field.editable === false || !correctionAllows('field', field.key),
    );
    const first = fields.filter(field => String(field.key || '').startsWith('guarantor_1_'));
    const second = fields.filter(field => String(field.key || '').startsWith('guarantor_2_'));
    if (!first.length && !second.length) return `<div class="laf-grid">${fields.map(rendered).join('')}</div>`;
    const other = fields.filter(field => !first.includes(field) && !second.includes(field));
    const card = (title, hint, items, optional) => items.length
      ? `<fieldset class="guarantor-card${optional ? ' is-optional' : ''}"${optional ? ' data-guarantor-two-card' : ''}><legend><span><strong>${title}</strong><small>${hint}</small></span>${optional && editable ? '<button type="button" class="btn btn-secondary" data-clear-guarantor-two>Clear Guarantor 2</button>' : ''}</legend><div class="laf-grid">${items.map(rendered).join('')}</div></fieldset>`
      : '';
    return `<div class="guarantor-groups">${card('Guarantor 1', 'Required guarantor', first, false)}${card('Guarantor 2', 'Optional unless any details are entered', second, true)}${other.length ? `<div class="laf-grid">${other.map(rendered).join('')}</div>` : ''}</div>`;
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

  function syncOriginationSubCountySelect() {
    const countySelect = root()?.querySelector('[data-location-type="county"]');
    const subCountySelect = root()?.querySelector('[data-location-type="sub_county"]');
    if (!countySelect || !subCountySelect) return;
    const county = locationMatch(originationCounties(), countySelect.value);
    let items = county?.sub_counties || [];
    const branch = locationMatch(locationCatalog.branches, current?.branch);
    const areas = branch ? (locationCatalog.branch_service_areas?.[branch.code] || []) : [];
    if (areas.length && !areas.includes(county?.code)) items = items.filter(item => areas.includes(item.code));
    subCountySelect.innerHTML = `<option value="">Choose sub-county</option>${locationSelectOptions(items, '')}`;
  }

  function fieldInput(field, value, disabled) {
    const key = escapeHtml(field.key);
    const label = escapeHtml(normalizeLabel(field));
    const classes = `laf-field${field.width === 'full' || FULL_WIDTH.has(field.key) ? ' laf-field-wide' : ''}`;
    const required = field.required ? '<span class="required-mark" aria-label="required">*</span>' : '';
    let control = '';
    if (field.type === 'repeating_group') {
      const structure = field.structure || {};
      const columns = structure.columns || [];
      const rows = Array.isArray(value) ? value : [];
      const maxItems = Number(structure.max_items || 20);
      const policyBound = field.key === 'loan_fees';
      const itemLabel = repeatableItemLabel(field);
      control = `<div class="repeatable-field" data-repeatable-field="${key}" data-main-repeatable="${key}" data-repeatable-grid="${escapeHtml(repeatableGridStyle(field))}" data-max-items="${maxItems}" data-item-label="${escapeHtml(itemLabel)}"><div class="repeatable-rows">${rows.map((row, index) => repeatableRowMarkup(columns, row, index, disabled, policyBound, itemLabel, repeatableGridStyle(field))).join('')}</div>${policyBound ? '' : `<div class="repeatable-summary"><button type="button" class="btn btn-secondary" data-repeat-add${disabled || rows.length >= maxItems ? ' disabled' : ''}>Add ${escapeHtml(itemLabel.toLowerCase())}</button></div>`}</div>`;
    } else if (field.type === 'branch') {
      const branch = locationMatch(locationCatalog.branches, current?.branch);
      control = `<select data-field="${key}" data-location-type="branch" disabled><option value="">Choose</option>${locationSelectOptions(branch ? [branch] : [], value || current?.branch)}</select>`;
    } else if (field.type === 'county') {
      const counties = originationCounties();
      control = `<select data-field="${key}" data-location-type="county"${disabled ? ' disabled' : ''}><option value="">Choose county</option>${locationSelectOptions(counties, value)}</select>`;
    } else if (field.type === 'sub_county') {
      const countyField = (current?.form_schema?.fields || []).find(item => item.type === 'county');
      const county = locationMatch(originationCounties(), current?.form_payload?.[countyField?.key]);
      let items = county?.sub_counties || [];
      const branch = locationMatch(locationCatalog.branches, current?.branch);
      const areas = branch ? (locationCatalog.branch_service_areas?.[branch.code] || []) : [];
      if (areas.length && !areas.includes(county?.code)) items = items.filter(item => areas.includes(item.code));
      control = `<select data-field="${key}" data-location-type="sub_county"${disabled ? ' disabled' : ''}><option value="">Choose sub-county</option>${locationSelectOptions(items, value)}</select>`;
    } else if (field.type === 'choice') {
      const options = (field.options || []).map(option => {
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
      const type = field.type === 'phone' ? 'tel' : field.type === 'date' ? 'date' : field.type === 'datetime' ? 'datetime-local' : 'text';
      const prefix = field.type === 'money' ? '<span class="input-prefix">KES</span>' : '';
      const validation = field.validation || {};
      const numeric = field.type === 'money' ? ` inputmode="numeric" data-numeric-input${field.source_type === 'system' ? '' : ' data-money-input'} data-min="${escapeHtml(validation.min ?? 0)}" data-max="${escapeHtml(validation.max ?? '')}"` : field.type === 'number' ? ` inputmode="decimal" data-numeric-input data-min="${escapeHtml(validation.min ?? '')}" data-max="${escapeHtml(validation.max ?? '')}"` : '';
      const textRules = ['text', 'textarea', 'phone', 'national_id'].includes(field.type) ? `${validation.min_length != null ? ` minlength="${escapeHtml(validation.min_length)}"` : ''}${validation.max_length != null ? ` maxlength="${escapeHtml(validation.max_length)}"` : ''}${validation.pattern ? ` pattern="${escapeHtml(validation.pattern)}"` : ''}` : '';
      const dobMin = field.key === 'applicant_dob' ? isoDate(new Date(new Date().getFullYear() - 120, 0, 1)) : '';
      const dobMax = field.key === 'applicant_dob' ? isoDate(new Date()) : '';
      const dateRules = field.type === 'date' ? `${validation.min_date || dobMin ? ` min="${escapeHtml(validation.min_date || dobMin)}"` : ''}${validation.max_date || dobMax ? ` max="${escapeHtml(validation.max_date || dobMax)}"` : ''}` : '';
      const input = field.type === 'date'
        ? nativeDateControl(`data-field="${key}"${field.required ? ' required' : ''}`, value, disabled, dateRules)
        : `<input data-field="${key}" type="${type}" value="${escapeHtml(value ?? '')}"${field.required ? ' required' : ''}${numeric}${textRules}${field.type === 'national_id' ? ' inputmode="numeric"' : ''}${disabled ? ' disabled' : ''}>`;
      control = `<div class="input-wrap${prefix ? ' has-prefix' : ''}">${prefix}${input}</div>`;
    }
    const help = field.help_text ? `<small class="field-help">${escapeHtml(field.help_text)}</small>` : '';
    const correction = ['ready_for_review', 'signed_pending_approval'].includes(current.status) ? correctionToggle('field', field.key, normalizeLabel(field)) : '';
    const wrapperTag = field.type === 'repeating_group' ? 'div' : 'label';
    return `<${wrapperTag} class="${classes}" data-field-wrap="${key}"><span>${label}${required}</span><small class="field-error" aria-live="polite"></small>${help}${correction}${control}</${wrapperTag}>`;
  }

  function numericInputError(input) {
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
    root()?.querySelectorAll('[data-numeric-input]').forEach(input => {
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
      (document?.schema?.fields || []).forEach(field => {
        if (field.type === 'repeating_group') {
          const container = root()?.querySelector(`[data-repeatable-field="${CSS.escape(field.key)}"]`);
          const rows = [...(container?.querySelectorAll('[data-repeat-row]') || [])];
          const structure = field.structure || {};
          const minimum = Number(structure.min_items || 0);
          const maximum = Number(structure.max_items || 0);
          if (field.required && rows.length < Math.max(minimum, 1)) errors[field.key] = `Add at least ${Math.max(minimum, 1)} asset`;
          if (maximum && rows.length > maximum) errors[field.key] = `Add no more than ${maximum} assets`;
          rows.forEach((row, index) => row.querySelectorAll('[data-repeat-column]').forEach(input => {
            if (!errors[field.key] && input.required && !input.value.trim()) errors[field.key] = `Complete row ${index + 1}`;
            if (!errors[field.key] && numericInputError(input)) errors[field.key] = `${numericInputError(input)} Row ${index + 1}.`;
          }));
          return;
        }
        const input = root()?.querySelector(`[data-document-field="${CSS.escape(field.key)}"]`);
        const value = input?.value ?? document.field_payload?.[field.key] ?? current.form_payload?.[field.key];
        if (field.required && (value === undefined || value === null || value === '')) errors[field.key] = 'Required';
        if (!errors[field.key] && input && !input.checkValidity()) errors[field.key] = input.validationMessage || 'Enter a valid value.';
      });
      return errors;
    }
    if (sectionKey === 'document_selection') return {};
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

  function showErrors(errors) {
    root()?.querySelector('.field-validation-summary')?.remove();
    const entries = Object.entries(errors || {}).filter(([, message]) => Boolean(message));
    const messageFor = key => errors[key] || Object.entries(errors).find(([candidate]) => candidate.startsWith(`${key}.`))?.[1] || '';
    root()?.querySelectorAll('[data-field-wrap]').forEach(wrapper => {
      const message = messageFor(wrapper.dataset.fieldWrap);
      wrapper.classList.toggle('invalid', Boolean(message));
      const output = wrapper.querySelector('.field-error');
      if (output) {
        output.textContent = message;
        output.id ||= `field-error-${String(wrapper.dataset.fieldWrap).replace(/[^a-z0-9_-]/gi, '-')}`;
        const control = wrapper.querySelector('input, select, textarea');
        if (control) {
          if (message) control.setAttribute('aria-describedby', output.id);
          else if (control.getAttribute('aria-describedby') === output.id) control.removeAttribute('aria-describedby');
          control.setAttribute('aria-invalid', message ? 'true' : 'false');
        }
      }
    });
    root()?.querySelectorAll('[data-product-wrap]').forEach(wrapper => {
      const message = errors[wrapper.dataset.productWrap] || '';
      wrapper.classList.toggle('invalid', Boolean(message));
      const output = wrapper.querySelector('.field-error');
      if (output) {
        output.textContent = message;
        output.id ||= `product-error-${String(wrapper.dataset.productWrap).replace(/[^a-z0-9_-]/gi, '-')}`;
        const control = wrapper.querySelector('input, select, textarea');
        if (control) {
          if (message) control.setAttribute('aria-describedby', output.id);
          else if (control.getAttribute('aria-describedby') === output.id) control.removeAttribute('aria-describedby');
          control.setAttribute('aria-invalid', message ? 'true' : 'false');
        }
      }
    });
    if (!entries.length) return;
    const summary = document.createElement('aside');
    summary.className = 'field-validation-summary';
    summary.setAttribute('role', 'alert');
    const heading = document.createElement('strong');
    heading.textContent = entries.length === 1 ? 'Fix this field before continuing' : `Fix ${entries.length} fields before continuing`;
    summary.append(heading);
    entries.slice(0, 1).forEach(([key, message]) => {
      const button = document.createElement('button');
      button.type = 'button';
      const wrapper = [...(root()?.querySelectorAll('[data-field-wrap], [data-product-wrap]') || [])].find(item => (
        item.dataset.fieldWrap === key || key.startsWith(`${item.dataset.fieldWrap}.`) || item.dataset.productWrap === key
      ));
      const label = wrapper?.firstElementChild?.textContent?.trim() || key.replaceAll('_', ' ');
      button.textContent = `${label}: ${message}`;
      button.onclick = () => {
        wrapper?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
        window.setTimeout(() => wrapper?.querySelector('input, select, textarea, button')?.focus?.(), 250);
      };
      summary.append(button);
    });
    if (entries.length > 1) {
      const remaining = document.createElement('small');
      remaining.textContent = `${entries.length - 1} more field${entries.length === 2 ? '' : 's'} highlighted below.`;
      summary.append(remaining);
    }
    root()?.querySelector('.wizard-card')?.before(summary);
  }

  function showServerErrors(errors) {
    if (!errors || typeof errors !== 'object') return;
    const firstKey = Object.keys(errors)[0];
    if (!firstKey) return;
    serverValidationErrorsVisible = true;
    const sections = wizardSections();
    let targetStep = sections.findIndex(section => fieldsFor(section.key).some(field => field.key === firstKey));
    if (firstKey.startsWith('requirement:') || firstKey.startsWith('custom:')) {
      targetStep = sections.findIndex(section => section.key === 'product_requirements');
    }
    if (targetStep >= 0 && targetStep !== step) renderEditor(current, targetStep);
    showErrors(errors);
    window.setTimeout(() => root()?.querySelector('.invalid input, .invalid select, .invalid textarea')?.focus(), 0);
  }

  async function saveDraft(showError) {
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
      return dirty ? saveDraft(showError) : true;
    }
    const applicationId = current.id;
    const revision = current.revision;
    const generation = editGeneration;
    const payload = collectPayload();
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
      revision, payload, configuration, requestId: key,
      generation, savedAt: Date.now(),
    };
    await persistRecoveryDraft(applicationId, attemptedDraft);
    setSaveState('Saving…', 'saving');
    saveInFlightRequestId = key;
    saveInFlight = apiFetch(`/applications/${applicationId}/`, {
      method: 'PATCH', headers: { 'Idempotency-Key': key, 'X-Request-ID': key },
      body: JSON.stringify({
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
            revision,
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
      current.product_requirements = latestConfiguration.requirements;
      current.product_custom_values = latestConfiguration.customValues;
      current.product_selected_fee_keys = latestConfiguration.selectedFeeKeys;
      dirty = true;
      syncCloseProtection();
      setSaveState('Saving newer changes…', 'saving');
      return saveDraft(showError);
    }
    pendingSaveRequestId = '';
    dirty = false;
    syncCloseProtection();
    await removeRecoveryDraft(applicationId);
    setSaveState('Saved', 'saved');
    return true;
  }

  function setSaveState(text, state) {
    const element = document.getElementById('origination-save-status');
    if (element) { element.textContent = text; element.dataset.state = state; }
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
    const configuration = collectProductConfiguration();
    void persistRecoveryDraft(current.id, {
      revision: current.revision,
      payload,
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
    const configuration = collectProductConfiguration();
    const key = pendingSaveRequestId;
    void persistRecoveryDraft(current.id, {
      revision: current.revision,
      payload,
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
    return `<div class="wizard-progress-compact"><button type="button" id="origination-section-picker" class="wizard-progress-trigger" aria-label="Choose application section"><span><small>Step ${step + 1} of ${sections.length}</small><strong>${escapeHtml(section.label)}</strong></span>${iconSvg('chevronDown')}</button><div class="wizard-progress-track" role="progressbar" aria-label="Application progress" aria-valuemin="1" aria-valuemax="${sections.length}" aria-valuenow="${step + 1}"><span style="width:${percent}%"></span></div></div>`;
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
    if (hasFinalSignedPacket()) return 'Preview signed packet';
    if (hasCurrentSigningPacket()) return 'Preview current signed packet';
    if (current?.review_packet_ready && ['ready_for_review', 'reviewed'].includes(current?.status)) {
      return current.status === 'reviewed' ? 'Preview approved packet' : 'Preview frozen packet';
    }
    return fallback;
  }

  function resolveLatestPreviewKey(documentKey) {
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
      return '<aside class="workflow-readiness is-waiting"><div><p class="eyebrow">Operations preparation</p><strong>Awaiting a frozen review packet</strong><span>Operations must freeze the application data, evidence, participants and complete document packet before a checker can review it.</span></div></aside>';
    }
    if (current.status === 'ready_for_review') {
      return `<aside class="workflow-readiness is-ready"><div><p class="eyebrow">Checker final review</p><strong>Review the exact frozen packet</strong><span>This immutable PDF and review-scope hash are the only version that can be approved and sent for signing.</span></div><button type="button" class="btn btn-primary" id="origination-review-packet-preview">Preview frozen packet</button></aside>`;
    }
    return `<aside class="workflow-readiness is-approved"><div><p class="eyebrow">Approved frozen packet</p><strong>Approved by ${escapeHtml(packageData.reviewed_by_name || 'an authorized checker')}</strong><span>Operations may now start signing. Any officer recall cancels this packet and invalidates the approval.</span></div><button type="button" class="btn btn-secondary" id="origination-review-packet-preview">Preview approved packet</button></aside>`;
  }

  function reviewMarkup(values) {
    const hasPacket = (current?.document_packet?.documents || []).filter(item => item.selected).length > 1;
    const signed = ['fully_signed', 'signed_pending_approval', 'approved'].includes(current?.status);
    const sectionAction = ['draft', 'correction_required'].includes(current?.status) ? 'Edit' : 'View';
    const reviewCards = ['fully_signed', 'approved'].includes(current?.status) ? '' : `<div class="review-sections">${wizardSections().slice(0, -1).map((section, index) => {
      if (section.key === 'document_selection') {
        const selected = (current?.document_packet?.documents || []).filter(item => item.role === 'supporting' && item.selected);
        return `<button type="button" class="review-card" data-edit-step="${index}"><span><strong>Supporting documents</strong><small>${selected.length} selected</small></span><span>${sectionAction} ${iconSvg('arrowRight')}</span></button>`;
      }
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
    return `${reviewWorkflowMarkup()}<div class="review-intro"><div><p class="eyebrow">${signed ? 'Completed packet' : 'Final check'}</p><h3>${signed ? 'Signed application' : 'Review the application'}</h3><p>${signed ? 'The application is immutable. View the final signed packet below.' : current?.review_packet_ready ? 'Inspect the frozen packet and open sections to verify the captured data.' : 'Open each section to correct details, then inspect the complete document packet.'}</p></div><div class="review-preview-actions"><button type="button" class="btn btn-primary" id="origination-preview">${latestPreviewLabel(hasPacket ? 'Preview full packet' : 'Preview main LAF')}</button></div></div>
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
        const externalAction = participant.staff && capabilities.can_staff_sign && staffRoleAllowed
          ? `<button type="button" class="btn btn-secondary" data-staff-sign data-package-id="${escapeHtml(packageData.id)}" data-signer-role="${escapeHtml(participant.role)}">Capture staff signature</button>`
          : participant.staff
            ? '<span class="status-chip">Awaiting authorized staff</span>'
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
        const signatureRow = signatures.length ? `<div class="signing-test-slot ${signaturesComplete ? 'is-complete' : ''}"><span><strong>${escapeHtml(participant.label)}</strong><small>${signatures.length} signature box(es) across the packet${participant.phone_mapped || participant.staff ? '' : ' · phone mapping missing'}</small>${signatureCorrections}</span>${signaturesComplete ? '<span class="status-chip">Complete</span>' : externalAction}</div>` : '';
        const stampRows = stamps.map(slot => `<div class="signing-test-slot ${slot.completed ? 'is-complete' : ''}"><span><strong>${escapeHtml(slot.label || slot.key)}</strong><small>${escapeHtml(participant.label)} · ${escapeHtml(slot.document_key)}</small></span>${slot.completed ? '<span class="status-chip">Stamped</span>' : `<select data-production-stamp-select><option value="">Choose production stamp</option>${stampOptions}</select><button type="button" class="btn btn-secondary" data-production-stamp data-package-id="${escapeHtml(packageData.id)}" data-document-key="${escapeHtml(slot.document_key)}" data-slot-key="${escapeHtml(slot.key)}" data-signer-role="${escapeHtml(participant.role)}">Apply stamp</button>`}</div>`).join('');
        return signatureRow + stampRows;
      }).join('');
      const archive = current.status === 'fully_signed' && verified.archive_status !== 'uploaded'
        ? `<aside class="notice"><strong>${verified.archive_status === 'failed' ? 'Automatic archival needs attention' : 'Automatic archival in progress'}</strong><span>${escapeHtml(verified.archive_error || 'The immutable signed PDF is being stored in restricted Drive automatically.')}</span>${verified.archive_status === 'failed' ? `<button type="button" class="btn btn-primary" id="origination-archive-signed" data-package-id="${escapeHtml(packageData.id)}">Retry archival</button>` : ''}</aside>` : '';
      const signedPacket = verified.signed_packet_available
        ? `<aside class="signed-packet-access"><div><strong>${verified.archive_status === 'uploaded' ? 'Archived signed packet' : 'Final signed packet'}</strong><span>${verified.archive_status === 'uploaded' ? 'Stored in restricted Drive and verified against its immutable hash.' : 'Ready to view while automatic archival completes.'}</span></div><div><button type="button" class="btn btn-secondary" id="origination-view-signed" data-package-id="${escapeHtml(packageData.id)}">View signed LAF</button><button type="button" class="btn btn-primary" id="origination-open-signed-pdf" data-package-id="${escapeHtml(packageData.id)}">Open PDF</button></div></aside>`
        : '';
      const signingComplete = ['fully_signed', 'signed_pending_approval', 'approved'].includes(current.status);
      const signingHeading = current.status === 'signed_pending_approval' ? 'Signed — pending JBL approval' : current.status === 'approved' ? 'Approved and locked' : signingComplete ? 'Signing complete' : 'Send each signer their secure link';
      const signingDetail = current.status === 'signed_pending_approval'
        ? 'Every required signature is present. An independent checker must approve these exact signed bytes before the application is final.'
        : current.status === 'approved'
          ? 'Independent final review approved this immutable signed packet.'
          : signingComplete ? 'Every required signature and stamp has been applied to the immutable packet.' : 'Remote signing works from any location. Each external signer reviews the immutable packet and verifies their own OTP.';
      return `<section class="signing-verified-panel"><div class="signing-panel-heading"><div><p class="eyebrow">Verified packet signing</p><h3>${signingHeading}</h3></div><button type="button" class="icon-button" id="origination-refresh-signing" aria-label="Refresh signing progress" title="Refresh signing progress">${iconSvg('refresh')}</button></div><p>${signingDetail}</p>${participants || '<div class="empty-state">No signing participants were configured.</div>'}${signedPacket}${archive}</section>`;
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
      if (capabilities.can_confirm_signing && officerOwnsApplication && ['ready_for_review', 'reviewed'].includes(current.status)) {
        return `${recall}<button class="btn btn-primary" id="origination-confirm-signing">Continue to signing</button>`;
      }
      if (current.status === 'ready_for_review' && !current.review_packet_ready) {
        const prepare = capabilities.can_start_signing
          ? '<button class="btn btn-primary" id="origination-prepare-review" data-primary-action="Prepare review packet">Prepare review packet</button>' : '';
        return `${recall}${prepare}`;
      }
      if (current.status === 'ready_for_review' && current.review_packet_ready && capabilities.can_review) {
        const assignedElsewhere = current.recheck_assigned_to_id
          && String(current.recheck_assigned_to_id) !== String(capabilities.user_id);
        if (assignedElsewhere) return `${recall}<button class="btn btn-secondary" id="origination-takeover-review">Take over re-check</button>`;
        return `${recall}<button class="btn btn-secondary" data-review="request_correction">Request correction</button><button class="btn btn-danger" data-review="decline">Decline</button><button class="btn btn-primary" data-review="approve">Approve frozen packet</button>`;
      }
      if (current.status === 'reviewed' && capabilities.can_start_signing) return `${recall}<button class="btn btn-primary" id="origination-start-signing" data-primary-action="Start signing">Start signing</button>`;
      return recall;
    }
    const finalAction = capabilities.can_confirm_signing
      ? '<button class="btn btn-primary" id="origination-confirm-signing" data-primary-action="Confirm and start signing">Confirm and start signing</button>'
      : '<button class="btn btn-primary" id="origination-submit" data-primary-action="Submit for packet preparation">Submit for packet preparation</button>';
    return `${step > 0 ? `<button class="btn btn-secondary" id="wizard-previous">${iconSvg('arrowLeft')} Previous</button>` : '<span></span>'}${step < wizardSections().length - 1 ? '<button class="btn btn-primary" id="wizard-next" data-primary-action="Save & continue">Save & continue</button>' : finalAction}`;
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
      return '<aside class="notice recovery-conflict"><strong>Refreshing the saved draft</strong><span>Your encrypted phone copy is safe. The latest server revision must load before either copy can be selected.</span><div><button type="button" class="btn btn-secondary" id="recovery-retry-refresh">Retry refresh</button></div></aside>';
    }
    return `<aside class="notice recovery-conflict"><strong>Two draft revisions need your choice</strong><span>The encrypted phone draft was based on revision ${escapeHtml(conflictDraft.revision)}; the server is now revision ${escapeHtml(current.revision)}. Nothing has been overwritten.</span><div><button type="button" class="btn btn-secondary" id="recovery-use-server">Use server version</button><button type="button" class="btn btn-primary" id="recovery-restore-phone">Restore phone draft</button></div></aside>`;
  }

  function persistentStateFeedbackMarkup() {
    if (current?.status === 'signed_pending_approval') {
      return '<aside class="notice feedback-banner success" role="status"><strong>Signed — pending JBL approval</strong><span>All required signatures are present. The packet becomes final only after independent checker approval.</span></aside>';
    }
    return '';
  }

  function renderEditor(application, requestedStep) {
    document.body.classList.add('origination-editor-open');
    current = application;
    step = Number.isInteger(requestedStep) ? requestedStep : step;
    const values = collectPayload();
    const editable = ['draft', 'correction_required'].includes(application.status);
    const sections = wizardSections();
    if (step >= sections.length) step = sections.length - 1;
    const section = sections[step];
    const sectionLocked = application.status === 'draft'
      && section.key !== 'review'
      && completedDraftSections.has(section.key)
      && !unlockedDraftSections.has(section.key);
    const sectionEditable = editable && !sectionLocked && !syncConflict;
    let content;
    if (section.key === 'review') content = reviewMarkup(values);
    else if (section.key === 'document_selection') content = documentSelectionMarkup(sectionEditable && application.status !== 'correction_required');
    else if (section.key.startsWith('document:')) content = supportingDocumentMarkup(section.document, sectionEditable);
    else {
      const fields = section.key === 'product_requirements'
        ? productConfigurationMarkup(sectionEditable)
        : sectionFieldsMarkup(section.key, values, sectionEditable);
      const quote = section.key === facilitySectionKey() && Number(application.form_schema?.commercial_contract_version || 0) >= 2
        ? commercialQuoteMarkup() : '';
      content = `<div class="section-title"><div><h3>${escapeHtml(section.label)}</h3><p>${escapeHtml(section.hint || '')}</p></div><button type="button" class="preview-link" id="origination-preview-early">${latestPreviewLabel('Preview PDF')}</button></div>${fields}${quote}`;
    }
    if (sectionLocked) {
      content = `<aside class="completed-section-lock"><span><strong>Section saved</strong><small>Values are locked while you continue. Unlock only when you need to change this section.</small></span><button type="button" class="btn btn-secondary" id="origination-edit-section">Edit section</button></aside>${content}`;
    }
    const recoveryState = syncConflict ? ['Conflict', 'offline'] : dirty ? ['Recovered securely', 'offline'] : ['Saved', 'saved'];
    const actions = actionMarkup(editable);
    const actionFooter = editable || actions
      ? `<footer class="wizard-actions">${editable ? `<span id="origination-save-status" data-state="${recoveryState[1]}">${recoveryState[0]}</span>` : '<span></span>'}<div>${actions}</div></footer>`
      : '';
    const statusHasPersistentBanner = application.status === 'signed_pending_approval';
    const contextStatus = statusHasPersistentBanner
      ? '' : `<small class="editor-status-text">${escapeHtml(application.status_text || applicationStatusLabel(application))}</small>`;
    const contextChip = statusHasPersistentBanner
      ? '' : `<span class="status-chip status-${escapeHtml(application.status)}">${escapeHtml(applicationStatusLabel(application))}</span>`;
    root().innerHTML = `<div class="editor-context"><button type="button" class="icon-button" id="origination-back" aria-label="Back to applications">${iconSvg('arrowLeft')}</button><div><strong>${escapeHtml(application.reference_number)}</strong><small>${escapeHtml(application.product_name)}</small>${contextStatus}</div>${contextChip}</div>${persistentStateFeedbackMarkup()}${recoveryConflictMarkup()}${correctionChecklistMarkup()}${recheckAssignmentMarkup()}${progressMarkup()}<section class="wizard-card">${content}</section>${actionFooter}`;
    syncNativeDateDisplays(root());
    bindEditor(sectionEditable);
    syncTelegramControls();
    scheduleSigningRefresh();
    window.requestAnimationFrame(() => window.scrollTo(0, 0));
  }

  function documentSelectionMarkup(editable) {
    const packet = current?.document_packet || {};
    const documents = (packet.documents || []).filter(item => item.role === 'supporting' && item.applicable);
    const rows = documents.map(item => {
      const locked = item.inclusion_mode !== 'optional';
      return `<label class="packet-document-option${item.selected ? ' selected' : ''}"><input type="checkbox" data-document-select="${escapeHtml(item.key)}"${item.selected ? ' checked' : ''}${locked || !editable ? ' disabled' : ''}><span><strong>${escapeHtml(item.name)}</strong><small>${locked ? 'Required for this application' : 'Optional supporting document'}</small></span><span class="status-chip">${item.selected ? 'Included' : 'Not included'}</span></label>`;
    }).join('');
    return `<div class="section-title"><div><h3>Supporting documents</h3><p>Required documents are selected automatically. Add optional documents now; one full-packet preview at the final check verifies everything together.</p></div></div><div class="packet-document-list">${rows || '<div class="empty-state">No supporting documents apply.</div>'}</div>`;
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
      if (column.type === 'choice') {
        const options = (column.options || []).map(option => {
          const code = option && typeof option === 'object' ? option.code : option;
          const label = option && typeof option === 'object' ? (option.label || option.code) : option;
          return `<option value="${escapeHtml(code)}"${columnValue === code ? ' selected' : ''}>${escapeHtml(label)}</option>`;
        }).join('');
        return `<label><span>${escapeHtml(column.label || column.key)}${column.required ? '<span class="required-mark" aria-label="required">*</span>' : ''}</span><select data-repeat-column="${escapeHtml(column.key)}"${column.required ? ' required' : ''}${columnDisabled ? ' disabled' : ''}><option value="">Choose</option>${options}</select></label>`;
      }
      if (column.type === 'date') {
        return `<label><span>${escapeHtml(column.label || column.key)}${column.required ? '<span class="required-mark" aria-label="required">*</span>' : ''}</span>${nativeDateControl(`data-repeat-column="${escapeHtml(column.key)}"${column.required ? ' required' : ''}`, columnValue, columnDisabled)}</label>`;
      }
      const validation = column.validation || {};
      const numericRules = numeric ? ` inputmode="${column.type === 'money' ? 'numeric' : 'decimal'}" data-numeric-input${column.type === 'money' && !lockRow ? ' data-money-input' : ''} data-min="${escapeHtml(validation.min ?? '')}" data-max="${escapeHtml(validation.max ?? '')}"` : '';
      return `<label><span>${escapeHtml(column.label || column.key)}${column.required ? '<span class="required-mark" aria-label="required">*</span>' : ''}</span><input data-repeat-column="${escapeHtml(column.key)}" type="text" value="${escapeHtml(columnValue)}"${numericRules}${column.required ? ' required' : ''}${columnDisabled ? ' disabled' : ''}></label>`;
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
    const key = escapeHtml(field.key);
    const shared = current.form_payload?.[field.key];
    const value = document.field_payload?.[field.key] ?? shared ?? '';
    const mainFormOwnsField = (current.form_schema?.fields || []).some(item => item.key === field.key);
    const locked = field.source_type === 'system' || (
      mainFormOwnsField && shared !== undefined && shared !== null && shared !== ''
    );
    const correctionKey = `${document.key}.${field.key}`;
    const disabled = !editable || locked || !correctionAllows('document_field', correctionKey);
    const required = field.required ? '<span class="required-mark" aria-label="required">*</span>' : '';
    let control;
    if (field.type === 'repeating_group') {
      const structure = field.structure || {};
      const columns = structure.columns || [];
      const rows = Array.isArray(value) ? value : [];
      const maxItems = Number(structure.max_items || 11);
      const itemLabel = repeatableItemLabel(field);
      control = `<div class="repeatable-field" data-repeatable-field="${key}" data-repeatable-grid="${escapeHtml(repeatableGridStyle(field))}" data-max-items="${maxItems}" data-item-label="${escapeHtml(itemLabel)}"><div class="repeatable-rows">${rows.map((row, index) => repeatableRowMarkup(columns, row, index, disabled, false, itemLabel, repeatableGridStyle(field))).join('')}</div><div class="repeatable-summary"><button type="button" class="btn btn-secondary" data-repeat-add${disabled || rows.length >= maxItems ? ' disabled' : ''}>Add ${escapeHtml(itemLabel.toLowerCase())}</button><strong>Total: KES <span data-repeat-total>0</span></strong></div></div>`;
    } else if (field.type === 'choice') {
      const options = (field.options || []).map(option => {
        const code = option && typeof option === 'object' ? option.code : option;
        const label = option && typeof option === 'object' ? (option.label || option.code) : option;
        return `<option value="${escapeHtml(code)}"${value === code ? ' selected' : ''}>${escapeHtml(label)}</option>`;
      }).join('');
      control = `<select data-document-field="${key}"${disabled ? ' disabled' : ''}><option value="">Choose</option>${options}</select>`;
    } else if (field.type === 'boolean') {
      control = `<select data-document-field="${key}"${disabled ? ' disabled' : ''}><option value="">Choose</option><option value="true"${value === true ? ' selected' : ''}>Yes</option><option value="false"${value === false ? ' selected' : ''}>No</option></select>`;
    } else if (field.type === 'textarea') {
      control = `<textarea data-document-field="${key}"${disabled ? ' disabled' : ''}>${escapeHtml(value)}</textarea>`;
    } else {
      const type = field.type === 'datetime' ? 'datetime-local' : 'text';
      control = field.type === 'date'
        ? nativeDateControl(`data-document-field="${key}"${field.required ? ' required' : ''}`, value, disabled)
        : `<input type="${type}" data-document-field="${key}" value="${escapeHtml(value)}"${field.required ? ' required' : ''}${disabled ? ' disabled' : ''}>`;
    }
    const correction = ['ready_for_review', 'signed_pending_approval'].includes(current.status)
      ? correctionToggle('document_field', `${document.key}.${field.key}`, `${document.name}: ${field.label || field.key}`)
      : '';
    const wrapperTag = field.type === 'repeating_group' ? 'div' : 'label';
    return `<${wrapperTag} class="laf-field" data-field-wrap="${key}"><span>${escapeHtml(field.label || field.key)}${required}</span><small class="field-error" aria-live="polite"></small>${correction}${locked ? '<small class="field-help">Filled from the main LAF</small>' : field.help_text ? `<small class="field-help">${escapeHtml(field.help_text)}</small>` : ''}${control}</${wrapperTag}>`;
  }

  function supportingDocumentMarkup(document, editable) {
    const fields = (document?.schema?.fields || []).map(field => supportingDocumentField(field, document, editable)).join('');
    return `<div class="section-title"><div><h3>${escapeHtml(document.name)}</h3><p>Shared LAF values are locked. Complete the remaining fields, save, then preview this document.</p></div><button type="button" class="preview-link" data-support-preview="${escapeHtml(document.key)}">${latestPreviewLabel('Preview document')}</button></div><div class="laf-grid">${fields || '<div class="empty-state">This document uses only values already collected in the main LAF.</div>'}</div>`;
  }

  function correctionTargetStep(identity) {
    const [targetType, targetKey] = String(identity || '').split(':', 2);
    const sections = wizardSections();
    if (targetType === 'requirement') return sections.findIndex(item => item.key === 'product_requirements');
    if (targetType === 'document_field') {
      const documentKey = targetKey.split('.', 1)[0];
      return sections.findIndex(item => item.key === `document:${documentKey}`);
    }
    return sections.findIndex(section => fieldsFor(section.key).some(field => field.key === targetKey));
  }

  function openReviewDialog(mode) {
    if (mode === 'request_correction' && !reviewTargets.size) {
      return showToast('Flag at least one field or requirement before requesting correction.', true);
    }
    reviewDialogMode = mode;
    reviewReturnFocus = document.activeElement;
    const overlay = document.getElementById('origination-review-overlay');
    document.getElementById('review-dialog-eyebrow').textContent = 'Maker-checker review';
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
        eyebrow: details.approval_invalidated ? 'Approval will be invalidated' : 'Frozen packet will be cancelled',
        title: 'Return this application to Draft?',
        hint: details.approval_invalidated
          ? 'Editing will cancel the checker-approved packet. The application must be prepared and fully reviewed again before signing.'
          : 'Editing will cancel the prepared review packet. Operations must prepare a new frozen packet before review.',
        body: '<aside class="notice warning"><strong>This action is audited</strong><span>Existing frozen hashes remain in history, but they can no longer be approved or signed.</span></aside>',
        footer: '<button type="button" class="btn btn-secondary" id="origination-recall-cancel">Keep current packet</button><button type="button" class="btn btn-danger" id="origination-recall-confirm">Cancel packet and edit</button>',
        trigger: document.getElementById('origination-recall'),
      });
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
    showToast('Application returned to Draft. Previous packet and approval are no longer valid.');
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
      xhr.setRequestHeader('Idempotency-Key', requestId);
      xhr.setRequestHeader('X-Request-ID', requestId);
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

  async function openEvidenceCamera(requirementKey, trigger) {
    if (!navigator.mediaDevices?.getUserMedia) {
      return showToast('This Telegram WebView cannot open the camera directly. Use Choose file instead.', true);
    }
    openSheet({
      mode: 'camera', eyebrow: 'Requirement evidence', title: 'Take photo',
      hint: 'Keep the document inside the frame. Nothing is uploaded until you use this photo.', trigger,
      body: '<div class="evidence-camera-stage"><video id="evidence-camera-video" autoplay playsinline muted></video><canvas id="evidence-camera-canvas" hidden></canvas></div>',
      footer: '<button type="button" class="btn btn-secondary" data-sheet-cancel>Cancel</button><button type="button" class="btn btn-primary" id="evidence-camera-capture">Use photo</button>',
    });
    document.querySelector('[data-sheet-cancel]').onclick = () => closeSheet();
    const capture = document.getElementById('evidence-camera-capture');
    const video = document.getElementById('evidence-camera-video');
    try {
      activeCameraStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' } }, audio: false,
      });
      video.srcObject = activeCameraStream;
      await video.play();
    } catch (_) {
      closeSheet();
      return showToast('Camera access was unavailable. Allow camera permission or use Choose file.', true);
    }
    capture.onclick = async () => {
      if (!video.videoWidth || !video.videoHeight) return showToast('The camera is still starting. Try again.', true);
      capture.disabled = true;
      const canvas = document.getElementById('evidence-camera-canvas');
      const maximum = 2000;
      const scale = Math.min(1, maximum / Math.max(video.videoWidth, video.videoHeight));
      canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
      canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
      canvas.getContext('2d')?.drawImage(video, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.88));
      if (!blob) { capture.disabled = false; return showToast('The photo could not be captured. Try again.', true); }
      const file = new File([blob], `evidence-${Date.now()}.jpg`, { type: 'image/jpeg' });
      closeSheet({ restoreFocus: false });
      await uploadEvidenceFile(file, requirementKey, trigger);
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

  async function saveDocumentSelection() {
    // Required documents are displayed as checked, disabled controls. They are
    // already selected by the server and are not part of the optional-choice
    // API contract; :checked alone also matches disabled controls.
    const selectedKeys = [...root().querySelectorAll('[data-document-select]:checked:not(:disabled)')].map(input => input.dataset.documentSelect);
    const result = await postJson(`/applications/${current.id}/documents/selection/`, {
      revision: current.revision,
      selected_keys: selectedKeys,
    });
    if (!result.ok) {
      showToast(result.data?.error || 'Could not save the supporting-document selection.', true);
      return false;
    }
    current = result.data.application;
    previewedRevision = current.revision;
    return true;
  }

  async function saveSupportingDocument(documentKey) {
    const document = (current?.document_packet?.documents || []).find(item => item.key === documentKey);
    const payload = { ...(document?.field_payload || {}) };
    root().querySelectorAll('[data-repeatable-field]').forEach(container => {
      payload[container.dataset.repeatableField] = [...container.querySelectorAll('[data-repeat-row]')].map(row => {
        const item = { row_id: row.dataset.rowId || newRowId() };
        row.querySelectorAll('[data-repeat-column]').forEach(input => { item[input.dataset.repeatColumn] = input.value.trim(); });
        return item;
      });
    });
    root().querySelectorAll('[data-document-field]').forEach(input => {
      if (input.disabled) return;
      if (input.options && ['true', 'false'].includes(input.value)) payload[input.dataset.documentField] = input.value === 'true';
      else payload[input.dataset.documentField] = input.value;
    });
    const result = await postJson(`/applications/${current.id}/documents/${encodeURIComponent(documentKey)}/fields/`, {
      revision: current.revision,
      payload,
    });
    if (!result.ok) {
      if (result.data?.errors) showErrors(result.data.errors);
      showToast(result.data?.error || 'Could not save this supporting document.', true);
      return false;
    }
    current = result.data.application;
    previewedRevision = current.revision;
    return true;
  }

  async function openSupportingPreview(documentKey) {
    await openPreview(documentKey);
  }

  async function openPacketPreview() {
    await openPreview('__packet__');
  }

  function bindEditor(editable) {
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
    root().querySelectorAll('[data-edit-step]').forEach(button => button.onclick = () => {
      const targetStep = Number(button.dataset.editStep);
      const targetSection = wizardSections()[targetStep];
      if (current.status === 'draft' && targetSection) unlockedDraftSections.add(targetSection.key);
      renderEditor(current, targetStep);
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
      if (hasFinalSignedPacket()) return openPreview('__signed_packet__');
      const sectionKey = wizardSections()[step]?.key || '';
      const errors = sectionErrors(sectionKey); showErrors(errors);
      if (Object.keys(errors).length) return showToast('Complete the required document fields before previewing.', true);
      if (editable && !(await saveSupportingDocument(button.dataset.supportPreview))) return;
      await openSupportingPreview(button.dataset.supportPreview);
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
        if (container.dataset.mainRepeatable) scheduleSave();
        else setSaveState('Supporting document not saved', 'dirty');
      });
      container.addEventListener('click', event => {
        const remove = event.target.closest('[data-repeat-remove]');
        if (!remove) return;
        remove.closest('[data-repeat-row]')?.remove();
        refreshRepeatableField(container);
        if (container.dataset.mainRepeatable) scheduleSave();
        else setSaveState('Supporting document not saved', 'dirty');
      });
      container.addEventListener('input', () => {
        refreshRepeatableField(container);
        if (container.dataset.mainRepeatable) scheduleSave();
        else setSaveState('Supporting document not saved', 'dirty');
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
    else if (current.status === 'reviewed' && capabilities.can_start_signing) {
      root().querySelector('.laf-grid')?.addEventListener('input', () => {
        const configuration = collectProductConfiguration();
        current.product_requirements = configuration.requirements;
        setSaveState('Signing requirements not saved', 'dirty');
      });
    }
    root().querySelectorAll('.native-date-control input[type="date"]').forEach(input => input.addEventListener('change', () => {
      syncNativeDateDisplays(input.closest('.native-date-control'));
      if (input.dataset.field) scheduleSave();
      if (wizardSections()[step]?.key === facilitySectionKey()) scheduleCommercialQuotePreview();
    }));
    root().querySelector('[data-clear-guarantor-two]')?.addEventListener('click', () => {
      const card = root().querySelector('[data-guarantor-two-card]');
      card?.querySelectorAll('input, select, textarea').forEach(input => {
        if (input.type === 'checkbox' || input.type === 'radio') input.checked = false;
        else input.value = '';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
      });
      syncNativeDateDisplays(card);
      scheduleSave();
      showToast('Guarantor 2 cleared. Save this section to omit the second guarantor.');
    });
    root().querySelector('[data-location-type="county"]')?.addEventListener('change', syncOriginationSubCountySelect);
    document.getElementById('wizard-previous')?.addEventListener('click', async () => {
      if (current.status === 'draft' && !editable) return renderEditor(current, step - 1);
      if (await saveDraft(true)) renderEditor(current, step - 1);
    });
    document.getElementById('wizard-next')?.addEventListener('click', () => runPrimaryAction('Saving...', async () => {
      const section = wizardSections()[step];
      const errors = sectionErrors(section.key); showErrors(errors);
      if (Object.keys(errors).length) return showToast('Complete the required fields in this section.', true);
      const continueToNext = () => {
        if (current.status === 'draft') {
          completedDraftSections.add(section.key);
          unlockedDraftSections.delete(section.key);
        }
        renderEditor(current, step + 1);
      };
      if (current.status === 'draft' && !editable) return continueToNext();
      if (section.key === 'document_selection') {
        if (await saveDocumentSelection()) continueToNext();
      } else if (section.key.startsWith('document:')) {
        if (await saveSupportingDocument(section.key.slice('document:'.length))) continueToNext();
      } else if (await saveDraft(true)) continueToNext();
    }));
    document.getElementById('origination-preview')?.addEventListener('click', () => {
      const selectedDocuments = (current?.document_packet?.documents || []).filter(item => item.selected);
      if (wizardSections()[step]?.key === 'review' && selectedDocuments.length > 1 && !current?.review_packet_ready && !hasFinalSignedPacket()) {
        return openPacketPreview();
      }
      return openPreview();
    });
    document.getElementById('origination-preview-early')?.addEventListener('click', () => openPreview());
    document.getElementById('origination-confirm-signing')?.addEventListener('click', () => runPrimaryAction('Confirming and freezing...', async () => {
      if (['draft', 'correction_required'].includes(current.status) && !(await saveDraft(true))) return;
      if (['draft', 'correction_required'].includes(current.status) && previewedRevision !== current.revision) {
        return showToast('Preview the complete packet for this saved revision before confirming.', true);
      }
      const result = await postJson(`/applications/${current.id}/confirm-signing/`, { revision: current.revision });
      if (!result.ok) {
        if (result.data?.errors) showServerErrors(result.data.errors);
        return showToast(result.data?.error || 'Could not confirm and freeze the signing packet.', true);
      }
      current = result.data.application;
      showToast('Packet frozen. Signing can begin.');
      renderEditor(current, wizardSections().length - 1);
    }));
    document.getElementById('origination-submit')?.addEventListener('click', () => runPrimaryAction('Submitting...', async () => {
      if (!(await saveDraft(true))) return;
      if (previewedRevision !== current.revision) return showToast('Preview the filled document for this saved revision before submitting.', true);
      const result = await postJson(`/applications/${current.id}/submit/`, { revision: current.revision });
      if (!result.ok) {
        if (result.data?.errors) showServerErrors(result.data.errors);
        return showToast(result.data?.error || 'Could not submit the application.', true);
      }
      await load();
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
        showToast('Frozen packet approved. Operations can now start signing.');
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
        if (!result.ok) return showToast(result.data?.error || 'Could not approve the signed packet.', true);
        showToast('Signed packet approved and locked.');
        await load();
      });
    });
    document.getElementById('origination-takeover-review')?.addEventListener('click', () => openReviewDialog('takeover'));
    document.getElementById('origination-prepare-review')?.addEventListener('click', () => runPrimaryAction('Freezing packet...', async () => {
      if (!(await saveSigningRequirements())) return;
      const result = await postJson(`/applications/${current.id}/prepare-review-packet/`, { revision: current.revision });
      if (!result.ok) {
        if (result.data?.errors) showServerErrors(result.data.errors);
        return showToast(result.data?.error || 'Could not prepare the frozen review packet.', true);
      }
      current = result.data.application;
      showToast('Frozen review packet prepared for the checker.');
      renderEditor(current, wizardSections().length - 1);
    }));
    document.getElementById('origination-start-signing')?.addEventListener('click', () => runPrimaryAction('Starting signing...', async () => {
      const result = await postJson(`/applications/${current.id}/prepare-signing/`, {
        ...reviewPacketPayload(), revision: current.revision,
      });
      if (!result.ok) return showToast(result.data?.error || 'Could not start signing.', true);
      current = result.data.application;
      showToast('Approved packet is ready for signer dispatch.');
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
          signer_role: button.dataset.signerRole, stamp_asset_id: stampAssetId,
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
          package_id: button.dataset.packageId, signer_role: button.dataset.signerRole,
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
                package_id: button.dataset.packageId, signer_role: button.dataset.signerRole,
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
    root().querySelectorAll('[data-production-stamp]').forEach(button => button.addEventListener('click', () => runPrimaryAction('Applying production stamp...', async () => {
      const stampAssetId = button.parentElement.querySelector('[data-production-stamp-select]')?.value || '';
      if (!stampAssetId) return showToast('Choose an active production stamp.', true);
      const result = await postJson(`/applications/${current.id}/production-stamp/`, {
        revision: current.revision, package_id: button.dataset.packageId,
        document_key: button.dataset.documentKey, slot_key: button.dataset.slotKey,
        signer_role: button.dataset.signerRole, stamp_asset_id: stampAssetId,
      });
      if (!result.ok) return showToast(result.data?.error || 'Could not apply the production stamp.', true);
      await load(); showToast('Production stamp applied.');
    })));
    document.getElementById('origination-archive-signed')?.addEventListener('click', event => runPrimaryAction('Archiving signed packet...', async () => {
      const result = await postJson(`/applications/${current.id}/archive-signed/`, {package_id:event.currentTarget.dataset.packageId});
      if (!result.ok) return showToast(result.data?.error || 'Could not archive the signed packet.', true);
      await load(); showToast('Signed packet archived in restricted Drive.');
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
      return showToast(result.data?.error || 'Could not open the signed packet.', true);
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

  async function openPreview(documentKey = '') {
    // Event listeners must call this through a wrapper. Keep a defensive
    // fallback too, so a future direct binding cannot turn a PointerEvent into
    // a document-key URL segment.
    if (typeof documentKey !== 'string') documentKey = '';
    documentKey = resolveLatestPreviewKey(documentKey);
    if (!documentKey && ['draft', 'correction_required'].includes(current.status) && !(await saveDraft(true))) return;
    previewDocumentKey = documentKey;
    previewSucceeded = false;
    clearPreviewPageCache();
    previewPage = 1; previewZoom = 100; previewPageCount = 1;
    previewRequestId = requestKey('preview');
    document.querySelector('.preview-toolbar').hidden = false;
    const overlay = document.getElementById('document-preview-overlay');
    const title = document.getElementById('preview-title');
    if (title) title.textContent = documentKey === '__signed_packet__'
      ? (current?.signing_package?.verified_signing?.archive_status === 'uploaded' ? 'Archived signed packet' : 'Final signed packet')
      : documentKey === '__signing_packet__' ? 'Current signing packet'
      : documentKey === '__review_packet__' ? (current?.status === 'reviewed' ? 'Checker-approved frozen packet' : 'Frozen packet for final review')
      : documentKey === '__packet__' ? 'Filled document packet'
      : documentKey === '__test_signing__' ? 'TEST signed packet'
      : 'Filled loan document';
    previewReturnFocus = document.activeElement;
    overlay.hidden = false;
    overlay.setAttribute('aria-hidden', 'false');
    document.body.classList.add('origination-modal-open');
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
    const key = previewRequestId || requestKey('preview');
    const applicationId = current.id;
    const revision = current.revision;
    const signedPacketPreview = ['__signed_packet__', '__signing_packet__'].includes(previewDocumentKey);
    const previewPath = signedPacketPreview
      ? `/applications/${applicationId}/${previewDocumentKey === '__signing_packet__' ? 'current-signing-packet' : 'signed-packet'}/?package_id=${encodeURIComponent(current?.signing_package?.id || '')}&preview_format=image&page=${pageNumber}`
      : previewDocumentKey === '__review_packet__'
      ? `/applications/${applicationId}/review-packet/preview/`
      : previewDocumentKey === '__test_signing__'
      ? `/applications/${applicationId}/test-signing/preview/`
      : previewDocumentKey === '__packet__'
      ? `/applications/${applicationId}/packet/preview/`
      : previewDocumentKey
      ? `/applications/${applicationId}/documents/${encodeURIComponent(previewDocumentKey)}/preview/`
      : `/applications/${applicationId}/preview/`;
    const pending = apiFetch(previewPath, signedPacketPreview ? {
      headers: { 'X-Request-ID': key },
    } : {
      method: 'POST', headers: { 'Idempotency-Key': key, 'X-Request-ID': key }, body: JSON.stringify({
        revision, request_id: key, preview_format: 'image', page: pageNumber,
        package_id: ['__test_signing__', '__review_packet__'].includes(previewDocumentKey) ? current?.signing_package?.id : undefined,
        unsigned_document_hash: previewDocumentKey === '__review_packet__' ? current?.signing_package?.unsigned_document_hash : undefined,
        review_scope_sha256: previewDocumentKey === '__review_packet__' ? current?.signing_package?.review_scope_sha256 : undefined,
      }),
    }).then(result => {
      if (!result.ok || !result.blob) return { error: result.data?.error || 'Could not generate the filled document.' };
      if (key !== previewRequestId || current?.id !== applicationId) return { stale: true };
      const entry = { url: URL.createObjectURL(result.blob), pageCount: Math.max(1, result.pageCount || 1), packetVersion: result.packetVersion || '' };
      if (signedPacketPreview && result.packetVersion) previewPacketVersion = result.packetVersion;
      previewPageUrls.set(pageNumber, entry);
      if (!previewDocumentKey && pageNumber === 1) {
        previewedRevision = current.revision;
        previewSucceeded = true;
      }
      if (previewDocumentKey === '__packet__' && pageNumber === 1) {
        previewedRevision = current.revision;
        previewSucceeded = true;
        (current?.document_packet?.documents || []).filter(item => item.selected).forEach(item => {
          item.previewed = true;
        });
        if (current?.document_packet) current.document_packet.primary_ready = true;
      }
      if (previewDocumentKey && !['__packet__', '__review_packet__', '__test_signing__', '__signed_packet__', '__signing_packet__'].includes(previewDocumentKey) && pageNumber === 1) {
        const document = current?.document_packet?.documents?.find(item => item.key === previewDocumentKey);
        if (document) document.previewed = true;
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
    if (entry?.error) { closePreview(); return showToast(entry.error, true); }
    if (!entry || entry.stale || requestedPage !== previewPage) return;
    previewUrl = entry.url;
    previewPageCount = entry.pageCount;
    updatePreviewFrame();
    const toast = document.getElementById('origination-toast');
    if (!wasCached && toast) toast.hidden = true;
    [requestedPage - 1, requestedPage + 1]
      .filter(pageNumber => pageNumber >= 1 && pageNumber <= previewPageCount)
      .forEach(pageNumber => { void fetchPreviewPage(pageNumber); });
  }

  function clearPreviewPageCache() {
    previewPageUrls.forEach(entry => URL.revokeObjectURL(entry.url));
    previewPageUrls.clear();
    previewPageLoads.clear();
    previewUrl = '';
  }

  function updatePreviewFrame() {
    const image = document.getElementById('document-preview-image');
    if (image && previewUrl) { image.src = previewUrl; image.style.width = `${previewZoom}%`; }
    const page = document.getElementById('preview-page'); if (page) page.textContent = `Page ${previewPage} of ${previewPageCount}`;
    const zoom = document.getElementById('preview-zoom'); if (zoom) zoom.textContent = `${previewZoom}%`;
    const previous = document.getElementById('preview-previous'); if (previous) previous.disabled = previewPage <= 1;
    const next = document.getElementById('preview-next'); if (next) next.disabled = previewPage >= previewPageCount;
  }

  function setPreviewZoom(value, focalPoint) {
    const stage = document.getElementById('document-preview-stage');
    const previousZoom = previewZoom;
    const nextZoom = Math.max(50, Math.min(300, Math.round(value)));
    if (!stage || nextZoom === previousZoom) return;
    const bounds = stage.getBoundingClientRect();
    const localX = (focalPoint?.x ?? (bounds.left + bounds.width / 2)) - bounds.left;
    const localY = (focalPoint?.y ?? (bounds.top + bounds.height / 2)) - bounds.top;
    const ratio = nextZoom / previousZoom;
    previewZoom = nextZoom;
    updatePreviewFrame();
    // Retain the document point beneath the user's fingers after resizing.
    stage.scrollLeft = (stage.scrollLeft + localX) * ratio - localX;
    stage.scrollTop = (stage.scrollTop + localY) * ratio - localY;
  }

  function bindPreviewPinch() {
    const stage = document.getElementById('document-preview-stage');
    if (!stage) return;
    stage.addEventListener('pointerdown', event => {
      previewPointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      if (previewPointers.size === 1) {
        previewSwipe = {
          pointerId: event.pointerId,
          startX: event.clientX,
          startY: event.clientY,
          startedAt: Date.now(),
          cancelled: false,
        };
      }
      try { stage.setPointerCapture(event.pointerId); } catch (_) { /* WebView may already own capture. */ }
      if (previewPointers.size === 2) {
        if (previewSwipe) previewSwipe.cancelled = true;
        const points = [...previewPointers.values()];
        previewPinch = { distance: pointDistance(points), zoom: previewZoom };
      }
      event.preventDefault();
    });
    stage.addEventListener('pointermove', event => {
      const previous = previewPointers.get(event.pointerId);
      if (!previous) return;
      previewPointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      if (previewPointers.size === 2 && previewPinch) {
        const points = [...previewPointers.values()];
        const distance = pointDistance(points);
        if (previewPinch.distance) {
          setPreviewZoom(previewPinch.zoom * (distance / previewPinch.distance), pointMidpoint(points));
        }
      } else if (previewPointers.size === 1) {
        stage.scrollLeft -= event.clientX - previous.x;
        stage.scrollTop -= event.clientY - previous.y;
      }
      event.preventDefault();
    });
    const finishPointer = event => {
      const swipe = previewSwipe;
      if (event.type === 'pointerup' && swipe && swipe.pointerId === event.pointerId && !swipe.cancelled && previewPointers.size === 1) {
        const deltaX = event.clientX - swipe.startX;
        const deltaY = event.clientY - swipe.startY;
        const threshold = Math.max(56, stage.clientWidth * .16);
        const deliberateHorizontalSwipe = Math.abs(deltaX) >= threshold
          && Math.abs(deltaX) > Math.abs(deltaY) * 1.35
          && Date.now() - swipe.startedAt <= 900;
        if (deliberateHorizontalSwipe) navigatePreviewPage(deltaX < 0 ? 1 : -1);
      }
      previewPointers.delete(event.pointerId);
      previewPinch = null;
      if (!previewPointers.size || swipe?.pointerId === event.pointerId) previewSwipe = null;
    };
    stage.addEventListener('pointerup', finishPointer);
    stage.addEventListener('pointercancel', finishPointer);
    stage.addEventListener('lostpointercapture', finishPointer);
  }

  async function navigatePreviewPage(direction) {
    const requestedPage = previewPage + direction;
    if (requestedPage < 1 || requestedPage > previewPageCount) return;
    previewPage = requestedPage;
    await loadPreviewPage();
    const stage = document.getElementById('document-preview-stage');
    if (stage) { stage.scrollLeft = 0; stage.scrollTop = 0; }
  }

  function closePreview() {
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
    previewPinch = null;
    previewSwipe = null;
    previewPointers.clear();
    document.body.classList.remove('origination-modal-open');
    syncTelegramControls();
    const returnFocus = previewReturnFocus;
    previewReturnFocus = null;
    const supportingStep = current && !previewDocumentKey && previewSucceeded && previewedRevision === current.revision
      && !current.document_packet?.primary_ready
      ? wizardSections().findIndex(item => item.key === 'document_selection')
      : -1;
    previewDocumentKey = '';
    previewSucceeded = false;
    if (supportingStep >= 0) {
      showToast('Main LAF previewed. Continue with supporting documents.');
      window.requestAnimationFrame(() => renderEditor(current, supportingStep));
      return;
    }
    window.requestAnimationFrame(() => returnFocus?.focus?.());
  }

  function showToast(message, presentation = 'success') {
    const toast = document.getElementById('origination-toast');
    const settings = typeof presentation === 'object' && presentation
      ? presentation : { tone: presentation === true ? 'error' : String(presentation || 'success') };
    const tone = ['info', 'success', 'warning', 'error'].includes(settings.tone) ? settings.tone : 'info';
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
      if (key === 'mine') return listState.queue === 'mine' ? listTotal : '';
      if (key === 'corrections') return listCounts.correction_required || 0;
      if (key === 'prepare') return listCounts.packet_preparation || 0;
      if (key === 'review') return listCounts.final_review || 0;
      if (key === 'signing') return (listCounts.reviewed || 0) + (listCounts.signing_pending || 0) + (listCounts.partially_signed || 0);
      if (key === 'my_signatures') return listCounts.my_signatures || 0;
      if (key === 'final_review') return listCounts.signed_final_review || 0;
      return '';
    };
    const cards = applications.map(item => {
      const identity = item.applicant_summary || {};
      const applicantName = identity.name || 'Applicant details pending';
      const identifiers = [identity.national_id ? `ID ${identity.national_id}` : '', identity.phone || ''].filter(Boolean).join(' · ');
      return `<button type="button" class="application-card" data-application-id="${item.id}"><span><strong>${escapeHtml(applicantName)}</strong><small>${escapeHtml(identifiers || 'ID and telephone pending')}</small><small>${escapeHtml(item.product_name)} · ${escapeHtml(item.branch || 'No branch')} · ${escapeHtml(item.reference_number)}${capabilities.can_review ? ` · ${escapeHtml(item.officer_name || 'Unassigned')}` : ''}</small><small class="application-status-text">${escapeHtml(item.status_text || applicationStatusLabel(item))}</small></span><span class="application-card-state"><span class="status-chip status-${escapeHtml(item.status)}">${escapeHtml(applicationStatusLabel(item))}</span>${iconSvg('arrowRight')}</span></button>`;
    }).join('');
    const alerts = reviewerAlerts.map(item => `<button type="button" class="reviewer-alert" data-reviewer-alert="${escapeHtml(item.id)}" data-application-id="${escapeHtml(item.application_id)}"><span><strong>Approval invalidated</strong><small>${escapeHtml(item.message)}</small></span>${iconSvg('arrowRight')}</button>`).join('');
    const queueTabs = [
      ...(capabilities.can_create ? [['mine', 'My applications'], ['corrections', 'Corrections']] : []),
      ...(capabilities.can_review ? [['review', 'Review']] : []),
      ...(capabilities.can_review && capabilities.conditional_approval_enabled ? [['final_review', 'Final review']] : []),
      ...(capabilities.can_start_signing ? [['prepare', 'Prepare packet']] : []),
      ...(capabilities.can_start_signing || capabilities.can_staff_sign ? [['signing', 'Signing']] : []),
      ...(capabilities.can_staff_sign ? [['my_signatures', 'My signatures']] : []),
    ].map(([key, label]) => {
      const count = queueCount(key);
      return `<button type="button" data-queue="${key}" class="queue-tab${listState.queue === key ? ' active' : ''}"><span>${label}</span>${count !== '' ? `<strong>${count}</strong>` : ''}</button>`;
    }).join('');
    const activeChips = [
      ...(listState.productKey ? [{ key: 'productKey', label: allProducts.find(item => item.product_key === listState.productKey)?.name || listState.productKey }] : []),
      ...(listState.status ? [{ key: 'status', label: listState.status.replaceAll('_', ' ') }] : []),
    ].map(item => `<button type="button" class="filter-chip" data-remove-filter="${item.key}"><span>${escapeHtml(item.label)}</span>${iconSvg('close')}</button>`).join('');
    const pagination = listState.pages > 1 ? `<div class="pagination-actions"><button type="button" class="btn btn-secondary" id="origination-page-previous"${listState.page <= 1 ? ' disabled' : ''}>Previous</button><span>Page ${listState.page} of ${listState.pages}</span><button type="button" class="btn btn-secondary" id="origination-page-next"${listState.page >= listState.pages ? ' disabled' : ''}>Next</button></div>` : '';
    const startAction = capabilities.can_create ? `<button type="button" class="btn btn-primary compact-start" id="origination-start">${iconSvg('plus')} Start application</button>` : '';
    root().innerHTML = `<section class="list-toolbar"><div><p class="eyebrow">Paperless lending</p><h2>Applications</h2></div><div>${startAction}<button type="button" class="icon-button" id="origination-list-refresh" aria-label="Refresh applications">${iconSvg('refresh')}</button></div></section>${alerts ? `<section class="reviewer-alerts" aria-label="Reviewer alerts"><p class="eyebrow">Attention</p>${alerts}</section>` : ''}<nav class="queue-tabs" aria-label="Origination queues">${queueTabs}</nav><form class="list-search" id="origination-search"><input name="q" value="${escapeHtml(listState.query)}" placeholder="Search applicant, ID, telephone or reference" aria-label="Search applications"><button type="button" class="filter-button${activeChips ? ' active' : ''}" id="origination-open-filters">${iconSvg('filter')}<span>Filters</span>${activeChips ? '<b></b>' : ''}</button></form>${activeChips ? `<div class="active-filters" aria-label="Active filters">${activeChips}</div>` : ''}<div class="list-heading"><h3>${escapeHtml(listState.queue ? listState.queue.replaceAll('_', ' ') : 'Applications')}</h3><span>${listTotal} ${listTotal === 1 ? 'application' : 'applications'}</span></div><div class="application-list">${cards || '<div class="empty-state"><strong>No applications in this queue</strong><span>Change the filters or refresh.</span></div>'}</div>${pagination}`;
    root().querySelectorAll('[data-application-id]').forEach(button => button.onclick = async () => {
      listScrollY = window.scrollY;
      button.disabled = true;
      const result = await apiFetch(`/applications/${button.dataset.applicationId}/`, {});
      button.disabled = false;
      if (!result.ok) return showToast(result.data?.error || 'Could not open this application.', true);
      if (button.dataset.reviewerAlert) {
        const seen = await postJson(`/reviewer-notices/${button.dataset.reviewerAlert}/seen/`, {});
        if (seen.ok) reviewerAlerts = reviewerAlerts.filter(item => item.id !== button.dataset.reviewerAlert);
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
    select.innerHTML = `<option value="">Choose product</option>${products.map(item => `<option value="${escapeHtml(item.product_key)}">${escapeHtml(item.name)}</option>`).join('')}`;
    select.disabled = !products.length;
    select.onchange = syncCreationPrimary;
    syncCreationPrimary();
    if (!products.length) showToast('No active origination product is available for this branch.', true);
  }

  async function loadApplications({ focusSearch = false } = {}) {
    const generation = ++listRequestGeneration;
    const result = await apiFetch(`/applications/?${applicationListParams()}`, {});
    if (generation !== listRequestGeneration) return;
    if (!result.ok) return showToast(result.data?.error || 'Could not load applications.', true);
    applications = result.data.applications || [];
    listCounts = result.data.counts || {};
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
    products = allProducts;
    branches = productResult.data.branches || [];
    locationCatalog = productResult.data.location_catalog || {};
    capabilities = productResult.data.capabilities || capabilities;
    if (!listState.queue) listState.queue = capabilities.can_create ? 'mine' : capabilities.can_start_signing ? 'prepare' : capabilities.can_staff_sign ? 'signing' : capabilities.can_review ? 'review' : '';
    await loadApplications();
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
    previewedRevision = current.revision;
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
  window.addEventListener('pagehide', () => preserveDraftOnExit());
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
      if (sheetMode) return closeSheet();
      if (reviewDialogMode) return closeReviewDialog();
      if (!document.getElementById('document-preview-overlay').hidden) return closePreview();
      if (current) await exitEditor();
    });
  } catch (_) { /* In-DOM controls remain available. */ }
  load();
})();
