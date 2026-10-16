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
  const sessionUrl = String(shell?.dataset.sessionUrl || '/api/origination/sign/api/session/');
  const base = sessionUrl.replace(/session\/?$/, '').replace(/\/$/, '');
  const status = document.getElementById('sign-status');
  const content = document.getElementById('sign-content');
  const signatureForm = window.MiniAppUtils?.bindAccessibleForm?.(document.getElementById('signature-card'), {
    resolveField: key => key === 'signature-pad' ? document.getElementById(key) : null,
    validate: () => mode === 'drawn' && !strokes.some(stroke => stroke.length >= 2) ? {'signature-pad': 'Draw your signature, or choose Type to enter your name.'} : {},
    validators: {
    'typed-name': value => mode === 'typed' && !String(value).trim() ? 'Enter your full legal name.' : '',
    'packet-consent': (value, input) => input.checked ? '' : 'Confirm that you reviewed and agree to sign the documents.',
    'assisted-consent': (value, input) => session?.access_mode !== 'assisted' || input.checked ? '' : 'Confirm that you are personally signing on this device.',
  }});
  const verificationForm = window.MiniAppUtils?.bindAccessibleForm?.(document.getElementById('otp-panel'), {validators: {
    'otp-code': value => /^\d{6}$/.test(String(value).trim()) ? '' : 'Enter the six-digit verification code.',
  }});
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
  let completion = null;
  let pageLoading = false;
  const pageGestures = window.SecureMediaViewer?.bindImageGestures(
    document.querySelector('.packet-preview'), document.getElementById('packet-page'), {
      navigateAtEdges: true,
      onNavigate: direction => { if (page + direction >= 1 && page + direction <= pages) void navigatePage(page + direction); },
      onZoom: scale => { document.getElementById('page-zoom').textContent = `${Math.round(scale * 100)}%`; },
    });
  const pendingRequests = new Map();

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
    const toast = document.getElementById('sign-toast');
    if (toast && message) {
      toast.textContent = message;
      toast.className = `sign-toast ${kind}`;
      toast.setAttribute('role', kind === 'error' ? 'alert' : 'status');
      toast.hidden = false;
      window.clearTimeout(show.timer);
      show.timer = window.setTimeout(() => { toast.hidden = true; }, kind === 'error' ? 7000 : 4500);
      window.MiniAppUtils?.haptic?.(kind);
    }
  };

  async function api(path, options = {}) {
    const isWrite = options.method === 'POST';
    const key = path + ':' + (options.body || '');
    const requestId = isWrite ? pendingRequests.get(key) || id() : id();
    if (isWrite) pendingRequests.set(key, requestId);
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 20000);
    let response, raw;
    try {
      response = await fetch(`${base}/${path}`, {
      credentials: 'omit', cache: 'no-store', ...options,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json', 'Authorization': `Bearer ${token}`,
        'Idempotency-Key': requestId, 'X-Request-ID': requestId,
        'X-MiniApp-Message-Contract': '2', ...(options.headers || {}),
      },
      });
      raw = await response.json();
    } catch (_) {
      const error = new Error('We could not confirm the save. Check your connection and try again.');
      error.uncertain = true;
      throw error;
    } finally { window.clearTimeout(timeout); }
    if (isWrite && response.status < 500) pendingRequests.delete(key);
    const data = window.MiniAppUtils?.normalizeResponsePayload
      ? window.MiniAppUtils.normalizeResponsePayload(response, raw, 'We could not complete this signing step.') : raw;
    if (!response.ok || !data.ok) {
      const error = window.MiniAppUtils?.apiError
        ? window.MiniAppUtils.apiError(response, data)
        : new Error(data.message || 'We could not complete this signing step.');
      error.retryAfter = response.headers.get('Retry-After');
      error.uncertain = response.status >= 500;
      throw error;
    }
    return data;
  }

  function render() {
    if (session.status === 'verified') {
      content.hidden = true;
      status.hidden = true;
      document.querySelector('.sign-brand h1').textContent = 'Signing complete';
      const host = document.getElementById('sign-completion');
      host.hidden = false;
      if (!completion) completion = window.OriginationSigningCompletion.show(host, {
        reference: session.reference, signedAt: session.verified_at,
        message: window.OriginationSigningCompletion.outcome(session, session.completion_text), external: true,
      });
      window.MiniAppUtils?.setCloseProtection?.('signing-capture', false);
      if (location.hash) history.replaceState(null, '', location.pathname + location.search);
      try { window.sessionStorage.removeItem('jbl-origination-signing-token'); } catch (_) { /* restricted WebView */ }
      return;
    }
    document.getElementById('sign-reference').textContent = session.reference;
    document.getElementById('sign-name').textContent = session.signer_name || '';
    document.getElementById('sign-role').textContent = session.signer_role.replaceAll('_', ' ');
    document.getElementById('sign-phone').textContent = session.phone_masked;
    document.getElementById('shared-phone-warning').hidden = !session.shared_phone_override;
    const assisted = session.access_mode === 'assisted';
    document.getElementById('assisted-confirmation').hidden = !assisted;
    const modeBanner = document.getElementById('signing-mode-banner');
    modeBanner.hidden = !assisted;
    modeBanner.classList.toggle('assisted', assisted);
    document.getElementById('signing-mode-label').textContent = assisted ? 'Assisted signing' : 'Remote signing';
    document.getElementById('signing-mode-detail').textContent = assisted
      ? 'You are signing in person on a JBL officer’s device. Keep control of the device while entering your verification code.'
      : 'Review and sign the documents on your phone.';
    document.getElementById('document-list').innerHTML = session.documents
      .map(item => `<span>${escapeHtml(item.name || item.key)} · ${item.page_count || 0} page(s)</span>`).join('');
    const consentText = document.getElementById('packet-consent-text');
    if (consentText && session.consent_text) consentText.textContent = session.consent_text;
    const allReviewed = pages > 0 && reviewedPages.size >= pages;
    const signatureCard = document.getElementById('signature-card');
    const verificationCard = document.getElementById('verification-card');
    const reviewCard = document.getElementById('review-card');
    if (signatureCard) signatureCard.hidden = !allReviewed || Boolean(session.consented);
    if (verificationCard) verificationCard.hidden = !session.consented || session.status === 'verified';
    if (reviewCard) reviewCard.open = !session.consented;
    document.getElementById('packet-consent').disabled = !allReviewed && !session.consented;
    document.getElementById('send-otp').disabled = !session.consented || session.status === 'verified';
    document.getElementById('otp-panel').hidden = !session.otp?.expires_at || session.status === 'verified';
    const resendAt = Date.parse(session.otp?.resend_available_at || '');
    document.getElementById('send-otp').disabled = !session.consented || (Number.isFinite(resendAt) && resendAt > Date.now());
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
    render();
    if (packetChanged) {
      show('Another signature was saved. Your signing progress is unchanged.', 'info');
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
  ['pointerup', 'pointercancel'].forEach(name => pad.addEventListener(name, () => { activeStroke = null; pad.dispatchEvent(new Event('input', {bubbles:true})); }));
  document.getElementById('signature-clear').onclick = () => { strokes = []; redraw(); syncSignatureProtection(); };
  document.getElementById('typed-name').addEventListener('input', () => { captureSaved = false; syncSignatureProtection(); });
  const typedAppearance = window.OriginationSignatureAppearance.mount({
    input: document.getElementById('typed-name'), container: document.getElementById('typed-appearance'),
    request: values => api('signature-preview/', {method: 'POST', body: JSON.stringify(values)}),
    onChange: () => { captureSaved = false; syncSignatureProtection(); },
  });
  function setMode(next) {
    mode = next;
    document.getElementById('mode-drawn').classList.toggle('active', next === 'drawn');
    document.getElementById('mode-typed').classList.toggle('active', next === 'typed');
    document.getElementById('draw-panel').hidden = next !== 'drawn';
    document.getElementById('type-panel').hidden = next !== 'typed';
    pad.dispatchEvent(new Event('input', {bubbles:true}));
  }
  document.getElementById('mode-drawn').onclick = () => setMode('drawn');
  document.getElementById('mode-typed').onclick = () => setMode('typed');
  async function navigatePage(next) {
    if (pageLoading || next < 1 || next > pages) return;
    const previous = page;
    pageLoading = true;
    page = next;
    try { await loadPage(); pageGestures?.reset(); }
    catch (error) { page = previous; document.getElementById('preview-loading').hidden = true; document.getElementById('packet-page').hidden = false; show(error.message, 'error'); }
    finally { pageLoading = false; }
  }
  document.getElementById('page-prev').onclick = () => { if (page > 1) void navigatePage(page - 1); };
  document.getElementById('page-next').onclick = () => { if (page < pages) void navigatePage(page + 1); };
  document.getElementById('page-zoom-out').onclick = () => pageGestures?.zoom(pageGestures.scale - .25);
  document.getElementById('page-zoom').onclick = () => pageGestures?.reset();
  document.getElementById('page-zoom-in').onclick = () => pageGestures?.zoom(pageGestures.scale + .25);
  document.getElementById('page-refresh').onclick = () => void navigatePage(page);

  async function recoverSession(error) {
    if (!error.uncertain) return;
    try {
      const data = await api('session/');
      session = data.session;
      captureSaved = Boolean(session.consented);
    } catch (_) { /* Keep the entered signature and the same request key. */ }
  }

  document.getElementById('save-signature').onclick = async event => {
    if (signatureForm && !signatureForm.validate()) return show('Check the highlighted signing fields.', 'warning');
    const button = event.currentTarget;
    try {
      await window.MiniAppUtils.runButtonAction(button, async () => {
        if (reviewedPages.size < pages) throw new Error('Review every page of the loan documents before continuing.');
        const capture = mode === 'typed'
          ? typedAppearance.capture()
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
        const verification = await api('otp/', {method: 'POST', body: '{}'});
        session = verification.session;
      }, { loadingLabel: 'Saving and sending code', successLabel: 'Code requested' });
      render();
      syncSignatureProtection();
      show(`Signature saved. A code is being sent to ${session.phone_masked}. Enter it to finish signing.`, 'info');
      document.getElementById('otp-code').focus();
    } catch (error) {
      await recoverSession(error);
      render();
      if (session.status !== 'verified') show(captureSaved ? `Signature saved. ${error.message}` : error.message, error.presentation?.tone || 'error');
    }
  };

  document.getElementById('send-otp').onclick = async event => {
    const button = event.currentTarget;
    try {
      await window.MiniAppUtils.runButtonAction(button, async () => {
        const data = await api('otp/', { method: 'POST', body: '{}' });
        session = data.session;
      }, { loadingLabel: 'Sending code', successLabel: 'Code requested' });
      render();
      show(`Your six-digit verification code is being sent to ${session.phone_masked}.`, 'success');
      document.getElementById('otp-code').focus();
    } catch (error) { await recoverSession(error); render(); if (session.status !== 'verified') show(error.message, error.presentation?.tone || 'error'); }
  };

  document.getElementById('verify-otp').onclick = async event => {
    if (verificationForm && !verificationForm.validate()) return show('Enter the six-digit code sent to your phone.', 'warning');
    const button = event.currentTarget;
    try {
      await window.MiniAppUtils.runButtonAction(button, async () => {
        const data = await api('verify/', {
          method: 'POST', body: JSON.stringify({ code: document.getElementById('otp-code').value.trim() }),
        });
        session = data.session;
      }, { loadingLabel: 'Verifying', successLabel: 'Verified' });
      render();
    } catch (error) { await recoverSession(error); render(); if (session.status !== 'verified') show(error.message, error.presentation?.tone || 'error'); }
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
  const resendTimer = window.setInterval(() => { if (session?.consented && session.status !== 'verified') render(); }, 1000);
  window.addEventListener('pagehide', () => { window.clearInterval(resendTimer); completion?.dispose(); if (pageObjectUrl) URL.revokeObjectURL(pageObjectUrl); });

  (async () => {
    try {
      const data = await api('session/', { headers: {} });
      session = data.session;
      reviewedPages = new Set((session.reviewed_pages || []).map(Number));
      content.hidden = false;
      render();
      if (session.status === 'verified') return;
      if (session.status !== 'verified') show(session.consented
        ? session.otp?.expires_at ? 'Enter your verification code to finish signing.' : 'Your signature is saved. Send a verification code to finish signing.'
        : 'Review every page before signing.', 'info');
      await loadPage();
    } catch (error) { show(error.message, error.presentation?.tone || 'error'); }
  })();
})();
