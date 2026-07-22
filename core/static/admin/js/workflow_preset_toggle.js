/**
 * Shows only the settings section matching the selected workflow preset.
 *
 * Supports both legacy collapsed fieldsets and Unfold tab fieldsets.
 */
(function () {
  'use strict';

  const PRESET_SECTIONS = {
    case: 'preset-case',
    order_approval: 'preset-order_approval',
    jawabu_homebiogas: 'preset-jawabu_homebiogas',
    spin_credit_analysis: 'preset-spin_credit_analysis',
    tat_tracker: 'preset-tat_tracker',
  };

  function applyToggle(selectedPreset) {
    const sections = document.querySelectorAll('.module.preset-section');
    const visibleTabLinks = [];

    sections.forEach(function (section) {
      const isMatch = section.classList.contains(
        PRESET_SECTIONS[selectedPreset] || '__none__'
      );
      const tabWrapper = section.closest('.tab-wrapper');
      const target = tabWrapper || section;
      const tabLink = findTabLink(tabWrapper);

      if (isMatch) {
        target.style.display = '';
        if (tabLink) {
          tabLink.style.display = '';
          visibleTabLinks.push(tabLink);
        }
        expandLegacyCollapse(section);
      } else {
        target.style.display = 'none';
        if (tabLink) {
          tabLink.style.display = 'none';
        }
      }
    });

    if (visibleTabLinks.length) {
      visibleTabLinks[0].querySelector('a')?.click();
    }
  }

  function expandLegacyCollapse(section) {
    const toggle = section.querySelector('.collapse-toggle');
    const content = section.querySelector('.collapse');
    if (toggle && content && content.style.display === 'none') {
      toggle.click();
    }
  }

  function findTabLink(tabWrapper) {
    if (!tabWrapper || !tabWrapper.parentElement) return null;

    const wrappers = Array.from(
      tabWrapper.parentElement.querySelectorAll(':scope > .tab-wrapper')
    );
    const index = wrappers.indexOf(tabWrapper);
    if (index < 0) return null;

    const tabList = tabWrapper.parentElement.querySelector(':scope > ul');
    return tabList ? tabList.children[index] : null;
  }

  function init() {
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
