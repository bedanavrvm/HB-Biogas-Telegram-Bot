(() => {
  'use strict';
  let leavingAfterSave = false;
  let unsaved = false;
  document.querySelectorAll('form[data-osw-submit]').forEach(form => {
    form.addEventListener('input', () => { unsaved = true; });
    form.addEventListener('change', () => { unsaved = true; });
  });
  window.addEventListener('beforeunload', event => {
    if (!unsaved || leavingAfterSave) return;
    event.preventDefault(); event.returnValue = '';
  });
  const confirmation = document.getElementById('osw-confirm');
  let pendingConfirmation = null;
  if (confirmation) {
    document.querySelectorAll('form[data-confirm]').forEach(form => {
      form.addEventListener('submit', event => {
        if (form.dataset.confirmed === 'true') return;
        event.preventDefault(); event.stopImmediatePropagation();
        pendingConfirmation = {form, button: event.submitter};
        confirmation.querySelector('[data-confirm-message]').textContent = form.dataset.confirm;
        confirmation.showModal();
      }, true);
    });
    confirmation.querySelector('[data-confirm-cancel]').onclick = () => confirmation.close();
    confirmation.querySelector('[data-confirm-accept]').onclick = () => {
      const pending = pendingConfirmation;
      confirmation.close(); pending.form.dataset.confirmed = 'true';
      pending.form.requestSubmit(pending.button);
    };
  }
  document.querySelectorAll('[data-osw-submit]').forEach(form => {
    form.addEventListener('submit', event => {
      if (!event.submitter?.formNoValidate && !form.checkValidity()) return;
      if (!confirmation && form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
        event.preventDefault();
        return;
      }
      const button = event.submitter || form.querySelector('button[type="submit"]');
      if (!button || button.dataset.busy === 'true') {
        if (button) event.preventDefault();
        return;
      }
      button.dataset.busy = 'true';
      leavingAfterSave = true;
      button.setAttribute('aria-busy', 'true');
      button.classList.add('is-busy');
      window.setTimeout(() => { button.disabled = true; }, 0);
    });
  });
  document.querySelectorAll('[data-osw-formset]').forEach(section => {
    const prefix = section.dataset.prefix;
    const total = section.querySelector(`#id_${prefix}-TOTAL_FORMS`);
    const template = section.querySelector('[data-empty-form]');
    const rows = section.querySelector('[data-formset-rows]');
    section.querySelector('[data-add-row]')?.addEventListener('click', () => {
      const index = Number(total.value || 0);
      rows.insertAdjacentHTML('beforeend', template.innerHTML.replaceAll('__prefix__', String(index)));
      total.value = String(index + 1);
      rows.lastElementChild?.querySelector('input:not([type="hidden"]),select,textarea')?.focus();
    });
  });
  document.querySelectorAll('[data-osw-preview]').forEach(section => {
    let previewUrl = '';
    let previewPage = 1;
    const pageCount = Number(section.dataset.pages || 1);
    const previous = section.querySelector('[data-preview-previous]');
    const next = section.querySelector('[data-preview-next]');
    let loading = false;
    const loadPreview = async event => {
      if (loading) return;
      loading = true;
      const button = event.currentTarget;
      const status = section.querySelector('[data-preview-status]');
      button.disabled = true;
      if (previous) previous.disabled = true;
      if (next) next.disabled = true;
      status.textContent = 'Loading sample…';
      try {
        const response = await fetch(section.dataset.url, {
          method: 'POST', credentials: 'same-origin',
          headers: {'Content-Type': 'application/json',
            'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value},
          body: JSON.stringify({configuration: JSON.parse(section.querySelector('script[type="application/json"]').textContent), page: previewPage}),
        });
        if (!response.ok) {
          const result = await response.json().catch(() => ({}));
          throw new Error(result.error || 'Sample could not be loaded. Try again.');
        }
        if (previewUrl) URL.revokeObjectURL(previewUrl);
        previewUrl = URL.createObjectURL(await response.blob());
        const image = section.querySelector('[data-preview-image]');
        image.src = previewUrl;
        image.hidden = false;
        status.textContent = `Sample · page ${previewPage} of ${pageCount}`;
      } catch (error) { status.textContent = error.message; }
      finally {
        loading = false;
        button.disabled = false;
        if (previous) previous.disabled = previewPage === 1;
        if (next) next.disabled = previewPage === pageCount;
      }
    };
    section.querySelector('[data-preview-load]').addEventListener('click', loadPreview);
    if (previous) previous.onclick = event => { previewPage = Math.max(1, previewPage - 1); loadPreview(event); };
    if (next) next.onclick = event => { previewPage = Math.min(pageCount, previewPage + 1); loadPreview(event); };
  });
  ['id_templates', 'id_branches'].forEach(id => {
    const list = document.getElementById(id);
    if (!list || list.children.length < 6) return;
    const search = document.createElement('input');
    search.type = 'search';
    search.className = 'osw-choice-search';
    search.placeholder = id === 'id_branches' ? 'Find a branch' : 'Find a document';
    search.setAttribute('aria-label', search.placeholder);
    list.before(search);
    search.addEventListener('input', () => {
      const query = search.value.trim().toLocaleLowerCase();
      [...list.children].forEach(row => { row.hidden = !row.textContent.toLocaleLowerCase().includes(query); });
    });
  });
})();
