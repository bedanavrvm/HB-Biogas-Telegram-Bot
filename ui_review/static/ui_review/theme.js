(function () {
  'use strict';
  const key='jbl-ui-lab-theme-v1'; let choice={theme:'telegram',mode:'auto'};
  try {const saved=JSON.parse(localStorage.getItem(key)||'{}');if(['telegram','jbl'].includes(saved.theme))choice.theme=saved.theme;if(['auto','light','dark'].includes(saved.mode))choice.mode=saved.mode;}catch(_error){}
  function apply(next) {
    if(next) choice={theme:['telegram','jbl'].includes(next.theme)?next.theme:'telegram',mode:['auto','light','dark'].includes(next.mode)?next.mode:'auto'};
    const tg=window.Telegram?.WebApp;
    const mode=choice.mode==='auto'?(tg?.colorScheme || (matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light')):choice.mode;
    document.body.dataset.uiTheme=choice.theme;document.body.dataset.uiMode=mode;document.documentElement.style.colorScheme=mode;
    if(choice.theme==='telegram') for(const [name,value] of Object.entries(tg?.themeParams||{})) if(/^#[\da-f]{6}$/i.test(value))document.body.style.setProperty('--tg-theme-'+name.replaceAll('_','-'),value);
    try{localStorage.setItem(key,JSON.stringify(choice));}catch(_error){}
    window.dispatchEvent(new CustomEvent('ui-lab:theme',{detail:{...choice,resolved:mode}}));
    return {...choice,resolved:mode};
  }
  window.UIStandardTheme={apply,current:()=>({...choice,resolved:document.body.dataset.uiMode})};
  window.Telegram?.WebApp?.onEvent?.('themeChanged',()=>apply());
  matchMedia('(prefers-color-scheme: dark)').addEventListener?.('change',()=>apply());
  apply();
})();
