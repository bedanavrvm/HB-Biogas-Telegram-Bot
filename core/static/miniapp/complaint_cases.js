(function () {
  'use strict';

  const apiClient = window.ComplaintCasesMiniAppApi;
  const utils = window.MiniAppUtils || {};
  const telegram = utils.initTelegram ? utils.initTelegram() : window.Telegram?.WebApp;
  const $ = id => document.getElementById(id);
  const state = {
    groupId: document.body.dataset.groupId || '',
    initData: telegram?.initData || '',
    status: 'pending', query: '', page: 1, pages: 1,
    capabilities: new Set(), currentCase: null, submitting: false,
    debounce: null, suggestionTimer: null, suggestionSequence: 0, suggestionUnavailableUntil: 0,
    suggestedCategory: null, categoryInferenceToken: '', categorySuggestionCache: new Map(), latitude: '', longitude: '',
    workspace: 'queue', returnWorkspace: 'queue', globalLoaded: false,
    globalOverview: null, globalPage: 1, globalPages: 1, globalPageSize: 50,
    globalSort: '-date_reported', reportGridApi: null, reportGridZoom: null, reportGridLoading: false,
    reportGridCopyTimer: null, reportGridCopyPointerId: null, reportGridCopyStart: null, reportGridCopyReadyCell: null,
    categoryChartType: 'bar', reportGranularity: 'month',
    reportChartDisplay: (() => { try { return localStorage.getItem('complaint-report-chart-display') === 'list' ? 'list' : 'carousel'; } catch (error) { return 'carousel'; } })(),
    reportChartSlide: 0, reportChartTouchStart: null,
    reportFilterSheetOpen: false, reportFilterSnapshot: null, reportFilterReturnFocus: null,
    reportSummarySequence: 0, reportTableSequence: 0, reportSearchTimer: null,
    reportTableAbortController: null,
    evidence: { create: [], resolve: [] },
    categoryDescriptions: new Map(),
    locationOptions: { branches: [], counties: [], sub_counties: [] },
    locationOptionsLoading: false, locationOptionsSequence: 0,
    evidenceLimits: { max_files: 10, max_file_size_mb: 10, max_total_upload_mb: 30 },
    cameraStream: null, cameraTarget: '', cameraReplaceId: '', cameraSessionStartCount: 0,
    mediaViewerObjectUrl: '', mediaViewerRestoreFocus: null,
    mediaViewerMode: '', mediaViewerTarget: '', mediaViewerItemId: '',
    mediaViewerRequestSequence: 0, persistedEvidence: [],
    mediaViewerPointers: new Map(), mediaViewerSwipe: null,
    mediaViewerPinch: null, mediaViewerZoom: 100,
    exportObjectUrl: '', exportDownloadUrl: '', exportFilename: '', exportFile: null,
    errorRetry: null,
    pendingWrites: new Map(),
    errorRetryTimer: null,
    voiceInput: { enabled: false, max_seconds: 30, fields: [] },
  };
  let voiceRecorder = null;
  let voiceStream = null;
  let voiceChunks = [];
  let voiceStartedAt = 0;
  let voiceStopTimer = null;
  let discardVoiceOnStop = false;
  let activeVoiceAttempt = null;
  const acceptedVoiceAttempts = {};
  const VOICE_LANGUAGE_KEY = 'portal:voice-language';
  const VOICE_LANGUAGE_ORDER = ['auto', 'en', 'sw'];
  const VOICE_LANGUAGE_LABELS = { auto: 'Auto', en: 'ENG', sw: 'KIS' };

  function requestId(prefix) {
    return utils.createRequestId
      ? utils.createRequestId(prefix || 'complaint')
      : `${prefix || 'complaint'}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }
  function can(key) { return state.capabilities.has(key); }
  function notify(message, error) {
    if (!error) clearPresentedError();
    if (window.MiniAppRuntime?.showToast) {
      window.MiniAppRuntime.showToast(message, { tone: error ? 'error' : 'success' });
      utils.haptic?.(error ? 'error' : 'success');
      return;
    }
    const node = $('toast');
    node.textContent = message || '';
    node.classList.toggle('error', !!error);
    node.classList.add('visible');
    utils.haptic?.(error ? 'error' : 'success');
    clearTimeout(node._timer);
    node._timer = setTimeout(() => node.classList.remove('visible'), 4000);
  }
  function pendingWriteId(key, prefix) {
    if (!state.pendingWrites.has(key)) state.pendingWrites.set(key, requestId(prefix));
    return state.pendingWrites.get(key);
  }
  function settleWrite(key, error) {
    const status = Number(error?.status || 0);
    if (!error || (status >= 400 && status < 500)) state.pendingWrites.delete(key);
  }
  function clearPresentedError() {
    const banner = $('errorBanner');
    if (banner) banner.hidden = true;
    state.errorRetry = null;
    if (state.errorRetryTimer) clearInterval(state.errorRetryTimer);
    state.errorRetryTimer = null;
  }
  function focusErrorField(error) {
    const fields = Array.isArray(error?.details?.fields)
      ? error.details.fields : (error?.details?.field ? [error.details.field] : []);
    document.querySelectorAll('[aria-invalid="true"]').forEach(node => node.removeAttribute('aria-invalid'));
    let first = null;
    fields.forEach(name => {
      const node = document.getElementsByName(String(name))[0];
      if (!node) return;
      node.setAttribute('aria-invalid', 'true');
      if (!first) first = node;
    });
    if (first) first.focus({ preventScroll: false });
  }
  function presentError(error, retry) {
    if (!error || error.name === 'AbortError') return;
    const presentation = error.presentation || error.payload?.presentation || {};
    if (presentation.surface_hint === 'toast' && presentation.persistence === 'transient') {
      notify(error.message || 'We could not complete that action.', true);
      return;
    }
    const banner = $('errorBanner');
    if (!banner) { notify(error.message || 'We could not complete that action.', true); return; }
    state.errorRetry = typeof retry === 'function' ? retry : null;
    $('errorBannerTitle').textContent = presentation.tone === 'warning' ? 'Please check' : 'Action needed';
    $('errorBannerMessage').textContent = error.message || 'We could not complete that action.';
    const reference = String(error.supportReference || error.payload?.support_reference || utils.displaySupportReference?.(error.requestId || error.payload?.request_id) || '').trim();
    $('errorBannerReference').textContent = reference ? `Reference: ${reference}` : '';
    $('errorBannerReference').hidden = !reference;
    $('errorBannerRetry').hidden = !state.errorRetry;
    $('errorBannerCloseApp').hidden = !['authentication_required', 'outdated_client'].includes(error.code || error.payload?.code || '');
    $('errorBannerDismiss').hidden = presentation.persistence === 'until_resolved';
    banner.hidden = false;
    const retryAfter = Math.min(300, Math.max(0, Number(error.details?.retry_after || 0)));
    if (state.errorRetry && retryAfter) {
      let remaining = Math.ceil(retryAfter);
      const retryButton = $('errorBannerRetry');
      retryButton.disabled = true;
      retryButton.textContent = `Try Again in ${remaining}s`;
      state.errorRetryTimer = setInterval(() => {
        remaining -= 1;
        if (remaining > 0) { retryButton.textContent = `Try Again in ${remaining}s`; return; }
        clearInterval(state.errorRetryTimer); state.errorRetryTimer = null;
        retryButton.disabled = false; retryButton.textContent = 'Try Again';
      }, 1000);
    } else {
      $('errorBannerRetry').disabled = false;
      $('errorBannerRetry').textContent = 'Try Again';
    }
    focusErrorField(error);
    banner.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    utils.haptic?.('error');
  }
  function json(path, payload) {
    return apiClient.postJson(path, Object.assign({ group_id: state.groupId }, payload || {}), state.initData, utils);
  }
  function getJson(path, params, requestSettings) {
    return apiClient.getJson(path, Object.assign({ group_id: state.groupId }, params || {}), state.initData, utils, requestSettings);
  }
  function form(path, data, groupId) {
    return apiClient.postForm(path, data, state.initData, groupId || state.groupId, utils);
  }
  function textNode(tag, value, className) {
    const node = document.createElement(tag);
    node.textContent = value == null ? '' : String(value);
    if (className) node.className = className;
    return node;
  }
  function iconNode(name, className) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', ['lucide', className || ''].filter(Boolean).join(' '));
    svg.setAttribute('aria-hidden', 'true');
    const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    use.setAttribute('href', `#lucide-${name}`);
    svg.appendChild(use);
    return svg;
  }
  function buttonWithIcon(label, icon, className) {
    const button = document.createElement('button');
    button.type = 'button';
    if (className) button.className = className;
    button.append(iconNode(icon), textNode('span', label));
    return button;
  }
  function shortCopiedValue(value) {
    const text = String(value || '').replace(/\s+/g, ' ').trim();
    return text.length > 56 ? `${text.slice(0, 53)}...` : text;
  }
  async function copyReportCell(cell) {
    const rowIndex = Number(cell?.closest('.ag-row')?.getAttribute('row-index'));
    const columnId = cell?.getAttribute('col-id');
    if (!Number.isInteger(rowIndex) || !columnId || !state.reportGridApi) return false;
    const row = state.reportGridApi.getDisplayedRowAtIndex(rowIndex);
    const column = state.reportGridApi.getColumn(columnId);
    const value = String(cell.innerText || '').replace(/\s+/g, ' ').trim();
    if (!row || !column || !value) return false;
    try {
      await navigator.clipboard.writeText(value);
      notify(`${shortCopiedValue(value)} copied`);
      return true;
    } catch (_) {
      notify('Copy was unavailable on this device.', true);
      return false;
    }
  }
  function clearReportGridCopy() {
    clearTimeout(state.reportGridCopyTimer);
    state.reportGridCopyTimer = null;
    state.reportGridCopyPointerId = null;
    state.reportGridCopyStart = null;
    state.reportGridCopyReadyCell = null;
  }
  function bindReportGridCopy() {
    const grid = $('complaintReportGrid');
    if (grid.dataset.copyBound === 'true') return;
    grid.dataset.copyBound = 'true';
    grid.addEventListener('pointerdown', event => {
      if (!event.isPrimary || event.button !== 0 || event.target.closest('a, button, input, textarea, select')) return;
      const cell = event.target.closest('.ag-cell');
      if (!cell || !grid.contains(cell)) return;
      clearReportGridCopy();
      state.reportGridCopyPointerId = event.pointerId;
      state.reportGridCopyStart = { x: event.clientX, y: event.clientY, cell };
      state.reportGridCopyTimer = setTimeout(() => {
        const current = state.reportGridCopyStart;
        if (!current || event.pointerId !== state.reportGridCopyPointerId) return;
        state.reportGridCopyTimer = null;
        state.reportGridCopyReadyCell = current.cell;
        utils.haptic?.('light');
      }, 500);
    });
    grid.addEventListener('pointermove', event => {
      const start = state.reportGridCopyStart;
      if (!start || event.pointerId !== state.reportGridCopyPointerId) return;
      if (Math.abs(event.clientX - start.x) > 8 || Math.abs(event.clientY - start.y) > 8) clearReportGridCopy();
    });
    const finish = event => {
      const readyCell = event.pointerId === state.reportGridCopyPointerId ? state.reportGridCopyReadyCell : null;
      if (readyCell && event.type === 'pointerup') {
        event.preventDefault();
        void copyReportCell(readyCell);
      }
      if (event.pointerId === state.reportGridCopyPointerId) clearReportGridCopy();
    };
    grid.addEventListener('pointerup', finish);
    grid.addEventListener('pointercancel', finish);
  }

  function savedVoiceLanguage() {
    try {
      const value = localStorage.getItem(VOICE_LANGUAGE_KEY) || 'auto';
      return VOICE_LANGUAGE_ORDER.includes(value) ? value : 'auto';
    } catch (_) { return 'auto'; }
  }
  function detectedLanguageLabel(language) {
    const value = String(language || '').trim().toLowerCase();
    if (value === 'en' || value.startsWith('english')) return 'English';
    if (value === 'sw' || value.startsWith('swahili') || value.startsWith('kiswahili')) return 'Kiswahili';
    return value;
  }
  function voiceWidgetMarkup(fieldName, inputId) {
    const language = savedVoiceLanguage();
    return `<div class="voice-input" data-voice-field="${fieldName}" data-input-id="${inputId}" data-language-mode="${language}">
      <button type="button" class="voice-record-button" data-voice-action="record" aria-pressed="false" aria-label="Start voice input" title="Start voice input">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0M12 17v5M8 22h8"/></svg><span class="voice-record-label">Voice input</span>
      </button>
      <button type="button" class="voice-language-button" data-voice-action="language" aria-label="Recording language: ${VOICE_LANGUAGE_LABELS[language]}. Tap to change.">${VOICE_LANGUAGE_LABELS[language]}</button>
      <small class="voice-status" role="status" aria-live="polite" hidden></small>
      <div class="voice-review" hidden>
        <div class="voice-review-text"><p class="voice-transcript" aria-label="Transcription to review"></p><small class="voice-detected-language"></small></div>
        <div class="voice-review-actions" aria-label="Transcription actions">
          <button type="button" data-voice-action="append" aria-label="Append transcription">Append</button>
          <button type="button" data-voice-action="replace" aria-label="Replace text with transcription">Replace</button>
          <button type="button" data-voice-action="retry" aria-label="Transcribe recording again">Retry</button>
          <button type="button" class="voice-action-cancel" data-voice-action="cancel" aria-label="Cancel transcription">Cancel</button>
        </div>
      </div>
    </div>`;
  }
  function setVoiceStatus(widget, message, statusName) {
    const node = widget?.querySelector('.voice-status');
    if (!node) return;
    node.textContent = message || ''; node.dataset.state = statusName || ''; node.hidden = !message;
  }
  function voiceMimeType() {
    return ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus']
      .find(value => window.MediaRecorder?.isTypeSupported?.(value)) || '';
  }
  function releaseVoiceStream() {
    clearTimeout(voiceStopTimer); voiceStopTimer = null;
    voiceStream?.getTracks?.().forEach(track => track.stop());
    voiceStream = null; voiceRecorder = null;
  }
  function caseIdForVoiceField(fieldName) {
    return fieldName === 'complaint_description' ? '' : String(state.currentCase?.case_id || '');
  }
  function groupIdForVoiceField(fieldName) {
    return fieldName === 'complaint_description'
      ? state.groupId
      : String(state.currentCase?.group_id || state.groupId);
  }
  async function transcribeVoice(widget, blob, durationMs, retryAttemptId) {
    const data = new FormData();
    data.set('client_request_id', requestId('complaint-voice'));
    data.set('field_name', widget.dataset.voiceField);
    data.set('duration_ms', String(Math.max(1, Math.round(durationMs))));
    data.set('language_mode', widget.dataset.languageMode || 'auto');
    const caseId = caseIdForVoiceField(widget.dataset.voiceField);
    if (caseId) data.set('case_id', caseId);
    if (retryAttemptId) data.set('retry_attempt_id', retryAttemptId);
    if (blob) data.set('audio', blob, blob.type.includes('mp4') ? 'recording.m4a' : 'recording.webm');
    const recordButton = widget.querySelector('[data-voice-action="record"]');
    recordButton.disabled = true; setVoiceStatus(widget, 'Transcribing...', 'loading');
    try {
      const voiceGroupId = groupIdForVoiceField(widget.dataset.voiceField);
      const response = await form('voice-transcriptions/', data, voiceGroupId);
      activeVoiceAttempt = {
        id: response.transcription_id, fieldName: widget.dataset.voiceField,
        inputId: widget.dataset.inputId, transcript: response.text,
        retryAvailable: Boolean(response.retry_available), durationMs,
        groupId: voiceGroupId, caseId,
      };
      widget.querySelector('.voice-transcript').textContent = response.text;
      widget.querySelector('.voice-review').hidden = false;
      widget.querySelector('[data-voice-action="retry"]').disabled = !response.retry_available;
      const detected = detectedLanguageLabel(response.detected_language);
      widget.querySelector('.voice-detected-language').textContent = (response.requested_language || widget.dataset.languageMode) === 'auto'
        ? (detected ? `Auto detected: ${detected}` : 'Auto detection used')
        : `Recorded as ${widget.dataset.languageMode === 'sw' ? 'Kiswahili' : 'English'}`;
      setVoiceStatus(widget, '', 'review');
      utils.setCloseProtection?.('complaint-voice', true);
    } catch (error) {
      setVoiceStatus(widget, error.message || 'Transcription is unavailable. Your typed text is unchanged.', 'error');
      if (retryAttemptId && activeVoiceAttempt?.id === retryAttemptId) widget.querySelector('.voice-review').hidden = false;
      presentError(error, () => transcribeVoice(widget, null, durationMs, retryAttemptId || activeVoiceAttempt?.id || ''));
    } finally { recordButton.disabled = false; }
  }
  function stopVoiceRecording(widget, discard) {
    discardVoiceOnStop = Boolean(discard);
    if (voiceRecorder?.state === 'recording') voiceRecorder.stop();
    const button = widget?.querySelector('[data-voice-action="record"]');
    button?.setAttribute('aria-pressed', 'false');
    button?.setAttribute('aria-label', 'Start voice input');
    if (button?.querySelector('.voice-record-label')) button.querySelector('.voice-record-label').textContent = 'Voice input';
    widget?.classList.remove('recording');
  }
  async function startVoiceRecording(widget) {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      setVoiceStatus(widget, 'Voice recording is unavailable on this phone. Type the note instead.', 'error'); return;
    }
    if (activeVoiceAttempt) {
      const previousWidget = document.querySelector(`.voice-input[data-voice-field="${activeVoiceAttempt.fieldName}"]`);
      if (previousWidget) {
        previousWidget.querySelector('.voice-review').hidden = true;
        setVoiceStatus(previousWidget, 'Cancelled. Your typed text is unchanged.', '');
      }
      await cancelVoiceAttempt(activeVoiceAttempt);
    }
    try {
      voiceStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = voiceMimeType();
      voiceRecorder = mimeType ? new MediaRecorder(voiceStream, { mimeType }) : new MediaRecorder(voiceStream);
      voiceChunks = []; discardVoiceOnStop = false; voiceStartedAt = Date.now();
      voiceRecorder.addEventListener('dataavailable', event => { if (event.data?.size) voiceChunks.push(event.data); });
      voiceRecorder.addEventListener('stop', () => {
        const recorderMime = voiceRecorder?.mimeType || mimeType || 'audio/webm';
        const duration = Math.max(1, Date.now() - voiceStartedAt);
        const blob = new Blob(voiceChunks, { type: recorderMime });
        const discard = discardVoiceOnStop; discardVoiceOnStop = false; releaseVoiceStream();
        if (!discard) void transcribeVoice(widget, blob, duration);
      }, { once: true });
      voiceRecorder.start();
      const button = widget.querySelector('[data-voice-action="record"]');
      button.setAttribute('aria-pressed', 'true'); button.setAttribute('aria-label', 'Stop recording');
      button.querySelector('.voice-record-label').textContent = 'Stop';
      widget.classList.add('recording'); setVoiceStatus(widget, 'Recording... tap Stop when finished.', 'recording');
      utils.setCloseProtection?.('complaint-voice', true);
      voiceStopTimer = setTimeout(() => stopVoiceRecording(widget), Number(state.voiceInput.max_seconds || 30) * 1000);
    } catch (_) {
      releaseVoiceStream();
      setVoiceStatus(widget, 'Microphone unavailable. Allow Telegram microphone access, then reopen the Mini App.', 'error');
    }
  }
  async function cancelVoiceAttempt(attempt) {
    if (!attempt?.id) return;
    if (activeVoiceAttempt?.id === attempt.id) activeVoiceAttempt = null;
    const data = new FormData(); data.set('client_request_id', requestId('complaint-voice-cancel'));
    try { await form(`voice-transcriptions/${encodeURIComponent(attempt.id)}/cancel/`, data, attempt.groupId || state.groupId); }
    catch (_) { /* Expiry cleanup remains authoritative. */ }
  }
  function resetVoiceField(fieldName, cancel = true) {
    const widget = document.querySelector(`.voice-input[data-voice-field="${fieldName}"]`);
    if (activeVoiceAttempt?.fieldName === fieldName) {
      const attempt = activeVoiceAttempt; activeVoiceAttempt = null;
      if (cancel) void cancelVoiceAttempt(attempt);
    }
    if (acceptedVoiceAttempts[fieldName]) {
      const attempt = acceptedVoiceAttempts[fieldName]; delete acceptedVoiceAttempts[fieldName];
      if (cancel) void cancelVoiceAttempt(attempt);
    }
    if (widget) { widget.querySelector('.voice-review').hidden = true; setVoiceStatus(widget, '', ''); }
  }
  function wireVoiceWidget(slot) {
    const fieldName = slot.dataset.voiceField;
    if (!state.voiceInput.enabled || !state.voiceInput.fields.includes(fieldName)) return;
    slot.innerHTML = voiceWidgetMarkup(fieldName, slot.dataset.inputId); slot.hidden = false;
    const widget = slot.firstElementChild;
    widget.addEventListener('click', async event => {
      const action = event.target.closest('[data-voice-action]')?.dataset.voiceAction;
      if (!action) return;
      if (action === 'language') {
        const current = widget.dataset.languageMode || 'auto';
        const next = VOICE_LANGUAGE_ORDER[(VOICE_LANGUAGE_ORDER.indexOf(current) + 1) % VOICE_LANGUAGE_ORDER.length];
        widget.dataset.languageMode = next; event.target.textContent = VOICE_LANGUAGE_LABELS[next];
        event.target.setAttribute('aria-label', `Recording language: ${VOICE_LANGUAGE_LABELS[next]}. Tap to change.`);
        try { localStorage.setItem(VOICE_LANGUAGE_KEY, next); } catch (_) {}
        return;
      }
      if (action === 'record') {
        if (voiceRecorder?.state === 'recording') stopVoiceRecording(widget); else await startVoiceRecording(widget);
        return;
      }
      const attempt = activeVoiceAttempt;
      if (!attempt || attempt.fieldName !== fieldName) return;
      if (action === 'retry') { widget.querySelector('.voice-review').hidden = true; await transcribeVoice(widget, null, attempt.durationMs, attempt.id); return; }
      if (action === 'cancel') {
        widget.querySelector('.voice-review').hidden = true;
        setVoiceStatus(widget, 'Cancelled. Your typed text is unchanged.', '');
        await cancelVoiceAttempt(attempt); utils.setCloseProtection?.('complaint-voice', false); return;
      }
      const input = $(attempt.inputId); if (!input) return;
      input.value = action === 'append' && input.value.trim() ? `${input.value.trim()} ${attempt.transcript}` : attempt.transcript;
      const previous = acceptedVoiceAttempts[fieldName];
      if (previous && previous.id !== attempt.id) void cancelVoiceAttempt(previous);
      acceptedVoiceAttempts[fieldName] = attempt; activeVoiceAttempt = null;
      widget.querySelector('.voice-review').hidden = true;
      setVoiceStatus(widget, 'Inserted. You can edit the text before saving.', 'accepted');
      input.dispatchEvent(new Event('input', { bubbles: true })); input.focus();
    });
  }
  function initializeVoiceInput() {
    document.querySelectorAll('.voice-input-slot').forEach(wireVoiceWidget);
  }
  function discardPendingVoice() {
    const recordingWidget = document.querySelector('.voice-input.recording');
    if (recordingWidget) stopVoiceRecording(recordingWidget, true);
    if (activeVoiceAttempt) void cancelVoiceAttempt(activeVoiceAttempt);
    Object.keys(acceptedVoiceAttempts).forEach(fieldName => resetVoiceField(fieldName));
    utils.setCloseProtection?.('complaint-voice', false);
  }
  function metaItem(icon, value) {
    const node = document.createElement('span');
    node.append(iconNode(icon), textNode('span', value));
    return node;
  }
  function loadingNode(label) {
    const node = document.createElement('span'); node.className = 'inline-loading'; node.setAttribute('role', 'status');
    const spinner = document.createElement('span'); spinner.className = 'spinner-inline'; spinner.setAttribute('aria-hidden', 'true');
    node.append(spinner, textNode('span', label || 'Loading...')); return node;
  }
  function setActionLoading(button, loading, label) {
    if (utils.setButtonLoading) utils.setButtonLoading(button, loading, label);
    else if (button) button.disabled = !!loading;
  }
  function bindCollapsingHeader() {
    const header = $('appHeader');
    if (!header) return;
    let previousY = Math.max(0, window.scrollY || 0); let scheduled = false;
    const update = () => {
      scheduled = false;
      const currentY = Math.max(0, window.scrollY || 0); const delta = currentY - previousY;
      if (currentY <= 12 || delta < -4 || header.contains(document.activeElement)) header.classList.remove('header-hidden');
      else if (currentY > header.offsetHeight && delta > 4) header.classList.add('header-hidden');
      previousY = currentY;
    };
    window.addEventListener('scroll', () => {
      if (!scheduled) { scheduled = true; window.requestAnimationFrame(update); }
    }, { passive: true });
    header.addEventListener('focusin', () => header.classList.remove('header-hidden'));
  }
  function statusStack(item) {
    const stack = document.createElement('div');
    stack.className = 'status-stack';
    const resolved = item.status === 'CLOSED' || item.status === 'Closed';
    const statusKey = displayStatus(item.status).toLowerCase();
    const status = textNode('span', displayStatus(item.status), `status-pill ${statusKey}`);
    status.prepend(iconNode(resolved ? 'circle-check' : 'clock'));
    stack.appendChild(status);
    if (item.hb_comment_count > 0) {
      const badge = textNode('span', String(item.hb_comment_count), 'hb-comment-count');
      badge.setAttribute('aria-label', `${item.hb_comment_count} HB comments`);
      badge.prepend(iconNode('message-circle'));
      stack.appendChild(badge);
    }
    if (item.needs_details) stack.appendChild(textNode('span', 'Needs More Information', 'needs-details-pill'));
    return stack;
  }
  function displayStatus(status) {
    return ({ Pending: 'OPEN', Open: 'OPEN', Reopened: 'REOPENED', Closed: 'CLOSED' })[status] || status || 'OPEN';
  }

  function setView(name) {
    if (name !== 'globalView' && state.reportFilterSheetOpen) closeComplaintReportFilters({ restoreFocus: false });
    if (!$('cameraOverlay').hidden) closeCamera();
    if (!$('mediaViewerOverlay').hidden) closeMediaViewer();
    ['queueView', 'globalView', 'createView', 'detailView'].forEach(id => { $(id).hidden = id !== name; });
    $('loadingState').hidden = true;
    const queueWorkspace = name === 'queueView';
    $('workspaceTabs').hidden = !queueWorkspace;
    if (queueWorkspace) state.workspace = 'queue';
    $('queueWorkspaceBtn').classList.toggle('active', queueWorkspace);
    $('globalWorkspaceBtn').classList.remove('active');
    telegram?.BackButton?.[queueWorkspace ? 'hide' : 'show']();
    window.scrollTo({ top: 0, behavior: 'instant' });
  }

  function selectOptions(select, values, placeholder) {
    select.replaceChildren(textNode('option', placeholder));
    select.firstElementChild.value = '';
    (values || []).forEach(item => {
      const option = textNode('option', typeof item === 'string' ? item : item.label);
      option.value = typeof item === 'string' ? item : item.value;
      select.appendChild(option);
    });
  }
  function locationSelectOptions(select, values, placeholder) {
    select.replaceChildren(textNode('option', placeholder)); select.firstElementChild.value = '';
    (values || []).forEach(item => {
      const option = textNode('option', item.name || item.label || item.code);
      option.value = item.code || item.value || item.name;
      select.appendChild(option);
    });
  }
  async function refreshLocationOptions() {
    const formNode = $('createCaseForm');
    const branch = formNode.elements.branch_region.value;
    const county = formNode.elements.county.value;
    const sequence = ++state.locationOptionsSequence;
    state.locationOptionsLoading = true; $('createSaveBtn').disabled = true;
    try {
      const response = await getJson('location-options/', { branch, county });
      if (sequence !== state.locationOptionsSequence) return;
      state.locationOptions = response.data || {};
      const previousCounty = county;
      locationSelectOptions(formNode.elements.county, state.locationOptions.counties, 'Select county');
      const retainedCounty = [...formNode.elements.county.options].some(option => option.value === previousCounty);
      if (retainedCounty) formNode.elements.county.value = previousCounty;
      locationSelectOptions(
        formNode.elements.sub_county,
        retainedCounty ? state.locationOptions.sub_counties : [],
        retainedCounty ? 'Select constituency' : 'Select county first',
      );
      formNode.elements.sub_county.disabled = !retainedCounty;
    } finally {
      if (sequence === state.locationOptionsSequence) {
        state.locationOptionsLoading = false; $('createSaveBtn').disabled = false;
      }
    }
  }
  function updateCounts(counts) {
    $('pendingCount').textContent = counts.pending || 0;
    $('resolvedCount').textContent = counts.resolved || 0;
    $('totalCount').textContent = counts.total || 0;
  }

  async function bootstrap() {
    try {
      const response = await json('bootstrap/');
      const data = response.data;
      state.capabilities = new Set(data.actor.capabilities || []);
      document.querySelectorAll('[data-required-capability]').forEach(node => {
        node.hidden = !can(node.dataset.requiredCapability);
      });
      state.evidenceLimits = Object.assign(state.evidenceLimits, data.evidence_limits || {});
      state.voiceInput = Object.assign(state.voiceInput, data.voice_input || {});
      const actorRoles = Array.isArray(data.actor.roles) && data.actor.roles.length
        ? data.actor.roles : [data.actor.role].filter(Boolean);
      $('actorLine').textContent = [data.actor.name, ...actorRoles].join(' · ');
      if ($('complaintSettingsBtn')) $('complaintSettingsBtn').hidden = !(data.report_email_allowed ?? actorRoles.some(role => ['IT', 'SUPERUSER'].includes(String(role).toUpperCase())));
      updateCounts(data.counts || {});
      $('newCaseBtn').hidden = !can('complaint.case.create');
      $('workspaceTabs').classList.toggle('single-tab', !can('complaint.reports.view'));
      $('exportAllBtn').hidden = !(can('complaint.reports.view') && can('complaint.case.export'));
      $('exportResultsBtn').hidden = $('exportAllBtn').hidden;
      selectOptions($('createCaseForm').elements.branch_region, data.branches, 'Select branch');
      state.locationOptions = data.location_options || state.locationOptions;
      locationSelectOptions($('createCaseForm').elements.county, state.locationOptions.counties, 'Select county');
      selectOptions($('createCaseForm').elements.complaint_category, data.categories, 'Select complaint type');
      selectOptions($('completeDetailsForm').elements.complaint_category, data.categories, 'Select complaint type');
      state.categoryDescriptions = new Map((data.category_catalogue || []).map(item => [item.label, item.description]));
      initializeVoiceInput();
      updateEvidenceHints();
      setView('queueView');
      await loadCases();
    } catch (error) {
      $('loadingState').textContent = error.message || 'Complaints could not be opened.';
      presentError(error, bootstrap);
    }
  }

  async function loadCases() {
    $('caseList').replaceChildren(loadingNode('Loading complaints...'));
    try {
      const response = await json('cases/', { status: state.status, query: state.query, page: state.page });
      const pagination = response.pagination || { page: 1, pages: 1, total: response.cases.length };
      state.page = pagination.page; state.pages = pagination.pages;
      $('queueResultCount').textContent = `${pagination.total} complaint${pagination.total === 1 ? '' : 's'}`;
      renderCases(response.cases || [], response.start_index || 0);
      $('queuePagination').hidden = pagination.pages <= 1;
      $('queuePageLabel').textContent = `Page ${pagination.page} of ${pagination.pages}`;
      $('queuePreviousBtn').disabled = pagination.page <= 1;
      $('queueNextBtn').disabled = pagination.page >= pagination.pages;
    } catch (error) {
      $('caseList').replaceChildren(textNode('p', 'Complaints could not be loaded.', 'empty'));
      presentError(error, loadCases);
    }
  }

  function renderCases(cases, start) {
    const list = $('caseList'); list.replaceChildren();
    if (!cases.length) { list.appendChild(textNode('p', 'No complaints match this view.', 'empty')); return; }
    cases.forEach((item, index) => {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'case-row'; button.dataset.caseId = item.case_id;
      const body = document.createElement('div');
      const meta = document.createElement('div'); meta.className = 'case-meta-line';
      meta.append(
        metaItem(item.customer_phone ? 'phone' : 'file', item.customer_phone || item.customer_id || 'Customer details required'),
        metaItem('tag', item.category || 'Other Complaint'),
        metaItem('map-pin', item.branch || 'Branch not provided'),
      );
      const resolved = item.status === 'CLOSED' || item.status === 'Closed';
      const age = document.createElement('p');
      age.className = `case-age ${resolved ? 'resolved' : (item.needs_details ? 'attention' : 'pending')}`;
      age.append(iconNode(resolved ? 'circle-check' : 'clock'), textNode('span', item.age_label || ''));
      body.append(
        textNode('p', `#${start + index} · ${item.reference_number || item.case_id}`, 'case-reference'),
        textNode('h2', item.customer_name || 'Unnamed customer'),
        meta,
        age,
      );
      button.append(body, statusStack(item));
      button.addEventListener('click', () => openCase(item.case_id));
      list.appendChild(button);
    });
  }

  async function openCase(caseId) {
    const source = document.querySelector(`[data-case-id="${CSS.escape(caseId)}"]`);
    setActionLoading(source, true, 'Opening');
    try {
      const response = await json(`cases/${encodeURIComponent(caseId)}/`);
      response.case.group_id = state.groupId; response.case.global_read = false;
      state.returnWorkspace = 'queue'; renderDetail(response.case); setView('detailView');
    } catch (error) { presentError(error, () => openCase(caseId)); }
    finally { setActionLoading(source, false); }
  }
  async function openGlobalCase(caseUuid) {
    try {
      const response = await json(`global/cases/${encodeURIComponent(caseUuid)}/`);
      response.case.global_read = true; state.returnWorkspace = 'global';
      renderDetail(response.case); setView('detailView');
    } catch (error) { presentError(error, () => openGlobalCase(caseUuid)); }
  }
  function syncLabel(value) {
    return ({ success: 'Synced', pending: 'Pending', failed: 'Failed', not_required: 'Not enabled', suspended: 'Not enabled' })[value] || value || 'Not recorded';
  }

  function selectHbAction(action) {
    if (voiceRecorder?.state === 'recording') { notify('Finish your recording before switching actions.'); return; }
    state.hbAction = action;
    const unavailable = $('hbActionTabs').hidden;
    $('commentForm').hidden = unavailable || $('commentTab').hidden || action !== 'comment';
    $('resolveForm').hidden = unavailable || $('resolveTab').hidden || action !== 'resolve';
    $('commentTab').setAttribute('aria-selected', String(action === 'comment'));
    $('resolveTab').setAttribute('aria-selected', String(action === 'resolve'));
  }

  function renderDetail(item, preserveDraft) {
    if (!preserveDraft && state.currentCase?.case_id !== item.case_id) {
      resetVoiceField('complaint_resolution_note');
      resetVoiceField('complaint_resolution_comment');
      resetVoiceField('complaint_reopen_reason');
    }
    state.currentCase = item;
    $('detailCaseId').textContent = item.reference_number || item.case_id;
    $('detailName').textContent = item.customer_name || 'Unnamed customer';
    $('detailGroup').textContent = item.group_label || '';
    $('detailStatus').textContent = displayStatus(item.status);
    $('detailStatus').className = `status-pill ${displayStatus(item.status).toLowerCase()}`;
    $('detailNeedsDetails').hidden = !item.needs_details;
    const ids = $('detailIdentifiers'); ids.replaceChildren();
    [item.customer_phone, item.customer_id].filter(Boolean).forEach(value => ids.appendChild(textNode('span', value)));
    $('detailDescription').textContent = item.description || 'No description recorded.';
    const meta = $('detailMeta'); meta.replaceChildren();
    [
      item.category ? `Complaint Type: ${item.category}` : '',
      item.branch ? `Branch: ${item.branch}` : 'Branch not provided',
      item.reported_at ? `Reported: ${item.reported_at}` : '',
    ].filter(Boolean).forEach(value => meta.appendChild(textNode('span', value)));
    const source = item.source_attribution || {};
    $('detailSource').textContent = source.type === 'officer' ? ''
      : (source.type === 'batch' ? `${source.label} · Uploaded by ${source.actor} · ${source.created_at}` : (source.label || ''));
    $('detailSource').hidden = !$('detailSource').textContent;
    $('detailSync').textContent = `Sheet Sync: ${syncLabel(item.sync_status)}`;
    renderEvidence(item.evidence || []); renderActivity(item.updates || []);
    $('evidencePanel').hidden = !!item.global_read; $('activityPanel').hidden = false;
    const actions = item.global_read ? (item.actions || {}) : {
      close: can('complaint.case.close'), reopen: can('complaint.case.reopen'),
      comment: can('complaint.case.comment'),
      complete_details: can('complaint.case.details.complete'),
    };
    $('completeDetailsForm').hidden = !item.needs_details || !actions.complete_details;
    $('hbActionTabs').hidden = ['Closed', 'CLOSED', 'Resolved'].includes(item.stored_status || item.status) || !(actions.comment || actions.close);
    $('commentTab').hidden = !actions.comment; $('resolveTab').hidden = !actions.close;
    if (!preserveDraft) state.hbAction = actions.comment ? 'comment' : 'resolve';
    selectHbAction(state.hbAction || 'comment');
    $('reopenForm').hidden = item.status !== 'CLOSED' || !actions.reopen;
    $('detailBackLabel').textContent = state.returnWorkspace === 'global' ? 'Overview' : 'Complaints';
    if (!preserveDraft) {
      $('completeDetailsForm').reset(); $('resolveForm').reset(); $('commentForm').reset(); $('reopenForm').reset();
      clearEvidence('resolve'); $('conflictPanel').hidden = true;
      const complete = $('completeDetailsForm').elements;
      complete.customer_phone.value = item.customer_phone || '';
      complete.customer_phone.readOnly = !!item.customer_phone;
      complete.customer_id.value = item.customer_id || '';
      complete.customer_id.readOnly = !!item.customer_id && /^\d+$/.test(item.customer_id);
      complete.complaint_category.value = item.category || '';
    }
  }

  function displayHistoryNote(note) {
    const value = String(note || '');
    const friendlyLegacyNotes = {
      'the case is now fully resolved': 'Complaint marked as resolved',
      'the case was resolved': 'Complaint resolved',
      'the customer is still complaining': 'Customer reported the issue again',
    };
    return friendlyLegacyNotes[value.trim().toLowerCase()] || value;
  }
  function renderEvidence(items) {
    const node = $('evidenceList'); node.replaceChildren();
    state.persistedEvidence = (items || []).filter(item => item.preview_url);
    if (!items.length) { node.appendChild(textNode('p', 'No attachments available.', 'muted')); return; }
    items.forEach(item => {
      const row = document.createElement('div'); row.className = 'item evidence-item'; row.appendChild(textNode('strong', item.name));
      if (item.preview_url) {
        const button = buttonWithIcon('View in app', 'eye', 'media-link');
        button.addEventListener('click', () => openPersistedEvidence(item, button));
        row.appendChild(button);
      } else if (item.status === 'success') {
        row.appendChild(textNode('small', 'In-app preview unavailable for this older file.', 'muted'));
      }
      node.appendChild(row);
    });
  }
  function mediaHeaders(accessRequestId) {
    return { 'X-Telegram-Init-Data': state.initData, 'X-Request-ID': accessRequestId || requestId('complaint-evidence') };
  }
  function mediaPointDistance(points) {
    return Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y);
  }
  function mediaPointMidpoint(points) {
    return { x: (points[0].x + points[1].x) / 2, y: (points[0].y + points[1].y) / 2 };
  }
  function resetMediaViewerGestures() {
    state.mediaViewerPointers.clear(); state.mediaViewerSwipe = null;
    state.mediaViewerPinch = null; state.mediaViewerZoom = 100;
    const content = $('mediaViewerContent'); const image = content.querySelector('.media-viewer-image');
    content.classList.remove('image-gestures', 'zoomed'); delete content.dataset.zoom;
    content.removeAttribute('aria-label'); content.scrollLeft = 0; content.scrollTop = 0;
    if (image) image.style.width = '';
  }
  function activateMediaViewerGestures() {
    resetMediaViewerGestures();
    const content = $('mediaViewerContent'); const image = content.querySelector('.media-viewer-image');
    content.setAttribute('aria-label', image
      ? 'File preview. Swipe left or right to browse files. Pinch to zoom this image.'
      : 'File preview. Swipe left or right to browse files.');
    if (image) { content.classList.add('image-gestures'); content.dataset.zoom = '100'; image.style.width = '100%'; }
  }
  function setMediaViewerZoom(value, focalPoint) {
    const content = $('mediaViewerContent'); const image = content.querySelector('.media-viewer-image');
    if (!image) return;
    const previousZoom = state.mediaViewerZoom;
    const nextZoom = Math.max(50, Math.min(300, Math.round(value)));
    if (nextZoom === previousZoom) return;
    const bounds = content.getBoundingClientRect();
    const localX = (focalPoint?.x ?? (bounds.left + bounds.width / 2)) - bounds.left;
    const localY = (focalPoint?.y ?? (bounds.top + bounds.height / 2)) - bounds.top;
    const ratio = nextZoom / previousZoom;
    state.mediaViewerZoom = nextZoom; content.dataset.zoom = String(nextZoom);
    content.classList.toggle('zoomed', nextZoom !== 100); image.style.width = `${nextZoom}%`;
    content.scrollLeft = (content.scrollLeft + localX) * ratio - localX;
    content.scrollTop = (content.scrollTop + localY) * ratio - localY;
  }
  function mediaViewerPointerDown(event) {
    if (event.pointerType === 'mouse' || $('mediaViewerOverlay').hidden) return;
    state.mediaViewerPointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (state.mediaViewerPointers.size === 1) {
      state.mediaViewerSwipe = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, startedAt: Date.now(), cancelled: false };
    }
    if (state.mediaViewerPointers.size === 2 && $('mediaViewerContent').querySelector('.media-viewer-image')) {
      if (state.mediaViewerSwipe) state.mediaViewerSwipe.cancelled = true;
      const points = Array.from(state.mediaViewerPointers.values());
      state.mediaViewerPinch = { distance: mediaPointDistance(points), zoom: state.mediaViewerZoom };
    }
    try { event.currentTarget.setPointerCapture(event.pointerId); } catch (_) { /* Synthetic and older WebView events may not capture. */ }
    event.preventDefault();
  }
  function mediaViewerPointerMove(event) {
    const previous = state.mediaViewerPointers.get(event.pointerId);
    if (!previous) return;
    state.mediaViewerPointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (state.mediaViewerPointers.size === 2 && state.mediaViewerPinch) {
      const points = Array.from(state.mediaViewerPointers.values());
      const distance = mediaPointDistance(points);
      if (state.mediaViewerPinch.distance) {
        setMediaViewerZoom(state.mediaViewerPinch.zoom * (distance / state.mediaViewerPinch.distance), mediaPointMidpoint(points));
      }
    } else if (state.mediaViewerPointers.size === 1) {
      event.currentTarget.scrollLeft -= event.clientX - previous.x;
      event.currentTarget.scrollTop -= event.clientY - previous.y;
    }
    event.preventDefault();
  }
  function finishMediaViewerPointer(event, cancelled) {
    if (!state.mediaViewerPointers.has(event.pointerId)) return;
    const swipe = state.mediaViewerSwipe;
    if (!cancelled && event.type === 'pointerup' && swipe && swipe.pointerId === event.pointerId && !swipe.cancelled && state.mediaViewerPointers.size === 1) {
      const deltaX = event.clientX - swipe.startX; const deltaY = event.clientY - swipe.startY;
      const threshold = Math.max(56, event.currentTarget.clientWidth * .16);
      const deliberateHorizontalSwipe = Math.abs(deltaX) >= threshold
        && Math.abs(deltaX) > Math.abs(deltaY) * 1.35
        && Date.now() - swipe.startedAt <= 900;
      if (deliberateHorizontalSwipe && navigateMediaViewer(deltaX < 0 ? 1 : -1)) utils.haptic?.('light');
    }
    state.mediaViewerPointers.delete(event.pointerId); state.mediaViewerPinch = null;
    if (!state.mediaViewerPointers.size || swipe?.pointerId === event.pointerId) state.mediaViewerSwipe = null;
  }
  function closeMediaViewer() {
    state.mediaViewerRequestSequence += 1;
    resetMediaViewerGestures();
    $('mediaViewerOverlay').hidden = true; $('mediaViewerContent').replaceChildren();
    $('mediaViewerActions').hidden = true;
    window.SecureMediaViewer?.revoke(state.mediaViewerObjectUrl); state.mediaViewerObjectUrl = '';
    state.mediaViewerMode = ''; state.mediaViewerTarget = ''; state.mediaViewerItemId = '';
    const restore = state.mediaViewerRestoreFocus; state.mediaViewerRestoreFocus = null; restore?.focus?.();
  }
  function showMediaViewer(restoreFocus) {
    resetMediaViewerGestures();
    if (!$('mediaViewerOverlay').hidden) {
      window.SecureMediaViewer?.revoke(state.mediaViewerObjectUrl); state.mediaViewerObjectUrl = '';
      $('mediaViewerContent').replaceChildren();
    } else {
      state.mediaViewerRestoreFocus = restoreFocus || null;
    }
    $('mediaViewerTitle').textContent = 'File Preview';
    $('mediaViewerContent').replaceChildren(loadingNode('Loading secure file...')); $('mediaViewerOverlay').hidden = false;
  }
  function mediaViewerEntries() {
    if (state.mediaViewerMode === 'selected') return state.evidence[state.mediaViewerTarget] || [];
    if (state.mediaViewerMode === 'persisted') return state.persistedEvidence || [];
    return [];
  }
  function updateMediaViewerControls(item) {
    const entries = mediaViewerEntries();
    const index = entries.findIndex(entry => state.mediaViewerMode === 'selected'
      ? entry.id === state.mediaViewerItemId
      : entry.preview_url === state.mediaViewerItemId);
    $('mediaViewerSub').textContent = index >= 0
      ? `${index + 1} of ${entries.length} · ${item?.file?.name || item?.name || 'Attachment'}`
      : (item?.file?.name || item?.name || 'Attachment');
    $('mediaViewerActions').hidden = entries.length === 0;
    $('mediaViewerPrevious').disabled = index <= 0;
    $('mediaViewerNext').disabled = index < 0 || index >= entries.length - 1;
    const selected = state.mediaViewerMode === 'selected';
    $('mediaViewerActions').dataset.mode = selected
      ? (String(item?.file?.type || '').startsWith('image/') ? 'selected-image' : 'selected-file')
      : 'persisted';
    $('mediaViewerDelete').hidden = !selected;
    $('mediaViewerRetake').hidden = !selected || !String(item?.file?.type || '').startsWith('image/');
  }
  async function openPersistedEvidence(item, button) {
    state.mediaViewerMode = 'persisted'; state.mediaViewerTarget = '';
    state.mediaViewerItemId = item.preview_url; showMediaViewer(button);
    updateMediaViewerControls(item);
    const requestSequence = ++state.mediaViewerRequestSequence;
    try {
      const viewer = window.SecureMediaViewer;
      if (!viewer) throw new Error('The secure evidence viewer is unavailable. Refresh and retry.');
      const groupId = state.currentCase.group_id || state.groupId; const accessRequestId = requestId('complaint-evidence');
      const blob = await viewer.fetchAuthorizedBlob(item.preview_url, {
        method: 'POST',
        headers: { ...mediaHeaders(accessRequestId), 'Content-Type': 'application/json', 'Idempotency-Key': accessRequestId },
        body: JSON.stringify({ group_id: groupId, client_request_id: accessRequestId }),
      });
      if (requestSequence !== state.mediaViewerRequestSequence || state.mediaViewerItemId !== item.preview_url) return;
      state.mediaViewerObjectUrl = viewer.renderBlob($('mediaViewerContent'), blob, {
        mimeType: item.mime_type || '', name: item.name || 'Complaint evidence',
      });
      activateMediaViewerGestures();
    } catch (error) {
      if (requestSequence !== state.mediaViewerRequestSequence) return;
      $('mediaViewerContent').replaceChildren(textNode('p', `${error.message || 'The evidence could not be opened.'} Close this view and retry.`, 'media-viewer-error'));
    }
  }
  function renderActivity(items) {
    const node = $('activityList'); node.replaceChildren();
    if (!items.length) { node.appendChild(textNode('p', 'No complaint history available.', 'muted')); return; }
    const grouped = [], groups = new Map();
    items.forEach(item => {
      // Only records explicitly tied to the same operation may share an entry.
      // Separate comments/actions are never merged just because their times match.
      const key = item.action_group && item.action !== 'commented'
        ? JSON.stringify([item.action_group, item.action, item.updated_by, item.actor_affiliation]) : '';
      const existing = key && groups.get(key);
      if (existing) {
        existing.notes = [...new Set([...existing.notes, item.note].filter(Boolean))];
        existing.changes.push(...(item.display_changes || item.changes || []));
      } else {
        const entry = {...item, notes:item.note ? [item.note] : [], changes:[...(item.display_changes || item.changes || [])]};
        grouped.push(entry);
        if (key) groups.set(key, entry);
      }
    });
    grouped.forEach(item => {
      const row = document.createElement('div'); row.className = 'item history-item';
      const actions = {created:'Complaint recorded by', commented:'Comment by', resolved:'Resolved by', reopened:'Reopened by', details_completed:'Details completed by', updated:'Updated by'};
      const action = actions[item.action] || (item.status === 'Closed' ? 'Resolved by' : item.status === 'Reopened' ? 'Reopened by' : !item.old_status && item.status === 'Open' ? 'Complaint recorded by' : 'Updated by');
      const creation = action === 'Complaint recorded by';
      const content = document.createElement('div');
      const affiliation = ['JBL', 'HB'].includes(item.actor_affiliation) ? item.actor_affiliation : 'Role unknown';
      const heading = document.createElement('div'); heading.className = 'history-heading';
      const affiliationClass = affiliation === 'Role unknown' ? 'unknown' : affiliation.toLowerCase();
      heading.append(textNode('strong', `${action} ${item.updated_by || 'Unknown actor'}`), textNode('span', affiliation, `history-affiliation history-affiliation-${affiliationClass}`));
      content.append(heading);
      const noteText = item.notes.filter(note => !/^(complaint recorded|complaint (marked as )?resolved|the case (is now fully|was) resolved)[.!]?$/i.test(String(note).trim())).join('\n');
      if (noteText) {
        const note = document.createElement('div');
        if (window.MiniAppActivityChanges) note.innerHTML = window.MiniAppActivityChanges.textHtml(displayHistoryNote(noteText));
        else note.textContent = displayHistoryNote(noteText);
        content.append(note);
      }
      content.append(textNode('small', item.created_at || '', 'muted'));
      const changes = creation ? [] : item.changes.filter(change =>
        !['priority', 'status'].includes(change.field) && !(item.notes.length && change.field === 'resolution_details'));
      window.MiniAppActivityChanges?.append(content, changes, {title: action, detail: noteText});
      row.append(iconNode(item.status === 'Closed' ? 'circle-check' : 'history', 'item-icon'), content);
      node.appendChild(row);
    });
  }

  function showConflict(error) {
    const current = error.payload?.current_case;
    if (!current) { presentError(error); return; }
    const draft = $('commentForm').elements.comment_text.value || $('resolveForm').elements.resolution_text.value || $('reopenForm').elements.reason.value || (current.needs_details ? 'Your entered complaint details remain in the form.' : '');
    current.group_id = state.currentCase.group_id; current.global_read = state.currentCase.global_read;
    state.currentCase = current; $('conflictMessage').textContent = error.message;
    const resolution = current.resolution_comments?.[0] || current.latest_resolution;
    $('conflictWinningNote').textContent = resolution ? `${resolution.note}\n— ${resolution.updated_by}, ${resolution.created_at}` : 'Review the latest complaint before trying again.';
    $('conflictDraft').textContent = draft || 'No draft text was entered.';
    $('copyConflictDraftBtn').disabled = !draft || draft.startsWith('Your entered complaint details');
    renderDetail(current, true); $('conflictPanel').hidden = false;
    $('conflictPanel').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  async function copyConflictDraft() {
    const draft = $('conflictDraft').textContent;
    if (!draft || $('copyConflictDraftBtn').disabled) return;
    try { await navigator.clipboard.writeText(draft); notify('Your draft was copied.'); }
    catch (_) { notify('Copy was unavailable. Select and copy the retained draft above.', true); }
  }

  function appendEvidence(data, target) {
    state.evidence[target].forEach(item => data.append('evidence', item.file, item.file.name));
  }
  async function submitTransition(event, action) {
    event.preventDefault(); if (!state.currentCase || state.submitting) return;
    const formNode = event.currentTarget; const data = new FormData(formNode);
    if (!validateRequiredForm(formNode)) return;
    const targetGroup = state.currentCase.group_id || state.groupId;
    data.set('expected_revision', state.currentCase.revision);
    const writeKey = `transition:${action}:${state.currentCase.case_id}`;
    data.set('client_request_id', pendingWriteId(writeKey, 'complaint-transition'));
    const voiceField = action === 'comments' ? 'complaint_resolution_comment' : (action === 'resolve' ? 'complaint_resolution_note' : 'complaint_reopen_reason');
    if (acceptedVoiceAttempts[voiceField]?.id) data.set('voice_transcription_id', acceptedVoiceAttempts[voiceField].id);
    if (action === 'resolve') appendEvidence(data, 'resolve');
    const button = formNode.querySelector('button[type="submit"]');
    state.submitting = true; setActionLoading(button, true, action === 'comments' ? 'Saving' : (action === 'resolve' ? 'Resolving' : 'Reopening')); utils.setCloseProtection?.('complaint-operation', true);
    try {
      const response = await form(`cases/${encodeURIComponent(state.currentCase.case_id)}/${action}/`, data, targetGroup);
      settleWrite(writeKey);
      resetVoiceField(voiceField, false);
      response.case.group_id = targetGroup; notify(response.message); if (action !== 'comments') clearEvidence('resolve');
      utils.setCloseProtection?.('complaint-transition-draft', false); await refreshCounts();
      if (action === 'comments') {
        response.case.global_read = state.currentCase.global_read;
        response.case.actions = state.currentCase.actions;
        renderDetail(response.case, true);
        if (state.returnWorkspace === 'global') await refreshGlobal();
      } else if (state.returnWorkspace === 'global') { await refreshGlobal(); await openGlobalCase(response.case.id); }
      else { response.case.global_read = false; renderDetail(response.case); }
      if (action === 'comments') {
        $('commentForm').reset();
        utils.setCloseProtection?.('complaint-transition-draft', !!$('resolveForm').elements.resolution_text.value || state.evidence.resolve.length > 0);
      }
    } catch (error) { settleWrite(writeKey, error); if (error.status === 409) showConflict(error); else presentError(error, () => formNode.requestSubmit()); }
    finally { state.submitting = false; setActionLoading(button, false); utils.setCloseProtection?.('complaint-operation', false); }
  }

  async function submitCompleteDetails(event) {
    event.preventDefault(); if (!state.currentCase || state.submitting) return;
    const formNode = event.currentTarget; const data = new FormData(formNode);
    const idError = validateCustomerId(formNode.elements.customer_id);
    if (idError) return notify(idError, true);
    if (!validateContactPair(formNode) || !validateRequiredForm(formNode)) return;
    const targetGroup = state.currentCase.group_id || state.groupId;
    data.set('expected_revision', state.currentCase.revision);
    const writeKey = `details:${state.currentCase.case_id}`;
    data.set('client_request_id', pendingWriteId(writeKey, 'complaint-details'));
    const button = formNode.querySelector('button[type="submit"]');
    state.submitting = true; setActionLoading(button, true, 'Saving details'); utils.setCloseProtection?.('complaint-operation', true);
    try {
      const response = await form(`cases/${encodeURIComponent(state.currentCase.case_id)}/complete-details/`, data, targetGroup);
      settleWrite(writeKey);
      response.case.group_id = targetGroup; notify(response.message);
      utils.setCloseProtection?.('complaint-transition-draft', false); await refreshCounts();
      if (state.returnWorkspace === 'global') { await refreshGlobal(); await openGlobalCase(response.case.id); }
      else { response.case.global_read = false; renderDetail(response.case); }
    } catch (error) { settleWrite(writeKey, error); if (error.status === 409) showConflict(error); else presentError(error, () => formNode.requestSubmit()); }
    finally { state.submitting = false; setActionLoading(button, false); utils.setCloseProtection?.('complaint-operation', false); }
  }

  async function refreshCounts() {
    try { const response = await json('bootstrap/'); updateCounts(response.data.counts || {}); }
    catch (_) { /* Keep the last confirmed counts. */ }
  }
  async function submitCreate(event) {
    event.preventDefault(); if (state.submitting) return;
    const formNode = event.currentTarget;
    normalizeCustomerNameInput(formNode.elements.client_name);
    const data = new FormData(formNode);
    const idError = validateCustomerId(formNode.elements.customer_id);
    if (idError) return notify(idError, true);
    if (!validateContactPair(formNode) || !validateCreateFields(formNode)) return;
    const writeKey = 'create';
    const creationRequestId = pendingWriteId(writeKey, 'complaint-create');
    const pendingEvidence = state.evidence.create.map(item => item.file);
    data.set('client_request_id', creationRequestId);
    if (acceptedVoiceAttempts.complaint_description?.id) {
      data.set('voice_transcription_id', acceptedVoiceAttempts.complaint_description.id);
    }
    if (state.categoryInferenceToken) data.set('category_inference_token', state.categoryInferenceToken);
    if (state.latitude) { data.set('latitude', state.latitude); data.set('longitude', state.longitude); }
    const button = $('createSaveBtn'); state.submitting = true; setActionLoading(button, true, 'Creating');
    utils.setCloseProtection?.('complaint-operation', true); $('createSaveState').textContent = 'Saving…';
    try {
      const response = await form('cases/create/', data); settleWrite(writeKey);
      resetVoiceField('complaint_description', false); formNode.reset();
      locationSelectOptions(formNode.elements.sub_county, [], 'Select county first');
      formNode.elements.sub_county.disabled = true;
      state.latitude = ''; state.longitude = ''; resetLocationCapture(); hideSuggestion();
      utils.setCloseProtection?.('complaint-create-draft', false); $('createSaveState').textContent = 'Saved';
      notify(response.message); void refreshCounts(); state.returnWorkspace = 'queue';
      response.case.group_id = state.groupId; response.case.global_read = false;
      renderDetail(response.case); setView('detailView');
      if (pendingEvidence.length || response.publication_deferred) {
        void finishCreatedCase(response.case, creationRequestId, pendingEvidence);
      } else clearEvidence('create');
    } catch (error) { settleWrite(writeKey, error); $('createSaveState').textContent = 'Not Saved'; presentError(error, () => formNode.requestSubmit()); }
    finally { state.submitting = false; setActionLoading(button, false); utils.setCloseProtection?.('complaint-operation', false); }
  }
  async function finishCreatedCase(caseItem, creationRequestId, files) {
    const data = new FormData();
    data.set('creation_request_id', creationRequestId);
    data.set('client_request_id', requestId('complaint-create-finish'));
    (files || []).forEach(file => data.append('evidence', file, file.name));
    utils.setCloseProtection?.('complaint-create-publication', true);
    try {
      const response = await form(`cases/${encodeURIComponent(caseItem.case_id)}/finish-created/`, data, caseItem.group_id || state.groupId);
      response.case.group_id = caseItem.group_id || state.groupId;
      response.case.global_read = false;
      if (state.currentCase?.case_id === caseItem.case_id || $('detailCaseId').textContent === caseItem.case_id) {
        renderDetail(response.case);
      }
      if ((files || []).length) notify('Complaint saved and evidence uploaded.');
    } catch (error) {
      notify('Complaint saved, but evidence or Sheet publication still needs attention.', true);
    } finally {
      clearEvidence('create');
      utils.setCloseProtection?.('complaint-create-publication', false);
    }
  }
  function validateCustomerId(input) {
    const value = String(input?.value || '').trim();
    if (!value) {
      input?.setCustomValidity?.('National ID / Maisha Namba is required.'); input?.reportValidity?.();
      return 'National ID / Maisha Namba is required.';
    }
    if (!/^\d{1,9}$/.test(value)) {
      input?.setCustomValidity?.('National ID / Maisha Namba must contain 1 to 9 digits only.'); input?.reportValidity?.();
      return 'National ID / Maisha Namba must contain 1 to 9 digits only.';
    }
    input?.setCustomValidity?.(''); return '';
  }
  function normalizedKenyanPhone(value) {
    const raw = String(value || '').trim();
    if (!raw || !/^[0-9+\s()-]+$/.test(raw) || (raw.match(/\+/g) || []).length > 1 || (raw.includes('+') && !raw.startsWith('+'))) return '';
    let digits = raw.replace(/[\s()\-+]/g, '');
    if (digits.startsWith('00254')) digits = digits.slice(2);
    else if (digits.startsWith('005')) digits = `254${digits.slice(3)}`;
    if (/^2540[17]\d{8}$/.test(digits)) digits = `254${digits.slice(4)}`;
    else if (/^0[17]\d{8}$/.test(digits)) digits = `254${digits.slice(1)}`;
    else if (/^[17]\d{8}$/.test(digits)) digits = `254${digits}`;
    return /^254[17]\d{8}$/.test(digits) && !digits.startsWith('254199') ? digits : '';
  }
  function setFieldError(input, message) {
    if (!input) return;
    input.setCustomValidity(message || '');
    input.setAttribute('aria-invalid', message ? 'true' : 'false');
  }
  function showFirstFormError(formNode) {
    const invalid = formNode.querySelector(':invalid');
    if (invalid) {
      invalid.focus(); invalid.reportValidity();
      notify(invalid.validationMessage || 'Review the highlighted field.', true);
    }
    return false;
  }
  function validateRequiredForm(formNode) {
    for (const input of formNode.querySelectorAll('[required]')) {
      setFieldError(
        input,
        String(input.value || '').trim()
          ? ''
          : `${input.closest('label')?.querySelector('span')?.textContent || input.name.replace(/_/g, ' ')} is required.`,
      );
    }
    return formNode.checkValidity() || showFirstFormError(formNode);
  }
  function validateContactPair(formNode) {
    const primary = formNode.elements.customer_phone;
    const secondary = formNode.elements.secondary_phone;
    const primaryValue = String(primary?.value || '').trim();
    const secondaryValue = String(secondary?.value || '').trim();
    const normalizedPrimary = primaryValue ? normalizedKenyanPhone(primaryValue) : '';
    const normalizedSecondary = secondaryValue ? normalizedKenyanPhone(secondaryValue) : '';
    setFieldError(
      primary,
      !primaryValue ? 'Primary Mobile Number is required.' : (!normalizedPrimary ? 'Enter a valid Kenyan mobile number.' : ''),
    );
    setFieldError(secondary, secondaryValue && !normalizedSecondary ? 'Enter a valid secondary Kenyan mobile number or leave it blank.' : '');
    if (normalizedPrimary && normalizedSecondary && normalizedPrimary === normalizedSecondary) {
      setFieldError(secondary, 'Primary and secondary phone numbers must be different.');
    }
    if (!formNode.checkValidity()) return showFirstFormError(formNode);
    return true;
  }
  function validateCreateFields(formNode) {
    if (state.locationOptionsLoading) {
      notify('Wait for the location choices to finish loading.', true);
      return false;
    }
    const whitespaceFields = ['client_name', 'village', 'complaint_description'];
    whitespaceFields.forEach(name => {
      const input = formNode.elements[name];
      setFieldError(input, String(input?.value || '').trim() ? '' : `${name.replace(/_/g, ' ')} is required.`);
    });
    const constituency = formNode.elements.sub_county;
    const validConstituency = !constituency.disabled && [...constituency.options].some(
      option => option.value && option.value === constituency.value,
    );
    setFieldError(constituency, validConstituency ? '' : 'Choose a constituency available for the selected county and branch.');
    return validateRequiredForm(formNode);
  }
  function normalizeCustomerNameInput(input) {
    if (!input) return;
    input.value = String(input.value || '').trim().replace(/\s+/g, ' ').split(/(\s+|[-'’])/).map(part => {
      if (!part || /^(\s+|[-'’])$/.test(part)) return part;
      const upper = part.toLocaleUpperCase(); const lower = part.toLocaleLowerCase();
      return part === upper || part === lower ? upper.charAt(0) + lower.slice(1) : part;
    }).join('');
  }
  function setLocationCaptureState(kind, buttonLabel, detail) {
    const button = $('captureLocationBtn'); const status = $('captureState');
    button.disabled = kind === 'capturing';
    button.classList.toggle('location-capturing', kind === 'capturing');
    button.classList.toggle('location-success', kind === 'success');
    button.classList.toggle('location-error', kind === 'error');
    const label = button.querySelector('span'); if (label) label.textContent = buttonLabel;
    status.classList.toggle('location-coordinate', kind === 'success');
    status.classList.toggle('location-error-text', kind === 'error');
    status.textContent = detail;
  }
  function resetLocationCapture() {
    setLocationCaptureState('idle', 'Use My Current Location', 'Location not added');
  }
  function captureLocation() {
    if (!navigator.geolocation) {
      setLocationCaptureState('error', 'Location Unavailable', 'This device cannot provide a GPS location.');
      notify('Location is unavailable on this device.', true); return;
    }
    setLocationCaptureState('capturing', 'Capturing Location…', 'Waiting for an accurate GPS position…');
    navigator.geolocation.getCurrentPosition(position => {
      state.latitude = position.coords.latitude.toFixed(6); state.longitude = position.coords.longitude.toFixed(6);
      setLocationCaptureState('success', 'Location Captured', `GPS: ${state.latitude}, ${state.longitude}`);
      utils.haptic?.('success');
    }, () => {
      setLocationCaptureState('error', 'Try Location Again', 'Location was not captured. Check location permission and try again.');
      notify('Location permission was not available.', true);
    }, { enableHighAccuracy: true, timeout: 12000 });
  }

  function updateEvidenceHints() {
    const limits = state.evidenceLimits;
    const text = `Up to ${limits.max_files} files · ${limits.max_file_size_mb} MB each · ${limits.max_total_upload_mb} MB total`;
    $('createEvidenceHint').textContent = text; $('resolveEvidenceHint').textContent = text;
  }
  function acceptedEvidence(file) {
    const name = String(file.name || '').toLowerCase();
    return ['image/jpeg', 'image/png', 'image/webp', 'application/pdf'].includes(file.type)
      || name.endsWith('.jpg') || name.endsWith('.jpeg') || name.endsWith('.png') || name.endsWith('.webp') || name.endsWith('.pdf');
  }
  function addFiles(target, files) {
    let added = false;
    for (const file of Array.from(files || [])) {
      const queued = state.evidence[target];
      const total = queued.reduce((sum, item) => sum + item.file.size, 0);
      if (!acceptedEvidence(file)) { notify(`${file.name || 'That file'} is not a supported evidence type.`, true); continue; }
      if (file.size > state.evidenceLimits.max_file_size_mb * 1024 * 1024) { notify(`${file.name} exceeds the ${state.evidenceLimits.max_file_size_mb} MB file limit.`, true); continue; }
      if (queued.length >= state.evidenceLimits.max_files) { notify(`You can attach up to ${state.evidenceLimits.max_files} files.`, true); continue; }
      if (total + file.size > state.evidenceLimits.max_total_upload_mb * 1024 * 1024) { notify(`These files would exceed the ${state.evidenceLimits.max_total_upload_mb} MB total limit.`, true); continue; }
      queued.push({ id: requestId('evidence-file'), file, preview: URL.createObjectURL(file) });
      added = true;
    }
    renderSelectedEvidence(target);
    if (added) utils.setCloseProtection?.(`complaint-${target}-evidence`, true);
    return added;
  }
  function removeEvidence(target, id) {
    const index = state.evidence[target].findIndex(item => item.id === id);
    if (index < 0) return;
    const [removed] = state.evidence[target].splice(index, 1);
    if (removed.preview) URL.revokeObjectURL(removed.preview);
    renderSelectedEvidence(target);
    if (!state.evidence[target].length) utils.setCloseProtection?.(`complaint-${target}-evidence`, false);
  }
  function clearEvidence(target) {
    state.evidence[target].forEach(item => { if (item.preview) URL.revokeObjectURL(item.preview); });
    state.evidence[target] = []; renderSelectedEvidence(target);
    utils.setCloseProtection?.(`complaint-${target}-evidence`, false);
  }
  function renderSelectedEvidence(target) {
    const list = $(`${target}SelectedEvidence`); list.replaceChildren();
    state.evidence[target].forEach(item => {
      const row = document.createElement('li');
      if (item.file.type.startsWith('image/')) { const image = document.createElement('img'); image.src = item.preview; image.alt = ''; row.appendChild(image); }
      else row.appendChild(textNode('span', item.file.name.split('.').pop()?.toUpperCase() || 'FILE', 'file-icon'));
      row.appendChild(textNode('span', item.file.name, 'file-name'));
      const view = buttonWithIcon('View', 'eye', 'view-file');
      view.addEventListener('click', () => openSelectedEvidence(target, item.id, view)); row.appendChild(view);
      const remove = buttonWithIcon('Remove', 'trash-2', 'remove-file');
      remove.addEventListener('click', () => removeEvidence(target, item.id)); row.appendChild(remove); list.appendChild(row);
    });
  }
  function openSelectedEvidence(target, itemId, button) {
    const item = state.evidence[target].find(entry => entry.id === itemId);
    if (!item) return;
    state.mediaViewerMode = 'selected'; state.mediaViewerTarget = target; state.mediaViewerItemId = item.id;
    const viewer = window.SecureMediaViewer; showMediaViewer(button);
    updateMediaViewerControls(item);
    if (!viewer) {
      $('mediaViewerContent').replaceChildren(textNode('p', 'The secure evidence viewer is unavailable. Refresh and retry.', 'media-viewer-error'));
      return;
    }
    state.mediaViewerObjectUrl = viewer.renderBlob($('mediaViewerContent'), item.file, { mimeType: item.file.type, name: item.file.name });
    activateMediaViewerGestures();
  }

  function stopCamera() {
    state.cameraStream?.getTracks?.().forEach(track => track.stop());
    state.cameraStream = null;
    if ($('cameraVideo')) $('cameraVideo').srcObject = null;
  }
  function closeCamera(options) {
    stopCamera(); $('cameraOverlay').hidden = true; document.body.classList.remove('camera-open');
    const focusTarget = options?.focusTarget || (state.cameraTarget ? document.querySelector(`[data-camera-target="${state.cameraTarget}"]`) : null);
    state.cameraTarget = ''; state.cameraReplaceId = ''; if (options?.restoreFocus !== false) focusTarget?.focus?.();
  }
  function updateCameraCaptureState() {
    const count = Math.max(0, (state.evidence[state.cameraTarget]?.length || 0) - state.cameraSessionStartCount);
    $('cameraCaptureState').textContent = state.cameraReplaceId
      ? 'The original stays selected until the replacement is captured.'
      : (count ? `${count} photo${count === 1 ? '' : 's'} added this session` : 'No photos added yet');
  }
  async function openCamera(target, options) {
    if (!navigator.mediaDevices?.getUserMedia) return notify('This Telegram WebView cannot open the camera directly. Use Upload Files instead.', true);
    if (!options?.replaceId && state.evidence[target].length >= state.evidenceLimits.max_files) return notify(`You can attach up to ${state.evidenceLimits.max_files} files. Delete one before taking another photo.`, true);
    state.cameraTarget = target; state.cameraReplaceId = options?.replaceId || '';
    state.cameraSessionStartCount = state.evidence[target].length;
    $('cameraTitle').textContent = state.cameraReplaceId ? 'Retake Photo' : 'Take Photos';
    $('cameraHelp').textContent = state.cameraReplaceId
      ? 'The existing photo will be replaced only after a new photo is captured.'
      : 'Take as many photos as needed, then tap Done. Nothing uploads until you submit.';
    $('cameraCaptureBtn').textContent = state.cameraReplaceId ? 'Retake Photo' : 'Take Photo';
    updateCameraCaptureState(); $('cameraOverlay').hidden = false; document.body.classList.add('camera-open');
    try {
      state.cameraStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false });
      $('cameraVideo').srcObject = state.cameraStream; await $('cameraVideo').play(); $('cameraCaptureBtn').focus();
    } catch (_) { closeCamera({ restoreFocus: true }); notify('Camera access was unavailable. Allow permission or use Upload Files.', true); }
  }
  async function captureCameraPhoto() {
    const video = $('cameraVideo'); const button = $('cameraCaptureBtn');
    if (!video.videoWidth || !video.videoHeight) return notify('The camera is still starting. Try again.', true);
    button.disabled = true;
    const canvas = $('cameraCanvas'); const maximum = 2000;
    const scale = Math.min(1, maximum / Math.max(video.videoWidth, video.videoHeight));
    canvas.width = Math.max(1, Math.round(video.videoWidth * scale)); canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
    canvas.getContext('2d')?.drawImage(video, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', .88));
    button.disabled = false;
    if (!blob) return notify('The photo could not be captured. Try again.', true);
    const target = state.cameraTarget; const replaceId = state.cameraReplaceId;
    const file = new File([blob], `complaint-evidence-${Date.now()}.jpg`, { type: 'image/jpeg' });
    if (replaceId) {
      const items = state.evidence[target]; const index = items.findIndex(item => item.id === replaceId);
      if (index < 0) { closeCamera({ restoreFocus: false }); return notify('That photo is no longer selected.', true); }
      const oldItem = items[index];
      const totalBytes = items.reduce((sum, item) => sum + item.file.size, 0) - oldItem.file.size + file.size;
      if (file.size > state.evidenceLimits.max_file_size_mb * 1024 * 1024 || totalBytes > state.evidenceLimits.max_total_upload_mb * 1024 * 1024) {
        return notify('The replacement photo exceeds the configured attachment limits.', true);
      }
      if (oldItem.preview) URL.revokeObjectURL(oldItem.preview);
      const replacement = { id: requestId('evidence-file'), file, preview: URL.createObjectURL(file) };
      items.splice(index, 1, replacement); renderSelectedEvidence(target);
      closeCamera({ restoreFocus: false }); openSelectedEvidence(target, replacement.id, null);
      notify('Photo retaken. Review it or retake it again.');
      return;
    }
    if (addFiles(target, [file])) {
      updateCameraCaptureState();
      notify('Photo added. Take another photo or tap Done.');
    }
  }

  function navigateMediaViewer(offset) {
    const entries = mediaViewerEntries();
    const index = entries.findIndex(entry => state.mediaViewerMode === 'selected'
      ? entry.id === state.mediaViewerItemId
      : entry.preview_url === state.mediaViewerItemId);
    const target = entries[index + offset];
    if (!target) return false;
    if (state.mediaViewerMode === 'selected') openSelectedEvidence(state.mediaViewerTarget, target.id, null);
    else openPersistedEvidence(target, null);
    return true;
  }
  function deleteSelectedMediaFromViewer() {
    if (state.mediaViewerMode !== 'selected') return;
    const target = state.mediaViewerTarget; const entries = mediaViewerEntries();
    const index = entries.findIndex(item => item.id === state.mediaViewerItemId);
    if (index < 0) return;
    removeEvidence(target, state.mediaViewerItemId);
    const remaining = state.evidence[target];
    if (!remaining.length) { closeMediaViewer(); notify('Attachment deleted.'); return; }
    openSelectedEvidence(target, remaining[Math.min(index, remaining.length - 1)].id, null);
    notify('Attachment deleted.');
  }
  function retakeSelectedMediaFromViewer() {
    if (state.mediaViewerMode !== 'selected') return;
    const target = state.mediaViewerTarget; const itemId = state.mediaViewerItemId;
    const item = state.evidence[target]?.find(entry => entry.id === itemId);
    if (!item || !String(item.file.type || '').startsWith('image/')) return;
    closeMediaViewer(); openCamera(target, { replaceId: itemId });
  }

  function hideSuggestion({ clearToken = true } = {}) {
    state.suggestedCategory = null;
    if (clearToken) state.categoryInferenceToken = '';
    $('categorySuggestion').hidden = true;
    $('categorySuggestion').classList.remove('checking', 'ambiguous');
  }
  function applyCategorySuggestion(result) {
    const chip = $('categorySuggestion');
    state.categoryInferenceToken = String(result?.inference_token || '');
    state.suggestedCategory = result?.suggestion || null;
    chip.disabled = true;
    chip.className = 'category-suggestion';
    if (result?.mode === 'shadow' || result?.mode === 'off') {
      chip.hidden = true;
      return;
    }
    if (result?.state === 'ambiguous') {
      const labels = (result.candidates || []).map(item => item.label).filter(Boolean).slice(0, 2);
      chip.hidden = false;
      chip.classList.add('ambiguous');
      chip.textContent = labels.length ? `Possible: ${labels.join(' / ')} — choose one` : 'More than one type may apply — choose one';
      return;
    }
    if (result?.suggestion) {
      chip.hidden = false;
      chip.disabled = false;
      chip.textContent = result.suggestion.label;
      return;
    }
    chip.hidden = false;
    chip.textContent = result?.state === 'unavailable'
      ? 'Suggestion unavailable — choose complaint type'
      : 'No clear suggestion — choose complaint type';
  }
  async function requestCategorySuggestion(description) {
    const sequence = ++state.suggestionSequence;
    const chip = $('categorySuggestion'); chip.hidden = false; chip.disabled = true; chip.className = 'category-suggestion checking'; chip.textContent = 'Checking category...';
    if (Date.now() < state.suggestionUnavailableUntil) {
      applyCategorySuggestion({ state: 'unavailable', mode: 'suggest' });
      return;
    }
    const cacheKey = description.toLocaleLowerCase();
    try {
      let result = state.categorySuggestionCache.get(cacheKey);
      if (!result) {
        const response = await json('categories/suggest/', { description });
        result = response.data || {};
        if (result.state === 'unavailable') state.suggestionUnavailableUntil = Date.now() + 30000;
        else state.categorySuggestionCache.set(cacheKey, result);
      }
      if (sequence !== state.suggestionSequence) return;
      applyCategorySuggestion(result);
    } catch (_) {
      state.suggestionUnavailableUntil = Date.now() + 30000;
      if (sequence === state.suggestionSequence) applyCategorySuggestion({ state: 'unavailable', mode: 'suggest' });
    }
  }
  function scheduleCategorySuggestion(event) {
    clearTimeout(state.suggestionTimer); const description = event.target.value.trim();
    state.categoryInferenceToken = '';
    if (description.length < 20) { hideSuggestion(); return; }
    // Wait for a meaningful pause in typing so slow mobile input does not
    // start several provider calls for successive partial descriptions.
    state.suggestionTimer = setTimeout(() => requestCategorySuggestion(description), 1500);
  }
  function updateCategoryGuidance() {
    const label = $('createCaseForm').elements.complaint_category.value.trim();
    $('categoryGuidance').textContent = state.categoryDescriptions.get(label) || 'Choose the option that best matches the main issue.';
  }

  function renderMetrics(metrics) {
    const labels = [['total', 'Total'], ['pending', 'Open'], ['resolved', 'Closed']];
    const icons = { total: 'list', pending: 'clock', resolved: 'circle-check' };
    const node = $('globalMetrics'); node.replaceChildren();
    labels.forEach(([key, label]) => {
      const card = document.createElement('div'); card.className = 'metric-card';
      card.append(iconNode(icons[key], 'metric-icon'), textNode('strong', metrics[key] || 0), textNode('span', label)); node.appendChild(card);
    });
    const timing = metrics.timing || {};
    const line = textNode('p', `Resolution ${window.ComplaintReportCharts.hours(timing.median_resolution_hours)} · ${timing.on_time_percent == null ? 'On-time rate unavailable' : timing.on_time_percent + '% on time'}`);
    line.className = 'complaint-timing-summary'; node.appendChild(line);
  }
  function refreshComplaintTheme() {
    syncComplaintGridTheme();
    if (state.globalOverview) renderReportCharts(state.globalOverview);
    state.reportGridApi?.refreshCells?.({ force: true });
  }
  function formatChartPeriodDate(value, granularity) {
    const raw = String(value || '').trim();
    let match;
    if (granularity === 'year' && (match = raw.match(/^(\d{4})$/))) return match[1];
    if (granularity === 'month' && (match = raw.match(/^(\d{4})-(\d{2})$/))) return `${formatReportDate(raw + '-01').slice(3,6)} ${match[1]}`;
    if (raw.match(/^(\d{4})-(\d{2})-(\d{2})/)) return formatReportDate(raw);
    return raw;
  }
  function setChartState(_name, message) { window.ComplaintReportCharts?.state(message); }
  function selectComplaintChart(filters, label) {
    state.reportDrill = { filters, label };
    const chip = $('complaintChartSelection'); chip.hidden = false; chip.textContent = label + ' ×';
    state.globalPage = 1;
    loadGlobalCases(currentTableFilters());
  }
  function syncComplaintGridTheme() {
    const dark = document.documentElement.dataset.miniappColorScheme === 'dark';
    $('complaintReportGrid').classList.toggle('ag-theme-quartz-dark', dark);
    $('complaintReportGrid').classList.toggle('ag-theme-quartz', !dark);
  }
  function currentTableFilters() {
    const base = currentReportFilters();
    const selected = Object.assign({}, base, state.reportDrill?.filters || {});
    // A monthly chart bucket must not expand a narrower custom date range.
    if (base.date_from && (!selected.date_from || selected.date_from < base.date_from)) selected.date_from = base.date_from;
    if (base.date_to && (!selected.date_to || selected.date_to > base.date_to)) selected.date_to = base.date_to;
    return selected;
  }
  function clearComplaintChartSelection() {
    state.reportDrill = null; $('complaintChartSelection').hidden = true;
    state.globalPage = 1; loadGlobalCases(currentTableFilters());
  }
  function renderReportCharts(summary) {
    window.ComplaintReportCharts.render(summary, {
      categoryType: state.categoryChartType, onSelect: selectComplaintChart,
      formatPeriod: formatChartPeriodDate,
    });
    syncComplaintChartDisplay();
  }
  function complaintChartSlides() {
    return Array.from($('complaintReportCharts').querySelectorAll('[data-complaint-chart-slide]'));
  }
  function syncComplaintChartDisplay() {
    const slides = complaintChartSlides();
    state.reportChartSlide = Math.max(0, Math.min(state.reportChartSlide, slides.length - 1));
    const carousel = state.reportChartDisplay === 'carousel';
    $('complaintReportCharts').classList.toggle('carousel', carousel);
    $('complaintReportCharts').classList.toggle('list', !carousel);
    slides.forEach((slide, index) => {
      slide.classList.toggle('carousel-inactive', carousel && index !== state.reportChartSlide);
      slide.setAttribute('aria-hidden', String(carousel && index !== state.reportChartSlide));
    });
    document.querySelectorAll('[data-complaint-chart-display]').forEach(button => {
      const active = button.dataset.complaintChartDisplay === state.reportChartDisplay;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    $('complaintChartPagination').hidden = !carousel;
    $('complaintChartPosition').textContent = `${state.reportChartSlide + 1} of ${slides.length}`;
    $('complaintChartPrevious').disabled = state.reportChartSlide === 0;
    $('complaintChartNext').disabled = state.reportChartSlide >= slides.length - 1;
    window.requestAnimationFrame(() => {
      window.ComplaintReportCharts?.resize();
    });
  }
  function setComplaintChartDisplay(display) {
    state.reportChartDisplay = display === 'list' ? 'list' : 'carousel';
    state.reportChartSlide = 0;
    try { localStorage.setItem('complaint-report-chart-display', state.reportChartDisplay); } catch (error) {}
    syncComplaintChartDisplay(); utils.haptic?.('light');
  }
  function moveComplaintChart(direction) {
    if (state.reportChartDisplay !== 'carousel') return;
    const next = Math.max(0, Math.min(complaintChartSlides().length - 1, state.reportChartSlide + direction));
    if (next === state.reportChartSlide) return;
    state.reportChartSlide = next; syncComplaintChartDisplay(); utils.haptic?.('light');
  }
  function preserveSelectOptions(select, items, placeholder) {
    const selected = select.value;
    selectOptions(select, items.map(item => item.label), placeholder);
    if (Array.from(select.options).some(option => option.value === selected)) select.value = selected;
  }
  function populateGlobalFilters(summary) {
    const formNode = $('globalFilters');
    preserveSelectOptions(formNode.elements.branch, summary.filter_options?.branches || [], 'Any Branch');
    preserveSelectOptions(formNode.elements.category, summary.filter_options?.categories || [], 'Any Category');
  }
  function showChartLoading() { setChartState('category', 'Loading complaint types...'); setChartState('time', 'Loading complaint history...'); }
  async function loadGlobalOverview(filters) {
    const sequence = ++state.reportSummarySequence; showChartLoading();
    try {
      const summary = await getJson('reports/summary/', Object.assign({}, filters, { granularity: state.reportGranularity }));
      if (sequence !== state.reportSummarySequence) return null;
      state.globalOverview = summary; renderMetrics(summary); populateGlobalFilters(summary); renderReportCharts(summary);
      state.globalLoaded = true; return summary;
    } catch (error) {
      if (sequence === state.reportSummarySequence) {
        setChartState('category', error.message); setChartState('time', error.message); presentError(error, refreshReport);
      }
      return null;
    }
  }
  function updateReportDateControls() {
    const formNode = $('globalFilters'); const mode = formNode.elements.date_mode.value;
    $('reportMonthField').hidden = mode !== 'month'; $('reportCustomDates').hidden = mode !== 'custom';
    formNode.elements.report_month.disabled = mode !== 'month';
    formNode.elements.date_from.disabled = mode !== 'custom'; formNode.elements.date_to.disabled = mode !== 'custom';
  }
  function snapshotComplaintReportFilters() {
    return Array.from($('globalFilters').elements).filter(input => input.name).map(input => [input.name, input.value]);
  }
  function closeComplaintReportFilters({ applied = false, restoreFocus = true } = {}) {
    if (!state.reportFilterSheetOpen) return;
    if (!applied && state.reportFilterSnapshot) {
      state.reportFilterSnapshot.forEach(([name, value]) => { $('globalFilters').elements[name].value = value; });
      updateReportDateControls();
    }
    state.reportFilterSheetOpen = false;
    state.reportFilterSnapshot = null;
    $('complaintReportFilterOverlay').hidden = true;
    $('complaintReportFilterOverlay').setAttribute('aria-hidden', 'true');
    document.body.classList.remove('complaint-filter-open');
    if (restoreFocus) state.reportFilterReturnFocus?.focus?.();
    state.reportFilterReturnFocus = null;
  }
  function openComplaintReportFilters() {
    if (state.reportFilterSheetOpen) return;
    if (state.reportSearchTimer) {
      clearTimeout(state.reportSearchTimer);
      state.reportSearchTimer = null;
      refreshReport();
    }
    state.reportFilterSheetOpen = true;
    state.reportFilterSnapshot = snapshotComplaintReportFilters();
    state.reportFilterReturnFocus = document.activeElement;
    $('complaintReportFilterOverlay').hidden = false;
    $('complaintReportFilterOverlay').setAttribute('aria-hidden', 'false');
    document.body.classList.add('complaint-filter-open');
    $('complaintReportFilterSheet').focus();
    utils.haptic?.('light');
  }
  function syncComplaintFilterSummary(filters) {
    const formNode = $('globalFilters');
    const active = ['status', 'branch', 'category'].filter(name => formNode.elements[name].value);
    if (formNode.elements.date_mode.value !== 'all') active.push('date');
    const badge = $('complaintActiveFilterCount');
    badge.textContent = String(active.length); badge.hidden = !active.length;
    const labels = [formNode.elements.status, formNode.elements.branch, formNode.elements.category]
      .filter(input => input.value).map(input => input.selectedOptions[0]?.textContent || input.value);
    $('complaintFilterSummary').textContent = labels.length ? labels.join(' · ') : 'All complaints';
    $('reportPeriodLabel').textContent = reportPeriodText(filters);
  }
  function monthBoundaries(value) {
    const match = /^(\d{4})-(\d{2})$/.exec(value || '');
    if (!match) throw new Error('Select the month you want to report on.');
    const year = Number(match[1]); const month = Number(match[2]);
    const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
    return [`${value}-01`, `${value}-${String(lastDay).padStart(2, '0')}`];
  }
  function globalFilterPayload() {
    const formNode = $('globalFilters'); const values = {};
    for (const name of ['search', 'status', 'branch', 'category', 'date_basis']) if (formNode.elements[name].value) values[name] = formNode.elements[name].value;
    const mode = formNode.elements.date_mode.value;
    if (mode === 'month') [values.date_from, values.date_to] = monthBoundaries(formNode.elements.report_month.value);
    if (mode === 'custom') {
      values.date_from = formNode.elements.date_from.value; values.date_to = formNode.elements.date_to.value;
      if (!values.date_from && !values.date_to) throw new Error('Select a start date, an end date, or both.');
      if (values.date_from && values.date_to && values.date_from > values.date_to) throw new Error('Start Date must be on or before End Date.');
    }
    return values;
  }
  function reportPeriodText(filters) {
    const formNode = $('globalFilters'); const mode = formNode.elements.date_mode.value;
    if (mode === 'month' && formNode.elements.report_month.value) {
      const [year, month] = formNode.elements.report_month.value.split('-').map(Number);
      return new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(Date.UTC(year, month - 1, 1)));
    }
    if (mode === 'custom') {
      const format = value => value ? new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${value}T00:00:00Z`)) : '';
      const basis = filters.date_basis === 'resolved' ? 'Resolved' : 'Reported';
      if (filters.date_from && filters.date_to) return `${basis} ${format(filters.date_from)} – ${format(filters.date_to)}`;
      return filters.date_from ? `${basis} from ${format(filters.date_from)}` : `${basis} through ${format(filters.date_to)}`;
    }
    return 'All reporting dates';
  }
  function currentReportFilters() {
    const filters = globalFilterPayload(); syncComplaintFilterSummary(filters); return filters;
  }
  async function refreshReport(options) {
    let filters; try { filters = currentReportFilters(); } catch (error) { notify(error.message, true); return; }
    const settings = Object.assign({ summary: true, table: true }, options || {}); const requests = [];
    if (settings.summary) requests.push(loadGlobalOverview(filters));
    if (settings.table) requests.push(loadGlobalCases(currentTableFilters()));
    await Promise.all(requests);
  }
  function formatReportDate(value) {
    if (!value) return '';
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const match = String(value).match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (match) return `${match[3]}-${months[Number(match[2]) - 1]}-${match[1]}`;
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return value;
    return [String(parsed.getDate()).padStart(2, '0'), months[parsed.getMonth()], parsed.getFullYear()].join('-');
  }
  function formatReportUppercase(value) {
    return typeof value === 'string' ? value.toUpperCase() : value;
  }
  function reportStatusRenderer(params) {
    const label = formatReportUppercase(params.value || 'OPEN');
    const statusKey = String(label).trim().toLowerCase().replace(/[^a-z0-9]+/g, '-');
    return textNode('span', label, `report-status ${statusKey}`);
  }
  function reportGpsRenderer(params) {
    if (!params.value) return '';
    const link = textNode('a', 'Open Map', 'report-gps');
    link.href = params.value; link.target = '_blank'; link.rel = 'noopener noreferrer';
    return link;
  }
  function bindReportGridZoom() {
    if (state.reportGridZoom || !window.MiniAppAgGridZoom) return;
    state.reportGridZoom = window.MiniAppAgGridZoom.bind({
      container: $('complaintGridZoom'),
      gridElement: $('complaintReportGrid'),
      outButton: $('complaintGridZoomOut'),
      resetButton: $('complaintGridZoomReset'),
      inButton: $('complaintGridZoomIn'),
      storageKey: 'complaint-report-grid-zoom',
      apiProvider: () => state.reportGridApi,
      defaults: { fontSize: 11, gridSize: 4, rowHeight: 34, headerHeight: 36, cellPadding: 4, smallFontSize: 10 },
    });
  }
  function initializeReportGrid() {
    if (state.reportGridApi || !window.agGrid) return;
    syncComplaintGridTheme();
    const touchManagedColumns = window.matchMedia('(max-width: 700px), (pointer: coarse)').matches;
    window.agGrid.ModuleRegistry.registerModules([window.agGrid.AllCommunityModule]);
    state.reportGridApi = window.agGrid.createGrid($('complaintReportGrid'), {
      theme: 'legacy', rowData: [], animateRows: false, suppressMultiSort: true,
      suppressMovableColumns: true, suppressColumnMoveAnimation: true,
      suppressCellFocus: false, ensureDomOrder: true, overlayNoRowsTemplate: 'No complaints match these filters.',
      defaultColDef: { sortable: true, resizable: !touchManagedColumns, suppressHeaderMenuButton: true, unSortIcon: true },
      columnDefs: [
        { headerName: '#', colId: 'row_number', width: 52, minWidth: 52, maxWidth: 52, sortable: false, resizable: false, pinned: 'left', valueGetter: p => ((state.globalPage - 1) * state.globalPageSize) + p.node.rowIndex + 1 },
        { headerName: 'Complaint ID', field: 'complaint_id', width: 125, sortable: false, valueFormatter: p => formatReportUppercase(p.value) },
        { headerName: 'Date Reported', field: 'date_reported', width: 130, valueFormatter: p => formatReportDate(p.value) },
        { headerName: 'Status', field: 'status', width: 170, cellRenderer: reportStatusRenderer },
        { headerName: 'Customer Name', field: 'customer_name', width: 190, sortable: false, valueFormatter: p => formatReportUppercase(p.value) },
        { headerName: 'Customer National ID', field: 'customer_id', width: 155, sortable: false },
        { headerName: 'Primary Phone Number', field: 'phone_number', width: 165, sortable: false },
        { headerName: 'Secondary Phone No', field: 'secondary_phone_number', width: 155, sortable: false },
        { headerName: 'County', field: 'county', width: 135, sortable: false, valueFormatter: p => formatReportUppercase(p.value) },
        { headerName: 'Constituency', field: 'constituency', width: 155, sortable: false, valueFormatter: p => formatReportUppercase(p.value) },
        { headerName: 'Village', field: 'village', width: 145, sortable: false, valueFormatter: p => formatReportUppercase(p.value) },
        { headerName: 'Branch', field: 'branch_region', width: 145, valueFormatter: p => formatReportUppercase(p.value) },
        { headerName: 'JBL Reported By', field: 'reported_by', width: 165, sortable: false, valueFormatter: p => formatReportUppercase(p.value) },
        { headerName: 'Complaint Type', field: 'complaint_category', width: 180, sortable: false, valueFormatter: p => formatReportUppercase(p.value) },
        { headerName: 'Complaint Description', field: 'complaint_description', width: 280, sortable: false },
        { headerName: 'GPS Link', field: 'gps_link', width: 105, sortable: false, cellRenderer: reportGpsRenderer },
        { headerName: 'Resolution Details', field: 'resolution_details', width: 260, sortable: false },
        { headerName: 'Resolution Comments', field: 'resolution_comments', width: 300, sortable: false },
        { headerName: 'Date Resolved', field: 'date_resolved', width: 130, valueFormatter: p => formatReportDate(p.value) },
        { headerName: 'Days Open', field: 'days_open', width: 105, type: 'numericColumn' },
        { headerName: 'Resolution time', field: 'resolution_hours', width: 130, sortable: false, valueFormatter: p => window.ComplaintReportCharts.hours(p.value) },
        { headerName: 'HB response', field: 'hb_response_hours', width: 125, sortable: false, valueFormatter: p => window.ComplaintReportCharts.hours(p.value) },
        { headerName: 'Resolution History', field: 'resolution_history_count', width: 145, sortable: false, valueFormatter: p => p.value ? `${p.value} ${p.value === 1 ? 'entry' : 'entries'}` : 'No history' },
      ],
      onSortChanged: event => {
        if (state.reportGridLoading) return;
        const selected = event.api.getColumnState().find(column => column.sort);
        const allowed = { date_reported: 'date_reported', status: 'status', branch_region: 'branch_region', days_open: 'days_open', date_resolved: 'date_resolved' };
        state.globalSort = selected && allowed[selected.colId]
          ? `${selected.sort === 'desc' ? '-' : ''}${allowed[selected.colId]}` : '-date_reported';
        state.globalPage = 1; refreshReport({ summary: false });
      },
    });
    bindReportGridCopy();
    state.reportGridZoom?.refresh();
  }
  async function loadGlobalCases(filters) {
    const sequence = ++state.reportTableSequence;
    state.reportTableAbortController?.abort();
    const controller = typeof AbortController === 'function' ? new AbortController() : null;
    state.reportTableAbortController = controller;
    let requestTimedOut = false;
    const reportRequestId = requestId('complaint-report');
    let timeout;
    const timeoutPromise = new Promise((resolve, reject) => {
      timeout = setTimeout(() => {
        requestTimedOut = true; controller?.abort();
        reject(new Error('The complaints table request timed out.'));
      }, 20000);
    });
    initializeReportGrid();
    state.reportGridLoading = true; state.reportGridApi?.showLoadingOverlay();
    try {
      const response = await Promise.race([getJson('reports/data/', Object.assign({}, filters, {
        page: state.globalPage, page_size: state.globalPageSize, sort: state.globalSort,
      }), { signal: controller?.signal, requestId: reportRequestId }), timeoutPromise]);
      if (sequence !== state.reportTableSequence) return;
      state.globalPage = response.page; state.globalPages = Math.max(1, Math.ceil(response.count / response.page_size));
      $('globalResultCount').textContent = `${response.count} complaint${response.count === 1 ? '' : 's'} found`;
      const rows = response.results || [];
      state.reportGridApi?.setGridOption('rowData', rows);
      if (rows.length) state.reportGridApi?.hideOverlay();
      else state.reportGridApi?.showNoRowsOverlay();
      $('globalPagination').hidden = state.globalPages <= 1;
      $('globalPageLabel').textContent = `Page ${state.globalPage} of ${state.globalPages}`;
      $('globalPreviousBtn').disabled = state.globalPage <= 1; $('globalNextBtn').disabled = state.globalPage >= state.globalPages;
    } catch (error) {
      if (sequence === state.reportTableSequence) {
        state.reportGridApi?.hideOverlay(); state.reportGridApi?.showNoRowsOverlay();
        const displayed = requestTimedOut && utils.clientRequestError
          ? utils.clientRequestError('timeout', { headers: { 'X-Request-ID': reportRequestId } }) : error;
        presentError(displayed, () => refreshReport({ summary: false }));
      }
    } finally {
      clearTimeout(timeout);
      if (sequence === state.reportTableSequence) {
        state.reportGridLoading = false;
        if (state.reportTableAbortController === controller) state.reportTableAbortController = null;
      }
    }
  }
  async function openGlobalWorkspace() {
    if (!can('complaint.reports.view')) return notify('Management report access is not assigned to your account.', true);
    state.returnWorkspace = 'queue'; setView('globalView');
    await refreshReport();
  }
  async function refreshGlobal() { await refreshReport(); }

  async function prepareExport(mode) {
    try {
      $('downloadResult').hidden = true;
      state.exportFilters = mode === 'results' ? currentTableFilters() : null;
      const overview = await getJson('reports/summary/', Object.assign({}, state.exportFilters || {}, { granularity: 'year' })); const count = overview.total || 0;
      $('exportConfirmText').textContent = `Download ${mode === 'results' ? 'these' : 'all'} ${count} complaints as an Excel file?`;
      $('exportConfirm').hidden = false; $('cancelExportBtn').focus();
    } catch (error) { presentError(error, openGlobalWorkspace); }
  }
  function cancelExport() { $('exportConfirm').hidden = true; (state.exportFilters ? $('exportResultsBtn') : $('exportAllBtn')).focus(); }
  function releaseExportDownload() {
    if (state.exportObjectUrl) URL.revokeObjectURL(state.exportObjectUrl);
    state.exportObjectUrl = ''; state.exportDownloadUrl = '';
    state.exportFilename = ''; state.exportFile = null;
  }
  function startExportDownload() {
    if (!state.exportObjectUrl || !state.exportFilename) return false;
    const link = document.createElement('a');
    link.href = state.exportObjectUrl; link.download = state.exportFilename;
    document.body.appendChild(link); link.click(); link.remove();
    return true;
  }
  function isMobileExportClient() {
    const platform = String(telegram?.platform || '').toLowerCase();
    return ['android', 'ios'].includes(platform) || /Android|iPhone|iPad|iPod/i.test(navigator.userAgent || '');
  }
  function telegramNativeDownloadAvailable() {
    return isMobileExportClient() && typeof telegram?.downloadFile === 'function';
  }
  function showExportDownload(filename, nativeAvailable) {
    $('downloadFilename').textContent = filename;
    $('downloadResultTitle').textContent = nativeAvailable ? 'Excel file ready' : 'Download started';
    const message = $('downloadResultMessage'); const filenameNode = $('downloadFilename');
    message.replaceChildren(filenameNode, document.createTextNode(nativeAvailable
      ? ' is ready. Save it to your device, then open it with Excel or Google Sheets.'
      : ' was sent to your device. Check Downloads or your browser’s download list.'));
    $('openExportBtn').hidden = !nativeAvailable;
    $('downloadResult').hidden = false;
  }
  async function openExportNatively(options) {
    const settings = options || {};
    if (!state.exportDownloadUrl || !state.exportFilename) {
      if (!settings.quiet) notify('That download link is no longer available. Create a new complaints download.', true);
      return false;
    }
    if (telegramNativeDownloadAvailable()) {
      const accepted = await new Promise(resolve => {
        try {
          telegram.downloadFile({ url: state.exportDownloadUrl, file_name: state.exportFilename }, value => resolve(value !== false));
        } catch (_) { resolve(false); }
      });
      if (!settings.quiet) notify(accepted ? 'Download started. Check your phone downloads.' : 'Download cancelled.', !accepted);
      return accepted;
    }
    try {
      if (typeof telegram?.openLink === 'function') telegram.openLink(state.exportDownloadUrl);
      else window.open(state.exportDownloadUrl, '_blank', 'noopener,noreferrer');
      if (!settings.quiet) notify('The download opened in your phone browser.');
      return true;
    } catch (_) {
      if (!settings.quiet) notify('The phone could not open the download. Try again or update Telegram.', true);
      return false;
    }
  }
  async function confirmExport() {
    const button = $('confirmExportBtn'); setActionLoading(button, true, 'Downloading');
    try {
      const exportPayload = Object.assign({}, state.exportFilters || {}, {
        confirm_all: !state.exportFilters, confirm_results: !!state.exportFilters,
        client_request_id: requestId('complaint-export'),
      });
      if (isMobileExportClient()) {
        const result = await json('global/export/', {
          ...exportPayload, delivery: 'signed_url',
        });
        releaseExportDownload();
        state.exportDownloadUrl = result.download_url;
        state.exportFilename = result.filename || 'complaints.xlsx';
        showExportDownload(state.exportFilename, true);
        $('exportConfirm').hidden = true;
        const opened = await openExportNatively({ quiet: true });
        notify(opened
          ? 'Download started. Check your phone downloads.'
          : 'Excel file ready. Tap Open Excel File to download it.');
        return;
      }
      const result = await apiClient.postBlob('global/export/', { group_id: state.groupId, ...exportPayload }, state.initData, utils);
      releaseExportDownload();
      state.exportObjectUrl = URL.createObjectURL(result.blob);
      state.exportFilename = result.filename || 'complaints.xlsx';
      state.exportFile = typeof File === 'function' ? new File([result.blob], state.exportFilename, {
        type: result.blob.type || 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      }) : null;
      showExportDownload(state.exportFilename, false);
      $('exportConfirm').hidden = true;
      startExportDownload(); notify(`Download started. Check Downloads for ${state.exportFilename}.`);
    } catch (error) { presentError(error, confirmExport); }
    finally { setActionLoading(button, false); }
  }
  function downloadAgain() {
    if (state.exportDownloadUrl) return openExportNatively();
    if (!startExportDownload()) return notify('That download is no longer available. Create a new complaints download.', true);
    notify(`Download started again. Check Downloads for ${state.exportFilename}.`);
  }
  function returnPrevious() {
    if ($('complaintSettingsOverlay') && !$('complaintSettingsOverlay').hidden) { closeComplaintSettings(); return; }
    if (state.reportFilterSheetOpen) { closeComplaintReportFilters(); return; }
    if (!$('mediaViewerOverlay').hidden) { closeMediaViewer(); return; }
    if (!$('cameraOverlay').hidden) { closeCamera(); return; }
    if (!$('exportConfirm').hidden) { cancelExport(); return; }
    if (!$('createView').hidden) resetVoiceField('complaint_description');
    if (!$('detailView').hidden) {
      resetVoiceField('complaint_resolution_note'); resetVoiceField('complaint_reopen_reason');
      resetVoiceField('complaint_resolution_comment');
    }
    if (!$('globalView').hidden) { setView('queueView'); loadCases(); return; }
    if (state.returnWorkspace === 'global') { setView('globalView'); refreshReport(); }
    else { setView('queueView'); loadCases(); }
  }

  document.querySelectorAll('[data-status]').forEach(button => button.addEventListener('click', () => {
    state.status = button.dataset.status; state.page = 1;
    document.querySelectorAll('[data-status]').forEach(item => item.classList.toggle('active', item === button)); loadCases();
  }));
  $('caseSearch').addEventListener('input', event => { state.query = event.target.value; state.page = 1; clearTimeout(state.debounce); state.debounce = setTimeout(loadCases, state.query ? 250 : 0); });
  $('queuePreviousBtn').addEventListener('click', () => { if (state.page > 1) { state.page -= 1; loadCases(); } });
  $('queueNextBtn').addEventListener('click', () => { if (state.page < state.pages) { state.page += 1; loadCases(); } });
  $('globalPreviousBtn').addEventListener('click', () => { if (state.globalPage > 1) { state.globalPage -= 1; refreshReport({ summary: false }); } });
  $('globalNextBtn').addEventListener('click', () => { if (state.globalPage < state.globalPages) { state.globalPage += 1; refreshReport({ summary: false }); } });
  $('queueWorkspaceBtn').addEventListener('click', () => { setView('queueView'); loadCases(); });
  $('globalWorkspaceBtn').addEventListener('click', openGlobalWorkspace);
  $('reportBackBtn').addEventListener('click', () => { setView('queueView'); loadCases(); });
  $('openComplaintReportFilters').addEventListener('click', openComplaintReportFilters);
  $('closeComplaintReportFilters').addEventListener('click', () => closeComplaintReportFilters());
  $('complaintReportFilterOverlay').addEventListener('click', event => { if (event.target === event.currentTarget) closeComplaintReportFilters(); });
  $('complaintReportFilterSheet').addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); closeComplaintReportFilters(); return; }
    if (event.key !== 'Tab') return;
    const focusable = Array.from($('complaintReportFilterSheet').querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled)'));
    const first = focusable[0]; const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });
  $('globalFilters').addEventListener('submit', event => {
    event.preventDefault();
    try { globalFilterPayload(); } catch (error) {
      notify(error.message, true);
      const formNode = $('globalFilters');
      (formNode.elements.date_mode.value === 'month' ? formNode.elements.report_month : formNode.elements.date_from).focus();
      return;
    }
    clearTimeout(state.reportSearchTimer); state.reportSearchTimer = null; state.globalPage = 1;
    state.reportDrill = null; $('complaintChartSelection').hidden = true;
    closeComplaintReportFilters({ applied: true }); refreshReport();
  });
  $('clearGlobalFiltersBtn').addEventListener('click', () => {
    const search = $('globalSearch').value;
    $('globalFilters').reset();
    $('globalSearch').value = search;
    updateReportDateControls();
    $('globalFilters').elements.status.focus();
  });
  $('globalFilters').addEventListener('change', event => { if (event.target.name === 'date_mode') updateReportDateControls(); });
  $('globalSearch').addEventListener('input', event => {
    clearTimeout(state.reportSearchTimer);
    state.globalPage = 1;
    state.reportSearchTimer = setTimeout(() => {
      state.reportSearchTimer = null;
      refreshReport();
    }, event.target.value ? 250 : 0);
  });
  document.querySelectorAll('[data-complaint-chart-display]').forEach(button => button.addEventListener('click', () => setComplaintChartDisplay(button.dataset.complaintChartDisplay)));
  $('complaintChartPrevious').addEventListener('click', () => moveComplaintChart(-1));
  $('complaintChartNext').addEventListener('click', () => moveComplaintChart(1));
  $('complaintReportCharts').addEventListener('keydown', event => {
    if (event.target.closest('button, input, select, textarea, a')) return;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault(); moveComplaintChart(event.key === 'ArrowLeft' ? -1 : 1);
    }
  });
  $('complaintReportCharts').addEventListener('touchstart', event => {
    state.reportChartTouchStart = null;
    if (state.reportChartDisplay !== 'carousel' || event.touches.length !== 1) return;
    state.reportChartTouchStart = { x: event.touches[0].clientX, y: event.touches[0].clientY };
  }, { passive: true });
  $('complaintReportCharts').addEventListener('touchend', event => {
    if (!state.reportChartTouchStart || !event.changedTouches.length) return;
    const deltaX = event.changedTouches[0].clientX - state.reportChartTouchStart.x;
    const deltaY = event.changedTouches[0].clientY - state.reportChartTouchStart.y;
    state.reportChartTouchStart = null;
    if (Math.abs(deltaX) >= 45 && Math.abs(deltaX) > Math.abs(deltaY) * 1.2) moveComplaintChart(deltaX < 0 ? 1 : -1);
  }, { passive: true });
  $('complaintReportCharts').addEventListener('touchcancel', () => { state.reportChartTouchStart = null; }, { passive: true });
  document.querySelectorAll('[data-category-chart]').forEach(button => button.addEventListener('click', () => {
    state.categoryChartType = button.dataset.categoryChart;
    document.querySelectorAll('[data-category-chart]').forEach(option => {
      const active = option === button; option.classList.toggle('active', active); option.setAttribute('aria-pressed', String(active));
    });
    if (state.globalOverview) renderReportCharts(state.globalOverview);
  }));
  // One report time grouping, available on every time-series slide. Copies
  // stay synchronized so swiping never silently changes the population.
  ['resolution', 'response', 'reopened'].forEach(key => {
    const head = document.querySelector(`[data-complaint-chart="${key}"] .report-chart-head`);
    if (!head) return;
    const label = $('reportGranularity').parentElement.cloneNode(true);
    label.querySelector('select').removeAttribute('id');
    head.appendChild(label);
  });
  document.querySelectorAll('.chart-granularity select').forEach(control => control.addEventListener('change', event => {
    state.reportGranularity = event.target.value;
    document.querySelectorAll('.chart-granularity select').forEach(select => { select.value = state.reportGranularity; });
    refreshReport({ table: false }); utils.haptic?.('light');
  }));
  $('exportAllBtn').addEventListener('click', () => prepareExport('all'));
  $('exportResultsBtn').addEventListener('click', () => prepareExport('results'));
  $('complaintChartSelection').addEventListener('click', clearComplaintChartSelection);
  $('cancelExportBtn').addEventListener('click', cancelExport); $('confirmExportBtn').addEventListener('click', confirmExport);
  $('openExportBtn').addEventListener('click', () => openExportNatively());
  $('downloadAgainBtn').addEventListener('click', downloadAgain);
  $('newCaseBtn').addEventListener('click', () => { resetVoiceField('complaint_description'); state.returnWorkspace = 'queue'; setView('createView'); });
  document.querySelectorAll('[data-back]').forEach(button => button.addEventListener('click', returnPrevious));
  function closeComplaintSettings() {
    $('complaintSettingsOverlay').hidden = true;
    $('complaintSettingsBtn').focus();
    if (!$('detailView').hidden || !$('globalView').hidden || !$('createView').hidden) telegram?.BackButton?.show();
    else telegram?.BackButton?.hide();
  }
  $('complaintSettingsBtn')?.addEventListener('click', () => {
    window.MiniAppReportEmailSettings?.mount($('complaintReportEmailSettings'), payload => json('settings/reports/', payload));
    $('complaintSettingsOverlay').hidden = false;
    $('complaintSettingsClose').focus();
    telegram?.BackButton?.show();
  });
  $('complaintSettingsClose')?.addEventListener('click', closeComplaintSettings);
  $('complaintSettingsOverlay')?.addEventListener('click', event => { if (event.target === event.currentTarget) closeComplaintSettings(); });
  document.addEventListener('keydown', event => {
    const overlay=$('complaintSettingsOverlay');
    if(!overlay || overlay.hidden)return;
    if(event.key==='Escape') { event.preventDefault(); closeComplaintSettings(); }
    if(event.key==='Tab') {
      const controls=[...overlay.querySelectorAll('button,input,select,textarea')].filter(n=>!n.disabled && n.offsetParent!==null);
      if(!controls.length)return;
      const first=controls[0],last=controls[controls.length-1];
      if(event.shiftKey && document.activeElement===first){event.preventDefault();last.focus();}
      else if(!event.shiftKey && document.activeElement===last){event.preventDefault();first.focus();}
    }
  });
  $('refreshBtn').addEventListener('click', () => {
    if (!$('queueView').hidden) { state.page = 1; loadCases(); refreshCounts(); }
    else if (!$('globalView').hidden) refreshGlobal();
    else if (state.currentCase?.global_read) openGlobalCase(state.currentCase.id);
    else if (state.currentCase) openCase(state.currentCase.case_id);
  });
  $('captureLocationBtn').addEventListener('click', captureLocation);
  document.querySelectorAll('[data-files-target]').forEach(button => button.addEventListener('click', () => $(`${button.dataset.filesTarget}EvidenceInput`).click()));
  document.querySelectorAll('[data-camera-target]').forEach(button => button.addEventListener('click', () => openCamera(button.dataset.cameraTarget)));
  ['create', 'resolve'].forEach(target => $(`${target}EvidenceInput`).addEventListener('change', event => { addFiles(target, event.target.files); event.target.value = ''; }));
  $('cameraCloseBtn').addEventListener('click', () => closeCamera()); $('cameraCancelBtn').addEventListener('click', () => closeCamera()); $('cameraCaptureBtn').addEventListener('click', captureCameraPhoto);
  $('cameraOverlay').addEventListener('click', event => { if (event.target === event.currentTarget) closeCamera(); });
  $('mediaViewerClose').addEventListener('click', closeMediaViewer);
  $('mediaViewerPrevious').addEventListener('click', () => navigateMediaViewer(-1));
  $('mediaViewerNext').addEventListener('click', () => navigateMediaViewer(1));
  $('mediaViewerDelete').addEventListener('click', deleteSelectedMediaFromViewer);
  $('mediaViewerRetake').addEventListener('click', retakeSelectedMediaFromViewer);
  $('mediaViewerOverlay').addEventListener('click', event => { if (event.target === event.currentTarget) closeMediaViewer(); });
  $('mediaViewerContent').addEventListener('pointerdown', mediaViewerPointerDown);
  $('mediaViewerContent').addEventListener('pointermove', mediaViewerPointerMove);
  $('mediaViewerContent').addEventListener('pointerup', event => finishMediaViewerPointer(event, false));
  $('mediaViewerContent').addEventListener('pointercancel', event => finishMediaViewerPointer(event, true));
  $('mediaViewerContent').addEventListener('lostpointercapture', event => finishMediaViewerPointer(event, true));
  $('createCaseForm').elements.complaint_description.addEventListener('input', scheduleCategorySuggestion);
  $('createCaseForm').elements.complaint_category.addEventListener('input', updateCategoryGuidance);
  $('createCaseForm').elements.branch_region.addEventListener('change', () => refreshLocationOptions().catch(error => presentError(error, refreshLocationOptions)));
  $('createCaseForm').elements.county.addEventListener('change', () => refreshLocationOptions().catch(error => presentError(error, refreshLocationOptions)));
  $('createCaseForm').elements.client_name.addEventListener('blur', event => normalizeCustomerNameInput(event.currentTarget));
  document.querySelectorAll('#createCaseForm input, #createCaseForm textarea, #createCaseForm select, #completeDetailsForm input, #completeDetailsForm select, #resolveForm textarea, #commentForm textarea, #reopenForm textarea').forEach(input => input.addEventListener('input', () => {
    input.setCustomValidity(''); input.setAttribute('aria-invalid', 'false');
  }));
  document.querySelectorAll('input[name="customer_id"]').forEach(input => input.addEventListener('input', () => validateCustomerId(input)));
  $('categorySuggestion').addEventListener('click', () => {
    if (!state.suggestedCategory) return;
    $('createCaseForm').elements.complaint_category.value = state.suggestedCategory.label;
    updateCategoryGuidance();
    $('categorySuggestion').textContent = `${state.suggestedCategory.label} selected`;
    $('categorySuggestion').disabled = true;
  });
  $('createCaseForm').addEventListener('submit', submitCreate);
  $('completeDetailsForm').addEventListener('submit', submitCompleteDetails);
  $('resolveForm').addEventListener('submit', event => submitTransition(event, 'resolve'));
  $('commentForm').addEventListener('submit', event => submitTransition(event, 'comments'));
  $('commentTab').addEventListener('click', () => { if (!state.submitting) selectHbAction('comment'); });
  $('resolveTab').addEventListener('click', () => { if (!state.submitting) selectHbAction('resolve'); });
  $('hbActionTabs').addEventListener('keydown', event => {
    if (state.submitting || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    const tabs = [$('commentTab'), $('resolveTab')].filter(tab => !tab.hidden);
    const index = tabs.indexOf(document.activeElement);
    const next = event.key === 'Home' ? 0 : (event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowLeft' ? -1 : 1) + tabs.length) % tabs.length);
    event.preventDefault(); tabs[next]?.focus(); tabs[next]?.click();
  });
  $('reopenForm').addEventListener('submit', event => submitTransition(event, 'reopen'));
  $('copyConflictDraftBtn').addEventListener('click', copyConflictDraft);
  $('errorBannerDismiss').addEventListener('click', clearPresentedError);
  $('errorBannerRetry').addEventListener('click', () => {
    const retry = state.errorRetry;
    clearPresentedError();
    if (retry) Promise.resolve().then(retry).catch(error => presentError(error, retry));
  });
  $('errorBannerCloseApp').addEventListener('click', () => telegram?.close?.());
  $('reviewConflictBtn').addEventListener('click', () => state.currentCase.global_read ? openGlobalCase(state.currentCase.id) : openCase(state.currentCase.case_id));
  $('createCaseForm').addEventListener('input', () => utils.setCloseProtection?.('complaint-create-draft', true));
  $('createCaseForm').addEventListener('change', () => utils.setCloseProtection?.('complaint-create-draft', true));
  ['completeDetailsForm', 'resolveForm', 'commentForm', 'reopenForm'].forEach(id => $(id).addEventListener('input', () => utils.setCloseProtection?.('complaint-transition-draft', true)));
  document.addEventListener('click', event => {
    const button = event.target.closest?.('button');
    if (button && !button.disabled) utils.haptic?.('light');
  }, { capture: true });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      closeCamera({ restoreFocus: false });
      const widget = document.querySelector('.voice-input.recording');
      if (widget) stopVoiceRecording(widget, true);
    }
  });
  window.addEventListener('pagehide', () => { discardPendingVoice(); closeCamera({ restoreFocus: false }); closeMediaViewer(); releaseExportDownload(); });
  window.addEventListener('beforeunload', () => { releaseVoiceStream(); stopCamera(); window.SecureMediaViewer?.revoke(state.mediaViewerObjectUrl); releaseExportDownload(); });
  telegram?.onEvent?.('deactivated', () => { discardPendingVoice(); closeCamera({ restoreFocus: false }); });
  telegram?.BackButton?.onClick(returnPrevious);
  updateReportDateControls();
  bindCollapsingHeader();
  bindReportGridZoom();
  utils.bindMiniAppTheme?.(telegram, refreshComplaintTheme);
  bootstrap();
}());
