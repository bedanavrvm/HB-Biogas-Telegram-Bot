(function () {
  'use strict';
  const app = document.getElementById('calibration-app');
  if (!app) return;
  const $ = id => document.getElementById(id);
  let configuration = null, revision = 0, pageSizes = [], contextKeys = [];
  let selectedKey = '', page = 1, zoom = 1, mode = 'source', pageUrl = '', dirty = false, drawing = false, previewTimer = null;
  const csrf = document.cookie.split('; ').find(item => item.startsWith('csrftoken='))?.split('=')[1] || '';
  const fields = () => configuration?.field_overlay_manifest?.fields || {};
  const pageSize = () => pageSizes.find(item => item.page_number === page);
  const unitsScale = spec => spec.units === 'mm' ? 72 / 25.4 : 1;
  const boxFor = spec => spec.allowed_area || spec.box;
  const copy = value => JSON.parse(JSON.stringify(value));
  const status = (text, error) => { $('calibration-status').textContent = text; $('calibration-status').style.color = error ? '#ba2121' : ''; };

  async function jsonRequest(url, options) {
    const response = await fetch(url, { credentials: 'same-origin', ...options, headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, ...(options?.headers || {}) } });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || 'Request failed.');
    return data;
  }

  async function load() {
    try {
      const state = await jsonRequest(app.dataset.stateUrl);
      configuration = state.configuration;
      configuration.field_overlay_manifest ||= { fields: {} };
      configuration.field_overlay_manifest.fields ||= {};
      revision = state.revision; pageSizes = state.page_sizes; contextKeys = state.context_keys;
      selectedKey = Object.keys(fields())[0] || '';
      populateContextKeys(); renderFieldList(); await renderPage(); inspect();
      status(state.published ? `Published revision ${revision}` : `Draft revision ${revision}`);
    } catch (error) { status(error.message, true); }
  }

  function populateContextKeys() {
    $('cal-context').innerHTML = contextKeys.map(item => `<option value="${escapeHtml(item.key)}">${escapeHtml(item.label)}</option>`).join('');
  }
  function escapeHtml(value) { const node = document.createElement('div'); node.textContent = value || ''; return node.innerHTML; }
  function renderFieldList() {
    const query = $('calibration-search').value.trim().toLowerCase();
    const keys = Object.keys(fields()).filter(key => `${key} ${fields()[key].context_key || ''}`.toLowerCase().includes(query));
    $('calibration-fields').innerHTML = keys.map(key => `<option value="${escapeHtml(key)}" ${key === selectedKey ? 'selected' : ''}>${escapeHtml(key)} · ${escapeHtml(fields()[key].context_key)}</option>`).join('');
    renderOverlays();
  }
  async function renderPage() {
    if (pageUrl) URL.revokeObjectURL(pageUrl);
    status(mode === 'filled' ? 'Rendering filled sample…' : 'Loading template…');
    const options = mode === 'filled' ? { method: 'POST', body: JSON.stringify({ configuration, page }) } : undefined;
    const url = mode === 'filled' ? app.dataset.previewUrl : `${app.dataset.pageUrl}?page=${page}`;
    const response = await fetch(url, { credentials: 'same-origin', ...options, headers: mode === 'filled' ? { 'Content-Type': 'application/json', 'X-CSRFToken': csrf } : {} });
    if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.error || 'Preview failed.'); }
    pageUrl = URL.createObjectURL(await response.blob());
    const image = $('calibration-page');
    await new Promise((resolve, reject) => { image.onload = resolve; image.onerror = reject; image.src = pageUrl; });
    applyZoom(); renderOverlays(); status(dirty ? 'Unsaved calibration changes' : `Revision ${revision}`);
  }
  function applyZoom() {
    const image = $('calibration-page'), size = pageSize(); if (!size || !image.naturalWidth) return;
    image.style.width = `${image.naturalWidth * zoom}px`;
    $('calibration-canvas').style.width = image.style.width;
    $('calibration-canvas').style.height = `${image.naturalHeight * zoom}px`;
    $('cal-page-label').textContent = `Page ${page} of ${pageSizes.length}`;
    $('cal-zoom-label').textContent = `${Math.round(zoom * 100)}%`;
    $('cal-prev').disabled = page <= 1; $('cal-next').disabled = page >= pageSizes.length;
  }
  function renderOverlays() {
    const layer = $('calibration-overlays'), image = $('calibration-page'), size = pageSize();
    layer.replaceChildren(); if (!size || !image.clientWidth) return;
    const scale = image.clientWidth / size.width;
    Object.entries(fields()).forEach(([key, spec]) => {
      if (Number(spec.page_number || 1) !== page) return;
      const box = boxFor(spec), unit = unitsScale(spec);
      const element = document.createElement('div'); element.className = `calibration-box${key === selectedKey ? ' selected' : ''}`; element.dataset.key = key;
      element.style.left = `${Number(box.x) * unit * scale}px`; element.style.top = `${(size.height - (Number(box.y) + Number(box.height)) * unit) * scale}px`;
      element.style.width = `${Number(box.width) * unit * scale}px`; element.style.height = `${Number(box.height) * unit * scale}px`;
      element.innerHTML = `<span>${escapeHtml(spec.context_key || key)}</span><i aria-label="Resize"></i>`;
      element.addEventListener('pointerdown', beginPointerEdit); element.addEventListener('click', () => select(key)); layer.appendChild(element);
    });
    layer.onpointerdown = beginDraw;
  }
  function beginDraw(event) {
    if (!drawing || event.target !== event.currentTarget) return;
    event.preventDefault(); const layer = event.currentTarget, rect = layer.getBoundingClientRect(), size = pageSize(), scale = $('calibration-page').clientWidth / size.width;
    const startX = event.clientX - rect.left, startY = event.clientY - rect.top;
    const moveHandler = move => {
      const left = Math.min(startX, move.clientX - rect.left), top = Math.min(startY, move.clientY - rect.top);
      const width = Math.max(3, Math.abs(move.clientX - rect.left - startX)), height = Math.max(3, Math.abs(move.clientY - rect.top - startY));
      const spec = fields()[selectedKey]; if (!spec) return; spec.units = 'pt'; spec.page_number = page;
      setBox(spec, { x: left / scale, y: size.height - (top + height) / scale, width: width / scale, height: height / scale });
      markDirty(); inspect(); renderOverlays();
    };
    const upHandler = () => { drawing = false; $('calibration-overlays').style.cursor = ''; $('calibration-draw').classList.remove('selected'); window.removeEventListener('pointermove', moveHandler); };
    window.addEventListener('pointermove', moveHandler); window.addEventListener('pointerup', upHandler, { once: true });
  }
  function beginPointerEdit(event) {
    event.preventDefault(); const element = event.currentTarget, key = element.dataset.key; select(key);
    const spec = fields()[key], start = { x: event.clientX, y: event.clientY, box: copy(boxFor(spec)) }, resizing = event.target.tagName === 'I';
    const moveHandler = move => {
      const size = pageSize(), scale = $('calibration-page').clientWidth / size.width, unit = unitsScale(spec);
      const dx = (move.clientX - start.x) / scale / unit, dy = (move.clientY - start.y) / scale / unit;
      const next = copy(start.box);
      if (resizing) { next.width = Math.max(1, start.box.width + dx); next.height = Math.max(1, start.box.height - dy); }
      else { next.x = Math.max(0, start.box.x + dx); next.y = Math.max(0, start.box.y - dy); }
      setBox(spec, next); markDirty(); inspect(); renderOverlays();
    };
    const upHandler = () => { window.removeEventListener('pointermove', moveHandler); };
    window.addEventListener('pointermove', moveHandler); window.addEventListener('pointerup', upHandler, { once: true });
  }
  function setBox(spec, box) { spec.box = copy(box); spec.allowed_area = copy(box); }
  function select(key) { selectedKey = key; renderFieldList(); inspect(); }
  function inspect() {
    const spec = fields()[selectedKey], panel = $('calibration-inspector'); panel.hidden = !spec; if (!spec) return;
    const box = boxFor(spec); $('cal-context').value = spec.context_key || ''; $('cal-x').value = box.x; $('cal-y').value = box.y; $('cal-width').value = box.width; $('cal-height').value = box.height;
    $('cal-font-size').value = spec.font_size || 8; $('cal-min-font-size').value = spec.min_font_size || 5; $('cal-render-as').value = spec.render_as || 'text'; $('cal-checked-when').value = spec.checked_when ?? '';
    const padding = typeof spec.padding === 'object' ? spec.padding : { x: spec.padding || 0, y: spec.padding || 0 }; $('cal-padding-x').value = padding.x || 0; $('cal-padding-y').value = padding.y || 0; $('cal-text-case').value = spec.text_case || 'none';
    $('cal-align').value = spec.align || 'left'; $('cal-vertical').value = spec.vertical_align || 'bottom'; $('cal-fit').value = spec.fit || 'shrink'; $('cal-checked-wrap').hidden = $('cal-render-as').value !== 'checkbox';
  }
  function markDirty() { dirty = true; status('Unsaved calibration changes'); if (mode === 'filled') { window.clearTimeout(previewTimer); previewTimer = window.setTimeout(() => renderPage().catch(error => status(error.message, true)), 500); } }
  function updateSelected() {
    const spec = fields()[selectedKey]; if (!spec) return; const next = { x: Number($('cal-x').value), y: Number($('cal-y').value), width: Number($('cal-width').value), height: Number($('cal-height').value) };
    setBox(spec, next); spec.context_key = $('cal-context').value; spec.font_size = Number($('cal-font-size').value); spec.min_font_size = Number($('cal-min-font-size').value); spec.render_as = $('cal-render-as').value;
    spec.padding = { x: Number($('cal-padding-x').value), y: Number($('cal-padding-y').value) }; spec.text_case = $('cal-text-case').value;
    spec.checked_when = $('cal-checked-when').value; spec.align = $('cal-align').value; spec.vertical_align = $('cal-vertical').value; spec.fit = $('cal-fit').value; markDirty(); renderFieldList(); inspect();
  }
  ['cal-context','cal-x','cal-y','cal-width','cal-height','cal-font-size','cal-min-font-size','cal-padding-x','cal-padding-y','cal-text-case','cal-render-as','cal-checked-when','cal-align','cal-vertical','cal-fit'].forEach(id => $(id).addEventListener('change', updateSelected));
  $('calibration-fields').onchange = event => select(event.target.value); $('calibration-search').oninput = renderFieldList;
  $('calibration-add').onclick = () => { const context = contextKeys.find(item => !Object.values(fields()).some(spec => spec.context_key === item.key))?.key || contextKeys[0]?.key || 'field'; let key = context, index = 2; while (fields()[key]) key = `${context}_${index++}`; fields()[key] = { context_key: context, units: 'pt', page_number: page, box: { x: 40, y: 40, width: 120, height: 14 }, allowed_area: { x: 40, y: 40, width: 120, height: 14 }, font_size: 8, min_font_size: 5, vertical_align: 'bottom', fit: 'shrink', padding: { x: 0, y: 0 } }; selectedKey = key; markDirty(); renderFieldList(); inspect(); };
  $('calibration-draw').onclick = () => { if (!selectedKey) $('calibration-add').click(); drawing = true; $('calibration-overlays').style.cursor = 'crosshair'; $('calibration-draw').classList.add('selected'); status('Drag on the document to draw the selected field area.'); };
  $('calibration-duplicate').onclick = () => { if (!selectedKey) return; const source = fields()[selectedKey]; let key = `${selectedKey}_copy`, i = 2; while (fields()[key]) key = `${selectedKey}_copy_${i++}`; fields()[key] = copy(source); fields()[key].box.x += 8; fields()[key].allowed_area = copy(fields()[key].box); selectedKey = key; markDirty(); renderFieldList(); inspect(); };
  $('calibration-delete').onclick = () => { if (!selectedKey || !confirm(`Delete ${selectedKey}?`)) return; delete fields()[selectedKey]; selectedKey = Object.keys(fields())[0] || ''; markDirty(); renderFieldList(); inspect(); };
  $('cal-prev').onclick = async () => { if (page > 1) { page--; await renderPage(); } }; $('cal-next').onclick = async () => { if (page < pageSizes.length) { page++; await renderPage(); } };
  $('cal-zoom-out').onclick = () => { zoom = Math.max(.5, zoom - .25); applyZoom(); renderOverlays(); }; $('cal-zoom-in').onclick = () => { zoom = Math.min(3, zoom + .25); applyZoom(); renderOverlays(); };
  $('cal-source').onclick = async () => { mode = 'source'; $('cal-source').classList.add('selected'); $('cal-filled').classList.remove('selected'); await renderPage(); };
  $('cal-filled').onclick = async () => { mode = 'filled'; $('cal-filled').classList.add('selected'); $('cal-source').classList.remove('selected'); await renderPage(); };
  $('cal-regenerate').onclick = async () => { try { await renderPage(); } catch (error) { status(error.message, true); } };
  $('calibration-save').onclick = async () => { try { status('Saving…'); const data = await jsonRequest(app.dataset.saveUrl, { method: 'POST', body: JSON.stringify({ revision, configuration }) }); revision = data.revision; dirty = false; status(`Draft revision ${revision} saved`); } catch (error) { status(error.message, true); } };
  $('calibration-publish').onclick = async () => { try { if (dirty) throw new Error('Save the draft before publishing.'); status('Publishing…'); const data = await jsonRequest(app.dataset.publishUrl, { method: 'POST', body: JSON.stringify({ revision }) }); revision = data.revision; status(`Published revision ${revision}`); } catch (error) { status(error.message, true); } };
  window.addEventListener('keydown', event => { if (!selectedKey || !['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key) || /INPUT|SELECT|TEXTAREA/.test(event.target.tagName)) return; event.preventDefault(); const spec = fields()[selectedKey], box = copy(boxFor(spec)), step = event.shiftKey ? 10 : 2; if (event.key === 'ArrowLeft') box.x -= step; if (event.key === 'ArrowRight') box.x += step; if (event.key === 'ArrowUp') box.y += step; if (event.key === 'ArrowDown') box.y -= step; box.x = Math.max(0, box.x); box.y = Math.max(0, box.y); setBox(spec, box); markDirty(); inspect(); renderOverlays(); });
  window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } if (pageUrl) URL.revokeObjectURL(pageUrl); });
  load();
})();
