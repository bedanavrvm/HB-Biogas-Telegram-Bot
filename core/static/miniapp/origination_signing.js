(() => {
  'use strict';

  window.MiniAppUtils?.initTelegram?.();

  const fragmentToken = decodeURIComponent(location.hash.slice(1));
  let storedToken = '';
  try { storedToken = window.sessionStorage.getItem('jbl-origination-signing-token') || ''; } catch (_) { /* restricted WebView */ }
  const token = fragmentToken || storedToken;
  if (fragmentToken) {
    try { window.sessionStorage.setItem('jbl-origination-signing-token', fragmentToken); } catch (_) { /* restricted WebView */ }
  }

  const shell = document.querySelector('.sign-shell');
  const sessionUrl = String(shell?.dataset.sessionUrl || '/origination/sign/api/session/');
  const base = sessionUrl.replace(/session\/?$/, '').replace(/\/$/, '');
  const status = document.getElementById('sign-status');
  const content = document.getElementById('sign-content');
  const pad = document.getElementById('signature-pad');
  const ctx = pad.getContext('2d');
  let session = null;
  let page = 1;
  let pages = 1;
  let mode = 'drawn';
  let strokes = [];
  let activeStroke = null;
  let captureSaved = false;
  let reviewedPages = new Set();
  let pageObjectUrl = '';

  function syncSignatureProtection() {
    const typedName = document.getElementById('typed-name')?.value.trim() || '';
    window.MiniAppUtils?.setCloseProtection?.(
      'signing-capture',
      Boolean(!captureSaved && session?.status !== 'verified' && (strokes.length || typedName)),
    );
  }

  const id = () => window.crypto?.randomUUID ? window.crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
  const escapeHtml = value => {
    const node = document.createElement('div');
    node.textContent = String(value ?? '');
    return node.innerHTML;
  };
  const show = (message, kind = 'info') => {
    status.textContent = message;
    status.className = `notice ${kind}`;
    status.hidden = !message;
  };

  async function api(path, options = {}) {
    const requestId = id();
    const response = await fetch(`${base}/${path}`, {
      credentials: 'omit', cache: 'no-store', ...options,
      headers: {
        'Content-Type': 'application/json', 'Authorization': `Bearer ${token}`,
        'Idempotency-Key': requestId, 'X-Request-ID': requestId,
        'X-MiniApp-Message-Contract': '2', ...(options.headers || {}),
      },
    });
    const raw = await response.json().catch(() => ({}));
    const data = window.MiniAppUtils?.normalizeResponsePayload
      ? window.MiniAppUtils.normalizeResponsePayload(response, raw, 'We could not complete this signing step.') : raw;
    if (!response.ok || !data.ok) {
      const error = window.MiniAppUtils?.apiError
        ? window.MiniAppUtils.apiError(response, data)
        : new Error(data.message || 'We could not complete this signing step.');
      error.retryAfter = response.headers.get('Retry-After');
      throw error;
    }
    return data;
  }

  function render() {
    document.getElementById('sign-reference').textContent = session.reference;
    document.getElementById('sign-role').textContent = session.signer_role.replaceAll('_', ' ');
    document.getElementById('sign-phone').textContent = session.phone_masked;
    document.getElementById('shared-phone-warning').hidden = !session.shared_phone_override;
    const assisted = session.access_mode === 'assisted';
    document.getElementById('assisted-confirmation').hidden = !assisted;
    const modeBanner = document.getElementById('signing-mode-banner');
    modeBanner.classList.toggle('assisted', assisted);
    document.getElementById('signing-mode-label').textContent = assisted ? 'Assisted signing' : 'Remote signing';
    document.getElementById('signing-mode-detail').textContent = assisted
      ? 'You are signing in person on a JBL officer’s device. Keep control of the device while entering your verification code.'
      : 'You can review and sign this packet securely from your own phone, wherever you are.';
    document.getElementById('document-list').innerHTML = session.documents
      .map(item => `<span>${escapeHtml(item.name || item.key)} · ${item.page_count || 0} page(s)</span>`).join('');
    const consentText = document.getElementById('packet-consent-text');
    if (consentText && session.consent_text) consentText.textContent = session.consent_text;
    const allReviewed = pages > 0 && reviewedPages.size >= pages;
    document.getElementById('packet-consent').disabled = !allReviewed && !session.consented;
    document.getElementById('send-otp').disabled = !session.consented || session.status === 'verified';
    document.getElementById('otp-panel').hidden = !session.otp?.expires_at || session.status === 'verified';
    if (session.status === 'verified') {
      show(session.completion_text || 'Signing complete. Your verified signature has been applied to every signature box assigned to you.', 'success');
      document.querySelectorAll('button,input').forEach(element => { element.disabled = true; });
      if (location.hash) history.replaceState(null, '', location.pathname + location.search);
      try { window.sessionStorage.removeItem('jbl-origination-signing-token'); } catch (_) { /* restricted WebView */ }
    }
  }

  async function loadPage() {
    const image = document.getElementById('packet-page');
    document.getElementById('preview-loading').hidden = false;
    image.hidden = true;
    const response = await fetch(`${base}/packet/?page=${page}`, {
      credentials: 'omit', cache: 'no-store',
      headers: { 'Authorization': `Bearer ${token}`, 'X-Request-ID': id(), 'X-MiniApp-Message-Contract': '2' },
    });
    if (!response.ok) {
      const raw = await response.json().catch(() => ({}));
      const data = window.MiniAppUtils?.normalizeResponsePayload
        ? window.MiniAppUtils.normalizeResponsePayload(response, raw) : raw;
      throw new Error(data.message || 'We could not load this document page. Please try again.');
    }
    const responseVersion = response.headers.get('X-Signing-Packet-Version') || '';
    const packetChanged = Boolean(session?.packet_version && responseVersion && session.packet_version !== responseVersion);
    if (responseVersion) session.packet_version = responseVersion;
    pages = Number(response.headers.get('X-Preview-Page-Count') || 1);
    reviewedPages.add(page);
    if (pageObjectUrl) URL.revokeObjectURL(pageObjectUrl);
    pageObjectUrl = URL.createObjectURL(await response.blob());
    image.src = pageObjectUrl;
    image.hidden = false;
    document.getElementById('preview-loading').hidden = true;
    document.getElementById('page-label').textContent = `${page} / ${pages}`;
    document.getElementById('page-prev').disabled = page <= 1;
    document.getElementById('page-next').disabled = page >= pages;
    document.getElementById('packet-consent').disabled = reviewedPages.size < pages && !session.consented;
    if (packetChanged) {
      show('The packet now includes a preceding verified signature. Your saved consent and verification step are unchanged.', 'info');
    }
  }

  function point(event) {
    const box = pad.getBoundingClientRect();
    return [
      Math.max(0, Math.min(1, (event.clientX - box.left) / box.width)),
      Math.max(0, Math.min(1, (event.clientY - box.top) / box.height)),
    ];
  }
  function redraw() {
    ctx.clearRect(0, 0, pad.width, pad.height);
    ctx.strokeStyle = '#123d77'; ctx.lineWidth = 4; ctx.lineCap = 'round';
    for (const stroke of strokes) {
      if (stroke.length < 2) continue;
      ctx.beginPath(); ctx.moveTo(stroke[0][0] * pad.width, stroke[0][1] * pad.height);
      stroke.slice(1).forEach(position => ctx.lineTo(position[0] * pad.width, position[1] * pad.height));
      ctx.stroke();
    }
  }
  pad.addEventListener('pointerdown', event => { pad.setPointerCapture(event.pointerId); activeStroke = [point(event)]; strokes.push(activeStroke); captureSaved = false; syncSignatureProtection(); });
  pad.addEventListener('pointermove', event => { if (!activeStroke) return; activeStroke.push(point(event)); redraw(); });
  ['pointerup', 'pointercancel'].forEach(name => pad.addEventListener(name, () => { activeStroke = null; }));
  document.getElementById('signature-clear').onclick = () => { strokes = []; redraw(); syncSignatureProtection(); };
  document.getElementById('typed-name').addEventListener('input', () => { captureSaved = false; syncSignatureProtection(); });
  function setMode(next) {
    mode = next;
    document.getElementById('mode-drawn').classList.toggle('active', next === 'drawn');
    document.getElementById('mode-typed').classList.toggle('active', next === 'typed');
    document.getElementById('draw-panel').hidden = next !== 'drawn';
    document.getElementById('type-panel').hidden = next !== 'typed';
  }
  document.getElementById('mode-drawn').onclick = () => setMode('drawn');
  document.getElementById('mode-typed').onclick = () => setMode('typed');
  document.getElementById('page-prev').onclick = async () => { if (page > 1) { page -= 1; await loadPage(); } };
  document.getElementById('page-next').onclick = async () => { if (page < pages) { page += 1; await loadPage(); } };

  document.getElementById('save-signature').onclick = async event => {
    const button = event.currentTarget;
    try {
      await window.MiniAppUtils.runButtonAction(button, async () => {
        if (reviewedPages.size < pages) throw new Error('Review every page of the loan documents before continuing.');
        const capture = mode === 'typed'
          ? { method: 'typed', name: document.getElementById('typed-name').value.trim() }
          : { method: 'drawn', strokes };
        const consent = document.getElementById('packet-consent').checked
          && (session.access_mode !== 'assisted' || document.getElementById('assisted-consent').checked);
        const data = await api('consent/', {
          method: 'POST',
          body: JSON.stringify({ signature_capture: capture, consent, access_mode: session.access_mode, reviewed_pages: [...reviewedPages].sort((a, b) => a - b) }),
        });
        session = data.session;
        captureSaved = true;
        window.MiniAppUtils?.setCloseProtection?.('signing-capture', false);
      }, { loadingLabel: 'Saving signature', successLabel: 'Signature saved' });
      render();
      syncSignatureProtection();
      show('Your signature is ready. Tap “Send verification code” to continue.', 'success');
    } catch (error) { show(error.message, error.presentation?.tone || 'error'); }
  };

  document.getElementById('send-otp').onclick = async event => {
    const button = event.currentTarget;
    try {
      await window.MiniAppUtils.runButtonAction(button, async () => {
        const data = await api('otp/', { method: 'POST', body: '{}' });
        session = data.session;
      }, { loadingLabel: 'Sending code', successLabel: 'Code sent' });
      render();
      show(`Your six-digit verification code is being sent to ${session.phone_masked}.`, 'success');
      document.getElementById('otp-code').focus();
    } catch (error) { show(error.message, error.presentation?.tone || 'error'); }
  };

  document.getElementById('verify-otp').onclick = async event => {
    const button = event.currentTarget;
    try {
      await window.MiniAppUtils.runButtonAction(button, async () => {
        const data = await api('verify/', {
          method: 'POST', body: JSON.stringify({ code: document.getElementById('otp-code').value.trim() }),
        });
        session = data.session;
      }, { loadingLabel: 'Verifying', successLabel: 'Verified' });
      render();
    } catch (error) { show(error.message, error.presentation?.tone || 'error'); }
  };

  async function refreshSession() {
    if (!session || document.visibilityState === 'hidden' || session.status === 'verified') return;
    try {
      const before = session.packet_version || '';
      const data = await api('session/', { headers: {} });
      session = data.session;
      render();
      if (before && session.packet_version && before !== session.packet_version) await loadPage();
    } catch (_) { /* Existing signer state remains usable during a transient refresh failure. */ }
  }
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') void refreshSession(); });
  window.addEventListener('pagehide', () => { if (pageObjectUrl) URL.revokeObjectURL(pageObjectUrl); });

  (async () => {
    try {
      const data = await api('session/', { headers: {} });
      session = data.session;
      reviewedPages = new Set((session.reviewed_pages || []).map(Number));
      content.hidden = false;
      render();
      show('Review every page before signing.', 'info');
      await loadPage();
    } catch (error) { show(error.message, error.presentation?.tone || 'error'); }
  })();
})();
