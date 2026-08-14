(function () {
  'use strict';

  const tg = window.Telegram?.WebApp;
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
  let capabilities = { can_create: false, can_review: false, can_start_signing: false };
  let listState = { queue: '', status: '', productKey: '', query: '', page: 1, pages: 1 };
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
  let editGeneration = 0;
  let saveInFlight = null;
  let pendingSaveRequestId = '';
  let syncConflict = false;
  let conflictDraft = null;
  let recoveryAvailable = Boolean(window.crypto?.subtle && window.indexedDB);
  const recoveredApplications = new Set();
  const reviewTargets = new Map();
  let reviewDialogMode = '';
  let previewPinch = null;
  let previewSwipe = null;
  const previewPointers = new Map();
  const previewPageUrls = new Map();
  const previewPageLoads = new Map();

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
    localStorage.removeItem(draftKey(applicationId));
  }

  async function recoverDraft(application) {
    if (recoveredApplications.has(application.id)) return;
    recoveredApplications.add(application.id);
    let local = await readRecoveryDraft(application.id);
    // One-time migration from the previous plaintext recovery format.
    if (!local) {
      try { local = JSON.parse(localStorage.getItem(draftKey(application.id)) || 'null'); } catch (_) { local = null; }
      if (local) await persistRecoveryDraft(application.id, local);
      localStorage.removeItem(draftKey(application.id));
    }
    if (!local) return;
    if (Number(local.revision) !== Number(application.revision)) {
      syncConflict = true;
      conflictDraft = local;
      showToast('A phone recovery draft and the server revision differ. Your phone copy was kept; refresh before editing.', true);
      return;
    }
    current.form_payload = local.payload || current.form_payload;
    current.product_requirements = local.configuration?.requirements || current.product_requirements;
    current.product_custom_values = local.configuration?.customValues || current.product_custom_values;
    current.product_selected_fee_keys = local.configuration?.selectedFeeKeys || current.product_selected_fee_keys;
    pendingSaveRequestId = local.requestId || requestKey('save');
    editGeneration = Number(local.generation || 1);
    dirty = true;
  }

  async function openEditor(application, requestedStep) {
    current = application;
    reviewTargets.clear();
    syncConflict = false;
    conflictDraft = null;
    await recoverDraft(application);
    renderEditor(current, requestedStep);
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
    const sections = Array.isArray(configured) && configured.length
      ? configured.map(item => ({ key: item.key, label: item.label || item.key, hint: item.help_text || '' }))
      : LEGACY_SECTIONS;
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
    return [...sections, { key: 'review', label: 'Review', hint: 'Confirm details against the filled document' }];
  }

  function fieldsFor(sectionKey) {
    return (current?.form_schema?.fields || []).filter(field => (field.section_key || sectionFor(field.key)) === sectionKey);
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
    const inputType = item.type === 'date' ? 'date' : ['number', 'money', 'amount'].includes(item.type) ? 'number' : 'text';
    const validation = item.validation || {};
    const numeric = ['number', 'money', 'amount'].includes(item.type) ? ` inputmode="decimal" step="any"${validation.min != null ? ` min="${escapeHtml(validation.min)}"` : ''}${validation.max != null ? ` max="${escapeHtml(validation.max)}"` : ''}` : '';
    const pattern = inputType === 'text' && validation.pattern ? ` pattern="${escapeHtml(validation.pattern)}"` : '';
    const placeholder = item.type === 'document' ? 'Document reference or evidence note' : '';
    return `<input type="${inputType}" ${data} value="${escapeHtml(value ?? '')}"${numeric}${pattern}${placeholder ? ` placeholder="${placeholder}"` : ''}${locked}>`;
  }

  function productConfigurationMarkup(editable) {
    const terms = current?.product_terms || {};
    const requirements = (terms.requirements || []).filter(item => !item.workflow || item.workflow === 'loan_origination');
    const attributes = (terms.custom_attributes || []).filter(item => !(item.workflows || []).length || item.workflows.includes('loan_origination'));
    const optionalFees = (terms.fees || []).filter(item => !item.mandatory);
    const evidenceEditable = editable || (current?.status === 'reviewed' && capabilities.can_start_signing);
    const selected = new Set(current?.product_selected_fee_keys || []);
    const requirementRows = requirements.map(item => {
      const required = item.required ? '<span class="required-mark" aria-label="required">*</span>' : '';
      const stage = item.enforcement_stage ? `<small class="field-help">Required before ${escapeHtml(item.enforcement_stage.replaceAll('_', ' '))}</small>` : '';
      const correction = current.status === 'ready_for_review' ? correctionToggle('requirement', item.key, item.label) : '';
      if (item.type === 'document') {
        const evidence = (current?.requirement_evidence || []).filter(file => file.requirement_key === item.key && file.status !== 'removed');
        const upload = evidenceEditable ? `<label class="evidence-upload"><input type="file" accept="application/pdf,image/jpeg,image/png" data-evidence-upload="${escapeHtml(item.key)}"><span>Choose PDF, JPG or PNG</span></label>` : '';
        const fileRows = evidence.map(file => `<span class="evidence-row status-${escapeHtml(file.status)}"><span><strong>${escapeHtml(file.filename)}</strong><small>${escapeHtml(file.status === 'failed' ? file.error || 'Upload failed' : `${Math.max(1, Math.round(file.byte_size / 1024))} KB · ${file.status}`)}</small></span><span class="evidence-actions">${file.download_url ? `<button type="button" data-evidence-open="${escapeHtml(file.id)}">Open</button>` : ''}${evidenceEditable && file.status === 'uploaded' ? `<button type="button" data-evidence-remove="${escapeHtml(file.id)}">Remove</button>` : ''}</span></span>`).join('');
        return `<div class="laf-field laf-field-wide evidence-field" data-product-wrap="requirement:${escapeHtml(item.key)}"><span>${escapeHtml(item.label)}${required}</span>${item.description ? `<small class="field-help">${escapeHtml(item.description)}</small>` : ''}${stage}${correction}${fileRows || '<small class="field-help">No evidence uploaded.</small>'}${upload}<small class="field-error" aria-live="polite"></small></div>`;
      }
      const signingEditable = current?.status === 'reviewed'
        && capabilities.can_start_signing && item.enforcement_stage === 'signing';
      return `<label class="laf-field" data-product-wrap="requirement:${escapeHtml(item.key)}"><span>${escapeHtml(item.label)}${required}</span>${item.description ? `<small class="field-help">${escapeHtml(item.description)}</small>` : ''}${stage}${correction}${configurationControl(item, current?.product_requirements?.[item.key], 'data-product-requirement', !(editable || signingEditable))}<small class="field-error" aria-live="polite"></small></label>`;
    }).join('');
    const attributeRows = attributes.map(item => {
      const required = item.required ? '<span class="required-mark" aria-label="required">*</span>' : '';
      return `<label class="laf-field" data-product-wrap="custom:${escapeHtml(item.key)}"><span>${escapeHtml(item.label)}${required}</span>${item.help_text ? `<small class="field-help">${escapeHtml(item.help_text)}</small>` : ''}${configurationControl(item, current?.product_custom_values?.[item.key] ?? item.default, 'data-product-custom', !editable)}<small class="field-error" aria-live="polite"></small></label>`;
    }).join('');
    const feeRows = optionalFees.map(item => `<label class="laf-field configuration-fee" data-product-wrap="fee:${escapeHtml(item.key)}"><span>${escapeHtml(item.label)}</span><small class="field-help">Optional ${escapeHtml(item.collection_mode)} fee</small><label class="configuration-check"><input type="checkbox" data-product-fee="${escapeHtml(item.key)}"${selected.has(item.key) ? ' checked' : ''}${editable ? '' : ' disabled'}><span>Include in quote</span></label><small class="field-error" aria-live="polite"></small></label>`).join('');
    const quote = current?.product_quote || {};
    const quoteMarkup = quote.installment_amount ? `<aside class="notice"><strong>Current quote</strong><span>${escapeHtml(quote.currency)} ${escapeHtml(quote.installment_amount)} × ${escapeHtml(quote.installment_count)}; total repayment ${escapeHtml(quote.currency)} ${escapeHtml(quote.total_repayment)}${quote.upfront_fees !== '0.00' ? `; upfront fees ${escapeHtml(quote.currency)} ${escapeHtml(quote.upfront_fees)}` : ''}</span></aside>` : '';
    return `${quoteMarkup}<div class="laf-grid">${requirementRows}${attributeRows}${feeRows}</div>`;
  }

  function correctionToggle(targetType, targetKey, targetLabel) {
    if (!capabilities.can_review) return '';
    const identity = `${targetType}:${targetKey}`;
    return `<span class="correction-toggle"><input type="checkbox" data-correction-target="${escapeHtml(identity)}" data-target-type="${escapeHtml(targetType)}" data-target-key="${escapeHtml(targetKey)}" data-target-label="${escapeHtml(targetLabel)}"${reviewTargets.has(identity) ? ' checked' : ''}><span>Flag for correction</span></span>`;
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
    if (field.type === 'branch') {
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
      const type = field.type === 'date' ? 'date' : ['money', 'number'].includes(field.type) ? 'number' : field.type === 'phone' ? 'tel' : 'text';
      const prefix = field.type === 'money' ? '<span class="input-prefix">KES</span>' : '';
      const validation = field.validation || {};
      const numeric = field.type === 'money' ? ` inputmode="decimal" min="${escapeHtml(validation.min ?? 0)}"${validation.max != null ? ` max="${escapeHtml(validation.max)}"` : ''} step="0.01"` : field.type === 'number' ? ` inputmode="decimal"${validation.min != null ? ` min="${escapeHtml(validation.min)}"` : ''}${validation.max != null ? ` max="${escapeHtml(validation.max)}"` : ''} step="any"` : '';
      const textRules = ['text', 'textarea', 'phone', 'national_id'].includes(field.type) ? `${validation.min_length != null ? ` minlength="${escapeHtml(validation.min_length)}"` : ''}${validation.max_length != null ? ` maxlength="${escapeHtml(validation.max_length)}"` : ''}${validation.pattern ? ` pattern="${escapeHtml(validation.pattern)}"` : ''}` : '';
      const dateRules = field.type === 'date' ? `${validation.min_date ? ` min="${escapeHtml(validation.min_date)}"` : ''}${validation.max_date ? ` max="${escapeHtml(validation.max_date)}"` : ''}` : '';
      control = `<div class="input-wrap${prefix ? ' has-prefix' : ''}">${prefix}<input data-field="${key}" type="${type}" value="${escapeHtml(value ?? '')}"${numeric}${textRules}${dateRules}${field.type === 'national_id' ? ' inputmode="numeric"' : ''}${disabled ? ' disabled' : ''}></div>`;
    }
    const help = field.help_text ? `<small class="field-help">${escapeHtml(field.help_text)}</small>` : '';
    const correction = current.status === 'ready_for_review' ? correctionToggle('field', field.key, normalizeLabel(field)) : '';
    return `<label class="${classes}" data-field-wrap="${key}"><span>${label}${required}</span>${help}${correction}${control}<small class="field-error" aria-live="polite"></small></label>`;
  }

  function sectionErrors(sectionKey) {
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
        if (input.checkValidity()) return;
        const key = input.dataset.productRequirement
          ? `requirement:${input.dataset.productRequirement}`
          : `custom:${input.dataset.productCustom}`;
        errors[key] ||= input.validationMessage || 'Enter a valid value.';
      });
      return errors;
    }
    const payload = collectPayload();
    const errors = {};
    fieldsFor(sectionKey).forEach(field => {
      const value = payload[field.key];
      if (field.required && (value === undefined || value === null || value === '')) errors[field.key] = 'Required';
      const input = root()?.querySelector(`[data-field="${CSS.escape(field.key)}"]`);
      if (!errors[field.key] && input && !input.checkValidity()) {
        errors[field.key] = input.validationMessage || 'Enter a valid value.';
      }
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
    root()?.querySelectorAll('[data-product-wrap]').forEach(wrapper => {
      const message = errors[wrapper.dataset.productWrap] || '';
      wrapper.classList.toggle('invalid', Boolean(message));
      const output = wrapper.querySelector('.field-error');
      if (output) output.textContent = message;
    });
  }

  function showServerErrors(errors) {
    if (!errors || typeof errors !== 'object') return;
    const firstKey = Object.keys(errors)[0];
    if (!firstKey) return;
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
      await saveInFlight;
      return dirty ? saveDraft(showError) : true;
    }
    const applicationId = current.id;
    const revision = current.revision;
    const generation = editGeneration;
    const payload = collectPayload();
    const configuration = collectProductConfiguration();
    pendingSaveRequestId ||= requestKey('save');
    const key = pendingSaveRequestId;
    await persistRecoveryDraft(applicationId, {
      revision, payload, configuration, requestId: key,
      generation, savedAt: Date.now(),
    });
    setSaveState('Saving…', 'saving');
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
    const result = await saveInFlight;
    saveInFlight = null;
    if (!result.ok || !result.data?.ok) {
      if (result.status === 409 || result.data?.conflict) syncConflict = true;
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
    pendingSaveRequestId = '';
    if (changedWhileSaving) {
      current.form_payload = latestPayload;
      current.product_requirements = latestConfiguration.requirements;
      current.product_custom_values = latestConfiguration.customValues;
      current.product_selected_fee_keys = latestConfiguration.selectedFeeKeys;
      dirty = true;
      setSaveState('Saving newer changes…', 'saving');
      return saveDraft(showError);
    }
    dirty = false;
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
    editGeneration += 1;
    pendingSaveRequestId ||= requestKey('save');
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

  function progressMarkup() {
    return `<nav class="wizard-progress" aria-label="Application sections">${wizardSections().map((item, index) => `<button type="button" class="wizard-step${index === step ? ' active' : ''}${index < step ? ' complete' : ''}" data-step="${index}"><span>${index < step ? '✓' : index + 1}</span><small>${escapeHtml(item.label)}</small></button>`).join('')}</nav>`;
  }

  function reviewMarkup(values) {
    return `<div class="review-intro"><div><p class="eyebrow">Final check</p><h3>Review the application</h3><p>Open each section to correct details, then inspect the populated ${escapeHtml(current.product_name)} document.</p></div><button type="button" class="btn btn-primary" id="origination-preview">Preview filled document</button></div>
      <div class="review-sections">${wizardSections().slice(0, -1).map((section, index) => {
        if (section.key === 'product_requirements') {
          const configuration = collectProductConfiguration();
          const completed = Object.values(configuration.requirements).filter(value => value !== '' && value != null && value !== false).length
            + Object.values(configuration.customValues).filter(value => value !== '' && value != null).length;
          const total = (current?.product_terms?.requirements || []).length + (current?.product_terms?.custom_attributes || []).length;
          return `<button type="button" class="review-card" data-edit-step="${index}"><span><strong>${escapeHtml(section.label)}</strong><small>${completed} of ${total} details completed</small></span><span>Edit â†’</span></button>`;
        }
        const fields = fieldsFor(section.key);
        const completed = fields.filter(field => values[field.key] !== '' && values[field.key] != null).length;
        return `<button type="button" class="review-card" data-edit-step="${index}"><span><strong>${escapeHtml(section.label)}</strong><small>${completed} of ${fields.length} fields completed</small></span><span>Edit →</span></button>`;
      }).join('')}</div>`;
  }

  function actionMarkup(editable) {
    if (!editable) {
      if (current.status === 'ready_for_review' && capabilities.can_review) return '<button class="btn btn-secondary" data-review="request_correction">Request correction</button><button class="btn btn-danger" data-review="decline">Decline</button><button class="btn btn-primary" data-review="approve">Approve</button>';
      if (current.status === 'reviewed' && capabilities.can_start_signing) return '<button class="btn btn-primary" id="origination-prepare-signing">Prepare signing package</button>';
      return '';
    }
    return `${step > 0 ? '<button class="btn btn-secondary" id="wizard-previous">Previous</button>' : '<span></span>'}${step < wizardSections().length - 1 ? '<button class="btn btn-primary" id="wizard-next">Save & continue</button>' : '<button class="btn btn-primary" id="origination-submit">Submit for review</button>'}`;
  }

  function correctionChecklistMarkup() {
    const correction = current?.active_correction;
    if (!correction) return '';
    const items = (correction.items || []).map(item => `<button type="button" class="correction-item" data-correction-jump="${escapeHtml(`${item.target_type}:${item.target_key}`)}"><span><strong>${escapeHtml(item.target_label)}</strong>${item.instruction ? `<small>${escapeHtml(item.instruction)}</small>` : ''}</span><span>Open →</span></button>`).join('');
    return `<aside class="correction-checklist"><p class="eyebrow">Correction required</p><strong>${escapeHtml(correction.summary)}</strong>${items ? `<div>${items}</div>` : '<small>Review the application and address the reviewer note.</small>'}</aside>`;
  }

  function recoveryConflictMarkup() {
    if (!syncConflict || !conflictDraft) return '';
    return `<aside class="notice recovery-conflict"><strong>Two draft revisions need your choice</strong><span>The encrypted phone draft was based on revision ${escapeHtml(conflictDraft.revision)}; the server is now revision ${escapeHtml(current.revision)}. Nothing has been overwritten.</span><div><button type="button" class="btn btn-secondary" id="recovery-use-server">Use server version</button><button type="button" class="btn btn-primary" id="recovery-restore-phone">Restore phone draft</button></div></aside>`;
  }

  function renderEditor(application, requestedStep) {
    current = application;
    step = Number.isInteger(requestedStep) ? requestedStep : step;
    tg?.BackButton?.show();
    const values = collectPayload();
    const editable = ['draft', 'correction_required'].includes(application.status);
    const sections = wizardSections();
    if (step >= sections.length) step = sections.length - 1;
    const section = sections[step];
    let content;
    if (section.key === 'review') content = reviewMarkup(values);
    else {
      const fields = section.key === 'product_requirements'
        ? productConfigurationMarkup(editable)
        : `<div class="laf-grid">${fieldsFor(section.key).map(field => fieldInput(field, values[field.key], !editable || field.editable === false)).join('')}</div>`;
      content = `<div class="section-title"><div><p class="eyebrow">Step ${step + 1} of ${sections.length}</p><h3>${escapeHtml(section.label)}</h3><p>${escapeHtml(section.hint || '')}</p></div><button type="button" class="preview-link" id="origination-preview-early">Preview PDF</button></div>${fields}`;
    }
    const recoveryState = syncConflict ? ['Conflict', 'offline'] : dirty ? ['Recovered securely', 'offline'] : ['Saved', 'saved'];
    root().innerHTML = `<div class="editor-top"><button type="button" class="icon-button" id="origination-back" aria-label="Back to applications">←</button><div><strong>${escapeHtml(application.reference_number)}</strong><small>${escapeHtml(application.product_name)}</small></div><span class="status-chip status-${escapeHtml(application.status)}">${escapeHtml(application.status.replaceAll('_', ' '))}</span></div>${recoveryConflictMarkup()}${correctionChecklistMarkup()}${progressMarkup()}<section class="wizard-card">${content}</section><footer class="wizard-actions"><span id="origination-save-status" data-state="${recoveryState[1]}">${recoveryState[0]}</span><div>${actionMarkup(editable)}</div></footer>`;
    bindEditor(editable);
  }

  function correctionTargetStep(identity) {
    const [targetType, targetKey] = String(identity || '').split(':', 2);
    const sections = wizardSections();
    if (targetType === 'requirement') return sections.findIndex(item => item.key === 'product_requirements');
    return sections.findIndex(section => fieldsFor(section.key).some(field => field.key === targetKey));
  }

  function openReviewDialog(mode) {
    if (mode === 'request_correction' && !reviewTargets.size) {
      return showToast('Flag at least one field or requirement before requesting correction.', true);
    }
    reviewDialogMode = mode;
    const overlay = document.getElementById('origination-review-overlay');
    const title = document.getElementById('review-dialog-title');
    const hint = document.getElementById('review-dialog-hint');
    const targets = document.getElementById('review-dialog-targets');
    const summary = document.getElementById('review-dialog-summary');
    title.textContent = mode === 'decline' ? 'Decline application' : 'Request corrections';
    hint.textContent = mode === 'decline'
      ? 'Record the reason. The decision is retained in the application audit history.'
      : 'Give the officer an overall instruction for the flagged items.';
    targets.innerHTML = mode === 'request_correction'
      ? [...reviewTargets.entries()].map(([identity, item]) => `<label><span>${escapeHtml(item.target_label)}</span><input data-review-instruction="${escapeHtml(identity)}" maxlength="1000" value="${escapeHtml(item.instruction || '')}" placeholder="Optional item-specific instruction"></label>`).join('')
      : '';
    summary.value = '';
    overlay.hidden = false;
    overlay.setAttribute('aria-hidden', 'false');
    summary.focus();
  }

  function closeReviewDialog() {
    const overlay = document.getElementById('origination-review-overlay');
    overlay.hidden = true;
    overlay.setAttribute('aria-hidden', 'true');
    reviewDialogMode = '';
  }

  async function submitReviewDialog() {
    const reason = document.getElementById('review-dialog-summary').value.trim();
    if (!reason) return showToast('Enter the review reason.', true);
    const decision = reviewDialogMode;
    if (decision === 'request_correction') {
      document.querySelectorAll('[data-review-instruction]').forEach(input => {
        const item = reviewTargets.get(input.dataset.reviewInstruction);
        if (item) item.instruction = input.value.trim();
      });
    }
    const correctionItems = decision === 'request_correction' ? [...reviewTargets.values()] : undefined;
    const button = document.getElementById('review-dialog-submit');
    button.disabled = true;
    const result = await postJson(`/applications/${current.id}/review/`, {
      revision: current.revision,
      decision,
      reason,
      ...(correctionItems ? { correction_items: correctionItems } : {}),
    });
    button.disabled = false;
    if (!result.ok) return showToast(result.data?.error || 'Could not record the review.', true);
    closeReviewDialog();
    await load();
  }

  async function uploadEvidence(input) {
    if (!(await saveDraft(true))) { input.value = ''; return; }
    const file = input.files?.[0];
    if (!file) return;
    const requestId = requestKey('evidence');
    const formData = new FormData();
    formData.append('revision', String(current.revision));
    formData.append('request_id', requestId);
    formData.append('file', file);
    input.disabled = true;
    setSaveState('Uploading evidence…', 'saving');
    const result = await new Promise(resolve => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `/api/origination/api/applications/${current.id}/requirements/${encodeURIComponent(input.dataset.evidenceUpload)}/evidence/`);
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
    input.disabled = false;
    input.value = '';
    if (result.data?.application) current = result.data.application;
    if (!result.ok) {
      renderEditor(current, step);
      return showToast(result.data?.error || 'Evidence was not uploaded. Select the file again to retry.', true);
    }
    renderEditor(current, step);
    showToast('Evidence uploaded securely.');
  }

  async function removeEvidence(evidenceId) {
    if (!(await saveDraft(true))) return;
    const result = await postJson(`/evidence/${evidenceId}/remove/`, { revision: current.revision });
    if (!result.ok) return showToast(result.data?.error || 'Could not remove the evidence.', true);
    current = result.data.application;
    renderEditor(current, step);
    showToast('Evidence removed from the active requirement.');
  }

  async function openEvidence(evidenceId) {
    const key = requestKey('evidence-read');
    const result = await apiFetch(`/evidence/${evidenceId}/download/`, {
      headers: { 'X-Request-ID': key },
    });
    if (!result.ok || !result.blob) return showToast(result.data?.error || 'Could not open the evidence.', true);
    const url = URL.createObjectURL(result.blob);
    window.open(url, '_blank', 'noopener');
    window.setTimeout(() => URL.revokeObjectURL(url), 60000);
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

  function bindEditor(editable) {
    document.getElementById('recovery-use-server')?.addEventListener('click', async () => {
      await removeRecoveryDraft(current.id);
      syncConflict = false; conflictDraft = null; dirty = false; pendingSaveRequestId = '';
      renderEditor(current, step);
    });
    document.getElementById('recovery-restore-phone')?.addEventListener('click', () => {
      current.form_payload = conflictDraft.payload || current.form_payload;
      current.product_requirements = conflictDraft.configuration?.requirements || current.product_requirements;
      current.product_custom_values = conflictDraft.configuration?.customValues || current.product_custom_values;
      current.product_selected_fee_keys = conflictDraft.configuration?.selectedFeeKeys || current.product_selected_fee_keys;
      syncConflict = false; conflictDraft = null; dirty = true; editGeneration += 1;
      pendingSaveRequestId = requestKey('save');
      renderEditor(current, step);
      scheduleSave();
    });
    document.getElementById('origination-back').onclick = async () => {
      if (!editable || await saveDraft(true)) renderList();
    };
    root().querySelectorAll('.wizard-step').forEach(button => button.onclick = async () => { if (editable && !(await saveDraft(true))) return; step = Number(button.dataset.step); renderEditor(current, step); });
    root().querySelectorAll('[data-edit-step]').forEach(button => button.onclick = () => renderEditor(current, Number(button.dataset.editStep)));
    root().querySelectorAll('[data-correction-jump]').forEach(button => button.onclick = () => {
      const targetStep = correctionTargetStep(button.dataset.correctionJump);
      if (targetStep >= 0) renderEditor(current, targetStep);
    });
    root().querySelectorAll('[data-correction-target]').forEach(input => input.onchange = () => {
      if (input.checked) reviewTargets.set(input.dataset.correctionTarget, {
        target_type: input.dataset.targetType,
        target_key: input.dataset.targetKey,
        target_label: input.dataset.targetLabel,
        instruction: '',
      });
      else reviewTargets.delete(input.dataset.correctionTarget);
    });
    root().querySelectorAll('[data-evidence-upload]').forEach(input => input.onchange = () => uploadEvidence(input));
    root().querySelectorAll('[data-evidence-remove]').forEach(button => button.onclick = () => removeEvidence(button.dataset.evidenceRemove));
    root().querySelectorAll('[data-evidence-open]').forEach(button => button.onclick = () => openEvidence(button.dataset.evidenceOpen));
    if (editable) root().querySelector('.laf-grid')?.addEventListener('input', scheduleSave);
    else if (current.status === 'reviewed' && capabilities.can_start_signing) {
      root().querySelector('.laf-grid')?.addEventListener('input', () => {
        const configuration = collectProductConfiguration();
        current.product_requirements = configuration.requirements;
        setSaveState('Signing requirements not saved', 'dirty');
      });
    }
    root().querySelector('[data-location-type="county"]')?.addEventListener('change', syncOriginationSubCountySelect);
    document.getElementById('wizard-previous')?.addEventListener('click', async () => { if (await saveDraft(true)) renderEditor(current, step - 1); });
    document.getElementById('wizard-next')?.addEventListener('click', async () => {
      const errors = sectionErrors(wizardSections()[step].key); showErrors(errors);
      if (Object.keys(errors).length) return showToast('Complete the required fields in this section.', true);
      if (await saveDraft(true)) renderEditor(current, step + 1);
    });
    document.getElementById('origination-preview')?.addEventListener('click', openPreview);
    document.getElementById('origination-preview-early')?.addEventListener('click', openPreview);
    document.getElementById('origination-submit')?.addEventListener('click', async () => {
      if (!(await saveDraft(true))) return;
      if (previewedRevision !== current.revision) return showToast('Preview the filled document for this saved revision before submitting.', true);
      const result = await postJson(`/applications/${current.id}/submit/`, { revision: current.revision });
      if (!result.ok) {
        if (result.data?.errors) showServerErrors(result.data.errors);
        return showToast(result.data?.error || 'Could not submit the application.', true);
      }
      await load();
    });
    root().querySelectorAll('[data-review]').forEach(button => button.onclick = async () => {
      const decision = button.dataset.review;
      if (decision !== 'approve') return openReviewDialog(decision);
      const result = await postJson(`/applications/${current.id}/review/`, { revision: current.revision, decision, reason: '' });
      if (!result.ok) return showToast(result.data?.error || 'Could not record the review.', true);
      await load();
    });
    document.getElementById('origination-prepare-signing')?.addEventListener('click', async () => {
      if (!(await saveSigningRequirements())) return;
      const result = await postJson(`/applications/${current.id}/prepare-signing/`, { revision: current.revision });
      if (!result.ok) {
        if (result.data?.errors) showServerErrors(result.data.errors);
        return showToast(result.data?.error || 'Could not prepare signing.', true);
      }
      await load();
    });
  }

  async function openPreview() {
    if (['draft', 'correction_required'].includes(current.status) && !(await saveDraft(true))) return;
    previewedRevision = current.revision;
    clearPreviewPageCache();
    previewPage = 1; previewZoom = 100; previewPageCount = 1;
    previewRequestId = requestKey('preview');
    const overlay = document.getElementById('document-preview-overlay');
    overlay.hidden = false;
    overlay.setAttribute('aria-hidden', 'false');
    tg?.BackButton?.show();
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
    const pending = apiFetch(`/applications/${applicationId}/preview/`, {
      method: 'POST', headers: { 'Idempotency-Key': key, 'X-Request-ID': key },
      body: JSON.stringify({ revision, request_id: key, preview_format: 'image', page: pageNumber }),
    }).then(result => {
      if (!result.ok || !result.blob) return { error: result.data?.error || 'Could not generate the filled document.' };
      if (key !== previewRequestId || current?.id !== applicationId) return { stale: true };
      const entry = { url: URL.createObjectURL(result.blob), pageCount: Math.max(1, result.pageCount || 1) };
      previewPageUrls.set(pageNumber, entry);
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
    clearPreviewPageCache();
    previewRequestId = '';
    previewPinch = null;
    previewSwipe = null;
    previewPointers.clear();
  }

  function showToast(message, error) {
    const toast = document.getElementById('origination-toast');
    if (!toast) return;
    toast.textContent = message; toast.classList.toggle('error', Boolean(error)); toast.hidden = false;
    window.clearTimeout(showToast.timer); showToast.timer = window.setTimeout(() => { toast.hidden = true; }, 3500);
  }

  function renderList() {
    current = null; step = 0; dirty = false; closePreview(); tg?.BackButton?.hide();
    const branchOptions = branches.map(item => `<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`).join('');
    const productFilterOptions = allProducts.map(item => `<option value="${escapeHtml(item.product_key)}"${listState.productKey === item.product_key ? ' selected' : ''}>${escapeHtml(item.name)}</option>`).join('');
    const cards = applications.map(item => `<button type="button" class="application-card" data-application-id="${item.id}"><span><strong>${escapeHtml(item.reference_number)}</strong><small>${escapeHtml(item.product_name)} · ${escapeHtml(item.branch || 'No branch')}${capabilities.can_review ? ` · ${escapeHtml(item.officer_name || 'Unassigned')}` : ''}</small></span><span class="status-chip status-${escapeHtml(item.status)}">${escapeHtml(item.status.replaceAll('_', ' '))}</span></button>`).join('');
    const queueTabs = [
      ...(capabilities.can_create ? [['mine', 'My applications'], ['corrections', 'Corrections']] : []),
      ...(capabilities.can_review ? [['review', 'Review queue']] : []),
      ...(capabilities.can_start_signing ? [['signing', 'Signing']] : []),
    ].map(([key, label]) => `<button type="button" data-queue="${key}" class="queue-tab${listState.queue === key ? ' active' : ''}">${label}</button>`).join('');
    const createMarkup = capabilities.can_create ? `<form id="origination-create" class="create-card"><div><h3>New application</h3><p>Select the branch first; only products available there will appear.</p></div><label><span>Branch</span><select name="branch" id="origination-create-branch" required><option value="">Choose branch</option>${branchOptions}</select></label><label><span>Product</span><select name="product_key" id="origination-create-product" required disabled><option value="">Choose branch first</option></select></label><button class="btn btn-primary" type="submit">Start application</button></form>` : '';
    root().innerHTML = `<section class="app-hero"><div><p class="eyebrow">Paperless lending</p><h2>Applications</h2><p>Capture, review and prepare approved product documents securely.</p></div></section><div class="metric-grid"><article><strong>${listCounts.draft || 0}</strong><span>Drafts</span></article><article><strong>${listCounts.ready_for_review || 0}</strong><span>Review</span></article><article><strong>${listCounts.correction_required || 0}</strong><span>Corrections</span></article><article><strong>${(listCounts.reviewed || 0) + (listCounts.signing_pending || 0)}</strong><span>Signing</span></article></div>${createMarkup}<nav class="queue-tabs" aria-label="Origination queues">${queueTabs}</nav><form class="list-filters" id="origination-filters"><input name="q" value="${escapeHtml(listState.query)}" placeholder="Search reference number"><select name="product_key"><option value="">All products</option>${productFilterOptions}</select><select name="status"><option value="">All statuses</option>${['draft','ready_for_review','correction_required','reviewed','signing_pending','partially_signed','fully_signed','declined','expired','cancelled'].map(status => `<option value="${status}"${listState.status === status ? ' selected' : ''}>${status.replaceAll('_', ' ')}</option>`).join('')}</select><button class="btn btn-secondary" type="submit">Filter</button></form><div class="list-heading"><h3>${escapeHtml(listState.queue ? listState.queue.replaceAll('_', ' ') : 'Applications')}</h3><button type="button" class="text-button" id="origination-list-refresh">Refresh</button></div><div class="application-list">${cards || '<div class="empty-state"><strong>No applications in this queue</strong><span>Change the filters or refresh.</span></div>'}</div><div class="pagination-actions"><button type="button" class="btn btn-secondary" id="origination-page-previous"${listState.page <= 1 ? ' disabled' : ''}>Previous</button><span>Page ${listState.page} of ${listState.pages}</span><button type="button" class="btn btn-secondary" id="origination-page-next"${listState.page >= listState.pages ? ' disabled' : ''}>Next</button></div>`;
    root().querySelectorAll('[data-application-id]').forEach(button => button.onclick = async () => { const result = await apiFetch(`/applications/${button.dataset.applicationId}/`, {}); if (!result.ok) return showToast(result.data?.error || 'Could not open this application.', true); await openEditor(result.data.application, 0); });
    root().querySelectorAll('[data-queue]').forEach(button => button.onclick = async () => { listState.queue = button.dataset.queue; listState.page = 1; await loadApplications(); });
    document.getElementById('origination-list-refresh').onclick = () => loadApplications();
    document.getElementById('origination-page-previous').onclick = async () => { if (listState.page > 1) { listState.page -= 1; await loadApplications(); } };
    document.getElementById('origination-page-next').onclick = async () => { if (listState.page < listState.pages) { listState.page += 1; await loadApplications(); } };
    document.getElementById('origination-filters').onsubmit = async event => {
      event.preventDefault();
      const values = new FormData(event.currentTarget);
      listState.query = String(values.get('q') || '').trim();
      listState.productKey = String(values.get('product_key') || '');
      listState.status = String(values.get('status') || '');
      listState.page = 1;
      await loadApplications();
    };
    const form = document.getElementById('origination-create');
    if (form) {
      document.getElementById('origination-create-branch').onchange = event => loadProductsForBranch(event.target.value);
      form.onsubmit = async event => {
        event.preventDefault();
        const values = new FormData(form);
        const identity = `${values.get('branch')}:${values.get('product_key')}`;
        const storageKey = `origination-create-request:${identity}`;
        const createKey = localStorage.getItem(storageKey) || requestKey('create');
        localStorage.setItem(storageKey, createKey);
        const result = await postJson('/applications/', { product_key: values.get('product_key'), branch: values.get('branch'), client_request_id: createKey });
        if (!result.ok) return showToast(result.data?.error || 'Could not start the application.', true);
        localStorage.removeItem(storageKey);
        await openEditor(result.data.application, 0);
      };
    }
  }

  async function loadProductsForBranch(branch) {
    const select = document.getElementById('origination-create-product');
    if (!select) return;
    if (!branch) { select.innerHTML = '<option value="">Choose branch first</option>'; select.disabled = true; return; }
    select.innerHTML = '<option value="">Loading products…</option>'; select.disabled = true;
    const result = await apiFetch(`/products/?branch=${encodeURIComponent(branch)}`, {});
    if (!result.ok) { select.innerHTML = '<option value="">Could not load products</option>'; return showToast(result.data?.error || 'Could not load branch products.', true); }
    products = result.data.products || [];
    select.innerHTML = `<option value="">Choose product</option>${products.map(item => `<option value="${escapeHtml(item.product_key)}">${escapeHtml(item.name)}</option>`).join('')}`;
    select.disabled = !products.length;
    if (!products.length) showToast('No active origination product is available for this branch.', true);
  }

  async function loadApplications() {
    const params = new URLSearchParams({ queue: listState.queue, page: String(listState.page), page_size: '25' });
    if (listState.status) params.set('status', listState.status);
    if (listState.productKey) params.set('product_key', listState.productKey);
    if (listState.query) params.set('q', listState.query);
    const result = await apiFetch(`/applications/?${params}`, {});
    if (!result.ok) return showToast(result.data?.error || 'Could not load applications.', true);
    applications = result.data.applications || [];
    listCounts = result.data.counts || {};
    capabilities = result.data.capabilities || capabilities;
    listState.page = result.data.pagination?.page || 1;
    listState.pages = result.data.pagination?.pages || 1;
    renderList();
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
    if (!listState.queue) listState.queue = capabilities.can_create ? 'mine' : capabilities.can_review ? 'review' : capabilities.can_start_signing ? 'signing' : '';
    await loadApplications();
    root().setAttribute('aria-busy', 'false');
  }

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
  document.getElementById('preview-zoom-out').onclick = () => setPreviewZoom(previewZoom - 25);
  document.getElementById('preview-zoom-in').onclick = () => setPreviewZoom(previewZoom + 25);
  document.getElementById('preview-open').onclick = () => { if (previewUrl) window.open(previewUrl, '_blank', 'noopener'); };
  document.getElementById('origination-review-dialog').onsubmit = event => { event.preventDefault(); submitReviewDialog(); };
  document.getElementById('review-dialog-close').onclick = closeReviewDialog;
  document.getElementById('review-dialog-cancel').onclick = closeReviewDialog;
  document.getElementById('origination-refresh').onclick = load;
  bindPreviewPinch();
  window.addEventListener('beforeunload', closePreview);
  window.addEventListener('online', () => { if (current && dirty && !syncConflict) void saveDraft(false); else if (!current) void loadApplications(); });
  tg?.ready(); tg?.expand();
  tg?.BackButton?.onClick(async () => {
    if (reviewDialogMode) return closeReviewDialog();
    if (previewUrl) return closePreview();
    if (current && ['draft', 'correction_required'].includes(current.status) && !(await saveDraft(true))) return;
    if (current && step > 0) renderEditor(current, step - 1);
    else if (current) renderList();
  });
  load();
})();
