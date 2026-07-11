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

  // Dashboard & Modal Elements
  const tabDashboardBtn = document.getElementById('tab-dashboard-btn');
  const dashboardTabBadge = document.getElementById('dashboardTabBadge');
  const dashboardCounts = document.getElementById('dashboardCounts');
  const cntAll = document.getElementById('cnt-all');
  const cntReview = document.getElementById('cnt-review');
  const cntCompleted = document.getElementById('cnt-completed');
  const cntFailed = document.getElementById('cnt-failed');
  const requestsList = document.getElementById('requestsList');
  const dashboardLoading = document.getElementById('dashboardLoading');
  const dashboardSearch = document.getElementById('dashboardSearch');
  const statusFilter = document.getElementById('statusFilter');
  const groupFilterLabel = document.getElementById('groupFilterLabel');
  const groupFilterCheckbox = document.getElementById('groupFilterCheckbox');

  const completeModal = document.getElementById('completeModal');
  const completeForm = document.getElementById('completeForm');
  const closeModalBtn = document.getElementById('closeModalBtn');
  const cancelModalBtn = document.getElementById('cancelModalBtn');
  const submitCompleteBtn = document.getElementById('submitCompleteBtn');
  const modalBanner = document.getElementById('modalBanner');

  let requests = [];
  let isAnalyst = false;

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

  function requestTypeLabel(value) {
    if (value === 'spin_crb') return 'SPIN/CRB';
    if (value === 'spin') return 'SPIN';
    if (value === 'crb') return 'CRB';
    return '';
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

  function selectedFiles() {
    const files = [];
    form.querySelectorAll('input[type="file"]').forEach(input => {
      Array.from(input.files || []).forEach(file => {
        if (file && file.name) files.push({ fieldName: input.name, file });
      });
    });
    return files;
  }

  function setBanner(message, type, targetBanner) {
    const activeBanner = targetBanner || banner;
    if (!message) {
      activeBanner.hidden = true;
      activeBanner.style.display = 'none';
      activeBanner.textContent = '';
      activeBanner.className = 'status-banner';
      return;
    }
    activeBanner.hidden = false;
    activeBanner.style.display = 'block';
    activeBanner.className = `status-banner ${type || ''}`.trim();
    activeBanner.textContent = message;
    if (!targetBanner) {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
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
    if (!['spin_crb', 'spin', 'crb'].includes(data.request_type)) errors.push('Choose SPIN/CRB, SPIN, or CRB.');
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
      ['Type', requestTypeLabel(data.request_type)],
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

  function buildSubmitOptions(data) {
    const files = selectedFiles();
    if (!files.length) {
      return {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          group_id: config.group_id || '',
          form_token: config.form_token || '',
          init_data: tg ? tg.initData || '' : '',
          fields: data
        })
      };
    }

    const payload = new FormData();
    payload.set('group_id', config.group_id || '');
    payload.set('form_token', config.form_token || '');
    payload.set('init_data', tg ? tg.initData || '' : '');
    Object.entries(data).forEach(([key, value]) => payload.set(key, value || ''));
    files.forEach(({ fieldName, file }) => payload.append(fieldName, file, file.name));
    return { method: 'POST', body: payload };
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
      const response = await fetch('/api/spin/submit/', buildSubmitOptions(data));
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
      updateFileSummaries();
      if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
    } catch (_) {
      setBanner('Network error. Check your connection and submit again.', 'error');
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Submit Request';
    }
  }

  // --- Dashboard Functionality ---

  function formatAmount(amount) {
    return Number(amount).toLocaleString('en-KE', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  function getStatusLabel(status) {
    if (status === 'completed') return 'Completed';
    if (status === 'review_needed') return 'Awaiting Review';
    if (status === 'failed') return 'Failed';
    if (status === 'imported') return 'Imported';
    return status;
  }

  function renderRequests() {
    const keyword = dashboardSearch.value.trim().toLowerCase();
    const status = statusFilter.value;

    const filtered = requests.filter(r => {
      if (status !== 'all' && r.import_status !== status) return false;
      if (keyword) {
        const name = (r.customer_name || '').toLowerCase();
        const id = (r.national_id || '').toLowerCase();
        const phone = (r.primary_phone || '').toLowerCase();
        const reqId = (r.request_id || '').toLowerCase();
        if (!name.includes(keyword) && !id.includes(keyword) && !phone.includes(keyword) && !reqId.includes(keyword)) {
          return false;
        }
      }
      return true;
    });

    if (!filtered.length) {
      requestsList.innerHTML = `
        <div class="empty-state">
          <i data-lucide="info" style="width:32px; height:32px; color:var(--spin-muted); margin:0 auto 8px; display:block;"></i>
          <p>No matching requests found.</p>
        </div>
      `;
      if (window.lucide) window.lucide.createIcons();
      return;
    }

    requestsList.innerHTML = filtered.map(r => {
      const attachments = (r.attachment_names || []).map((name, i) => {
        const url = (r.media_urls || [])[i] || '#';
        return `<a href="${url}" target="_blank" class="card-link"><i data-lucide="file"></i> ${escapeHtml(name)}</a>`;
      }).join('');

      let reports = '';
      if (r.import_status === 'completed') {
        const reportLinks = [];
        if (r.spin_report_url) reportLinks.push(`<a href="${r.spin_report_url}" target="_blank" class="card-link"><i data-lucide="shield"></i> SPIN Report</a>`);
        if (r.crb_report_url) reportLinks.push(`<a href="${r.crb_report_url}" target="_blank" class="card-link"><i data-lucide="file-text"></i> CRB Report</a>`);
        if (r.credit_analysis_report_url) reportLinks.push(`<a href="${r.credit_analysis_report_url}" target="_blank" class="card-link"><i data-lucide="trending-up"></i> Credit Analysis</a>`);
        
        if (reportLinks.length) {
          reports = `
            <div class="card-section-title">Reports Uploaded</div>
            <div class="card-links">${reportLinks.join('')}</div>
          `;
        }
      }

      let actions = '';
      if (isAnalyst && r.import_status !== 'completed') {
        actions = `
          <div class="card-actions">
            <button type="button" class="primary complete-action-btn" data-id="${r.id}">
              <i data-lucide="check-square" style="width:14px; height:14px; display:inline-block; vertical-align:middle; margin-right:4px;"></i>
              Complete Request
            </button>
          </div>
        `;
      }

      return `
        <div class="request-card" id="card-${r.id}">
          <header class="card-header">
            <div class="card-title-group">
              <span class="card-id">${escapeHtml(r.request_id)}</span>
              <span class="card-date">${escapeHtml(r.request_datetime || 'Date not set')}</span>
            </div>
            <span class="badge status-${r.import_status}">${getStatusLabel(r.import_status)}</span>
          </header>
          <div class="card-body">
            <div class="card-field">
              <label>Customer Name</label>
              <span>${escapeHtml(r.customer_name)}</span>
            </div>
            <div class="card-field">
              <label>National ID</label>
              <span>${escapeHtml(r.national_id)}</span>
            </div>
            <div class="card-field">
              <label>Primary Phone</label>
              <span>${escapeHtml(r.primary_phone)}</span>
            </div>
            <div class="card-field">
              <label>Request Type</label>
              <span class="badge type" style="display:inline-block; width:fit-content;">${escapeHtml(r.request_type)}</span>
            </div>
            <div class="card-field">
              <label>Amount (KES)</label>
              <span>${formatAmount(r.requested_amount)}</span>
            </div>
            <div class="card-field">
              <label>Tenor</label>
              <span>${escapeHtml(r.tenor)}</span>
            </div>
            ${r.business_notes ? `
            <div class="card-field wide">
              <label>Business / Employment Notes</label>
              <p>${escapeHtml(r.business_notes)}</p>
            </div>` : ''}
            ${attachments ? `
            <div class="card-section-title">Submitted Documents</div>
            <div class="card-links">${attachments}</div>` : ''}
            ${reports}
            ${actions}
          </div>
        </div>
      `;
    }).join('');

    if (window.lucide) window.lucide.createIcons();

    // Hook modal triggers
    requestsList.querySelectorAll('.complete-action-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        openCompleteModal(btn.dataset.id);
      });
    });
  }

  async function fetchRequests() {
    requestsList.style.display = 'none';
    dashboardLoading.style.display = 'block';
    
    const filterGroup = groupFilterCheckbox.checked ? 'true' : 'false';
    const initDataEnc = encodeURIComponent(tg ? tg.initData || '' : '');
    const url = `/api/spin/requests/?group_id=${config.group_id || ''}&form_token=${config.form_token || ''}&init_data=${initDataEnc}&filter_group=${filterGroup}`;

    try {
      const response = await fetch(url);
      const result = await response.json();
      if (!response.ok || !result.success) {
        requestsList.innerHTML = `
          <div class="empty-state">
            <i data-lucide="alert-triangle" style="width:32px; height:32px; color:var(--spin-danger); margin:0 auto 8px; display:block;"></i>
            <p>${escapeHtml(result.message || 'Could not load requests.')}</p>
          </div>
        `;
        if (window.lucide) window.lucide.createIcons();
        return;
      }
      requests = result.requests || [];
      isAnalyst = !!result.is_analyst;

      // Update summary count values
      const countAllVal = requests.length;
      const countReviewVal = requests.filter(r => r.import_status === 'review_needed').length;
      const countCompletedVal = requests.filter(r => r.import_status === 'completed').length;
      const countFailedVal = requests.filter(r => r.import_status === 'failed').length;

      cntAll.textContent = countAllVal;
      cntReview.textContent = countReviewVal;
      cntCompleted.textContent = countCompletedVal;
      cntFailed.textContent = countFailedVal;
      dashboardCounts.style.display = 'grid';

      // Update dashboard tab badge
      if (countReviewVal > 0) {
        dashboardTabBadge.textContent = countReviewVal;
        dashboardTabBadge.style.display = 'inline-flex';
      } else {
        dashboardTabBadge.style.display = 'none';
      }

      // Show/hide analyst group filters
      if (isAnalyst) {
        groupFilterLabel.style.display = 'inline-flex';
      } else {
        groupFilterLabel.style.display = 'none';
      }

      renderRequests();
      requestsList.style.display = 'block';
    } catch (_) {
      requestsList.innerHTML = `
        <div class="empty-state">
          <i data-lucide="wifi-off" style="width:32px; height:32px; color:var(--spin-danger); margin:0 auto 8px; display:block;"></i>
          <p>Network error loading dashboard.</p>
        </div>
      `;
      if (window.lucide) window.lucide.createIcons();
    } finally {
      dashboardLoading.style.display = 'none';
    }
  }

  // --- Tab Navigation Setup ---

  document.querySelectorAll('.spin-tab-bar .tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      // Toggle button active states
      document.querySelectorAll('.spin-tab-bar .tab-btn').forEach(b => {
        b.classList.remove('active');
        b.setAttribute('aria-selected', 'false');
      });
      btn.classList.add('active');
      btn.setAttribute('aria-selected', 'true');

      // Toggle tab page visibility
      const tabName = btn.dataset.tab;
      document.querySelectorAll('.tab-page').forEach(page => {
        page.classList.remove('active');
      });
      document.getElementById(`tab-${tabName}`).classList.add('active');

      // Clear any global banners
      setBanner('', '');

      // Trigger load if dashboard
      if (tabName === 'dashboard') {
        fetchRequests();
      }
      
      if (window.lucide) window.lucide.createIcons();
    });
  });

  // --- Complete Modal Handlers ---

  function openCompleteModal(reqId) {
    document.getElementById('completeRequestId').value = reqId;
    completeForm.reset();
    setBanner('', '', modalBanner);
    completeModal.hidden = false;
    completeModal.classList.remove('hidden');
    if (window.lucide) window.lucide.createIcons();
  }

  function closeCompleteModal() {
    completeModal.hidden = true;
    completeModal.classList.add('hidden');
    completeForm.reset();
    setBanner('', '', modalBanner);
  }

  async function submitComplete(event) {
    event.preventDefault();
    setBanner('', '', modalBanner);

    const spin = completeForm.elements['spin_report'].files[0];
    const crb = completeForm.elements['crb_report'].files[0];
    const analysis = completeForm.elements['credit_analysis'].files[0];

    if (!spin && !crb && !analysis) {
      setBanner('Please upload at least one report file.', 'error', modalBanner);
      return;
    }

    submitCompleteBtn.disabled = true;
    submitCompleteBtn.textContent = 'Uploading...';

    const formData = new FormData(completeForm);
    formData.append('group_id', config.group_id || '');
    formData.append('form_token', config.form_token || '');
    formData.append('init_data', tg ? tg.initData || '' : '');

    try {
      const response = await fetch('/api/spin/complete/', {
        method: 'POST',
        body: formData
      });
      const result = await response.json();
      if (!response.ok || !result.success) {
        setBanner(result.message || 'Upload failed.', 'error', modalBanner);
        return;
      }

      closeCompleteModal();
      setBanner('Reports submitted and request marked completed.', 'success');
      fetchRequests();
      if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
    } catch (_) {
      setBanner('Network error submitting reports.', 'error', modalBanner);
    } finally {
      submitCompleteBtn.disabled = false;
      submitCompleteBtn.textContent = 'Submit Reports';
    }
  }

  // Hook Modal events
  closeModalBtn.addEventListener('click', closeCompleteModal);
  cancelModalBtn.addEventListener('click', closeCompleteModal);
  completeForm.addEventListener('submit', submitComplete);

  // Hook search & filters events
  dashboardSearch.addEventListener('input', renderRequests);
  
  statusFilter.addEventListener('change', () => {
    // Sync active class on count cards
    const val = statusFilter.value;
    document.querySelectorAll('.count-card').forEach(card => {
      if (card.dataset.filter === val) {
        card.classList.add('active');
      } else {
        card.classList.remove('active');
      }
    });
    renderRequests();
  });

  // Count cards click handler
  document.querySelectorAll('.count-card').forEach(card => {
    card.addEventListener('click', () => {
      document.querySelectorAll('.count-card').forEach(c => c.classList.remove('active'));
      card.classList.add('active');
      statusFilter.value = card.dataset.filter;
      renderRequests();
    });
  });

  groupFilterCheckbox.addEventListener('change', fetchRequests);

  // --- Initial Setup ---

  form.addEventListener('input', () => { updateSummary(); saveDraft(); });
  form.addEventListener('change', () => { updateSummary(); updateFileSummaries(); saveDraft(); });
  form.addEventListener('submit', submitForm);
  clearBtn.addEventListener('click', clearDraft);

  loadDraft();
  updateSummary();
  updateFileSummaries();
  
  if (window.lucide) window.lucide.createIcons();
}());

