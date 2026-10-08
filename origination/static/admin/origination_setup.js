(() => {
  'use strict';
  document.querySelectorAll('[data-osw-submit]').forEach(form => {
    form.addEventListener('submit', event => {
      if (!event.submitter?.formNoValidate && !form.checkValidity()) return;
      if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
        event.preventDefault();
        return;
      }
      const button = event.submitter || form.querySelector('button[type="submit"]');
      if (!button || button.dataset.busy === 'true') {
        if (button) event.preventDefault();
        return;
      }
      button.dataset.busy = 'true';
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
    section.querySelector('[data-preview-load]').addEventListener('click', async event => {
      const button = event.currentTarget;
      const status = section.querySelector('[data-preview-status]');
      button.disabled = true;
      status.textContent = 'Loading sample…';
      try {
        const response = await fetch(section.dataset.url, {
          method: 'POST', credentials: 'same-origin',
          headers: {'Content-Type': 'application/json',
            'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value},
          body: JSON.stringify({configuration: JSON.parse(section.querySelector('script[type="application/json"]').textContent), page: 1}),
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
        status.textContent = 'Synthetic sample · page 1';
      } catch (error) { status.textContent = error.message; }
      finally { button.disabled = false; }
    });
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
