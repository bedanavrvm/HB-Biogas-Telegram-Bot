(function () {
  'use strict';

  const utils = window.MiniAppUtils || {};
  const escapeHtml = utils.escapeHtml || function (value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (character) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character];
    });
  };

  function fmt(value) {
    return value || '-';
  }

  function fmtDate(value) {
    if (!value) return '-';
    let date;
    if (/^\d{4}-\d{2}-\d{2}$/.test(String(value))) {
      const parts = String(value).split('-').map(Number);
      date = new Date(parts[0], parts[1] - 1, parts[2]);
    } else {
      date = new Date(value);
    }
    if (Number.isNaN(date.getTime())) return String(value);
    const day = String(date.getDate()).padStart(2, '0');
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return `${day}-${months[date.getMonth()]}-${date.getFullYear()}`;
  }

  function stageBadge(farmer) {
    const stage = farmer.pipeline_stage || 1;
    const labels = ['-', 'Awaiting JBL', 'JBL Visited', 'Credit Set', 'Ordered', '', '', 'Invoiced'];
    const styles = ['', 'badge-grey', 'badge-blue', 'badge-orange', 'badge-green', '', '', 'badge-green'];
    return `<span class="badge ${styles[stage] || ''}">${escapeHtml(labels[stage] || 'Stage ' + stage)}</span>`;
  }

  function creditBadge(farmer) {
    if (!farmer.credit_decision) return '';
    const map = { Approved: 'badge-green', Rejected: 'badge-red', Deferred: 'badge-orange', Pending: 'badge-grey', 'Exemption Approved': 'badge-green' };
    return `<span class="badge ${map[farmer.credit_decision] || 'badge-grey'}">${escapeHtml(farmer.credit_decision)}</span>`;
  }

  function finalDecisionBadge(farmer) {
    if (!farmer.final_decision) return '';
    const map = { Approved: 'badge-green', Rejected: 'badge-red', Deferred: 'badge-orange', 'Under Review': 'badge-blue' };
    return `<span class="badge ${map[farmer.final_decision] || 'badge-grey'}">Final: ${escapeHtml(farmer.final_decision)}</span>`;
  }

  function jblBadge(farmer) {
    if (!farmer.jbl_visit_status) return '';
    const status = String(farmer.jbl_visit_status);
    const cls = status.startsWith('Approved') ? 'badge-green'
      : status === 'Awaiting Analysis' ? 'badge-blue'
      : status.includes('Reject') || status.includes('Cancel') ? 'badge-red'
      : 'badge-orange';
    return `<span class="badge ${cls}">${escapeHtml(status)}</span>`;
  }

  function summaryGrid(items) {
    return items.map(function (item) {
      return `
      <div class="batch-summary-item">
        <strong>${escapeHtml(item.value)}</strong>
        <span>${escapeHtml(item.label)}</span>
      </div>
    `;
    }).join('');
  }

  function renderWarnings(container, warnings) {
    if (!container) return;
    if (!warnings || !warnings.length) {
      container.innerHTML = '';
      return;
    }
    container.innerHTML = `<div class="batch-warning-list">${warnings.map(function (warning) {
      return `<div class="batch-warning">${escapeHtml(warning.message || warning)}</div>`;
    }).join('')}</div>`;
  }

  function batchClientRows(farmers, blockedById) {
    const blocked = blockedById || {};
    if (!farmers.length) return '<div class="empty-state"><div class="es-title">No clients</div></div>';
    return farmers.map(function (farmer) {
      const missing = blocked[farmer.id] || [];
      const invoice = farmer.invoice_number ? `Invoice ${escapeHtml(farmer.invoice_number)}` : 'No invoice';
      return `
        <div class="batch-client-row">
          <div class="name">${escapeHtml(farmer.customer_name || 'Unnamed client')}</div>
          <div class="meta">ID ${escapeHtml(farmer.national_id || '-')} | ${escapeHtml(farmer.primary_phone || '-')} | ${escapeHtml(farmer.county || '-')}</div>
          <div class="meta">${escapeHtml(invoice)}${farmer.invoice_amount ? ' | KES ' + escapeHtml(farmer.invoice_amount) : ''}</div>
          ${missing.length ? `<div class="batch-warning" style="margin-top:8px;">Missing: ${missing.map(escapeHtml).join(', ')}</div>` : ''}
        </div>
      `;
    }).join('');
  }

  function invoiceResultsSummary(result) {
    const matchedCount = result.matched_count || 0;
    const totalParsed = result.total_parsed || 0;
    const candidateCount = result.candidate_count ?? 'unknown';
    return result.ok
      ? `Matched ${matchedCount} of ${totalParsed} parsed invoice(s). Candidates in selected batch: ${candidateCount}.`
      : `${result.error || 'Invoice upload needs review.'} Parsed: ${totalParsed}. Matched: ${matchedCount}. Candidates in selected batch: ${candidateCount}.`;
  }

  function invoiceResultRows(result) {
    return (result.results || []).map(function (row) {
      const matched = row.status === 'Matched';
      const customerName = escapeHtml(row.customer_name || '-');
      const invoiceNo = escapeHtml(row.invoice_no || '-');
      const status = escapeHtml(row.status || 'Unmatched');
      const reason = row.reason ? `<div style="font-size:11px; color:#7f1d1d; margin-top:2px;">${escapeHtml(row.reason)}</div>` : '';
      const parsed = !matched ? `
          <div style="font-size:11px; color:#475569; margin-top:4px; line-height:1.45;">
            Parsed ID: <strong>${escapeHtml(row.parsed_national_id || '-')}</strong> |
            Phone: <strong>${escapeHtml(row.parsed_phone || '-')}</strong> |
            Selected order: <strong>${escapeHtml(row.selected_order_number || result.order_number || '-')}</strong><br>
            Batch candidates: ${escapeHtml(row.batch_candidate_count ?? '-')} |
            ID matches: ${escapeHtml(row.batch_id_match_count ?? '-')} |
            Phone matches: ${escapeHtml(row.batch_phone_match_count ?? '-')} |
            Name matches: ${escapeHtml(row.batch_name_match_count ?? '-')}
          </div>` : '';
      const outside = (row.outside_batch_matches || []).length ? `
          <div style="font-size:11px; color:#7c2d12; margin-top:4px; line-height:1.45;">
            Possible match outside selected order:<br>
            ${(row.outside_batch_matches || []).map(function (match) {
              return `${escapeHtml(match.customer_name || '-')} | ID ${escapeHtml(match.national_id || '-')} - ${escapeHtml(match.primary_phone || '-')} | Order ${escapeHtml(match.order_number || '-')} | Status ${escapeHtml(match.status || '-')}`;
            }).join('<br>')}
          </div>` : '';
      return `
        <div style="font-size:13px; padding:6px 8px; background:${matched ? '#f0fdf4' : '#fef2f2'}; border-radius:6px; border:1px solid ${matched ? '#bbf7d0' : '#fecaca'};">
          <div style="display:flex; justify-content:space-between; align-items:center; gap:8px;">
            <span style="font-weight:600; color:#1e293b;">${customerName}</span>
            <div style="display:flex; align-items:center; gap:6px;">
              <span style="font-size:11px; font-family:monospace; color:#64748b;">${invoiceNo}</span>
              <span class="badge ${matched ? 'badge-green' : 'badge-red'}" style="font-size:10px; padding:2px 6px;">${status}</span>
            </div>
          </div>
          ${reason}
          ${parsed}
          ${outside}
        </div>`;
    }).join('');
  }

  function invoiceFileSizeLabel(bytes) {
    if (!bytes && bytes !== 0) return 'unknown size';
    if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
    return `${(bytes / 1024).toFixed(1)} KB`;
  }

  function validateInvoiceFile(file, maxBytes, maxMb) {
    if (!file) return 'Select a PDF file first.';
    if (!String(file.name || '').toLowerCase().endsWith('.pdf')) return 'Only PDF files are supported.';
    if (file.size > maxBytes) {
      return `This PDF is ${invoiceFileSizeLabel(file.size)}. Maximum supported size is ${maxMb} MB.`;
    }
    return '';
  }

  window.PortalMiniAppHelpers = {
    creditBadge,
    batchClientRows,
    finalDecisionBadge,
    fmt,
    fmtDate,
    invoiceResultRows,
    invoiceResultsSummary,
    invoiceFileSizeLabel,
    jblBadge,
    renderWarnings,
    stageBadge,
    summaryGrid,
    validateInvoiceFile,
  };
})();
