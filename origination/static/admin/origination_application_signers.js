(() => {
  const form = document.querySelector('[data-signer-autosave]');
  if (!form || form.querySelector('fieldset').disabled) return;
  const status = form.querySelector('[data-save-status]');
  const saveButton = form.querySelector('[type=submit]');
  saveButton.hidden = true;
  let pending = false, running = false, timer = null, retryBody = null;
  let generation = 0, retryGeneration = 0;
  function inlineErrors(errors = {}) {
    form.querySelectorAll('[data-signer-error]').forEach(node => {
      const input = form.elements.namedItem(node.dataset.signerError);
      if (input?.getAttribute('aria-describedby') === node.id) input.removeAttribute('aria-describedby');
      node.remove();
    });
    form.querySelectorAll('[aria-invalid]').forEach(node => node.removeAttribute('aria-invalid'));
    for (const [name, items] of Object.entries(errors)) {
      const input = form.elements.namedItem(name);
      if (!input || input.type === 'hidden') continue;
      input.setAttribute('aria-invalid', 'true');
      const error = document.createElement('small');
      error.dataset.signerError = name;
      error.id = `${input.id}-error`;
      error.textContent = items.map(item => item.message).join(' ');
      input.setAttribute('aria-describedby', error.id);
      input.insertAdjacentElement('afterend', error);
    }
  }
  async function save() {
    pending = true;
    if (running) return;
    running = true;
    while (pending) {
      pending = false;
      const body = retryBody || new FormData(form);
      const bodyGeneration = retryBody ? retryGeneration : generation;
      if (!retryBody) body.set('request_id', crypto.randomUUID());
      status.textContent = 'Saving…';
      try {
        const response = await fetch(form.action || location.href, {method: 'POST', body,
          headers: {'X-Requested-With': 'XMLHttpRequest'}, credentials: 'same-origin'});
        const data = await response.json();
        if (!response.ok || !data.ok) {
          inlineErrors(data.errors);
          status.textContent = data.error || 'Not saved. Try again.';
          saveButton.hidden = false;
          retryBody = null;
          pending = false;
          break;
        }
        form.elements.revision.value = data.revision;
        form.elements.plan_revision.value = data.plan_revision;
        retryBody = null;
        inlineErrors();
        status.textContent = 'Saved';
        saveButton.hidden = true;
        pending = pending || generation > bodyGeneration;
      } catch (_) {
        retryBody = body;
        retryGeneration = bodyGeneration;
        status.textContent = 'Not confirmed. Use Save signers to retry.';
        saveButton.hidden = false;
        pending = false;
      }
    }
    running = false;
  }
  const changed = () => {
    generation += 1;
    clearTimeout(timer);
    timer = setTimeout(save, 350);
  };
  form.addEventListener('change', changed);
  window.django?.jQuery?.(form).on('change', '.admin-autocomplete', changed);
  form.addEventListener('submit', event => {event.preventDefault();clearTimeout(timer);save();});
})();
