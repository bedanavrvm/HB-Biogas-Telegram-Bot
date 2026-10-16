(function () {
  'use strict';
  const scene = window.UI_SCENE;
  const actions = {
    tat: {form:'[data-view="new"]',filters:'#openQueueFiltersBtn',reports:'#dashboardWorkspaceBtn',recognition:'#recognitionWorkspaceBtn',settings:'#settingsTab'},
    complaints:{form:'#newCaseBtn',filters:'#openComplaintQueueFilters',reports:'#globalWorkspaceBtn',settings:'#complaintSettingsBtn'},
    origination:{form:'#origination-start',filters:'[aria-label="Filters"]',settings:'#origination-settings-open'},
    portal:{form:'.farmer-card',filters:'[data-portal-filter-trigger]'},
  };
  window.addEventListener('error',event=>scene.gaps.push('JavaScript: '+event.message));
  window.setTimeout(() => {
    const target = actions[scene.config.app]?.[scene.config.scene];
    const button = target && document.querySelector(target);
    if (button && button.getClientRects().length) button.click();
    else if (scene.config.scene!=='queue' && !(scene.config.app==='portal' && ['reports','settings','recognition'].includes(scene.config.scene))) scene.gaps.push('Requested scene could not be opened automatically.');
    scene.ready = true;
  }, 700);
  window.addEventListener('message',event=>{if(event.source===window.parent && event.data?.type==='ui-lab-expect')scene.expected=event.data.selector;});
  // The host receives only observations, never Telegram identity or app data.
  window.setInterval(() => {
    const expected=scene.expected?[...document.querySelectorAll(scene.expected)]:[];
    const observations = {type:'ui-scene-observation',config:scene.config,calls:scene.calls.slice(-40),gaps:[...new Set(scene.gaps)],
      component:scene.expected?{selector:scene.expected,matched:expected.length,visible:expected.filter(node=>node.getClientRects().length).length}:null,
      ready:scene.ready,fontFamilies:[...new Set([...document.querySelectorAll('h1,h2,label,input')].slice(0,30).map(node=>getComputedStyle(node).fontFamily))]};
    window.parent.postMessage(observations,'*');
  },1500);
})();
