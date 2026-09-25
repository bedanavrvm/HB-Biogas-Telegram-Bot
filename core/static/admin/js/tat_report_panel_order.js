document.addEventListener('DOMContentLoaded', () => {
  const select = document.getElementById('id_report_panel_order');
  if (!select) return;
  const controls = document.createElement('div');
  controls.className = 'tat-panel-order-controls';
  for (const [label, direction] of [['Move up', -1], ['Move down', 1]]) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.setAttribute('aria-label', `${label} the selected report panel`);
    button.addEventListener('click', () => {
      const option = select.selectedOptions[0];
      if (!option) return;
      const neighbour = direction < 0 ? option.previousElementSibling : option.nextElementSibling;
      if (!neighbour) return;
      if (direction < 0) select.insertBefore(option, neighbour);
      else select.insertBefore(neighbour, option);
      option.focus?.();
      select.focus();
    });
    controls.append(button);
  }
  select.after(controls);
  select.form?.addEventListener('submit', () => {
    for (const option of select.options) option.selected = true;
  });
});
