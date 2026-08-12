(function () {
  'use strict';

  const tg = window.Telegram?.WebApp;
  const api = {
    async apiFetch(path, options) {
      const requestOptions = options || {};
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 20000);
      try {
        const response = await fetch(`/api/origination/api${path}`, {
          ...requestOptions,
          cache: requestOptions.method ? requestOptions.cache : 'no-store',
          signal: controller.signal,
          headers: {
            'Content-Type': 'application/json',
            ...(tg?.initData ? { 'X-Telegram-Init-Data': tg.initData } : {}),
            ...(requestOptions.headers || {}),
          },
        });
        return { ok: response.ok, status: response.status, data: await response.json().catch(() => ({})) };
      } catch (error) {
        return { ok: false, status: 0, data: { error: error?.name === 'AbortError' ? 'The request timed out. Try again.' : 'Could not connect. Check your signal and try again.' } };
      } finally {
        window.clearTimeout(timeout);
      }
    },
    async postJson(path, payload) {
      const body = { ...(payload || {}) };
      const key = body.client_request_id || requestKey('write');
      body.client_request_id = key;
      return this.apiFetch(path, {
        method: 'POST',
        headers: { 'Idempotency-Key': key, 'X-Request-ID': key },
        body: JSON.stringify(body),
      });
    },
  };
  let products = [];
  let applications = [];
  let current = null;
  let saveTimer = null;

  function escapeHtml(value) {
    const node = document.createElement('div');
    node.textContent = String(value ?? '');
    return node.innerHTML;
  }

  function requestKey(prefix) {
    return `${prefix}-${window.crypto?.randomUUID ? window.crypto.randomUUID() : Date.now()}`;
  }

  function draftKey(id) {
    return `portal-origination-draft:${id}`;
  }

  function root() {
    return document.getElementById('origination-root');
  }

  function errorView(message) {
    const target = root();
    if (target) target.innerHTML = `<div class="batch-warning">${escapeHtml(message)}</div>`;
  }

  function fieldInput(field, value, disabled) {
    const key = escapeHtml(field.key);
    const label = escapeHtml(field.label || field.key);
    const required = field.required ? ' required' : '';
    if (field.type === 'boolean') {
      return `<label class="form-row"><span>${label}</span><select data-field="${key}"${required}${disabled ? ' disabled' : ''}><option value="">Choose</option><option value="true"${value === true ? ' selected' : ''}>Yes</option><option value="false"${value === false ? ' selected' : ''}>No</option></select></label>`;
    }
    if (field.type === 'choice') {
      const options = (field.options || []).map(option => `<option value="${escapeHtml(option)}"${value === option ? ' selected' : ''}>${escapeHtml(option)}</option>`).join('');
      return `<label class="form-row"><span>${label}</span><select data-field="${key}"${required}${disabled ? ' disabled' : ''}><option value="">Choose</option>${options}</select></label>`;
    }
    const type = field.type === 'date' ? 'date' : (field.type === 'money' ? 'number' : (field.type === 'phone' ? 'tel' : 'text'));
    return `<label class="form-row"><span>${label}</span><input data-field="${key}" type="${type}" value="${escapeHtml(value ?? '')}"${required}${disabled ? ' disabled' : ''}></label>`;
  }

  function collectPayload() {
    const payload = {};
    root()?.querySelectorAll('[data-field]').forEach(input => {
      if (input.value === '') payload[input.dataset.field] = '';
      else if (input.options && ['true', 'false'].includes(input.value)) payload[input.dataset.field] = input.value === 'true';
      else payload[input.dataset.field] = input.value;
    });
    return payload;
  }

  async function saveDraft(showMessage) {
    if (!current) return;
    const payload = collectPayload();
    localStorage.setItem(draftKey(current.id), JSON.stringify({ revision: current.revision, payload, savedAt: Date.now() }));
    const key = requestKey('save');
    const result = await api.apiFetch(`/applications/${current.id}/`, {
      method: 'PATCH',
      headers: { 'Idempotency-Key': key, 'X-Request-ID': key },
      body: JSON.stringify({ revision: current.revision, form_payload: payload, request_id: key }),
    }, tg);
    if (!result.ok || !result.data?.ok) {
      if (showMessage) errorView(result.data?.error || 'Draft is saved on this phone and will retry when you save again.');
      return false;
    }
    current = result.data.application;
    localStorage.removeItem(draftKey(current.id));
    const status = document.getElementById('origination-save-status');
    if (status) status.textContent = 'Saved';
    return true;
  }

  function scheduleSave() {
    const status = document.getElementById('origination-save-status');
    if (status) status.textContent = 'Saving...';
    window.clearTimeout(saveTimer);
    saveTimer = window.setTimeout(() => saveDraft(false), 800);
  }

  function renderEditor(application) {
    current = application;
    tg?.BackButton?.show();
    let local = null;
    try {
      local = JSON.parse(localStorage.getItem(draftKey(application.id)) || 'null');
    } catch (_) {
      localStorage.removeItem(draftKey(application.id));
    }
    const values = local?.revision === application.revision ? local.payload : application.form_payload;
    const fields = application.form_schema?.fields || [];
    const editable = ['draft', 'correction_required'].includes(application.status);
    let actions = '';
    if (editable) actions = '<button type="button" class="btn btn-secondary" id="origination-save">Save draft</button><button type="button" class="btn btn-primary" id="origination-submit">Submit for review</button>';
    if (application.status === 'ready_for_review') actions = '<button type="button" class="btn btn-secondary" data-review="request_correction">Request correction</button><button type="button" class="btn btn-secondary" data-review="decline">Decline</button><button type="button" class="btn btn-primary" data-review="approve">Approve</button>';
    if (application.status === 'reviewed') actions = '<button type="button" class="btn btn-primary" id="origination-prepare-signing">Prepare signing package</button>';
    root().innerHTML = `
      <button type="button" class="btn btn-secondary" id="origination-back">Back to applications</button>
      <article class="form-section" style="margin-top:12px">
        <div class="section-head"><div><h3>${escapeHtml(application.product_name)}</h3><p>${escapeHtml(application.reference_number)} · ${escapeHtml(application.status.replaceAll('_', ' '))}</p></div><span id="origination-save-status">${local ? 'Recovered from this phone' : 'Saved'}</span></div>
        <div id="origination-fields">${fields.map(field => fieldInput(field, values?.[field.key], !editable || field.editable === false)).join('')}</div>
        <div class="form-actions">${actions}</div>
      </article>`;
    document.getElementById('origination-back').onclick = renderList;
    if (editable) {
      document.getElementById('origination-save').onclick = () => saveDraft(true);
      document.getElementById('origination-fields').addEventListener('input', scheduleSave);
      document.getElementById('origination-submit').onclick = async () => {
        if (!(await saveDraft(true))) return;
      const result = await api.postJson(`/applications/${current.id}/submit/`, { revision: current.revision });
        if (!result.ok || !result.data?.ok) return errorView(result.data?.error || 'Could not submit the application.');
        await load();
      };
    }
    root().querySelectorAll('[data-review]').forEach(button => {
      button.onclick = async () => {
        const decision = button.dataset.review;
        const reason = decision === 'approve' ? '' : window.prompt('Record the reason for this decision:');
        if (decision !== 'approve' && !reason) return;
        const result = await api.postJson(`/applications/${current.id}/review/`, { revision: current.revision, decision, reason });
        if (!result.ok) return errorView(result.data?.error || 'Could not record the review.');
        await load();
      };
    });
    const prepare = document.getElementById('origination-prepare-signing');
    if (prepare) prepare.onclick = async () => {
      const result = await api.postJson(`/applications/${current.id}/prepare-signing/`, { revision: current.revision });
      if (!result.ok) return errorView(result.data?.error || 'Could not prepare signing.');
      await load();
    };
  }

  function renderList() {
    current = null;
    tg?.BackButton?.hide();
    const target = root();
    if (!target) return;
    const productOptions = products.map(item => `<option value="${escapeHtml(item.product_key)}">${escapeHtml(item.name)}</option>`).join('');
    const cards = applications.map(item => `<button type="button" class="farmer-card" data-application-id="${item.id}" style="width:100%;text-align:left"><div class="fc-name">${escapeHtml(item.reference_number)}</div><div class="fc-sub">${escapeHtml(item.product_name)} · ${escapeHtml(item.branch || 'No branch')} · ${escapeHtml(item.status.replaceAll('_', ' '))}</div></button>`).join('');
    target.innerHTML = `
      ${products.length ? `<form id="origination-create" class="form-section"><h3>Start an application</h3><label class="form-row"><span>Product</span><select name="product_key" required>${productOptions}</select></label><label class="form-row"><span>Branch</span><input name="branch" required autocomplete="organization"></label><button class="btn btn-primary" type="submit">Start application</button></form>` : '<div class="batch-warning">No origination product has been approved and activated yet.</div>'}
      <div class="section-head" style="margin-top:18px"><h3>Applications</h3></div>
      <div class="farmer-list">${cards || '<div class="empty-state"><div class="es-title">No applications yet</div><div class="es-sub">Approved products will appear above when the pilot is activated.</div></div>'}</div>`;
    target.querySelectorAll('[data-application-id]').forEach(button => {
      button.onclick = async () => {
        const result = await api.apiFetch(`/applications/${button.dataset.applicationId}/`, {});
        if (!result.ok) return errorView(result.data?.error || 'Could not open this application.');
        renderEditor(result.data.application);
      };
    });
    const form = document.getElementById('origination-create');
    if (form) form.onsubmit = async event => {
      event.preventDefault();
      const values = new FormData(form);
      const result = await api.postJson('/applications/', { product_key: values.get('product_key'), branch: values.get('branch') });
      if (!result.ok) return errorView(result.data?.error || 'Could not start the application.');
      renderEditor(result.data.application);
    };
  }

  async function load() {
    if (!root()) return;
    const [productResult, applicationResult] = await Promise.all([
      api.apiFetch('/products/', {}),
      api.apiFetch('/applications/', {}),
    ]);
    if (!productResult.ok || !applicationResult.ok) return errorView(productResult.data?.error || applicationResult.data?.error || 'Could not load origination.');
    products = productResult.data.products || [];
    applications = applicationResult.data.applications || [];
    renderList();
    const refresh = document.getElementById('origination-refresh');
    if (refresh) refresh.onclick = load;
  }

  window.LoanOriginationMiniApp = { load };
  tg?.ready();
  tg?.expand();
  tg?.BackButton?.onClick(() => {
    if (current) renderList();
  });
  if (document.body?.dataset.miniapp === 'loan-origination') load();
})();
