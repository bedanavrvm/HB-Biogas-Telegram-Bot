/* Shared acknowledgement for external signers and authenticated staff. */
(function () {
  'use strict';
  function outcome(application, fallback = '') {
    const status = application.application_status || application.status;
    if (status === 'approved') return 'Application approved.';
    if (['signed_pending_approval', 'fully_signed'].includes(status)) return 'Awaiting final approval.';
    return application.signing_policy === 'all_required' || application.signing_workspace
      ? 'Awaiting other signatures or stamps.' : (fallback || 'Awaiting final approval.');
  }
  function show(container, { reference, signedAt, message, onClose, external = false }) {
    const section = document.createElement('section');
    section.className = 'signing-completion';
    section.innerHTML = '<span class="signing-completion-icon" aria-hidden="true">✓</span><h2 tabindex="-1">Signature saved</h2><p data-completion-message></p><p class="signing-completion-reference"></p><p class="signing-completion-time"></p><p data-countdown aria-live="off"></p><div class="signing-completion-actions"><button type="button" class="btn btn-primary" data-completion-close></button><button type="button" class="btn btn-secondary" data-completion-stay>Stay here</button></div>';
    section.querySelector('[data-completion-message]').textContent = message;
    section.querySelector('.signing-completion-reference').textContent = reference || '';
    const timestamp = signedAt && new Date(signedAt);
    section.querySelector('.signing-completion-time').textContent = timestamp && !Number.isNaN(timestamp.getTime())
      ? 'Signed ' + new Intl.DateTimeFormat('en-KE', { timeZone: 'Africa/Nairobi', dateStyle: 'medium', timeStyle: 'short' }).format(timestamp) + ' EAT' : '';
    const close = section.querySelector('[data-completion-close]');
    close.textContent = external ? 'Close now' : 'Back to application';
    const countdown = section.querySelector('[data-countdown]');
    let timer, seconds = 10, disposed = false;
    const deadline = Date.now() + 10000;
    const stop = () => { window.clearInterval(timer); timer = null; };
    const exit = () => {
      stop();
      if (onClose) { onClose(); return; }
      const tg = window.Telegram?.WebApp;
      try {
        if (tg?.initData && typeof tg.close === 'function') tg.close();
        else if (window.opener) window.close();
      } catch (_) { /* A browser may refuse closure; the saved acknowledgement remains visible. */ }
      countdown.textContent = 'You can close this tab.';
      section.querySelector('[data-completion-stay]').hidden = true;
    };
    const update = () => { countdown.textContent = external ? `Closing in ${seconds} seconds.` : `Returning to the application in ${seconds} seconds.`; };
    close.onclick = exit;
    section.querySelector('[data-completion-stay]').onclick = () => { stop(); countdown.textContent = 'Your signature is saved. Close when you are ready.'; section.querySelector('[data-completion-stay]').hidden = true; };
    container.replaceChildren(section);
    section.setAttribute('role', 'status');
    update();
    section.querySelector('h2').focus();
    window.MiniAppUtils?.haptic?.('success');
    timer = window.setInterval(() => { if (!section.isConnected || disposed) return stop(); seconds = Math.max(0, Math.ceil((deadline - Date.now()) / 1000)); if (seconds <= 0) exit(); else update(); }, 1000);
    return { dispose() { disposed = true; stop(); } };
  }
  window.OriginationSigningCompletion = { show, outcome };
})();
