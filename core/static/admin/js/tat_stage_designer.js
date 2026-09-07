(function () {
  'use strict';

  const form = document.getElementById('tat-stage-form');
  if (!form) return;

  const list = document.getElementById('tat-stage-list');
  const source = document.getElementById('tat-stage-source');
  const output = document.getElementById('tat-stages-json');
  const roleSource = document.getElementById('tat-role-options');
  let stages = [];
  let roleOptions = [];

  try {
    stages = JSON.parse(source.value || '[]');
  } catch (_error) {
    stages = [];
  }
  try {
    roleOptions = JSON.parse(roleSource?.textContent || '[]');
  } catch (_error) {
    roleOptions = [];
  }

  function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, character => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[character]));
  }

  function roleChoices(selectedRole) {
    const selected = String(selectedRole || '').trim().toUpperCase();
    const choices = [...roleOptions];
    if (selected && !choices.some(item => String(item.value).toUpperCase() === selected)) {
      // Preserve a legacy role already stored on this version without making
      // free-text role creation the normal editing path.
      choices.push({ value: selected, label: `${selected} (legacy)` });
    }
    return choices.map(item => {
      const value = String(item.value || '').trim().toUpperCase();
      return `<option value="${esc(value)}"${value === selected ? ' selected' : ''}>${esc(item.label || value)}</option>`;
    }).join('');
  }

  function sync() {
    output.value = JSON.stringify(stages);
  }

  function collect() {
    stages = [...list.querySelectorAll('.tat-stage-card')].map(card => ({
      key: card.querySelector('[data-key]').value,
      label: card.querySelector('[data-label]').value,
      role: card.querySelector('[data-role]').value,
      column: card.querySelector('[data-column]').value,
      kind: card.querySelector('[data-kind]').value,
      options: card.querySelector('[data-options]').value.split('\n').map(value => value.trim()).filter(Boolean),
      auto_timestamp_key: card.querySelector('[data-auto]').value,
      requires_signature_certificate: card.querySelector('[data-signature]').checked,
    }));
    sync();
  }

  function render() {
    list.innerHTML = stages.map((stage, index) => `
      <article class="tat-stage-card" data-index="${index}">
        <div class="tat-stage-order">
          <button type="button" data-up aria-label="Move up">↑</button>
          <button type="button" data-down aria-label="Move down">↓</button>
        </div>
        <label>Stable key<input data-key value="${esc(stage.key)}" required></label>
        <label>Label<input data-label value="${esc(stage.label)}" required></label>
        <label>Responsible role<select data-role required>${roleChoices(stage.role)}</select></label>
        <label>Sheet column<input data-column type="number" min="1" value="${esc(stage.column)}" required></label>
        <label>Control<select data-kind><option value="timestamp"${stage.kind !== 'dropdown' ? ' selected' : ''}>Timestamp</option><option value="dropdown"${stage.kind === 'dropdown' ? ' selected' : ''}>Dropdown</option></select></label>
        <label>Dropdown options<textarea data-options rows="3" placeholder="One per line">${esc((stage.options || []).join('\n'))}</textarea><span>Auto timestamp key</span><input data-auto value="${esc(stage.auto_timestamp_key)}"><span><input data-signature type="checkbox"${stage.requires_signature_certificate ? ' checked' : ''}> Signature certificate</span></label>
        <button class="tat-stage-remove" type="button" data-remove>Remove</button>
      </article>
    `).join('');
    sync();
  }

  list.addEventListener('input', collect);
  list.addEventListener('change', collect);
  list.addEventListener('click', event => {
    const card = event.target.closest('.tat-stage-card');
    if (!card) return;
    collect();
    const index = Number(card.dataset.index);
    if (event.target.matches('[data-up]') && index > 0) {
      [stages[index - 1], stages[index]] = [stages[index], stages[index - 1]];
    } else if (event.target.matches('[data-down]') && index < stages.length - 1) {
      [stages[index + 1], stages[index]] = [stages[index], stages[index + 1]];
    } else if (event.target.matches('[data-remove]')) {
      stages.splice(index, 1);
    } else {
      return;
    }
    render();
  });
  document.getElementById('tat-add-stage').addEventListener('click', () => {
    collect();
    stages.push({
      key: '', label: '', role: '', column: '', kind: 'timestamp', options: [],
      auto_timestamp_key: '', requires_signature_certificate: false,
    });
    render();
  });
  form.addEventListener('submit', collect);
  render();
}());
