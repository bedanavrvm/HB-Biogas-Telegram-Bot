(function () {
  'use strict';

  const tg = window.Telegram?.WebApp;
  const SECTIONS = [
    { key: 'applicant', label: 'Applicant', hint: 'Identity, contacts and residence' },
    { key: 'business', label: 'Business', hint: 'Enterprise and household finances' },
    { key: 'loan', label: 'Loan', hint: 'Product, purpose and repayment' },
    { key: 'security', label: 'Security', hint: 'Assets pledged for the facility' },
    { key: 'guarantors', label: 'Guarantors', hint: 'Guarantor and relationship details' },
    { key: 'review', label: 'Review', hint: 'Confirm details against the filled LAF' },
  ];
  const FULL_WIDTH = new Set([
    'applicant_residence_address', 'employer_business_address', 'loan_purpose',
    'security_1_description', 'guarantor_1_business_location', 'guarantor_1_residence_location',
  ]);
  let products = [];
  let applications = [];
  let current = null;
  let step = 0;
  let saveTimer = null;
  let previewUrl = '';
  let previewPage = 1;
  let previewZoom = 100;
  let previewPageCount = 1;
  let previewRequestId = '';
  let previewedRevision = null;
  let dirty = false;

  function requestKey(prefix) {
    return `${prefix}-${window.crypto?.randomUUID ? window.crypto.randomUUID() : Date.now()}`;
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
          ...(tg?.initData ? { 'X-Telegram-Init-Data': tg.initData } : {}),
          ...(requestOptions.headers || {}),
        },
      });
      const contentType = String(response.headers.get('Content-Type') || '');
      if (contentType.startsWith('application/pdf') || contentType.startsWith('image/')) return { ok: response.ok, status: response.status, blob: await response.blob(), pageCount: Number(response.headers.get('X-Preview-Page-Count') || 1) };
      return { ok: response.ok, status: response.status, data: await response.json().catch(() => ({})) };
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

  function sectionFor(key) {
    if (key.startsWith('guarantor_')) return 'guarantors';
    if (key.startsWith('security_')) return 'security';
    if (['business_location', 'business_type', 'employer_business_address', 'monthly_income', 'net_income', 'monthly_expenses', 'monthly_household_expenses'].includes(key)) return 'business';
    if (key.startsWith('applicant_') || ['borrower_full_name', 'deponent_full_name', 'deponent_id_number'].includes(key)) return 'applicant';
    if (['loan_product', 'loan_product_other', 'loan_amount', 'loan_purpose', 'own_contribution', 'repayment_period', 'project_cost', 'number_of_weeks', 'installment_amount', 'penalty_rate', 'amount_advanced', 'interest_rate', 'loan_agreement_repayment_period', 'approval_amount', 'acknowledgement_amount', 'acknowledgement_recipient_name'].includes(key)) return 'loan';
    return 'business';
  }

  function fieldsFor(sectionKey) {
    return (current?.form_schema?.fields || []).filter(field => sectionFor(field.key) === sectionKey);
  }

  function collectPayload() {
    const payload = { ...(current?.form_payload || {}) };
    root()?.querySelectorAll('[data-field]').forEach(input => {
      if (input.value === '') payload[input.dataset.field] = '';
      else if (input.options && ['true', 'false'].includes(input.value)) payload[input.dataset.field] = input.value === 'true';
      else payload[input.dataset.field] = input.value;
    });
    return payload;
  }

  function fieldInput(field, value, disabled) {
    const key = escapeHtml(field.key);
    const label = escapeHtml(normalizeLabel(field));
    const classes = `laf-field${FULL_WIDTH.has(field.key) ? ' laf-field-wide' : ''}`;
    const required = field.required ? '<span class="required-mark" aria-label="required">*</span>' : '';
    let control = '';
    if (field.type === 'choice') {
      const options = (field.options || []).map(option => `<option value="${escapeHtml(option)}"${value === option ? ' selected' : ''}>${escapeHtml(option)}</option>`).join('');
      control = `<select data-field="${key}"${disabled ? ' disabled' : ''}><option value="">Choose</option>${options}</select>`;
    } else if (field.type === 'boolean') {
      control = `<select data-field="${key}"${disabled ? ' disabled' : ''}><option value="">Choose</option><option value="true"${value === true ? ' selected' : ''}>Yes</option><option value="false"${value === false ? ' selected' : ''}>No</option></select>`;
    } else {
      const type = field.type === 'date' ? 'date' : field.type === 'money' ? 'number' : field.type === 'phone' ? 'tel' : 'text';
      const prefix = field.type === 'money' ? '<span class="input-prefix">KES</span>' : '';
      control = `<div class="input-wrap${prefix ? ' has-prefix' : ''}">${prefix}<input data-field="${key}" type="${type}" value="${escapeHtml(value ?? '')}"${field.type === 'money' ? ' inputmode="decimal" min="0" step="0.01"' : ''}${field.type === 'national_id' ? ' inputmode="numeric"' : ''}${disabled ? ' disabled' : ''}></div>`;
    }
    return `<label class="${classes}" data-field-wrap="${key}"><span>${label}${required}</span>${control}<small class="field-error" aria-live="polite"></small></label>`;
  }

  function sectionErrors(sectionKey) {
    const payload = collectPayload();
    const errors = {};
    fieldsFor(sectionKey).forEach(field => {
      const value = payload[field.key];
      if (field.required && (value === undefined || value === null || value === '')) errors[field.key] = 'Required';
    });
    return errors;
  }

  function showErrors(errors) {
    root()?.querySelectorAll('[data-field-wrap]').forEach(wrapper => {
      const message = errors[wrapper.dataset.fieldWrap] || '';
      wrapper.classList.toggle('invalid', Boolean(message));
      const output = wrapper.querySelector('.field-error');
      if (output) output.textContent = message;
    });
  }

  async function saveDraft(showError) {
    if (!current || !['draft', 'correction_required'].includes(current.status)) return true;
    if (!dirty) return true;
    const payload = collectPayload();
    localStorage.setItem(draftKey(current.id), JSON.stringify({ revision: current.revision, payload, savedAt: Date.now() }));
    setSaveState('Saving…', 'saving');
    const key = requestKey('save');
    const result = await apiFetch(`/applications/${current.id}/`, {
      method: 'PATCH', headers: { 'Idempotency-Key': key, 'X-Request-ID': key },
      body: JSON.stringify({ revision: current.revision, form_payload: payload, request_id: key }),
    });
    if (!result.ok || !result.data?.ok) {
      setSaveState('Saved on phone', 'offline');
      if (showError) showToast(result.data?.error || 'Draft remains on this phone. Reconnect and try again.', true);
      return false;
    }
    current = result.data.application;
    dirty = false;
    previewedRevision = null;
    localStorage.removeItem(draftKey(current.id));
    setSaveState('Saved', 'saved');
    return true;
  }

  function setSaveState(text, state) {
    const element = document.getElementById('origination-save-status');
    if (element) { element.textContent = text; element.dataset.state = state; }
  }

  function scheduleSave() {
    dirty = true;
    setSaveState('Unsaved changes', 'dirty');
    window.clearTimeout(saveTimer);
    saveTimer = window.setTimeout(() => saveDraft(false), 900);
  }

  function progressMarkup() {
    return `<nav class="wizard-progress" aria-label="Application sections">${SECTIONS.map((item, index) => `<button type="button" class="wizard-step${index === step ? ' active' : ''}${index < step ? ' complete' : ''}" data-step="${index}"><span>${index < step ? '✓' : index + 1}</span><small>${item.label}</small></button>`).join('')}</nav>`;
  }

  function reviewMarkup(values) {
    return `<div class="review-intro"><div><p class="eyebrow">Final check</p><h3>Review the application</h3><p>Open each section to correct details, then inspect the populated two-page LAF.</p></div><button type="button" class="btn btn-primary" id="origination-preview">Preview filled document</button></div>
      <div class="review-sections">${SECTIONS.slice(0, -1).map((section, index) => {
        const fields = fieldsFor(section.key);
        const completed = fields.filter(field => values[field.key] !== '' && values[field.key] != null).length;
        return `<button type="button" class="review-card" data-edit-step="${index}"><span><strong>${section.label}</strong><small>${completed} of ${fields.length} fields completed</small></span><span>Edit →</span></button>`;
      }).join('')}</div>`;
  }

  function actionMarkup(editable) {
    if (!editable) {
      if (current.status === 'ready_for_review') return '<button class="btn btn-secondary" data-review="request_correction">Request correction</button><button class="btn btn-danger" data-review="decline">Decline</button><button class="btn btn-primary" data-review="approve">Approve</button>';
      if (current.status === 'reviewed') return '<button class="btn btn-primary" id="origination-prepare-signing">Prepare signing package</button>';
      return '';
    }
    return `${step > 0 ? '<button class="btn btn-secondary" id="wizard-previous">Previous</button>' : '<span></span>'}${step < SECTIONS.length - 1 ? '<button class="btn btn-primary" id="wizard-next">Save & continue</button>' : '<button class="btn btn-primary" id="origination-submit">Submit for review</button>'}`;
  }

  function renderEditor(application, requestedStep) {
    current = application;
    step = Number.isInteger(requestedStep) ? requestedStep : step;
    tg?.BackButton?.show();
    let local = null;
    try { local = JSON.parse(localStorage.getItem(draftKey(application.id)) || 'null'); } catch (_) { localStorage.removeItem(draftKey(application.id)); }
    dirty = Boolean(local?.revision === application.revision);
    if (dirty) current.form_payload = local.payload;
    const values = collectPayload();
    const editable = ['draft', 'correction_required'].includes(application.status);
    const section = SECTIONS[step];
    const content = section.key === 'review' ? reviewMarkup(values) : `<div class="section-title"><div><p class="eyebrow">Step ${step + 1} of ${SECTIONS.length}</p><h3>${section.label}</h3><p>${section.hint}</p></div><button type="button" class="preview-link" id="origination-preview-early">Preview PDF</button></div><div class="laf-grid">${fieldsFor(section.key).map(field => fieldInput(field, values[field.key], !editable || field.editable === false)).join('')}</div>`;
    root().innerHTML = `<div class="editor-top"><button type="button" class="icon-button" id="origination-back" aria-label="Back to applications">←</button><div><strong>${escapeHtml(application.reference_number)}</strong><small>${escapeHtml(application.product_name)}</small></div><span class="status-chip status-${escapeHtml(application.status)}">${escapeHtml(application.status.replaceAll('_', ' '))}</span></div>${progressMarkup()}<section class="wizard-card">${content}</section><footer class="wizard-actions"><span id="origination-save-status" data-state="${local ? 'offline' : 'saved'}">${local ? 'Recovered from phone' : 'Saved'}</span><div>${actionMarkup(editable)}</div></footer>`;
    bindEditor(editable);
  }

  function bindEditor(editable) {
    document.getElementById('origination-back').onclick = async () => {
      if (!editable || await saveDraft(true)) renderList();
    };
    root().querySelectorAll('.wizard-step').forEach(button => button.onclick = async () => { if (editable && !(await saveDraft(true))) return; step = Number(button.dataset.step); renderEditor(current, step); });
    root().querySelectorAll('[data-edit-step]').forEach(button => button.onclick = () => renderEditor(current, Number(button.dataset.editStep)));
    if (editable) root().querySelector('.laf-grid')?.addEventListener('input', scheduleSave);
    document.getElementById('wizard-previous')?.addEventListener('click', async () => { if (await saveDraft(true)) renderEditor(current, step - 1); });
    document.getElementById('wizard-next')?.addEventListener('click', async () => {
      const errors = sectionErrors(SECTIONS[step].key); showErrors(errors);
      if (Object.keys(errors).length) return showToast('Complete the required fields in this section.', true);
      if (await saveDraft(true)) renderEditor(current, step + 1);
    });
    document.getElementById('origination-preview')?.addEventListener('click', openPreview);
    document.getElementById('origination-preview-early')?.addEventListener('click', openPreview);
    document.getElementById('origination-submit')?.addEventListener('click', async () => {
      if (!(await saveDraft(true))) return;
      if (previewedRevision !== current.revision) return showToast('Preview the filled document for this saved revision before submitting.', true);
      const result = await postJson(`/applications/${current.id}/submit/`, { revision: current.revision });
      if (!result.ok) return showToast(result.data?.error || 'Could not submit the application.', true);
      await load();
    });
    root().querySelectorAll('[data-review]').forEach(button => button.onclick = async () => {
      const decision = button.dataset.review;
      const reason = decision === 'approve' ? '' : window.prompt('Record the reason for this decision:');
      if (decision !== 'approve' && !reason) return;
      const result = await postJson(`/applications/${current.id}/review/`, { revision: current.revision, decision, reason });
      if (!result.ok) return showToast(result.data?.error || 'Could not record the review.', true);
      await load();
    });
    document.getElementById('origination-prepare-signing')?.addEventListener('click', async () => {
      const result = await postJson(`/applications/${current.id}/prepare-signing/`, { revision: current.revision });
      if (!result.ok) return showToast(result.data?.error || 'Could not prepare signing.', true);
      await load();
    });
  }

  async function openPreview() {
    if (['draft', 'correction_required'].includes(current.status) && !(await saveDraft(true))) return;
    previewedRevision = current.revision;
    previewPage = 1; previewZoom = 100; previewPageCount = 1;
    previewRequestId = requestKey('preview');
    const overlay = document.getElementById('document-preview-overlay');
    overlay.hidden = false;
    overlay.setAttribute('aria-hidden', 'false');
    tg?.BackButton?.show();
    await loadPreviewPage();
  }

  async function loadPreviewPage() {
    showToast('Generating filled PDF…');
    const key = previewRequestId || requestKey('preview');
    const result = await apiFetch(`/applications/${current.id}/preview/`, { method: 'POST', headers: { 'Idempotency-Key': key, 'X-Request-ID': key }, body: JSON.stringify({ revision: current.revision, request_id: key, preview_format: 'image', page: previewPage }) });
    if (!result.ok || !result.blob) { closePreview(); return showToast(result.data?.error || 'Could not generate the filled document.', true); }
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = URL.createObjectURL(result.blob);
    previewPageCount = Math.max(1, result.pageCount || 1);
    updatePreviewFrame();
  }

  function updatePreviewFrame() {
    const image = document.getElementById('document-preview-image');
    if (image && previewUrl) { image.src = previewUrl; image.style.width = `${previewZoom}%`; }
    const page = document.getElementById('preview-page'); if (page) page.textContent = `Page ${previewPage} of ${previewPageCount}`;
    const zoom = document.getElementById('preview-zoom'); if (zoom) zoom.textContent = `${previewZoom}%`;
    const previous = document.getElementById('preview-previous'); if (previous) previous.disabled = previewPage <= 1;
    const next = document.getElementById('preview-next'); if (next) next.disabled = previewPage >= previewPageCount;
  }

  function closePreview() {
    const overlay = document.getElementById('document-preview-overlay');
    if (overlay) { overlay.hidden = true; overlay.setAttribute('aria-hidden', 'true'); }
    const image = document.getElementById('document-preview-image'); if (image) image.removeAttribute('src');
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = '';
    previewRequestId = '';
  }

  function showToast(message, error) {
    const toast = document.getElementById('origination-toast');
    if (!toast) return;
    toast.textContent = message; toast.classList.toggle('error', Boolean(error)); toast.hidden = false;
    window.clearTimeout(showToast.timer); showToast.timer = window.setTimeout(() => { toast.hidden = true; }, 3500);
  }

  function renderList() {
    current = null; step = 0; dirty = false; closePreview(); tg?.BackButton?.hide();
    const counts = applications.reduce((result, item) => { result[item.status] = (result[item.status] || 0) + 1; return result; }, {});
    const options = products.map(item => `<option value="${escapeHtml(item.product_key)}">${escapeHtml(item.name)}</option>`).join('');
    const cards = applications.map(item => `<button type="button" class="application-card" data-application-id="${item.id}"><span><strong>${escapeHtml(item.reference_number)}</strong><small>${escapeHtml(item.product_name)} · ${escapeHtml(item.branch || 'No branch')}</small></span><span class="status-chip status-${escapeHtml(item.status)}">${escapeHtml(item.status.replaceAll('_', ' '))}</span></button>`).join('');
    root().innerHTML = `<section class="app-hero"><div><p class="eyebrow">Paperless lending</p><h2>Applications</h2><p>Capture details once and place them directly onto the approved LAF.</p></div></section><div class="metric-grid"><article><strong>${counts.draft || 0}</strong><span>Drafts</span></article><article><strong>${counts.ready_for_review || 0}</strong><span>Review</span></article><article><strong>${counts.correction_required || 0}</strong><span>Corrections</span></article><article><strong>${(counts.reviewed || 0) + (counts.signing_pending || 0)}</strong><span>Signing</span></article></div>${products.length ? `<form id="origination-create" class="create-card"><div><h3>New application</h3><p>Start with the approved partnership LAF.</p></div><label><span>Product</span><select name="product_key" required>${options}</select></label><label><span>Branch</span><input name="branch" required autocomplete="organization"></label><button class="btn btn-primary" type="submit">Start application</button></form>` : '<div class="notice error">No approved origination product is active.</div>'}<div class="list-heading"><h3>Recent applications</h3><button type="button" class="text-button" id="origination-list-refresh">Refresh</button></div><div class="application-list">${cards || '<div class="empty-state"><strong>No applications yet</strong><span>Start the first application above.</span></div>'}</div>`;
    root().querySelectorAll('[data-application-id]').forEach(button => button.onclick = async () => { const result = await apiFetch(`/applications/${button.dataset.applicationId}/`, {}); if (!result.ok) return showToast(result.data?.error || 'Could not open this application.', true); renderEditor(result.data.application, 0); });
    document.getElementById('origination-list-refresh').onclick = load;
    const form = document.getElementById('origination-create');
    if (form) form.onsubmit = async event => { event.preventDefault(); const values = new FormData(form); const result = await postJson('/applications/', { product_key: values.get('product_key'), branch: values.get('branch') }); if (!result.ok) return showToast(result.data?.error || 'Could not start the application.', true); renderEditor(result.data.application, 0); };
  }

  async function load() {
    const [productResult, applicationResult] = await Promise.all([apiFetch('/products/', {}), apiFetch('/applications/', {})]);
    if (!productResult.ok || !applicationResult.ok) { root().innerHTML = `<div class="notice error">${escapeHtml(productResult.data?.error || applicationResult.data?.error || 'Could not load Origination.')} <button class="btn btn-secondary" id="load-retry">Retry</button></div>`; document.getElementById('load-retry').onclick = load; return; }
    products = productResult.data.products || []; applications = applicationResult.data.applications || []; renderList();
  }

  document.getElementById('preview-close').onclick = closePreview;
  document.getElementById('preview-previous').onclick = async () => { if (previewPage > 1) { previewPage -= 1; await loadPreviewPage(); } };
  document.getElementById('preview-next').onclick = async () => { if (previewPage < previewPageCount) { previewPage += 1; await loadPreviewPage(); } };
  document.getElementById('preview-regenerate').onclick = async () => {
    if (['draft', 'correction_required'].includes(current?.status) && !(await saveDraft(true))) return;
    previewedRevision = current.revision;
    previewRequestId = requestKey('preview');
    await loadPreviewPage();
  };
  document.getElementById('preview-zoom-out').onclick = () => { previewZoom = Math.max(50, previewZoom - 25); updatePreviewFrame(); };
  document.getElementById('preview-zoom-in').onclick = () => { previewZoom = Math.min(200, previewZoom + 25); updatePreviewFrame(); };
  document.getElementById('preview-open').onclick = () => { if (previewUrl) window.open(previewUrl, '_blank', 'noopener'); };
  window.addEventListener('beforeunload', closePreview);
  tg?.ready(); tg?.expand();
  tg?.BackButton?.onClick(async () => {
    if (previewUrl) return closePreview();
    if (current && ['draft', 'correction_required'].includes(current.status) && !(await saveDraft(true))) return;
    if (current && step > 0) renderEditor(current, step - 1);
    else if (current) renderList();
  });
  load();
})();
