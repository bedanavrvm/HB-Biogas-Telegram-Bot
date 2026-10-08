(function () {
  'use strict';
  const pending = new Map();
  let activeDialog = null;
  const icon = '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 6 9 7 9-7"/></svg>';
  const names = {date_from:'From',date_to:'To',from:'From',to:'To',date_mode:'Period',date_basis:'Date basis',
    metric:'Measure',metric_value:'Result',chart_key:'Chart',series_key:'Series',bucket_key:'Selection',sla_state:'Target result'};
  const values = {all:'Any time',custom:'Date range',month:'Month',hb_response:'HB response',late:'Late',
    within_target:'Within target',near_target:'Near target',overdue:'Over target',current:'Current workload',performance:'Period performance',
    jbl_visit:'JBL visit',final_review:'Final review',reported:'Reported date',resolved:'Resolved date'};
  function readable(value) {
    if (/^\d{4}-\d{2}-\d{2}$/.test(String(value))) {
      const date = new Date(`${value}T12:00:00+03:00`);
      return date.toLocaleDateString('en-GB',{day:'2-digit',month:'short',year:'numeric',timeZone:'Africa/Nairobi'}).replace(/ /g,'-');
    }
    return values[value] || String(value).replace(/_/g,' ');
  }
  function requestKey() {
    if (window.crypto?.randomUUID) return window.crypto.randomUUID();
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => { const r = Math.random() * 16 | 0; return (c === 'x' ? r : (r & 3 | 8)).toString(16); });
  }
  function open(options) {
    if (activeDialog?.open) return;
    const origin = document.activeElement;
    const filters = JSON.parse(JSON.stringify(options.filters || {}));
    const dialog = document.createElement('dialog');
    dialog.className = 'report-email-dialog';
    dialog.setAttribute('aria-labelledby', 'report-email-dialog-title');
    dialog.innerHTML = '<form><header><h2 id="report-email-dialog-title">Email report</h2><button class="report-email-icon" type="button" data-close aria-label="Close email report">×</button></header><p data-title></p><p class="report-email-scope"></p><label>Email address<input type="email" name="email" required maxlength="254" autocomplete="email" placeholder="name@company.co.ke"></label><p role="status" aria-live="polite"></p><footer><button type="button" data-close>Cancel</button><button type="submit" class="report-email-send">Send</button></footer></form>';
    dialog.querySelector('[data-title]').textContent = options.title || 'Filtered report';
    const scope = Object.entries(filters).filter(([k,v]) => v !== '' && v != null && !['page','page_size','sort','group'].includes(k));
    dialog.querySelector('.report-email-scope').textContent = scope.map(([k,v]) => `${names[k] || k[0].toUpperCase()+k.slice(1).replace(/_/g,' ')}: ${readable(v)}`).join(' · ') || 'All matching cases in your report access';
    const form = dialog.querySelector('form'), status = dialog.querySelector('[role="status"]'), send = dialog.querySelector('[type="submit"]');
    window.MiniAppUtils?.bindAccessibleForm?.(form);
    let busy = false;
    dialog.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => dialog.close()));
    const back = options.telegram?.BackButton;
    const backWasVisible = back?.isVisible;
    dialog.addEventListener('close', () => {
      activeDialog = null;
      if (!busy) dialog.remove(); origin?.focus?.();
      if (back && !backWasVisible) back.hide?.();
      window.dispatchEvent(new Event('portal:dialog-change'));
    });
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (busy || !form.reportValidity()) return;
      const email = form.elements.email.value.trim();
      const identity = JSON.stringify([options.workflow, options.preset, filters, email.toLowerCase()]);
      const key = pending.get(identity) || requestKey(); pending.set(identity, key);
      busy = true; send.disabled = true; form.elements.email.readOnly = true; status.textContent = 'Preparing report…';
      try {
        let result = await options.post({ email, preset: options.preset, filters, client_request_id: key });
        const messages = {queued:'Preparing report…', processing:'Sending…', retry:'Delivery retry scheduled.', accepted:'Accepted for delivery.', delivered:'Delivered.', delayed:'Email delivery is delayed.', failed:'Email could not be sent.', blocked:'Report access changed. Reopen the report.', uncertain:'Delivery is uncertain. Ask IT to check before sending again.', bounced:'The recipient address rejected this email.', complained:'This address cannot receive further reports.'};
        for (let i = 0; i < 30; i++) {
          status.textContent = result.issue || messages[result.status] || 'Sending…';
          if (!['queued','processing'].includes(result.status)) break;
          await new Promise(resolve => setTimeout(resolve, 2000));
          result = await options.post({action:'status', delivery_id: result.delivery_id});
        }
        options.notify?.(status.textContent, ['accepted','delivered'].includes(result.status) ? 'ok' : 'info');
        // Reopening after confirmed acceptance is a deliberate new send. Keep
        // unresolved keys so lost responses/retries cannot duplicate delivery.
        if (['accepted','delivered'].includes(result.status)) pending.delete(identity);
        // A confirmed reservation must not be duplicated by another click.
        send.textContent = 'Submitted';
      } catch (error) {
        status.textContent = error.message || 'Could not send the report. Try again.';
        send.disabled = false; send.textContent = 'Retry'; form.elements.email.readOnly = false;
      } finally { busy = false; if (!dialog.open) dialog.remove(); }
    });
    document.body.appendChild(dialog); activeDialog = dialog; dialog.showModal(); form.elements.email.focus();
    back?.show?.(); window.dispatchEvent(new Event('portal:dialog-change'));
  }
  function attach(button, options) {
    if (!button || button.dataset.emailBound) return;
    button.dataset.emailBound = 'true'; button.classList.add('report-email-icon');
    button.setAttribute('aria-label','Email report'); button.title = 'Email report'; button.innerHTML = icon;
    button.addEventListener('click', () => open(typeof options === 'function' ? options() : options));
  }
  function closeActive() { if (!activeDialog?.open) return false; activeDialog.close(); return true; }
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && activeDialog?.open) {event.preventDefault();event.stopImmediatePropagation();closeActive();}
  }, true);
  window.MiniAppReportEmailExport = {open, attach, icon, closeActive, isOpen:() => Boolean(activeDialog?.open)};
}());
