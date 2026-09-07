(function () {
  'use strict';

  function fieldValue(id) { return document.getElementById(id)?.value || ''; }

  async function refreshImpact(root) {
    const state = root.querySelector('[data-tat-impact-state]');
    const results = root.querySelector('[data-tat-impact-results]');
    const editor = document.querySelector('[data-tat-editor]');
    const required = ['id_group_configuration', 'id_branch', 'id_role', 'id_primary_user'];
    if (required.some((id) => !fieldValue(id))) {
      state.textContent = 'Choose the workflow group, branch, role, and primary recipient to review impact.';
      results.hidden = true;
      return;
    }
    const url = new URL(editor.dataset.impactUrl, window.location.href);
    url.search = new URLSearchParams({
      group_configuration: fieldValue('id_group_configuration'),
      branch: fieldValue('id_branch'), role: fieldValue('id_role'),
      product_key: fieldValue('id_product_key'), stage_key: fieldValue('id_stage_key'),
      primary_user: fieldValue('id_primary_user'), assignment_id: editor.dataset.assignmentId || '',
    }).toString();
    state.textContent = 'Checking effective impact…';
    try {
      const response = await fetch(url, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || 'Impact could not be checked.');
      root.querySelector('[data-tat-impact-change]').textContent = payload.change_summary;
      root.querySelector('[data-tat-impact-stages]').textContent = payload.stages.length ? payload.stages.join(', ') : 'No governed stages match';
      root.querySelector('[data-tat-impact-access]').textContent = payload.primary_has_access ? 'Valid for this scope' : 'Missing matching access';
      root.querySelector('[data-tat-impact-dm]').textContent = payload.primary_dm_status;
      root.querySelector('[data-tat-impact-tasks]').textContent = `${payload.open_tasks} open task${payload.open_tasks === 1 ? '' : 's'}`;
      state.textContent = 'This is the current server-checked impact. Refresh after changing access in another window.';
      results.hidden = false;
    } catch (error) {
      state.textContent = `${error.message} Reload before saving if this continues.`;
      results.hidden = true;
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    const impact = document.querySelector('[data-tat-impact]');
    if (!impact) return;
    impact.querySelector('[data-tat-refresh-impact]')?.addEventListener('click', () => refreshImpact(impact));
    ['id_group_configuration', 'id_branch', 'id_role', 'id_product_key', 'id_stage_key', 'id_primary_user'].forEach((id) => {
      document.getElementById(id)?.addEventListener('change', () => refreshImpact(impact));
    });
    document.querySelector('form')?.addEventListener('submit', function () {
      document.querySelectorAll('input[type="submit"],button[type="submit"]').forEach((button) => { button.disabled = true; });
    });
    refreshImpact(impact);
  });
})();
