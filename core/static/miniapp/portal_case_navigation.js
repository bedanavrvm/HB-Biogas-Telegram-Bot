// One read-only case detour. Retained DOM/search/forms never enter storage.
(() => {
  'use strict';
  let deps;
  let context = null;
  let loading = false;
  const marker = 'portalCaseInspection';

  function isCaseUrl(url) {
    return url.origin === location.origin && /^\/portal\/cases\/[^/]+\/$/.test(url.pathname);
  }

  function canOpen(url) {
    const destination = new URL(url, location.href);
    return isCaseUrl(destination) && Boolean(deps && !canReturn() && document.getElementById('portal-screen'));
  }

  function changed() {
    window.dispatchEvent(new Event('portal:case-route-change'));
  }

  async function open(url) {
    if (!canOpen(url) || loading) return false;
    if (!deps.hasCapability('portal.case.read')) {
      deps.showToast('Case History is not available to your role.', 'error');
      return true;
    }
    // Inspection preserves the live form, including local files; only an
    // in-flight write blocks it. Ordinary document navigation still guards
    // against discarding those edits.
    if (window.MiniAppUtils?.canNavigatePage?.(url, { preserveEdits: true }) === false) return true;
    loading = true;
    const originRoot = document.getElementById('portal-screen');
    const originPage = originRoot.dataset.screen;
    deps.rememberSelection?.(originPage, new URL(url, location.href).pathname.split('/')[3]);
    originRoot.setAttribute('aria-busy', 'true');
    deps.showToast('Opening Case History…', 'info');
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(url, {
        headers: { 'HX-Request': 'true', ...deps.headers() },
        signal: controller.signal, cache: 'no-store',
      });
      if (!response.ok) throw new Error(response.status === 403
        ? 'You no longer have access to this case.' : 'Could not open Case History. Please retry.');
      const html = await response.text();
      const parsed = new DOMParser().parseFromString(html, 'text/html');
      const root = parsed.getElementById('portal-screen');
      const caseId = new URL(url, location.href).pathname.split('/')[3];
      if (!root || root.dataset.screen !== 'case_history' || root.dataset.caseFarmerId !== caseId) {
        throw new Error('Case History could not start. Please retry.');
      }
      if (document.getElementById('portal-screen') !== originRoot) return true;
      // Never execute fragment scripts. The already-loaded history controller
      // owns the validated screen and its authorization-checked detail API.
      root.querySelectorAll('script').forEach(node => node.remove());
      const overlays = [...document.querySelectorAll('.sheet-overlay.open')];
      const originState = context?.originState || history.state;
      context = {
        originRoot, originPage, originUrl: location.href, historyRoot: root,
        historyUrl: new URL(url, location.href).href,
        scroll: document.getElementById('content')?.scrollTop || 0,
        overlays, originState, caseId,
      };
      history.replaceState({ ...history.state, [marker]: 'origin' }, '', location.href);
      history.pushState({ [marker]: 'history' }, '', context.historyUrl);
      overlays.forEach(node => node.classList.remove('open'));
      originRoot.replaceWith(root);
      document.getElementById('content')?.scrollTo(0, 0);
      root.dataset.historySource = originPage;
      const backButton = root.querySelector('.case-history-back');
      if (backButton) {
        const sourceLabels = {
          payments: 'Back to Payment Batch', requisition: 'Back to Order Preparation',
          jbl: 'Back to JBL Visit', credit: 'Back to Credit Analysis',
          final: 'Back to Head of Rural Review',
        };
        const label = sourceLabels[originPage] || 'Back';
        backButton.setAttribute('aria-label', label);
        backButton.setAttribute('title', label);
        backButton.addEventListener('click', event => { event.preventDefault(); back(); });
      }
      deps.activate('case_history');
      changed();
    } catch (error) {
      deps.showToast(error.name === 'AbortError'
        ? 'Case History took too long to open. Check your connection and retry.'
        : error.name === 'TypeError' ? 'Could not connect. Check your connection and retry.'
        : error.message || 'Could not open Case History. Please retry.', 'error');
    } finally {
      clearTimeout(timer);
      loading = false;
      originRoot.removeAttribute('aria-busy');
    }
    return true;
  }

  function canReturn() {
    return Boolean(context && document.getElementById('portal-screen') === context.historyRoot);
  }

  function back() {
    if (!canReturn()) return false;
    // Nested media previews have their own close controls and are handled by
    // the shell before this function is reached.
    history.back();
    return true;
  }

  window.addEventListener('popstate', event => {
    if (!context) return;
    if (event.state?.[marker] === 'origin' && location.href === context.originUrl) {
      const overlay = [...document.querySelectorAll('.sheet-overlay.open')].at(-1);
      if (overlay) {
        const close = overlay.querySelector('.sheet-close-button, [id$="-cancel"]');
        if (close) close.click();
        else overlay.classList.remove('open');
        history.pushState({ [marker]: 'history' }, '', context.historyUrl);
        return;
      }
      context.historyRoot.replaceWith(context.originRoot);
      const returning = context;
      const loaded = deps.activate(returning.originPage);
      context.overlays.forEach(node => node.classList.add('open'));
      Promise.resolve(loaded).then(() => requestAnimationFrame(() => {
        if (document.getElementById('portal-screen') !== returning.originRoot) return;
        document.getElementById('content')?.scrollTo(0, returning.scroll);
        const card = returning.originRoot.querySelector('[data-farmer-id="' + CSS.escape(returning.caseId) + '"]');
        if (card) {
          card.tabIndex = -1;
          card.focus({ preventScroll: true });
        } else if (!returning.overlays.length) {
          deps.showToast('This case is no longer in this queue or filter. Your other selections are unchanged.', 'info');
        }
      }));
      changed();
    } else if (event.state?.[marker] === 'history' && location.href === context.historyUrl) {
      context.overlays.forEach(node => node.classList.remove('open'));
      context.originRoot.replaceWith(context.historyRoot);
      document.getElementById('content')?.scrollTo(0, 0);
      deps.activate('case_history');
      changed();
    }
  });

  window.PortalCaseNavigation = {
    init(value) { deps = value; }, canOpen, open, canReturn, back,
    // Replace the single retained detour when the user next inspects a case.
    release() {
      if (context && !canReturn()) {
        history.replaceState(context.originState, '', location.href);
        context = null;
      }
    },
  };
})();
