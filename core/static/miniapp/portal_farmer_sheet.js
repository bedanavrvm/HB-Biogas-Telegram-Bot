(function () {
  'use strict';

  let deps = null;
  let mapInstance = null;
  let mapMarker = null;

  function el(id) { return deps.el(id); }
  function state() { return deps.state; }

  function openFarmerSheet(farmer, mode) {
    state().selectedFarmer = farmer;
    state().activeMode = mode;

    el('sheet-name').textContent = farmer.customer_name || 'Unknown Farmer';
    el('sheet-sub').textContent = [farmer.county, farmer.sub_county, farmer.branch].filter(Boolean).join(' | ') || farmer.primary_phone || '';

    const infoFields = [
      ['National ID', deps.fmt(farmer.national_id)],
      ['Phone', deps.fmt(farmer.primary_phone)],
      ['HBG Visit', deps.fmtDate(farmer.sign_date)],
      ['JBL Visit', deps.fmtDate(farmer.jbl_visit_date)],
      ['JBL Officer', deps.fmt(farmer.jbl_officer)],
      ['JBL Status', farmer.jbl_visit_status ? `<span class="badge badge-blue">${deps.escapeHtml(farmer.jbl_visit_status)}</span>` : '-'],
      ['Credit Decision', farmer.credit_decision ? `<span class="badge ${farmer.credit_decision === 'Approved' ? 'badge-green' : 'badge-orange'}">${deps.escapeHtml(farmer.credit_decision)}</span>` : '-'],
      ['IMAB Created', deps.fmt(farmer.imab_created)],
      ['Customer No.', deps.fmt(farmer.customer_no)],
      ['Visit Media', farmer.jbl_media_count ? `${farmer.jbl_media_count} file link${farmer.jbl_media_count === 1 ? '' : 's'}` : '-'],
      ['Order No.', farmer.order_number ? `<strong>${deps.escapeHtml(farmer.order_number)}</strong>` : '-'],
      ['Requisition Date', deps.fmtDate(farmer.requisition_date)],
      ['HB Sales Person', deps.fmt(farmer.hb_sales_person)],
      ['Village', deps.fmt(farmer.village)],
      ...(farmer.invoice_number || farmer.invoice_amount || farmer.balance_due ? [
        ['Invoice', ''],
        ['Invoice No.', farmer.invoice_number ? `<code style="font-size:12px;">${deps.escapeHtml(farmer.invoice_number)}</code>` : '-'],
        ['Invoice Date', deps.fmtDate(farmer.invoice_date)],
        ['Invoice Amount', farmer.invoice_amount ? `<strong>KES ${deps.escapeHtml(farmer.invoice_amount)}</strong>` : '-'],
        ['Discount', farmer.discount ? `KES ${deps.escapeHtml(farmer.discount)}` : '-'],
        ['Payment', farmer.payment ? `KES ${deps.escapeHtml(farmer.payment)}` : '-'],
        ['Balance Due', farmer.balance_due
          ? `<span class="badge ${parseFloat(farmer.balance_due) === 0 ? 'badge-green' : 'badge-orange'}">KES ${deps.escapeHtml(farmer.balance_due)}</span>`
          : '-'],
      ] : []),
    ];

    el('sheet-info').innerHTML = infoFields.map(([label, value]) =>
      `<li class="info-row"><span class="ir-label">${deps.escapeHtml(label)}</span><span class="ir-value">${value}</span></li>`
    ).join('');

    const formEl = el('sheet-form');
    const footerEl = el('sheet-footer');
    formEl.innerHTML = '';
    footerEl.innerHTML = '';
    el('sheet-gate-warning').style.display = 'none';

    if (mode === 'jbl_visit') {
      formEl.innerHTML = buildJblForm(farmer);
      footerEl.innerHTML = '<button class="primary" id="btn-submit-jbl">Log JBL Visit</button>';
      el('btn-submit-jbl').addEventListener('click', submitJblVisit);
      wireGpsButton();
    } else if (mode === 'credit') {
      formEl.innerHTML = buildCreditForm(farmer);
      footerEl.innerHTML = '<button class="primary" id="btn-submit-credit">Set Credit Decision</button>';
      el('btn-submit-credit').addEventListener('click', submitCreditDecision);
      wireCreditImabFields();
    } else if (mode === 'final_review') {
      formEl.innerHTML = buildFinalReviewForm(farmer);
      footerEl.innerHTML = '<button class="primary" id="btn-submit-final">Save Final Review</button>';
      el('btn-submit-final').addEventListener('click', submitFinalDecision);
    } else if (mode === 'requisition') {
      const notApproved = farmer.final_decision !== 'Approved';
      formEl.innerHTML = buildRequisitionForm(farmer);
      if (notApproved) {
        el('sheet-gate-warning').style.display = 'flex';
        el('sheet-gate-warning').innerHTML = `Final Decision is <strong>${deps.escapeHtml(farmer.final_decision || 'not set')}</strong>. Must be <strong>Approved</strong> to assign an order.`;
        footerEl.innerHTML = '<button class="primary" id="btn-submit-req" disabled>Assign Order (Gate: Final Review)</button>';
      } else {
        footerEl.innerHTML = '<button class="primary" id="btn-submit-req">Assign Order Number</button>';
        el('btn-submit-req').addEventListener('click', submitOrder);
      }
    }

    const lat = parseFloat(farmer.latitude);
    const lng = parseFloat(farmer.longitude);
    if (!isNaN(lat) && !isNaN(lng)) initMap(lat, lng);
    else destroyMap();

    el('sheet-overlay').classList.add('open');
    if (window.lucide) window.lucide.createIcons();
  }

  function initMap(lat, lng) {
    const mapContainer = el('sheet-map-container');
    if (!mapContainer || !window.L) return;
    mapContainer.style.display = 'block';

    const isDark = (window.Telegram?.WebApp?.colorScheme === 'dark') ||
      (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
    const tileUrl = isDark
      ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
      : 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png';
    const attribution = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>';

    if (!mapInstance) {
      mapInstance = L.map('sheet-map', { zoomControl: false, attributionControl: false }).setView([lat, lng], 13);
      L.tileLayer(tileUrl, { attribution, maxZoom: 20 }).addTo(mapInstance);
      mapMarker = L.marker([lat, lng]).addTo(mapInstance);
    } else {
      mapInstance.setView([lat, lng], 13);
      mapInstance.eachLayer(layer => {
        if (layer instanceof L.TileLayer) layer.setUrl(tileUrl);
      });
      if (mapMarker) mapMarker.setLatLng([lat, lng]);
      else mapMarker = L.marker([lat, lng]).addTo(mapInstance);
    }

    setTimeout(() => {
      if (mapInstance) mapInstance.invalidateSize();
    }, 100);
  }

  function destroyMap() {
    const mapContainer = el('sheet-map-container');
    if (mapContainer) mapContainer.style.display = 'none';
  }

  function buildJblForm(farmer) {
    const today = new Date().toISOString().split('T')[0];
    const statusOptions = state().metaStatuses.map(status =>
      `<option value="${deps.escapeHtml(status)}"${farmer.jbl_visit_status === status ? ' selected' : ''}>${deps.escapeHtml(status)}</option>`
    ).join('');
    return `
      <div class="form-section">
        <div class="form-row"><label>Visit Date</label><input type="date" id="jbl-date" value="${deps.escapeHtml(farmer.jbl_visit_date || today)}"></div>
        <div class="form-row"><label>Status / Outcome</label><select id="jbl-status"><option value="">- Select -</option>${statusOptions}</select></div>
        <div class="form-row"><label>Officer Name</label><input type="text" id="jbl-officer" placeholder="Your name" value="${deps.escapeHtml(farmer.jbl_officer || '')}"></div>
        <div class="form-row"><label>County</label><input type="text" id="jbl-county" placeholder="County" value="${deps.escapeHtml(farmer.county || '')}"></div>
        <div class="form-row"><label>Constituency</label><input type="text" id="jbl-sub-county" placeholder="Constituency / sub-county" value="${deps.escapeHtml(farmer.sub_county || '')}"></div>
        <div class="form-row"><label>Village</label><input type="text" id="jbl-village" placeholder="Village / area" value="${deps.escapeHtml(farmer.village || '')}"></div>
        <div class="form-row"><label>Comment (optional)</label><textarea id="jbl-comment" rows="2" placeholder="Additional notes...">${deps.escapeHtml(farmer.jbl_visit_comment || '')}</textarea></div>
        <div class="form-row media-upload-row">
          <label>Visit Media</label>
          <div class="media-upload-control">
            <input type="file" id="jbl-media" name="files" multiple accept="image/*,.pdf,.doc,.docx,.xls,.xlsx">
            <small>Optional. Upload visit photos, signed docs, or supporting files.</small>
            ${farmer.jbl_media_count ? `<small>${farmer.jbl_media_count} existing Drive link${farmer.jbl_media_count === 1 ? '' : 's'} on this record.</small>` : ''}
          </div>
        </div>
        <div class="form-row" style="border-bottom: none; background: transparent; padding: 12px 0 0;">
          <button type="button" id="btn-gps" style="width: 100%; height: 38px; display: flex; align-items: center; justify-content: center; gap: 8px;">- Capture GPS Location</button>
          <div id="gps-coords" style="font-size: 11px; font-weight: 600; color: var(--text-muted); text-align: center; margin-top: 6px;">Not captured</div>
          <input type="hidden" id="jbl-lat" value="">
          <input type="hidden" id="jbl-lng" value="">
        </div>
      </div>
    `;
  }

  function wireGpsButton() {
    const btn = el('btn-gps');
    if (!btn) return;
    btn.addEventListener('click', () => {
      if (!navigator.geolocation) {
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
          el('gps-coords').innerHTML = `Location captured<br><span style="font-family: monospace; font-size: 12px; color: var(--color-success)">Lat: ${lat.toFixed(6)}, Lng: ${lng.toFixed(6)}</span>`;
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
          el('gps-coords').textContent = msg;
          deps.showToast(msg, 'error');
        },
        { enableHighAccuracy: true, timeout: 8000, maximumAge: 0 }
      );
    });
  }

  function buildCreditForm(farmer) {
    const decisionOptions = state().metaDecisions.map(decision =>
      `<option value="${deps.escapeHtml(decision)}"${farmer.credit_decision === decision ? ' selected' : ''}>${deps.escapeHtml(decision)}</option>`
    ).join('');
    const imabOptions = (state().metaImabOptions.length ? state().metaImabOptions : ['Yes', 'No', 'Pending']).map(value =>
      `<option value="${deps.escapeHtml(value)}"${farmer.imab_created === value ? ' selected' : ''}>${deps.escapeHtml(value)}</option>`
    ).join('');
    const customerNoDisabled = farmer.imab_created !== 'Yes';
    return `
      <div class="form-section">
        <div class="form-row"><label>Credit Decision</label><select id="credit-decision"><option value="">- Select -</option>${decisionOptions}</select></div>
        <div class="form-row"><label>IS CUSTOMER CREATED ON IMAB?</label><select id="credit-imab"><option value="">- Select -</option>${imabOptions}</select></div>
        <div class="form-row">
          <label>CUSTOMER NO</label>
          <input type="text" id="credit-customer-no" inputmode="numeric" pattern="[0-9]*" placeholder="IMAB customer number" value="${deps.escapeHtml(customerNoDisabled ? '' : (farmer.customer_no || ''))}"${customerNoDisabled ? ' disabled' : ''}>
          <small id="credit-imab-help" class="field-help">${customerNoDisabled ? 'Select Yes after IMAB creation before entering a customer number.' : 'Required before this case can move to Head of Rural review.'}</small>
        </div>
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
    const decisionOptions = state().metaFinalDecisions.map(decision =>
      `<option value="${deps.escapeHtml(decision)}"${farmer.final_decision === decision ? ' selected' : ''}>${deps.escapeHtml(decision)}</option>`
    ).join('');
    const phone = String(farmer.primary_phone || '').replace(/[^0-9+]/g, '');
    return `
      <div class="form-section">
        <div class="form-row">
          <label>Client Phone</label>
          <div style="display:flex;gap:8px;align-items:center;width:100%;">
            <input type="tel" value="${deps.escapeHtml(farmer.primary_phone || '')}" readonly style="flex:1;">
            ${phone ? `<a class="phone-call-button" href="tel:+${phone.replace(/^\+/, '')}" aria-label="Call client"><i data-lucide="phone"></i></a>` : ''}
          </div>
        </div>
        <div class="form-row"><label>Final Decision</label><select id="final-decision"><option value="">- Select -</option>${decisionOptions}</select></div>
        <div class="form-row"><label>After-call Comments</label><textarea id="final-comment" rows="4" placeholder="Summarize the call and reason for the decision...">${deps.escapeHtml(farmer.final_decision_comment || '')}</textarea></div>
      </div>
      ${farmer.jbl_visit_comment ? `<div class="info-row"><span class="ir-label">BRO Comment</span><span class="ir-value">${deps.escapeHtml(farmer.jbl_visit_comment)}</span></div>` : ''}
    `;
  }

  function buildRequisitionForm(farmer) {
    const today = new Date().toISOString().split('T')[0];
    return `
      <div class="form-section">
        <div class="form-row"><label>Order Number</label><input type="text" id="req-order" placeholder="e.g. JBL-2026-001" value="${deps.escapeHtml(farmer.order_number || '')}"></div>
        <div class="form-row"><label>Requisition Date</label><input type="date" id="req-date" value="${deps.escapeHtml(farmer.requisition_date || today)}"></div>
        <div class="form-row"><label>Repayment Date</label><input type="text" id="req-repayment-date" placeholder="e.g. 10TH" value="${deps.escapeHtml(farmer.repayment_date || '')}"></div>
        <div class="form-row"><label>Tenor</label><input type="text" id="req-tenor" placeholder="e.g. 6" value="${deps.escapeHtml(farmer.repayment_tenor || '')}"></div>
        <div class="form-row"><label>Payment Product</label><input type="text" id="req-product" placeholder="Optional" value="${deps.escapeHtml(farmer.payment_product || '')}"></div>
      </div>
    `;
  }

  function closeSheet() {
    el('sheet-overlay').classList.remove('open');
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

    const btn = el('btn-submit-jbl');
    deps.setButtonLoading(btn, true, 'Saving...');
    const { ok, data } = await deps.apiFetch('/jbl-queue/' + farmer.id + '/', {
      method: 'POST',
      body: JSON.stringify({
        visit_date: el('jbl-date')?.value || '',
        visit_status: visitStatus,
        officer: el('jbl-officer')?.value || '',
        county: el('jbl-county')?.value || '',
        sub_county: el('jbl-sub-county')?.value || '',
        village: el('jbl-village')?.value || '',
        comment: el('jbl-comment')?.value || '',
        latitude: el('jbl-lat')?.value || '',
        longitude: el('jbl-lng')?.value || '',
      }),
    });
    deps.setButtonLoading(btn, false);
    if (!ok) {
      deps.showToast(data.error || 'Save failed', 'error');
      return;
    }
    const uploadOk = await uploadJblMediaIfSelected(farmer.id);
    if (!uploadOk) return;
    deps.showToast('JBL visit logged', 'success');
    closeSheet();
    deps.reloadCurrentQueue();
    deps.loadDashboard();
  }

  async function uploadJblMediaIfSelected(farmerId) {
    const input = el('jbl-media');
    const files = input?.files ? Array.from(input.files) : [];
    if (!files.length) return true;
    if (!navigator.onLine) {
      deps.showToast('Offline. Reconnect before uploading visit media.', 'error');
      return false;
    }
    const formData = new FormData();
    files.forEach(file => formData.append('files', file));
    deps.showToast('Uploading visit media...');
    try {
      const result = await deps.portalApi.postForm('/jbl-queue/' + farmerId + '/media/', formData, deps.tg, { 'X-CSRFToken': deps.getCookie('csrftoken') || '' });
      const data = result.data || {};
      if (!result.ok || data.ok === false) {
        deps.showToast(data.error || 'Media upload failed. Visit was saved; retry media upload from the record.', 'error');
        return false;
      }
      const warnings = Array.isArray(data.warnings) && data.warnings.length ? ' ' + data.warnings.join(' ') : '';
      deps.showToast(`Stored ${data.stored_count || 0} media file${(data.stored_count || 0) === 1 ? '' : 's'}.${warnings}`, data.warnings?.length ? 'warning' : 'success');
      return true;
    } catch (err) {
      console.error(err);
      deps.showToast('Media upload failed. Visit was saved; retry media upload from the record.', 'error');
      return false;
    }
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
      body: JSON.stringify({ decision, imab_created: imabCreated, customer_no: customerNo }),
    });
    deps.setButtonLoading(btn, false);
    if (!ok) return deps.showToast(data.error || 'Save failed', 'error');
    deps.showToast('Credit decision saved', 'success');
    closeSheet();
    deps.reloadCurrentQueue();
    deps.loadDashboard();
  }

  async function submitFinalDecision() {
    const farmer = state().selectedFarmer;
    if (!farmer) return;
    const finalDecision = el('final-decision')?.value || '';
    const decisionComment = el('final-comment')?.value || '';
    if (!finalDecision) return deps.showToast('Please select a final decision', 'error');

    const btn = el('btn-submit-final');
    deps.setButtonLoading(btn, true, 'Saving...');
    const { ok, data } = await deps.apiFetch('/final-review-queue/' + farmer.id + '/', {
      method: 'POST',
      body: JSON.stringify({ final_decision: finalDecision, decision_comment: decisionComment }),
    });
    deps.setButtonLoading(btn, false);
    if (!ok) return deps.showToast(data.error || 'Save failed', 'error');
    deps.showToast('Final review saved', 'success');
    closeSheet();
    deps.reloadCurrentQueue();
    deps.loadDashboard();
  }

  async function submitOrder() {
    const farmer = state().selectedFarmer;
    if (!farmer) return;
    const orderNumber = (el('req-order')?.value || '').trim();
    const reqDate = el('req-date')?.value || '';
    const repaymentDate = (el('req-repayment-date')?.value || '').trim();
    const repaymentTenor = (el('req-tenor')?.value || '').trim();
    const paymentProduct = (el('req-product')?.value || '').trim();
    if (!orderNumber) return deps.showToast('Order number is required', 'error');
    if (!repaymentDate) return deps.showToast('Repayment date is required for payment documents', 'error');
    if (!repaymentTenor) return deps.showToast('Tenor is required for payment documents', 'error');

    const btn = el('btn-submit-req');
    deps.setButtonLoading(btn, true, 'Saving...');
    const { ok, status, data } = await deps.apiFetch('/requisition-queue/' + farmer.id + '/', {
      method: 'POST',
      body: JSON.stringify({
        order_number: orderNumber,
        requisition_date: reqDate,
        repayment_date: repaymentDate,
        repayment_tenor: repaymentTenor,
        payment_product: paymentProduct,
      }),
    });
    deps.setButtonLoading(btn, false);
    if (!ok) {
      deps.showToast(status === 403 ? ('Error: ' + (data.error || 'Final review not approved')) : (data.error || 'Save failed'), 'error');
      return;
    }
    deps.showToast('Order assigned', 'success');
    closeSheet();
    deps.reloadCurrentQueue();
    deps.loadDashboard();
  }

  function bindEvents() {
    el('sheet-overlay')?.addEventListener('click', event => {
      if (event.target === el('sheet-overlay')) closeSheet();
    });
    el('sheet-close')?.addEventListener('click', closeSheet);
  }

  function init(initialDeps) {
    deps = initialDeps;
    bindEvents();
  }

  window.PortalMiniAppFarmerSheet = {
    init,
    openFarmerSheet,
    closeSheet,
  };
})();
