(() => {
  'use strict';
  const tg = window.MiniAppUtils?.initTelegram?.() || window.Telegram?.WebApp;
  tg?.MainButton?.hide?.();
  const list = document.getElementById('apps-list'), status = document.getElementById('apps-status');
  const refresh = document.getElementById('apps-refresh');
  const paths = {
    tat_tracker:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    complaint_cases:'<path d="M21 11a8 8 0 0 1-8 8H6l-4 3V10a8 8 0 0 1 8-8h3a8 8 0 0 1 8 8Z"/><path d="M7 8h9M7 12h6"/>',
    pipeline_portal:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    loan_origination:'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8ZM14 2v6h6M8 12h8M8 16h6"/>',
  };
  const icon = key => `<svg aria-hidden="true" viewBox="0 0 24 24">${paths[key] || '<path d="m9 6 6 6-6 6"/>'}</svg>`;
  function link(destination, className = '') {
    const node = document.createElement('a'); node.className = className;
    const url = new URL(destination.url, location.origin);
    if (url.origin !== location.origin && !(url.protocol === 'https:' && url.hostname === 't.me')) return null;
    node.href = url.href;
    node.addEventListener('click', event => {
      if (url.hostname === 't.me' && tg?.openTelegramLink) {event.preventDefault(); tg.openTelegramLink(url.href);}
    });
    return node;
  }
  let generation = 0;
  async function load() {
    const ticket = ++generation;
    refresh.disabled = true; list.setAttribute('aria-busy','true');
    status.hidden = false; status.textContent = 'Loading your apps…';
    list.replaceChildren();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch('/api/miniapps/available/', {method:'POST',cache:'no-store',
        signal:controller.signal, headers:{'X-Telegram-Init-Data':tg?.initData || ''}});
      const data = await response.json();
      if (ticket !== generation) return;
      if (!response.ok || !data.ok) throw new Error(data.error || 'Could not load your apps. Tap Refresh to retry.');
      for (const app of data.apps || []) {
        const card = document.createElement(app.destinations.length > 1 ? 'details' : 'div'); card.className = 'app-choice';
        const main = app.destinations.length > 1 ? document.createElement('summary') : link(app.destinations[0], 'app-link');
        if (!main) continue;
        const identity = document.createElement('span'), name = document.createElement('strong'), detail = document.createElement('small');
        name.textContent = app.label; detail.textContent = app.description; identity.append(name,detail);
        main.innerHTML = icon(app.key); main.append(identity); main.insertAdjacentHTML('beforeend',icon('next')); card.append(main);
        if (app.destinations.length > 1) {
          const choices = document.createElement('div'); choices.className = 'app-groups';
          for (const destination of app.destinations) {const item = link(destination); if (item) {item.textContent = destination.label; item.insertAdjacentHTML('beforeend',icon('next')); choices.append(item);}}
          card.append(choices);
        }
        list.append(card);
      }
      status.hidden = list.childElementCount > 0;
      if (!status.hidden) status.textContent = 'No apps are assigned to this account. Ask IT to check your access.';
    } catch (error) {
      if (ticket === generation) status.textContent = error.name === 'AbortError' ? 'Connection timed out. Tap Refresh to retry.' : error.message || 'Could not connect. Tap Refresh to retry.';
    } finally {
      clearTimeout(timeout);
      if (ticket === generation) {refresh.disabled = false; list.removeAttribute('aria-busy');}
    }
  }
  refresh.onclick = load;
  tg?.onEvent?.('activated', load);
  load();
})();
