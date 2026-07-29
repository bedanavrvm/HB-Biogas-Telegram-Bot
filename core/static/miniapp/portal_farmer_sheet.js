(function () {
  'use strict';

  let deps = null;
  let mapInstance = null;
  let mapMarker = null;
  let currentMapLocation = null;

  const MODE_WRITE_CAPABILITIES = {
    jbl_visit: 'portal.jbl_visit.write',
    credit: 'portal.credit.write',
    final_review: 'portal.final_review.write',
    requisition: 'portal.requisition.write',
  };

  function el(id) { return deps.el(id); }
  function state() { return deps.state; }
  function hasCapability(capability) { return !capability || state().capabilities?.has(capability); }
  function requestId() { return window.crypto?.randomUUID?.() || `portal-${Date.now()}-${Math.random().toString(16).slice(2)}`; }

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

  function caseStageFlow(sections) {
    const steps = [
      ['Application', Boolean(sections.identity?.customer_name || sections.intake?.hbg_visit_date)],
      ['JBL Visit', Boolean(sections.jbl_visit?.visit_date || sections.jbl_visit?.status)],
      ['Credit', Boolean(sections.credit?.decision)],
      ['Final Review', Boolean(sections.final_review?.decision)],
      ['Order', Boolean(sections.order?.order_number)],
      ['Invoice', Boolean(sections.invoice?.number)],
    ];
    const current = steps.findIndex(([, complete]) => !complete);
    return `<ol class="case360-flow" aria-label="Case progress">${steps.map(([label, complete], index) => {
      const status = complete ? 'complete' : index === current ? 'current' : 'pending';
      const icon = complete
        ? '<svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>'
        : status === 'current'
          ? '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>'
          : '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 018 0v3"/></svg>';
      return `<li class="${status}"><span>${icon}</span><small>${deps.escapeHtml(label)}</small></li>`;
    }).join('')}</ol>`;
  }

  function caseHeader(sections) {
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
    </header>${caseStageFlow(sections)}`;
  }

  function renderCase360(data, target) {
    const root = target || el('case360');
    if (!root || !data) return;
    const sections = data.sections || {};
    const timeline = data.timeline || [];
    const tat = data.tat || {};
    const documents = data.documents || {};
    const validation = data.validation || [];
    const stageRows = (tat.stages || []).map((stage, index) => `<article class="case360-tat-row"><span class="case360-stage-number">${index + 1}</span><div><strong>${deps.escapeHtml(stage.label)}</strong><small>${stage.completed_at ? 'Completed' : stage.started_at ? 'In progress' : 'Not tracked'}</small></div><div><strong>${stage.minutes == null ? '-' : deps.escapeHtml(formatTatMinutes(stage.minutes))}</strong><span class="case360-sla ${deps.escapeHtml(stage.status || '')}">${deps.escapeHtml(humanLabel(stage.status || ''))}</span></div></article>`).join('');
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
    root.innerHTML = `
      ${caseHeader(sections)}
      <div class="case360-tabs" role="tablist">
        ${tabs.map(([key, label, count], index) => `<button type="button" role="tab" aria-selected="${index ? 'false' : 'true'}" data-case360-tab="${key}" class="${index ? '' : 'active'}"><span>${label}</span>${count !== '' ? `<b>${count}</b>` : ''}</button>`).join('')}
      </div>
      <section class="case360-panel" role="tabpanel" data-case360-panel="overview"><div class="case360-sections">${sectionCards}</div></section>
      <section class="case360-panel" role="tabpanel" data-case360-panel="timeline" hidden>
        <div class="case360-panel-heading"><div><h3>Case Timeline</h3><p>Recorded actions in chronological order</p></div><strong>${timeline.length} events</strong></div>
        ${timeline.length ? `<div class="case360-timeline">${timeline.map(event => `<article><time>${deps.escapeHtml(deps.fmtDate(event.occurred_at))}</time><div><strong>${deps.escapeHtml(humanLabel(event.action))}</strong><small>${deps.escapeHtml([event.actor, event.stage].filter(Boolean).join(' - ') || 'System')}</small></div></article>`).join('')}</div>` : '<div class="empty-state">No exact events recorded yet.</div>'}
      </section>
      <section class="case360-panel" role="tabpanel" data-case360-panel="tat" hidden>
        <div class="case360-panel-heading"><div><h3>Turnaround Time</h3><p>Time spent at each tracked workflow stage</p></div></div>
        ${tat.historical_timestamps_available ? '' : '<div class="batch-warning">Historical stage timestamps were not inferred. TAT begins with exact events recorded after tracking was enabled.</div>'}
        <div class="case360-tat-total"><div><span>Total tracked TAT</span><strong>${tat.total_minutes == null ? '-' : deps.escapeHtml(formatTatMinutes(tat.total_minutes))}</strong></div><span class="case360-sla ${deps.escapeHtml(tat.status || '')}">${deps.escapeHtml(humanLabel(tat.status || ''))}</span></div><div class="case360-tat-list">${stageRows}</div>
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

    el('sheet-name').textContent = farmer.customer_name || 'Unknown Farmer';
    const location = deps.locationText(farmer);
    el('sheet-sub').textContent = location !== '-' ? location : (farmer.primary_phone || '');

    const infoFields = summaryFields(farmer, mode);

    el('sheet-info').innerHTML = infoFields.map(([label, value]) =>
      `<li class="info-row"><span class="ir-label">${deps.escapeHtml(label)}</span><span class="ir-value">${value}</span></li>`
    ).join('');
    const caseToggle = el('case360-toggle');
    caseToggle.textContent = 'Open Case History';
    caseToggle.onclick = () => {
      window.PortalAppShell?.openCaseHistory(farmer.id);
    };

    const formEl = el('sheet-form');
    const footerEl = el('sheet-footer');
    formEl.innerHTML = '';
    footerEl.innerHTML = '';
    el('sheet-gate-warning').style.display = 'none';

    const writeCapability = MODE_WRITE_CAPABILITIES[mode];
    if (writeCapability && !hasCapability(writeCapability)) {
      formEl.innerHTML = '<div class="field-help">Your role can view this case but is not assigned to update this workflow stage.</div>';
    } else if (mode === 'jbl_visit') {
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
      el('btn-view-laf')?.addEventListener('click', () => loadLafMedia(farmer.id));
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
    const statusOptions = state().metaStatuses.map(status =>
      `<option value="${deps.escapeHtml(status)}"${farmer.jbl_visit_status === status ? ' selected' : ''}>${deps.escapeHtml(status)}</option>`
    ).join('');
    const countyOptions = (state().metaCounties || []).map(county =>
      `<option value="${deps.escapeHtml(county)}"></option>`
    ).join('');
    const mediaFields = hasCapability('portal.jbl_media.write') ? `
        <div class="form-row media-upload-row">
          <label>Visit Media</label>
          <div class="media-upload-control">
            <div class="media-category-upload">
              <label for="jbl-laf-media">LAF document(s)</label>
              <input type="file" id="jbl-laf-media" name="laf_files" multiple accept="application/pdf,.pdf,image/*,.doc,.docx,.xls,.xlsx">
              <small>Stored in the LAF folder.</small>
            </div>
            <div class="media-category-upload">
              <label for="jbl-visit-photo-media">JBL visit photo(s)</label>
              <input type="file" id="jbl-visit-photo-media" name="jbl_visit_photo_files" multiple accept="image/*,.pdf,.doc,.docx,.xls,.xlsx">
              <small>Stored in the JBL visit photo folder.</small>
            </div>
            ${farmer.jbl_media_count ? `<small>${farmer.jbl_media_count} existing Drive link${farmer.jbl_media_count === 1 ? '' : 's'} on this record.</small>` : ''}
          </div>
        </div>` : '';
    return `
      <div class="form-section">
        <div class="form-row"><label title="JBL visits follow the HBG visit and cannot be dated earlier.">Visit Date <span class="label-help" aria-hidden="true">?</span></label><input type="date" id="jbl-date" min="${deps.escapeHtml(hbgVisitDate)}" value="${deps.escapeHtml(farmer.jbl_visit_date || defaultVisitDate)}"></div>
        <div class="form-row"><label>Status / Outcome</label><select id="jbl-status"><option value="">- Select -</option>${statusOptions}</select></div>
        <div class="form-row"><label>Officer Name</label><input type="text" id="jbl-officer" placeholder="Your name" value="${deps.escapeHtml(farmer.jbl_officer || '')}"></div>
        <div class="form-row"><label>County</label><input type="text" id="jbl-county" list="jbl-county-options" placeholder="County" value="${deps.escapeHtml(farmer.county || '')}"><datalist id="jbl-county-options">${countyOptions}</datalist></div>
        <div class="form-row"><label>Constituency</label><input type="text" id="jbl-sub-county" placeholder="Constituency / sub-county" value="${deps.escapeHtml(farmer.sub_county || '')}"></div>
        <div class="form-row"><label>Village</label><input type="text" id="jbl-village" placeholder="Village / area" value="${deps.escapeHtml(farmer.village || '')}"></div>
        <div class="form-row"><label>Comment (optional)</label><textarea id="jbl-comment" rows="2" placeholder="Additional notes...">${deps.escapeHtml(farmer.jbl_visit_comment || '')}</textarea></div>
        ${mediaFields}
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
    const imabOptions = (state().metaImabOptions.length ? state().metaImabOptions : ['Yes', 'No', 'Pending']).map(value =>
      `<option value="${deps.escapeHtml(value)}"${farmer.imab_created === value ? ' selected' : ''}>${deps.escapeHtml(value)}</option>`
    ).join('');
    const customerNoDisabled = farmer.imab_created !== 'Yes';
    const spinReferences = (farmer.spin_references || []).map((reference, index) => {
      const links = (reference.links || []).map(link => `<a class="media-link" href="${deps.escapeHtml(link.url)}" target="_blank" rel="noopener">${deps.escapeHtml(link.label)}</a>`).join('');
      const names = (reference.attachment_names || []).map(name => deps.escapeHtml(name)).join(', ');
      return `<article class="credit-reference"><div><strong>${deps.escapeHtml(reference.request_type || `SPIN/CRB request ${index + 1}`)}</strong><small>${deps.escapeHtml(reference.status || '')}${reference.created_at ? ` · ${deps.escapeHtml(deps.fmtDate(reference.created_at))}` : ''}</small></div>${links || (names ? `<small>Uploaded: ${names}</small>` : '<small>No report link recorded yet.</small>')}</article>`;
    }).join('');
    return `
      <div class="form-section">
        ${spinReferences ? `<div class="credit-reference-panel"><div class="field-help"><strong>SPIN / CRB reference</strong> · reports already uploaded for this customer</div>${spinReferences}</div>` : ''}
        <div class="field-help credit-status-help"><strong>Status guide:</strong> Pending = the initial state until an analyst records a decision; Approved = move to Head of Rural review; Rejected = stop the case; Deferred = pause and reappraise after the deferral window; Exemption Approved = approved under the exemption path.</div>
        <div class="form-row"><label title="Pending is the default until a credit analyst records a decision.">Credit Decision <span class="label-help" aria-hidden="true">?</span></label><select id="credit-decision"><option value="">- Select a decision -</option>${decisionOptions}</select><small class="field-help">Current status: <strong>${deps.escapeHtml(currentDecision)}</strong>. Pending is display-only and cannot be submitted as a decision.</small></div>
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
        ${hasCapability('portal.jbl_media.view') ? `<div class="form-row">
          <label>LAF document</label>
          <button type="button" class="secondary" id="btn-view-laf">View LAF document(s)</button>
          <div id="final-laf-media" class="media-links" hidden></div>
        </div>` : ''}
        <div class="form-row"><label>Repayment Dates</label><input type="text" id="final-repayment-date" placeholder="e.g. 10TH" value="${deps.escapeHtml(farmer.repayment_date || '')}"></div>
        <div class="form-row"><label>Tenor</label><input type="text" id="final-repayment-tenor" placeholder="e.g. 6 months" value="${deps.escapeHtml(farmer.repayment_tenor || '')}"></div>
        <div class="form-row"><label>After-call Comments</label><textarea id="final-comment" rows="4" placeholder="Summarize the call and reason for the decision...">${deps.escapeHtml(farmer.final_decision_comment || '')}</textarea></div>
      </div>
      ${farmer.jbl_visit_comment ? `<div class="info-row"><span class="ir-label">BRO Comment</span><span class="ir-value">${deps.escapeHtml(farmer.jbl_visit_comment)}</span></div>` : ''}
    `;
  }

  async function loadLafMedia(farmerId) {
    const button = el('btn-view-laf');
    const target = el('final-laf-media');
    if (!farmerId || !target) return;
    button && (button.disabled = true);
    target.hidden = false;
    target.innerHTML = '<span class="field-help">Loading LAF documents...</span>';
    try {
      const result = await deps.apiFetch('/jbl-queue/' + encodeURIComponent(farmerId) + '/media/list/');
      const media = result.data?.laf_media || [];
      if (!result.ok || !result.data?.ok) {
        target.innerHTML = `<span class="field-help">${deps.escapeHtml(result.data?.error || 'Could not load LAF documents.')}</span>`;
        return;
      }
      target.innerHTML = media.length
        ? media.map((item, index) => `<a class="media-link" href="${deps.escapeHtml(item.url)}" target="_blank" rel="noopener">${deps.escapeHtml(item.name || `LAF document ${index + 1}`)} <span aria-hidden="true">↗</span></a>`).join('')
        : '<span class="field-help">No LAF document has been uploaded for this client.</span>';
    } catch (error) {
      target.innerHTML = '<span class="field-help">Could not load LAF documents. Check your connection and retry.</span>';
    } finally {
      if (button) button.disabled = false;
    }
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

    const btn = el('btn-submit-jbl');
    deps.setButtonLoading(btn, true, 'Saving...');
    const { ok, data } = await deps.apiFetch('/jbl-queue/' + farmer.id + '/', {
      method: 'POST',
      body: JSON.stringify({
        request_id: requestId(),
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
    const mediaResult = await uploadJblMediaIfSelected(farmer.id);
    if (!mediaResult.ok) {
      deps.showToast('JBL visit logged, but media upload failed. Retry the media upload from this record.', 'error');
      return;
    }
    const uploaded = mediaResult.storedCount;
    deps.showToast(
      uploaded ? `JBL visit logged and ${uploaded} media file${uploaded === 1 ? '' : 's'} uploaded.` : 'JBL visit logged successfully.',
      mediaResult.partial ? 'warning' : 'success',
    );
    closeSheet();
    deps.reloadCurrentQueue();
    deps.loadDashboard();
  }

  async function uploadJblMediaIfSelected(farmerId) {
    const lafFiles = Array.from(el('jbl-laf-media')?.files || []);
    const visitPhotoFiles = Array.from(el('jbl-visit-photo-media')?.files || []);
    if (!lafFiles.length && !visitPhotoFiles.length) return { ok: true, storedCount: 0, partial: false };
    if (!navigator.onLine) {
      return { ok: false, storedCount: 0, partial: false, error: 'Offline' };
    }
    const formData = new FormData();
    lafFiles.forEach(file => formData.append('laf_files', file));
    visitPhotoFiles.forEach(file => formData.append('jbl_visit_photo_files', file));
    try {
      const result = await deps.portalApi.postForm('/jbl-queue/' + farmerId + '/media/', formData, deps.tg, { 'X-CSRFToken': deps.getCookie('csrftoken') || '' });
      const data = result.data || {};
      if (!result.ok || data.ok === false) {
        return { ok: false, storedCount: Number(data.stored_count || 0), partial: false, error: data.error || 'Media upload failed' };
      }
      const warnings = Array.isArray(data.warnings) && data.warnings.length ? ' ' + data.warnings.join(' ') : '';
      const errors = Array.isArray(data.errors) && data.errors.length
        ? ' ' + data.errors.map(item => `${item.category}: ${item.error}`).join(' ')
        : '';
      const isPartial = Boolean(data.partial || data.errors?.length);
      return { ok: !errors, storedCount: Number(data.stored_count || 0), partial: isPartial || Boolean(data.warnings?.length), error: errors || warnings };
    } catch (err) {
      console.error(err);
      return { ok: false, storedCount: 0, partial: false, error: 'Media upload failed' };
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
      body: JSON.stringify({ request_id: requestId(), decision, imab_created: imabCreated, customer_no: customerNo }),
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
    const repaymentDate = el('final-repayment-date')?.value || '';
    const repaymentTenor = el('final-repayment-tenor')?.value || '';
    if (!finalDecision) return deps.showToast('Please select a final decision', 'error');

    const btn = el('btn-submit-final');
    deps.setButtonLoading(btn, true, 'Saving...');
    const { ok, data } = await deps.apiFetch('/final-review-queue/' + farmer.id + '/', {
      method: 'POST',
      body: JSON.stringify({
        request_id: requestId(),
        final_decision: finalDecision,
        decision_comment: decisionComment,
        repayment_date: repaymentDate,
        repayment_tenor: repaymentTenor,
      }),
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
        request_id: requestId(),
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
    deps.showToast('Order assigned. Showing it under Batches.', 'success');
    closeSheet();
    deps.reloadCurrentQueue();
    deps.loadDashboard();
    if (deps.openAssignedOrder) {
      await deps.openAssignedOrder(orderNumber);
    }
  }

  function bindEvents() {
    if (document.documentElement.dataset.portalSheetCloseBound) return;
    document.documentElement.dataset.portalSheetCloseBound = 'true';
    document.addEventListener('click', event => {
      if (event.target.closest('#sheet-close')) {
        closeSheet();
        return;
      }
      if (event.target.closest('#sheet-map-refresh')) {
        refreshMap();
        return;
      }
      const overlay = event.target.closest('#sheet-overlay');
      if (overlay && event.target === overlay) closeSheet();
    });
  }

  function init(initialDeps) {
    deps = initialDeps;
    bindEvents();
  }

  window.PortalMiniAppFarmerSheet = {
    init,
    openFarmerSheet,
    closeSheet,
    renderCase360,
  };
})();
