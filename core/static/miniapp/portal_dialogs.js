(function () {
  'use strict';

  const overlays = new Map();
  const stack = [];
  const focusableSelector = [
    'a[href]', 'button:not([disabled])', 'input:not([disabled]):not([type="hidden"])',
    'select:not([disabled])', 'textarea:not([disabled])', '[tabindex]:not([tabindex="-1"])',
  ].join(',');
  const closeSelectors = {
    'sheet-overlay': '#sheet-close',
    'media-viewer-overlay': '#media-viewer-close',
    'requisition-preview-overlay': '#requisition-preview-close, #requisition-preview-cancel',
    'batch-detail-overlay': '#batch-detail-close',
    'invoice-overlay': '#invoice-overlay-close',
    'invoice-match-overlay': '#invoice-match-close',
    'invoice-detail-overlay': '#invoice-detail-close',
    'payment-preview-overlay': '#payment-preview-close, #payment-preview-done',
  };

  function focusable(overlay) {
    return Array.from(overlay.querySelectorAll(focusableSelector)).filter(node => {
      return !node.hidden && node.getAttribute('aria-hidden') !== 'true' && node.getClientRects().length > 0;
    });
  }

  function topOverlay() {
    return stack.length ? stack[stack.length - 1] : null;
  }

  function syncBody() {
    document.body.classList.toggle('portal-overlay-open', stack.length > 0);
  }

  function opened(overlay) {
    const existingIndex = stack.indexOf(overlay);
    if (existingIndex >= 0) stack.splice(existingIndex, 1);
    const record = overlays.get(overlay) || {};
    record.returnFocus = document.activeElement && !overlay.contains(document.activeElement)
      ? document.activeElement : record.returnFocus;
    overlays.set(overlay, record);
    stack.push(overlay);
    overlay.setAttribute('aria-hidden', 'false');
    syncBody();
    window.setTimeout(function () {
      if (topOverlay() !== overlay) return;
      const target = overlay.querySelector(closeSelectors[overlay.id] || '') || focusable(overlay)[0]
        || overlay.querySelector('.sheet-panel');
      if (target && !target.hasAttribute('tabindex') && target.matches('.sheet-panel')) target.tabIndex = -1;
      target?.focus?.({ preventScroll: true });
    }, 20);
  }

  function closed(overlay) {
    const index = stack.indexOf(overlay);
    if (index >= 0) stack.splice(index, 1);
    overlay.setAttribute('aria-hidden', 'true');
    window.MiniAppUtils?.setCloseProtection?.(`portal-dialog:${overlay.id}`, false);
    syncBody();
    const next = topOverlay();
    if (next) {
      focusable(next)[0]?.focus?.({ preventScroll: true });
      return;
    }
    const returnFocus = overlays.get(overlay)?.returnFocus;
    if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true });
  }

  function observeOverlay(overlay) {
    if (overlays.has(overlay)) return;
    overlays.set(overlay, { returnFocus: null, open: overlay.classList.contains('open') });
    overlay.setAttribute('aria-hidden', overlay.classList.contains('open') ? 'false' : 'true');
    new MutationObserver(function () {
      const record = overlays.get(overlay);
      const isOpen = overlay.classList.contains('open');
      if (record.open === isOpen) return;
      record.open = isOpen;
      if (isOpen) opened(overlay);
      else closed(overlay);
    }).observe(overlay, { attributes: true, attributeFilter: ['class'] });
    if (overlay.classList.contains('open')) opened(overlay);
  }

  document.querySelectorAll('.sheet-overlay[role="dialog"]').forEach(observeOverlay);

  document.addEventListener('input', function (event) {
    const overlay = event.target.closest('.sheet-overlay.open');
    if (overlay) window.MiniAppUtils?.setCloseProtection?.(`portal-dialog:${overlay.id}`, true);
  });
  document.addEventListener('change', function (event) {
    const overlay = event.target.closest('.sheet-overlay.open');
    if (overlay) window.MiniAppUtils?.setCloseProtection?.(`portal-dialog:${overlay.id}`, true);
  });

  document.addEventListener('keydown', function (event) {
    const overlay = topOverlay();
    if (!overlay) return;
    if (event.key === 'Escape') {
      const close = overlay.querySelector(closeSelectors[overlay.id] || '');
      if (close) {
        event.preventDefault();
        close.click();
      }
      return;
    }
    if (event.key !== 'Tab') return;
    const items = focusable(overlay);
    if (!items.length) {
      event.preventDefault();
      overlay.querySelector('.sheet-panel')?.focus?.();
      return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });

  window.PortalDialogs = { topOverlay };
})();
