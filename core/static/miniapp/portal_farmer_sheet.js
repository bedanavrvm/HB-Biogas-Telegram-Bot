(function () {
  'use strict';

  let deps = null;
  let mapInstance = null;
  let mapMarker = null;
  let currentMapLocation = null;
  let activeMediaObjectUrl = '';
  let jblServerDraft = null;
  let jblServerDraftFarmerId = '';
  let jblDraftInputVersion = 0;
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

  function voiceWidget(fieldName, inputId) {
    if (!state().voiceInput?.enabled || !state().voiceInput?.fields?.includes(fieldName)) return '';
    return `<div class="voice-input" data-voice-field="${fieldName}" data-input-id="${inputId}">
      <button type="button" class="voice-record-button" data-voice-action="record" aria-pressed="false" aria-label="Dictate comment" title="Dictate comment">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0M12 17v5M8 22h8"/></svg><span class="voice-record-label sr-only">Dictate</span>
      </button>
      <small class="voice-status" aria-live="polite" hidden></small>
      <div class="voice-review" hidden>
        <strong>Review transcription</strong><p class="voice-transcript"></p>
        <div class="voice-review-actions">
          <button type="button" class="secondary" data-voice-action="append">Append</button>
          <button type="button" class="secondary" data-voice-action="replace">Replace</button>
          <button type="button" class="secondary" data-voice-action="retry">Retry</button>
          <button type="button" class="secondary" data-voice-action="cancel">Cancel</button>
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
      };
      widget.querySelector('.voice-transcript').textContent = data.text;
      widget.querySelector('.voice-review').hidden = false;
      widget.querySelector('[data-voice-action="retry"]').disabled = !data.retry_available;
      setVoiceStatus(widget, 'Choose Append or Replace after checking the text.', 'review');
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
    const stageRows = (tat.stages || []).map((stage, index) => `<article class="case360-tat-row"><span class="case360-stage-number">${index + 1}</span><div><strong>${deps.escapeHtml(stage.label)}</strong><small>${stage.completed_at ? 'Completed' : stage.started_at ? 'In progress' : 'Not tracked'}</small>${stage.business_minutes != null ? `<details class="tat-business-time"><summary>Show business-hours time</summary><small>${deps.escapeHtml(formatTatMinutes(stage.business_minutes))}</small></details>` : ''}</div><div><strong>${stage.wall_clock_minutes == null ? '-' : deps.escapeHtml(formatTatMinutes(stage.wall_clock_minutes))}</strong><span class="case360-sla ${deps.escapeHtml(stage.status || '')}">${deps.escapeHtml(humanLabel(stage.status || ''))}</span></div></article>`).join('');
    const docLinks = [
      ...(documents.visit_media || []).map((url, index) => ({ name: `Visit media ${index + 1}`, url })),
      documents.requisition,
      documents.invoice,
      ...(documents.payments || []),
    ].filter(Boolean);
    const tabs = [
      ['overview', 'Overview', ''],
      ['timeline', 'Timeline', timeline.length],
      ['tat', 'TAT', (tat.stages || []).length],
      ['documents', 'Documents', docLinks.length],
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
        <div class="case360-tat-total"><div><span>Official TAT (wall clock)</span><strong>${tat.wall_clock_minutes == null ? '-' : deps.escapeHtml(formatTatMinutes(tat.wall_clock_minutes))}</strong>${tat.business_minutes != null ? `<details class="tat-business-time"><summary>Show business-hours time</summary><small>${deps.escapeHtml(formatTatMinutes(tat.business_minutes))}</small></details>` : ''}</div><span class="case360-sla ${deps.escapeHtml(tat.status || '')}">${deps.escapeHtml(humanLabel(tat.status || ''))}</span></div><div class="case360-tat-list">${stageRows}</div>
      </section>
      <section class="case360-panel" role="tabpanel" data-case360-panel="documents" hidden><div class="case360-panel-heading"><div><h3>Case Documents</h3><p>Files connected to this customer and order</p></div></div><div class="case360-documents">${docLinks.length ? docLinks.map(doc => `<a class="case360-document" href="${deps.escapeHtml(doc.url)}" target="_blank" rel="noopener"><span>DOC</span><strong>${deps.escapeHtml(doc.name || 'Document')}</strong><b>Open</b></a>`).join('') : '<div class="empty-state">No linked documents.</div>'}</div></section>
      <section class="case360-panel" role="tabpanel" data-case360-panel="quality" hidden><div class="case360-panel-heading"><div><h3>Data Quality</h3><p>Validation checks requiring staff attention</p></div></div>${validation.length ? `<div class="case360-quality-list">${validation.map(issue => `<article><span>!</span><div><strong>${deps.escapeHtml(humanLabel(issue.field))}</strong><p>${deps.escapeHtml(issue.message)}</p></div></article>`).join('')}</div>` : '<div class="case360-valid"><strong>All checks passed</strong><span>All monitored business fields are valid.</span></div>'}</section>`;
    root.hidden = false;
    root.querySelectorAll('[data-case360-tab]').forEach(button => button.addEventListener('click', () => {
      root.querySelectorAll('[data-case360-tab]').forEach(item => {
        item.classList.toggle('active', item === button);
        item.setAttribute('aria-selected', String(item === button));
      });
      root.querySelectorAll('[data-case360-panel]').forEach(panel => { panel.hidden = panel.dataset.case360Panel !== button.dataset.case360Tab; });
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
        ['HBG Visit', deps.fmtDate(farmer.sign_date)],
        ['HB Sales Person', deps.fmt(farmer.hb_sales_person)],
        ['Current JBL Status', deps.fmt(farmer.jbl_visit_status)],
      ],
      credit: [
        ['JBL Visit', deps.fmtDate(farmer.jbl_visit_date)],
        ['JBL Officer', deps.fmt(farmer.jbl_officer)],
        ['JBL Status', deps.fmt(farmer.jbl_visit_status)],
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

    el('sheet-name').textContent = farmer.customer_name || 'Unknown Farmer';
    const location = deps.locationText(farmer);
    el('sheet-sub').textContent = location !== '-' ? location : (farmer.primary_phone || '');

    const infoFields = summaryFields(farmer, mode);

    const mediaCount = Number(farmer.jbl_media_count || 0);
    el('sheet-info').innerHTML = infoFields.map(([label, value]) =>
      `<li class="info-row"><span class="ir-label">${deps.escapeHtml(label)}</span><span class="ir-value">${value}</span></li>`
    ).join('');
    const mediaSection = el('sheet-client-media');
    if (mediaSection) {
      const canViewMedia = hasCapability('portal.jbl_media.view') && mediaCount >= 1;
      mediaSection.hidden = !canViewMedia;
      mediaSection.innerHTML = canViewMedia
        ? `<button type="button" class="btn btn-secondary sheet-client-media-toggle" id="btn-view-client-media" aria-expanded="false" data-collapsed-label="View ${mediaCount} media file${mediaCount === 1 ? '' : 's'}">View ${mediaCount} media file${mediaCount === 1 ? '' : 's'}</button><div id="final-client-media" class="media-links client-media-links" hidden></div>`
        : '';
      el('btn-view-client-media')?.addEventListener('click', () => toggleClientMedia(farmer.id));
    }
    const caseToggle = el('case360-toggle');
    caseToggle.textContent = 'Open Case History';
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
      formEl.innerHTML = buildJblForm(farmer);
      footerEl.innerHTML = '<button class="primary" id="btn-submit-jbl">Log JBL Visit</button>';
      el('btn-submit-jbl').addEventListener('click', submitJblVisit);
      wireGpsButton();
      wireJblVisitDraft(farmer);
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
    el('sheet-overlay').classList.add('open');
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

  function buildJblForm(farmer) {
    const today = new Date().toISOString().split('T')[0];
    const hbgVisitDate = farmer.hbg_visit_date || '';
    const defaultVisitDate = hbgVisitDate && hbgVisitDate > today ? hbgVisitDate : today;
    const statusOptions = state().metaStatuses.filter(status => status !== 'JBL to Schedule Visit').map(status =>
      `<option value="${deps.escapeHtml(status)}"${farmer.jbl_visit_status === status ? ' selected' : ''}>${deps.escapeHtml(status)}</option>`
    ).join('');
    const countyOptions = (state().metaCounties || []).map(county =>
      `<option value="${deps.escapeHtml(county)}"></option>`
    ).join('');
    const mediaFields = hasCapability('portal.jbl_media.write') ? `
        <div class="form-row media-upload-row form-row-wide">
          <label>Visit Media</label>
          <div class="media-upload-control">
            <label class="media-category-upload media-file-tile" for="jbl-laf-media">
              <span>LAF document(s)</span><strong id="jbl-laf-media-name">Tap to choose file(s)</strong>
              <small>PDF, JPG or PNG. Required before forwarding.</small>
              <input class="sr-only" type="file" id="jbl-laf-media" name="laf_files" multiple accept="application/pdf,.pdf,image/jpeg,image/png,.jpg,.jpeg,.png">
            </label>
            <label class="media-category-upload media-file-tile" for="jbl-visit-photo-media">
              <span>JBL visit photo(s)</span><strong id="jbl-visit-photo-media-name">Tap to choose photo(s)</strong>
              <small>Image only. Required before forwarding.</small>
              <input class="sr-only" type="file" id="jbl-visit-photo-media" name="jbl_visit_photo_files" multiple accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp">
            </label>
            ${farmer.jbl_media_count ? `<small class="form-row-wide">${farmer.jbl_media_count} existing Drive link${farmer.jbl_media_count === 1 ? '' : 's'} on this record.</small>` : ''}
          </div>
        </div>` : '';
    return `
      <div class="form-section form-grid">
        <div class="form-row"><label title="JBL visits follow the HBG visit and cannot be dated earlier.">Visit Date <span class="label-help" aria-hidden="true">?</span></label><input type="date" id="jbl-date" min="${deps.escapeHtml(hbgVisitDate)}" value="${deps.escapeHtml(farmer.jbl_visit_date || defaultVisitDate)}"></div>
        <div class="form-row"><label>Status / Outcome</label><select id="jbl-status"><option value="">- Select -</option>${statusOptions}</select></div>
        <div class="form-row"><label>Officer Name</label><input type="text" id="jbl-officer" placeholder="Your name" value="${deps.escapeHtml(farmer.jbl_officer || '')}"></div>
        <div class="form-row"><label>County</label><input type="text" id="jbl-county" list="jbl-county-options" placeholder="County" value="${deps.escapeHtml(farmer.county || '')}"><datalist id="jbl-county-options">${countyOptions}</datalist></div>
        <div class="form-row"><label>Constituency</label><input type="text" id="jbl-sub-county" placeholder="Constituency / sub-county" value="${deps.escapeHtml(farmer.sub_county || '')}"></div>
        <div class="form-row"><label>Village</label><input type="text" id="jbl-village" placeholder="Village / area" value="${deps.escapeHtml(farmer.village || '')}"></div>
        <div class="form-row form-row-wide"><label>Comment (optional)</label><textarea id="jbl-comment" rows="2" placeholder="Additional notes...">${deps.escapeHtml(farmer.jbl_visit_comment || '')}</textarea>${voiceWidget('jbl_visit_comment', 'jbl-comment')}</div>
        ${mediaFields}
        <div class="form-row form-row-wide gps-capture-row">
          <button type="button" id="btn-gps" class="secondary">Capture GPS Location</button>
          <div id="gps-coords" class="field-help">Not captured</div>
          <input type="hidden" id="jbl-lat" value="">
          <input type="hidden" id="jbl-lng" value="">
          <div id="jbl-location-unavailable-wrap" hidden>
            <label class="field-help" for="jbl-location-unavailable">GPS could not be captured. Explain why before forwarding.</label>
            <input type="text" id="jbl-location-unavailable" maxlength="255" placeholder="e.g. phone location was disabled">
          </div>
        </div>
        <p id="jbl-draft-state" class="field-help jbl-draft-state" aria-live="polite">Draft saves automatically. Files are never stored in a draft.</p>
      </div>
    `;
  }

  function jblDraftKey(farmerId) { return `portal:jbl-visit-draft:${farmerId}`; }
  const JBL_ACTIVE_DRAFT_KEY = 'portal:jbl-visit-active';

  function selectedFileLabel(files) {
    if (!files?.length) return 'Tap to choose file(s)';
    return files.length === 1 ? files[0].name : `${files.length} files selected`;
  }

  function updateJblFileLabel(inputId, labelId) {
    const input = el(inputId);
    const label = el(labelId);
    if (label) label.textContent = selectedFileLabel(Array.from(input?.files || []));
  }

  function jblVisitDraftValues() {
    const values = {};
    ['jbl-date', 'jbl-status', 'jbl-officer', 'jbl-county', 'jbl-sub-county', 'jbl-village', 'jbl-comment', 'jbl-lat', 'jbl-lng', 'jbl-location-unavailable'].forEach(id => {
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
      onSaving: () => setJblDraftState('Saving draft…', 'saving'),
      onSaved: () => setJblDraftState('Draft saved securely. Files must be selected again after Telegram closes.', 'saved'),
      onError: () => setJblDraftState('Draft is kept on this device. Keep the form open and retry when connected.', 'local-only'),
      onCleared: () => setJblDraftState('', ''),
    });
    return jblServerDraft;
  }

  function saveJblVisitDraft(farmer, { immediate = false } = {}) {
    if (!farmer?.id || !el('jbl-date')) return;
    const draft = { farmer_id: farmer.id, values: jblVisitDraftValues(), saved_at: Date.now() };
    try { sessionStorage.setItem(jblDraftKey(farmer.id), JSON.stringify(draft)); } catch (_error) {}
    const serverDraft = ensureJblServerDraft(farmer);
    if (!serverDraft || !navigator.onLine) return draft;
    const save = immediate ? serverDraft.save(draft) : serverDraft.schedule(draft);
    if (immediate && save?.catch) save.catch(() => {});
    return draft;
  }

  function restoreJblVisitDraft(farmer) {
    const draft = jblLocalDraft(farmer);
    if (applyJblVisitDraft(draft)) {
      setJblDraftState('Details restored on this device. Files must be selected again.', 'restored');
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
        setJblDraftState('Details restored from your secure draft. Files must be selected again.', 'restored');
      } else if (!localDraft) {
        setJblDraftState('Draft saves automatically. Files are never stored in a draft.', 'ready');
      }
    } catch (_error) {
      // A local copy still protects the current session. The status below is
      // deliberately informative rather than a disruptive autosave toast.
      if (!localDraft) setJblDraftState('Draft will save when your connection is available.', 'offline');
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
    const files = [
      ...Array.from(el('jbl-laf-media')?.files || []),
      ...Array.from(el('jbl-visit-photo-media')?.files || []),
    ];
    const oversize = files.find(file => file.size > maxBytes);
    if (oversize) {
      const maxMb = Math.round(maxBytes / (1024 * 1024));
      deps.showToast(`${oversize.name} is larger than the ${maxMb} MB evidence limit.`, 'error');
      return false;
    }
    return true;
  }

  function wireJblVisitDraft(farmer) {
    jblDraftInputVersion = 0;
    const localDraft = restoreJblVisitDraft(farmer);
    restoreJblVisitServerDraft(farmer, localDraft, jblDraftInputVersion);
    ['jbl-laf-media', 'jbl-visit-photo-media'].forEach((id, index) => {
      const labelId = index ? 'jbl-visit-photo-media-name' : 'jbl-laf-media-name';
      el(id)?.addEventListener('change', () => {
        updateJblFileLabel(id, labelId);
        jblDraftInputVersion += 1;
        saveJblVisitDraft(farmer);
      });
    });
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
      onSaving: () => setWorkflowDraftState('Saving draft…', 'saving'),
      onSaved: () => setWorkflowDraftState('Draft saved securely.', 'saved'),
      onError: () => setWorkflowDraftState('Draft is kept on this device. Keep the form open and retry when connected.', 'local-only'),
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
        setWorkflowDraftState('Details restored from your secure draft.', 'restored');
      } else if (!localDraft) {
        setWorkflowDraftState('Draft saves automatically.', 'ready');
      }
    } catch (_error) {
      if (!localDraft) setWorkflowDraftState('Draft will save when your connection is available.', 'offline');
    }
  }

  function wireWorkflowDraft(farmer, mode) {
    workflowDraftInputVersion = 0;
    const localDraft = localWorkflowDraft(farmer, mode);
    if (applyWorkflowDraft(localDraft, mode)) setWorkflowDraftState('Details restored on this device.', 'restored');
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
      <div class="form-section">
        ${spinReferences ? `<div class="credit-reference-panel"><div class="field-help"><strong>SPIN / CRB reference</strong> · reports already uploaded for this customer</div>${spinReferences}</div>` : ''}
        <div class="form-row"><label>Credit decision</label><select id="credit-decision"><option value="">- Select a decision -</option>${decisionOptions}</select></div>
        <div class="form-row"><label>IS CUSTOMER CREATED ON IMAB?</label><select id="credit-imab">${imabOptions}</select></div>
        <div class="form-row">
          <label>CUSTOMER NO</label>
          <input type="text" id="credit-customer-no" inputmode="numeric" pattern="[0-9]*" placeholder="IMAB customer number" value="${deps.escapeHtml(customerNoDisabled ? '' : (farmer.customer_no || ''))}"${customerNoDisabled ? ' disabled' : ''}>
          <small id="credit-imab-help" class="field-help">${customerNoDisabled ? 'Select Yes after IMAB creation before entering a customer number.' : 'Required before this case can move to Head of Rural review.'}</small>
        </div>
        <p id="workflow-draft-state" class="field-help jbl-draft-state" aria-live="polite">Draft saves automatically.</p>
      </div>
      ${farmer.jbl_visit_comment ? `<div class="info-row"><span class="ir-label">JBL Comment</span><span class="ir-value">${deps.escapeHtml(farmer.jbl_visit_comment)}</span></div>` : ''}
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
        button.textContent = button.dataset.collapsedLabel || 'View client media';
      }
      return;
    }
    target.hidden = false;
    if (button) {
      button.setAttribute('aria-expanded', 'true');
      button.textContent = 'Hide client media';
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
    if (content) content.replaceChildren();
    if (activeMediaObjectUrl) {
      URL.revokeObjectURL(activeMediaObjectUrl);
      activeMediaObjectUrl = '';
    }
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
      const response = await fetch(item.preview_url, {
        headers: mediaPreviewHeaders(),
        cache: 'no-store',
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.error || 'Could not open this client media.');
      }
      const blob = await response.blob();
      if (!blob.size) throw new Error('The media file was empty.');
      activeMediaObjectUrl = URL.createObjectURL(blob);
      const mimeType = String(blob.type || item.mime_type || '').toLowerCase();
      const safeName = deps.escapeHtml(item.name || 'Client media');
      content.innerHTML = mimeType.startsWith('image/')
        ? `<img class="media-viewer-image" src="${activeMediaObjectUrl}" alt="${safeName}">`
        : `<iframe class="media-viewer-document" sandbox="" src="${activeMediaObjectUrl}" title="${safeName}"></iframe>`;
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
    el('sheet-overlay')?.classList.remove('open');
    state().selectedFarmer = null;
    state().activeMode = null;
    destroyMap();
  }

  async function submitJblVisit() {
    const farmer = state().selectedFarmer;
    if (!farmer) return;
    const visitStatus = el('jbl-status')?.value || '';
    if (!visitStatus) {
      deps.showToast('Please select a visit status', 'error');
      return;
    }

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
    Array.from(el('jbl-laf-media')?.files || []).forEach(file => formData.append('laf_files', file));
    Array.from(el('jbl-visit-photo-media')?.files || []).forEach(file => formData.append('jbl_visit_photo_files', file));
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
    }
    const { ok, data } = response;
    if (!ok) {
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
    if (!decision) return deps.showToast('Please select a decision', 'error');
    if (imabCreated !== 'Yes') return deps.showToast('Create the customer in IMAB before sending this case to Head of Rural review.', 'error');
    if (!customerNo) return deps.showToast('Enter the IMAB Customer No before sending this case to Head of Rural review.', 'error');

    const btn = el('btn-submit-credit');
    deps.setButtonLoading(btn, true, 'Saving...');
    const { ok, data } = await deps.apiFetch('/credit-queue/' + farmer.id + '/', {
      method: 'POST',
      body: JSON.stringify({ request_id: requestId(), workflow_revision: Number(farmer.workflow_revision || 1), decision, imab_created: imabCreated, customer_no: customerNo }),
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
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden' && state().activeMode === 'jbl_visit') {
        saveJblVisitDraft(state().selectedFarmer, { immediate: true });
      }
      if (document.visibilityState === 'hidden' && WORKFLOW_DRAFT_CONFIG[state().activeMode]) {
        saveWorkflowDraft(state().selectedFarmer, state().activeMode, { immediate: true });
      }
    });
    window.addEventListener('pagehide', () => {
      if (state().activeMode === 'jbl_visit') saveJblVisitDraft(state().selectedFarmer, { immediate: true });
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
