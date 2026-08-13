(function () {
  'use strict';
  const app = document.getElementById('calibration-app');
  if (!app) return;
  const $ = id => document.getElementById(id);
  const copy = value => JSON.parse(JSON.stringify(value));
  const escapeHtml = value => { const node = document.createElement('div'); node.textContent = String(value ?? ''); return node.innerHTML; };
  const csrf = document.cookie.split('; ').find(item => item.startsWith('csrftoken='))?.split('=')[1] || '';

  let configuration = null;
  let revision = 0;
  let pageSizes = [];
  let contextKeys = [];
  let schemaRevision = 0;
  let formSections = [];
  let signatureCatalog = [];
  let selectedKind = 'field';
  let selectedKey = '';
  let page = 1;
  let zoom = 1;
  let mode = 'source';
  let pageUrl = '';
  let dirty = false;
  let drawing = false;
  let previewTimer = null;

  const fields = () => configuration?.field_overlay_manifest?.fields || {};
  const signatures = () => configuration?.signature_overlay_manifest?.slots || {};
  const pageSize = () => pageSizes.find(item => item.page_number === page);
  const unitsScale = spec => spec.units === 'mm' ? 72 / 25.4 : 1;
  const boxFor = spec => spec?.allowed_area || spec?.box;
  const centeredBox = (width, height) => {
    const size = pageSize();
    if (!size) return null;
    const pageWidth = Number(size.width);
    const pageHeight = Number(size.height);
    const boxWidth = Math.min(Number(width), pageWidth);
    const boxHeight = Math.min(Number(height), pageHeight);
    const rounded = value => Math.round(value * 100) / 100;
    return {
      x: rounded((pageWidth - boxWidth) / 2),
      y: rounded((pageHeight - boxHeight) / 2),
      width: rounded(boxWidth),
      height: rounded(boxHeight),
    };
  };
  const currentCollection = () => selectedKind === 'signature' ? signatures() : fields();
  const currentSpec = () => currentCollection()[selectedKey];
  const status = (message, error) => {
    $('calibration-status').textContent = message;
    $('calibration-status').style.color = error ? '#ba2121' : '';
  };

  async function jsonRequest(url, options) {
    const response = await fetch(url, {
      credentials: 'same-origin', ...options,
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, ...(options?.headers || {}) },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || 'Request failed.');
    return data;
  }

  async function load() {
    try {
      const state = await jsonRequest(app.dataset.stateUrl);
      configuration = state.configuration || {};
      configuration.field_overlay_manifest ||= { fields: {} };
      configuration.field_overlay_manifest.fields ||= {};
      configuration.signature_overlay_manifest ||= { slots: {} };
      configuration.signature_overlay_manifest.slots ||= {};
      configuration.sample_context ||= {};
      revision = state.revision;
      pageSizes = state.page_sizes || [];
      contextKeys = state.context_keys || [];
      schemaRevision = state.schema_revision || 0;
      formSections = state.form_sections || [];
      signatureCatalog = state.signature_slots || [];
      const firstField = Object.keys(fields())[0];
      const firstSignature = Object.keys(signatures())[0];
      selectedKind = firstField ? 'field' : 'signature';
      selectedKey = firstField || firstSignature || '';
      populateCatalogs();
      populateGlobalFormatting();
      renderItemList();
      await renderPage();
      inspect();
      status(state.product_published ? `Product published at revision ${revision}` : state.published ? `Alignment published at revision ${revision}` : `Draft revision ${revision}`);
    } catch (error) {
      status(error.message, true);
    }
  }

  function populateCatalogs() {
    $('cal-context').innerHTML = contextKeys.map(item => `<option value="${escapeHtml(item.key)}">${escapeHtml(item.label)} · ${escapeHtml(item.key)}${item.attached ? '' : ' · catalogue'}</option>`).join('');
    $('cal-signature-slot').innerHTML = signatureCatalog.map(item => {
      const identity = `${item.role}.${item.slot_key}`;
      return `<option value="${escapeHtml(identity)}">${escapeHtml(item.label)} · ${escapeHtml(item.role)}</option>`;
    }).join('');
  }

  function populateGlobalFormatting() {
    const defaults = configuration?.field_overlay_manifest?.defaults || {};
    const firstText = Object.values(fields()).find(spec => (spec.render_as || 'text') !== 'checkbox') || {};
    const seed = { ...firstText, ...defaults };
    $('global-font').value = seed.font || 'Helvetica';
    $('global-font-size').value = seed.font_size || 8;
    $('global-min-font-size').value = seed.min_font_size || 5;
    $('global-text-case').value = seed.text_case || 'none';
    $('global-align').value = seed.align || 'left';
    $('global-vertical').value = seed.vertical_align || 'bottom';
    $('global-fit').value = seed.fit || 'shrink';
    const padding = typeof seed.padding === 'object' ? seed.padding : { x: seed.padding || 0, y: seed.padding || 0 };
    $('global-padding-x').value = padding.x || 0;
    $('global-padding-y').value = padding.y || 0;
  }

  function renderItemList() {
    const query = $('calibration-search').value.trim().toLowerCase();
    const items = [
      ...Object.entries(fields()).map(([key, spec]) => ({ kind: 'field', key, label: spec.context_key || key })),
      ...Object.entries(signatures()).map(([key, spec]) => ({ kind: 'signature', key, label: spec.label || key })),
    ].filter(item => `${item.kind} ${item.key} ${item.label}`.toLowerCase().includes(query));
    $('calibration-fields').innerHTML = items.map(item => {
      const value = `${item.kind}:${item.key}`;
      const selected = item.kind === selectedKind && item.key === selectedKey;
      const prefix = item.kind === 'signature' ? 'SIGN' : 'FIELD';
      return `<option value="${escapeHtml(value)}"${selected ? ' selected' : ''}>${prefix} · ${escapeHtml(item.label)}</option>`;
    }).join('');
    renderOverlays();
  }

  async function renderPage() {
    if (pageUrl) URL.revokeObjectURL(pageUrl);
    status(mode === 'filled' ? 'Rendering filled sample…' : 'Loading template…');
    const options = mode === 'filled' ? { method: 'POST', body: JSON.stringify({ configuration, page }) } : undefined;
    const url = mode === 'filled' ? app.dataset.previewUrl : `${app.dataset.pageUrl}?page=${page}`;
    const response = await fetch(url, {
      credentials: 'same-origin', ...options,
      headers: mode === 'filled' ? { 'Content-Type': 'application/json', 'X-CSRFToken': csrf } : {},
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || 'Preview failed.');
    }
    pageUrl = URL.createObjectURL(await response.blob());
    const image = $('calibration-page');
    await new Promise((resolve, reject) => { image.onload = resolve; image.onerror = reject; image.src = pageUrl; });
    applyZoom();
    renderOverlays();
    status(dirty ? 'Unsaved calibration changes' : `Revision ${revision}`);
  }

  function applyZoom() {
    const image = $('calibration-page');
    const size = pageSize();
    if (!size || !image.naturalWidth) return;
    image.style.width = `${image.naturalWidth * zoom}px`;
    $('calibration-canvas').style.width = image.style.width;
    $('calibration-canvas').style.height = `${image.naturalHeight * zoom}px`;
    $('cal-page-label').textContent = `Page ${page} of ${pageSizes.length}`;
    $('cal-zoom-label').textContent = `${Math.round(zoom * 100)}%`;
    $('cal-prev').disabled = page <= 1;
    $('cal-next').disabled = page >= pageSizes.length;
  }

  function renderOverlays() {
    const layer = $('calibration-overlays');
    const image = $('calibration-page');
    const size = pageSize();
    layer.replaceChildren();
    if (!size || !image.clientWidth) return;
    const scale = image.clientWidth / size.width;
    const items = [
      ...Object.entries(fields()).map(([key, spec]) => ({ kind: 'field', key, spec })),
      ...Object.entries(signatures()).map(([key, spec]) => ({ kind: 'signature', key, spec })),
    ];
    items.forEach(({ kind, key, spec }) => {
      if (Number(spec.page_number || 1) !== page) return;
      const box = boxFor(spec);
      if (!box) return;
      const unit = unitsScale(spec);
      const element = document.createElement('div');
      const selected = kind === selectedKind && key === selectedKey;
      element.className = `calibration-box ${kind}${selected ? ' selected' : ''}`;
      element.dataset.kind = kind;
      element.dataset.key = key;
      element.style.left = `${Number(box.x) * unit * scale}px`;
      element.style.top = `${(size.height - (Number(box.y) + Number(box.height)) * unit) * scale}px`;
      element.style.width = `${Number(box.width) * unit * scale}px`;
      element.style.height = `${Number(box.height) * unit * scale}px`;
      const label = kind === 'signature' ? (spec.label || key) : (spec.context_key || key);
      element.innerHTML = `<span>${escapeHtml(label)}</span><i aria-label="Resize"></i>`;
      element.addEventListener('pointerdown', beginPointerEdit);
      element.addEventListener('click', () => select(kind, key));
      layer.appendChild(element);
    });
    layer.onpointerdown = beginDraw;
  }

  function beginDraw(event) {
    if (!drawing || event.target !== event.currentTarget || !currentSpec()) return;
    event.preventDefault();
    const layer = event.currentTarget;
    const rect = layer.getBoundingClientRect();
    const size = pageSize();
    const scale = $('calibration-page').clientWidth / size.width;
    const startX = event.clientX - rect.left;
    const startY = event.clientY - rect.top;
    const moveHandler = move => {
      const left = Math.min(startX, move.clientX - rect.left);
      const top = Math.min(startY, move.clientY - rect.top);
      const width = Math.max(3, Math.abs(move.clientX - rect.left - startX));
      const height = Math.max(3, Math.abs(move.clientY - rect.top - startY));
      const spec = currentSpec();
      spec.units = 'pt'; spec.page_number = page;
      setBox(spec, { x: left / scale, y: size.height - (top + height) / scale, width: width / scale, height: height / scale });
      markDirty(); inspect(); renderOverlays();
    };
    const upHandler = () => {
      drawing = false;
      $('calibration-overlays').style.cursor = '';
      $('calibration-draw').classList.remove('selected');
      window.removeEventListener('pointermove', moveHandler);
    };
    window.addEventListener('pointermove', moveHandler);
    window.addEventListener('pointerup', upHandler, { once: true });
  }

  function beginPointerEdit(event) {
    event.preventDefault();
    const element = event.currentTarget;
    select(element.dataset.kind, element.dataset.key);
    const spec = currentSpec();
    const start = { x: event.clientX, y: event.clientY, box: copy(boxFor(spec)) };
    const resizing = event.target.tagName === 'I';
    const moveHandler = move => {
      const size = pageSize();
      const scale = $('calibration-page').clientWidth / size.width;
      const unit = unitsScale(spec);
      const dx = (move.clientX - start.x) / scale / unit;
      const dy = (move.clientY - start.y) / scale / unit;
      const next = copy(start.box);
      if (resizing) { next.width = Math.max(1, start.box.width + dx); next.height = Math.max(1, start.box.height - dy); }
      else { next.x = Math.max(0, start.box.x + dx); next.y = Math.max(0, start.box.y - dy); }
      setBox(spec, next); markDirty(); inspect(); renderOverlays();
    };
    window.addEventListener('pointermove', moveHandler);
    window.addEventListener('pointerup', () => window.removeEventListener('pointermove', moveHandler), { once: true });
  }

  function setBox(spec, box) { spec.box = copy(box); spec.allowed_area = copy(box); }
  function select(kind, key) { selectedKind = kind; selectedKey = key; renderItemList(); inspect(); }

  function inspect() {
    const spec = currentSpec();
    const panel = $('calibration-inspector');
    panel.hidden = !spec;
    if (!spec) return;
    const isSignature = selectedKind === 'signature';
    $('calibration-inspector-title').textContent = isSignature ? 'Selected signer slot' : 'Selected field';
    $('calibration-field-controls').hidden = isSignature;
    $('calibration-signature-controls').hidden = !isSignature;
    $('calibration-format-controls').hidden = isSignature;
    $('calibration-duplicate').disabled = isSignature;
    const box = boxFor(spec);
    $('cal-x').value = box.x; $('cal-y').value = box.y; $('cal-width').value = box.width; $('cal-height').value = box.height;
    if (isSignature) {
      $('cal-signature-slot').value = selectedKey;
      $('cal-signature-type').value = spec.slot_type || 'signature';
      return;
    }
    $('cal-context').value = spec.context_key || '';
    $('cal-font').value = spec.font || 'Helvetica';
    $('cal-font-size').value = spec.font_size || 8;
    $('cal-min-font-size').value = spec.min_font_size || 5;
    $('cal-render-as').value = spec.render_as || 'text';
    $('cal-checked-when').value = spec.checked_when ?? '';
    const padding = typeof spec.padding === 'object' ? spec.padding : { x: spec.padding || 0, y: spec.padding || 0 };
    $('cal-padding-x').value = padding.x || 0; $('cal-padding-y').value = padding.y || 0;
    $('cal-text-case').value = spec.text_case || 'none';
    $('cal-align').value = spec.align || 'left'; $('cal-vertical').value = spec.vertical_align || 'bottom'; $('cal-fit').value = spec.fit || 'shrink';
    $('cal-checked-wrap').hidden = $('cal-render-as').value !== 'checkbox';
  }

  function markDirty() {
    dirty = true;
    status('Unsaved calibration changes');
    if (mode === 'filled') {
      window.clearTimeout(previewTimer);
      previewTimer = window.setTimeout(() => renderPage().catch(error => status(error.message, true)), 500);
    }
  }

  function updateGeometry() {
    const spec = currentSpec();
    if (!spec) return;
    setBox(spec, { x: Number($('cal-x').value), y: Number($('cal-y').value), width: Number($('cal-width').value), height: Number($('cal-height').value) });
    markDirty(); renderItemList(); inspect();
  }

  function updateSelectedField() {
    const spec = currentSpec();
    if (!spec || selectedKind !== 'field') return;
    spec.context_key = $('cal-context').value;
    spec.font = $('cal-font').value;
    spec.font_size = Number($('cal-font-size').value);
    spec.min_font_size = Number($('cal-min-font-size').value);
    spec.render_as = $('cal-render-as').value;
    spec.padding = { x: Number($('cal-padding-x').value), y: Number($('cal-padding-y').value) };
    spec.text_case = $('cal-text-case').value;
    spec.checked_when = $('cal-checked-when').value;
    spec.align = $('cal-align').value;
    spec.vertical_align = $('cal-vertical').value;
    spec.fit = $('cal-fit').value;
    markDirty(); renderItemList(); inspect();
  }

  function selectedCatalogueField(id) {
    return contextKeys.find(item => String(item.id || '') === String(id || ''));
  }

  function fieldOptionLines(item) {
    return (item?.choice_options || []).filter(option => option.active !== false).map(option => `${option.code} | ${option.label || option.code}`).join('\n');
  }

  function populateFieldDialog(query = '') {
    const normalized = String(query || '').trim().toLowerCase();
    const matches = contextKeys.filter(item => {
      const haystack = [item.label, item.key, item.category, ...(item.aliases || [])].join(' ').toLowerCase();
      return !normalized || haystack.includes(normalized);
    });
    $('cal-field-catalogue').innerHTML = matches.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.category || 'Application')} · ${escapeHtml(item.label)} · ${escapeHtml(item.key)}${item.attached ? ' · on form' : ''}</option>`).join('');
    if (!$('cal-field-catalogue').value && matches.length) $('cal-field-catalogue').value = matches[0].id;
    populateFieldDefaults();
  }

  function populateFieldDefaults() {
    const item = selectedCatalogueField($('cal-field-catalogue').value);
    if (!item || $('cal-field-custom').checked) return;
    $('cal-field-label').value = item.label || '';
    $('cal-field-help').value = item.help_text || '';
    $('cal-field-presentation').hidden = item.source_type === 'system';
    $('cal-field-options-wrap').hidden = item.type !== 'choice';
    $('cal-field-options').value = fieldOptionLines(item);
  }

  function openFieldDialog(preselectedKey = '') {
    const dialog = $('calibration-field-dialog');
    $('cal-field-error').hidden = true;
    $('cal-field-custom').checked = false;
    $('cal-field-create').hidden = true;
    $('cal-field-presentation').hidden = false;
    $('cal-field-required').checked = false;
    $('cal-field-width').value = 'half';
    $('cal-new-label').value = '';
    $('cal-new-key').value = '';
    delete $('cal-new-key').dataset.touched;
    $('cal-new-type').value = 'text';
    $('cal-new-sensitivity').value = 'pii';
    $('cal-new-category').value = 'Application';
    $('cal-new-aliases').value = '';
    $('cal-new-options').value = '';
    $('cal-new-options-wrap').hidden = true;
    $('cal-field-section').innerHTML = formSections.map(section => `<option value="${escapeHtml(section.key)}">${escapeHtml(section.label || section.key)}</option>`).join('');
    $('cal-field-search').value = '';
    populateFieldDialog();
    const selected = contextKeys.find(item => item.key === preselectedKey);
    if (selected?.id) $('cal-field-catalogue').value = selected.id;
    populateFieldDefaults();
    dialog.showModal();
  }

  function closeFieldDialog() { $('calibration-field-dialog').close(); }

  function parseProductOptions(value) {
    return String(value || '').split(/\r?\n/).map(item => item.trim()).filter(Boolean).map(item => {
      const [code, ...label] = item.split('|');
      return { code: code.trim(), label: label.join('|').trim() || code.trim() };
    });
  }

  async function submitFieldDialog(event) {
    event.preventDefault();
    const custom = $('cal-field-custom').checked;
    const selected = selectedCatalogueField($('cal-field-catalogue').value);
    const type = custom ? $('cal-new-type').value : selected?.type;
    const body = {
      schema_revision: schemaRevision,
      data_field_id: custom ? '' : selected?.id,
      presentation: {
        section_key: $('cal-field-section').value,
        label: $('cal-field-label').value,
        required: $('cal-field-required').checked,
        width: $('cal-field-width').value,
        help_text: $('cal-field-help').value,
        options: type === 'choice' ? parseProductOptions($('cal-field-options').value) : [],
      },
    };
    if (custom) {
      body.create_field = {
        label: $('cal-new-label').value,
        key: $('cal-new-key').value,
        type,
        sensitivity: $('cal-new-sensitivity').value,
        category: $('cal-new-category').value,
        aliases: $('cal-new-aliases').value.split(',').map(item => item.trim()).filter(Boolean),
        choice_options: type === 'choice'
          ? $('cal-new-options').value.split(/\r?\n/).map(item => item.trim()).filter(Boolean)
          : [],
      };
    }
    const error = $('cal-field-error');
    try {
      $('cal-field-confirm').disabled = true;
      const data = await jsonRequest(app.dataset.fieldUrl, { method: 'POST', body: JSON.stringify(body) });
      contextKeys = data.context_keys || contextKeys;
      schemaRevision = data.schema_revision;
      formSections = data.form_sections || formSections;
      populateCatalogs();
      closeFieldDialog();
      addFieldOverlay(data.field.key);
      status(data.replayed ? `${data.field.label} mapped to the PDF.` : `${data.field.label} added to the form and PDF.`);
    } catch (requestError) {
      error.textContent = requestError.message;
      error.hidden = false;
    } finally {
      $('cal-field-confirm').disabled = false;
    }
  }

  function addFieldOverlay(context) {
    if (!context) return status('Choose a canonical data field.', true);
    const box = centeredBox(120, 14);
    if (!box) return status('The current PDF page is not ready yet.', true);
    let key = context, index = 2;
    while (fields()[key]) key = `${context}_${index++}`;
    fields()[key] = {
      context_key: context, units: 'pt', page_number: page,
      box: copy(box), allowed_area: copy(box),
      font: 'Helvetica', font_size: 8, min_font_size: 5, vertical_align: 'bottom', fit: 'shrink', padding: { x: 0, y: 0 },
    };
    const catalogueField = contextKeys.find(item => item.key === context);
    configuration.sample_context[context] ||= catalogueField?.label || context.replaceAll('_', ' ');
    select('field', key); markDirty();
  }

  ['cal-x', 'cal-y', 'cal-width', 'cal-height'].forEach(id => $(id).addEventListener('change', updateGeometry));
  ['cal-font', 'cal-font-size', 'cal-min-font-size', 'cal-padding-x', 'cal-padding-y', 'cal-text-case', 'cal-render-as', 'cal-checked-when', 'cal-align', 'cal-vertical', 'cal-fit'].forEach(id => $(id).addEventListener('change', updateSelectedField));
  $('cal-context').addEventListener('change', event => {
    const item = contextKeys.find(candidate => candidate.key === event.target.value);
    if (item && !item.attached && item.source_type === 'user_input') {
      event.target.value = currentSpec()?.context_key || '';
      openFieldDialog(item.key);
      return;
    }
    updateSelectedField();
  });
  $('calibration-fields').onchange = event => { const [kind, ...key] = event.target.value.split(':'); select(kind, key.join(':')); };
  $('calibration-search').oninput = renderItemList;

  $('calibration-add').onclick = () => {
    if (!contextKeys.length) return status('No canonical data fields are available.', true);
    openFieldDialog();
  };

  $('cal-field-search').oninput = event => populateFieldDialog(event.target.value);
  $('cal-field-catalogue').onchange = populateFieldDefaults;
  $('cal-field-custom').onchange = event => {
    $('cal-field-create').hidden = !event.target.checked;
    if (event.target.checked) {
      $('cal-field-presentation').hidden = false;
      $('cal-new-label').focus();
      $('cal-field-label').value = '';
      $('cal-field-help').value = '';
      $('cal-field-options-wrap').hidden = true;
    } else {
      populateFieldDefaults();
    }
  };
  $('cal-new-label').oninput = event => {
    if (!$('cal-new-key').dataset.touched) {
      $('cal-new-key').value = event.target.value.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
    }
    if (!$('cal-field-label').value) $('cal-field-label').value = event.target.value;
  };
  $('cal-new-key').oninput = () => { $('cal-new-key').dataset.touched = '1'; };
  $('cal-new-type').onchange = event => {
    const choice = event.target.value === 'choice';
    $('cal-new-options-wrap').hidden = !choice;
    $('cal-field-options-wrap').hidden = !choice;
  };
  $('calibration-field-form').onsubmit = submitFieldDialog;
  $('cal-field-cancel').onclick = closeFieldDialog;
  $('cal-field-dismiss').onclick = closeFieldDialog;

  $('calibration-add-signature').onclick = () => {
    const slot = signatureCatalog.find(item => !signatures()[`${item.role}.${item.slot_key}`]);
    if (!slot) return status('Every configured signer slot is already placed.', true);
    const key = `${slot.role}.${slot.slot_key}`;
    const box = centeredBox(140, slot.slot_type === 'stamp' ? 55 : 28);
    if (!box) return status('The current PDF page is not ready yet.', true);
    signatures()[key] = {
      role: slot.role, slot_key: slot.slot_key, label: slot.label, slot_type: slot.slot_type,
      units: 'pt', page_number: page,
      box: copy(box), allowed_area: copy(box),
    };
    select('signature', key); markDirty();
  };

  $('cal-signature-slot').addEventListener('change', event => {
    if (selectedKind !== 'signature' || event.target.value === selectedKey) return;
    if (signatures()[event.target.value]) { event.target.value = selectedKey; return status('That signer slot is already placed.', true); }
    const catalog = signatureCatalog.find(item => `${item.role}.${item.slot_key}` === event.target.value);
    const spec = signatures()[selectedKey];
    delete signatures()[selectedKey];
    selectedKey = event.target.value;
    Object.assign(spec, { role: catalog.role, slot_key: catalog.slot_key, label: catalog.label, slot_type: catalog.slot_type });
    signatures()[selectedKey] = spec;
    markDirty(); renderItemList(); inspect();
  });

  $('calibration-draw').onclick = () => {
    if (!currentSpec()) { $('calibration-add').click(); return; }
    drawing = true; $('calibration-overlays').style.cursor = 'crosshair'; $('calibration-draw').classList.add('selected');
    status('Drag on the document to draw the selected area.');
  };
  $('calibration-duplicate').onclick = () => {
    if (selectedKind !== 'field' || !selectedKey) return;
    const source = fields()[selectedKey];
    let key = `${selectedKey}_copy`, index = 2;
    while (fields()[key]) key = `${selectedKey}_copy_${index++}`;
    fields()[key] = copy(source); fields()[key].box.x += 8; fields()[key].allowed_area = copy(fields()[key].box);
    select('field', key); markDirty();
  };
  $('calibration-delete').onclick = () => {
    if (!selectedKey || !window.confirm(`Delete ${selectedKey}?`)) return;
    delete currentCollection()[selectedKey];
    selectedKey = Object.keys(fields())[0] || Object.keys(signatures())[0] || '';
    selectedKind = Object.keys(fields()).length ? 'field' : 'signature';
    markDirty(); renderItemList(); inspect();
  };

  $('global-apply').onclick = () => {
    const values = {
      font: $('global-font').value, font_size: Number($('global-font-size').value), min_font_size: Number($('global-min-font-size').value),
      text_case: $('global-text-case').value, align: $('global-align').value, vertical_align: $('global-vertical').value,
      fit: $('global-fit').value, padding: { x: Number($('global-padding-x').value), y: Number($('global-padding-y').value) },
    };
    if (values.min_font_size > values.font_size) return status('Minimum font size cannot exceed font size.', true);
    configuration.field_overlay_manifest.defaults = copy(values);
    Object.values(fields()).forEach(spec => { if ((spec.render_as || 'text') !== 'checkbox') Object.assign(spec, copy(values)); });
    markDirty(); inspect(); renderItemList(); status('Global formatting applied. Preview, then save the draft.');
  };

  $('cal-prev').onclick = async () => { if (page > 1) { page--; await renderPage(); } };
  $('cal-next').onclick = async () => { if (page < pageSizes.length) { page++; await renderPage(); } };
  $('cal-zoom-out').onclick = () => { zoom = Math.max(.5, zoom - .25); applyZoom(); renderOverlays(); };
  $('cal-zoom-in').onclick = () => { zoom = Math.min(3, zoom + .25); applyZoom(); renderOverlays(); };
  $('cal-source').onclick = async () => { mode = 'source'; $('cal-source').classList.add('selected'); $('cal-filled').classList.remove('selected'); await renderPage(); };
  $('cal-filled').onclick = async () => { mode = 'filled'; $('cal-filled').classList.add('selected'); $('cal-source').classList.remove('selected'); await renderPage(); };
  $('cal-regenerate').onclick = async () => { try { await renderPage(); } catch (error) { status(error.message, true); } };

  async function saveDraft() {
    const data = await jsonRequest(app.dataset.saveUrl, { method: 'POST', body: JSON.stringify({ revision, configuration }) });
    revision = data.revision; dirty = false; return data;
  }
  $('calibration-save').onclick = async () => {
    try { status('Saving draft…'); await saveDraft(); status(`Draft revision ${revision} saved; Mini App unchanged`); }
    catch (error) { status(error.message, true); }
  };
  $('calibration-publish').onclick = async () => {
    try {
      if (dirty) { status('Saving alignment…'); await saveDraft(); }
      status('Validating and publishing product…');
      const data = await jsonRequest(app.dataset.publishUrl, { method: 'POST', body: JSON.stringify({ revision }) });
      revision = data.revision;
      status(`Published ${data.product_key || 'template'} version ${data.product_version || ''}`.trim());
    } catch (error) { status(error.message, true); }
  };

  window.addEventListener('keydown', event => {
    if (!currentSpec() || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key) || /INPUT|SELECT|TEXTAREA/.test(event.target.tagName)) return;
    event.preventDefault();
    const spec = currentSpec(), box = copy(boxFor(spec)), step = event.shiftKey ? 10 : 2;
    if (event.key === 'ArrowLeft') box.x -= step;
    if (event.key === 'ArrowRight') box.x += step;
    if (event.key === 'ArrowUp') box.y += step;
    if (event.key === 'ArrowDown') box.y -= step;
    box.x = Math.max(0, box.x); box.y = Math.max(0, box.y);
    setBox(spec, box); markDirty(); inspect(); renderOverlays();
  });
  window.addEventListener('beforeunload', event => {
    if (dirty) { event.preventDefault(); event.returnValue = ''; }
    if (pageUrl) URL.revokeObjectURL(pageUrl);
  });
  load();
})();
