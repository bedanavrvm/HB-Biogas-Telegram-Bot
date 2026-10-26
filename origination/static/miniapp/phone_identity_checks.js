(function (global) {
  'use strict';
  let disposeCurrent = () => {};
  let refreshCurrent = () => {};
  const inFlight = new Set();

  function mount(container, options) {
    disposeCurrent();
    refreshCurrent = () => {};
    const application = options.current();
    if (!application?.phone_id_checks?.allowed) return;
    const applicationId = application.id;
    const abort = new AbortController();
    let active = true;
    let timer;
    let deadline = 0;
    let status = application.phone_id_checks;
    const path = `/applications/${applicationId}/phone-id-checks/`;
    const live = () => active && options.current()?.id === applicationId;
    const key = target => `${applicationId}:${target}`;
    const value = field => container.querySelector(`[data-field="${CSS.escape(field)}"]`)?.value
      ?? options.current()?.form_payload?.[field] ?? '';
    const normalize = text => global.MiniAppUtils?.normalizeKenyanPhone?.(text) || '';
    const equalSaved = target => normalize(value(target.field_key)) === normalize(options.current()?.form_payload?.[target.field_key])
      && String(value(target.id_field_key)).trim() === String(options.current()?.form_payload?.[target.id_field_key] || '').trim();

    function valid(target) {
      const fields = options.current()?.form_schema?.fields || [];
      return Boolean(normalize(value(target.field_key))) && /^\d{1,9}$/.test(String(value(target.id_field_key)).trim())
        && [target.field_key, target.id_field_key].every(field => {
          const definition = fields.find(item => item.key === field);
          return !definition || !global.OriginationFieldRules?.validate(definition, String(value(field)).trim());
        });
    }

    function update() {
      if (!live()) return;
      for (const target of status.targets || []) {
        const host = container.querySelector(`[data-phone-id-target="${target.target}"]`);
        if (!host) continue;
        const compact = host.hasAttribute('data-phone-id-compact');
        const expanded = host.querySelector('details')?.open;
        host.replaceChildren();
        host.className = compact ? 'phone-id-compact' : 'field-help';
        host.setAttribute('aria-live', 'polite');
        const revisionMatches = status.revision === options.current()?.revision;
        const same = revisionMatches && equalSaved(target);
        const busy = inFlight.has(key(target.target)) || target.status === 'checking';
        const checkAgain = same && target.status !== 'not_checked' && target.freshness !== 'changed';
        let text = '';
        if (!revisionMatches) text = 'Application changed. Refresh before checking.';
        else if (!same && target.status !== 'not_checked') text = 'Details changed; previous check does not apply.';
        else if (target.freshness === 'changed') text = 'Previous check does not apply to these details.';
        else if (busy) text = 'Checking registration…';
        else if (['matched', 'not_matched'].includes(target.status)) {
          const date = new Date(target.checked_at).toLocaleDateString('en-KE', {timeZone:'Africa/Nairobi'});
          text = `${target.status === 'matched' ? 'Registration matched' : 'Registration does not match this ID'} · ${date}`;
          if (target.reused) text += ' · Reused';
          if (target.freshness === 'expired') text += ' · Expired';
        } else if (['unknown', 'unavailable'].includes(target.status)) text = target.message || 'Could not verify. This is not a mismatch.';
        if (text && status.environment === 'sandbox') text = `Sandbox test · ${text}`;
        let content = host;
        if (compact && text) {
          const details = document.createElement('details');
          details.open = Boolean(expanded);
          const summary = document.createElement('summary');
          summary.title = text;
          summary.setAttribute('aria-label', 'Phone registration details');
          summary.innerHTML = target.status === 'matched'
            ? '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="m5 12 4 4L19 6"/></svg>'
            : '<svg aria-hidden="true" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v6m0 3v1"/></svg>';
          content = document.createElement('div');
          content.className = 'phone-check-popover';
          details.append(summary, content);
          host.appendChild(details);
        }
        if (text) {
          const feedback = document.createElement('span');
          feedback.className = 'field-help';
          feedback.textContent = text;
          feedback.setAttribute('role', 'status');
          content.appendChild(feedback);
        }
        if (status.enabled && revisionMatches && valid(target)) {
          const button = document.createElement('button');
          button.type = 'button';
          button.className = checkAgain || compact ? 'icon-button' : 'btn btn-secondary';
          if (checkAgain || compact) {
            // Same refresh glyph and sizing as the existing Origination controls.
            button.innerHTML = '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M20 11a8 8 0 1 0-2.34 5.66M20 4v7h-7"/></svg>';
          } else button.textContent = busy ? 'Checking…' : 'Check against ID';
          button.title = busy ? 'Checking…' : checkAgain ? 'Check again' : 'Check against ID';
          button.setAttribute('aria-label', `Check ${target.target === 'alternate' ? 'alternate' : 'primary'} Applicant phone against ID${checkAgain ? ' again' : ''}`);
          button.disabled = busy;
          button.addEventListener('click', () => check(target.target, checkAgain), {signal:abort.signal});
          content.appendChild(button);
        }
        host.hidden = !host.childNodes.length;
      }
    }

    async function refresh() {
      const result = await options.get(path);
      if (!live()) return false;
      if (result.ok && result.data?.phone_id_checks?.allowed) {
        const checking = new Set((status.targets || []).filter(target => target.status === 'checking').map(target => target.target));
        status = result.data.phone_id_checks;
        options.current().phone_id_checks = status;
        update();
        for (const target of status.targets || []) if (checking.has(target.target) && target.status !== 'checking') announce(target);
        return true;
      }
      if (result.status === 403) {
        status = {enabled:false, targets:[]};
        container.querySelectorAll('[data-phone-id-target]').forEach(host => host.replaceChildren());
      }
      return false;
    }

    function announce(target) {
      const prefix = status.environment === 'sandbox' ? 'Sandbox test · ' : '';
      if (target?.status === 'matched') options.toast(prefix + 'Registration matched.', 'success');
      else if (target?.status === 'not_matched') options.toast(prefix + 'Registration does not match this ID.', 'warning');
      else if (target && ['unknown', 'unavailable'].includes(target.status)) options.toast(prefix + (target.message || 'Could not verify. This is not a mismatch.'), 'info');
    }

    function poll() {
      clearTimeout(timer);
      if (!live()) return;
      if (Date.now() >= deadline) {
        for (const target of status.targets || []) if (target.status === 'checking') {
          target.status = 'unknown';
          target.message = 'The result is uncertain. No automatic retry was made.';
        }
        update();
        return;
      }
      timer = setTimeout(async () => {
        const loaded = await refresh();
        if (live() && (!loaded || status.targets?.some(target => target.status === 'checking'))) poll();
      }, 2000);
    }

    async function check(targetName, freshCheck = false) {
      if (!live() || inFlight.has(key(targetName))) return;
      inFlight.add(key(targetName));
      update();
      try {
        if (!await options.save()) return;
        if (!live() || !await refresh()) return;
        const target = status.targets.find(item => item.target === targetName);
        if (status.revision !== options.current()?.revision) {
          options.toast('Application changed. Refresh before checking.', 'warning');
          return;
        }
        if (!target?.can_check || !equalSaved(target)) {
          options.toast('Save valid Applicant details before checking.', 'warning');
          return;
        }
        const message = freshCheck
          ? `Check phone ending ${target.phone_suffix} against National ID ending ${target.id_suffix} again? Ask Safaricom for a new result instead of reusing the previous check. A charge may apply.`
          : `Check whether the applicant phone ending ${target.phone_suffix} is registered against their National ID ending ${target.id_suffix}? A result checked within the last 30 days may be reused; otherwise Safaricom will be contacted and a charge may apply. This does not approve the application.`;
        const telegram = global.Telegram?.WebApp;
        const confirmed = typeof telegram?.showPopup === 'function'
          ? await new Promise(resolve => telegram.showPopup({title:freshCheck ? 'Check again' : 'Check phone against ID', message,
            buttons:[{id:'check', type:'default', text:'Check'}, {type:'cancel'}]}, id => resolve(id === 'check')))
          : global.confirm(message);
        if (!confirmed || !live()) return;
        const requestId = options.requestKey('phone-id');
        deadline = Date.now() + 120000;
        const response = await options.post(path, {target:targetName, revision:status.revision,
          subject_token:target.subject_token, confirmed:true, confirmation_version:1, client_request_id:requestId,
          ...(freshCheck ? {fresh_check:true} : {})});
        if (!live()) return;
        if (response.data?.result) Object.assign(target, response.data.result);
        if (!response.ok) options.toast(response.data?.error || 'Could not confirm the result. No automatic check retry was made.', 'warning');
        await refresh();
        if (response.ok && response.status !== 202) announce(status.targets?.find(item => item.target === targetName));
        if (response.status === 202 || response.status === 0 || status.targets?.some(item => item.status === 'checking')) poll();
      } catch (_) {
        if (live()) options.toast('Could not complete the check. No automatic retry was made.', 'warning');
      } finally {
        inFlight.delete(key(targetName));
        if (live()) update();
        else refreshCurrent();
      }
    }

    container.addEventListener('input', update, {signal:abort.signal});
    disposeCurrent = () => {active = false; abort.abort(); clearTimeout(timer);};
    refreshCurrent = () => {if (live()) refresh();};
    update();
    if (status.targets?.some(item => item.status === 'checking')) {
      deadline = Date.now() + 120000;
      poll();
    }
  }

  global.OriginationPhoneIdentity = {mount};
})(window);
