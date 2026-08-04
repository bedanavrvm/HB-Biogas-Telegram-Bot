(function () {
  'use strict';

  const QUEUE_CONFIG = {
    jbl: { endpoint: '/jbl-queue/', fragmentEndpoint: '/queues/jbl/fragment/', listId: 'jbl-list', pageKey: 'jbl', mode: 'jbl_visit', emptyTitle: 'JBL visit queue is clear', emptySub: 'No farmer is waiting for a JBL visit.' },
    my_visits: { endpoint: '/my-visits/', fragmentEndpoint: '/queues/my_visits/fragment/', listId: 'my-visits-list', pageKey: 'my_visits', mode: null, emptyTitle: 'No submitted JBL visits', emptySub: 'Cases you log after a JBL visit will appear here.' },
    credit: { endpoint: '/credit-queue/', fragmentEndpoint: '/queues/credit/fragment/', listId: 'credit-list', pageKey: 'credit', mode: 'credit', emptyTitle: 'Credit queue is clear', emptySub: 'No farmer is waiting for credit analysis.' },
    final: { endpoint: '/final-review-queue/', fragmentEndpoint: '/queues/final/fragment/', listId: 'final-list', pageKey: 'final', mode: 'final_review', emptyTitle: 'Final review queue is clear', emptySub: 'No client is waiting for Head of Rural review.' },
    requisition: { endpoint: '/requisition-queue/', fragmentEndpoint: '/queues/requisition/fragment/', listId: 'req-list', pageKey: 'requisition', mode: 'requisition', emptyTitle: 'No orders to assign', emptySub: 'Approved cases awaiting an order number will appear here.' },
    deferred: { endpoint: '/deferred/', fragmentEndpoint: '/queues/deferred/fragment/', listId: 'deferred-list', pageKey: 'deferred', mode: null, emptyTitle: 'No deferred cases', emptySub: 'No farmers are deferred or flagged.' },
    all: { endpoint: '/farmers/', fragmentEndpoint: '/queues/all/fragment/', listId: 'all-list', pageKey: 'all', mode: null, emptyTitle: 'No farmers found', emptySub: 'Try a different search term.' },
    batches: { endpoint: '/requisition-batches/', fragmentEndpoint: '/requisition-batches/fragment/', listId: 'batches-list', pageKey: 'batches', mode: null, emptyTitle: 'No batches found', emptySub: 'No requisition batches have been generated yet.' },
  };

  function config() {
    return QUEUE_CONFIG;
  }

  function getConfig(queueKey) {
    return QUEUE_CONFIG[queueKey] || null;
  }

  function queueKeyForList(listId) {
    if (!listId) return null;
    const entry = Object.entries(QUEUE_CONFIG).find(function ([, cfg]) {
      return cfg.listId === listId && cfg.fragmentEndpoint;
    });
    return entry ? entry[0] : null;
  }

  function appendCommonFilters(params, state, queueKey) {
    if ((state.filters || {}).county) params.set('county', state.filters.county);
    if ((state.filters || {}).branch) params.set('branch', state.filters.branch);
    // The selected Head of Rural lens belongs to the Final Review queue, not
    // to whatever page the shell last considered active. This keeps a payment
    // review selection intact across fragment swaps and direct navigation.
    if (queueKey === 'final' && (state.filters || {}).reviewStage) {
      params.set('stage', state.filters.reviewStage);
    }
    if (state.workspaceOrdering === 'newest') params.set('ordering', 'newest');
  }

  function queueUrl(queueKey, page, state) {
    const cfg = getConfig(queueKey);
    if (!cfg) return '';
    const params = new URLSearchParams({ page: String(page || 1) });
    if (queueKey === 'all' && state.search) params.set('search', state.search);
    if (queueKey === 'jbl' && state.jblSearch) params.set('search', state.jblSearch);
    if (queueKey === 'all' || cfg.fragmentEndpoint) appendCommonFilters(params, state, queueKey);
    return cfg.endpoint + '?' + params.toString();
  }

  function fragmentPath(queueKey, page, state) {
    const cfg = getConfig(queueKey);
    if (!cfg || !cfg.fragmentEndpoint) return '';
    const params = new URLSearchParams({ page: String(page || 1) });
    if (queueKey === 'all' && state.search) params.set('search', state.search);
    if (queueKey === 'jbl' && state.jblSearch) params.set('search', state.jblSearch);
    appendCommonFilters(params, state, queueKey);
    return cfg.fragmentEndpoint + '?' + params.toString();
  }

  async function renderFragment(queueKey, page, deps) {
    const cfg = getConfig(queueKey);
    const list = cfg && deps.el ? deps.el(cfg.listId) : null;
    if (!cfg || !cfg.fragmentEndpoint || !window.htmx || !list) return false;
    try {
      const path = fragmentPath(queueKey, page, deps.state || {});
      const html = deps.portalApi && deps.portalApi.fetchHtml
        ? await deps.portalApi.fetchHtml(path, {}, deps.tg)
        : await deps.fetchHtml(path);
      // A search, filter change, or route change may have started a newer
      // request while this one was in transit. Do not let an old response
      // replace the current queue (or leave its current loader behind).
      if (deps.isCurrent && !deps.isCurrent()) return false;
      list.innerHTML = html;
      if (queueKey === 'batches') deps.hydrateBatchCards(list);
      else deps.hydrateFarmerCards(list);
      if (deps.state && deps.state.pages) deps.state.pages[queueKey] = page || 1;
      if (window.lucide) window.lucide.createIcons();
      return true;
    } catch (error) {
      return false;
    }
  }

  window.PortalMiniAppQueues = {
    config,
    fragmentPath,
    getConfig,
    queueKeyForList,
    queueUrl,
    renderFragment,
  };
})();
