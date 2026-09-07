(function () {
  'use strict';

  function setExpanded(role, expanded) {
    const detail = document.getElementById(`tat-role-${role}`);
    if (!detail) return;
    detail.hidden = !expanded;
    document.querySelectorAll(`[data-tat-expand-role="${CSS.escape(role)}"]`).forEach((button) => {
      button.setAttribute('aria-expanded', String(expanded));
      if (button.classList.contains('tat-row-toggle')) {
        button.textContent = expanded ? 'Hide details' : 'View details';
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    const workspace = document.querySelector('[data-tat-workspace]');
    if (!workspace) return;
    workspace.querySelectorAll('[data-tat-expand-role]').forEach((button) => {
      button.addEventListener('click', function () {
        const detail = document.getElementById(`tat-role-${button.dataset.tatExpandRole}`);
        setExpanded(button.dataset.tatExpandRole, Boolean(detail?.hidden));
      });
    });
    workspace.querySelectorAll('.tat-role-detail').forEach((detail) => {
      detail.querySelectorAll('[data-tat-tab]').forEach((button) => {
        button.addEventListener('click', function () {
          const tab = button.dataset.tatTab;
          detail.querySelectorAll('[data-tat-tab]').forEach((item) => {
            const active = item === button;
            item.classList.toggle('is-active', active);
            item.setAttribute('aria-selected', String(active));
          });
          detail.querySelectorAll('[data-tat-panel]').forEach((panel) => {
            panel.hidden = panel.dataset.tatPanel !== tab;
          });
        });
      });
    });
    const scopeForm = workspace.querySelector('[data-tat-scope-form]');
    if (scopeForm && workspace.dataset.scopeExplicit !== 'true') {
      let restored = false;
      scopeForm.querySelectorAll('select[data-tat-persist]').forEach((select) => {
        try {
          const saved = window.localStorage.getItem(`tat-responsibility-scope:${select.dataset.tatPersist}`);
          if (saved !== null && [...select.options].some((option) => option.value === saved)) {
            select.value = saved;
            restored = true;
          }
        } catch (_error) {}
      });
      if (restored) {
        scopeForm.submit();
        return;
      }
    }
    scopeForm?.querySelectorAll('select').forEach((select) => {
      select.addEventListener('change', function () {
        try {
          window.localStorage.setItem(`tat-responsibility-scope:${select.dataset.tatPersist}`, select.value);
        } catch (_error) {}
        scopeForm.submit();
      });
    });
  });
})();
