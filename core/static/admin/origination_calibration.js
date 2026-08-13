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
    $('cal-context').innerHTML = contextKeys.map(item => `<option value="${escapeHtml(item.key)}">${escapeHtml(item.label)}</option>`).join('');
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

  ['cal-x', 'cal-y', 'cal-width', 'cal-height'].forEach(id => $(id).addEventListener('change', updateGeometry));
  ['cal-context', 'cal-font', 'cal-font-size', 'cal-min-font-size', 'cal-padding-x', 'cal-padding-y', 'cal-text-case', 'cal-render-as', 'cal-checked-when', 'cal-align', 'cal-vertical', 'cal-fit'].forEach(id => $(id).addEventListener('change', updateSelectedField));
  $('calibration-fields').onchange = event => { const [kind, ...key] = event.target.value.split(':'); select(kind, key.join(':')); };
  $('calibration-search').oninput = renderItemList;

  $('calibration-add').onclick = () => {
    const context = contextKeys.find(item => !Object.values(fields()).some(spec => spec.context_key === item.key))?.key || contextKeys[0]?.key;
    if (!context) return status('Add fields to the product before calibrating its PDF.', true);
    let key = context, index = 2;
    while (fields()[key]) key = `${context}_${index++}`;
    fields()[key] = {
      context_key: context, units: 'pt', page_number: page,
      box: { x: 40, y: 40, width: 120, height: 14 }, allowed_area: { x: 40, y: 40, width: 120, height: 14 },
      font: 'Helvetica', font_size: 8, min_font_size: 5, vertical_align: 'bottom', fit: 'shrink', padding: { x: 0, y: 0 },
    };
    select('field', key); markDirty();
  };

  $('calibration-add-signature').onclick = () => {
    const slot = signatureCatalog.find(item => !signatures()[`${item.role}.${item.slot_key}`]);
    if (!slot) return status('Every configured signer slot is already placed.', true);
    const key = `${slot.role}.${slot.slot_key}`;
    signatures()[key] = {
      role: slot.role, slot_key: slot.slot_key, label: slot.label, slot_type: slot.slot_type,
      units: 'pt', page_number: page,
      box: { x: 40, y: 40, width: 140, height: slot.slot_type === 'stamp' ? 55 : 28 },
      allowed_area: { x: 40, y: 40, width: 140, height: slot.slot_type === 'stamp' ? 55 : 28 },
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
    if (!currentSpec()) $('calibration-add').click();
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
