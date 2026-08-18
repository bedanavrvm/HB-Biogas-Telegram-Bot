(function () {
  'use strict';

  const productInput = document.getElementById('id_product_definition');
  const fieldInput = document.getElementById('id_condition_field');
  const operatorInput = document.getElementById('id_condition_operator');
  const source = document.getElementById('origination-condition-fields-data');
  if (!productInput || !fieldInput || !operatorInput || !document.getElementById('id_condition_value') || !source) return;

  let fieldsByProduct = {};
  try { fieldsByProduct = JSON.parse(source.textContent || '{}'); } catch (_) { return; }
  const escapeHtml = value => { const node = document.createElement('div'); node.textContent = String(value ?? ''); return node.innerHTML; };
  const optionValue = option => typeof option === 'object' ? option.code : option;
  const optionLabel = option => typeof option === 'object' ? (option.label || option.code) : option;
  const valueInput = () => document.getElementById('id_condition_value');
  const currentValue = () => valueInput()?.value || '';

  function fields() {
    return fieldsByProduct[String(productInput.value || '')] || [];
  }

  function selectedField() {
    return fields().find(item => item.key === fieldInput.value);
  }

  function updateValueControl() {
    const field = selectedField();
    const previous = currentValue();
    const input = valueInput();
    if (!input) return;
    const valueRow = input.closest('.form-row, .fieldBox, p');
    const needsValue = !['truthy', 'falsy'].includes(operatorInput.value);
    if (valueRow) valueRow.hidden = !needsValue || !field;
    if (!field) return;
    if (field.type === 'boolean') {
      input.outerHTML = `<select name="condition_value" id="id_condition_value"><option value="">Choose answer</option><option value="true">Yes</option><option value="false">No</option></select>`;
    } else if (field.type === 'choice' && Array.isArray(field.options) && field.options.length) {
      const options = field.options.map(option => {
        const value = optionValue(option);
        return `<option value="${escapeHtml(value)}">${escapeHtml(optionLabel(option))}</option>`;
      }).join('');
      input.outerHTML = `<select name="condition_value" id="id_condition_value"><option value="">Choose answer</option>${options}</select>`;
    } else if (input.tagName !== 'INPUT') {
      input.outerHTML = '<input type="text" name="condition_value" id="id_condition_value">';
    }
    const refreshed = document.getElementById('id_condition_value');
    if (refreshed) refreshed.value = previous;
  }

  function updateFields() {
    const previous = fieldInput.value;
    const options = fields().map(item => (
      `<option value="${escapeHtml(item.key)}">${escapeHtml(item.label)} (${escapeHtml(item.key)})</option>`
    )).join('');
    fieldInput.innerHTML = '<option value="">Always include</option>' + options;
    fieldInput.value = fields().some(item => item.key === previous) ? previous : '';
    updateValueControl();
  }

  productInput.addEventListener('change', updateFields);
  fieldInput.addEventListener('change', updateValueControl);
  operatorInput.addEventListener('change', updateValueControl);
  updateFields();
})();
