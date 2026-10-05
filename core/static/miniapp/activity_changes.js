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
  const blank = value => value === null || value === undefined || String(value).trim() === '';
  const normalized = value => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
  function textHtml(value) {
    const text = String(value);
    if (text.length <= 160) return escape(text);
    return `<details class="activity-long-text"><summary><span class="activity-text-excerpt">${escape(text.slice(0, 100))}… </span><span class="activity-read-more">Read more</span><span class="activity-read-less">Show less</span></summary><div>${escape(text)}</div></details>`;
  }
  function changeHtml(change, context) {
    const old = valueText(change.old_value);
    const next = valueText(change.new_value);
    const label = change.label || 'Value';
    const previous = change.previous_recorded !== false && !blank(change.old_value);
    if (blank(change.new_value)) return previous ? `<div class="activity-change">${escape(label)} removed</div>` : '';
    // A status transition is the outcome of an action, not a correction.
    const outcome = /^(status|decision|installation_status|commissioning_status)$/.test(change.field || '') ||
      (change.field === 'value' && labels[String(change.new_value)]);
    if (normalized(context.detail) === normalized(next) ||
        (outcome && normalized(context.title).includes(normalized(next)))) return '';
    return `<div class="activity-change"><span class="activity-change-label">${escape(label)}:</span> ${previous && !outcome ? `${textHtml(old)} <span aria-label="changed to">→</span> ` : ''}${textHtml(next)}</div>`;
  }
  function html(changes, context = {}) {
    if (!Array.isArray(changes) || !changes.length) return '';
    const seen = new Set();
    const rows = changes.filter(change => {
      if (change.previous_recorded !== false && change.old_value === change.new_value) return false;
      const key = JSON.stringify([change.field || change.label, change.old_value, change.new_value]);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    }).map(change => changeHtml(change, context)).filter(Boolean);
    if (!rows.length) return '';
    return `<div class="activity-changes">${rows.slice(0, 2).join('')}${rows.length > 2 ? `<details class="activity-more"><summary>More changes (${rows.length - 2})</summary>${rows.slice(2).join('')}</details>` : ''}</div>`;
  }
  function append(node, changes, context) {
    const markup = html(changes, context);
    if (markup && node) node.insertAdjacentHTML('beforeend', markup);
  }
  window.MiniAppActivityChanges = {html, append, valueText, textHtml};
})();
