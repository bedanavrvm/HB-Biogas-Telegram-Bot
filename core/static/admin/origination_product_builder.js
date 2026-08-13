(function () {
  'use strict';

  const root = document.getElementById('origination-product-builder');
  const schemaInput = document.getElementById('id_form_schema');
  const signersInput = document.getElementById('id_signer_rules');
  if (!root || !schemaInput || !signersInput) return;

  const roles = JSON.parse(document.getElementById('origination-signer-role-data')?.textContent || '[]');
  const catalogue = JSON.parse(document.getElementById('origination-data-field-data')?.textContent || '[]');
  const inputCatalogue = catalogue.filter(item => item.source_type === 'user_input' && item.active !== false);
  const catalogueById = new Map(inputCatalogue.map(item => [String(item.id), item]));
  const fieldTypes = [
    ['text', 'Short text'], ['textarea', 'Long text'], ['number', 'Number'],
    ['money', 'Money'], ['date', 'Date'], ['phone', 'Phone'],
    ['national_id', 'National ID'], ['choice', 'Choice'], ['boolean', 'Yes / No'],
  ];
  const parse = (value, fallback) => { try { return JSON.parse(value || '') ?? fallback; } catch (_) { return fallback; } };
  const escapeHtml = value => { const node = document.createElement('div'); node.textContent = String(value ?? ''); return node.innerHTML; };
  const slug = value => String(value || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'item';
  const optionMarkup = (items, selected) => items.map(([value, label]) => `<option value="${escapeHtml(value)}"${value === selected ? ' selected' : ''}>${escapeHtml(label)}</option>`).join('');
  const canonicalOptions = field => {
    const selectedId = String(field.data_field_id || '');
    const legacy = !catalogueById.has(selectedId) && field.key
      ? `<option value="" selected>Legacy: ${escapeHtml(field.label || field.key)} (${escapeHtml(field.key)})</option>`
      : '<option value="">Choose a canonical field</option>';
    return legacy + inputCatalogue.map(item => {
      const search = [item.category, item.label, item.key, ...(item.aliases || [])].filter(Boolean).join(' · ');
      return `<option value="${escapeHtml(item.id)}"${String(item.id) === selectedId ? ' selected' : ''}>${escapeHtml(search)}</option>`;
    }).join('');
  };

  let schema = parse(schemaInput.value, {});
  let signers = parse(signersInput.value, []);
  schema.fields = Array.isArray(schema.fields) ? schema.fields : [];
  schema.sections = Array.isArray(schema.sections) ? schema.sections : [];
  signers = Array.isArray(signers) ? signers : [];

  function legacySection(key) {
    if (String(key).startsWith('guarantor_')) return ['guarantors', 'Guarantors'];
    if (String(key).startsWith('security_')) return ['security', 'Security'];
    if (String(key).startsWith('applicant_') || ['borrower_full_name', 'deponent_full_name', 'deponent_id_number'].includes(key)) return ['applicant', 'Applicant'];
    if (String(key).startsWith('loan_') || ['repayment_period', 'project_cost', 'installment_amount', 'interest_rate', 'approval_amount'].includes(key)) return ['loan', 'Loan'];
    return ['business', 'Business'];
  }

  function normalize() {
    if (!schema.sections.length) {
      const seen = new Set();
      schema.fields.forEach(field => {
        const [key, label] = legacySection(field.key);
        field.section_key ||= key;
        if (!seen.has(key)) { schema.sections.push({ key, label, help_text: '' }); seen.add(key); }
      });
      if (!schema.sections.length) schema.sections.push({ key: 'application', label: 'Application', help_text: 'Product application details' });
    }
    const firstSection = schema.sections[0]?.key || 'application';
    schema.fields.forEach(field => {
      field.section_key ||= firstSection;
      field.type ||= 'text';
      field.width ||= field.type === 'textarea' ? 'full' : 'half';
      field.help_text ||= '';
      field.options = Array.isArray(field.options) ? field.options : [];
    });
    signers = signers.filter(item => item && typeof item === 'object').map(item => ({
      role: item.role || 'borrower',
      required: item.required !== false,
      slots: (Array.isArray(item.slots) ? item.slots : []).map(slotItem => {
        const slot = typeof slotItem === 'string' ? { key: slotItem } : { ...(slotItem || {}) };
        return {
          key: slot.key || 'signature', label: slot.label || String(slot.key || 'signature').replaceAll('_', ' '),
          type: slot.type || item.slot_type || 'signature', required: slot.required ?? item.required !== false,
        };
      }),
    }));
    if (!signers.length) signers.push({ role: 'borrower', required: true, slots: [{ key: 'signature', label: 'Borrower signature', type: 'signature', required: true }] });
    sync();
  }

  function sync() {
    schemaInput.value = JSON.stringify(schema);
    signersInput.value = JSON.stringify(signers);
  }

  function fieldMarkup(field, fieldIndex) {
    const choiceOptions = (field.options || []).map(option => {
      if (option && typeof option === 'object') return `${option.code} | ${option.label || option.code}`;
      return String(option || '');
    }).filter(Boolean).join('\n');
    return `<article class="opb-field" data-field-index="${fieldIndex}">
      <div class="opb-row">
        <label class="opb-wide">Canonical data field<select data-prop="data_field_id">${canonicalOptions(field)}</select></label>
        <label>Stable key<input data-prop="key" value="${escapeHtml(field.key)}" readonly></label>
        <label>Label<input data-prop="label" value="${escapeHtml(field.label || '')}" required></label>
        <label>Control<input value="${escapeHtml(fieldTypes.find(item => item[0] === field.type)?.[1] || field.type)}" readonly></label>
        <label class="opb-small">Width<select data-prop="width">${optionMarkup([['half', 'Half'], ['full', 'Full']], field.width)}</select></label>
        <label class="opb-check opb-small"><input data-prop="required" type="checkbox"${field.required ? ' checked' : ''}> Required</label>
        <label class="opb-wide">Help text<input data-prop="help_text" value="${escapeHtml(field.help_text || '')}"></label>
        <label class="opb-wide"${field.type === 'choice' ? '' : ' hidden'}>Product choices <small>Canonical code | display label; reorder or remove lines as needed.</small><textarea data-prop="options_text" placeholder="canonical_code | Display label">${escapeHtml(choiceOptions)}</textarea></label>
        <div class="opb-tools"><button type="button" data-action="field-up">Move up</button><button type="button" data-action="field-down">Move down</button><button type="button" data-action="remove-field">Remove</button></div>
      </div>
    </article>`;
  }

  function renderSections() {
    const container = document.getElementById('opb-sections');
    container.innerHTML = schema.sections.map((section, sectionIndex) => {
      const fields = schema.fields.map((field, index) => ({ field, index })).filter(item => item.field.section_key === section.key);
      return `<article class="opb-section" data-section-index="${sectionIndex}">
        <div class="opb-row">
          <label>Section key<input data-section-prop="key" value="${escapeHtml(section.key)}" pattern="[a-z0-9_]+" required></label>
          <label>Section title<input data-section-prop="label" value="${escapeHtml(section.label || '')}" required></label>
          <label class="opb-wide">Guidance<input data-section-prop="help_text" value="${escapeHtml(section.help_text || '')}"></label>
          <div class="opb-tools"><button type="button" data-action="section-up">Move up</button><button type="button" data-action="section-down">Move down</button><button type="button" data-action="add-field">Add field</button><button type="button" data-action="remove-section">Remove section</button></div>
        </div>
        <div>${fields.length ? fields.map(item => fieldMarkup(item.field, item.index)).join('') : '<div class="opb-empty">No fields in this section yet.</div>'}</div>
      </article>`;
    }).join('');
  }

  function slotMarkup(slot, signerIndex, slotIndex) {
    return `<article class="opb-slot" data-signer-index="${signerIndex}" data-slot-index="${slotIndex}"><div class="opb-row">
      <label>Slot key<input data-slot-prop="key" value="${escapeHtml(slot.key)}" pattern="[a-z0-9_]+" required></label>
      <label class="opb-wide">Label<input data-slot-prop="label" value="${escapeHtml(slot.label || '')}" required></label>
      <label>Type<select data-slot-prop="type">${optionMarkup([['signature', 'Signature'], ['stamp', 'Stamp']], slot.type)}</select></label>
      <label class="opb-check opb-small"><input data-slot-prop="required" type="checkbox"${slot.required ? ' checked' : ''}> Required</label>
      <div class="opb-tools"><button type="button" data-action="remove-slot">Remove slot</button></div>
    </div></article>`;
  }

  function renderSigners() {
    const container = document.getElementById('opb-signers');
    const roleOptions = roles.map(item => [item.key, item.label]);
    container.innerHTML = signers.map((signer, signerIndex) => `<article class="opb-signer" data-signer-index="${signerIndex}">
      <div class="opb-row">
        <label class="opb-wide">Role<select data-signer-prop="role">${optionMarkup(roleOptions, signer.role)}</select></label>
        <label class="opb-check"><input data-signer-prop="required" type="checkbox"${signer.required ? ' checked' : ''}> Required signer</label>
        <div class="opb-tools"><button type="button" data-action="signer-up">Move up</button><button type="button" data-action="signer-down">Move down</button><button type="button" data-action="add-slot">Add slot</button><button type="button" data-action="remove-signer">Remove</button></div>
      </div>
      <div>${signer.slots.length ? signer.slots.map((slot, slotIndex) => slotMarkup(slot, signerIndex, slotIndex)).join('') : '<div class="opb-empty">No signature or stamp slots.</div>'}</div>
    </article>`).join('') || '<div class="opb-empty">Add at least one signer.</div>';
  }

  function render() { renderSections(); renderSigners(); sync(); }
  function move(list, index, delta) { const target = index + delta; if (target < 0 || target >= list.length) return; [list[index], list[target]] = [list[target], list[index]]; }
  function uniqueKey(base, values) { let key = slug(base), index = 2; while (values.includes(key)) key = `${slug(base)}_${index++}`; return key; }

  root.addEventListener('input', event => {
    const sectionNode = event.target.closest('[data-section-index]');
    const fieldNode = event.target.closest('[data-field-index]');
    const signerNode = event.target.closest('[data-signer-index]');
    const slotNode = event.target.closest('[data-slot-index]');
    if (slotNode && event.target.dataset.slotProp) {
      const slot = signers[Number(slotNode.dataset.signerIndex)].slots[Number(slotNode.dataset.slotIndex)];
      slot[event.target.dataset.slotProp] = event.target.type === 'checkbox' ? event.target.checked : event.target.value;
    } else if (fieldNode && event.target.dataset.prop) {
      const field = schema.fields[Number(fieldNode.dataset.fieldIndex)];
      const prop = event.target.dataset.prop;
      field[prop === 'options_text' ? 'options' : prop] = prop === 'options_text'
        ? event.target.value.split(/\r?\n/).map(item => item.trim()).filter(Boolean).map(item => {
          const [code, ...label] = item.split('|');
          return { code: code.trim(), label: label.join('|').trim() || code.trim() };
        })
        : event.target.type === 'checkbox' ? event.target.checked : event.target.value;
    } else if (sectionNode && event.target.dataset.sectionProp) {
      const section = schema.sections[Number(sectionNode.dataset.sectionIndex)];
      const prop = event.target.dataset.sectionProp;
      const oldKey = section.key;
      section[prop] = event.target.value;
      if (prop === 'key') schema.fields.filter(field => field.section_key === oldKey).forEach(field => { field.section_key = event.target.value; });
    } else if (signerNode && event.target.dataset.signerProp) {
      signers[Number(signerNode.dataset.signerIndex)][event.target.dataset.signerProp] = event.target.type === 'checkbox' ? event.target.checked : event.target.value;
    }
    sync();
  });

  root.addEventListener('change', event => {
    if (event.target.dataset.prop === 'data_field_id') {
      const fieldNode = event.target.closest('[data-field-index]');
      const field = schema.fields[Number(fieldNode.dataset.fieldIndex)];
      const canonical = catalogueById.get(String(event.target.value));
      if (!canonical) return;
      Object.assign(field, {
        data_field_id: canonical.id, key: canonical.key, label: canonical.label,
        type: canonical.type, help_text: canonical.help_text || '',
        sensitivity: canonical.sensitivity, masking_policy: canonical.masking_policy,
        reporting_use: canonical.reporting_use, export_allowed: canonical.export_allowed,
        source_type: canonical.source_type,
        options: canonical.type === 'choice'
          ? (canonical.choice_options || []).filter(item => item.active !== false).map(item => ({ code: item.code, label: item.label }))
          : [],
      });
      renderSections();
    }
  });

  root.addEventListener('click', event => {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    const action = button.dataset.action;
    const sectionIndex = Number(button.closest('[data-section-index]')?.dataset.sectionIndex);
    const fieldIndex = Number(button.closest('[data-field-index]')?.dataset.fieldIndex);
    const signerIndex = Number(button.closest('[data-signer-index]')?.dataset.signerIndex);
    const slotIndex = Number(button.closest('[data-slot-index]')?.dataset.slotIndex);
    if (action === 'add-section') {
      const key = uniqueKey('section', schema.sections.map(item => item.key));
      schema.sections.push({ key, label: `Section ${schema.sections.length + 1}`, help_text: '' });
    } else if (action === 'remove-section') {
      if (schema.fields.some(field => field.section_key === schema.sections[sectionIndex].key)) return window.alert('Move or remove this section\'s fields first.');
      if (schema.sections.length === 1) return window.alert('A product requires at least one section.');
      schema.sections.splice(sectionIndex, 1);
    } else if (action === 'section-up') move(schema.sections, sectionIndex, -1);
    else if (action === 'section-down') move(schema.sections, sectionIndex, 1);
    else if (action === 'add-field') {
      const used = new Set(schema.fields.map(item => String(item.data_field_id || '')));
      const usedKeys = new Set(schema.fields.map(item => String(item.key || '')));
      const canonical = inputCatalogue.find(item => !used.has(String(item.id)) && !usedKeys.has(String(item.key)));
      if (!canonical) return window.alert('Every active canonical input field is already attached. Create another field in the catalogue, then reload this page.');
      schema.fields.push({
        data_field_id: canonical.id, key: canonical.key, label: canonical.label,
        type: canonical.type, section_key: schema.sections[sectionIndex].key,
        required: false, width: 'half', help_text: canonical.help_text || '',
        sensitivity: canonical.sensitivity, masking_policy: canonical.masking_policy,
        reporting_use: canonical.reporting_use, export_allowed: canonical.export_allowed,
        source_type: canonical.source_type,
        options: canonical.type === 'choice'
          ? (canonical.choice_options || []).filter(item => item.active !== false).map(item => ({ code: item.code, label: item.label }))
          : [],
      });
    } else if (action === 'remove-field') schema.fields.splice(fieldIndex, 1);
    else if (action === 'field-up' || action === 'field-down') {
      const sectionKey = schema.fields[fieldIndex].section_key;
      const indexes = schema.fields.map((field, index) => field.section_key === sectionKey ? index : -1).filter(index => index >= 0);
      const position = indexes.indexOf(fieldIndex), target = indexes[position + (action === 'field-up' ? -1 : 1)];
      if (target != null) [schema.fields[fieldIndex], schema.fields[target]] = [schema.fields[target], schema.fields[fieldIndex]];
    } else if (action === 'add-signer') {
      const role = roles.find(item => !signers.some(signer => signer.role === item.key))?.key || roles[0]?.key || 'borrower';
      signers.push({ role, required: true, slots: [] });
    } else if (action === 'remove-signer') {
      if (signers.length === 1) return window.alert('A product requires at least one signer.');
      signers.splice(signerIndex, 1);
    } else if (action === 'signer-up') move(signers, signerIndex, -1);
    else if (action === 'signer-down') move(signers, signerIndex, 1);
    else if (action === 'add-slot') {
      const signer = signers[signerIndex];
      const key = uniqueKey('signature', signer.slots.map(item => item.key));
      signer.slots.push({ key, label: 'Signature', type: 'signature', required: signer.required });
    } else if (action === 'remove-slot') signers[signerIndex].slots.splice(slotIndex, 1);
    render();
  });

  schemaInput.form?.addEventListener('submit', event => {
    sync();
    const errors = [];
    if (!schema.sections.length) errors.push('Add at least one section.');
    if (!schema.fields.length) errors.push('Add at least one field.');
    if (!signers.length) errors.push('Add at least one signer.');
    const keys = schema.fields.map(field => slug(field.key));
    if (new Set(keys).size !== keys.length) errors.push('Field variable keys must be unique.');
    const canonicalIds = schema.fields.map(field => String(field.data_field_id || '')).filter(Boolean);
    if (new Set(canonicalIds).size !== canonicalIds.length) errors.push('A canonical data field can appear only once in the application form. Duplicate its PDF box in the alignment builder when the same value must be printed twice.');
    const output = document.getElementById('opb-errors');
    output.hidden = !errors.length; output.textContent = errors.join(' ');
    if (errors.length) { event.preventDefault(); root.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
  });

  normalize();
  render();
})();
