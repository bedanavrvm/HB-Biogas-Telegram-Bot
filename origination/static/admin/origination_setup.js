(() => {
  'use strict';
  document.querySelectorAll('[data-osw-submit]').forEach(form => {
    form.addEventListener('submit', event => {
      if (!form.checkValidity()) return;
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
})();
