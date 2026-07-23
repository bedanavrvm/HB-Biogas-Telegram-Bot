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
    finalDecisionBadge,
    fmt,
    fmtDate,
    invoiceFileSizeLabel,
    jblBadge,
    renderWarnings,
    stageBadge,
    summaryGrid,
    validateInvoiceFile,
  };
})();
