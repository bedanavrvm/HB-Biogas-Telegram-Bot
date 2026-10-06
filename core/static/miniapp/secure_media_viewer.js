(function () {
  'use strict';
  const active = new WeakMap();
  const owners = new Map();

  function showPages(container, pages, settings) {
    container.replaceChildren();
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
    let index = 0, scale = 1, panX = 0, panY = 0;
    const pointers = new Map();
    let start = null, pinch = null, multiTouch = false;
    function transform() {img.style.transform = `translate(${panX}px, ${panY}px) scale(${scale})`; stage.dataset.zoom = String(scale);}
    function zoom(value) {scale = Math.max(1, Math.min(5, value)); if (scale === 1) panX = panY = 0; transform();}
    function navigate(offset) {
      if (index + offset >= 0 && index + offset < pages.length) { index += offset; render(); }
      else if (offset > 0) settings.onNext?.(); else settings.onPrevious?.();
    }
    const previous = button('Previous page', '‹', () => navigate(-1));
    const count = document.createElement('span'); count.setAttribute('role', 'status'); controls.appendChild(count);
    const next = button('Next page', '›', () => navigate(1));
    button('Zoom out', '−', () => zoom(scale - .5));
    button('Zoom in', '+', () => zoom(scale + .5));
    button('Reset zoom', '↺', () => zoom(1));
    function render() {
      scale = 1; panX = panY = 0; transform();
      img.src = pages[index].src; img.alt = pages[index].alt || settings.name || 'Evidence preview';
      count.textContent = `${index + 1} / ${pages.length}`;
      previous.disabled = index === 0 && !settings.onPrevious;
      next.disabled = index === pages.length - 1 && !settings.onNext;
      previous.hidden = next.hidden = pages.length === 1 && !settings.onNext && !settings.onPrevious;
      count.hidden = pages.length === 1;
    }
    stage.addEventListener('pointerdown', event => {
      pointers.set(event.pointerId, {x:event.clientX,y:event.clientY});
      try { stage.setPointerCapture?.(event.pointerId); } catch (_) { /* Synthetic/legacy pointer events have no capture target. */ }
      if (pointers.size === 1) {start = {x:event.clientX,y:event.clientY,panX,panY}; multiTouch = false;}
      if (pointers.size === 2) {
        const [a,b] = [...pointers.values()];
        pinch = {distance:Math.hypot(a.x-b.x,a.y-b.y),scale}; multiTouch = true;
      }
    });
    stage.addEventListener('pointermove', event => {
      if (!pointers.has(event.pointerId)) return;
      pointers.set(event.pointerId,{x:event.clientX,y:event.clientY});
      if (pointers.size === 2 && pinch?.distance) {
        const [a,b] = [...pointers.values()]; zoom(pinch.scale * Math.hypot(a.x-b.x,a.y-b.y) / pinch.distance);
      } else if (scale > 1 && start && !multiTouch) {
        panX = start.panX + event.clientX-start.x; panY = start.panY + event.clientY-start.y; transform();
      }
    });
    function release(event) {
      pointers.delete(event.pointerId);
      if (!pointers.size) {
        if (event.type !== 'pointercancel' && start && !multiTouch && scale === 1
            && Math.abs(event.clientX-start.x) > 60 && Math.abs(event.clientY-start.y) < 40) navigate(event.clientX < start.x ? 1 : -1);
        start = pinch = null;
      }
    }
    stage.addEventListener('pointerup', release); stage.addEventListener('pointercancel', release);
    stage.addEventListener('keydown', event => {
      if (event.key === 'ArrowRight') navigate(1); else if (event.key === 'ArrowLeft') navigate(-1);
      else if (event.key === '+') zoom(scale+.5); else if (event.key === '-') zoom(scale-.5); else return;
      event.preventDefault(); event.stopPropagation();
    });
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
      if (owner && active.get(owner) === objectUrl) active.delete(owner);
      owners.delete(objectUrl);
      URL.revokeObjectURL(objectUrl);
    }
  }

  window.SecureMediaViewer = { fetchAuthorizedBlob, renderBlob, revoke };
}());
