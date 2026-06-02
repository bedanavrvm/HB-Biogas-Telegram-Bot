/**
 * Complaint Management Register - Google Apps Script.
 *
 * Install:
 * 1. Upload/use Complaint_Management_Register_V2.xlsx as a Google Sheet.
 * 2. Extensions -> Apps Script -> paste this file.
 * 3. Run setupComplaintRegisterSupport() once and authorize.
 * 4. Fill real users in the Staff tab.
 * 5. Run Apply Staff permissions only after the bot service account is listed.
 *
 * Sheet structure:
 * Row 1 = visual title banner.
 * Row 2 = bot-readable headers.
 * Row 3+ = complaint rows.
 */
const CM = {
  TAB: 'Complaints Register',
  HEADER_ROW: 2,
  DATA_ROW: 3,
  STAFF_TAB: 'Staff',
  OPTIONS_TAB: 'Dropdown Options',
  DASHBOARD_TAB: 'Complaint Summary',
  STAFF_HEADERS: ['Name', 'Email', 'Role', 'Branch', 'Notify On', 'Editable Columns', 'Active'],
  OPTION_HEADERS: [
    'Branch / Region',
    'JBL Reported By',
    'Complaint Category',
    'Status',
    'Loan Status',
    'Risk Level',
    'Source',
    'Image Flag',
  ],
  OWNER_EMAILS: [],
  STALE_DAYS: 7,
  C: {
    COMPLAINT_ID: 1,
    MESSAGE_ID: 2,
    DATE_REPORTED: 3,
    CUSTOMER_NAME: 4,
    CUSTOMER_ID: 5,
    PHONE: 6,
    REPORTED_BY: 7,
    BRANCH: 8,
    CATEGORY: 9,
    DESCRIPTION: 10,
    RAW_MESSAGE: 11,
    GPS_LINK: 12,
    IMAGE_FLAG: 13,
    SOURCE: 14,
    LOAN_STATUS: 15,
    LOAN_AT_RISK: 16,
    RISK_LEVEL: 17,
    STATUS: 18,
    RESOLUTION: 19,
    DATE_RESOLVED: 20,
    DAYS_OPEN: 21,
  },
  BOT_COLS: [1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14, 21],
  REQUIRED: [3, 4, 6, 10, 18],
  STAFF: {
    NAME: 1,
    EMAIL: 2,
    ROLE: 3,
    BRANCH: 4,
    NOTIFY_ON: 5,
    EDITABLE_COLUMNS: 6,
    ACTIVE: 7,
  },
  ROLE_EDIT_GROUPS: {
    SUPPORT: ['Status', 'Resolution Details', 'Date Resolved'],
    MANAGER: ['Loan Status', 'Loan at Risk', 'Risk Level', 'Status', 'Resolution Details', 'Date Resolved'],
    BRO: ['Resolution Details'],
    IT: ['All'],
    ALL: ['All'],
  },
  COLOURS: {
    Open: { bg: '#FFF8E1', fg: '#E65100' },
    'In Progress': { bg: '#E3F2FD', fg: '#0D47A1' },
    'Waiting for Customer': { bg: '#F3E5F5', fg: '#6A1B9A' },
    Resolved: { bg: '#E8F5E9', fg: '#1B5E20' },
    Closed: { bg: '#ECEFF1', fg: '#37474F' },
  },
  RISK_COLOURS: {
    High: { bg: '#FFEBEE', fg: '#B71C1C' },
    Critical: { bg: '#FCE4EC', fg: '#880E4F' },
  },
};

function onOpen() {
  if (!isComplaintAdminUser_()) return;
  SpreadsheetApp.getUi()
    .createMenu('Complaints')
    .addItem('Search complaints', 'showComplaintSearch')
    .addSeparator()
    .addItem('Apply validation + formatting', 'applyComplaintValidationAndFormatting')
    .addItem('Validate required fields', 'validateComplaintRequired')
    .addItem('Highlight stale open cases', 'highlightStaleComplaints')
    .addItem('Refresh dashboard', 'buildComplaintDashboard')
    .addSeparator()
    .addItem('Send stale digest now', 'sendComplaintStaleDigestNow')
    .addItem('Send status alert for selected row', 'sendComplaintStatusAlertForSelectedRow')
    .addSeparator()
    .addItem('Setup complaint sheet support', 'setupComplaintRegisterSupport')
    .addItem('Create/update Staff tab', 'ensureComplaintStaffSheet')
    .addItem('Validate Staff tab', 'validateComplaintStaffSheetSetup')
    .addSeparator()
    .addItem('Protect bot columns', 'protectComplaintBotColumns')
    .addItem('Apply Staff permissions', 'applyComplaintStaffPermissions')
    .addItem('Remove complaint protections', 'removeComplaintProtections')
    .addItem('Install daily triggers', 'installComplaintTriggers')
    .addToUi();
}

function onEdit(e) {
  if (!e) return;
  const sh = e.range.getSheet();
  const row = e.range.getRow();
  const col = e.range.getColumn();
  if (sh.getName() !== CM.TAB || row < CM.DATA_ROW) return;

  if (col === CM.C.PHONE) normaliseComplaintPhone_(sh, row, col);
  if ([CM.C.CUSTOMER_NAME, CM.C.REPORTED_BY, CM.C.BRANCH].includes(col)) {
    upperCaseComplaintText_(sh, row, col);
  }
  if (col === CM.C.STATUS) {
    maybeSetResolvedDate_(sh, row);
    colourComplaintRow_(sh, row);
    const status = String(e.value || '').trim();
    if (['Resolved', 'Closed'].includes(status)) notifyComplaintStatus_(sh, row, status);
  }
  if (col === CM.C.RISK_LEVEL) colourComplaintRow_(sh, row);
}

function setupComplaintRegisterSupport() {
  if (!requireComplaintAdmin_()) return;
  ensureComplaintDropdownOptionsSheet();
  ensureComplaintStaffSheet(false);
  applyComplaintValidationAndFormatting(false);
  buildComplaintDashboard(false);
  const result = validateComplaintStaffSheetSetup_(false);
  SpreadsheetApp.getUi().alert(
    'Complaint register setup complete.\n\n' +
    complaintStaffValidationSummary_(result) + '\n\n' +
    'Next: replace sample emails in Staff, add the Render service account, then apply staff permissions if required.'
  );
}

function applyComplaintValidationAndFormatting(showAlert) {
  if (!requireComplaintAdmin_()) return;
  showAlert = showAlert !== false;
  const ss = SpreadsheetApp.getActive();
  const sh = ss.getSheetByName(CM.TAB);
  if (!sh) return SpreadsheetApp.getUi().alert('Sheet not found: ' + CM.TAB);
  const options = ensureComplaintDropdownOptionsSheet();
  applyComplaintDataValidation_(sh, options);
  applyComplaintConditionalFormatting_(sh);
  if (showAlert) SpreadsheetApp.getUi().alert('Complaint validation and formatting applied.');
}

function applyComplaintDataValidation_(sh, optionsSheet) {
  const rows = Math.max(sh.getMaxRows() - CM.DATA_ROW + 1, 1);
  applyComplaintOptionsDropdown_(sh, optionsSheet, CM.C.BRANCH, 1);
  applyComplaintOptionsDropdown_(sh, optionsSheet, CM.C.REPORTED_BY, 2);
  applyComplaintOptionsDropdown_(sh, optionsSheet, CM.C.CATEGORY, 3);
  applyComplaintOptionsDropdown_(sh, optionsSheet, CM.C.STATUS, 4);
  applyComplaintOptionsDropdown_(sh, optionsSheet, CM.C.LOAN_STATUS, 5);
  applyComplaintOptionsDropdown_(sh, optionsSheet, CM.C.RISK_LEVEL, 6);
  applyComplaintOptionsDropdown_(sh, optionsSheet, CM.C.SOURCE, 7);
  applyComplaintOptionsDropdown_(sh, optionsSheet, CM.C.IMAGE_FLAG, 8);

  applyComplaintFormulaValidation_(sh, CM.C.PHONE, rows, '=OR(F3="",REGEXMATCH(TO_TEXT(F3),"^254[0-9]{9}$"))', 'Use 254XXXXXXXXX format.');
  applyComplaintFormulaValidation_(sh, CM.C.LOAN_AT_RISK, rows, '=OR(P3="",REGEXMATCH(TO_TEXT(P3),"^[0-9]+(\\.[0-9]{1,2})?$"))', 'Use a non-negative amount.');
  sh.getRange(CM.DATA_ROW, CM.C.DATE_REPORTED, rows, 1).setDataValidation(
    SpreadsheetApp.newDataValidation()
      .requireDateBetween(new Date(2020, 0, 1), new Date(2099, 11, 31))
      .setAllowInvalid(false)
      .build()
  ).setNumberFormat('dd-mmm-yyyy');
  sh.getRange(CM.DATA_ROW, CM.C.DATE_RESOLVED, rows, 1).setDataValidation(
    SpreadsheetApp.newDataValidation()
      .requireDateBetween(new Date(2020, 0, 1), new Date(2099, 11, 31))
      .setAllowInvalid(false)
      .build()
  ).setNumberFormat('dd-mmm-yyyy');
}

function applyComplaintOptionsDropdown_(sh, optionsSheet, targetCol, optionsCol) {
  const rows = Math.max(sh.getMaxRows() - CM.DATA_ROW + 1, 1);
  const source = optionsSheet.getRange(2, optionsCol, Math.max(optionsSheet.getMaxRows() - 1, 1), 1);
  sh.getRange(CM.DATA_ROW, targetCol, rows, 1).setDataValidation(
    SpreadsheetApp.newDataValidation()
      .requireValueInRange(source, true)
      .setAllowInvalid(true)
      .build()
  );
}

function applyComplaintFormulaValidation_(sh, col, rows, formula, helpText) {
  sh.getRange(CM.DATA_ROW, col, rows, 1).setDataValidation(
    SpreadsheetApp.newDataValidation()
      .requireFormulaSatisfied(formula)
      .setHelpText(helpText)
      .setAllowInvalid(false)
      .build()
  );
}

function applyComplaintConditionalFormatting_(sh) {
  const rows = Math.max(sh.getMaxRows() - CM.DATA_ROW + 1, 1);
  const range = sh.getRange(CM.DATA_ROW, 1, rows, complaintLastColumn_());
  const dataA1 = range.getA1Notation();
  const existing = sh.getConditionalFormatRules().filter(rule => {
    return !rule.getRanges().some(r => r.getSheet().getSheetId() === sh.getSheetId() && r.getA1Notation() === dataA1);
  });
  const rules = [];
  Object.keys(CM.COLOURS).forEach(status => {
    const style = CM.COLOURS[status];
    rules.push(SpreadsheetApp.newConditionalFormatRule()
      .whenFormulaSatisfied('=$R3="' + status + '"')
      .setBackground(style.bg)
      .setFontColor(style.fg)
      .setRanges([range])
      .build());
  });
  Object.keys(CM.RISK_COLOURS).forEach(risk => {
    const style = CM.RISK_COLOURS[risk];
    rules.push(SpreadsheetApp.newConditionalFormatRule()
      .whenFormulaSatisfied('=$Q3="' + risk + '"')
      .setBackground(style.bg)
      .setFontColor(style.fg)
      .setRanges([range])
      .build());
  });
  sh.setConditionalFormatRules(existing.concat(rules));
}

function ensureComplaintDropdownOptionsSheet() {
  const ss = SpreadsheetApp.getActive();
  let sh = ss.getSheetByName(CM.OPTIONS_TAB);
  if (!sh) sh = ss.insertSheet(CM.OPTIONS_TAB, ss.getNumSheets());
  sh.getRange(1, 1, 1, CM.OPTION_HEADERS.length)
    .setValues([CM.OPTION_HEADERS])
    .setBackground('#37474F')
    .setFontColor('#FFFFFF')
    .setFontWeight('bold');
  sh.setFrozenRows(1);
  sh.setColumnWidths(1, CM.OPTION_HEADERS.length, 170);
  if (sh.getLastRow() < 2) {
    sh.getRange(2, 1, 6, CM.OPTION_HEADERS.length).setValues([
      ['MURANGA', 'JACKSON NJOROGE', 'System Underperformance', 'Open', 'Performing', 'Low', 'telegram bot', 'TRUE'],
      ['EMBU', 'DICKSON MWANGI', 'System Damage(Tear/Burst)', 'In Progress', 'Non Performing', 'Moderate', 'google sheets', 'FALSE'],
      ['MERU', '', 'Bag Leakage', 'Waiting for Customer', 'Cleared', 'High', 'manual', ''],
      ['NYERI', '', 'Blockage Inlet/Oulet', 'Resolved', 'Unknown', 'Critical', '', ''],
      ['NYANDARUA', '', 'Relocation', 'Closed', '', '', '', ''],
      ['', '', 'Other', '', '', '', '', ''],
    ]);
  }
  return sh;
}

function ensureComplaintStaffSheet(showAlert) {
  if (showAlert !== false && !requireComplaintAdmin_()) return;
  const ss = SpreadsheetApp.getActive();
  let sh = ss.getSheetByName(CM.STAFF_TAB);
  if (!sh) sh = ss.insertSheet(CM.STAFF_TAB, ss.getNumSheets());
  sh.getRange(1, 1, 1, CM.STAFF_HEADERS.length)
    .setValues([CM.STAFF_HEADERS])
    .setBackground('#00695C')
    .setFontColor('#FFFFFF')
    .setFontWeight('bold');
  sh.setFrozenRows(1);
  sh.setColumnWidths(1, CM.STAFF_HEADERS.length, 180);
  if (sh.getLastRow() < 2) {
    sh.getRange(2, 1, 3, CM.STAFF_HEADERS.length).setValues([
      ['IT Admin', 'it@example.com', 'IT', 'All', 'all', 'All', 'Yes'],
      ['Manager', 'manager@example.com', 'Manager', 'All', 'stale_digest,status_resolved,status_closed', 'Risk,Resolution', 'Yes'],
      ['Support Staff', 'support@example.com', 'Support', 'All', 'stale_digest,status_resolved', 'Resolution', 'Yes'],
    ]);
  }
  if (showAlert !== false) SpreadsheetApp.getUi().alert('Staff tab ready. Replace sample emails with real users.');
  return sh;
}

function validateComplaintRequired() {
  if (!requireComplaintAdmin_()) return;
  const sh = SpreadsheetApp.getActive().getSheetByName(CM.TAB);
  const last = sh.getLastRow();
  if (last < CM.DATA_ROW) return SpreadsheetApp.getUi().alert('No complaint rows yet.');
  const headers = complaintHeaders_(sh);
  const data = sh.getRange(CM.DATA_ROW, 1, last - CM.DATA_ROW + 1, complaintLastColumn_()).getValues();
  const issues = [];
  data.forEach((row, index) => {
    if (!row[CM.C.CUSTOMER_NAME - 1] && !row[CM.C.DESCRIPTION - 1]) return;
    const missing = CM.REQUIRED.filter(col => !row[col - 1]).map(col => headers[col - 1]);
    if (missing.length) issues.push('Row ' + (CM.DATA_ROW + index) + ': missing ' + missing.join(', '));
  });
  SpreadsheetApp.getUi().alert(
    issues.length ? issues.slice(0, 20).join('\n') : 'All visible complaint rows have required fields.'
  );
}

function highlightStaleComplaints() {
  if (!requireComplaintAdmin_()) return;
  const rows = collectStaleComplaints_();
  rows.forEach(item => {
    item.sheet.getRange(item.row, 1, 1, complaintLastColumn_()).setBackground('#FFF3CD');
  });
  SpreadsheetApp.getUi().alert(rows.length + ' stale open complaint row(s) highlighted.');
}

function sendComplaintStaleDigestNow() {
  if (!requireComplaintAdmin_()) return;
  const rows = collectStaleComplaints_();
  if (!rows.length) return SpreadsheetApp.getUi().alert('No stale open complaints found.');
  const result = sendComplaintStaleDigest_(rows);
  SpreadsheetApp.getUi().alert(
    result.sent
      ? 'Stale digest sent for ' + rows.length + ' row(s) to ' + result.recipientCount + ' recipient(s).'
      : 'No Staff recipients matched stale_digest.'
  );
}

function sendComplaintStatusAlertForSelectedRow() {
  if (!requireComplaintAdmin_()) return;
  const sh = SpreadsheetApp.getActiveSheet();
  if (sh.getName() !== CM.TAB) return SpreadsheetApp.getUi().alert('Select a row on ' + CM.TAB + '.');
  const row = sh.getActiveRange().getRow();
  if (row < CM.DATA_ROW) return SpreadsheetApp.getUi().alert('Select a complaint data row.');
  const status = String(sh.getRange(row, CM.C.STATUS).getValue() || '').trim();
  if (!status) return SpreadsheetApp.getUi().alert('The selected row has no Status.');
  const result = notifyComplaintStatus_(sh, row, status);
  SpreadsheetApp.getUi().alert(
    result.sent
      ? 'Status alert sent to ' + result.recipientCount + ' recipient(s).'
      : 'No Staff recipients matched this status alert.'
  );
}

function collectStaleComplaints_() {
  const sh = SpreadsheetApp.getActive().getSheetByName(CM.TAB);
  if (!sh) return [];
  const last = sh.getLastRow();
  if (last < CM.DATA_ROW) return [];
  const values = sh.getRange(CM.DATA_ROW, 1, last - CM.DATA_ROW + 1, complaintLastColumn_()).getValues();
  const now = new Date();
  const rows = [];
  values.forEach((row, index) => {
    const status = String(row[CM.C.STATUS - 1] || '').trim();
    const reported = row[CM.C.DATE_REPORTED - 1];
    if (!reported || !(reported instanceof Date) || ['Closed', 'Resolved'].includes(status)) return;
    const days = Math.floor((now - reported) / 86400000);
    if (days >= CM.STALE_DAYS) {
      rows.push({
        sheet: sh,
        row: CM.DATA_ROW + index,
        complaintId: row[CM.C.COMPLAINT_ID - 1],
        customer: row[CM.C.CUSTOMER_NAME - 1],
        branch: row[CM.C.BRANCH - 1],
        category: row[CM.C.CATEGORY - 1],
        status,
        days,
      });
    }
  });
  return rows;
}

function notifyComplaintStatus_(sh, row, status) {
  const event = 'status_' + normalizeComplaintToken_(status).replace(/\s+/g, '_');
  const branch = sh.getRange(row, CM.C.BRANCH).getValue();
  const recipients = uniqueComplaintEmails_(getComplaintStaffEmails_({
    event,
    roles: ['Manager', 'Support', 'IT', 'All'],
    branch,
  }));
  if (!recipients.length) return { sent: false, recipientCount: 0 };

  const subject = '[COMPLAINT ' + String(status).toUpperCase() + '] ' + sh.getRange(row, CM.C.CUSTOMER_NAME).getValue();
  const body = [
    'Complaint status updated.',
    '',
    'Status: ' + status,
    'Complaint ID: ' + sh.getRange(row, CM.C.COMPLAINT_ID).getValue(),
    'Customer: ' + sh.getRange(row, CM.C.CUSTOMER_NAME).getValue(),
    'Phone: ' + sh.getRange(row, CM.C.PHONE).getValue(),
    'Branch: ' + branch,
    'Category: ' + sh.getRange(row, CM.C.CATEGORY).getValue(),
    '',
    'View sheet: ' + SpreadsheetApp.getActive().getUrl(),
  ].join('\n');
  MailApp.sendEmail({ to: recipients.join(','), subject, body });
  return { sent: true, recipientCount: recipients.length };
}

function sendComplaintStaleDigest_(rows) {
  const recipients = uniqueComplaintEmails_(getComplaintStaffEmails_({
    event: 'stale_digest',
    roles: ['Manager', 'Support', 'IT', 'All'],
    branch: 'All',
  }));
  if (!recipients.length) return { sent: false, recipientCount: 0 };
  const bodyRows = rows.map(item =>
    'Row ' + item.row + ': ' + item.customer + ' - ' + item.branch + ' - ' + item.days + ' days - ' + item.status
  );
  MailApp.sendEmail({
    to: recipients.join(','),
    subject: '[STALE COMPLAINTS] ' + rows.length + ' open complaint(s) pending',
    body: ['The following complaints are stale:', '', ...bodyRows, '', SpreadsheetApp.getActive().getUrl()].join('\n'),
  });
  return { sent: true, recipientCount: recipients.length };
}

function buildComplaintDashboard(showAlert) {
  if (showAlert !== false && !requireComplaintAdmin_()) return;
  const ss = SpreadsheetApp.getActive();
  const src = ss.getSheetByName(CM.TAB);
  if (!src) return;
  let dash = ss.getSheetByName(CM.DASHBOARD_TAB);
  if (!dash) dash = ss.insertSheet(CM.DASHBOARD_TAB, 0);
  dash.clearContents().clearFormats();
  dash.getRange('A1:G1').merge().setValue('Complaint Dashboard - ' + Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'dd MMM yyyy HH:mm'))
    .setBackground('#1A7744').setFontColor('#FFFFFF').setFontWeight('bold').setHorizontalAlignment('center');
  const metrics = [
    ['Total', '=COUNTA(\'' + CM.TAB + '\'!D3:D1000)'],
    ['Open', '=COUNTIF(\'' + CM.TAB + '\'!R:R,"Open")'],
    ['In Progress', '=COUNTIF(\'' + CM.TAB + '\'!R:R,"In Progress")'],
    ['Waiting', '=COUNTIF(\'' + CM.TAB + '\'!R:R,"Waiting for Customer")'],
    ['Resolved', '=COUNTIF(\'' + CM.TAB + '\'!R:R,"Resolved")'],
    ['Closed', '=COUNTIF(\'' + CM.TAB + '\'!R:R,"Closed")'],
    ['High/Critical Risk', '=COUNTIF(\'' + CM.TAB + '\'!Q:Q,"High")+COUNTIF(\'' + CM.TAB + '\'!Q:Q,"Critical")'],
  ];
  metrics.forEach((item, index) => {
    dash.getRange(3, index + 1).setValue(item[0]).setBackground('#1565C0').setFontColor('#FFFFFF').setFontWeight('bold').setHorizontalAlignment('center');
    dash.getRange(4, index + 1).setFormula(item[1]).setBackground('#E3F2FD').setFontWeight('bold').setHorizontalAlignment('center');
  });
  dash.setColumnWidths(1, 7, 130);
  if (showAlert !== false) SpreadsheetApp.getUi().alert('Complaint dashboard refreshed.');
}

function showComplaintSearch() {
  if (!requireComplaintAdmin_()) return;
  const html = HtmlService.createHtmlOutput(`
<style>
body{font-family:Arial,sans-serif;padding:14px;font-size:13px}
input{width:100%;padding:8px;margin:8px 0;border:1px solid #ccc;border-radius:4px}
button{width:100%;padding:9px;background:#1565C0;color:white;border:0;border-radius:4px;font-weight:bold}
td,th{padding:5px;border-bottom:1px solid #eee;font-size:11px}
table{width:100%;border-collapse:collapse;margin-top:8px}
th{background:#1565C0;color:white;text-align:left}
</style>
<b>Search complaints</b>
<input id="q" placeholder="Name, phone, complaint ID, category" onkeydown="if(event.key==='Enter')go()">
<button onclick="go()">Search</button>
<div id="out"></div>
<script>
function go(){
  const q=document.getElementById('q').value.trim();
  if(!q)return;
  document.getElementById('out').innerHTML='Searching...';
  google.script.run.withSuccessHandler(r=>document.getElementById('out').innerHTML=r)
    .withFailureHandler(e=>document.getElementById('out').innerText='Error: '+e.message)
    .runComplaintSearch(q);
}
document.getElementById('q').focus();
<\/script>
`).setWidth(460).setHeight(360);
  SpreadsheetApp.getUi().showModalDialog(html, 'Search complaints');
}

function runComplaintSearch(query) {
  if (!isComplaintAdminUser_()) return '<i>Access denied.</i>';
  const sh = SpreadsheetApp.getActive().getSheetByName(CM.TAB);
  const last = sh.getLastRow();
  if (last < CM.DATA_ROW) return '<i>No complaint rows yet.</i>';
  const q = String(query || '').toLowerCase();
  const values = sh.getRange(CM.DATA_ROW, 1, last - CM.DATA_ROW + 1, complaintLastColumn_()).getValues();
  const hits = [];
  values.forEach((row, i) => {
    const fields = [CM.C.COMPLAINT_ID, CM.C.MESSAGE_ID, CM.C.CUSTOMER_NAME, CM.C.PHONE, CM.C.CATEGORY, CM.C.DESCRIPTION];
    if (fields.some(col => String(row[col - 1] || '').toLowerCase().includes(q))) {
      hits.push({ row: CM.DATA_ROW + i, id: row[0], name: row[3], phone: row[5], status: row[17] });
    }
  });
  if (!hits.length) return '<i>No results.</i>';
  sh.getRange(hits[0].row, 1).activate();
  const rows = hits.slice(0, 20).map(h => '<tr><td>' + h.row + '</td><td>' + h.id + '</td><td>' + h.name + '</td><td>' + h.phone + '</td><td>' + h.status + '</td></tr>').join('');
  return '<b>' + hits.length + ' result(s)</b><table><tr><th>Row</th><th>ID</th><th>Name</th><th>Phone</th><th>Status</th></tr>' + rows + '</table>';
}

function protectComplaintBotColumns() {
  if (!requireComplaintAdmin_()) return;
  const sh = SpreadsheetApp.getActive().getSheetByName(CM.TAB);
  if (!sh) return;
  const currentUser = Session.getEffectiveUser().getEmail();
  const rowCount = Math.max(sh.getMaxRows() - CM.DATA_ROW + 1, 1);
  CM.BOT_COLS.forEach(col => {
    const protection = sh.getRange(CM.DATA_ROW, col, rowCount, 1).protect().setDescription('Complaint bot-managed column');
    protection.removeEditors(protection.getEditors());
    protection.addEditor(currentUser);
    protection.setWarningOnly(true);
  });
  SpreadsheetApp.getUi().alert('Bot-managed columns are now warning-protected.');
}

function applyComplaintStaffPermissions() {
  if (!requireComplaintAdmin_()) return;
  const sh = SpreadsheetApp.getActive().getSheetByName(CM.TAB);
  if (!sh) return;
  ensureComplaintStaffSheet(false);
  const map = complaintStaffPermissionMap_();
  const existing = sh.getProtections(SpreadsheetApp.ProtectionType.RANGE)
    .filter(p => String(p.getDescription() || '').startsWith('Complaint permission:'));
  existing.forEach(p => p.remove());
  const headers = complaintHeaders_(sh);
  const currentUser = Session.getEffectiveUser().getEmail();
  let count = 0;
  headers.forEach((header, index) => {
    const col = index + 1;
    if (CM.BOT_COLS.includes(col)) return;
    const editors = uniqueComplaintEmails_((map[col] || []).concat(currentUser));
    if (!editors.length) return;
    const protection = sh.getRange(CM.DATA_ROW, col, Math.max(sh.getMaxRows() - CM.DATA_ROW + 1, 1), 1)
      .protect()
      .setDescription('Complaint permission: ' + header);
    protection.removeEditors(protection.getEditors());
    protection.addEditors(editors);
    if (protection.canDomainEdit()) protection.setDomainEdit(false);
    count++;
  });
  protectComplaintBotColumns();
  SpreadsheetApp.getUi().alert('Staff permissions applied to ' + count + ' column(s).');
}

function removeComplaintProtections() {
  if (!requireComplaintAdmin_()) return;
  const protections = SpreadsheetApp.getActive().getProtections(SpreadsheetApp.ProtectionType.RANGE)
    .filter(p => String(p.getDescription() || '').startsWith('Complaint'));
  protections.forEach(p => p.remove());
  SpreadsheetApp.getUi().alert('Removed ' + protections.length + ' complaint protection(s).');
}

function installComplaintTriggers() {
  if (!requireComplaintAdmin_()) return;
  ScriptApp.getProjectTriggers()
    .filter(t => ['sendComplaintStaleDigestNow', 'buildComplaintDashboard'].includes(t.getHandlerFunction()))
    .forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('sendComplaintStaleDigestNow').timeBased().everyDays(1).atHour(8).create();
  ScriptApp.newTrigger('buildComplaintDashboard').timeBased().everyHours(1).create();
  SpreadsheetApp.getUi().alert('Complaint triggers installed.');
}

function maybeSetResolvedDate_(sh, row) {
  const status = String(sh.getRange(row, CM.C.STATUS).getValue() || '').trim();
  const resolvedCell = sh.getRange(row, CM.C.DATE_RESOLVED);
  if (['Resolved', 'Closed'].includes(status) && !resolvedCell.getValue()) {
    resolvedCell.setValue(new Date()).setNumberFormat('dd-mmm-yyyy');
  }
}

function colourComplaintRow_(sh, row) {
  const status = String(sh.getRange(row, CM.C.STATUS).getValue() || '').trim();
  const risk = String(sh.getRange(row, CM.C.RISK_LEVEL).getValue() || '').trim();
  const style = CM.RISK_COLOURS[risk] || CM.COLOURS[status];
  const range = sh.getRange(row, 1, 1, complaintLastColumn_());
  if (style) {
    range.setBackground(style.bg);
    sh.getRange(row, CM.C.STATUS).setFontColor(style.fg).setFontWeight('bold');
  }
}

function normaliseComplaintPhone_(sh, row, col) {
  const cell = sh.getRange(row, col);
  const raw = String(cell.getValue() || '').replace(/\D/g, '');
  if (!raw) return;
  let next = raw;
  if (raw.startsWith('0') && raw.length === 10) next = '254' + raw.slice(1);
  else if ((raw.startsWith('7') || raw.startsWith('1')) && raw.length === 9) next = '254' + raw;
  if (next !== raw) cell.setValue(next);
}

function upperCaseComplaintText_(sh, row, col) {
  const cell = sh.getRange(row, col);
  const value = String(cell.getValue() || '').trim().replace(/\s+/g, ' ');
  if (value) cell.setValue(value.toUpperCase());
}

function validateComplaintStaffSheetSetup() {
  if (!requireComplaintAdmin_()) return;
  SpreadsheetApp.getUi().alert(complaintStaffValidationSummary_(validateComplaintStaffSheetSetup_(false)));
}

function validateComplaintStaffSheetSetup_(showAlert) {
  const sh = SpreadsheetApp.getActive().getSheetByName(CM.STAFF_TAB);
  const result = { activeRows: 0, invalidEmails: 0 };
  if (!sh || sh.getLastRow() < 2) return result;
  const rows = sh.getRange(2, 1, sh.getLastRow() - 1, CM.STAFF_HEADERS.length).getValues();
  rows.forEach(row => {
    if (normalizeComplaintToken_(row[CM.STAFF.ACTIVE - 1]) !== 'yes') return;
    result.activeRows++;
    if (!isComplaintEmail_(row[CM.STAFF.EMAIL - 1])) result.invalidEmails++;
  });
  if (showAlert) SpreadsheetApp.getUi().alert(complaintStaffValidationSummary_(result));
  return result;
}

function complaintStaffValidationSummary_(result) {
  return 'Active Staff rows: ' + result.activeRows + '\nInvalid emails: ' + result.invalidEmails;
}

function getComplaintStaffEmails_(options) {
  const sh = SpreadsheetApp.getActive().getSheetByName(CM.STAFF_TAB);
  if (!sh || sh.getLastRow() < 2) return [];
  const opts = options || {};
  const roles = (opts.roles || []).map(normalizeComplaintToken_);
  const branch = normalizeComplaintToken_(opts.branch || 'All');
  const event = normalizeComplaintToken_(opts.event || 'all');
  return sh.getRange(2, 1, sh.getLastRow() - 1, CM.STAFF_HEADERS.length).getValues()
    .filter(row => normalizeComplaintToken_(row[CM.STAFF.ACTIVE - 1]) === 'yes')
    .filter(row => isComplaintEmail_(row[CM.STAFF.EMAIL - 1]))
    .filter(row => complaintRoleMatches_(row[CM.STAFF.ROLE - 1], roles))
    .filter(row => complaintBranchMatches_(row[CM.STAFF.BRANCH - 1], branch))
    .filter(row => complaintEventMatches_(row[CM.STAFF.NOTIFY_ON - 1], event))
    .map(row => String(row[CM.STAFF.EMAIL - 1]).trim());
}

function complaintStaffPermissionMap_() {
  const sh = SpreadsheetApp.getActive().getSheetByName(CM.STAFF_TAB);
  const register = SpreadsheetApp.getActive().getSheetByName(CM.TAB);
  if (!sh || !register || sh.getLastRow() < 2) return {};
  const headers = complaintHeaders_(register);
  const map = {};
  sh.getRange(2, 1, sh.getLastRow() - 1, CM.STAFF_HEADERS.length).getValues().forEach(row => {
    if (normalizeComplaintToken_(row[CM.STAFF.ACTIVE - 1]) !== 'yes') return;
    const email = String(row[CM.STAFF.EMAIL - 1] || '').trim();
    if (!isComplaintEmail_(email)) return;
    editableComplaintColumns_(row[CM.STAFF.EDITABLE_COLUMNS - 1], headers).forEach(col => {
      if (!map[col]) map[col] = [];
      map[col].push(email);
    });
  });
  return map;
}

function editableComplaintColumns_(value, headers) {
  const columns = new Set();
  String(value || '').split(',').map(s => s.trim()).filter(Boolean).forEach(token => {
    expandComplaintEditableToken_(token, headers).forEach(col => columns.add(col));
  });
  return Array.from(columns);
}

function expandComplaintEditableToken_(token, headers) {
  const normalized = normalizeEditableComplaintToken_(token);
  if (!normalized) return [];
  if (normalized === 'ALL') return headers.map((_, index) => index + 1);
  if (normalized === 'RISK') return [CM.C.LOAN_STATUS, CM.C.LOAN_AT_RISK, CM.C.RISK_LEVEL];
  if (normalized === 'RESOLUTION') return [CM.C.STATUS, CM.C.RESOLUTION, CM.C.DATE_RESOLVED];
  if (CM.ROLE_EDIT_GROUPS[normalized]) return editableComplaintColumns_(CM.ROLE_EDIT_GROUPS[normalized].join(','), headers);
  if (/^\d+$/.test(normalized)) return [Number(normalized)];
  const idx = headers.map(normalizeEditableComplaintToken_).indexOf(normalized);
  if (idx >= 0) return [idx + 1];
  return [];
}

function requireComplaintAdmin_() {
  if (isComplaintAdminUser_()) return true;
  SpreadsheetApp.getUi().alert('Access denied. Only the owner or active IT staff can use this menu.');
  return false;
}

function isComplaintAdminUser_() {
  const email = currentComplaintUserEmail_();
  if (!email) return false;
  if (CM.OWNER_EMAILS.map(normalizeComplaintToken_).includes(normalizeComplaintToken_(email))) return true;
  if (normalizeComplaintToken_(email) === normalizeComplaintToken_(spreadsheetComplaintOwnerEmail_())) return true;
  return getComplaintStaffEmails_({ roles: ['IT', 'All'], event: 'all', branch: 'All' })
    .map(normalizeComplaintToken_)
    .includes(normalizeComplaintToken_(email));
}

function currentComplaintUserEmail_() {
  const candidates = [];
  try { candidates.push(Session.getActiveUser().getEmail()); } catch (err) {}
  try { candidates.push(Session.getEffectiveUser().getEmail()); } catch (err) {}
  return String(candidates.find(email => String(email || '').trim()) || '').trim();
}

function spreadsheetComplaintOwnerEmail_() {
  try {
    return DriveApp.getFileById(SpreadsheetApp.getActive().getId()).getOwner().getEmail();
  } catch (err) {
    return '';
  }
}

function complaintRoleMatches_(value, roles) {
  if (!roles.length) return true;
  const role = normalizeComplaintToken_(value || 'All');
  return role === 'all' || roles.includes(role);
}

function complaintBranchMatches_(value, branch) {
  const staffBranch = normalizeComplaintToken_(value || 'All');
  return staffBranch === 'all' || branch === 'all' || staffBranch === branch;
}

function complaintEventMatches_(value, event) {
  const events = String(value || '').split(',').map(normalizeComplaintToken_).filter(Boolean);
  return events.includes('all') || events.includes(event);
}

function complaintHeaders_(sh) {
  return sh.getRange(CM.HEADER_ROW, 1, 1, complaintLastColumn_()).getValues()[0].map(h => String(h || '').trim());
}

function complaintLastColumn_() {
  return Math.max.apply(null, Object.keys(CM.C).map(key => CM.C[key]));
}

function normalizeComplaintToken_(value) {
  return String(value || '').trim().toLowerCase().replace(/\s+/g, ' ');
}

function normalizeEditableComplaintToken_(value) {
  return String(value || '').trim().toUpperCase().replace(/\s+/g, ' ');
}

function uniqueComplaintEmails_(values) {
  const seen = {};
  return (values || []).map(email => String(email || '').trim()).filter(email => {
    const key = email.toLowerCase();
    if (!key || seen[key]) return false;
    seen[key] = true;
    return true;
  });
}

function isComplaintEmail_(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(value || '').trim());
}
