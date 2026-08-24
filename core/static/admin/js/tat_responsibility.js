(function () {
  'use strict';

  let eligibleUsers = [];
  let eligibilityRequest = 0;

  function announceEligibility(message, isError) {
    const help = document.getElementById('tat-eligible-users-help');
    if (!help) return;
    help.textContent = message;
    help.classList.toggle('text-red-600', Boolean(isError));
    help.classList.toggle('dark:text-red-400', Boolean(isError));
  }

  function updateSelect(select, users) {
    const selected = select.value || select.dataset.initialUserId || '';
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = users.length ? 'Select eligible user' : 'No eligible users';
    select.replaceChildren(placeholder);
    users.forEach((user) => {
      const option = document.createElement('option');
      option.value = String(user.id);
      option.textContent = user.label;
      select.appendChild(option);
    });
    const selectedIsEligible = users.some((user) => String(user.id) === selected);
    if (selectedIsEligible) {
      select.value = selected;
    } else if (select.id === 'id_primary_user' && users.length === 1) {
      // With only one legally eligible primary there is no useful choice to
      // make. Selecting it also prevents Unfold's wrapper from looking blank.
      select.value = String(users[0].id);
    } else {
      select.value = '';
    }
    // Unfold can emit transient scope changes while its widgets initialize.
    // Keep a persisted inline value through an interim empty response and only
    // discard it once a non-empty authoritative option set has been received.
    if (selectedIsEligible || users.length) delete select.dataset.initialUserId;
    select.dispatchEvent(new Event('change', { bubbles: true }));
    if (window.django && window.django.jQuery) {
      window.django.jQuery(select).trigger('change');
    }
  }

  function updateUserSelects(users) {
    eligibleUsers = users;
    const primary = document.getElementById('id_primary_user');
    if (primary) updateSelect(primary, users);
    updateBackupUserSelects();
  }

  function updateBackupUserSelects() {
    const primaryId = document.getElementById('id_primary_user')?.value || '';
    const backupUsers = eligibleUsers.filter((user) => String(user.id) !== primaryId);
    document.querySelectorAll('select[id^="id_backups-"][id$="-user"]').forEach(
      (select) => updateSelect(select, backupUsers),
    );
  }

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

  async function refreshEligibleUsers() {
    const primary = document.getElementById('id_primary_user');
    const group = document.getElementById('id_group_configuration');
    const branch = document.getElementById('id_branch');
    const role = document.getElementById('id_role');
    const product = document.getElementById('id_product_key');
    if (!primary || !group || !branch || !role || !product) return;

    const missing = [
      ['workflow group', group.value],
      ['branch', branch.value],
      ['role', role.value],
    ].filter((item) => !item[1]).map((item) => item[0]);
    if (missing.length) {
      updateUserSelects([]);
      announceEligibility(`Choose ${missing.join(', ')} to load eligible users.`, false);
      return;
    }

    const requestNumber = ++eligibilityRequest;
    announceEligibility('Loading eligible users…', false);
    const url = new URL(primary.dataset.eligibleUsersUrl, window.location.href);
    url.search = new URLSearchParams({
      group_configuration: group.value,
      branch: branch.value,
      role: role.value,
      product_key: product.value,
    }).toString();
    try {
      const response = await fetch(url.toString(), {
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
      });
      const payload = await response.json();
      if (requestNumber !== eligibilityRequest) return;
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || 'Eligible users could not be loaded.');
      }
      updateUserSelects(Array.isArray(payload.users) ? payload.users : []);
      announceEligibility(payload.message || 'Eligible users updated.', false);
    } catch (error) {
      if (requestNumber !== eligibilityRequest) return;
      announceEligibility(`${error.message} Reload this page before saving.`, true);
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    const stage = document.getElementById('id_stage_key');
    const scopeFields = [
      document.getElementById('id_group_configuration'),
      document.getElementById('id_branch'),
      document.getElementById('id_role'),
      document.getElementById('id_product_key'),
    ].filter(Boolean);
    const primary = document.getElementById('id_primary_user');
    if (stage) {
      stage.addEventListener('change', function () {
        syncStageRole();
        refreshEligibleUsers();
      });
    }
    scopeFields.forEach((field) => field.addEventListener('change', refreshEligibleUsers));
    if (primary) primary.addEventListener('change', updateBackupUserSelects);
    syncStageRole();
    refreshEligibleUsers();

    const inlineRoot = document.querySelector('.inline-group');
    if (inlineRoot) {
      new MutationObserver((mutations) => {
        const addedUserSelect = mutations.some((mutation) => [...mutation.addedNodes].some((node) => (
          node.nodeType === Node.ELEMENT_NODE
          && (node.matches?.('select[id^="id_backups-"][id$="-user"]')
            || node.querySelector?.('select[id^="id_backups-"][id$="-user"]'))
        )));
        if (addedUserSelect) {
          updateBackupUserSelects();
        }
      }).observe(inlineRoot, { childList: true, subtree: true });
    }
  });
})();
