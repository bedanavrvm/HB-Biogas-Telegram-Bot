(function () {
  'use strict';

  const groupTypes = {
    jawabu_portal: new Set(['jawabu', 'jawabu_homebiogas']),
    complaint_cases: new Set(['case']),
    tat_tracker: new Set(['tat_tracker']),
  };

  function field(row, suffix) {
    return row.querySelector(`[name="${suffix}"], [name$="-${suffix}"]`);
  }

  function filterOptions(select, predicate) {
    if (!select) return;
    let selectedAllowed = true;
    Array.from(select.options).forEach(function (option) {
      const allowed = predicate(option);
      option.hidden = !allowed;
      option.disabled = !allowed;
      if (option.selected && !allowed) selectedAllowed = false;
    });
    if (!selectedAllowed) select.value = '';
  }

  function updateRow(row) {
    const workflowSelect = field(row, 'workflow');
    if (!workflowSelect) return;
    const workflow = workflowSelect.value;
    ['role', 'branch', 'product'].forEach(function (name) {
      filterOptions(field(row, name), function (option) {
        const workflows = (option.dataset.workflows || '').split(',').filter(Boolean);
        return !option.value || workflows.includes(workflow);
      });
    });
    filterOptions(field(row, 'group_configuration'), function (option) {
      if (!option.value) return true;
      return (groupTypes[workflow] || new Set([''])).has(option.dataset.workflowType || '');
    });
  }

  function updateAll() {
    document.querySelectorAll('.inline-related').forEach(updateRow);
  }

  function updateLoginFields() {
    const root = document.getElementById('staff-user-creation');
    if (!root) return;
    const method = field(root, 'login_method');
    if (!method) return;
    const telegram = method.value === 'telegram';
    ['telegram_username'].forEach(function (name) {
      const wrapper = root.querySelector(`[data-staff-field="${name}"]`);
      if (wrapper) wrapper.hidden = !telegram;
    });
    ['django_username', 'email', 'password'].forEach(function (name) {
      const wrapper = root.querySelector(`[data-staff-field="${name}"]`);
      if (wrapper) wrapper.hidden = telegram;
    });
  }

  document.addEventListener('change', function (event) {
    if (event.target.matches('[name="login_method"]')) updateLoginFields();
    if (!event.target.matches('[name="workflow"], [name$="-workflow"]')) return;
    const row = event.target.closest('.inline-related, #enroll-telegram-user');
    if (row) updateRow(row);
  });
  document.addEventListener('formset:added', function (event) {
    updateRow(event.target);
  });
  document.addEventListener('DOMContentLoaded', updateAll);
  document.addEventListener('DOMContentLoaded', updateLoginFields);
  document.addEventListener('DOMContentLoaded', function () {
    const enrollment = document.getElementById('enroll-telegram-user');
    if (enrollment) updateRow(enrollment);
  });
})();
