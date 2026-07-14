(function () {
  'use strict';

  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  function applyTelegramTheme() {
    const scheme = tg && tg.colorScheme === 'dark' ? 'tg-dark' : 'tg-light';
    document.body.classList.remove('tg-dark', 'tg-light');
    document.body.classList.add(scheme);
  }

  if (tg) {
    tg.ready();
    tg.expand();
    applyTelegramTheme();
    if (tg.onEvent) tg.onEvent('themeChanged', applyTelegramTheme);
    if (tg.enableClosingConfirmation) tg.enableClosingConfirmation();
  } else {
    document.body.classList.add('tg-light');
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
  let bannerTimeout = null;

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

  const completeModal = document.getElementById('completeModal');
  const completeForm = document.getElementById('completeForm');
  const closeModalBtn = document.getElementById('closeModalBtn');
  const cancelModalBtn = document.getElementById('cancelModalBtn');
  const submitCompleteBtn = document.getElementById('submitCompleteBtn');
  const modalBanner = document.getElementById('modalBanner');
  const reviewModal = document.getElementById('reviewModal');
  const reviewForm = document.getElementById('reviewForm');
  const closeReviewModalBtn = document.getElementById('closeReviewModalBtn');
  const cancelReviewModalBtn = document.getElementById('cancelReviewModalBtn');
  const submitReviewBtn = document.getElementById('submitReviewBtn');
  const reviewModalBanner = document.getElementById('reviewModalBanner');
  const reviewBranchField = document.getElementById('reviewBranchField');
  const reviewBranchSelect = document.getElementById('reviewBranchSelect');

  let requests = [];
  let isAnalyst = false;

  document.getElementById('groupId').value = config.group_id || '';
  document.getElementById('formToken').value = config.form_token || '';
  const branchField = document.getElementById('branchField');
  const branchSelect = document.getElementById('branchSelect');
  const defaultBranch = document.getElementById('defaultBranch');
  if (defaultBranch) defaultBranch.value = config.default_branch || '';
  if (branchSelect && Array.isArray(config.branch_choices) && config.branch_choices.length) {
    branchSelect.innerHTML = '<option value="">Select branch</option>' + config.branch_choices.map(branch => `<option value="${escapeHtml(branch)}">${escapeHtml(branch)}</option>`).join('');
    branchSelect.value = config.default_branch || '';
    if (branchField) branchField.hidden = false;
  } else if (branchSelect && branchField) {
    branchSelect.removeAttribute('name');
    branchField.hidden = true;
  }
  if (reviewBranchSelect && Array.isArray(config.branch_choices) && config.branch_choices.length) {
    reviewBranchSelect.innerHTML = '<option value="">Select branch</option>' + config.branch_choices.map(branch => `<option value="${escapeHtml(branch)}">${escapeHtml(branch)}</option>`).join('');
    if (reviewBranchField) reviewBranchField.hidden = false;
  } else if (reviewBranchSelect && reviewBranchField) {
    reviewBranchSelect.removeAttribute('name');
    reviewBranchField.hidden = true;
  }

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
      branch: field('branch') ? field('branch').value.trim() : (config.default_branch || ''),
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

  function normalizedMessages(message) {
    if (Array.isArray(message)) return message.map(item => String(item || '').trim()).filter(Boolean);
    const value = String(message || '').trim();
    return value ? [value] : [];
  }

  function setButtonLoading(button, isLoading, label) {
    if (!button) return;
    if (!button.dataset.idleText) button.dataset.idleText = button.textContent.trim();
    button.disabled = !!isLoading;
    if (isLoading) {
      button.innerHTML = `<span class="button-spinner" aria-hidden="true"></span><span>${escapeHtml(label || 'Working...')}</span>`;
    } else {
      button.textContent = button.dataset.idleText || label || '';
    }
  }

  function setBanner(message, type, targetBanner) {
    if (bannerTimeout && !targetBanner) {
      clearTimeout(bannerTimeout);
      bannerTimeout = null;
    }
    const activeBanner = targetBanner || banner;
    const messages = normalizedMessages(message);
    if (!messages.length) {
      activeBanner.hidden = true;
      activeBanner.style.display = 'none';
      activeBanner.textContent = '';
      activeBanner.className = 'status-banner';
      return;
    }
    activeBanner.hidden = false;
    activeBanner.style.display = 'block';
    activeBanner.className = `status-banner ${type || ''}`.trim();
    activeBanner.innerHTML = messages.length === 1
      ? escapeHtml(messages[0])
      : `<strong>${type === 'success' ? 'Done' : 'Fix these items'}</strong><ul>${messages.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`;
    if (!targetBanner) {
      activeBanner.scrollIntoView({ behavior: 'smooth', block: 'start' });
      
      if (type === 'success') {
        bannerTimeout = setTimeout(() => {
          setBanner('', '');
        }, 2000);
      }
    }
  }

  function setFieldError(wrapper, message) {
    let error = wrapper.querySelector('.field-error');
    if (!error) {
      error = document.createElement('small');
      error.className = 'field-error';
      wrapper.appendChild(error);
    }
    error.textContent = message || '';
  }

  function markInvalid(details) {
    form.querySelectorAll('.field.invalid').forEach(el => {
      el.classList.remove('invalid');
      setFieldError(el, '');
    });
    (details || []).forEach(item => {
      const name = typeof item === 'string' ? item : item.field;
      const message = typeof item === 'string' ? '' : item.message;
      const input = field(name);
      const wrapper = input && input.closest ? input.closest('.field') : null;
      if (wrapper) {
        wrapper.classList.add('invalid');
        setFieldError(wrapper, message);
      }
    });
  }

  function focusFirstInvalid(details) {
    const first = (details || []).find(item => field(typeof item === 'string' ? item : item.field));
    if (!first) return;
    const input = field(typeof first === 'string' ? first : first.field);
    if (input && input.focus) input.focus({ preventScroll: true });
  }

  function validate(data) {
    const errors = [];
    const invalid = [];
    function add(fieldName, message) {
      errors.push(message);
      invalid.push({ field: fieldName, message });
    }
    if (!['spin_crb', 'spin', 'crb'].includes(data.request_type)) add('request_type', 'Choose SPIN/CRB, SPIN, or CRB.');
    if (Array.isArray(config.branch_choices) && config.branch_choices.length && !data.branch) add('branch', 'Select a valid branch.');
    if (!data.customer_name) add('customer_name', 'Customer Name is required.');
    if (!/^\d{7,8}$/.test(data.national_id)) add('national_id', 'National ID must be 7 or 8 digits.');
    if (!normalizePhone(data.primary_phone)) add('primary_phone', 'Primary Phone must be a valid Kenyan number, for example 254712345678.');
    if (data.secondary_phone && !normalizePhone(data.secondary_phone)) add('secondary_phone', 'Secondary Phone is invalid. Use 254 format or leave it blank.');
    if (!data.requested_amount || Number(data.requested_amount) <= 0) add('requested_amount', 'Requested Amount is required and must be greater than 0.');
    if (!data.tenor) add('tenor', 'Tenor is required, for example 6 weeks or 12 months.');
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
        const message = `${input.closest('.field').querySelector('span').textContent} supports at most ${maxFiles} files.`;
        errors.push(message);
        invalid.push({ field: input.name, message });
      }
    });
    return { errors, invalid };
  }

  function updateSummary() {
    const data = formValues();
    const rows = [
      ['Type', requestTypeLabel(data.request_type)],
      ['Branch', data.branch || '-'],
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
    if (branchSelect && branchSelect.name) branchSelect.value = config.default_branch || '';
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
    const invalidDetails = check.invalid.concat(fileCheck.invalid);
    const errorMessages = check.errors.concat(fileCheck.errors);
    markInvalid(invalidDetails);
    if (errorMessages.length) {
      setBanner(errorMessages, 'error');
      focusFirstInvalid(invalidDetails);
      return;
    }

    setButtonLoading(submitBtn, true, 'Submitting');
    try {
      const response = await fetch('/api/spin/submit/', buildSubmitOptions(data));
      const result = await response.json();
      if (!response.ok || !result.success) {
        const messages = (result.errors && result.errors.length ? result.errors : [result.message || 'Submission failed.']);
        setBanner(messages, 'error');
        return;
      }
      localStorage.removeItem(draftKey);
      markInvalid([]);
      setBanner(`Submitted ${result.request_id || ''} for ${result.customer_name || 'customer'}.`, 'success');
      form.reset();
      if (branchSelect && branchSelect.name) branchSelect.value = config.default_branch || '';
      updateSummary();
      updateFileSummaries();
      if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
    } catch (_) {
      setBanner('Network error. Check your connection and submit again.', 'error');
    } finally {
      setButtonLoading(submitBtn, false);
    }
  }

  // --- Dashboard Functionality ---

  function formatAmount(amount) {
    return Number(amount).toLocaleString('en-KE', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  function getStatusLabel(status) {
    if (status === 'completed') return 'Completed';
    if (status === 'review_needed' || status === 'imported') return 'Awaiting Review';
    return status;
  }

  function renderRequests() {
    const keyword = dashboardSearch.value.trim().toLowerCase();
    const status = statusFilter.value;

    const filtered = requests.filter(r => {
      if (status !== 'all') {
        if (status === 'review_needed') {
          if (r.import_status !== 'review_needed' && r.import_status !== 'imported') return false;
        } else if (r.import_status !== status) {
          return false;
        }
      }
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
      const statusClass = r.import_status === 'imported' ? 'review_needed' : r.import_status;
      const customerName = r.customer_name || 'Unnamed customer';
      const attachments = (r.attachment_names || []).map((name, i) => {
        const url = (r.media_urls || [])[i] || '#';
        if (url === '#') return `<span class="card-link muted"><i data-lucide="file"></i> ${escapeHtml(name)}</span>`;
        return `<a href="${escapeHtml(url)}" target="_blank" rel="noopener" class="card-link"><i data-lucide="file"></i> ${escapeHtml(name)}</a>`;
      }).join('');

      let reports = '';
      if (r.import_status === 'completed') {
        const reportLinks = [];
        if (r.spin_report_url) reportLinks.push(`<a href="${escapeHtml(r.spin_report_url)}" target="_blank" rel="noopener" class="card-link"><i data-lucide="shield"></i> SPIN Report</a>`);
        if (r.crb_report_url) reportLinks.push(`<a href="${escapeHtml(r.crb_report_url)}" target="_blank" rel="noopener" class="card-link"><i data-lucide="file-text"></i> CRB Report</a>`);
        if (r.credit_analysis_report_url) reportLinks.push(`<a href="${escapeHtml(r.credit_analysis_report_url)}" target="_blank" rel="noopener" class="card-link"><i data-lucide="trending-up"></i> Credit Analysis</a>`);
        if (reportLinks.length) {
          reports = `
            <div class="card-section-title">Reports Uploaded</div>
            <div class="card-links">${reportLinks.join('')}</div>
          `;
        }
      }

      let actions = '';
      const actionButtons = [];
      if (r.import_status === 'review_needed') {
        actionButtons.push(`
            <button type="button" class="secondary review-action-btn" data-id="${escapeHtml(r.id)}">
              <i data-lucide="edit-3" style="width:14px; height:14px; display:inline-block; vertical-align:middle; margin-right:4px;"></i>
              Review Details
            </button>
        `);
      }
      if (isAnalyst && r.import_status !== 'completed') {
        actionButtons.push(`
            <button type="button" class="primary complete-action-btn" data-id="${escapeHtml(r.id)}">
              <i data-lucide="check-square" style="width:14px; height:14px; display:inline-block; vertical-align:middle; margin-right:4px;"></i>
              Complete Request
            </button>
        `);
      }
      if (actionButtons.length) {
        actions = `
          <div class="card-actions">
            ${actionButtons.join('')}
          </div>
        `;
      }

      return `
        <details class="request-card" id="card-${escapeHtml(r.id)}">
          <summary class="card-toggle">
            <span class="card-title-group">
              <span class="card-customer-name">${escapeHtml(customerName)}</span>
              <span class="card-summary-meta">${escapeHtml(r.national_id || 'No ID')} / ${escapeHtml(r.primary_phone || 'No phone')} / KES ${formatAmount(r.requested_amount)}</span>
              <span class="card-date">${escapeHtml(r.request_datetime || 'Date not set')} / ${escapeHtml(r.request_id || '')}</span>
            </span>
            <span class="card-header-right">
              <span class="badge status-${statusClass}">${getStatusLabel(r.import_status)}</span>
              <i data-lucide="chevron-down" class="card-chevron"></i>
            </span>
          </summary>
          <div class="card-body">
            <div class="card-field">
              <label>Request ID</label>
              <span>${escapeHtml(r.request_id)}</span>
            </div>
            <div class="card-field">
              <label>Requested By</label>
              <span>${escapeHtml(r.requested_by || '-')}</span>
            </div>
            <div class="card-field">
              <label>National ID</label>
              <span>${escapeHtml(r.national_id || '-')}</span>
            </div>
            <div class="card-field">
              <label>Primary Phone</label>
              <span>${escapeHtml(r.primary_phone || '-')}</span>
            </div>
            <div class="card-field">
              <label>Request Type</label>
              <span class="badge type" style="display:inline-block; width:fit-content;">${escapeHtml(r.request_type || '-')}</span>
            </div>
            <div class="card-field">
              <label>Amount (KES)</label>
              <span>${formatAmount(r.requested_amount)}</span>
            </div>
            <div class="card-field">
              <label>Tenor</label>
              <span>${escapeHtml(r.tenor || '-')}</span>
            </div>
            ${r.code ? `
            <div class="card-field">
              <label>MPESA Statement Code</label>
              <span>${escapeHtml(r.code)}</span>
            </div>` : ''}
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
        </details>
      `;
    }).join('');

    if (window.lucide) window.lucide.createIcons();

    requestsList.querySelectorAll('.complete-action-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        openCompleteModal(btn.dataset.id);
      });
    });
    requestsList.querySelectorAll('.review-action-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        openReviewModal(btn.dataset.id);
      });
    });
  }
  async function fetchRequests() {
    requestsList.style.display = 'none';
    dashboardLoading.style.display = 'block';
    
    const initDataEnc = encodeURIComponent(tg ? tg.initData || '' : '');
    const url = `/api/spin/requests/?group_id=${config.group_id || ''}&form_token=${config.form_token || ''}&init_data=${initDataEnc}`;

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
        requestsList.style.display = 'block';
        return;
      }
      requests = (result.requests || []).filter(r => r.import_status !== 'failed');
      isAnalyst = !!result.is_analyst;

      // Update summary count values
      const countAllVal = requests.length;
      const countReviewVal = requests.filter(r => r.import_status === 'review_needed' || r.import_status === 'imported').length;
      const countCompletedVal = requests.filter(r => r.import_status === 'completed').length;

      cntAll.textContent = countAllVal;
      cntReview.textContent = countReviewVal;
      cntCompleted.textContent = countCompletedVal;
      dashboardCounts.style.display = 'grid';

      // Update dashboard tab badge
      if (countReviewVal > 0) {
        dashboardTabBadge.textContent = countReviewVal;
        dashboardTabBadge.style.display = 'inline-flex';
      } else {
        dashboardTabBadge.style.display = 'none';
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
      requestsList.style.display = 'block';
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
    setButtonLoading(submitCompleteBtn, false);
    if (window.lucide) window.lucide.createIcons();
  }

  function closeCompleteModal() {
    completeModal.hidden = true;
    completeModal.classList.add('hidden');
    completeForm.reset();
    setBanner('', '', modalBanner);
    setButtonLoading(submitCompleteBtn, false);
  }

  function reviewFormValues() {
    return {
      request_type: reviewForm.elements['request_type'].value,
      branch: reviewForm.elements['branch'] ? reviewForm.elements['branch'].value : (config.default_branch || ''),
      customer_name: reviewForm.elements['customer_name'].value.trim(),
      national_id: reviewForm.elements['national_id'].value.replace(/\D/g, ''),
      primary_phone: normalizePhone(reviewForm.elements['primary_phone'].value) || reviewForm.elements['primary_phone'].value.trim(),
      secondary_phone: normalizePhone(reviewForm.elements['secondary_phone'].value) || reviewForm.elements['secondary_phone'].value.trim(),
      requested_amount: cleanAmount(reviewForm.elements['requested_amount'].value),
      tenor: reviewForm.elements['tenor'].value.trim(),
      customer_type: reviewForm.elements['customer_type'].value,
      loan_product: reviewForm.elements['loan_product'].value.trim(),
      code: reviewForm.elements['code'].value.trim(),
      business_notes: reviewForm.elements['business_notes'].value.trim()
    };
  }

  function openReviewModal(reqId) {
    const record = requests.find(r => r.id === reqId);
    if (!record) return;
    reviewForm.reset();
    setBanner('', '', reviewModalBanner);
    document.getElementById('reviewRequestId').value = record.id;
    reviewForm.elements['request_type'].value = record.request_type === 'SPIN/CRB' ? 'spin_crb' : String(record.request_type || '').toLowerCase();
    if (!['spin_crb', 'spin', 'crb'].includes(reviewForm.elements['request_type'].value)) {
      reviewForm.elements['request_type'].value = 'spin_crb';
    }
    if (reviewForm.elements['branch']) reviewForm.elements['branch'].value = record.branch || config.default_branch || '';
    reviewForm.elements['customer_name'].value = record.customer_name || '';
    reviewForm.elements['national_id'].value = record.national_id || '';
    reviewForm.elements['primary_phone'].value = record.primary_phone || '';
    reviewForm.elements['secondary_phone'].value = record.secondary_phone || '';
    reviewForm.elements['requested_amount'].value = record.requested_amount ? String(record.requested_amount) : '';
    reviewForm.elements['tenor'].value = record.tenor || '';
    reviewForm.elements['customer_type'].value = record.customer_type || '';
    reviewForm.elements['loan_product'].value = record.loan_product || '';
    reviewForm.elements['code'].value = record.code || '';
    reviewForm.elements['business_notes'].value = record.business_notes || '';
    reviewModal.hidden = false;
    reviewModal.classList.remove('hidden');
    setButtonLoading(submitReviewBtn, false);
    if (window.lucide) window.lucide.createIcons();
  }

  function closeReviewModal() {
    reviewModal.hidden = true;
    reviewModal.classList.add('hidden');
    reviewForm.reset();
    setBanner('', '', reviewModalBanner);
    setButtonLoading(submitReviewBtn, false);
  }

  async function submitReview(event) {
    event.preventDefault();
    setBanner('', '', reviewModalBanner);
    setButtonLoading(submitReviewBtn, true, 'Saving');

    const payload = {
      request_id: document.getElementById('reviewRequestId').value,
      group_id: config.group_id || '',
      form_token: config.form_token || '',
      init_data: tg ? tg.initData || '' : '',
      fields: reviewFormValues()
    };

    try {
      const response = await fetch('/api/spin/review/update/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const result = await response.json();
      if (!response.ok || !result.success) {
        setBanner(result.errors || result.message || 'Review could not be saved.', 'error', reviewModalBanner);
        return;
      }
      closeReviewModal();
      setBanner(result.sheet_synced ? 'Review saved and sheet updated.' : 'Review saved. Sheet update needs retry.', result.sheet_synced ? 'success' : 'warning');
      fetchRequests();
      if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
    } catch (_) {
      setBanner('Network error saving review.', 'error', reviewModalBanner);
    } finally {
      setButtonLoading(submitReviewBtn, false);
    }
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
    setButtonLoading(submitCompleteBtn, true, 'Uploading');

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
      setButtonLoading(submitCompleteBtn, false);
    }
  }

  // Hook Modal events
  closeModalBtn.addEventListener('click', closeCompleteModal);
  cancelModalBtn.addEventListener('click', closeCompleteModal);
  completeForm.addEventListener('submit', submitComplete);
  closeReviewModalBtn.addEventListener('click', closeReviewModal);
  cancelReviewModalBtn.addEventListener('click', closeReviewModal);
  reviewForm.addEventListener('submit', submitReview);

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











