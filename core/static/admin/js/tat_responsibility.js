(function () {
  'use strict';

  function syncStageRole() {
    const stage = document.getElementById('id_stage_key');
    const role = document.getElementById('id_role');
    if (!stage || !role) return;
    let mapping = {};
    try { mapping = JSON.parse(stage.dataset.stageRoleMap || '{}'); } catch (_error) { return; }
    const derivedRole = mapping[stage.value] || '';
    if (derivedRole) {
      role.value = derivedRole;
      role.disabled = true;
      role.setAttribute('aria-describedby', 'tat-derived-role-help');
    } else {
      role.disabled = false;
      role.removeAttribute('aria-describedby');
    }
    let help = document.getElementById('tat-derived-role-help');
    if (!help) {
      help = document.createElement('p');
      help.id = 'tat-derived-role-help';
      help.className = 'help mt-1 text-xs';
      role.insertAdjacentElement('afterend', help);
    }
    help.textContent = derivedRole
      ? `Responsible role is derived from this stage: ${derivedRole}.`
      : 'Choose the role for this default roster.';
  }

  document.addEventListener('DOMContentLoaded', function () {
    const stage = document.getElementById('id_stage_key');
    if (!stage) return;
    stage.addEventListener('change', syncStageRole);
    syncStageRole();
  });
})();
