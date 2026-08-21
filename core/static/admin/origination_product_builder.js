(function () {
  'use strict';

  const root = document.getElementById('origination-product-builder');
  const schemaInput = document.getElementById('id_form_schema');
  const signersInput = document.getElementById('id_signer_rules');
  if (!root || !schemaInput || !signersInput) return;

  const supportingDocument = root.dataset.builderKind === 'supporting-document';
  const requiresFields = root.dataset.requireFields !== 'false';
  const requiresSigners = root.dataset.requireSigners !== 'false';

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
    const usedIds = new Set(schema.fields.filter(item => item !== field).map(item => String(item.data_field_id || '')));
    const usedKeys = new Set(schema.fields.filter(item => item !== field).map(item => String(item.key || '')));
    const available = inputCatalogue.filter(item => (
      String(item.id) === selectedId
      || (!usedIds.has(String(item.id)) && !usedKeys.has(String(item.key)))
    ));
    const legacy = !catalogueById.has(selectedId) && field.key
      ? `<option value="" selected>Legacy: ${escapeHtml(field.label || field.key)} (${escapeHtml(field.key)})</option>`
      : '<option value="">Choose a canonical field</option>';
    return legacy + available.map(item => {
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
    if (!supportingDocument) schema.identity_contract = 'applicant_v1';
    if (!schema.sections.length) {
      const seen = new Set();
      schema.fields.forEach(field => {
        const [key, label] = legacySection(field.key);
        field.section_key ||= key;
        if (!seen.has(key)) { schema.sections.push({ key, label, help_text: '' }); seen.add(key); }
      });
      if (!schema.sections.length) schema.sections.push({ key: 'application', label: 'Application', help_text: 'Product application details' });
    }
    const normalizedSectionKeys = [];
    schema.sections.forEach((section, index) => {
      const previousKey = section.key;
      const nextKey = uniqueKey(section.label || `section_${index + 1}`, normalizedSectionKeys);
      section.key = nextKey;
      normalizedSectionKeys.push(nextKey);
      schema.fields.filter(field => field.section_key === previousKey).forEach(field => { field.section_key = nextKey; });
    });
    const firstSection = schema.sections[0]?.key || 'application';
    schema.fields.forEach(field => {
      field.section_key ||= firstSection;
      field.type ||= 'text';
      field.width ||= field.type === 'textarea' ? 'full' : 'half';
      field.help_text ||= '';
      field.options = Array.isArray(field.options) ? field.options : [];
      field.validation = field.validation && typeof field.validation === 'object' ? field.validation : {};
    });
    signers = signers.filter(item => item && typeof item === 'object').map(item => ({
      role: item.role || 'borrower',
      required: item.required !== false,
      identity_fields: item.identity_fields && typeof item.identity_fields === 'object' ? { ...item.identity_fields } : {},
      slots: (Array.isArray(item.slots) ? item.slots : []).map(slotItem => {
        const slot = typeof slotItem === 'string' ? { key: slotItem } : { ...(slotItem || {}) };
        return {
          key: slot.key || 'signature', label: slot.label || String(slot.key || 'signature').replaceAll('_', ' '),
          type: slot.type || item.slot_type || 'signature', required: slot.required ?? item.required !== false,
        };
      }),
    }));
    if (requiresSigners && !signers.length) signers.push({ role: 'borrower', required: true, identity_fields: {}, slots: [{ key: 'signature', label: 'Borrower signature', type: 'signature', required: true }] });
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
    const validation = field.validation || {};
    const validationMarkup = ['money', 'number'].includes(field.type)
      ? `<label>Minimum<input type="number" step="any" data-validation-prop="min" value="${escapeHtml(validation.min ?? '')}"></label><label>Maximum<input type="number" step="any" data-validation-prop="max" value="${escapeHtml(validation.max ?? '')}"></label>`
      : field.type === 'date'
        ? `<label>Earliest date<input type="date" data-validation-prop="min_date" value="${escapeHtml(validation.min_date || '')}"></label><label>Latest date<input type="date" data-validation-prop="max_date" value="${escapeHtml(validation.max_date || '')}"></label>`
        : ['text', 'textarea', 'phone', 'national_id'].includes(field.type)
          ? `<label>Minimum length<input type="number" min="0" step="1" data-validation-prop="min_length" value="${escapeHtml(validation.min_length ?? '')}"></label><label>Maximum length<input type="number" min="1" step="1" data-validation-prop="max_length" value="${escapeHtml(validation.max_length ?? '')}"></label><label class="opb-wide">Format pattern <small>Optional regular expression, limited to 200 characters.</small><input data-validation-prop="pattern" maxlength="200" value="${escapeHtml(validation.pattern || '')}"></label>`
          : '';
    return `<article class="opb-field" data-field-index="${fieldIndex}">
      <div class="opb-row">
        <label class="opb-wide">Canonical data field<select data-prop="data_field_id">${canonicalOptions(field)}</select></label>
        <label>Stable key<input data-prop="key" value="${escapeHtml(field.key)}" readonly></label>
        <label>Label<input data-prop="label" value="${escapeHtml(field.label || '')}" required></label>
        <label>Control<input value="${escapeHtml(fieldTypes.find(item => item[0] === field.type)?.[1] || field.type)}" readonly></label>
        <label class="opb-small">Width<select data-prop="width">${optionMarkup([['half', 'Half'], ['full', 'Full']], field.width)}</select></label>
        <label class="opb-check opb-small"><input data-prop="required" type="checkbox"${field.required ? ' checked' : ''}> Required</label>
        <label class="opb-wide">Help text<input data-prop="help_text" value="${escapeHtml(field.help_text || '')}"></label>
        ${validationMarkup}
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
          <label>Section key<input data-section-prop="key" value="${escapeHtml(section.key)}" readonly aria-readonly="true"><small>Generated automatically from the section title.</small></label>
          <label>Section title<input data-section-prop="label" value="${escapeHtml(section.label || '')}" placeholder="Applicant" required><small>Use Applicant for the person applying; Borrower is reserved for legal signing.</small></label>
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
    const identityOptions = (kind, selected) => {
      const allowed = kind === 'phone' ? ['phone'] : kind === 'national_id' ? ['national_id', 'text'] : ['text', 'textarea'];
      return '<option value="">Choose canonical field</option>' + inputCatalogue.filter(item => allowed.includes(item.type)).map(item => `<option value="${escapeHtml(item.key)}"${item.key === selected ? ' selected' : ''}>${escapeHtml(item.label)} · ${escapeHtml(item.key)}</option>`).join('');
    };
    container.innerHTML = signers.map((signer, signerIndex) => `<article class="opb-signer" data-signer-index="${signerIndex}">
      <div class="opb-row">
        <label class="opb-wide">Role<select data-signer-prop="role">${optionMarkup(roleOptions, signer.role)}</select></label>
        <label class="opb-check"><input data-signer-prop="required" type="checkbox"${signer.required ? ' checked' : ''}> Required signer</label>
        <label>Signer name field<select data-signer-identity="name">${identityOptions('name', signer.identity_fields?.name || '')}</select></label>
        <label>OTP phone field<select data-signer-identity="phone">${identityOptions('phone', signer.identity_fields?.phone || '')}</select></label>
        <label>National ID field<select data-signer-identity="national_id">${identityOptions('national_id', signer.identity_fields?.national_id || '')}</select></label>
        <div class="opb-tools"><button type="button" data-action="signer-up">Move up</button><button type="button" data-action="signer-down">Move down</button><button type="button" data-action="add-slot">Add slot</button><button type="button" data-action="remove-signer">Remove</button></div>
      </div>
      <div>${signer.slots.length ? signer.slots.map((slot, slotIndex) => slotMarkup(slot, signerIndex, slotIndex)).join('') : '<div class="opb-empty">No signature or stamp slots.</div>'}</div>
    </article>`).join('') || '<div class="opb-empty">Add at least one signer.</div>';
  }

  function render() { renderSections(); renderSigners(); sync(); }
  function move(list, index, delta) { const target = index + delta; if (target < 0 || target >= list.length) return; [list[index], list[target]] = [list[target], list[index]]; }
  function uniqueKey(base, values) { let key = slug(base), index = 2; while (values.includes(key)) key = `${slug(base)}_${index++}`; return key; }

  function sectionKeyForTitle(title, sectionIndex) {
    const used = schema.sections
      .filter((_, index) => index !== sectionIndex)
      .map(item => item.key);
    return uniqueKey(title || `section_${sectionIndex + 1}`, used);
  }

  let fieldPickerSectionIndex = 0;
  const advancedCatalogueUrl = document.querySelector('.opb-actions a[href*="originationdatafield"]')?.href || '#';
  const fieldPicker = document.createElement('dialog');
  fieldPicker.className = 'opb-field-picker';
  fieldPicker.setAttribute('aria-labelledby', 'opb-field-picker-title');
  fieldPicker.innerHTML = `<form method="dialog" class="opb-field-picker-card">
    <header><div><p>Add to form</p><h2 id="opb-field-picker-title">Choose or create a canonical field</h2></div><button type="button" class="opb-picker-close" aria-label="Close">&times;</button></header>
    <div class="opb-field-picker-grid">
      <section>
        <h3>Use an existing field</h3>
        <p>Search the global catalogue. Fields already attached to this form are excluded.</p>
        <label>Search<input type="search" data-picker-search placeholder="Name, key, category, or alias"></label>
        <label>Canonical field<select data-picker-existing size="7"></select></label>
        <p class="opb-picker-empty" data-picker-empty hidden></p>
        <button type="button" class="button" data-picker-add>Add selected field</button>
      </section>
      <section>
        <h3>Create a new canonical field</h3>
        <p>Use this only when the catalogue has no field with the same business meaning.</p>
        <div class="opb-picker-form">
          <label>Label<input data-picker-label required maxlength="160" placeholder="Applicant national ID"></label>
          <label>Stable key<input data-picker-key required maxlength="120" pattern="[a-z0-9_]+" placeholder="applicant_national_id"></label>
          <label>Type<select data-picker-type>
            <option value="text">Short text</option><option value="textarea">Long text</option>
            <option value="number">Number</option><option value="money">Money</option>
            <option value="date">Date</option><option value="phone">Phone</option>
            <option value="national_id">National ID</option><option value="choice">Choice</option>
            <option value="boolean">Yes / No</option><option value="branch">Governed branch</option>
            <option value="county">Governed county</option><option value="sub_county">Governed sub-county</option>
          </select></label>
          <label>Sensitivity<select data-picker-sensitivity>
            <option value="pii">Personal data (PII)</option><option value="financial">Financial</option>
            <option value="internal">Internal</option><option value="restricted">Restricted</option>
            <option value="public">Public</option>
          </select></label>
          <label class="opb-picker-wide">Category<input data-picker-category maxlength="80" value="Application"></label>
          <label class="opb-picker-wide" data-picker-options-wrap hidden>Choice options <small>One per line: stable_code | Display label</small><textarea data-picker-options placeholder="employed | Employed"></textarea></label>
        </div>
        <p class="opb-picker-error" data-picker-error hidden></p>
        <button type="button" class="button" data-picker-create>Create and add field</button>
        <a class="opb-secondary-link" href="${escapeHtml(advancedCatalogueUrl)}" target="_blank" rel="noopener">Open advanced field catalogue</a>
      </section>
    </div>
  </form>`;
  document.body.appendChild(fieldPicker);

  const picker = selector => fieldPicker.querySelector(selector);
  const usedFieldIds = () => new Set(schema.fields.map(item => String(item.data_field_id || '')));
  const usedFieldKeys = () => new Set(schema.fields.map(item => String(item.key || '')));
  const availableFields = (query = '') => {
    const usedIds = usedFieldIds(), usedKeys = usedFieldKeys();
    const normalized = String(query || '').trim().toLowerCase();
    return inputCatalogue.filter(item => {
      if (usedIds.has(String(item.id)) || usedKeys.has(String(item.key))) return false;
      const haystack = [item.label, item.key, item.category, ...(item.aliases || [])].join(' ').toLowerCase();
      return !normalized || haystack.includes(normalized);
    });
  };
  const renderFieldPicker = () => {
    const matches = availableFields(picker('[data-picker-search]').value);
    picker('[data-picker-existing]').innerHTML = matches.map(item => (
      `<option value="${escapeHtml(item.id)}">${escapeHtml(item.category || 'Application')} · ${escapeHtml(item.label)} · ${escapeHtml(item.key)}</option>`
    )).join('');
    picker('[data-picker-add]').disabled = !matches.length;
    const empty = picker('[data-picker-empty]');
    empty.hidden = Boolean(matches.length);
    empty.textContent = inputCatalogue.length
      ? 'Every active input field is already on this form, or no field matches the search. Create a genuinely new canonical field here when needed.'
      : 'No active user-input fields exist yet. Create the first canonical field here.';
  };
  const appendCanonicalField = canonical => {
    if (!canonical) throw new Error('Choose a canonical field.');
    if (usedFieldIds().has(String(canonical.id)) || usedFieldKeys().has(String(canonical.key))) {
      throw new Error(`${canonical.label} is already attached to this form.`);
    }
    schema.fields.push({
      data_field_id: canonical.id, key: canonical.key, label: canonical.label,
      type: canonical.type, section_key: schema.sections[fieldPickerSectionIndex].key,
      required: false, width: canonical.type === 'textarea' ? 'full' : 'half', help_text: canonical.help_text || '',
      validation: {}, sensitivity: canonical.sensitivity, masking_policy: canonical.masking_policy,
      reporting_use: canonical.reporting_use, export_allowed: canonical.export_allowed,
      source_type: canonical.source_type,
      options: canonical.type === 'choice'
        ? (canonical.choice_options || []).filter(item => item.active !== false).map(item => ({ code: item.code, label: item.label }))
        : [],
    });
    render();
    fieldPicker.close();
  };
  const openFieldPicker = sectionIndex => {
    fieldPickerSectionIndex = sectionIndex;
    picker('[data-picker-search]').value = '';
    picker('[data-picker-label]').value = '';
    picker('[data-picker-key]').value = '';
    delete picker('[data-picker-key]').dataset.touched;
    picker('[data-picker-type]').value = 'text';
    picker('[data-picker-sensitivity]').value = 'pii';
    picker('[data-picker-category]').value = 'Application';
    picker('[data-picker-options]').value = '';
    picker('[data-picker-options-wrap]').hidden = true;
    picker('[data-picker-error]').hidden = true;
    renderFieldPicker();
    fieldPicker.showModal();
    (availableFields().length ? picker('[data-picker-search]') : picker('[data-picker-label]')).focus();
  };

  picker('[data-picker-search]').addEventListener('input', renderFieldPicker);
  picker('[data-picker-add]').addEventListener('click', () => {
    const canonical = catalogueById.get(String(picker('[data-picker-existing]').value));
    try { appendCanonicalField(canonical); } catch (error) {
      const output = picker('[data-picker-error]'); output.textContent = error.message; output.hidden = false;
    }
  });
  picker('[data-picker-label]').addEventListener('input', event => {
    const keyInput = picker('[data-picker-key]');
    if (!keyInput.dataset.touched) keyInput.value = slug(event.target.value);
  });
  picker('[data-picker-key]').addEventListener('input', event => { event.target.dataset.touched = '1'; });
  picker('[data-picker-type]').addEventListener('change', event => {
    picker('[data-picker-options-wrap]').hidden = event.target.value !== 'choice';
  });
  picker('[data-picker-create]').addEventListener('click', async event => {
    const output = picker('[data-picker-error]'); output.hidden = true;
    const label = picker('[data-picker-label]').value.trim();
    const key = picker('[data-picker-key]').value.trim();
    const type = picker('[data-picker-type]').value;
    if (!label || !/^[a-z0-9_]+$/.test(key)) {
      output.textContent = 'Enter a label and a lowercase stable key using letters, numbers, or underscores.';
      output.hidden = false; return;
    }
    const body = {
      label, key, type,
      sensitivity: picker('[data-picker-sensitivity]').value,
      category: picker('[data-picker-category]').value.trim() || 'Application',
      choice_options: type === 'choice'
        ? picker('[data-picker-options]').value.split(/\r?\n/).map(item => item.trim()).filter(Boolean).map(item => {
          const [code, ...label] = item.split('|');
          return { code: slug(code), label: label.join('|').trim() || code.trim() };
        })
        : [],
    };
    try {
      event.currentTarget.disabled = true;
      const response = await fetch(root.dataset.createFieldUrl, {
        method: 'POST', credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': document.querySelector('input[name="csrfmiddlewaretoken"]')?.value || '',
        },
        body: JSON.stringify(body),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) throw new Error(data.error || 'The canonical field could not be created.');
      if (!catalogueById.has(String(data.field.id))) {
        catalogue.push(data.field); inputCatalogue.push(data.field); catalogueById.set(String(data.field.id), data.field);
      }
      appendCanonicalField(data.field);
    } catch (error) {
      output.textContent = error.message; output.hidden = false;
    } finally { event.currentTarget.disabled = false; }
  });
  picker('.opb-picker-close').addEventListener('click', () => fieldPicker.close());
  fieldPicker.querySelector('form').addEventListener('submit', event => event.preventDefault());
  fieldPicker.addEventListener('click', event => { if (event.target === fieldPicker) fieldPicker.close(); });

  root.addEventListener('input', event => {
    const sectionNode = event.target.closest('[data-section-index]');
    const fieldNode = event.target.closest('[data-field-index]');
    const signerNode = event.target.closest('[data-signer-index]');
    const slotNode = event.target.closest('[data-slot-index]');
    if (slotNode && event.target.dataset.slotProp) {
      const slot = signers[Number(slotNode.dataset.signerIndex)].slots[Number(slotNode.dataset.slotIndex)];
      slot[event.target.dataset.slotProp] = event.target.type === 'checkbox' ? event.target.checked : event.target.value;
    } else if (fieldNode && event.target.dataset.validationProp) {
      const field = schema.fields[Number(fieldNode.dataset.fieldIndex)];
      field.validation ||= {};
      const prop = event.target.dataset.validationProp;
      if (event.target.value === '') delete field.validation[prop];
      else field.validation[prop] = event.target.value;
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
      const sectionIndex = Number(sectionNode.dataset.sectionIndex);
      const section = schema.sections[sectionIndex];
      const prop = event.target.dataset.sectionProp;
      const oldKey = section.key;
      if (prop === 'label') {
        section.label = event.target.value;
        section.key = sectionKeyForTitle(section.label, sectionIndex);
        schema.fields.filter(field => field.section_key === oldKey).forEach(field => { field.section_key = section.key; });
        const keyInput = sectionNode.querySelector('[data-section-prop="key"]');
        if (keyInput) keyInput.value = section.key;
      } else if (prop !== 'key') section[prop] = event.target.value;
    } else if (signerNode && event.target.dataset.signerProp) {
      signers[Number(signerNode.dataset.signerIndex)][event.target.dataset.signerProp] = event.target.type === 'checkbox' ? event.target.checked : event.target.value;
    } else if (signerNode && event.target.dataset.signerIdentity) {
      const signer = signers[Number(signerNode.dataset.signerIndex)];
      signer.identity_fields ||= {};
      if (event.target.value) signer.identity_fields[event.target.dataset.signerIdentity] = event.target.value;
      else delete signer.identity_fields[event.target.dataset.signerIdentity];
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
      const label = `Section ${schema.sections.length + 1}`;
      const key = uniqueKey(label, schema.sections.map(item => item.key));
      schema.sections.push({ key, label, help_text: '' });
    } else if (action === 'remove-section') {
      if (schema.fields.some(field => field.section_key === schema.sections[sectionIndex].key)) return window.alert('Move or remove this section\'s fields first.');
      if (schema.sections.length === 1) return window.alert(`A ${supportingDocument ? 'document' : 'product'} requires at least one section.`);
      schema.sections.splice(sectionIndex, 1);
    } else if (action === 'section-up') move(schema.sections, sectionIndex, -1);
    else if (action === 'section-down') move(schema.sections, sectionIndex, 1);
    else if (action === 'add-field') {
      openFieldPicker(sectionIndex);
    } else if (action === 'remove-field') schema.fields.splice(fieldIndex, 1);
    else if (action === 'field-up' || action === 'field-down') {
      const sectionKey = schema.fields[fieldIndex].section_key;
      const indexes = schema.fields.map((field, index) => field.section_key === sectionKey ? index : -1).filter(index => index >= 0);
      const position = indexes.indexOf(fieldIndex), target = indexes[position + (action === 'field-up' ? -1 : 1)];
      if (target != null) [schema.fields[fieldIndex], schema.fields[target]] = [schema.fields[target], schema.fields[fieldIndex]];
    } else if (action === 'add-signer') {
      const role = roles.find(item => !signers.some(signer => signer.role === item.key))?.key || roles[0]?.key || 'borrower';
      signers.push({ role, required: true, identity_fields: {}, slots: [] });
    } else if (action === 'remove-signer') {
      if (requiresSigners && signers.length === 1) return window.alert(`A ${supportingDocument ? 'document' : 'product'} requires at least one signer.`);
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
    if (requiresFields && !schema.sections.length) errors.push('Add at least one section.');
    if (requiresFields && !schema.fields.length) errors.push('Add at least one canonical field.');
    if (requiresSigners && !signers.length) errors.push('Add at least one signer.');
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

  if (supportingDocument) {
    const roleInput = document.getElementById('id_document_role');
    const note = root.querySelector('[data-supporting-builder-note]');
    const content = root.querySelector('[data-supporting-builder-content]');
    const updateSupportingVisibility = () => {
      // The product-scoped supporting-document wizard has no role selector:
      // its context already guarantees it is a supporting PDF.
      const isSupporting = !roleInput || roleInput.value === 'supporting';
      if (note) note.hidden = isSupporting;
      if (content) content.hidden = !isSupporting;
      root.classList.toggle('opb-builder-muted', !isSupporting);
    };
    roleInput?.addEventListener('change', updateSupportingVisibility);
    updateSupportingVisibility();
  }
})();
