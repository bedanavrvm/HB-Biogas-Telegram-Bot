/**
 * workflow_preset_toggle.js
 *
 * Shows only the settings fieldset that matches the currently selected
 * workflow preset dropdown value, hiding all others.
 *
 * Relies on Django's fieldset <h2> title matching the CSS classes
 * preset-<preset_key> that are added in admin.py fieldsets.
 */
(function () {
  'use strict';

  /** Map preset value → CSS class suffix applied to the fieldset module. */
  const PRESET_SECTIONS = {
    order_approval: 'preset-order_approval',
    jawabu_homebiogas: 'preset-jawabu_homebiogas',
  };

  function applyToggle(selectedPreset) {
    // All fieldsets carrying a preset-section class.
    const sections = document.querySelectorAll('.module.preset-section');
    sections.forEach(function (section) {
      const isMatch = section.classList.contains(
        PRESET_SECTIONS[selectedPreset] || '__none__'
      );
      if (isMatch) {
        // Show and auto-expand.
        section.style.display = '';
        const toggle = section.querySelector('.collapse-toggle');
        const content = section.querySelector('.collapse');
        if (toggle && content && content.style.display === 'none') {
          toggle.click();
        }
      } else {
        // Hide entirely — no need to pollute form with irrelevant fields.
        section.style.display = 'none';
      }
    });
  }

  function init() {
    // Django renders the select as id_workflow_preset.
    const select = document.getElementById('id_workflow_preset');
    if (!select) return;

    applyToggle(select.value);

    select.addEventListener('change', function () {
      applyToggle(this.value);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
