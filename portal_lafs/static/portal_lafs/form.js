(() => {
  'use strict';

  const escape = v => String(v ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  })[c]);
  let activeFlush = null;
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') activeFlush?.();
  });
  window.addEventListener('pagehide', () => activeFlush?.());
  const display = iso => /^\d{4}-\d{2}-\d{2}$/.test(iso || '') ? iso.split('-').reverse().join('/') : iso || '';
  function isoDate(value) {
    if (!value) return '';
    const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(value);
    if (!m) throw Error('Use dd/mm/yyyy for dates.');
    const d = new Date(Date.UTC(+m[3], +m[2] - 1, +m[1]));
    if (d.getUTCDate() !== +m[1] || d.getUTCMonth() !== +m[2] - 1) throw Error('Enter a valid date in dd/mm/yyyy format.');
    return `${m[3]}-${m[2]}-${m[1]}`;
  }
  function fieldMarkup(field, value) {
    const type = field.type || 'text',
      label = escape(field.label || field.key),
      name = escape(field.key),
      required = field.required ? ' *' : '';
    if (type === 'repeating_group') return `<section class="laf-wide" data-repeat="${name}"><h3>${label}${required}</h3><div data-rows></div><button type="button" data-add="${name}">Add item</button><span class="laf-field-error" data-error="${name}"></span></section>`;
    let control;
    if (type === 'boolean') control = `<select data-kind="boolean"><option value="">Select</option><option value="true" ${value === true ? 'selected' : ''}>Yes</option><option value="false" ${value === false ? 'selected' : ''}>No</option></select>`;else if (['choice', 'select'].includes(type)) control = `<select><option value="">Select</option>${(field.options || []).map(o => {
      const v = typeof o === 'string' ? o : o.value ?? o.key;
      return `<option value="${escape(v)}" ${value === v ? 'selected' : ''}>${escape(typeof o === 'string' ? o : o.label || v)}</option>`;
    }).join('')}</select>`;else if (type === 'textarea') control = `<textarea rows="3">${escape(value)}</textarea>`;else if (type === 'date') control = `<span class="laf-date"><input data-kind="date" placeholder="dd/mm/yyyy" inputmode="numeric" value="${escape(display(value))}" maxlength="10"><button type="button" data-calendar aria-label="Choose ${label} date">Calendar</button><input type="date" aria-hidden="true" tabindex="-1" value="${escape(value)}"></span>`;else control = `<input type="text" ${['money', 'number'].includes(type) ? 'inputmode="decimal"' : type === 'phone' ? 'inputmode="tel"' : ''} value="${escape(value)}">`;
    return `<label data-field="${name}">${label}${required}${control}<span class="laf-field-error" data-error="${name}"></span></label>`;
  }
  function readFields(root) {
    const values = {};
    root.querySelectorAll(':scope > label[data-field]').forEach(label => {
      const input = label.querySelector('input:not([type="date"]),select,textarea');
      if (input.disabled) return;
      let value = input.value;
      if (input.dataset.kind === 'date') value = isoDate(value);
      if (input.dataset.kind === 'boolean') value = value === '' ? '' : value === 'true';
      values[label.dataset.field] = value;
    });
    return values;
  }
  window.PortalLaf = {
    async mount({
      farmer,
      mode,
      root,
      apiFetch,
      onChange
    }) {
      const panel = document.createElement('section');
      panel.className = 'portal-laf-panel';
      panel.hidden = true;
      const existing = root.querySelector('[data-media-category="LAF"]');
      if (existing) existing.after(panel);else root.append(panel);
      const path = `/cases/${encodeURIComponent(farmer.id)}/laf/`;
      const callApi = async (url, options) => {
        const response = await apiFetch(url, options);
        if (!response.ok || !response.data?.ok) {
          const error = new Error(response.data?.message || response.data?.error || 'Could not update the LAF. Retry when connected.');
          error.payload = response.data;
          throw error;
        }
        return response.data;
      };
      let data,
        dialog,
        savePromise = Promise.resolve(),
        timer;
      const request = async (action, extra = {}) => {
        const posted = {
          action,
          ...(data?.version ? {
            version_id: data.version.id,
            revision: data.version.revision
          } : {}),
          ...extra
        };
        const result = await callApi(path, {
          method: 'POST',
          body: JSON.stringify(posted)
        });
        if (result.version !== undefined) {
          data = result;
          paint();
        }
        return result;
      };
      const notify = () => {
        farmer.visit_evidence = farmer.visit_evidence || {};
        if (data.active_source === 'form') farmer.visit_evidence.LAF = data.evidence_ready ? 1 : 0;
        farmer.workflow_revision = data.case_revision || farmer.workflow_revision;
        onChange?.();
      };
      const paint = () => {
        if (!panel.isConnected) return;
        panel.hidden = !data.enabled;
        if (panel.hidden) return;
        const v = data.version;
        panel.innerHTML = `<button type="button" class="btn btn-secondary" data-open ${!data.available && !v ? 'disabled' : ''}>${v ? 'Resume Biogas LAF' : 'Fill Biogas LAF'}</button>${v ? `<p class="meta">${escape(v.progress)} · Using ${data.active_source === 'form' ? 'Filled LAF' : 'Uploaded LAF'}</p>` : ''}${data.message ? `<p class="field-help">${escape(data.message)}</p>` : ''}`;
        panel.querySelector('[data-open]').onclick = () => open().catch(err => {
          panel.insertAdjacentHTML('beforeend', `<p role="alert">${escape(err.message)}</p>`);
        });
        notify();
      };
      const blob = async (versionId, page) => {
        const init = window.Telegram?.WebApp?.initData || '';
        const res = await fetch(`/api/portal/cases/${encodeURIComponent(farmer.id)}/laf/${versionId}/pages/${page}/`, {
          headers: {
            'X-Telegram-Init-Data': init
          }
        });
        if (!res.ok) throw Error('Could not load the LAF page.');
        return res.blob();
      };
      async function preview(role) {
        await saveNow(true);
        const p = await request('preview'),
          v = p.version;
        const external = Boolean(role?.external);
        await window.DocumentSigning.open({
          title: role ? `Sign as ${role.label}` : 'Biogas LAF',
          pageCount: v.page_count,
          loadPage: page => blob(v.id, page),
          previewSignature: values => request('signature_preview', values),
          external,
          stamps: data.stamps || [],
          needsStamp: Boolean(role?.needs_stamp),
          commit: async signature => {
            if (!role) throw Error('Close the preview and select the signer below.');
            await request('sign', {
              ...signature,
              role: role.role,
              digest: data.version.digest
            });
            await refresh();
            renderSigners();
          },
          readOnly: !role
        });
      }
      function collect() {
        const values = {};
        dialog.querySelectorAll('.laf-form-grid').forEach(grid => Object.assign(values, readFields(grid)));
        dialog.querySelectorAll('[data-repeat]').forEach(section => {
          values[section.dataset.repeat] = [...section.querySelectorAll('.laf-repeat-row')].map(readFields);
        });
        return values;
      }
      async function saveNow(force = false) {
        clearTimeout(timer);
        await savePromise.catch(() => {});
        if (!dialog || !data.version?.can_edit) return;
        const values = collect();
        if (!force && JSON.stringify(values) === JSON.stringify(dialog._saved)) return;
        const status = dialog.querySelector('[data-save-status]');
        status.textContent = 'Saving…';
        savePromise = request('save', {
          values
        }).then(async result => {
          if (result.form_updated) {
            dialog.close();
            dialog.remove();
            dialog = null;
            await open();
            throw Error('The published LAF changed. Review the updated form before signing.');
          }
          dialog._saved = values;
          status.textContent = 'Saved';
        }).catch(exc => {
          status.textContent = 'Not saved — retry before closing.';
          throw exc;
        });
        await savePromise;
      }
      async function refresh() {
        data = await callApi(path);
        paint();
      }
      function renderSigners() {
        if (!dialog) return;
        const v = data.version,
          container = dialog.querySelector('[data-signers]');
        container.innerHTML = `<h3>Signatures</h3><p>${escape(v.progress)}</p>${v.slots.map(slot => `<p>${escape(slot.label)}: ${slot.signed ? 'Signed' : slot.can_sign ? `<button type="button" data-sign="${escape(slot.role)}">${slot.external ? 'Sign in person' : 'Review and sign'}</button>` : 'Awaiting signature'}</p>`).join('')}`;
        container.querySelectorAll('[data-sign]').forEach(button => button.onclick = () => preview(v.slots.find(s => s.role === button.dataset.sign)).catch(showError));
        dialog.querySelector('[data-source]').textContent = data.active_source === 'form' ? 'Use uploaded LAF instead' : 'Use this filled LAF';
        dialog.querySelector('[data-source]').hidden = mode !== 'jbl_visit';
        dialog.querySelector('[data-archive]').hidden = v.progress !== 'Completed' || v.archive_status === 'Archived';
        dialog.querySelector('[data-archive-status]').textContent = v.archive_error || v.archive_status;
        if (v.frozen) dialog.querySelectorAll('[data-fields] input,[data-fields] select,[data-fields] textarea,[data-fields] button').forEach(i => {
          i.disabled = true;
        });
      }
      const showError = error => {
        if (!dialog) return;
        dialog.querySelector('[data-error-summary]').textContent = error.message;
        Object.entries(error.payload?.errors || {}).forEach(([field, message]) => {
          const el = [...dialog.querySelectorAll('[data-error]')].find(e => e.dataset.error === field);
          if (el) el.textContent = message;
        });
      };
      async function open() {
        if (!data.version) await request('start');
        dialog = document.createElement('dialog');
        dialog.className = 'portal-laf-dialog';
        dialog.innerHTML = `<header><h2>Biogas LAF</h2><button type="button" data-close>Save and close</button></header><p data-save-status role="status">Saved</p><p data-error-summary role="alert"></p><div data-fields></div><div class="laf-actions"><button type="button" data-save>Save draft</button><button type="button" data-preview>Preview LAF</button><button type="button" data-source>Use this filled LAF</button><button type="button" data-replace>Replace LAF</button><button type="button" data-archive>Retry archive</button></div><p class="meta" data-archive-status></p><section data-signers></section>`;
        const v = data.version,
          fields = v.schema.fields || [],
          target = dialog.querySelector('[data-fields]');
        const sections = v.schema.sections?.length ? v.schema.sections : [{
          key: 'details',
          label: 'LAF details'
        }];
        sections.forEach(section => {
          target.insertAdjacentHTML('beforeend', `<h3>${escape(section.label)}</h3><div class="laf-form-grid">${fields.filter(f => (f.section_key || 'details') === section.key).map(f => fieldMarkup(f, v.values[f.key] ?? '')).join('')}</div>`);
        });
        function addRow(section, field, values = {}) {
          const row = document.createElement('div');
          row.className = 'laf-repeat-row';
          row.innerHTML = (field.structure?.columns || []).map(col => fieldMarkup(col, values[col.key] ?? '')).join('') + '<button type="button" data-remove>Remove item</button>';
          row.querySelector('[data-remove]').onclick = () => {
            row.remove();
            schedule();
          };
          section.querySelector('[data-rows]').append(row);
        }
        target.querySelectorAll('[data-repeat]').forEach(section => {
          const field = fields.find(f => f.key === section.dataset.repeat);
          (v.values[field.key] || []).forEach(values => addRow(section, field, values));
          section.querySelector('[data-add]').onclick = () => {
            addRow(section, field);
            schedule();
          };
        });
        const schedule = () => {
          clearTimeout(timer);
          timer = setTimeout(() => saveNow().catch(showError), 600);
        };
        target.addEventListener('input', schedule);
        target.addEventListener('change', event => {
          if (event.target.type === 'date') {
            event.target.closest('.laf-date').querySelector('[data-kind="date"]').value = display(event.target.value);
          }
          schedule();
        });
        target.addEventListener('click', event => {
          const button = event.target.closest('[data-calendar]');
          if (button) {
            const picker = button.parentNode.querySelector('[type="date"]');
            picker.showPicker?.();
          }
        });
        fields.filter(f => f.editable === false).forEach(f => {
          target.querySelectorAll('[data-field]').forEach(label => {
            if (label.dataset.field === f.key) label.querySelectorAll('input,select,textarea,button').forEach(i => {
              i.disabled = true;
            });
          });
        });
        document.body.append(dialog);
        dialog.showModal();
        activeFlush = () => saveNow().catch(showError);
        dialog._saved = collect();
        if (!v.can_edit) target.querySelectorAll('input,select,textarea,button').forEach(i => {
          i.disabled = true;
        });
        const close = async () => {
          try {
            await saveNow();
            dialog.close();
            dialog.remove();
            dialog = null;
            activeFlush = null;
          } catch (exc) {
            showError(exc);
          }
        };
        dialog.querySelector('[data-close]').onclick = close;
        dialog.addEventListener('cancel', event => {
          event.preventDefault();
          close();
        });
        dialog.querySelector('[data-save]').onclick = () => saveNow(true).catch(showError);
        dialog.querySelector('[data-preview]').onclick = () => preview(null).catch(showError);
        dialog.querySelector('[data-source]').onclick = async () => {
          try {
            await saveNow();
            if (!confirm('Use this LAF source for the case? Existing evidence will be retained.')) return;
            await request('source', {
              source: data.active_source === 'form' ? 'upload' : 'form',
              confirm: true
            });
            renderSigners();
          } catch (exc) {
            showError(exc);
          }
        };
        dialog.querySelector('[data-replace]').hidden = mode !== 'jbl_visit';
        dialog.querySelector('[data-replace]').onclick = async () => {
          if (!confirm('Replace this LAF? Previous signatures remain in history and the replacement needs new signatures.')) return;
          try {
            await request('replace', {
              confirm: true
            });
            dialog.close();
            dialog.remove();
            dialog = null;
            await open();
          } catch (exc) {
            showError(exc);
          }
        };
        dialog.querySelector('[data-archive]').onclick = () => request('archive').then(renderSigners).catch(showError);
        renderSigners();
      }
      try {
        data = await callApi(path);
        if (root.isConnected) paint();
      } catch (_) {
        panel.remove();
      }
    }
  };
})();
