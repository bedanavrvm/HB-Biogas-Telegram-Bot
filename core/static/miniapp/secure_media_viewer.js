(function () {
  'use strict';
  const active = new WeakMap();
  const owners = new Map();
  const gestures = new WeakMap();

  function bindImageGestures(stage, img, options = {}) {
    gestures.get(stage)?.dispose();
    let scale = 1, panX = 0, panY = 0, fittedWidth = 0, fittedHeight = 0;
    let start = null, pinch = null, multiTouch = false;
    const pointers = new Map(), listeners = [];
    const originalStage = stage.getAttribute('style'), originalImage = img.getAttribute('style');
    Object.assign(stage.style, {position:'relative', overflow:'hidden', touchAction:'none', minWidth:'0'});
    Object.assign(img.style, {position:'absolute', left:'50%', top:'50%', maxWidth:'none', maxHeight:'none',
      margin:'0', objectFit:'contain', transformOrigin:'center', userSelect:'none', touchAction:'none'});
    img.draggable = false;
    function transform() {
      const rect = stage.getBoundingClientRect();
      const limitX = Math.max(0, (fittedWidth * scale - rect.width) / 2);
      const limitY = Math.max(0, (fittedHeight * scale - rect.height) / 2);
      panX = Math.max(-limitX, Math.min(limitX, panX)); panY = Math.max(-limitY, Math.min(limitY, panY));
      img.style.transform = `translate(-50%, -50%) translate(${panX}px, ${panY}px) scale(${scale})`;
      stage.dataset.zoom = String(scale);
      options.onZoom?.(scale);
    }
    function fit() {
      const rect = stage.getBoundingClientRect();
      const ratio = Math.min(rect.width / (img.naturalWidth || 1), rect.height / (img.naturalHeight || 1));
      fittedWidth = (img.naturalWidth || 1) * ratio; fittedHeight = (img.naturalHeight || 1) * ratio;
      img.style.width = `${fittedWidth}px`; img.style.height = `${fittedHeight}px`; transform();
    }
    function zoom(value, focal) {
      const next = Math.max(1, Math.min(5, value));
      if (focal) {
        const rect = stage.getBoundingClientRect(), x = focal.x - rect.left - rect.width / 2, y = focal.y - rect.top - rect.height / 2;
        panX = x - (x - panX) * next / scale; panY = y - (y - panY) * next / scale;
      }
      scale = next; if (scale === 1) panX = panY = 0; transform();
    }
    function on(target, name, handler) { target.addEventListener(name, handler); listeners.push(() => target.removeEventListener(name, handler)); }
    on(stage, 'pointerdown', event => {
      pointers.set(event.pointerId, {x:event.clientX, y:event.clientY});
      try { stage.setPointerCapture?.(event.pointerId); } catch (_) {}
      if (pointers.size === 1) { start = {x:event.clientX,y:event.clientY,panX,panY}; multiTouch = false; }
      if (pointers.size === 2) {
        const [a,b] = [...pointers.values()], rect = stage.getBoundingClientRect();
        pinch = {distance:Math.hypot(a.x-b.x,a.y-b.y), scale,
          x:((a.x+b.x)/2-rect.left-rect.width/2-panX)/scale,
          y:((a.y+b.y)/2-rect.top-rect.height/2-panY)/scale}; multiTouch = true;
      }
    });
    on(stage, 'pointermove', event => {
      if (!pointers.has(event.pointerId)) return;
      pointers.set(event.pointerId, {x:event.clientX,y:event.clientY});
      if (pointers.size === 2 && pinch?.distance) {
        const [a,b] = [...pointers.values()], rect = stage.getBoundingClientRect();
        scale = Math.max(1, Math.min(5, pinch.scale*Math.hypot(a.x-b.x,a.y-b.y)/pinch.distance));
        panX = (a.x+b.x)/2-rect.left-rect.width/2-pinch.x*scale;
        panY = (a.y+b.y)/2-rect.top-rect.height/2-pinch.y*scale; transform();
      } else if (scale > 1 && start && !multiTouch) {
        panX = start.panX+event.clientX-start.x; panY = start.panY+event.clientY-start.y; transform();
      }
    });
    function release(event) {
      if (!pointers.has(event.pointerId)) return;
      pointers.delete(event.pointerId);
      if (!pointers.size) {
        if (event.type === 'pointerup' && start && !multiTouch && scale === 1
            && Math.abs(event.clientX-start.x)>60 && Math.abs(event.clientY-start.y)<40) options.onNavigate?.(event.clientX<start.x ? 1 : -1);
        start = pinch = null;
      }
    }
    ['pointerup','pointercancel','lostpointercapture'].forEach(name => on(stage, name, release));
    on(stage, 'keydown', event => {
      if (event.key === '+' || event.key === '=') zoom(scale+.5);
      else if (event.key === '-') zoom(scale-.5);
      else if (event.key === '0') zoom(1);
      else if (['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)) {
        if (scale === 1) { if (event.key === 'ArrowRight') options.onNavigate?.(1); else if (event.key === 'ArrowLeft') options.onNavigate?.(-1); }
        else { panX += event.key === 'ArrowLeft' ? 60 : event.key === 'ArrowRight' ? -60 : 0; panY += event.key === 'ArrowUp' ? 60 : event.key === 'ArrowDown' ? -60 : 0; transform(); }
      } else return;
      event.preventDefault(); event.stopPropagation();
    });
    on(img, 'load', fit);
    const observer = new ResizeObserver(fit); observer.observe(stage); fit();
    const controller = {zoom, reset:() => zoom(1), get scale() { return scale; }, dispose() {
      listeners.forEach(remove => remove()); observer.disconnect(); pointers.clear();
      if (originalStage === null) stage.removeAttribute('style'); else stage.setAttribute('style', originalStage);
      if (originalImage === null) img.removeAttribute('style'); else img.setAttribute('style', originalImage);
      gestures.delete(stage);
      delete stage.dataset.zoom;
    }};
    gestures.set(stage, controller); return controller;
  }

  function showPages(container, pages, settings) {
    container.querySelectorAll('.secure-media-stage').forEach(stage => gestures.get(stage)?.dispose());
    container.replaceChildren();
    container.classList.add('secure-media-pages');
    const stage = document.createElement('div');
    stage.className = 'secure-media-stage';
    stage.tabIndex = 0;
    stage.setAttribute('aria-label', 'Document preview. Pinch to zoom; swipe to navigate.');
    const img = document.createElement('img');
    img.className = settings.imageClass || 'media-viewer-image';
    img.draggable = false;
    stage.appendChild(img);
    const controls = document.createElement('div');
    controls.className = 'secure-media-controls';
    function button(label, symbol, handler) {
      const node = document.createElement('button');
      node.type = 'button'; node.className = 'miniapp-icon-button';
      node.setAttribute('aria-label', label); node.title = label; node.textContent = symbol;
      node.addEventListener('click', handler); controls.appendChild(node); return node;
    }
    let index = 0;
    const controller = bindImageGestures(stage, img, {onNavigate:navigate});
    function navigate(offset) {
      if (index + offset >= 0 && index + offset < pages.length) { index += offset; render(); }
      else if (offset > 0) settings.onNext?.(); else settings.onPrevious?.();
    }
    const previous = button('Previous page', '‹', () => navigate(-1));
    const count = document.createElement('span'); count.setAttribute('role', 'status'); controls.appendChild(count);
    const next = button('Next page', '›', () => navigate(1));
    button('Zoom out', '−', () => controller.zoom(controller.scale - .5));
    button('Zoom in', '+', () => controller.zoom(controller.scale + .5));
    button('Reset zoom', '↺', () => controller.reset());
    function render() {
      controller.reset();
      img.src = pages[index].src; img.alt = pages[index].alt || settings.name || 'Evidence preview';
      count.textContent = `${index + 1} / ${pages.length}`;
      previous.disabled = index === 0 && !settings.onPrevious;
      next.disabled = index === pages.length - 1 && !settings.onNext;
      previous.hidden = next.hidden = pages.length === 1 && !settings.onNext && !settings.onPrevious;
      count.hidden = pages.length === 1;
    }
    container.append(stage,controls); render();
  }

  async function fetchAuthorizedBlob(url, options) {
    const settings = options || {};
    const response = await fetch(url, {
      method: settings.method || 'GET',
      headers: { ...(settings.headers || {}) },
      body: settings.body,
      cache: 'no-store',
      signal: settings.signal,
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || payload.message || 'The evidence could not be opened.');
    }
    const blob = await response.blob();
    if (!blob.size) throw new Error('The evidence file was empty.');
    return blob;
  }

  function renderBlob(container, blob, options) {
    const settings = options || {};
    revoke(active.get(container));
    const objectUrl = URL.createObjectURL(blob);
    const mimeType = String(blob.type || settings.mimeType || '').toLowerCase();
    container.replaceChildren();
    container.classList.remove('secure-media-pages');
    active.set(container, objectUrl);
    owners.set(objectUrl, container);
    if (settings.gestures === false) {
      // Existing clients with their own gesture controller retain their DOM
      // contract; never attach two pinch/swipe controllers to the same image.
      const node = document.createElement(mimeType.startsWith('image/') ? 'img' : 'iframe');
      node.className = mimeType.startsWith('image/') ? (settings.imageClass || 'media-viewer-image') : (settings.documentClass || 'media-viewer-document');
      node.src = objectUrl;
      if (node.tagName === 'IMG') node.alt = settings.name || 'Evidence preview';
      else {node.title = settings.name || 'Evidence preview'; node.setAttribute('sandbox', '');}
      container.appendChild(node);
    } else if (mimeType.startsWith('image/')) {
      showPages(container, [{src:objectUrl, alt:settings.name}], settings);
    } else if (mimeType.startsWith('text/html')) {
      // Parse only bounded server-rendered image data; never execute response HTML.
      blob.text().then(html => {
        if (active.get(container) !== objectUrl) return;
        const parsed = new DOMParser().parseFromString(html, 'text/html');
        const pages = [...parsed.querySelectorAll('figure img')].filter(img => /^data:image\/(jpeg|png);base64,/i.test(img.getAttribute('src') || '')).map(img => ({src:img.getAttribute('src'),alt:img.alt}));
        if (!pages.length) throw new Error('No preview pages were available.');
        showPages(container, pages, settings);
        const notice = parsed.querySelector('.notice');
        if (notice) {const text = document.createElement('p'); text.className = 'media-viewer-loading'; text.textContent = notice.textContent; container.appendChild(text);}
      }).catch(() => {if (active.get(container) === objectUrl) container.textContent = 'This preview could not be opened. Close it and retry.';});
    } else {
      const frame = document.createElement('iframe');
      frame.className = settings.documentClass || 'media-viewer-document';
      frame.src = objectUrl;
      frame.title = settings.name || 'Evidence preview';
      frame.setAttribute('sandbox', '');
      container.appendChild(frame);
    }
    return objectUrl;
  }

  function revoke(objectUrl) {
    if (objectUrl) {
      const owner = owners.get(objectUrl);
      owner?.querySelectorAll('.secure-media-stage').forEach(stage => gestures.get(stage)?.dispose());
      if (owner && active.get(owner) === objectUrl) active.delete(owner);
      owners.delete(objectUrl);
      URL.revokeObjectURL(objectUrl);
    }
  }

  window.SecureMediaViewer = { fetchAuthorizedBlob, renderBlob, revoke, bindImageGestures };
}());
