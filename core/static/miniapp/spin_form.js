(function () {
  'use strict';

  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  if (tg) {
    tg.ready();
    tg.expand();
    if (tg.enableClosingConfirmation) tg.enableClosingConfirmation();
  }

  const configEl = document.getElementById('spin-form-data');
  const config = configEl ? JSON.parse(configEl.textContent || '{}') : {};
  const form = document.getElementById('spinForm');
  const banner = document.getElementById('statusBanner');
  const submitBtn = document.getElementById('submitBtn');
  const clearBtn = document.getElementById('clearDraft');
  const draftState = document.getElementById('draftState');
  const summaryList = document.getElementById('summaryList');
  const draftKey = `spin_form_draft:${config.group_id || 'unknown'}`;

  document.getElementById('groupId').value = config.group_id || '';
  document.getElementById('formToken').value = config.form_token || '';

  function field(name) { return form.elements[name]; }

  function normalizePhone(value) {
    const digits = String(value || '').replace(/\D/g, '');
    if (/^254[17]\d{8}$/.test(digits)) return digits;
    if (/^0[17]\d{8}$/.test(digits)) return `254${digits.slice(1)}`;
    if (/^[17]\d{8}$/.test(digits)) return `254${digits}`;
    return '';
  }

  function cleanAmount(value) {
    return String(value || '').replace(/,/g, '').trim();
  }

  function formValues() {
    const selectedType = form.querySelector('input[name="request_type"]:checked');
    return {
      request_type: selectedType ? selectedType.value : '',
      customer_name: field('customer_name').value.trim(),
      national_id: field('national_id').value.replace(/\D/g, ''),
      customer_type: field('customer_type').value,
      primary_phone: normalizePhone(field('primary_phone').value) || field('primary_phone').value.trim(),
      secondary_phone: normalizePhone(field('secondary_phone').value) || field('secondary_phone').value.trim(),
      requested_amount: cleanAmount(field('requested_amount').value),
      tenor: field('tenor').value.trim(),
      loan_product: field('loan_product').value.trim(),
      code: field('code').value.trim(),
      business_notes: field('business_notes').value.trim()
    };
  }

  function setBanner(message, type) {
    if (!message) {
      banner.hidden = true;
      banner.textContent = '';
      banner.className = 'status-banner';
      return;
    }
    banner.hidden = false;
    banner.className = `status-banner ${type || ''}`.trim();
    banner.textContent = message;
  }

  function markInvalid(names) {
    form.querySelectorAll('.field.invalid').forEach(el => el.classList.remove('invalid'));
    names.forEach(name => {
      const input = field(name);
      const wrapper = input && input.closest ? input.closest('.field') : null;
      if (wrapper) wrapper.classList.add('invalid');
    });
  }

  function validate(data) {
    const errors = [];
    const invalid = [];
    if (!['spin', 'crb'].includes(data.request_type)) errors.push('Choose SPIN or CRB.');
    if (!data.customer_name) { errors.push('Customer Name is required.'); invalid.push('customer_name'); }
    if (!/^\d{7,8}$/.test(data.national_id)) { errors.push('National ID must be 7 or 8 digits.'); invalid.push('national_id'); }
    if (!normalizePhone(data.primary_phone)) { errors.push('Primary Phone must be a valid Kenyan number.'); invalid.push('primary_phone'); }
    if (data.secondary_phone && !normalizePhone(data.secondary_phone)) { errors.push('Secondary Phone is invalid.'); invalid.push('secondary_phone'); }
    if (!data.requested_amount || Number(data.requested_amount) <= 0) { errors.push('Requested Amount is required.'); invalid.push('requested_amount'); }
    if (!data.tenor) { errors.push('Tenor is required.'); invalid.push('tenor'); }
    return { errors, invalid };
  }


  function updateFileSummaries() {
    form.querySelectorAll('input[type="file"]').forEach(input => {
      const summary = form.querySelector(`[data-file-summary="${input.name}"]`);
      const files = Array.from(input.files || []);
      if (summary) {
        summary.textContent = files.length ? files.map(file => file.name).join(', ') : 'No files selected';
      }
    });
  }

  function validateFiles() {
    const errors = [];
    const invalid = [];
    form.querySelectorAll('input[type="file"]').forEach(input => {
      const maxFiles = Number(input.dataset.maxFiles || 2);
      if ((input.files || []).length > maxFiles) {
        errors.push(`${input.closest('.field').querySelector('span').textContent} supports at most ${maxFiles} files.`);
        invalid.push(input.name);
      }
    });
    return { errors, invalid };
  }

  function updateSummary() {
    const data = formValues();
    const rows = [
      ['Type', data.request_type ? data.request_type.toUpperCase() : ''],
      ['Name', data.customer_name || '-'],
      ['National ID', data.national_id || '-'],
      ['Phone', normalizePhone(data.primary_phone) || data.primary_phone || '-'],
      ['Amount', data.requested_amount || '-'],
      ['Tenor', data.tenor || '-']
    ];
    summaryList.innerHTML = rows.map(([label, value]) => `<dt>${label}</dt><dd>${escapeHtml(value)}</dd>`).join('');
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"]/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]));
  }

  function saveDraft() {
    try {
      localStorage.setItem(draftKey, JSON.stringify(formValues()));
      draftState.textContent = 'Draft saved';
    } catch (_) {
      draftState.textContent = 'Draft not saved';
    }
  }

  function loadDraft() {
    try {
      const raw = localStorage.getItem(draftKey);
      if (!raw) return;
      const data = JSON.parse(raw);
      Object.entries(data).forEach(([name, value]) => {
        if (name === 'request_type') {
          const option = form.querySelector(`input[name="request_type"][value="${value}"]`);
          if (option) option.checked = true;
        } else if (field(name)) {
          field(name).value = value || '';
        }
      });
      draftState.textContent = 'Draft restored';
    } catch (_) {
      draftState.textContent = 'Draft unavailable';
    }
  }

  function clearDraft() {
    localStorage.removeItem(draftKey);
    form.reset();
    field('primary_phone').value = '';
    field('secondary_phone').value = '';
    markInvalid([]);
    setBanner('', '');
    updateSummary();
    updateFileSummaries();
    saveDraft();
  }

  async function submitForm(event) {
    event.preventDefault();
    setBanner('', '');

    field('primary_phone').value = normalizePhone(field('primary_phone').value) || field('primary_phone').value.trim();
    if (field('secondary_phone').value.trim()) {
      field('secondary_phone').value = normalizePhone(field('secondary_phone').value) || field('secondary_phone').value.trim();
    }

    const data = formValues();
    const check = validate(data);
    const fileCheck = validateFiles();
    markInvalid(check.invalid.concat(fileCheck.invalid));
    if (check.errors.length || fileCheck.errors.length) {
      setBanner((check.errors[0] || fileCheck.errors[0]), 'error');
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Submitting...';
    try {
      const payload = new FormData(form);
      payload.set('group_id', config.group_id || '');
      payload.set('form_token', config.form_token || '');
      payload.set('init_data', tg ? tg.initData || '' : '');
      Object.entries(data).forEach(([key, value]) => payload.set(key, value || ''));
      const response = await fetch('/api/spin/submit/', {
        method: 'POST',
        body: payload
      });
      const result = await response.json();
      if (!response.ok || !result.success) {
        const message = (result.errors && result.errors[0]) || result.message || 'Submission failed.';
        setBanner(message, 'error');
        return;
      }
      localStorage.removeItem(draftKey);
      markInvalid([]);
      setBanner(`Submitted ${result.request_id || ''} for ${result.customer_name || 'customer'}.`, 'success');
      form.reset();
      updateSummary();
      if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
    } catch (_) {
      setBanner('Network error. Check your connection and submit again.', 'error');
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Submit Request';
    }
  }

  form.addEventListener('input', () => { updateSummary(); saveDraft(); });
  form.addEventListener('change', () => { updateSummary(); updateFileSummaries(); saveDraft(); });
  form.addEventListener('submit', submitForm);
  clearBtn.addEventListener('click', clearDraft);

  loadDraft();
  updateSummary();
  updateFileSummaries();
}());


