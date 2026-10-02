/* Shared presentation of server-allowlisted, immutable activity comparisons. */
(() => {
  'use strict';
  const escape = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const labels = {'LOAN-JAWABU':'Loan – Jawabu', CASH:'Cash', not_installed:'Not installed', installed:'Installed', not_commissioned:'Not commissioned', commissioned:'Commissioned', in_review:'Awaiting review', review_complete:'Reviewed', awaiting_scan:'Awaiting signed scan', completed:'Completed', pending:'Pending', approved:'Approved', returned:'Returned', draft:'Draft', cancelled:'Cancelled'};
  function valueText(value) {
    if (value === null || value === undefined || value === '') return 'Not set';
    if (typeof value === 'boolean') return value ? 'Yes' : 'No';
    const text = String(value);
    if (labels[text]) return labels[text];
    if (/^\d{4}-\d{2}-\d{2}(?:T.*)?$/.test(text)) {
      const date = new Date(text.length === 10 ? `${text}T00:00:00+03:00` : text);
      if (!Number.isNaN(date.getTime())) return new Intl.DateTimeFormat('en-GB', {timeZone:'Africa/Nairobi',day:'2-digit',month:'short',year:'numeric',...(text.length > 10 ? {hour:'2-digit',minute:'2-digit',hour12:false} : {})}).format(date);
    }
    return text;
  }
  function changeHtml(change) {
    const old = change.previous_recorded === false ? 'Previous value not recorded' : valueText(change.old_value);
    const next = valueText(change.new_value);
    const heading = escape(change.label || 'Value');
    if (old.length + next.length > 160 || /\n/.test(old + next)) {
      return `<details class="activity-change-long"><summary>${heading}</summary><div><strong>Old</strong><span>${escape(old)}</span></div><div><strong>New</strong><span>${escape(next)}</span></div></details>`;
    }
    return `<div class="activity-change"><strong>${heading}:</strong> <span>${escape(old)}</span> <span aria-label="changed to">→</span> <span>${escape(next)}</span></div>`;
  }
  function html(changes) {
    if (!Array.isArray(changes) || !changes.length) return '';
    const rows = changes.map(changeHtml);
    return `<div class="activity-changes">${rows.slice(0,3).join('')}${rows.length > 3 ? `<details><summary>Show all ${rows.length} changes</summary>${rows.slice(3).join('')}</details>` : ''}</div>`;
  }
  function append(node, changes) {
    const markup = html(changes);
    if (markup) node.insertAdjacentHTML('beforeend', markup);
  }
  window.MiniAppActivityChanges = {html, append, valueText};
})();
