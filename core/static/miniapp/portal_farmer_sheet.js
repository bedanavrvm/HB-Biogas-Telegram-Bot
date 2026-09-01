(function () {
  'use strict';

  let deps = null;
  let mapInstance = null;
  let mapMarker = null;
  let currentMapLocation = null;
  let activeMediaObjectUrl = '';
  let activeJblSelectionPreviewId = '';
  let jblServerDraft = null;
  let jblServerDraftFarmerId = '';
  let jblDraftInputVersion = 0;
  let pendingJblDraftConflict = null;
  let pendingJblWorkflowConflict = null;
  let case360CounterCleanup = null;
  let jblMediaSelections = { LAF: [], JBL_VISIT_PHOTO: [] };
  let jblThumbnailQueue = Promise.resolve();
  let jblCameraStream = null;
  let jblCameraCategory = '';
  let jblCameraRequestId = 0;
  let workflowServerDraft = null;
  let workflowServerDraftKey = '';
  let workflowDraftInputVersion = 0;
  let voiceRecorder = null;
  let voiceStream = null;
  let voiceChunks = [];
  let voiceStartedAt = 0;
  let voiceStopTimer = null;
  let voiceReleaseTimer = null;
  let discardVoiceOnStop = false;
  let activeVoiceAttempt = null;
  const acceptedVoiceAttempts = {};
  const VOICE_LANGUAGE_KEY = 'portal:voice-language';
  const VOICE_LANGUAGE_ORDER = ['auto', 'en', 'sw'];
  const VOICE_LANGUAGE_LABELS = { auto: 'Auto', en: 'ENG', sw: 'KIS' };

  const MODE_WRITE_CAPABILITIES = {
    jbl_visit: 'portal.jbl_visit.write',
    credit: 'portal.credit.write',
    final_review: 'portal.final_review.write',
  };

  function el(id) { return deps.el(id); }
  function state() { return deps.state; }
  function hasCapability(capability) { return !capability || state().capabilities?.has(capability); }
  function canUpdateMode(mode, capability) {
    if (hasCapability(capability)) return true;
    const gateByMode = { credit: 'credit', final_review: 'final_review' };
    return Boolean(gateByMode[mode] && state().approvalDelegationGates?.includes(gateByMode[mode]));
  }
  function requestId() { return window.crypto?.randomUUID?.() || `portal-${Date.now()}-${Math.random().toString(16).slice(2)}`; }

  function savedVoiceLanguage() {
    try {
      const value = localStorage.getItem(VOICE_LANGUAGE_KEY) || 'auto';
      return VOICE_LANGUAGE_ORDER.includes(value) ? value : 'auto';
    } catch (_error) {
      return 'auto';
    }
  }

  function detectedLanguageLabel(language) {
    const value = String(language || '').trim().toLowerCase();
    if (value === 'en' || value.startsWith('english')) return 'English';
    if (value === 'sw' || value.startsWith('swahili') || value.startsWith('kiswahili')) return 'Kiswahili';
    return value ? humanLabel(value) : '';
  }

  function voiceWidget(fieldName, inputId) {
    if (!state().voiceInput?.enabled || !state().voiceInput?.fields?.includes(fieldName)) return '';
    const language = savedVoiceLanguage();
    return `<div class="voice-input" data-voice-field="${fieldName}" data-input-id="${inputId}" data-language-mode="${language}">
      <button type="button" class="voice-record-button" data-voice-action="record" aria-pressed="false" aria-label="Dictate comment" title="Dictate comment">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0M12 17v5M8 22h8"/></svg><span class="voice-record-label sr-only">Dictate</span><span class="voice-record-visible-label" aria-hidden="true">Voice Input</span>
      </button>
      <div class="voice-language-switch" role="group" aria-label="Recording language">
        ${VOICE_LANGUAGE_ORDER.map(mode => `<button type="button" class="voice-language-button${mode === language ? ' active' : ''}" data-voice-action="language" data-language-mode-value="${mode}" aria-pressed="${mode === language ? 'true' : 'false'}">${VOICE_LANGUAGE_LABELS[mode]}</button>`).join('')}
      </div>
      <small class="voice-status" aria-live="polite" hidden></small>
      <div class="voice-review" hidden>
        <div><p class="voice-transcript" aria-label="Transcription to review"></p><small class="voice-detected-language"></small></div>
        <div class="voice-review-actions" aria-label="Transcription actions">
          <button type="button" class="voice-action-button" data-voice-action="append" aria-label="Append transcription" title="Append"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg><span class="sr-only">Append</span></button>
          <button type="button" class="voice-action-button" data-voice-action="replace" aria-label="Replace field with transcription" title="Replace"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 7h-9a4 4 0 0 0-4 4v1M4 17h9a4 4 0 0 0 4-4v-1"/><path d="m17 4 3 3-3 3M7 14l-3 3 3 3"/></svg><span class="sr-only">Replace</span></button>
          <button type="button" class="voice-action-button" data-voice-action="retry" aria-label="Transcribe recording again" title="Retry"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/></svg><span class="sr-only">Retry</span></button>
          <button type="button" class="voice-action-button voice-action-cancel" data-voice-action="cancel" aria-label="Cancel transcription" title="Cancel"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg><span class="sr-only">Cancel</span></button>
        </div>
      </div>
    </div>`;
  }

  function voiceMimeType() {
    const candidates = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus'];
    return candidates.find(value => window.MediaRecorder?.isTypeSupported?.(value)) || '';
  }

  function setVoiceStatus(widget, message, stateName = '') {
    const status = widget?.querySelector('.voice-status');
    if (status) { status.textContent = message; status.dataset.state = stateName; status.hidden = !message; }
  }

  function releaseVoiceStream() {
    window.clearTimeout(voiceStopTimer);
    window.clearTimeout(voiceReleaseTimer);
    voiceStopTimer = null;
    voiceReleaseTimer = null;
    voiceStream?.getTracks?.().forEach(track => track.stop());
    voiceStream = null;
    voiceRecorder = null;
  }

  function parkVoiceStream() {
    window.clearTimeout(voiceStopTimer);
    window.clearTimeout(voiceReleaseTimer);
    voiceStopTimer = null;
    voiceRecorder = null;
    voiceStream?.getTracks?.().forEach(track => { track.enabled = false; });
    // Retain the current WebView grant only for quick corrections. The audio
    // track is disabled while parked and fully released after one minute.
    voiceReleaseTimer = window.setTimeout(releaseVoiceStream, 60000);
  }

  async function transcribeVoice(widget, blob, durationMs, retryAttemptId = '') {
    const farmer = state().selectedFarmer;
    if (!farmer) return;
    const key = requestId();
    const formData = new FormData();
    formData.set('client_request_id', key);
    formData.set('field_name', widget.dataset.voiceField);
    formData.set('duration_ms', String(Math.max(1, Math.round(durationMs))));
    formData.set('language_mode', widget.dataset.languageMode || 'auto');
    if (retryAttemptId) formData.set('retry_attempt_id', retryAttemptId);
    if (blob) formData.set('audio', blob, blob.type.includes('mp4') ? 'recording.m4a' : 'recording.webm');
    setVoiceStatus(widget, 'Transcribing...', 'loading');
    const button = widget.querySelector('[data-voice-action="record"]');
    if (button) button.disabled = true;
    try {
      const { ok, data } = await deps.portalApi.postForm(
        `/farmers/${encodeURIComponent(farmer.id)}/voice-transcriptions/`, formData, deps.tg,
        { 'X-CSRFToken': deps.getCookie('csrftoken') || '', 'X-Request-ID': key, 'Idempotency-Key': key },
      );
      if (!ok || !data?.text) throw new Error(data?.error || 'Transcription failed.');
      activeVoiceAttempt = {
        id: data.transcription_id, fieldName: widget.dataset.voiceField,
        inputId: widget.dataset.inputId, transcript: data.text,
        retryAvailable: Boolean(data.retry_available), durationMs,
        requestedLanguage: data.requested_language || widget.dataset.languageMode || 'auto',
        detectedLanguage: data.detected_language || '',
      };
      widget.querySelector('.voice-transcript').textContent = data.text;
      widget.querySelector('.voice-review').hidden = false;
      widget.querySelector('[data-voice-action="retry"]').disabled = !data.retry_available;
      const detected = detectedLanguageLabel(data.detected_language);
      const selected = activeVoiceAttempt.requestedLanguage;
      const detectedNode = widget.querySelector('.voice-detected-language');
      if (detectedNode) detectedNode.textContent = selected === 'auto'
        ? (detected ? `Auto detected: ${detected}` : 'Auto detection used')
        : `Recorded as ${selected === 'sw' ? 'Kiswahili' : 'English'}`;
      setVoiceStatus(widget, '', 'review');
    } catch (error) {
      setVoiceStatus(widget, error.message || 'Transcription is unavailable. Please type the comment.', 'error');
      if (retryAttemptId && activeVoiceAttempt?.id === retryAttemptId) {
        widget.querySelector('.voice-review').hidden = false;
      }
      deps.showToast(error.message || 'Transcription is unavailable. Please type the comment.', 'error');
    } finally {
      if (button) button.disabled = false;
    }
  }

  async function startVoiceRecording(widget) {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      setVoiceStatus(widget, 'Voice recording is unavailable on this phone. Use keyboard dictation or type.', 'error');
      return;
    }
    try {
      window.clearTimeout(voiceReleaseTimer);
      voiceReleaseTimer = null;
      const reusableStream = voiceStream?.getAudioTracks?.().some(track => track.readyState === 'live');
      if (!reusableStream) voiceStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      voiceStream.getTracks().forEach(track => { track.enabled = true; });
      const mimeType = voiceMimeType();
      voiceRecorder = mimeType ? new MediaRecorder(voiceStream, { mimeType }) : new MediaRecorder(voiceStream);
      discardVoiceOnStop = false;
      voiceChunks = [];
      voiceStartedAt = Date.now();
      voiceRecorder.addEventListener('dataavailable', event => { if (event.data?.size) voiceChunks.push(event.data); });
      voiceRecorder.addEventListener('stop', () => {
        const duration = Math.max(1, Date.now() - voiceStartedAt);
        const blob = new Blob(voiceChunks, { type: voiceRecorder?.mimeType || mimeType || 'audio/webm' });
        if (discardVoiceOnStop) {
          discardVoiceOnStop = false;
          releaseVoiceStream();
          return;
        }
        parkVoiceStream();
        transcribeVoice(widget, blob, duration);
      }, { once: true });
      voiceRecorder.start();
      const button = widget.querySelector('[data-voice-action="record"]');
      button?.setAttribute('aria-pressed', 'true');
      widget.querySelector('.voice-record-label').textContent = 'Stop recording';
      button?.setAttribute('aria-label', 'Stop recording');
      button?.setAttribute('title', 'Stop recording');
      widget.classList.add('recording');
      setVoiceStatus(widget, 'Recording... tap Stop when finished.', 'recording');
      voiceStopTimer = window.setTimeout(() => stopVoiceRecording(widget), Number(state().voiceInput.maxSeconds || 30) * 1000);
    } catch (_error) {
      releaseVoiceStream();
      setVoiceStatus(widget, 'Microphone unavailable. Allow Telegram microphone access in phone Settings, then reopen this Mini App.', 'error');
    }
  }

  function stopVoiceRecording(widget) {
    if (voiceRecorder?.state === 'recording') voiceRecorder.stop();
    const button = widget.querySelector('[data-voice-action="record"]');
    button?.setAttribute('aria-pressed', 'false');
    widget.querySelector('.voice-record-label').textContent = 'Dictate';
    button?.setAttribute('aria-label', 'Dictate comment');
    button?.setAttribute('title', 'Dictate comment');
    widget.classList.remove('recording');
  }

  async function cancelVoiceAttempt(attempt = activeVoiceAttempt) {
    if (!attempt?.id) return;
    const id = attempt.id;
    if (activeVoiceAttempt?.id === id) activeVoiceAttempt = null;
    try {
      await deps.apiFetch(`/voice-transcriptions/${encodeURIComponent(id)}/cancel/`, {
        method: 'POST', body: JSON.stringify({ request_id: requestId() }),
      });
    } catch (_error) {}
  }

  function wireVoiceWidget(fieldName) {
    const widget = document.querySelector(`.voice-input[data-voice-field="${fieldName}"]`);
    if (!widget) return;
    widget.addEventListener('click', event => {
      const action = event.target.closest('[data-voice-action]')?.dataset.voiceAction;
      if (!action) return;
      if (action === 'language') {
        const next = event.target.closest('[data-language-mode-value]')?.dataset.languageModeValue || 'auto';
        widget.dataset.languageMode = next;
        const label = VOICE_LANGUAGE_LABELS[next];
        widget.querySelectorAll('[data-language-mode-value]').forEach(button => {
          const selected = button.dataset.languageModeValue === next;
          button.classList.toggle('active', selected);
          button.setAttribute('aria-pressed', String(selected));
        });
        try { localStorage.setItem(VOICE_LANGUAGE_KEY, next); } catch (_error) {}
        setVoiceStatus(widget, '', 'language');
        deps.showToast(`${label} voice mode`, 'info');
        return;
      }
      if (action === 'record') {
        if (voiceRecorder?.state === 'recording') stopVoiceRecording(widget);
        else startVoiceRecording(widget);
        return;
      }
      const attempt = activeVoiceAttempt;
      if (!attempt || attempt.fieldName !== fieldName) return;
      if (action === 'retry') {
        widget.querySelector('.voice-review').hidden = true;
        transcribeVoice(widget, null, attempt.durationMs, attempt.id);
        return;
      }
      if (action === 'cancel') {
        widget.querySelector('.voice-review').hidden = true;
        setVoiceStatus(widget, 'Transcription cancelled. Your typed text is unchanged.', '');
        cancelVoiceAttempt(attempt);
        return;
      }
      const input = el(attempt.inputId);
      if (!input) return;
      input.value = action === 'append' && input.value.trim()
        ? `${input.value.trim()} ${attempt.transcript}`
        : attempt.transcript;
      const previousAcceptedId = acceptedVoiceAttempts[fieldName];
      if (previousAcceptedId && previousAcceptedId !== attempt.id) {
        cancelVoiceAttempt({ id: previousAcceptedId, fieldName });
      }
      acceptedVoiceAttempts[fieldName] = attempt.id;
      activeVoiceAttempt = null;
      widget.querySelector('.voice-review').hidden = true;
      setVoiceStatus(widget, 'Transcription inserted. Edit it if needed, then save the form.', 'accepted');
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.focus();
    });
  }

  function humanLabel(value) {
    return String(value || '').replace(/_/g, ' ').replace(/\b\w/g, char => char.toUpperCase());
  }

  function jblStatusLabel(farmer) {
    return farmer?.jbl_visit_date || farmer?.jbl_visit_status
      ? deps.fmt(farmer.jbl_visit_status || 'Visit logged')
      : 'Pending Visit';
  }

  function formatTatMinutes(value) {
    const number = Number(String(value ?? '').replace(/,/g, '').trim());
    if (!Number.isFinite(number)) return '';
    let minutes = Math.max(0, Math.round(number));
    const days = Math.floor(minutes / 1440);
    minutes %= 1440;
    const hours = Math.floor(minutes / 60);
    minutes %= 60;
    const parts = [];
    if (days) parts.push(`${days} day${days === 1 ? '' : 's'}`);
    if (hours) parts.push(`${hours} hr${hours === 1 ? '' : 's'}`);
    if (minutes || !parts.length) parts.push(`${minutes} min`);
    return parts.join(' + ');
  }

  const CASE_SECTION_META = {
    identity: ['Customer Identity', 'Core identifiers and contact details'],
    intake: ['Application & Intake', 'Origin, location, sales, and deposit information'],
    jbl_visit: ['JBL Visit', 'Field visit outcome and officer notes'],
    credit: ['Credit Analysis', 'Credit decision and IMAB preparation'],
    final_review: ['Final Review', 'Final decision and repayment terms'],
    order: ['Order', 'Requisition and product details'],
    invoice: ['Invoice & Balance', 'Confirmed invoice and payment amounts'],
  };

  function renderCaseFieldValue(key, value) {
    const text = value == null || value === '' ? '-' : String(value);
    // GPS links originate in imported/master data. Only turn an explicitly
    // absolute HTTP(S) URL into a link; everything else stays escaped text so
    // a malformed value cannot become executable markup.
    if (key === 'gps_link' && /^https?:\/\//i.test(text)) {
      const href = deps.escapeHtml(text);
      return `<a class="case360-link" href="${href}" target="_blank" rel="noopener">Open map ↗</a>`;
    }
    return deps.escapeHtml(text);
  }

  function renderBusinessSection(section, sectionName = '') {
    return `<div class="case360-grid">${Object.entries(section || {}).map(([key, value]) =>
      `<div class="case360-field ${['comment', 'payment_comment', 'gps_link'].includes(key) ? 'wide' : ''} ${value === null || value === '' ? 'empty' : ''}"><span>${deps.escapeHtml(sectionName === 'final_review' && key === 'comment' ? 'Order / requisition comment' : sectionName === 'final_review' && key === 'payment_comment' ? 'Payment comment (COL)' : humanLabel(key))}</span><strong>${renderCaseFieldValue(key, value)}</strong></div>`
    ).join('')}</div>`;
  }

  function caseStageFlow(sections, workflowState = '') {
    const steps = [
      ['Application', Boolean(sections.identity?.customer_name || sections.intake?.hbg_visit_date)],
      ['JBL Visit', Boolean(sections.jbl_visit?.visit_date || sections.jbl_visit?.status)],
      ['Credit', Boolean(sections.credit?.decision)],
      ['Final Review', Boolean(sections.final_review?.decision)],
      ['Order', Boolean(sections.order?.order_number)],
      ['Invoice', Boolean(sections.invoice?.number)],
    ];
    const stateIndex = {
      jbl_visit: 1,
      credit: 2,
      final_review: 3,
      order: 4,
      ordered: 5,
    };
    // The workflow state is canonical. The older field-presence fallback is
    // retained for records created before state integrity existed.
    const current = Object.prototype.hasOwnProperty.call(stateIndex, workflowState)
      ? stateIndex[workflowState]
      : steps.findIndex(([, complete]) => !complete);
    return `<ol class="case360-flow" aria-label="Case progress">${steps.map(([label, complete], index) => {
      const status = index < current ? 'complete' : index === current ? 'current' : 'pending';
      // A historical value can remain populated after a case is returned to
      // JBL. Render from canonical step status, not the stale value itself.
      const icon = status === 'complete'
        ? '<svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>'
        : status === 'current'
          ? '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>'
          : '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 018 0v3"/></svg>';
      return `<li class="${status}"><span>${icon}</span><small>${deps.escapeHtml(label)}</small></li>`;
    }).join('')}</ol>`;
  }

  function caseHeader(sections, workflowState = '') {
    const identity = sections.identity || {};
    const intake = sections.intake || {};
    const systemName = identity.system_name && identity.system_name !== identity.customer_name
      ? `IMAB: ${identity.system_name}`
      : '';
    const status = sections.invoice?.number ? 'Invoiced'
      : sections.order?.order_number ? 'Ordered'
      : sections.final_review?.decision || sections.credit?.decision || sections.jbl_visit?.status || 'Application received';
    return `<header class="case360-hero">
      <div class="case360-identity"><span class="case360-eyebrow">Customer case</span><h2>${deps.escapeHtml(identity.customer_name || 'Unnamed customer')}</h2><p>${deps.escapeHtml([systemName, identity.national_id && `ID ${identity.national_id}`, identity.primary_phone, intake.branch].filter(Boolean).join('  |  ') || 'Identifiers not recorded')}</p></div>
      <span class="case360-status">${deps.escapeHtml(status)}</span>
    </header>${caseStageFlow(sections, workflowState)}`;
  }

  function caseTatCounter(record, key) {
    const elapsed = Number(record?.elapsed_seconds);
    if (!Number.isFinite(elapsed)) return '-';
    const label = window.MiniAppRuntime?.formatElapsedSeconds?.(elapsed) || formatTatMinutes(elapsed / 60);
    return `<span class="live-tat-counter" data-server-counter data-case360-counter="${deps.escapeHtml(key)}" data-elapsed-seconds="${elapsed}" data-calculated-at="${deps.escapeHtml(record.calculated_at || '')}" data-running="${record.running ? 'true' : 'false'}" data-target-seconds="${record.target_seconds == null ? '' : deps.escapeHtml(record.target_seconds)}">${deps.escapeHtml(label)}</span>`;
  }

  function updateCase360Counter(node, elapsed) {
    const target = Number(node.dataset.targetSeconds);
    const badge = node.closest('.case360-tat-row, .case360-tat-total')?.querySelector('.case360-sla');
    if (!badge || !Number.isFinite(target) || target <= 0) return;
    const status = elapsed > target ? 'over' : elapsed >= target * 0.8 ? 'near' : 'within';
    badge.classList.remove('within', 'near', 'over');
    badge.classList.add(status);
    badge.textContent = humanLabel(status);
  }

  function caseDocumentKind(item) {
    const mime = String(item?.mime_type || '').toLowerCase();
    if (mime.includes('pdf')) return 'PDF';
    if (mime.startsWith('image/')) return 'IMG';
    if (mime.includes('spreadsheet') || mime.includes('excel')) return 'XLSX';
    return 'DOC';
  }

  function renderCaseDocumentList(items, target) {
    if (!target) return;
    target._caseDocuments = items;
    target.innerHTML = items.length ? items.map((item, index) => `
      <article class="case360-document">
        <span>${deps.escapeHtml(caseDocumentKind(item))}</span>
        <strong title="${deps.escapeHtml(item.name || 'Document')}">${deps.escapeHtml(item.name || 'Document')}</strong>
        <div class="case360-document-actions">
          ${item.preview_url ? `<button type="button" class="media-link case360-document-preview" data-document-index="${index}">View in app</button>` : ''}
          ${item.open_url ? `<button type="button" class="media-link case360-document-open" data-document-index="${index}">Open externally</button>` : ''}
        </div>
      </article>`).join('') : '<div class="empty-state">No linked documents.</div>';
    target.querySelectorAll('.case360-document-preview').forEach(button => button.addEventListener('click', () => {
      const item = items[Number(button.dataset.documentIndex)];
      if (item) openClientMediaPreview(item);
    }));
    target.querySelectorAll('.case360-document-open').forEach(button => button.addEventListener('click', async () => {
      const item = items[Number(button.dataset.documentIndex)];
      if (!item) return;
      if (item.kind === 'visit_media') openClientMediaExternally(item, target, button);
      else if (item.prepare_external) {
        const label = button.textContent;
        button.disabled = true;
        button.textContent = 'Preparing...';
        try {
          const result = await deps.apiFetch(item.open_url);
          if (!result.ok || !result.data?.open_url) throw new Error(result.data?.error || 'Could not prepare this document.');
          deps.openPortalLink(result.data.open_url);
        } catch (error) {
          deps.showToast(error.message || 'Could not open this document externally.', 'error');
        } finally {
          button.disabled = false;
          button.textContent = label;
        }
      } else deps.openPortalLink(item.open_url);
    }));
  }

  async function loadCase360Documents(documents, target) {
    if (!target || target.dataset.loaded === 'true') return;
    const farmerId = String(documents?.farmer_id || state().selectedFarmer?.id || '');
    const retained = Array.isArray(documents?.items) ? documents.items : [];
    target.dataset.farmerId = farmerId;
    if (!farmerId) {
      renderCaseDocumentList(retained, target);
      return;
    }
    target.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div> Loading secure evidence...</div>';
    try {
      const result = await deps.apiFetch('/jbl-queue/' + encodeURIComponent(farmerId) + '/media/list/');
      if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Could not load visit evidence.');
      const visitMedia = (result.data.media || []).map(item => ({ ...item, kind: 'visit_media' }));
      target.dataset.loaded = 'true';
      renderCaseDocumentList([...visitMedia, ...retained], target);
    } catch (error) {
      renderCaseDocumentList(retained, target);
      const warning = document.createElement('div');
      warning.className = 'batch-warning';
      warning.textContent = error.message || 'Visit evidence could not be loaded. Retry by reopening Documents.';
      target.prepend(warning);
    }
  }

  function renderCase360(data, target) {
    const root = target || el('case360');
    if (!root || !data) return;
    const sections = data.sections || {};
    const timeline = data.timeline || [];
    const tat = data.tat || {};
    const escalation = data.escalation || null;
    const relatedCases = data.related_cases || [];
    const householdRelationships = data.household_relationships || [];
    const invoiceNameChanges = data.invoice_name_changes || [];
    const documents = data.documents || {};
    const validation = data.validation || [];
    const stageRows = (tat.stages || []).map((stage, index) => `<article class="case360-tat-row"><span class="case360-stage-number">${index + 1}</span><div><strong>${deps.escapeHtml(stage.label)}</strong><small>${stage.completed_at ? 'Completed' : stage.started_at ? 'In progress' : 'Not tracked'}</small></div><div><strong>${caseTatCounter(stage, `stage-${index}`)}</strong><span class="case360-sla ${deps.escapeHtml(stage.status || '')}">${deps.escapeHtml(humanLabel(stage.status || ''))}</span></div></article>`).join('');
    const docLinks = Array.isArray(documents.items) ? documents.items : [
      documents.requisition,
      documents.invoice,
      ...(documents.payments || []),
    ].filter(Boolean).map(item => ({ ...item, open_url: item.open_url || item.url || '' }));
    const tabs = [
      ['overview', 'Overview', ''],
      ['timeline', 'Timeline', timeline.length],
      ['tat', 'TAT', (tat.stages || []).length],
      ['documents', 'Documents', docLinks.length + Number(documents.visit_media_count || (documents.visit_media || []).length || 0)],
      ['quality', 'Data Quality', validation.length],
    ];
    const sectionCards = Object.entries(sections).map(([name, values]) => {
      const meta = CASE_SECTION_META[name] || [humanLabel(name), ''];
      return `<details class="case360-section"><summary><div><h3>${deps.escapeHtml(meta[0])}</h3><p>${deps.escapeHtml(meta[1])}</p></div><span class="case360-chevron" aria-hidden="true"></span></summary>${renderBusinessSection(values, name)}</details>`;
    }).join('');
    const relatedCaseCards = relatedCases.length ? `<details class="case360-section"><summary><div><h3>Other Units</h3><p>Prior or repeat-customer applications</p></div><span class="case360-chevron" aria-hidden="true"></span></summary><div class="case360-related-cases">${relatedCases.map(item => `<button type="button" class="case360-related-case" data-related-farmer="${deps.escapeHtml(item.id)}"><strong>Unit ${deps.escapeHtml(item.unit_number)}</strong><span>${deps.escapeHtml(item.customer_name || 'Customer')} · ${deps.escapeHtml(humanLabel(item.status || ''))}</span></button>`).join('')}</div></details>` : '';
    const householdCards = householdRelationships.length ? `<details class="case360-section"><summary><div><h3>Confirmed Household</h3><p>Distinct people linked with Operations evidence</p></div><span class="case360-chevron" aria-hidden="true"></span></summary><div class="case360-related-cases">${householdRelationships.map(item => `<div class="case360-related-case"><strong>${deps.escapeHtml(item.name || 'Household member')}</strong><span>${deps.escapeHtml(humanLabel(item.relationship_type || ''))} · ID ${deps.escapeHtml(item.national_id || '-')} · ${deps.escapeHtml(humanLabel(item.status || ''))}</span></div>`).join('')}</div></details>` : '';
    const invoiceChangeCards = invoiceNameChanges.length ? `<details class="case360-section"><summary><div><h3>Invoice Name Changes</h3><p>Original and corrected invoice history</p></div><span class="case360-chevron" aria-hidden="true"></span></summary><div class="case360-related-cases">${invoiceNameChanges.map(item => `<div class="case360-related-case"><strong>${deps.escapeHtml(item.original_invoice || '-')} → ${deps.escapeHtml(item.replacement_invoice || 'Awaiting replacement')}</strong><span>${deps.escapeHtml(humanLabel(item.status || ''))} · ${deps.escapeHtml(item.batch_reference || '')}</span></div>`).join('')}</div></details>` : '';
    const escalationAlert = escalation ? `<div class="case360-escalation level-${deps.escapeHtml(escalation.escalation_level)}"><strong>SLA escalation: ${deps.escapeHtml(escalation.routing_role)}</strong><span>${deps.escapeHtml(formatTatMinutes(escalation.overdue_minutes))} overdue at ${deps.escapeHtml(escalation.threshold_percent)}% threshold</span></div>` : '';
    root.innerHTML = `
      ${caseHeader(sections, data.workflow_state || '')}
      <div class="case360-tabs" role="tablist">
        ${tabs.map(([key, label, count], index) => `<button type="button" role="tab" aria-selected="${index ? 'false' : 'true'}" data-case360-tab="${key}" class="${index ? '' : 'active'}"><span>${label}</span>${count !== '' ? `<b>${count}</b>` : ''}</button>`).join('')}
      </div>
      <section class="case360-panel" role="tabpanel" data-case360-panel="overview">${escalationAlert}<div class="case360-sections">${sectionCards}${householdCards}${invoiceChangeCards}${relatedCaseCards}</div></section>
      <section class="case360-panel" role="tabpanel" data-case360-panel="timeline" hidden>
        <div class="case360-panel-heading"><div><h3>Case Timeline</h3><p>Recorded actions in chronological order</p></div><strong>${timeline.length} events</strong></div>
        ${timeline.length ? `<div class="case360-timeline">${timeline.map(event => `<article class="${event.redacted ? 'redacted' : ''}"><time>${deps.escapeHtml(deps.fmtDate(event.occurred_at))}</time><div><strong>${deps.escapeHtml(event.title || humanLabel(event.action))}</strong><small>${deps.escapeHtml([event.actor, event.authority && `Authority: ${event.authority}`, event.stage, humanLabel(event.origin || event.source)].filter(Boolean).join(' · ') || 'System')}</small>${event.detail ? `<p>${deps.escapeHtml(event.detail)}</p>` : ''}${event.artifact?.url ? `<a class="case360-link" href="${deps.escapeHtml(event.artifact.url)}" target="_blank" rel="noopener">${deps.escapeHtml(event.artifact.name || 'Open linked document')} ↗</a>` : ''}</div></article>`).join('')}</div>` : '<div class="empty-state">No exact events recorded yet.</div>'}
      </section>
      <section class="case360-panel" role="tabpanel" data-case360-panel="tat" hidden>
        <div class="case360-panel-heading"><div><h3>Turnaround Time</h3><p>Time spent at each tracked workflow stage</p></div></div>
        ${tat.historical_timestamps_available ? '' : '<div class="batch-warning">Historical stage timestamps were not inferred. TAT begins with exact events recorded after tracking was enabled.</div>'}
        <div class="case360-tat-total"><div><span>Official TAT (wall clock)</span><strong>${caseTatCounter(tat, 'overall')}</strong></div><span class="case360-sla ${deps.escapeHtml(tat.status || '')}">${deps.escapeHtml(humanLabel(tat.status || ''))}</span></div><div class="case360-tat-list">${stageRows}</div>
      </section>
      <section class="case360-panel" role="tabpanel" data-case360-panel="documents" hidden><div class="case360-panel-heading"><div><h3>Case Documents</h3><p>View supported evidence without leaving Portal, or open a file in its external app.</p></div></div><div class="case360-documents" data-case360-documents></div></section>
      <section class="case360-panel" role="tabpanel" data-case360-panel="quality" hidden><div class="case360-panel-heading"><div><h3>Data Quality</h3><p>Validation checks requiring staff attention</p></div></div>${validation.length ? `<div class="case360-quality-list">${validation.map(issue => `<article><span>!</span><div><strong>${deps.escapeHtml(humanLabel(issue.field))}</strong><p>${deps.escapeHtml(issue.message)}</p></div></article>`).join('')}</div>` : '<div class="case360-valid"><strong>All checks passed</strong><span>All monitored business fields are valid.</span></div>'}</section>`;
    root.hidden = false;
    renderCaseDocumentList(docLinks, root.querySelector('[data-case360-documents]'));
    if (case360CounterCleanup) case360CounterCleanup();
    case360CounterCleanup = window.MiniAppRuntime?.bindServerCounters?.(root, {
      selector: '[data-server-counter]',
      onTick: updateCase360Counter,
    }) || null;
    root.querySelectorAll('[data-case360-tab]').forEach(button => button.addEventListener('click', () => {
      root.querySelectorAll('[data-case360-tab]').forEach(item => {
        item.classList.toggle('active', item === button);
        item.setAttribute('aria-selected', String(item === button));
      });
      root.querySelectorAll('[data-case360-panel]').forEach(panel => { panel.hidden = panel.dataset.case360Panel !== button.dataset.case360Tab; });
      if (button.dataset.case360Tab === 'documents') {
        loadCase360Documents(documents, root.querySelector('[data-case360-documents]'));
      }
    }));
    root.querySelectorAll('[data-related-farmer]').forEach(button => button.addEventListener('click', () => {
      window.location.assign('/portal/cases/' + encodeURIComponent(button.dataset.relatedFarmer) + '/');
    }));
  }

  async function loadCase360(farmer) {
    const root = el('case360');
    if (!root) return;
    root.hidden = false;
    root.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div></div>';
    if (farmer.case360) return renderCase360(farmer.case360);
    try {
      const response = await deps.apiFetch('/farmers/' + farmer.id + '/');
      if (!response.ok || !response.data?.ok) throw new Error(response.data?.error || 'Could not load Case 360.');
      renderCase360(response.data.case360);
    } catch (error) {
      root.innerHTML = `<div class="batch-warning">${deps.escapeHtml(error.message || 'Could not load Case 360.')}</div>`;
    }
  }

  function summaryFields(farmer, mode) {
    const common = [
      ['National ID', deps.fmt(farmer.national_id)],
      ['Phone', deps.fmt(farmer.primary_phone)],
    ];
    const byMode = {
      jbl_visit: [
        ['HBG Visit Date', deps.fmtDate(farmer.hbg_visit_date || farmer.sign_date)],
        ['HB Sales Person', deps.fmt(farmer.hb_sales_person)],
        ['JBL Status', jblStatusLabel(farmer)],
      ],
      credit: [
        ['JBL Visit', deps.fmtDate(farmer.jbl_visit_date)],
        ['JBL Officer', deps.fmt(farmer.jbl_officer)],
        ['JBL Status', jblStatusLabel(farmer)],
        ['Customer No.', deps.fmt(farmer.customer_no)],
      ],
      final_review: [
        ['Credit Decision', deps.fmt(farmer.credit_decision)],
        ['IMAB Created', deps.fmt(farmer.imab_created)],
        ['Customer No.', deps.fmt(farmer.customer_no)],
      ],
      requisition: [
        ['Final Decision', deps.fmt(farmer.final_decision)],
        ['Customer No.', deps.fmt(farmer.customer_no)],
        ['Current Order No.', deps.fmt(farmer.order_number)],
      ],
    };
    return common.concat(byMode[mode] || []);
  }

  function openFarmerSheet(farmer, mode) {
    state().selectedFarmer = farmer;
    state().activeMode = mode;
    activeVoiceAttempt = null;
    Object.keys(acceptedVoiceAttempts).forEach(key => delete acceptedVoiceAttempts[key]);

    const sheetOverlay = el('sheet-overlay');
    sheetOverlay?.classList.toggle('jbl-visit-sheet', mode === 'jbl_visit');
    sheetOverlay?.classList.toggle('credit-analysis-sheet', mode === 'credit');
    el('sheet-name').textContent = farmer.customer_name || 'Unknown Farmer';
    const location = deps.locationText(farmer);
    el('sheet-sub').textContent = location !== '-' ? location : (farmer.primary_phone || '');

    const infoFields = summaryFields(farmer, mode);

    const mediaCount = Number(farmer.jbl_media_count || 0);
    el('sheet-info').innerHTML = infoFields.map(([label, value]) => {
      const isJblStatus = label === 'JBL Status' && ['jbl_visit', 'credit'].includes(mode);
      const statusClass = mode === 'jbl_visit' && isJblStatus ? ' info-row-status' : isJblStatus ? ' info-row-credit-status' : '';
      return `<li class="info-row${statusClass}"><span class="ir-label">${deps.escapeHtml(label)}</span><span class="ir-value">${isJblStatus ? `<span class="visit-status-pill">${value}</span>` : value}</span></li>`;
    }).join('');
    const mediaSection = el('sheet-client-media');
    if (mediaSection) {
      const canViewMedia = hasCapability('portal.jbl_media.view') && mediaCount >= 1;
      document.querySelector('.sheet-quick-actions')?.classList.toggle('has-client-media', canViewMedia);
      mediaSection.hidden = !canViewMedia;
      mediaSection.innerHTML = canViewMedia
        ? `<button type="button" class="btn btn-secondary sheet-client-media-toggle" id="btn-view-client-media" aria-expanded="false" data-collapsed-label="View ${mediaCount} media file${mediaCount === 1 ? '' : 's'}"><i data-lucide="image" aria-hidden="true"></i><span class="sheet-action-label">View ${mediaCount} media file${mediaCount === 1 ? '' : 's'}</span></button><div id="final-client-media" class="media-links client-media-links" hidden></div>`
        : '';
      el('btn-view-client-media')?.addEventListener('click', () => toggleClientMedia(farmer.id));
    }
    const caseToggle = el('case360-toggle');
    caseToggle.innerHTML = '<i data-lucide="history" aria-hidden="true"></i><span>Open Case History</span>';
    caseToggle.onclick = () => {
      window.PortalAppShell?.openCaseHistory(farmer.id);
    };

    const formEl = el('sheet-form');
    const footerEl = el('sheet-footer');
    formEl.oninput = null;
    formEl.onchange = null;
    formEl.innerHTML = '';
    footerEl.innerHTML = '';
    el('sheet-gate-warning').style.display = 'none';

    const writeCapability = MODE_WRITE_CAPABILITIES[mode];
    if (writeCapability && !canUpdateMode(mode, writeCapability)) {
      formEl.innerHTML = '<div class="field-help">Your role can view this case but is not assigned to update this workflow stage.</div>';
    } else if (mode === 'jbl_visit') {
      stopJblLiveCamera();
      resetJblMediaSelections();
      formEl.innerHTML = buildJblForm(farmer);
      footerEl.innerHTML = '<button class="primary" id="btn-submit-jbl">Log JBL Visit</button>';
      el('btn-submit-jbl').addEventListener('click', submitJblVisit);
      wireJblDateInput();
      wireGpsButton();
      wireJblVisitDraft(farmer);
      wireJblLocationFields(farmer);
      wireVoiceWidget('jbl_visit_comment');
      sessionStorage.setItem(JBL_ACTIVE_DRAFT_KEY, farmer.id);
    } else if (mode === 'credit') {
      formEl.innerHTML = buildCreditForm(farmer);
      footerEl.innerHTML = '<button class="primary" id="btn-submit-credit">Set Credit Decision</button>';
      el('btn-submit-credit').addEventListener('click', submitCreditDecision);
      wireCreditImabFields();
      wireWorkflowDraft(farmer, mode);
      wireVoiceWidget('final_decision_comment');
    } else if (mode === 'final_review') {
      formEl.innerHTML = buildFinalReviewForm(farmer);
      footerEl.innerHTML = '<button class="primary" id="btn-submit-final">Save Final Review</button>';
      el('btn-submit-final').addEventListener('click', submitFinalDecision);
      wireWorkflowDraft(farmer, mode);
    } else if (mode === 'requisition') {
      formEl.innerHTML = buildRequisitionBatchNotice();
    }
    sheetOverlay?.classList.add('open');
    const lat = parseFloat(farmer.latitude);
    const lng = parseFloat(farmer.longitude);
    // Leaflet measures its container when it is created. The sheet is hidden
    // until this point, so initialize after opening and invalidate on the next
    // frame to avoid intermittent blank maps in Telegram WebView.
    if (!isNaN(lat) && !isNaN(lng)) {
      window.requestAnimationFrame(() => {
        if (el('sheet-overlay')?.classList.contains('open')) initMap(lat, lng);
      });
    } else {
      destroyMap();
    }
    if (window.lucide) window.lucide.createIcons();
  }

  function initMap(lat, lng) {
    const mapContainer = el('sheet-map-container');
    if (!mapContainer) return;
    currentMapLocation = { lat, lng };
    mapContainer.style.display = 'block';
    const mapLink = el('sheet-map-link');
    const mapMeta = el('sheet-map-meta');
    if (mapMeta) mapMeta.textContent = `GPS: ${lat.toFixed(6)}, ${lng.toFixed(6)}`;
    if (mapLink) {
      mapLink.href = `https://www.google.com/maps?q=${encodeURIComponent(`${lat},${lng}`)}`;
      mapLink.hidden = false;
    }
    if (!window.L) {
      const fallback = el('sheet-map-fallback');
      if (fallback) fallback.hidden = false;
      return;
    }

    const isDark = (window.Telegram?.WebApp?.colorScheme === 'dark') ||
      (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
    const tileUrl = isDark
      ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
      : 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png';
    const attribution = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>';
    const showMapFallback = () => {
      const fallback = el('sheet-map-fallback');
      if (fallback) fallback.hidden = false;
    };

    if (!mapInstance) {
      mapInstance = L.map('sheet-map', { zoomControl: true, attributionControl: true }).setView([lat, lng], 15);
      const tiles = L.tileLayer(tileUrl, { attribution, maxZoom: 20 }).addTo(mapInstance);
      tiles.on('tileerror', showMapFallback);
      mapMarker = L.marker([lat, lng]).addTo(mapInstance).bindPopup(`Recorded location<br><small>${lat.toFixed(6)}, ${lng.toFixed(6)}</small>`);
    } else {
      mapInstance.setView([lat, lng], 15);
      mapInstance.eachLayer(layer => {
        if (layer instanceof L.TileLayer) layer.setUrl(tileUrl);
      });
      if (mapMarker) mapMarker.setLatLng([lat, lng]);
      else mapMarker = L.marker([lat, lng]).addTo(mapInstance);
      mapMarker.bindPopup(`Recorded location<br><small>${lat.toFixed(6)}, ${lng.toFixed(6)}</small>`);
    }

    setTimeout(() => {
      if (mapInstance) mapInstance.invalidateSize();
    }, 100);
    window.requestAnimationFrame(() => mapInstance?.invalidateSize());
  }

  function destroyMap() {
    const mapContainer = el('sheet-map-container');
    if (mapContainer) mapContainer.style.display = 'none';
    const mapLink = el('sheet-map-link');
    if (mapLink) mapLink.hidden = true;
    const fallback = el('sheet-map-fallback');
    if (fallback) fallback.hidden = true;
    currentMapLocation = null;
  }

  function refreshMap() {
    if (!currentMapLocation) return;
    const { lat, lng } = currentMapLocation;
    const fallback = el('sheet-map-fallback');
    if (fallback) fallback.hidden = true;
    if (mapInstance) {
      mapInstance.invalidateSize(true);
      mapInstance.setView([lat, lng], 15);
      mapInstance.eachLayer(layer => {
        if (layer instanceof window.L.TileLayer) layer.redraw();
      });
    } else {
      initMap(lat, lng);
    }
  }

  function localIsoDate() {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const day = String(now.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  function displayDateFromIso(value) {
    const match = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})$/);
    return match ? `${match[3]}-${match[2]}-${match[1].slice(-2)}` : '';
  }

  function isoDateFromDisplay(value) {
    const match = String(value || '').trim().match(/^(\d{2})-(\d{2})-(\d{2}|\d{4})$/);
    if (!match) return '';
    const year = match[3].length === 2 ? `20${match[3]}` : match[3];
    const iso = `${year}-${match[2]}-${match[1]}`;
    const parsed = new Date(Number(year), Number(match[2]) - 1, Number(match[1]));
    if (
      Number.isNaN(parsed.getTime())
      || parsed.getFullYear() !== Number(year)
      || parsed.getMonth() + 1 !== Number(match[2])
      || parsed.getDate() !== Number(match[1])
    ) return '';
    return iso;
  }

  function syncJblDateControls(isoValue) {
    const iso = String(isoValue || '');
    const value = el('jbl-date');
    const display = el('jbl-date-display');
    const picker = el('jbl-date-picker');
    if (value) value.value = iso;
    if (picker) picker.value = iso;
    if (display) display.value = displayDateFromIso(iso);
  }

  function commitJblDisplayDate({ showError = false } = {}) {
    const display = el('jbl-date-display');
    const value = el('jbl-date');
    if (!display || !value) return false;
    const iso = isoDateFromDisplay(display.value);
    const minimum = el('jbl-date-picker')?.min || '';
    const maximum = el('jbl-date-picker')?.max || '';
    if (!iso || (minimum && iso < minimum) || (maximum && iso > maximum)) {
      if (showError) {
        const range = minimum
          ? `${displayDateFromIso(minimum)} to ${displayDateFromIso(maximum)}`
          : `on or before ${displayDateFromIso(maximum)}`;
        deps.showToast(`Enter the visit date as dd-mm-yy within ${range}.`, 'error');
        display.focus();
      }
      return false;
    }
    syncJblDateControls(iso);
    return true;
  }

  function calendarIcon() {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>';
  }

  function wireJblDateInput() {
    const display = el('jbl-date-display');
    const picker = el('jbl-date-picker');
    const open = el('jbl-date-open');
    if (!display || !picker || !open) return;
    display.addEventListener('input', () => {
      if (isoDateFromDisplay(display.value)) commitJblDisplayDate();
    });
    // Keep entry interruption-free. Full date validation and visible errors
    // belong to the explicit Log JBL Visit submission path.
    display.addEventListener('blur', () => commitJblDisplayDate({ showError: false }));
    picker.addEventListener('change', () => {
      if (picker.value) syncJblDateControls(picker.value);
    });
    open.addEventListener('click', () => {
      try {
        if (typeof picker.showPicker === 'function') picker.showPicker();
        else picker.click();
      } catch (_error) {
        picker.click();
      }
    });
  }

  function buildJblForm(farmer) {
    const today = state().businessDate || localIsoDate();
    const hbgVisitDate = farmer.hbg_visit_date || '';
    const defaultVisitDate = farmer.jbl_visit_date || today;
    const statusOptions = state().metaStatuses.filter(status => status !== 'JBL to Schedule Visit').map(status =>
      `<option value="${deps.escapeHtml(status)}"${farmer.jbl_visit_status === status ? ' selected' : ''}>${deps.escapeHtml(status)}</option>`
    ).join('');
    const catalogCounties = state().metaLocationCatalog?.counties || (state().metaCounties || []).map(name => ({ code: name, name }));
    const selectedCounty = String(farmer.county_ref_code || farmer.county || '').toLowerCase();
    const countyOptions = catalogCounties.map(county =>
      `<option value="${deps.escapeHtml(county.code)}"${[county.code, county.name].map(value => String(value || '').toLowerCase()).includes(selectedCounty) ? ' selected' : ''}>${deps.escapeHtml(county.name)}</option>`
    ).join('');
    const legacySubCounty = farmer.sub_county
      ? `<option value="${deps.escapeHtml(farmer.sub_county)}" selected>${deps.escapeHtml(farmer.sub_county)}</option>`
      : '';
    const mediaFields = hasCapability('portal.jbl_media.write') ? `
        <div class="form-row media-upload-row form-row-wide">
          <label>Visit Media</label>
          <div class="media-upload-control">
            ${jblMediaCategoryMarkup({
              category: 'LAF', title: 'LAF document(s)', help: 'PDF, JPG or PNG.',
              pickerId: 'jbl-laf-media', cameraId: 'jbl-laf-camera',
              accept: 'application/pdf,.pdf,image/jpeg,image/png,.jpg,.jpeg,.png',
            })}
            ${jblMediaCategoryMarkup({
              category: 'JBL_VISIT_PHOTO', title: 'JBL visit photo(s)', help: 'Images only.',
              pickerId: 'jbl-visit-photo-media', cameraId: 'jbl-visit-photo-camera',
              accept: 'image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp',
            })}
            ${jblLiveCameraMarkup()}
            <small class="form-row-wide jbl-media-limit-help">Up to ${Number(state().jblVisitMediaMaxFiles || 6)} files and ${Math.round(Number(state().jblVisitMediaMaxTotalBytes || 40 * 1024 * 1024) / (1024 * 1024))} MB combined. Tap a selected item to review it full-size.</small>
            ${farmer.jbl_media_count ? `<small class="form-row-wide">${farmer.jbl_media_count} existing Drive link${farmer.jbl_media_count === 1 ? '' : 's'} on this record.</small>` : ''}
          </div>
        </div>` : '';
    return `
      <section id="jbl-form-errors" class="jbl-form-errors" role="alert" tabindex="-1" hidden><strong>Correct the following before logging the visit:</strong><ul></ul></section>
      <section id="jbl-workflow-conflict" class="jbl-workflow-conflict" role="alert" tabindex="-1" hidden><strong>This case changed since you opened it.</strong><p id="jbl-workflow-conflict-message"></p><p>Your draft and selected files are still here. Review the latest case before retrying.</p><button type="button" id="jbl-review-latest">Review latest case and keep my draft</button></section>
      <section id="jbl-draft-conflict" class="jbl-workflow-conflict" role="alert" tabindex="-1" hidden><strong>This draft changed on another device.</strong><p>Choose which field-only draft to continue with. Files are never included.</p><div class="jbl-conflict-actions"><button type="button" id="jbl-use-local-draft">Use this device</button><button type="button" id="jbl-use-server-draft">Use saved draft</button></div></section>
      <div class="form-section form-grid">
        <div class="form-row" data-jbl-field="visit_date"><label title="JBL visits follow the HBG visit and cannot be future-dated.">Visit Date <span class="required-marker" aria-hidden="true">*</span><span class="sr-only"> required</span></label><div class="jbl-date-control"><input type="text" id="jbl-date-display" inputmode="numeric" autocomplete="off" maxlength="10" placeholder="dd-mm-yy" aria-describedby="jbl-date-help" aria-required="true" value="${deps.escapeHtml(displayDateFromIso(defaultVisitDate))}"><button type="button" id="jbl-date-open" class="jbl-date-open" aria-label="Open native visit date picker" title="Choose visit date">${calendarIcon()}</button><input type="date" id="jbl-date-picker" class="native-date-proxy" min="${deps.escapeHtml(hbgVisitDate)}" max="${deps.escapeHtml(today)}" value="${deps.escapeHtml(defaultVisitDate)}" tabindex="-1" aria-hidden="true"><input type="hidden" id="jbl-date" value="${deps.escapeHtml(defaultVisitDate)}"></div><small id="jbl-date-help" class="field-help">Use dd-mm-yy. Earliest: ${deps.escapeHtml(displayDateFromIso(hbgVisitDate) || 'recorded HBG visit')}; latest: ${deps.escapeHtml(displayDateFromIso(today))}.</small><small class="jbl-field-error" data-error-message-for="visit_date"></small></div>
        <div class="form-row" data-jbl-field="visit_status"><label>Status / Outcome <span class="required-marker" aria-hidden="true">*</span><span class="sr-only"> required</span></label><select id="jbl-status" aria-required="true"><option value="">- Select -</option>${statusOptions}</select><small class="jbl-field-error" data-error-message-for="visit_status"></small></div>
        <div class="form-row"><label>Officer Name</label><input type="text" id="jbl-officer" placeholder="Uses your staff identity when blank" value="${deps.escapeHtml(farmer.jbl_officer || '')}"></div>
        <div class="form-row" data-jbl-field="county"><label>County</label><select id="jbl-county"><option value="">- Select county -</option>${countyOptions}</select><small class="jbl-field-error" data-error-message-for="county"></small></div>
        <div class="form-row" data-jbl-field="sub_county"><label>Sub-county</label><select id="jbl-sub-county"><option value="">- Select sub-county -</option>${legacySubCounty}</select><small class="jbl-field-error" data-error-message-for="sub_county"></small></div>
        <div class="form-row"><label>Village</label><input type="text" id="jbl-village" placeholder="Village / area" value="${deps.escapeHtml(farmer.village || '')}"></div>
        <div class="form-row form-row-wide"><label>Comment</label><textarea id="jbl-comment" rows="2" placeholder="Additional notes...">${deps.escapeHtml(farmer.jbl_visit_comment || '')}</textarea>${voiceWidget('jbl_visit_comment', 'jbl-comment')}</div>
        ${mediaFields}
        <div class="form-row form-row-wide gps-capture-row" data-jbl-field="capture_location">
          <button type="button" id="btn-gps" class="secondary"><i data-lucide="map-pin" aria-hidden="true"></i><span>Capture GPS Location</span></button>
          <div id="gps-coords" class="field-help">Not captured</div>
          <input type="hidden" id="jbl-lat" value="">
          <input type="hidden" id="jbl-lng" value="">
          <div id="jbl-location-unavailable-wrap" hidden>
            <label class="field-help" for="jbl-location-unavailable">GPS could not be captured. Explain why before forwarding.</label>
            <input type="text" id="jbl-location-unavailable" maxlength="255" placeholder="e.g. phone location was disabled">
          </div>
          <small class="jbl-field-error" data-error-message-for="capture_location"></small>
        </div>
        <p id="jbl-draft-state" class="field-help jbl-draft-state form-row-wide" aria-live="polite" title="Form fields save automatically. Files are not included.">Autosave on</p>
      </div>
    `;
  }

  function replaceLocationOptions(select, items, selectedValue, placeholder) {
    if (!select) return;
    const selected = String(selectedValue || '').toLowerCase();
    select.replaceChildren(new Option(placeholder, ''));
    (items || []).forEach(item => {
      const option = new Option(item.name, item.code);
      option.selected = [item.code, item.name].some(value => String(value || '').toLowerCase() === selected);
      select.add(option);
    });
  }

  async function wireJblLocationFields(farmer) {
    const countySelect = el('jbl-county');
    const subCountySelect = el('jbl-sub-county');
    if (!countySelect || !subCountySelect) return;
    let initialCounty = countySelect.value || farmer.county_ref_code || farmer.county || '';
    let initialSubCounty = subCountySelect.value || farmer.sub_county_ref_code || farmer.sub_county || '';
    const loadOptions = async () => {
      const branch = farmer.branch_ref_code || farmer.branch || '';
      const county = countySelect.value || initialCounty;
      const query = new URLSearchParams({ branch, county });
      const { ok, data } = await deps.apiFetch(`/location-options/?${query.toString()}`);
      if (!ok || !data?.ok) {
        deps.showToast(data?.error || 'Could not load governed location choices.', 'error');
        return;
      }
      replaceLocationOptions(countySelect, data.counties, data.selected_county?.code || county, '- Select county -');
      replaceLocationOptions(subCountySelect, data.sub_counties, initialSubCounty, '- Select sub-county -');
      initialCounty = countySelect.value;
      initialSubCounty = subCountySelect.value;
    };
    countySelect.addEventListener('change', () => {
      initialCounty = countySelect.value;
      initialSubCounty = '';
      loadOptions();
    });
    await loadOptions();
  }

  function jblDraftKey(farmerId) { return `portal:jbl-visit-draft:${farmerId}`; }
  const JBL_ACTIVE_DRAFT_KEY = 'portal:jbl-visit-active';

  function cameraIcon() {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14.5 4 16 7h3a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h3l1.5-3h5Z"/><circle cx="12" cy="13" r="3"/></svg>';
  }

  function pickerIcon() {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z"/><path d="M12 11v5M9.5 13.5H14.5"/></svg>';
  }

  function removeIcon() {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg>';
  }

  function jblMediaCategoryMarkup({ category, title, help, pickerId, cameraId, accept }) {
    const safeTitle = deps.escapeHtml(title);
    const fieldKey = category === 'LAF' ? 'laf_files' : 'jbl_visit_photo_files';
    return `<section class="media-category-upload" data-media-category="${category}" data-jbl-field="${fieldKey}">
      <div class="jbl-media-category-heading">
        <span>${safeTitle}</span>
        <div class="jbl-media-source-actions">
          <button type="button" class="jbl-media-icon-button" id="${cameraId}" data-camera-category="${category}" aria-label="Open live camera for ${safeTitle}" title="Open camera">${cameraIcon()}<span class="sr-only">Open camera</span></button>
          <label class="jbl-media-icon-button" for="${pickerId}" data-input-id="${pickerId}" role="button" tabindex="0" aria-label="Choose files for ${safeTitle}" title="Choose files">${pickerIcon()}<span class="sr-only">Choose files</span></label>
        </div>
      </div>
      <small>${deps.escapeHtml(help)}</small>
      <strong class="jbl-media-selection-summary" id="${pickerId}-name" aria-live="polite">No files selected</strong>
      <div class="jbl-media-preview-list" id="${pickerId}-previews"></div>
      <input class="sr-only" type="file" id="${pickerId}" data-media-category="${category}" multiple accept="${accept}">
      <small class="jbl-field-error" data-error-message-for="${fieldKey}"></small>
    </section>`;
  }

  function jblLiveCameraMarkup() {
    return `<section class="jbl-live-camera" id="jbl-live-camera" hidden aria-label="Live camera">
      <div class="jbl-live-camera-heading"><strong id="jbl-live-camera-title">Take evidence photo</strong><button type="button" class="jbl-camera-close" id="jbl-camera-close" aria-label="Close camera" title="Close">${removeIcon()}<span class="sr-only">Close camera</span></button></div>
      <div class="jbl-camera-viewport"><video id="jbl-camera-video" autoplay muted playsinline></video><div class="jbl-camera-status" id="jbl-camera-status" role="status">Starting camera…</div></div>
      <button type="button" class="jbl-camera-shutter" id="jbl-camera-shutter" aria-label="Take photo" title="Take photo" disabled><span aria-hidden="true"></span><span class="sr-only">Take photo</span></button>
    </section>`;
  }

  function stopJblLiveCamera() {
    jblCameraRequestId += 1;
    jblCameraStream?.getTracks?.().forEach(track => track.stop());
    jblCameraStream = null;
    jblCameraCategory = '';
    const video = el('jbl-camera-video');
    if (video) {
      video.pause?.();
      video.srcObject = null;
    }
    const panel = el('jbl-live-camera');
    if (panel) panel.hidden = true;
    const shutter = el('jbl-camera-shutter');
    if (shutter) shutter.disabled = true;
  }

  async function startJblLiveCamera(category) {
    const panel = el('jbl-live-camera');
    const video = el('jbl-camera-video');
    const status = el('jbl-camera-status');
    const shutter = el('jbl-camera-shutter');
    if (!panel || !video || !navigator.mediaDevices?.getUserMedia) {
      deps.showToast('Live camera is not available in this Telegram WebView. Use the folder icon to choose a photo.', 'error');
      return;
    }
    if (jblMediaItems().length >= Number(state().jblVisitMediaMaxFiles || 6)) {
      deps.showToast(`A JBL visit can include at most ${Number(state().jblVisitMediaMaxFiles || 6)} evidence files.`, 'error');
      return;
    }
    if (jblCameraStream) stopJblLiveCamera();
    const cameraRequestId = ++jblCameraRequestId;
    jblCameraCategory = category;
    panel.hidden = false;
    if (status) { status.hidden = false; status.textContent = 'Starting camera…'; }
    if (shutter) shutter.disabled = true;
    const title = el('jbl-live-camera-title');
    if (title) title.textContent = category === 'LAF' ? 'Photograph LAF document' : 'Take JBL visit photo';
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: 1920 },
          height: { ideal: 1080 },
        },
      });
      if (cameraRequestId !== jblCameraRequestId || !jblCameraCategory || !el('jbl-live-camera')) {
        stream.getTracks().forEach(track => track.stop());
        return;
      }
      jblCameraStream = stream;
      video.srcObject = stream;
      await video.play();
      if (status) status.hidden = true;
      if (shutter) shutter.disabled = false;
      panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } catch (error) {
      if (cameraRequestId !== jblCameraRequestId) return;
      stopJblLiveCamera();
      const denied = error?.name === 'NotAllowedError' || error?.name === 'PermissionDeniedError';
      deps.showToast(
        denied
          ? 'Camera permission was denied. Enable Camera for Telegram in your phone settings, reopen the Mini App, and retry.'
          : 'The live camera could not start. Close other camera apps and retry, or use the folder icon.',
        'error',
      );
    }
  }

  function capturedJblPhotoBlob(video) {
    const sourceWidth = Number(video.videoWidth || 0);
    const sourceHeight = Number(video.videoHeight || 0);
    if (!sourceWidth || !sourceHeight) return Promise.resolve(null);
    const scale = Math.min(1, 1920 / Math.max(sourceWidth, sourceHeight));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(sourceWidth * scale));
    canvas.height = Math.max(1, Math.round(sourceHeight * scale));
    const context = canvas.getContext('2d');
    if (!context) return Promise.resolve(null);
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    return new Promise(resolve => canvas.toBlob(blob => {
      canvas.width = 1;
      canvas.height = 1;
      resolve(blob);
    }, 'image/jpeg', 0.86));
  }

  async function captureJblLivePhoto() {
    const video = el('jbl-camera-video');
    const shutter = el('jbl-camera-shutter');
    if (!video || !jblCameraStream || !jblCameraCategory || shutter?.disabled) return;
    if (shutter) shutter.disabled = true;
    try {
      const blob = await capturedJblPhotoBlob(video);
      if (!blob) throw new Error('empty camera frame');
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
      const prefix = jblCameraCategory === 'LAF' ? 'laf-photo' : 'visit-photo';
      const file = new File([blob], `${prefix}-${timestamp}.jpg`, {
        type: 'image/jpeg',
        lastModified: Date.now(),
      });
      addJblMediaFiles(jblCameraCategory, [file]);
    } catch (_error) {
      deps.showToast('The photo could not be captured. Keep the camera open and retry.', 'error');
    } finally {
      if (shutter && jblCameraStream) shutter.disabled = false;
    }
  }

  function jblMediaFingerprint(file) {
    return [file.name, file.size, file.lastModified, file.type].join('|');
  }

  function jblMediaItems() {
    return [...jblMediaSelections.LAF, ...jblMediaSelections.JBL_VISIT_PHOTO];
  }

  function revokeJblThumbnail(item) {
    if (item?.thumbnailUrl) URL.revokeObjectURL(item.thumbnailUrl);
    if (item) item.thumbnailUrl = '';
  }

  function resetJblMediaSelections() {
    jblMediaItems().forEach(revokeJblThumbnail);
    jblMediaSelections = { LAF: [], JBL_VISIT_PHOTO: [] };
  }

  function formatMediaBytes(bytes) {
    if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function jblMediaInputId(category) {
    return category === 'LAF' ? 'jbl-laf-media' : 'jbl-visit-photo-media';
  }

  function renderJblMediaCategory(category) {
    const inputId = jblMediaInputId(category);
    const items = jblMediaSelections[category] || [];
    const summary = el(`${inputId}-name`);
    if (summary) {
      const totalBytes = items.reduce((total, item) => total + item.file.size, 0);
      summary.textContent = items.length ? `${items.length} selected · ${formatMediaBytes(totalBytes)}` : 'No files selected';
    }
    const previews = el(`${inputId}-previews`);
    if (!previews) return;
    previews.innerHTML = items.map(item => {
      const safeName = deps.escapeHtml(item.file.name || 'Evidence file');
      const isImage = String(item.file.type || '').startsWith('image/');
      const visual = item.thumbnailUrl
        ? `<img src="${item.thumbnailUrl}" alt="">`
        : `<span class="jbl-media-preview-placeholder" aria-hidden="true">${isImage ? cameraIcon() : 'PDF'}</span>`;
      return `<div class="jbl-media-preview-item" data-media-category="${category}" data-media-item-id="${item.id}" role="button" tabindex="0" aria-label="Preview ${safeName}">
        ${visual}<span class="jbl-media-preview-name" title="${safeName}">${safeName}</span>
        <button type="button" class="jbl-media-preview-open" data-media-item-id="${item.id}" aria-label="Preview ${safeName}" title="Preview"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg><span class="sr-only">Preview</span></button>
        <button type="button" class="jbl-media-remove" data-media-category="${category}" data-media-item-id="${item.id}" aria-label="Remove ${safeName}" title="Remove">${removeIcon()}<span class="sr-only">Remove</span></button>
      </div>`;
    }).join('');
  }

  function renderJblMediaSelections() {
    renderJblMediaCategory('LAF');
    renderJblMediaCategory('JBL_VISIT_PHOTO');
  }

  function allowedJblMediaFile(file, category) {
    const extension = String(file.name || '').toLowerCase().match(/\.[^.]+$/)?.[0] || '';
    const allowed = category === 'LAF'
      ? new Set(['.pdf', '.jpg', '.jpeg', '.png'])
      : new Set(['.jpg', '.jpeg', '.png', '.webp']);
    return allowed.has(extension);
  }

  function canvasThumbnailBlob(bitmap) {
    const canvas = document.createElement('canvas');
    canvas.width = 160;
    canvas.height = 160;
    const context = canvas.getContext('2d');
    context.drawImage(bitmap, 0, 0, 160, 160);
    return new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.68));
  }

  async function generateJblThumbnail(category, item) {
    if (!String(item.file.type || '').startsWith('image/') || !window.createImageBitmap) return;
    let bitmap;
    try {
      bitmap = await window.createImageBitmap(item.file, {
        resizeWidth: 160, resizeHeight: 160, resizeQuality: 'low',
      });
      const thumbnailBlob = await canvasThumbnailBlob(bitmap);
      const stillSelected = jblMediaSelections[category]?.some(candidate => candidate.id === item.id);
      if (!thumbnailBlob || !stillSelected) return;
      item.thumbnailUrl = URL.createObjectURL(thumbnailBlob);
      renderJblMediaCategory(category);
    } catch (_error) {
      // The generic image placeholder remains usable if this WebView cannot
      // decode a thumbnail. The original file is never decoded as a fallback.
    } finally {
      bitmap?.close?.();
    }
  }

  function queueJblThumbnail(category, item) {
    jblThumbnailQueue = jblThumbnailQueue
      .then(() => generateJblThumbnail(category, item))
      .catch(() => {});
  }

  function addJblMediaFiles(category, files) {
    const additions = Array.from(files || []);
    if (!additions.length) return;
    const existingFingerprints = new Set(jblMediaItems().map(item => jblMediaFingerprint(item.file)));
    const unique = additions.filter(file => {
      const fingerprint = jblMediaFingerprint(file);
      if (existingFingerprints.has(fingerprint)) return false;
      existingFingerprints.add(fingerprint);
      return true;
    });
    if (!unique.length) {
      deps.showToast('Those files are already selected.', 'info');
      return;
    }
    const invalid = unique.find(file => !allowedJblMediaFile(file, category));
    if (invalid) {
      deps.showToast(`${invalid.name} is not an accepted evidence type.`, 'error');
      return;
    }
    const maxBytes = Number(state().jblVisitMediaMaxBytes || 20 * 1024 * 1024);
    const oversize = unique.find(file => file.size > maxBytes);
    if (oversize) {
      deps.showToast(`${oversize.name} is larger than the ${Math.round(maxBytes / (1024 * 1024))} MB evidence limit.`, 'error');
      return;
    }
    const maximumFiles = Number(state().jblVisitMediaMaxFiles || 6);
    if (jblMediaItems().length + unique.length > maximumFiles) {
      deps.showToast(`A JBL visit can include at most ${maximumFiles} evidence files.`, 'error');
      return;
    }
    const totalBytes = [...jblMediaItems().map(item => item.file), ...unique]
      .reduce((total, file) => total + file.size, 0);
    const maximumTotalBytes = Number(state().jblVisitMediaMaxTotalBytes || 40 * 1024 * 1024);
    if (totalBytes > maximumTotalBytes) {
      deps.showToast(`JBL visit evidence cannot exceed ${Math.round(maximumTotalBytes / (1024 * 1024))} MB in one submission.`, 'error');
      return;
    }
    unique.forEach(file => {
      const item = { id: requestId(), file, thumbnailUrl: '' };
      jblMediaSelections[category].push(item);
      queueJblThumbnail(category, item);
    });
    renderJblMediaSelections();
  }

  function removeJblMediaItem(category, itemId) {
    const items = jblMediaSelections[category] || [];
    const index = items.findIndex(item => item.id === itemId);
    if (index < 0) return;
    revokeJblThumbnail(items[index]);
    items.splice(index, 1);
    renderJblMediaSelections();
  }

  function selectedJblPreviewEntries() {
    return ['LAF', 'JBL_VISIT_PHOTO'].flatMap(category =>
      (jblMediaSelections[category] || []).map(item => ({ category, item }))
    );
  }

  function openSelectedJblMediaPreview(itemId) {
    const entries = selectedJblPreviewEntries();
    const index = entries.findIndex(entry => entry.item.id === itemId);
    if (index < 0) return;
    const { category, item } = entries[index];
    const overlay = el('media-viewer-overlay');
    const title = el('media-viewer-title');
    const sub = el('media-viewer-sub');
    const content = el('media-viewer-content');
    if (!overlay || !content) return;
    closeMediaViewer();
    activeJblSelectionPreviewId = item.id;
    activeMediaObjectUrl = URL.createObjectURL(item.file);
    if (title) title.textContent = category === 'LAF' ? 'Review LAF evidence' : 'Review visit photo';
    if (sub) sub.textContent = `${index + 1} of ${entries.length} · ${item.file.name}`;
    const safeName = deps.escapeHtml(item.file.name || 'Selected evidence');
    const visual = String(item.file.type || '').startsWith('image/')
      ? `<img class="media-viewer-image jbl-selection-viewer-image" src="${activeMediaObjectUrl}" alt="${safeName}">`
      : `<iframe class="media-viewer-document" sandbox="" src="${activeMediaObjectUrl}" title="${safeName}"></iframe>`;
    content.classList.add('jbl-selection-preview-active');
    content.innerHTML = `<div class="jbl-selection-viewer">
      <div class="jbl-selection-viewer-stage">${visual}</div>
      <div class="jbl-selection-viewer-actions">
        <button type="button" class="jbl-selection-nav" data-selection-preview-action="previous" aria-label="Previous selected file" title="Previous" ${index === 0 ? 'disabled' : ''}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m15 18-6-6 6-6"/></svg><span class="sr-only">Previous</span></button>
        <button type="button" class="jbl-selection-delete" data-selection-preview-action="remove" data-media-category="${category}" data-media-item-id="${item.id}" aria-label="Remove this selected file" title="Remove"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 10v6M14 10v6"/></svg><span class="sr-only">Remove</span></button>
        <button type="button" class="jbl-selection-nav" data-selection-preview-action="next" aria-label="Next selected file" title="Next" ${index === entries.length - 1 ? 'disabled' : ''}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m9 18 6-6-6-6"/></svg><span class="sr-only">Next</span></button>
      </div>
    </div>`;
    overlay.classList.add('open');
  }

  function navigateSelectedJblPreview(offset) {
    const entries = selectedJblPreviewEntries();
    const currentIndex = entries.findIndex(entry => entry.item.id === activeJblSelectionPreviewId);
    const target = entries[currentIndex + offset];
    if (target) openSelectedJblMediaPreview(target.item.id);
  }

  function removeActiveJblPreview(category, itemId) {
    const entries = selectedJblPreviewEntries();
    const index = entries.findIndex(entry => entry.item.id === itemId);
    removeJblMediaItem(category, itemId);
    const remaining = selectedJblPreviewEntries();
    if (!remaining.length) {
      closeMediaViewer();
      return;
    }
    openSelectedJblMediaPreview(remaining[Math.min(index, remaining.length - 1)].item.id);
  }

  function jblVisitDraftValues() {
    const values = {};
    (state().jblVisitDraftFields || []).forEach(id => {
      values[id] = el(id)?.value || '';
    });
    return values;
  }

  function setJblDraftState(message, stateName) {
    const status = el('jbl-draft-state');
    if (!status) return;
    status.textContent = message;
    status.dataset.state = stateName || '';
  }

  function jblLocalDraft(farmer) {
    try {
      const raw = sessionStorage.getItem(jblDraftKey(farmer.id));
      const draft = raw ? JSON.parse(raw) : null;
      return draft?.values ? draft : null;
    } catch (_error) {
      sessionStorage.removeItem(jblDraftKey(farmer.id));
      return null;
    }
  }

  function applyJblVisitDraft(draft) {
    if (!draft?.values) return false;
    Object.entries(draft.values).forEach(([id, value]) => {
      const field = el(id);
      if (field) field.value = value;
    });
    if (draft.values['jbl-date']) syncJblDateControls(draft.values['jbl-date']);
    const help = el('gps-coords');
    if (help && draft.values['jbl-lat'] && draft.values['jbl-lng']) {
      help.textContent = `Location restored: ${draft.values['jbl-lat']}, ${draft.values['jbl-lng']}`;
    }
    setGpsUnavailableReasonVisible(
      !draft.values['jbl-lat'] && !draft.values['jbl-lng'] && !!draft.values['jbl-location-unavailable'],
    );
    return true;
  }

  function ensureJblServerDraft(farmer) {
    if (!farmer?.id || !window.MiniAppUtils?.createServerDraft) return null;
    if (jblServerDraft && jblServerDraftFarmerId === String(farmer.id)) return jblServerDraft;
    jblServerDraftFarmerId = String(farmer.id);
    jblServerDraft = window.MiniAppUtils.createServerDraft({
      workflow: 'portal_jbl_visit',
      contextKey: String(farmer.id),
      baseUrl: `/api/portal/jbl-queue/${encodeURIComponent(farmer.id)}/draft/`,
      initData: () => deps.tg?.initData || '',
      requestId,
      onSaving: () => setJblDraftState('Saving…', 'saving'),
      onSaved: () => setJblDraftState('Saved', 'saved'),
      onError: error => handleJblDraftSaveError(farmer, error),
      onCleared: () => setJblDraftState('', ''),
    });
    return jblServerDraft;
  }

  function saveJblVisitDraft(farmer, { immediate = false } = {}) {
    if (!farmer?.id || !el('jbl-date')) return;
    if (!(state().jblVisitDraftFields || []).length) {
      setJblDraftState('Autosave unavailable', 'local-only');
      return null;
    }
    const draft = {
      farmer_id: farmer.id,
      values: jblVisitDraftValues(),
      saved_at: Date.now(),
      workflow_revision: Number(farmer.workflow_revision || 1),
    };
    try { sessionStorage.setItem(jblDraftKey(farmer.id), JSON.stringify(draft)); } catch (_error) {}
    const serverDraft = ensureJblServerDraft(farmer);
    if (!serverDraft || !navigator.onLine) return draft;
    const save = immediate ? serverDraft.save(draft) : serverDraft.schedule(draft);
    if (immediate && save?.catch) save.catch(() => {});
    return draft;
  }

  async function handleJblDraftSaveError(farmer, error) {
    if (!error?.conflict || !jblServerDraft) {
      setJblDraftState('Saved on this device', 'local-only');
      return;
    }
    const localDraft = jblLocalDraft(farmer);
    try {
      const remoteDraft = await jblServerDraft.load();
      pendingJblDraftConflict = { farmer, localDraft, remoteDraft };
      const panel = el('jbl-draft-conflict');
      if (panel) { panel.hidden = false; panel.focus(); }
      setJblDraftState('Draft conflict', 'conflict');
    } catch (_loadError) {
      setJblDraftState('Saved on this device', 'local-only');
    }
  }

  async function resolveJblDraftConflict(choice) {
    const conflict = pendingJblDraftConflict;
    if (!conflict) return;
    if (choice === 'server') {
      if (applyJblVisitDraft(conflict.remoteDraft?.payload)) {
        try { sessionStorage.setItem(jblDraftKey(conflict.farmer.id), JSON.stringify(conflict.remoteDraft.payload)); } catch (_error) {}
      }
      setJblDraftState('Draft restored · reselect files', 'restored');
    } else if (conflict.localDraft && jblServerDraft) {
      try {
        await jblServerDraft.save(conflict.localDraft);
        setJblDraftState('Saved', 'saved');
      } catch (_error) {
        setJblDraftState('Saved on this device', 'local-only');
        return;
      }
    }
    pendingJblDraftConflict = null;
    if (el('jbl-draft-conflict')) el('jbl-draft-conflict').hidden = true;
  }

  function restoreJblVisitDraft(farmer) {
    const draft = jblLocalDraft(farmer);
    if (applyJblVisitDraft(draft)) {
      setJblDraftState('Draft restored · reselect files', 'restored');
    }
    return draft;
  }

  async function restoreJblVisitServerDraft(farmer, localDraft, inputVersion) {
    const serverDraft = ensureJblServerDraft(farmer);
    if (!serverDraft) return;
    try {
      const remoteDraft = await serverDraft.load();
      const remote = remoteDraft?.payload;
      const localSavedAt = Number(localDraft?.saved_at || 0);
      const remoteSavedAt = Number(remote?.saved_at || 0);
      // Do not overwrite fields the officer has started typing while the
      // network request was in flight. The device-local copy wins ties.
      if (
        remote?.values
        && jblServerDraftFarmerId === String(farmer.id)
        && state().selectedFarmer?.id === farmer.id
        && jblDraftInputVersion === inputVersion
        && remoteSavedAt > localSavedAt
      ) {
        applyJblVisitDraft(remote);
        try { sessionStorage.setItem(jblDraftKey(farmer.id), JSON.stringify(remote)); } catch (_error) {}
        setJblDraftState('Draft restored · reselect files', 'restored');
        if (Number(remote.workflow_revision || 1) !== Number(farmer.workflow_revision || 1)) {
          showJblWorkflowConflict(
            Number(remote.workflow_revision || 1),
            Number(farmer.workflow_revision || 1),
            'This restored draft was created before the latest case update.',
            { saveDraft: false },
          );
        }
      } else if (!localDraft) {
        setJblDraftState('Autosave on', 'ready');
      }
    } catch (_error) {
      // A local copy still protects the current session. The status below is
      // deliberately informative rather than a disruptive autosave toast.
      if (!localDraft) setJblDraftState('Waiting for connection', 'offline');
    }
  }

  async function clearJblVisitDraft(farmer) {
    if (farmer?.id) sessionStorage.removeItem(jblDraftKey(farmer.id));
    if (jblServerDraftFarmerId === String(farmer?.id || '')) {
      const draft = jblServerDraft;
      jblServerDraft = null;
      jblServerDraftFarmerId = '';
      if (draft) {
        try { await draft.clear(); } catch (_error) {}
      }
    }
  }

  function setGpsUnavailableReasonVisible(visible) {
    const wrapper = el('jbl-location-unavailable-wrap');
    const field = el('jbl-location-unavailable');
    if (!wrapper) return;
    wrapper.hidden = !visible;
    if (!visible && field) field.value = '';
  }

  function selectedJblFilesAreValid() {
    const maxBytes = Number(state().jblVisitMediaMaxBytes || 20 * 1024 * 1024);
    const files = jblMediaItems().map(item => item.file);
    const oversize = files.find(file => file.size > maxBytes);
    if (oversize) {
      const maxMb = Math.round(maxBytes / (1024 * 1024));
      deps.showToast(`${oversize.name} is larger than the ${maxMb} MB evidence limit.`, 'error');
      return false;
    }
    const maximumFiles = Number(state().jblVisitMediaMaxFiles || 6);
    if (files.length > maximumFiles) {
      deps.showToast(`A JBL visit can include at most ${maximumFiles} evidence files.`, 'error');
      return false;
    }
    const maximumTotalBytes = Number(state().jblVisitMediaMaxTotalBytes || 40 * 1024 * 1024);
    if (files.reduce((total, file) => total + file.size, 0) > maximumTotalBytes) {
      deps.showToast(`JBL visit evidence cannot exceed ${Math.round(maximumTotalBytes / (1024 * 1024))} MB in one submission.`, 'error');
      return false;
    }
    return true;
  }

  const JBL_FORWARD_VISIT_STATUSES = new Set(['Approved', 'Awaiting Analysis']);

  function clearJblFieldErrors() {
    document.querySelectorAll('[data-jbl-field]').forEach(node => {
      node.classList.remove('invalid');
      node.querySelectorAll('[aria-invalid="true"]').forEach(control => control.removeAttribute('aria-invalid'));
    });
    document.querySelectorAll('[data-error-message-for]').forEach(node => { node.textContent = ''; });
    const summary = el('jbl-form-errors');
    if (summary) { summary.hidden = true; summary.querySelector('ul')?.replaceChildren(); }
  }

  function showJblFieldErrors(errors) {
    clearJblFieldErrors();
    const entries = Object.entries(errors || {}).filter(([, message]) => Boolean(message));
    if (!entries.length) return false;
    const summary = el('jbl-form-errors');
    const list = summary?.querySelector('ul');
    entries.forEach(([field, message]) => {
      const wrapper = document.querySelector(`[data-jbl-field="${field}"]`);
      wrapper?.classList.add('invalid');
      const control = wrapper?.querySelector('input:not([type="hidden"]), select, textarea, button');
      control?.setAttribute('aria-invalid', 'true');
      const detail = document.querySelector(`[data-error-message-for="${field}"]`);
      if (detail) detail.textContent = message;
      if (list) { const item = document.createElement('li'); item.textContent = message; list.appendChild(item); }
    });
    if (summary) { summary.hidden = false; summary.focus(); }
    const first = document.querySelector('[data-jbl-field].invalid');
    first?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
    window.setTimeout(() => first?.querySelector('input:not([type="hidden"]), select, textarea, button')?.focus(), 180);
    return true;
  }

  function validateJblVisitFields() {
    const errors = {};
    const status = el('jbl-status')?.value || '';
    if (!status) errors.visit_status = 'Select the JBL visit outcome.';
    if (!el('jbl-date')?.value) errors.visit_date = 'Enter the JBL visit date.';
    if (JBL_FORWARD_VISIT_STATUSES.has(status)) {
      if (!jblMediaSelections.LAF.length) errors.laf_files = 'Add at least one LAF document for this outcome.';
      if (!jblMediaSelections.JBL_VISIT_PHOTO.length) errors.jbl_visit_photo_files = 'Add at least one JBL visit photo for this outcome.';
      const hasCoordinates = Boolean(el('jbl-lat')?.value && el('jbl-lng')?.value);
      if (!hasCoordinates && !el('jbl-location-unavailable')?.value.trim()) {
        errors.capture_location = 'Capture GPS or explain why the visit location was unavailable.';
        setGpsUnavailableReasonVisible(true);
      }
    }
    return errors;
  }

  function showJblWorkflowConflict(expected, actual, message, options = {}) {
    pendingJblWorkflowConflict = { expected, actual };
    const panel = el('jbl-workflow-conflict');
    const detail = el('jbl-workflow-conflict-message');
    if (detail) detail.textContent = `${message || 'Another staff member updated this case.'} You opened revision ${expected}; the case is now revision ${actual}.`;
    if (panel) { panel.hidden = false; panel.focus(); }
    if (el('btn-submit-jbl')) el('btn-submit-jbl').disabled = true;
    if (options.saveDraft !== false) saveJblVisitDraft(state().selectedFarmer, { immediate: true });
  }

  async function reviewLatestJblCase() {
    const farmer = state().selectedFarmer;
    if (!farmer || !pendingJblWorkflowConflict) return;
    const result = await deps.apiFetch(`/farmers/${encodeURIComponent(farmer.id)}/`);
    if (!result.ok || !result.data?.farmer) {
      deps.showToast(result.data?.error || 'The latest case could not be loaded. Retry before submitting.', 'error');
      return;
    }
    Object.assign(farmer, result.data.farmer);
    pendingJblWorkflowConflict = null;
    if (el('jbl-workflow-conflict')) el('jbl-workflow-conflict').hidden = true;
    if (el('btn-submit-jbl')) el('btn-submit-jbl').disabled = false;
    saveJblVisitDraft(farmer, { immediate: true });
    deps.showToast('Latest case loaded. Your draft remains in the form; review it before submitting.', 'info');
  }

  function wireJblVisitDraft(farmer) {
    jblDraftInputVersion = 0;
    const localDraft = restoreJblVisitDraft(farmer);
    restoreJblVisitServerDraft(farmer, localDraft, jblDraftInputVersion);
    el('jbl-review-latest')?.addEventListener('click', reviewLatestJblCase);
    el('jbl-use-local-draft')?.addEventListener('click', () => resolveJblDraftConflict('local'));
    el('jbl-use-server-draft')?.addEventListener('click', () => resolveJblDraftConflict('server'));
    ['jbl-laf-media', 'jbl-visit-photo-media'].forEach(id => {
      el(id)?.addEventListener('change', () => {
        const input = el(id);
        addJblMediaFiles(input?.dataset.mediaCategory, input?.files);
        if (input) input.value = '';
        jblDraftInputVersion += 1;
        saveJblVisitDraft(farmer);
      });
    });
    el('sheet-form')?.querySelector('.media-upload-control')?.addEventListener('click', event => {
      const cameraButton = event.target.closest('[data-camera-category]');
      if (cameraButton) {
        startJblLiveCamera(cameraButton.dataset.cameraCategory);
        return;
      }
      const removeButton = event.target.closest('.jbl-media-remove');
      if (!removeButton) return;
      removeJblMediaItem(removeButton.dataset.mediaCategory, removeButton.dataset.mediaItemId);
      return;
    });
    el('sheet-form')?.querySelector('.media-upload-control')?.addEventListener('click', event => {
      if (event.target.closest('.jbl-media-remove, [data-camera-category], .jbl-media-icon-button')) return;
      const previewButton = event.target.closest('.jbl-media-preview-open');
      if (previewButton) {
        openSelectedJblMediaPreview(previewButton.dataset.mediaItemId);
        return;
      }
      const previewItem = event.target.closest('.jbl-media-preview-item');
      if (previewItem) openSelectedJblMediaPreview(previewItem.dataset.mediaItemId);
    });
    el('sheet-form')?.querySelector('.media-upload-control')?.addEventListener('keydown', event => {
      if (event.target.closest('button')) return;
      const previewItem = event.target.closest('.jbl-media-preview-item');
      if (previewItem && ['Enter', ' '].includes(event.key)) {
        event.preventDefault();
        openSelectedJblMediaPreview(previewItem.dataset.mediaItemId);
        return;
      }
      const sourceButton = event.target.closest('.jbl-media-icon-button');
      if (!sourceButton || !['Enter', ' '].includes(event.key)) return;
      event.preventDefault();
      if (sourceButton.getAttribute('aria-disabled') !== 'true') el(sourceButton.dataset.inputId)?.click();
    });
    el('jbl-camera-close')?.addEventListener('click', stopJblLiveCamera);
    el('jbl-camera-shutter')?.addEventListener('click', captureJblLivePhoto);
    const form = el('sheet-form');
    if (form) form.oninput = () => {
      jblDraftInputVersion += 1;
      saveJblVisitDraft(farmer);
    };
    if (form) form.onchange = () => {
      jblDraftInputVersion += 1;
      saveJblVisitDraft(farmer);
    };
  }

  const PORTAL_ACTIVE_WORKFLOW_DRAFT_KEY = 'portal:case-workflow-active';
  const WORKFLOW_DRAFT_CONFIG = {
    credit: {
      fields: ['credit-decision', 'credit-imab', 'credit-customer-no'],
      endpoint: farmerId => `/api/portal/credit-queue/${encodeURIComponent(farmerId)}/draft/`,
    },
    final_review: {
      fields: ['final-decision', 'final-repayment-date', 'final-repayment-tenor', 'final-comment'],
      endpoint: farmerId => `/api/portal/final-review-queue/${encodeURIComponent(farmerId)}/draft/`,
    },
  };

  function workflowDraftKey(mode, farmerId) { return `portal:${mode}-draft:${farmerId}`; }

  function workflowDraftValues(mode) {
    const values = {};
    (WORKFLOW_DRAFT_CONFIG[mode]?.fields || []).forEach(id => { values[id] = el(id)?.value || ''; });
    return values;
  }

  function setWorkflowDraftState(message, stateName) {
    const status = el('workflow-draft-state');
    if (!status) return;
    status.textContent = message;
    status.dataset.state = stateName || '';
  }

  function localWorkflowDraft(farmer, mode) {
    const key = workflowDraftKey(mode, farmer.id);
    try {
      const draft = JSON.parse(sessionStorage.getItem(key) || 'null');
      return draft?.values ? draft : null;
    } catch (_error) {
      sessionStorage.removeItem(key);
      return null;
    }
  }

  function applyWorkflowDraft(draft, mode) {
    if (!draft?.values) return false;
    Object.entries(draft.values).forEach(([id, value]) => {
      const field = el(id);
      if (field) field.value = value;
    });
    if (mode === 'credit') el('credit-imab')?.dispatchEvent(new Event('change'));
    return true;
  }

  function ensureWorkflowServerDraft(farmer, mode) {
    const config = WORKFLOW_DRAFT_CONFIG[mode];
    if (!config || !farmer?.id || !window.MiniAppUtils?.createServerDraft) return null;
    const key = `${mode}:${farmer.id}`;
    if (workflowServerDraft && workflowServerDraftKey === key) return workflowServerDraft;
    workflowServerDraftKey = key;
    workflowServerDraft = window.MiniAppUtils.createServerDraft({
      workflow: `portal_${mode}`,
      contextKey: String(farmer.id),
      baseUrl: config.endpoint(farmer.id),
      initData: () => deps.tg?.initData || '',
      requestId,
      onSaving: () => setWorkflowDraftState('Saving…', 'saving'),
      onSaved: () => setWorkflowDraftState('Saved', 'saved'),
      onError: () => setWorkflowDraftState('Saved on this device', 'local-only'),
      onCleared: () => setWorkflowDraftState('', ''),
    });
    return workflowServerDraft;
  }

  function saveWorkflowDraft(farmer, mode, { immediate = false } = {}) {
    const config = WORKFLOW_DRAFT_CONFIG[mode];
    if (!config || !farmer?.id || !el(config.fields[0])) return null;
    const draft = { farmer_id: farmer.id, mode, values: workflowDraftValues(mode), saved_at: Date.now() };
    try {
      sessionStorage.setItem(workflowDraftKey(mode, farmer.id), JSON.stringify(draft));
      sessionStorage.setItem(PORTAL_ACTIVE_WORKFLOW_DRAFT_KEY, JSON.stringify({ farmer_id: farmer.id, mode }));
    } catch (_error) {}
    const serverDraft = ensureWorkflowServerDraft(farmer, mode);
    if (!serverDraft || !navigator.onLine) return draft;
    const save = immediate ? serverDraft.save(draft) : serverDraft.schedule(draft);
    if (immediate && save?.catch) save.catch(() => {});
    return draft;
  }

  async function restoreWorkflowServerDraft(farmer, mode, localDraft, inputVersion) {
    const serverDraft = ensureWorkflowServerDraft(farmer, mode);
    if (!serverDraft) return;
    try {
      const remote = (await serverDraft.load())?.payload;
      if (
        remote?.values
        && workflowServerDraftKey === `${mode}:${farmer.id}`
        && String(state().selectedFarmer?.id || '') === String(farmer.id)
        && state().activeMode === mode
        && workflowDraftInputVersion === inputVersion
        && Number(remote.saved_at || 0) > Number(localDraft?.saved_at || 0)
      ) {
        applyWorkflowDraft(remote, mode);
        sessionStorage.setItem(workflowDraftKey(mode, farmer.id), JSON.stringify(remote));
        setWorkflowDraftState('Draft restored', 'restored');
      } else if (!localDraft) {
        setWorkflowDraftState('Autosave on', 'ready');
      }
    } catch (_error) {
      if (!localDraft) setWorkflowDraftState('Waiting for connection', 'offline');
    }
  }

  function wireWorkflowDraft(farmer, mode) {
    workflowDraftInputVersion = 0;
    const localDraft = localWorkflowDraft(farmer, mode);
    if (applyWorkflowDraft(localDraft, mode)) setWorkflowDraftState('Draft restored', 'restored');
    restoreWorkflowServerDraft(farmer, mode, localDraft, workflowDraftInputVersion);
    const recordEdit = () => {
      workflowDraftInputVersion += 1;
      saveWorkflowDraft(farmer, mode);
    };
    const form = el('sheet-form');
    if (form) {
      form.oninput = recordEdit;
      form.onchange = recordEdit;
    }
  }

  async function clearWorkflowDraft(farmer, mode) {
    if (farmer?.id) sessionStorage.removeItem(workflowDraftKey(mode, farmer.id));
    sessionStorage.removeItem(PORTAL_ACTIVE_WORKFLOW_DRAFT_KEY);
    if (workflowServerDraftKey === `${mode}:${farmer?.id || ''}`) {
      const draft = workflowServerDraft;
      workflowServerDraft = null;
      workflowServerDraftKey = '';
      if (draft) {
        try { await draft.clear(); } catch (_error) {}
      }
    }
  }

  function wireGpsButton() {
    const btn = el('btn-gps');
    if (!btn) return;
    btn.addEventListener('click', () => {
      if (!navigator.geolocation) {
        setGpsUnavailableReasonVisible(true);
        deps.showToast('GPS is not supported by your browser', 'error');
        return;
      }
      btn.disabled = true;
      btn.innerHTML = 'Capturing Location...';
      navigator.geolocation.getCurrentPosition(
        position => {
          const lat = position.coords.latitude;
          const lng = position.coords.longitude;
          el('jbl-lat').value = lat;
          el('jbl-lng').value = lng;
          setGpsUnavailableReasonVisible(false);
          el('gps-coords').innerHTML = `Location captured<br><span style="font-family: monospace; font-size: 12px; color: var(--color-success)">Lat: ${lat.toFixed(6)}, Lng: ${lng.toFixed(6)}</span>`;
          initMap(lat, lng);
          btn.innerHTML = 'Location Captured';
          btn.disabled = false;
          deps.showToast('GPS location captured', 'success');
        },
        error => {
          btn.disabled = false;
          btn.innerHTML = 'Try Capture Again';
          let msg = 'Failed to get location';
          if (error.code === error.PERMISSION_DENIED) msg = 'Location permission denied';
          else if (error.code === error.POSITION_UNAVAILABLE) msg = 'Location unavailable';
          else if (error.code === error.TIMEOUT) msg = 'Location request timed out';
          const coords = el('gps-coords');
          if (coords) {
            coords.innerHTML = `${deps.escapeHtml(msg)}${error.code === error.PERMISSION_DENIED ? ' <button type="button" class="btn btn-secondary gps-settings-button" id="gps-open-settings">Open location settings</button>' : ''}`;
            coords.querySelector('#gps-open-settings')?.addEventListener('click', openLocationSettings);
          }
          setGpsUnavailableReasonVisible(true);
          deps.showToast(msg, 'error');
        },
        { enableHighAccuracy: true, timeout: 8000, maximumAge: 0 }
      );
    });
  }

  function openLocationSettings() {
    // Telegram does not expose a portable OS-settings API. Android accepts
    // this intent in most clients; other platforms receive a clear fallback.
    const isAndroid = /Android/i.test(navigator.userAgent || '');
    const settingsUrl = isAndroid
      ? 'intent:#Intent;action=android.settings.LOCATION_SOURCE_SETTINGS;end'
      : '';
    try {
      if (settingsUrl) window.location.href = settingsUrl;
      else deps.showToast('Open phone Settings → Privacy/Location and allow Telegram to use your location, then try again.', 'error');
    } catch (error) {
      deps.showToast('Open your phone settings and enable Location for Telegram.', 'error');
    }
  }

  function buildCreditForm(farmer) {
    const currentDecision = farmer.credit_decision || 'Pending';
    const decisionOptions = state().metaDecisions.filter(decision => decision !== 'Pending').map(decision =>
      `<option value="${deps.escapeHtml(decision)}"${currentDecision === decision ? ' selected' : ''}>${deps.escapeHtml(decision)}</option>`
    ).join('');
    const currentImabStatus = farmer.imab_created || 'Pending';
    const imabValues = state().metaImabOptions.length ? [...state().metaImabOptions] : ['Yes', 'No', 'Pending'];
    if (!imabValues.includes('Pending')) imabValues.push('Pending');
    const imabOptions = imabValues.map(value =>
      `<option value="${deps.escapeHtml(value)}"${currentImabStatus === value ? ' selected' : ''}>${deps.escapeHtml(value)}</option>`
    ).join('');
    const customerNoDisabled = currentImabStatus !== 'Yes';
    const spinReferences = (farmer.spin_references || []).map((reference, index) => {
      const links = (reference.links || []).map(link => `<a class="media-link" href="${deps.escapeHtml(link.url)}" target="_blank" rel="noopener">${deps.escapeHtml(link.label)}</a>`).join('');
      const names = (reference.attachment_names || []).map(name => deps.escapeHtml(name)).join(', ');
      return `<article class="credit-reference"><div><strong>${deps.escapeHtml(reference.request_type || `SPIN/CRB request ${index + 1}`)}</strong><small>${deps.escapeHtml(reference.status || '')}${reference.created_at ? ` · ${deps.escapeHtml(deps.fmtDate(reference.created_at))}` : ''}</small></div>${links || (names ? `<small>Uploaded: ${names}</small>` : '<small>No report link recorded yet.</small>')}</article>`;
    }).join('');
    return `
      <div class="form-section form-grid credit-analysis-form">
        ${spinReferences ? `<div class="credit-reference-panel"><div class="field-help"><strong>SPIN / CRB reference</strong> · reports already uploaded for this customer</div>${spinReferences}</div>` : ''}
        <div class="form-row"><label>Credit Decision <span class="required-marker" aria-hidden="true">*</span><span class="sr-only"> required</span></label><select id="credit-decision" aria-required="true"><option value="">- Select a decision -</option>${decisionOptions}</select></div>
        <div class="form-row"><label>Created on IMAB?</label><select id="credit-imab">${imabOptions}</select></div>
        <div class="form-row form-row-wide">
          <label>Customer No.</label>
          <input type="text" id="credit-customer-no" inputmode="numeric" pattern="[0-9]*" placeholder="IMAB customer number" value="${deps.escapeHtml(customerNoDisabled ? '' : (farmer.customer_no || ''))}"${customerNoDisabled ? ' disabled' : ''}>
          <small id="credit-imab-help" class="field-help">${customerNoDisabled ? 'Select Yes after IMAB creation before entering a customer number.' : 'Required before this case can move to Head of Rural review.'}</small>
        </div>
        <p id="workflow-draft-state" class="field-help jbl-draft-state form-row-wide" aria-live="polite" title="Form fields save automatically.">Autosave on</p>
      </div>
      ${productConfigurationMarkup(farmer, 'credit_decision')}
      ${farmer.jbl_visit_comment ? `<section class="credit-jbl-comment"><span>JBL Comment</span><p>${deps.escapeHtml(farmer.jbl_visit_comment)}</p></section>` : ''}
    `;
  }

  function wireCreditImabFields() {
    const imab = el('credit-imab');
    const customerNo = el('credit-customer-no');
    const help = el('credit-imab-help');
    if (!imab || !customerNo) return;
    const sync = () => {
      const enabled = imab.value === 'Yes';
      customerNo.disabled = !enabled;
      if (!enabled) customerNo.value = '';
      if (help) {
        help.textContent = enabled
          ? 'Required before this case can move to Head of Rural review.'
          : 'Select Yes after IMAB creation before entering a customer number.';
      }
    };
    imab.addEventListener('change', sync);
    sync();
  }

  function productConfigurationControl(item, value, dataName) {
    const data = `${dataName}="${deps.escapeHtml(item.key)}"`;
    if (['boolean', 'checkbox', 'eligibility'].includes(item.type)) {
      return `<label class="checkbox-row"><input type="checkbox" ${data}${value === true ? ' checked' : ''}><span>Confirmed</span></label>`;
    }
    if (item.type === 'choice') {
      return `<select ${data}><option value="">Choose</option>${(item.options || []).map(option => `<option value="${deps.escapeHtml(option)}"${value === option ? ' selected' : ''}>${deps.escapeHtml(option)}</option>`).join('')}</select>`;
    }
    const type = item.type === 'date' ? 'date' : ['number', 'money', 'amount'].includes(item.type) ? 'number' : 'text';
    return `<input type="${type}" ${data} value="${deps.escapeHtml(value ?? '')}"${type === 'number' ? ' step="any" inputmode="decimal"' : ''}${item.type === 'document' ? ' placeholder="Document reference or evidence note"' : ''}>`;
  }

  function productConfigurationMarkup(farmer, stage) {
    const terms = farmer.product_terms || {};
    const requirements = (terms.requirements || []).filter(item =>
      item.enforcement_stage === stage && (!item.workflow || item.workflow === 'jawabu_portal')
    );
    const attributes = (terms.custom_attributes || []).filter(item =>
      !(item.workflows || []).length || item.workflows.includes('jawabu_portal')
    );
    if (!requirements.length && !attributes.length) return '';
    const requirementRows = requirements.map(item => `<div class="form-row"><label>${deps.escapeHtml(item.label)}${item.required ? ' *' : ''}</label>${item.description ? `<small class="field-help">${deps.escapeHtml(item.description)}</small>` : ''}${productConfigurationControl(item, farmer.product_requirements?.[item.key], 'data-product-requirement')}</div>`).join('');
    const attributeRows = attributes.map(item => `<div class="form-row"><label>${deps.escapeHtml(item.label)}${item.required ? ' *' : ''}</label>${item.help_text ? `<small class="field-help">${deps.escapeHtml(item.help_text)}</small>` : ''}${productConfigurationControl(item, farmer.product_custom_values?.[item.key] ?? item.default, 'data-product-custom')}</div>`).join('');
    return `<div class="form-section form-grid product-configuration"><div class="form-row form-row-wide"><strong>${deps.escapeHtml(terms.product_name || farmer.payment_product || 'Product')} requirements</strong></div>${requirementRows}${attributeRows}</div>`;
  }

  function collectProductConfiguration() {
    const requirementEvidence = {};
    const customValues = {};
    el('sheet-form')?.querySelectorAll('[data-product-requirement]').forEach(input => {
      requirementEvidence[input.dataset.productRequirement] = input.type === 'checkbox' ? input.checked : input.value;
    });
    el('sheet-form')?.querySelectorAll('[data-product-custom]').forEach(input => {
      customValues[input.dataset.productCustom] = input.type === 'checkbox' ? input.checked : input.value;
    });
    return { requirementEvidence, customValues };
  }

  function buildFinalReviewForm(farmer) {
    const decisionOptions = state().metaFinalDecisions.filter(decision => decision !== 'Under Review').map(decision =>
      `<option value="${deps.escapeHtml(decision)}"${farmer.final_decision === decision ? ' selected' : ''}>${deps.escapeHtml(decision)}</option>`
    ).join('');
    const phoneDigits = String(farmer.primary_phone || '').replace(/\D/g, '');
    const phone = phoneDigits.startsWith('0')
      ? `254${phoneDigits.slice(1)}`
      : phoneDigits;
    return `
      <div class="form-section form-grid final-review-grid">
        <div class="form-row">
          <label>Client Phone</label>
          <div class="phone-action-field">
            <input type="tel" value="${deps.escapeHtml(farmer.primary_phone || '')}" readonly>
            ${phone ? `<a class="phone-call-button" href="tel:+${phone}" aria-label="Call ${deps.escapeHtml(farmer.primary_phone || 'client')}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.8 19.8 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.12 4.18 2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.12.9.33 1.77.63 2.6a2 2 0 0 1-.45 2.11L8.02 9.7a16 16 0 0 0 6.28 6.28l1.27-1.27a2 2 0 0 1 2.11-.45c.83.3 1.7.51 2.6.63A2 2 0 0 1 22 16.92Z"/></svg><span>Call</span></a>` : ''}
          </div>
        </div>
        <div class="form-row"><label>Final Decision</label><select id="final-decision"><option value="">- Select -</option>${decisionOptions}</select></div>
        <div class="form-row"><label>Repayment Dates</label><input type="text" id="final-repayment-date" placeholder="e.g. 10TH" value="${deps.escapeHtml(farmer.repayment_date || '')}"></div>
        <div class="form-row"><label>Tenor</label><input type="text" id="final-repayment-tenor" placeholder="e.g. 6 months" value="${deps.escapeHtml(farmer.repayment_tenor || '')}"></div>
        <div class="form-row form-row-wide"><label>After-call Comments</label><textarea id="final-comment" rows="4" placeholder="Summarize the call and decision...">${deps.escapeHtml(farmer.final_decision_comment || '')}</textarea>${voiceWidget('final_decision_comment', 'final-comment')}</div>
        <p id="workflow-draft-state" class="field-help jbl-draft-state form-row-wide" aria-live="polite">Draft saves automatically.</p>
      </div>
      ${productConfigurationMarkup(farmer, 'final_decision')}
      ${farmer.jbl_visit_comment ? `<div class="info-row"><span class="ir-label">BRO Comment</span><span class="ir-value">${deps.escapeHtml(farmer.jbl_visit_comment)}</span></div>` : ''}
    `;
  }

  function toggleClientMedia(farmerId) {
    const button = el('btn-view-client-media');
    const target = el('final-client-media');
    if (!farmerId || !target) return;
    if (!target.hidden) {
      target.hidden = true;
      if (button) {
        button.setAttribute('aria-expanded', 'false');
        const label = button.querySelector('.sheet-action-label');
        if (label) label.textContent = button.dataset.collapsedLabel || 'View client media';
      }
      return;
    }
    target.hidden = false;
    if (button) {
      button.setAttribute('aria-expanded', 'true');
      const label = button.querySelector('.sheet-action-label');
      if (label) label.textContent = 'Hide client media';
    }
    if (target.dataset.loaded === 'true') return;
    loadClientMedia(farmerId);
  }

  async function loadClientMedia(farmerId) {
    const button = el('btn-view-client-media');
    const target = el('final-client-media');
    if (!farmerId || !target) return;
    button && (button.disabled = true);
    target.innerHTML = '<span class="field-help">Loading client media...</span>';
    try {
      const result = await deps.apiFetch('/jbl-queue/' + encodeURIComponent(farmerId) + '/media/list/');
      const media = result.data?.media || [];
      if (!result.ok || !result.data?.ok) {
        target.innerHTML = `<span class="field-help">${deps.escapeHtml(result.data?.error || 'Could not load client media.')}</span>`;
        return;
      }
      media.forEach((item, index) => {
        const category = item.category === 'JBL_VISIT_PHOTO' ? 'JBL visit photo' : 'Signed LAF document';
        item.name = `${category} — ${item.name || `${category} ${index + 1}`}`;
      });
      target.dataset.farmerId = farmerId;
      target.dataset.loaded = 'true';
      renderClientMediaLinks(media, target);
      return;
    } catch (error) {
      target.innerHTML = '<span class="field-help">Could not load client media. Check your connection and retry.</span>';
    } finally {
      if (button) button.disabled = false;
    }
  }

  function renderClientMediaLinks(media, target) {
    target.innerHTML = media.length
      ? media.map((item, index) => `
        <article class="client-media-item">
          <p class="client-media-name">${deps.escapeHtml(item.name || `Client media ${index + 1}`)}</p>
          <div class="client-media-actions">
            ${item.preview_url
              ? `<button type="button" class="media-link media-preview-link" data-media-index="${index}">View in app</button>`
              : '<span class="media-link media-link-unavailable">In-app preview unavailable for this older upload</span>'}
            ${item.open_url
              ? `<button type="button" class="media-link media-external-link" data-media-external-index="${index}" title="Open in your phone's external viewer to download">Open externally</button>`
              : ''}
          </div>
        </article>
      `).join('')
      : '<span class="field-help">No signed LAF document or JBL visit photo has been uploaded for this client.</span>';
    target.querySelectorAll('.media-preview-link').forEach(link => {
      link.addEventListener('click', () => {
        const item = media[Number(link.dataset.mediaIndex)];
        if (item) openClientMediaPreview(item);
      });
    });
    target.querySelectorAll('.media-external-link').forEach(link => {
      link.addEventListener('click', () => {
        const item = media[Number(link.dataset.mediaExternalIndex)];
        if (item) openClientMediaExternally(item, target, link);
      });
    });
  }

  async function openClientMediaExternally(item, target, button) {
    const farmerId = target.dataset.farmerId;
    if (!farmerId) return;
    const originalLabel = button.textContent;
    button.disabled = true;
    button.textContent = 'Preparing…';
    try {
      // Refresh immediately before launching because the short-lived external
      // link is intentionally not reusable after a staff member waits in the
      // case for a while. The new link remains scoped to this attachment.
      const result = await deps.apiFetch('/jbl-queue/' + encodeURIComponent(farmerId) + '/media/list/');
      const latest = (result.data?.media || []).find(candidate => String(candidate.id) === String(item.id));
      if (!result.ok || !latest?.open_url) {
        throw new Error(result.data?.error || 'Could not prepare this media for download.');
      }
      deps.openPortalLink(latest.open_url);
    } catch (error) {
      deps.showToast(error.message || 'Could not open this media externally.', 'error');
    } finally {
      button.disabled = false;
      button.textContent = originalLabel;
    }
  }

  function closeMediaViewer() {
    el('media-viewer-overlay')?.classList.remove('open');
    const content = el('media-viewer-content');
    if (content) {
      content.replaceChildren();
      content.classList.remove('jbl-selection-preview-active');
    }
    if (activeMediaObjectUrl) {
      URL.revokeObjectURL(activeMediaObjectUrl);
      activeMediaObjectUrl = '';
    }
    activeJblSelectionPreviewId = '';
  }

  function mediaPreviewHeaders() {
    const fromPortalApi = deps.portalApi?.initDataHeader?.(deps.tg) || {};
    if (Object.keys(fromPortalApi).length) return { ...fromPortalApi, 'X-Request-ID': requestId() };
    return deps.tg?.initData
      ? { 'X-Telegram-Init-Data': deps.tg.initData, 'X-Request-ID': requestId() }
      : { 'X-Request-ID': requestId() };
  }

  async function openClientMediaPreview(item) {
    const overlay = el('media-viewer-overlay');
    const title = el('media-viewer-title');
    const sub = el('media-viewer-sub');
    const content = el('media-viewer-content');
    if (!overlay || !content || !item?.preview_url) return;

    closeMediaViewer();
    if (title) title.textContent = item.category === 'JBL_VISIT_PHOTO' ? 'JBL Visit Photo' : 'Signed LAF Document';
    if (sub) sub.textContent = item.name || 'Client media';
    content.innerHTML = '<div class="media-viewer-loading" role="status"><span class="spinner-inline" aria-hidden="true"></span> Loading secure media…</div>';
    overlay.classList.add('open');
    try {
      const viewer = window.SecureMediaViewer;
      if (!viewer) throw new Error('The secure media viewer is unavailable. Refresh the Portal and retry.');
      const blob = await viewer.fetchAuthorizedBlob(item.preview_url, { headers: mediaPreviewHeaders() });
      activeMediaObjectUrl = viewer.renderBlob(content, blob, {
        mimeType: item.mime_type,
        name: item.name || 'Client media',
      });
    } catch (error) {
      content.innerHTML = `<p class="media-viewer-error">${deps.escapeHtml(error.message || 'Could not open this client media.')} The Portal remains open; close this view and retry.</p>`;
    }
  }

  function buildRequisitionBatchNotice() {
    return `
      <div class="form-section">
        <div class="field-help">Select this case using its checkbox in the Orders queue, then assign one order batch from the selected cases panel. Payment product is supplied later by the controlled system export.</div>
      </div>
    `;
  }

  function closeSheet({ saveDraft = true } = {}) {
    const farmer = state().selectedFarmer;
    // Closing a sheet, opening case history, or Telegram temporarily replacing
    // this WebView must never discard unfinished visit fields. Successful
    // submission is the sole path that clears this private recovery draft.
    if (saveDraft && state().activeMode === 'jbl_visit') saveJblVisitDraft(farmer, { immediate: true });
    if (saveDraft && WORKFLOW_DRAFT_CONFIG[state().activeMode]) saveWorkflowDraft(farmer, state().activeMode, { immediate: true });
    sessionStorage.removeItem(JBL_ACTIVE_DRAFT_KEY);
    sessionStorage.removeItem(PORTAL_ACTIVE_WORKFLOW_DRAFT_KEY);
    if (voiceRecorder?.state === 'recording') { discardVoiceOnStop = true; voiceRecorder.stop(); }
    else releaseVoiceStream();
    if (activeVoiceAttempt) cancelVoiceAttempt(activeVoiceAttempt);
    Object.entries(acceptedVoiceAttempts).forEach(([fieldName, id]) => {
      cancelVoiceAttempt({ id, fieldName });
      delete acceptedVoiceAttempts[fieldName];
    });
    stopJblLiveCamera();
    closeMediaViewer();
    if (case360CounterCleanup) case360CounterCleanup();
    case360CounterCleanup = null;
    resetJblMediaSelections();
    el('sheet-overlay')?.classList.remove('open', 'jbl-visit-sheet', 'credit-analysis-sheet');
    state().selectedFarmer = null;
    state().activeMode = null;
    destroyMap();
  }

  async function submitJblVisit() {
    const farmer = state().selectedFarmer;
    if (!farmer) return;
    if (pendingJblWorkflowConflict) {
      el('jbl-workflow-conflict')?.focus();
      deps.showToast('Review the latest case before submitting this draft.', 'error');
      return;
    }
    const visitStatus = el('jbl-status')?.value || '';
    if (!commitJblDisplayDate({ showError: false })) {
      showJblFieldErrors({ visit_date: 'Enter a valid visit date in dd-mm-yy format.' });
      return;
    }
    if (showJblFieldErrors(validateJblVisitFields())) return;

    stopJblLiveCamera();
    if (!selectedJblFilesAreValid()) return;
    if (!navigator.onLine) {
      deps.showToast('You are offline. Keep the form open and retry when connected.', 'error');
      return;
    }
    const btn = el('btn-submit-jbl');
    const formData = new FormData();
    const key = requestId();
    formData.set('client_request_id', key);
    formData.set('workflow_revision', String(Number(farmer.workflow_revision || 1)));
    formData.set('visit_date', el('jbl-date')?.value || '');
    formData.set('visit_status', visitStatus);
    formData.set('officer', el('jbl-officer')?.value || '');
    formData.set('county', el('jbl-county')?.value || '');
    formData.set('sub_county', el('jbl-sub-county')?.value || '');
    formData.set('village', el('jbl-village')?.value || '');
    formData.set('comment', el('jbl-comment')?.value || '');
    if (acceptedVoiceAttempts.jbl_visit_comment) formData.set('voice_transcription_id', acceptedVoiceAttempts.jbl_visit_comment);
    formData.set('capture_latitude', el('jbl-lat')?.value || '');
    formData.set('capture_longitude', el('jbl-lng')?.value || '');
    formData.set('location_unavailable_reason', el('jbl-location-unavailable')?.value || '');
    jblMediaSelections.LAF.forEach(item => formData.append('laf_files', item.file));
    jblMediaSelections.JBL_VISIT_PHOTO.forEach(item => formData.append('jbl_visit_photo_files', item.file));
    el('sheet-form')?.querySelectorAll('.jbl-media-icon-button, .jbl-media-preview-open, .jbl-media-remove').forEach(control => {
      control.classList.add('is-disabled');
      control.setAttribute('aria-disabled', 'true');
      if (control.matches('button')) control.disabled = true;
    });
    el('sheet-form')?.querySelectorAll('input[type="file"]').forEach(input => { input.disabled = true; });
    deps.setButtonLoading(btn, true, 'Saving visit and evidence…');
    // Do not abort a slow multipart request: it may already be committing on
    // the server. The stable request key makes an explicit retry safe instead.
    const slowUploadNotice = window.setTimeout(() => {
      deps.showToast('Upload is taking longer than usual. Keep this screen open until it confirms that the visit was saved.', 'info');
    }, 12000);
    let response;
    try {
      response = await deps.portalApi.postForm(
        '/jbl-queue/' + farmer.id + '/complete-visit/',
        formData,
        deps.tg,
        { 'X-CSRFToken': deps.getCookie('csrftoken') || '', 'X-Request-ID': key, 'Idempotency-Key': key },
      );
    } catch (error) {
      deps.showToast(error.message || 'The upload could not be completed. Keep the form open and retry when connected.', 'error');
      return;
    } finally {
      window.clearTimeout(slowUploadNotice);
      deps.setButtonLoading(btn, false);
      el('sheet-form')?.querySelectorAll('.jbl-media-icon-button, .jbl-media-preview-open, .jbl-media-remove').forEach(control => {
        control.classList.remove('is-disabled');
        control.removeAttribute('aria-disabled');
        if (control.matches('button')) control.disabled = false;
      });
      el('sheet-form')?.querySelectorAll('input[type="file"]').forEach(input => { input.disabled = false; });
    }
    const { ok, data } = response;
    if (!ok) {
      if (data.code === 'workflow_revision_conflict') {
        showJblWorkflowConflict(
          Number(data.expected_revision || farmer.workflow_revision || 1),
          Number(data.actual_revision || farmer.workflow_revision || 1),
          data.error,
        );
        return;
      }
      if (data.field_errors && showJblFieldErrors(data.field_errors)) return;
      const recovered = data.evidence_saved ? ' Evidence was saved; retry to log the visit.' : '';
      deps.showToast((data.error || 'Visit could not be saved.') + recovered, 'error');
      return;
    }
    const uploaded = Number(data.stored_count || 0);
    deps.showToast(data.already_completed ? 'This visit was already saved.' : `JBL visit logged${uploaded ? ` with ${uploaded} new evidence file${uploaded === 1 ? '' : 's'}` : ''}.`, 'success');
    await clearJblVisitDraft(farmer);
    closeSheet({ saveDraft: false });
    deps.reloadCurrentQueue();
    deps.loadDashboard();
  }

  async function submitCreditDecision() {
    const farmer = state().selectedFarmer;
    if (!farmer) return;
    const decision = el('credit-decision')?.value || '';
    const imabCreated = el('credit-imab')?.value || '';
    const customerNo = (el('credit-customer-no')?.value || '').replace(/[^0-9]/g, '');
    const productConfiguration = collectProductConfiguration();
    if (!decision) return deps.showToast('Please select a decision', 'error');
    if (imabCreated !== 'Yes') return deps.showToast('Create the customer in IMAB before sending this case to Head of Rural review.', 'error');
    if (!customerNo) return deps.showToast('Enter the IMAB Customer No before sending this case to Head of Rural review.', 'error');

    const btn = el('btn-submit-credit');
    deps.setButtonLoading(btn, true, 'Saving...');
    const { ok, data } = await deps.apiFetch('/credit-queue/' + farmer.id + '/', {
      method: 'POST',
      body: JSON.stringify({
        request_id: requestId(), workflow_revision: Number(farmer.workflow_revision || 1),
        decision, imab_created: imabCreated, customer_no: customerNo,
        product_requirement_evidence: productConfiguration.requirementEvidence,
        product_custom_values: productConfiguration.customValues,
      }),
    });
    deps.setButtonLoading(btn, false);
    if (!ok) return deps.showToast(data.error || 'Save failed', 'error');
    deps.showToast('Credit decision saved', 'success');
    await clearWorkflowDraft(farmer, 'credit');
    closeSheet({ saveDraft: false });
    deps.reloadCurrentQueue();
    deps.loadDashboard();
  }

  async function submitFinalDecision() {
    const farmer = state().selectedFarmer;
    if (!farmer) return;
    const finalDecision = el('final-decision')?.value || '';
    const decisionComment = el('final-comment')?.value || '';
    const repaymentDate = el('final-repayment-date')?.value || '';
    const repaymentTenor = el('final-repayment-tenor')?.value || '';
    const productConfiguration = collectProductConfiguration();
    if (!finalDecision) return deps.showToast('Please select a final decision', 'error');

    const btn = el('btn-submit-final');
    deps.setButtonLoading(btn, true, 'Saving...');
    const { ok, data } = await deps.apiFetch('/final-review-queue/' + farmer.id + '/', {
      method: 'POST',
      body: JSON.stringify({
        request_id: requestId(),
        workflow_revision: Number(farmer.workflow_revision || 1),
        final_decision: finalDecision,
        decision_comment: decisionComment,
        voice_transcription_id: acceptedVoiceAttempts.final_decision_comment || '',
        repayment_date: repaymentDate,
        repayment_tenor: repaymentTenor,
        product_requirement_evidence: productConfiguration.requirementEvidence,
        product_custom_values: productConfiguration.customValues,
      }),
    });
    deps.setButtonLoading(btn, false);
    if (!ok) return deps.showToast(data.error || 'Save failed', 'error');
    deps.showToast('Final review saved', 'success');
    await clearWorkflowDraft(farmer, 'final_review');
    closeSheet({ saveDraft: false });
    deps.reloadCurrentQueue();
    deps.loadDashboard();
  }

  function bindEvents() {
    if (document.documentElement.dataset.portalSheetCloseBound) return;
    document.documentElement.dataset.portalSheetCloseBound = 'true';
    document.addEventListener('click', event => {
      if (event.target.closest('#sheet-close')) {
        closeSheet();
        return;
      }
      if (event.target.closest('#media-viewer-close')) {
        closeMediaViewer();
        return;
      }
      const selectionAction = event.target.closest('[data-selection-preview-action]');
      if (selectionAction) {
        const action = selectionAction.dataset.selectionPreviewAction;
        if (action === 'previous') navigateSelectedJblPreview(-1);
        if (action === 'next') navigateSelectedJblPreview(1);
        if (action === 'remove') {
          removeActiveJblPreview(selectionAction.dataset.mediaCategory, selectionAction.dataset.mediaItemId);
        }
        return;
      }
      if (event.target.closest('#sheet-map-refresh')) {
        refreshMap();
        return;
      }
      const overlay = event.target.closest('#sheet-overlay');
      if (overlay && event.target === overlay) closeSheet();
      const mediaOverlay = event.target.closest('#media-viewer-overlay');
      if (mediaOverlay && event.target === mediaOverlay) closeMediaViewer();
    });
  }

  async function restoreJblVisitAfterWebViewReturn() {
    const farmerId = sessionStorage.getItem(JBL_ACTIVE_DRAFT_KEY);
    if (!farmerId || state().selectedFarmer) return;
    try {
      const { ok, data } = await deps.apiFetch(`/farmers/${encodeURIComponent(farmerId)}/`);
      if (!ok || !data?.ok || !data.farmer) throw new Error('The draft case is no longer available.');
      openFarmerSheet(data.farmer, 'jbl_visit');
    } catch (_error) {
      sessionStorage.removeItem(JBL_ACTIVE_DRAFT_KEY);
    }
  }

  async function restoreWorkflowDraftAfterWebViewReturn() {
    if (state().selectedFarmer) return;
    let active;
    try { active = JSON.parse(sessionStorage.getItem(PORTAL_ACTIVE_WORKFLOW_DRAFT_KEY) || 'null'); } catch (_error) { active = null; }
    if (!active?.farmer_id || !WORKFLOW_DRAFT_CONFIG[active.mode]) return;
    try {
      const { ok, data } = await deps.apiFetch(`/farmers/${encodeURIComponent(active.farmer_id)}/`);
      if (!ok || !data?.ok || !data.farmer) throw new Error('The draft case is no longer available.');
      openFarmerSheet(data.farmer, active.mode);
    } catch (_error) {
      sessionStorage.removeItem(PORTAL_ACTIVE_WORKFLOW_DRAFT_KEY);
    }
  }

  function init(initialDeps) {
    deps = initialDeps;
    bindEvents();
    deps.tg?.onEvent?.('deactivated', () => {
      if (state().activeMode === 'jbl_visit') {
        saveJblVisitDraft(state().selectedFarmer, { immediate: true });
        stopJblLiveCamera();
      }
      if (WORKFLOW_DRAFT_CONFIG[state().activeMode]) {
        saveWorkflowDraft(state().selectedFarmer, state().activeMode, { immediate: true });
      }
    });
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden' && state().activeMode === 'jbl_visit') {
        saveJblVisitDraft(state().selectedFarmer, { immediate: true });
        stopJblLiveCamera();
      }
      if (document.visibilityState === 'hidden' && WORKFLOW_DRAFT_CONFIG[state().activeMode]) {
        saveWorkflowDraft(state().selectedFarmer, state().activeMode, { immediate: true });
      }
    });
    window.addEventListener('pagehide', () => {
      if (state().activeMode === 'jbl_visit') {
        saveJblVisitDraft(state().selectedFarmer, { immediate: true });
        stopJblLiveCamera();
      }
      if (WORKFLOW_DRAFT_CONFIG[state().activeMode]) saveWorkflowDraft(state().selectedFarmer, state().activeMode, { immediate: true });
    });
    window.addEventListener('pageshow', () => {
      restoreJblVisitAfterWebViewReturn();
      restoreWorkflowDraftAfterWebViewReturn();
    });
    window.setTimeout(restoreJblVisitAfterWebViewReturn, 0);
    window.setTimeout(restoreWorkflowDraftAfterWebViewReturn, 0);
  }

  window.PortalMiniAppFarmerSheet = {
    init,
    openFarmerSheet,
    closeSheet,
    renderCase360,
  };
})();
