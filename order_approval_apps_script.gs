/**
 * Config.gs — single source of truth for column layout.
 * Row 1 = visual title banner (ignored by bot).
 * Row 2 = header row (bot reads this).
 * Row 3+ = data rows.
 */
const CFG = {
  TAB:         'Orders',
  HEADER_ROW:  2,
  DATA_ROW:    3,

  /* Column positions — 1-based, matching Order_Approval_Form.xlsx */
  C: {
    DATE_VISITED:  1,  /* A */
    NAME:          2,  /* B */
    BRANCH:        3,  /* C */
    ID_NUMBER:     4,  /* D  ← dedup key */
    PRIMARY:       5,  /* E */
    SECONDARY:     6,  /* F */
    COUNTY:        7,  /* G */
    LANDMARK:      8,  /* H */
    VISITED_BY:    9,  /* I */
    HB_STAFF:     10,  /* J */
    DEP_HB:       11,  /* K */
    DEP_JBL:      12,  /* L */
    COMMENT:      13,  /* M */
    IMAB:         14,  /* N */
    CUSTOMER_NO:  15,  /* O */
    CREDIT:       16,  /* P */
    DECISION:     17,  /* Q */
    MEDIA_URLS:   18,  /* R  ← bot-managed */
    SOURCE_TAB:   19,  /* S  ← bot-managed */
    SOURCE_ROW:   20,  /* T  ← bot-managed */
  },

  /* Columns the Telegram bot owns — show warning before manual edit */
  BOT_COLS: [18, 19, 20],

  /* Minimum columns needed for a row to count as "complete" */
  REQUIRED: [1, 2, 4, 5, 7],   /* Date, Name, ID, Primary, County */

  /* FINAL DECISION → row highlight colour */
  COLOURS: {
    'Approved':     { bg:'#E8F5E9', accent:'#1B5E20' },
    'Rejected':     { bg:'#FFEBEE', accent:'#B71C1C' },
    'Hold':         { bg:'#FFF8E1', accent:'#E65100' },
    'Under Review': { bg:'#E3F2FD', accent:'#0D47A1' },
  },

  /* Days before a pending row is flagged as stale */
  STALE_DAYS: 7,

  /*
   * Staff notification directory.
   *
   * Create a sheet/tab named "Staff" with these columns:
   * Name | Email | Role | Branch | Notify On | Active
   *
   * Role examples: BRO, Manager, Back-office, All
   * Branch examples: Embu, Muranga, All
   * Notify On examples: decision_approved, decision_rejected, stale_digest, all
   * Active examples: Yes, No
   */
  STAFF_TAB: 'Staff',
  STAFF_HEADERS: ['Name', 'Email', 'Role', 'Branch', 'Notify On', 'Active'],
  STAFF: {
    NAME:       1,
    EMAIL:      2,
    ROLE:       3,
    BRANCH:     4,
    NOTIFY_ON:  5,
    ACTIVE:     6,
  },
};

/** onOpen: build the custom menu. */
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Orders')
    .addItem('Search by ID / Name / Phone', 'showSearch')
    .addSeparator()
    .addItem('Highlight pending decisions', 'highlightPending')
    .addItem('Highlight stale rows', 'highlightStale')
    .addItem('Validate required fields', 'validateRequired')
    .addSeparator()
    .addItem('Refresh dashboard', 'buildDashboard')
    .addSeparator()
    .addItem('Create/update Staff tab', 'ensureStaffSheet')
    .addSeparator()
    .addItem('Protect bot columns', 'protectBotCols')
    .addItem('Install daily triggers', 'installTriggers')
    .addToUi();
}

/**
 * onEdit: fires on every cell change.
 * Keeps logic fast — no external calls here.
 */
function onEdit(e) {
  if (!e) return;
  const sh  = e.range.getSheet();
  const row = e.range.getRow();
  const col = e.range.getColumn();
  if (sh.getName() !== CFG.TAB) return;
  if (row < CFG.DATA_ROW)       return;

  /* 1. Auto-fill DATE VISITED on first touch of any data column */
  autoDate(sh, row, col);

  /* 2. Duplicate ID alert */
  if (col === CFG.C.ID_NUMBER) checkDuplicate(sh, row, e.value);

  /* 3. Normalise phone numbers */
  if (col === CFG.C.PRIMARY || col === CFG.C.SECONDARY)
    normalisePhone(sh, row, col);

  /* 4. Title-case customer name */
  if (col === CFG.C.NAME) titleCase(sh, row, col);

  /* 5. Colour the row when a decision is recorded */
  if (col === CFG.C.DECISION || col === CFG.C.CREDIT)
    colourRow(sh, row);

  /* 6. Email notification on final Approved / Rejected */
  if (col === CFG.C.DECISION) {
    const dec = String(e.value).trim();
    if (dec === 'Approved' || dec === 'Rejected')
      notifyDecision(sh, row, dec);
  }
}

/** Install time-based triggers (run once from the menu). */
function installTriggers() {
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));
  const ss = SpreadsheetApp.getActive();

  /* Daily stale-row digest at 08:00 */
  ScriptApp.newTrigger('dailyStaleScan')
    .timeBased().everyDays(1).atHour(8).create();

  /* Dashboard refresh every hour */
  ScriptApp.newTrigger('buildDashboard')
    .timeBased().everyHours(1).create();

  SpreadsheetApp.getUi().alert(
    'Triggers installed:\n' +
    '  Daily stale scan at 08:00\n' +
    '  Dashboard refresh every hour'
  );
}

/** Fill DATE VISITED with today when a new row is first touched. */
function autoDate(sh, row, editedCol) {
  if (CFG.BOT_COLS.includes(editedCol)) return;   /* ignore bot writes */
  const cell = sh.getRange(row, CFG.C.DATE_VISITED);
  if (cell.getValue() !== '') return;
  cell.setValue(new Date()).setNumberFormat('DD/MM/YYYY');
}

/**
 * Warn when ID_NUMBER already exists in another row.
 * Highlights the duplicate cell yellow and adds a note.
 */
function checkDuplicate(sh, row, newId) {
  if (!newId) return;
  const last = sh.getLastRow();
  if (last < CFG.DATA_ROW) return;

  const ids = sh.getRange(CFG.DATA_ROW, CFG.C.ID_NUMBER,
                           last - CFG.DATA_ROW + 1, 1).getValues().flat();
  const dupes = [];
  ids.forEach((id, i) => {
    const r = i + CFG.DATA_ROW;
    if (r !== row && String(id).trim() === String(newId).trim()) dupes.push(r);
  });

  const cell = sh.getRange(row, CFG.C.ID_NUMBER);
  if (dupes.length > 0) {
    cell.setBackground('#FFF176')
        .setNote('Duplicate ID — also in row(s): ' + dupes.join(', '));
    SpreadsheetApp.getUi().alert(
      'Duplicate ID Detected\n\n' +
      'ID "' + newId + '" already exists in row(s): ' + dupes.join(', ') + '\n\n' +
      'Verify this is not the same customer before saving.'
    );
  } else {
    cell.setBackground(null).clearNote();
  }
}

/**
 * Normalise Kenyan phone numbers to 07XXXXXXXX format.
 * Handles +254..., 254..., and 07... inputs.
 */
function normalisePhone(sh, row, col) {
  const cell = sh.getRange(row, col);
  const raw  = String(cell.getValue()).replace(/[\s\-]/g, '');
  if (!raw || raw.length < 9) return;
  let n = raw;
  if (n.startsWith('+254') && n.length === 13) n = '0' + n.slice(4);
  else if (n.startsWith('254') && n.length === 12) n = '0' + n.slice(3);
  if (n !== raw) cell.setValue(n);
}

/** Convert customer name to Title Case on entry. */
function titleCase(sh, row, col) {
  const cell = sh.getRange(row, col);
  const val  = String(cell.getValue()).trim();
  if (!val) return;
  const tc = val.replace(/\w\S*/g,
    w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase());
  if (tc !== val) cell.setValue(tc);
}

/**
 * Menu action: scan all rows and alert on any missing required fields.
 * Required: DATE VISITED, CUSTOMER NAME, ID NUMBER, PRIMARY CONTACT, COUNTY.
 */
function validateRequired() {
  const sh   = SpreadsheetApp.getActive().getSheetByName(CFG.TAB);
  const last = sh.getLastRow();
  if (last < CFG.DATA_ROW) { alert('No data yet.'); return; }

  const data = sh.getRange(CFG.DATA_ROW, 1,
                             last - CFG.DATA_ROW + 1, 20).getValues();
  const issues = [];

  data.forEach((row, i) => {
    const r = i + CFG.DATA_ROW;
    if (!row[CFG.C.NAME - 1]) return;            /* skip completely empty rows */
    const miss = CFG.REQUIRED
      .filter(c => !row[c - 1])
      .map(c => sh.getRange(CFG.HEADER_ROW, c).getValue());
    if (miss.length) issues.push('Row ' + r + ': missing ' + miss.join(', '));
  });

  SpreadsheetApp.getUi().alert(
    issues.length === 0
      ? 'All rows have required fields filled.'
      : issues.length + ' row(s) with missing fields:\n\n' +
        issues.slice(0, 15).join('\n') +
        (issues.length > 15 ? '\n...and ' + (issues.length - 15) + ' more' : '')
  );
}

/**
 * Colour the entire row based on FINAL DECISION value.
 * Leaves unset rows as alternating white/light-grey.
 */
function colourRow(sh, row) {
  const dec   = String(sh.getRange(row, CFG.C.DECISION).getValue()).trim();
  const style = CFG.COLOURS[dec];
  const rng   = sh.getRange(row, 1, 1, Object.keys(CFG.C).length);

  if (style) {
    rng.setBackground(style.bg);
    sh.getRange(row, CFG.C.DECISION)
      .setFontColor(style.accent).setFontWeight('bold');
  } else {
    rng.setBackground(row % 2 === 0 ? '#F5F5F5' : null);
    sh.getRange(row, CFG.C.DECISION)
      .setFontColor(null).setFontWeight('normal');
  }
}

/** Recolour every data row — useful after a bulk import. */
function refreshAllColours() {
  const sh   = SpreadsheetApp.getActive().getSheetByName(CFG.TAB);
  const last = sh.getLastRow();
  for (let r = CFG.DATA_ROW; r <= last; r++) colourRow(sh, r);
}

/** Menu action: yellow-highlight rows with no FINAL DECISION. */
function highlightPending() {
  const sh   = SpreadsheetApp.getActive().getSheetByName(CFG.TAB);
  const last = sh.getLastRow();
  let n = 0;
  for (let r = CFG.DATA_ROW; r <= last; r++) {
    const name = sh.getRange(r, CFG.C.NAME).getValue();
    const dec  = sh.getRange(r, CFG.C.DECISION).getValue();
    if (name && !dec) {
      sh.getRange(r, CFG.C.DECISION).setBackground('#FFF9C4');
      n++;
    }
  }
  SpreadsheetApp.getUi().alert(
    n > 0 ? n + ' pending rows highlighted in yellow.' : 'No pending rows found.'
  );
}

/** Menu action: orange-highlight rows pending >= STALE_DAYS days. */
function highlightStale() {
  const sh   = SpreadsheetApp.getActive().getSheetByName(CFG.TAB);
  const last = sh.getLastRow();
  const now  = new Date();
  let n = 0;
  for (let r = CFG.DATA_ROW; r <= last; r++) {
    const name = sh.getRange(r, CFG.C.NAME).getValue();
    const dec  = sh.getRange(r, CFG.C.DECISION).getValue();
    const dv   = sh.getRange(r, CFG.C.DATE_VISITED).getValue();
    if (!name || dec || !(dv instanceof Date)) continue;
    const days = Math.floor((now - dv) / 86400000);
    if (days >= CFG.STALE_DAYS) {
      sh.getRange(r, 1, 1, 20).setBackground('#FFCCBC');
      sh.getRange(r, CFG.C.DATE_VISITED)
        .setNote(days + ' days since visit — no decision yet');
      n++;
    }
  }
  SpreadsheetApp.getUi().alert(
    n > 0
      ? n + ' stale row(s) highlighted in orange.'
      : 'No stale rows (all within ' + CFG.STALE_DAYS + ' days).'
  );
}

/** Time-based trigger: daily stale scan → email digest. */
function dailyStaleScan() {
  const sh   = SpreadsheetApp.getActive().getSheetByName(CFG.TAB);
  const last = sh.getLastRow();
  const now  = new Date();
  const stale = [];

  for (let r = CFG.DATA_ROW; r <= last; r++) {
    const name = sh.getRange(r, CFG.C.NAME).getValue();
    const dec  = sh.getRange(r, CFG.C.DECISION).getValue();
    const dv   = sh.getRange(r, CFG.C.DATE_VISITED).getValue();
    const id   = sh.getRange(r, CFG.C.ID_NUMBER).getValue();
    const branch = sh.getRange(r, CFG.C.BRANCH).getValue();
    const visitedBy = sh.getRange(r, CFG.C.VISITED_BY).getValue();
    if (!name || dec || !(dv instanceof Date)) continue;
    const days = Math.floor((now - dv) / 86400000);
    if (days >= CFG.STALE_DAYS) stale.push({ r, name, id, branch, visitedBy, days });
  }
  if (stale.length > 0) sendStaleDigest(stale);
}

/**
 * Create or repair the Staff tab used for email notification routing.
 * Staff can edit rows 2+ directly in the spreadsheet.
 */
function ensureStaffSheet() {
  const ss = SpreadsheetApp.getActive();
  let sh = ss.getSheetByName(CFG.STAFF_TAB);
  if (!sh) sh = ss.insertSheet(CFG.STAFF_TAB, ss.getNumSheets());

  sh.getRange(1, 1, 1, CFG.STAFF_HEADERS.length)
    .setValues([CFG.STAFF_HEADERS])
    .setBackground('#263238')
    .setFontColor('#FFFFFF')
    .setFontWeight('bold');
  sh.setFrozenRows(1);
  sh.setColumnWidths(1, CFG.STAFF_HEADERS.length, 150);
  sh.setColumnWidth(CFG.STAFF.NOTIFY_ON, 260);

  if (sh.getLastRow() < 2) {
    sh.getRange(2, 1, 4, CFG.STAFF_HEADERS.length).setValues([
      ['Manager Name', 'manager@example.com', 'Manager', 'All', 'decision_approved,decision_rejected,stale_digest', 'No'],
      ['Back Office Name', 'backoffice@example.com', 'Back-office', 'All', 'decision_approved,decision_rejected,stale_digest', 'No'],
      ['BRO Name', 'bro@example.com', 'BRO', 'Embu', 'decision_approved,decision_rejected,stale_digest', 'No'],
      ['Inactive Example', 'inactive@example.com', 'BRO', 'All', 'all', 'No'],
    ]);
  }

  SpreadsheetApp.getUi().alert(
    'Staff tab is ready.\n\n' +
    'Edit rows 2+ with real staff names, emails, roles, branches, notification events, and Active=Yes.'
  );
}

/**
 * Read active Staff rows and return emails matching role, branch, event and optional names.
 */
function getStaffEmails(options) {
  const ss = SpreadsheetApp.getActive();
  const sh = ss.getSheetByName(CFG.STAFF_TAB);
  if (!sh) {
    Logger.log('Staff tab not found. Run Orders > Create/update Staff tab.');
    return [];
  }

  const last = sh.getLastRow();
  if (last < 2) return [];

  const opts = options || {};
  const roles = (opts.roles || []).map(normalizeStaffToken);
  const branch = normalizeStaffToken(opts.branch || 'All');
  const event = normalizeStaffToken(opts.event || 'all');
  const names = (opts.names || []).map(normalizeStaffToken).filter(Boolean);

  const rows = sh.getRange(2, 1, last - 1, CFG.STAFF_HEADERS.length).getValues();
  return rows
    .filter(row => normalizeStaffToken(row[CFG.STAFF.ACTIVE - 1]) === 'yes')
    .filter(row => isValidEmail(row[CFG.STAFF.EMAIL - 1]))
    .filter(row => staffRoleMatches(row[CFG.STAFF.ROLE - 1], roles))
    .filter(row => staffBranchMatches(row[CFG.STAFF.BRANCH - 1], branch))
    .filter(row => staffEventMatches(row[CFG.STAFF.NOTIFY_ON - 1], event))
    .filter(row => staffNameMatches(row[CFG.STAFF.NAME - 1], names))
    .map(row => String(row[CFG.STAFF.EMAIL - 1]).trim());
}

function staffRoleMatches(value, roles) {
  if (!roles || roles.length === 0) return true;
  const role = normalizeStaffToken(value || 'All');
  return role === 'all' || roles.includes(role);
}

function staffBranchMatches(value, branch) {
  const staffBranch = normalizeStaffToken(value || 'All');
  return staffBranch === 'all' || branch === 'all' || staffBranch === branch;
}

function staffEventMatches(value, event) {
  const events = String(value || '')
    .split(',')
    .map(normalizeStaffToken)
    .filter(Boolean);
  return events.includes('all') || events.includes(event);
}

function staffNameMatches(value, names) {
  if (!names || names.length === 0) return true;
  const staffName = normalizeStaffToken(value);
  if (!staffName) return false;
  return names.some(name => staffName.includes(name) || name.includes(staffName));
}

function staffNameTokens(value) {
  return String(value || '')
    .split(/[,/&+]| and /i)
    .map(part => part.trim())
    .filter(Boolean);
}

function normalizeStaffToken(value) {
  return String(value || '').trim().toLowerCase().replace(/\s+/g, ' ');
}

function uniqueEmails(values) {
  const seen = {};
  return (values || [])
    .map(email => String(email || '').trim())
    .filter(email => {
      const key = email.toLowerCase();
      if (!key || seen[key]) return false;
      seen[key] = true;
      return true;
    });
}

function isValidEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(value || '').trim());
}

function sendStaleDigestEmail(recipients, rows, url) {
  const lines = rows.map(r =>
    '  Row ' + r.r + ': ' + r.name + ' (ID ' + r.id + ') - ' +
    (r.branch || 'Unknown') + ' - ' + r.days + ' days pending'
  );

  const subject = '[STALE] ' + rows.length + ' order(s) pending ' + CFG.STALE_DAYS + '+ days';
  const body = [
    'The following orders have no FINAL DECISION after ' + CFG.STALE_DAYS + ' days:',
    '',
    ...lines,
    '',
    'View sheet: ' + url,
  ].join('\n');

  MailApp.sendEmail({ to: uniqueEmails(recipients).join(','), subject, body });
}

/**
 * Send an email when a FINAL DECISION of Approved or Rejected is recorded.
 * Called from onEdit — keep it fast.
 */
function notifyDecision(sh, row, decision) {
  const g = col => sh.getRange(row, col).getValue();

  const name   = g(CFG.C.NAME);
  const id     = g(CFG.C.ID_NUMBER);
  const branch = g(CFG.C.BRANCH);
  const visitedBy = g(CFG.C.VISITED_BY);
  const credit = g(CFG.C.CREDIT)      || 'not set';
  const custNo = g(CFG.C.CUSTOMER_NO) || 'not set';
  const comment= g(CFG.C.COMMENT)     || 'not set';
  const url    = SpreadsheetApp.getActive().getUrl();
  const mark   = decision === 'Approved' ? '[APPROVED]' : '[REJECTED]';
  const event  = decision === 'Approved' ? 'decision_approved' : 'decision_rejected';
  const recipients = getStaffEmails({
    event,
    roles: ['Manager', 'Back-office', 'All'],
    branch,
  }).concat(getStaffEmails({
    event,
    roles: ['BRO', 'All'],
    branch,
    names: staffNameTokens(visitedBy),
  }));
  const to = uniqueEmails(recipients);

  if (to.length === 0) {
    Logger.log('No active Staff recipients for ' + event + ', branch=' + branch);
    return;
  }

  const subject = mark + ' ' + name + ' - ' + branch;
  const body = [
    'A new order decision has been recorded.',
    '',
    'Decision:       ' + decision.toUpperCase(),
    'Customer name:  ' + name,
    'ID number:      ' + id,
    'Branch:         ' + branch,
    'Credit analysis:' + credit,
    'Customer no:    ' + custNo,
    'Comment:        ' + comment,
    '',
    'View in sheet: ' + url,
    '',
    '- Order Approval Form (automated)',
  ].join('\n');

  MailApp.sendEmail({ to: to.join(','), subject, body });
}

/**
 * Send a digest listing all stale orders.
 * Called by dailyStaleScan() time-based trigger.
 */
function sendStaleDigest(rows) {
  const url   = SpreadsheetApp.getActive().getUrl();
  const managerRecipients = uniqueEmails(getStaffEmails({
    event: 'stale_digest',
    roles: ['Manager', 'Back-office', 'All'],
    branch: 'All',
  }));
  if (managerRecipients.length > 0) {
    sendStaleDigestEmail(managerRecipients, rows, url);
  }

  const byBranch = {};
  rows.forEach(row => {
    const key = String(row.branch || 'Unknown').trim() || 'Unknown';
    if (!byBranch[key]) byBranch[key] = [];
    byBranch[key].push(row);
  });

  Object.keys(byBranch).forEach(branch => {
    const branchRows = byBranch[branch];
    const branchRecipients = uniqueEmails(getStaffEmails({
      event: 'stale_digest',
      roles: ['BRO', 'All'],
      branch,
      names: branchRows.flatMap(row => staffNameTokens(row.visitedBy)),
    }));
    const recipients = branchRecipients.filter(email => !managerRecipients.includes(email));
    if (recipients.length > 0) sendStaleDigestEmail(recipients, branchRows, url);
  });
}


/** Build (or refresh) the Dashboard sheet. Called by menu and hourly trigger. */
function buildDashboard() {
  const ss = SpreadsheetApp.getActive();
  const src = ss.getSheetByName(CFG.TAB);
  const last = src.getLastRow();

  let dash = ss.getSheetByName('Dashboard');
  if (!dash) dash = ss.insertSheet('Dashboard', ss.getNumSheets());
  dash.clearContents().clearFormats();

  if (last < CFG.DATA_ROW) { dash.getRange('A1').setValue('No data yet.'); return; }

  const data = src.getRange(CFG.DATA_ROW, 1,
                              last - CFG.DATA_ROW + 1, 20).getValues();

  /* ── Aggregate ────────────────────────────────────── */
  const tot = { total:0, approved:0, rejected:0, hold:0, pending:0 };
  const byBranch = {}, byMonth = {};

  data.forEach(row => {
    const name = row[CFG.C.NAME - 1];
    if (!name) return;
    const dec    = String(row[CFG.C.DECISION - 1]).trim();
    const branch = String(row[CFG.C.BRANCH - 1]).trim() || 'Unknown';
    const dv     = row[CFG.C.DATE_VISITED - 1];
    tot.total++;
    if      (dec === 'Approved') tot.approved++;
    else if (dec === 'Rejected') tot.rejected++;
    else if (dec === 'Hold')     tot.hold++;
    else                          tot.pending++;
    if (!byBranch[branch]) byBranch[branch] = {total:0,approved:0,rejected:0,hold:0,pending:0};
    byBranch[branch].total++;
    if (dec === 'Approved') byBranch[branch].approved++;
    else if (dec === 'Rejected') byBranch[branch].rejected++;
    else if (dec === 'Hold') byBranch[branch].hold++;
    else byBranch[branch].pending++;
    if (dv instanceof Date) {
      const mk = Utilities.formatDate(dv, Session.getScriptTimeZone(), 'MMM yyyy');
      byMonth[mk] = (byMonth[mk] || 0) + 1;
    }
  });

  /* ── Title ────────────────────────────────────────── */
  const cols = 6;
  dash.setRowHeight(1, 30);
  const titleRng = dash.getRange(1, 1, 1, cols);
  titleRng.merge();
  titleRng.setValue('Order Approval Dashboard — ' +
    Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'dd MMM yyyy HH:mm'));
  _hdr(titleRng, '#0D47A1', '#FFFFFF', 12);

  /* ── Summary tiles ────────────────────────────────── */
  const tiles = [
    ['Total',    tot.total,    '#1565C0'],
    ['Approved', tot.approved, '#2E7D32'],
    ['Rejected', tot.rejected, '#B71C1C'],
    ['Hold',     tot.hold,     '#E65100'],
    ['Pending',  tot.pending,  '#37474F'],
  ];
  tiles.forEach(([lbl, val, bg], i) => {
    dash.setColumnWidth(i + 1, 110).setRowHeight(3, 22).setRowHeight(4, 40);
    _hdr(dash.getRange(3, i+1).setValue(lbl), bg, '#FFFFFF', 10);
    dash.getRange(4, i+1).setValue(val)
      .setBackground(bg).setFontColor('#FFFFFF')
      .setFontSize(22).setFontWeight('bold')
      .setHorizontalAlignment('center').setVerticalAlignment('middle');
  });

  /* ── By Branch ────────────────────────────────────── */
  let r = 6;
  _hdrRow(dash, r, ['Branch','Total','Approved','Rejected','Hold','Pending'], '#1A7744');
  Object.entries(byBranch).sort((a,b)=>b[1].total-a[1].total).forEach(([br,s],i) => {
    r++;
    const vals = [br,s.total,s.approved,s.rejected,s.hold,s.pending];
    vals.forEach((v,ci) => {
      const c = dash.getRange(r,ci+1).setValue(v).setFontFamily('Arial').setFontSize(10)
        .setBackground(i%2===0?'#E8F5E9':'#FFFFFF').setVerticalAlignment('middle');
      if(ci>0) c.setHorizontalAlignment('center');
    });
    dash.setRowHeight(r, 18);
  });

  /* ── By Month ─────────────────────────────────────── */
  r += 2;
  _hdrRow(dash, r, ['Month','Orders'], '#6A1B9A');
  Object.entries(byMonth).forEach(([mo,cnt]) => {
    r++;
    dash.getRange(r,1).setValue(mo).setFontFamily('Arial').setFontSize(10);
    dash.getRange(r,2).setValue(cnt).setFontFamily('Arial').setFontSize(10)
      .setHorizontalAlignment('center');
    dash.setRowHeight(r,18);
  });

  Logger.log('Dashboard refreshed: ' + new Date());
}

function _hdr(rng, bg, fg, sz) {
  return rng.setBackground(bg).setFontColor(fg).setFontWeight('bold')
    .setFontFamily('Arial').setFontSize(sz || 10)
    .setHorizontalAlignment('center').setVerticalAlignment('middle');
}
function _hdrRow(sh, row, labels, bg) {
  labels.forEach((l,i) => _hdr(sh.getRange(row,i+1).setValue(l), bg, '#FFFFFF', 10));
  sh.setRowHeight(row, 20);
}

/** Open the search dialog. */
function showSearch() {
  const html = HtmlService.createHtmlOutput(`
<style>
  *{box-sizing:border-box;margin:0;padding:0;font-family:Arial,sans-serif}
  body{padding:14px;font-size:13px;color:#212121}
  input{width:100%;padding:7px 10px;margin:6px 0 10px;border:1px solid #ccc;
        border-radius:4px;font-size:13px}
  button{width:100%;padding:9px;background:#1565C0;color:#fff;border:none;
         border-radius:4px;cursor:pointer;font-size:13px;font-weight:500}
  button:hover{background:#0D47A1}
  #out{margin-top:12px;font-size:12px;line-height:1.5}
  table{width:100%;border-collapse:collapse;margin-top:6px}
  th{background:#1565C0;color:#fff;padding:4px 6px;font-size:11px;text-align:left}
  td{padding:4px 6px;border-bottom:0.5px solid #e0e0e0;font-size:11px}
  tr:nth-child(even)td{background:#F5F5F5}
  .chip{display:inline-block;padding:1px 7px;border-radius:9px;font-size:10px;
        font-weight:600;color:#fff}
</style>
<b>Search orders</b>
<input id="q" placeholder="ID number, name, or phone" onkeydown="if(event.key==='Enter')go()">
<button onclick="go()">Search</button>
<div id="out"></div>
<script>
  document.getElementById('q').focus();
  function go(){
    const q=document.getElementById('q').value.trim();
    if(!q)return;
    document.getElementById('out').innerHTML='Searching…';
    google.script.run
      .withSuccessHandler(r=>{document.getElementById('out').innerHTML=r;})
      .withFailureHandler(e=>{document.getElementById('out').innerText='Error: '+e.message;})
      .runSearch(q);
  }
<\/script>
  `).setWidth(380).setHeight(320);
  SpreadsheetApp.getUi().showModalDialog(html, 'Search orders');
}

/** Server-side search — called by the dialog. Returns HTML string. */
function runSearch(query) {
  const sh   = SpreadsheetApp.getActive().getSheetByName(CFG.TAB);
  const last = sh.getLastRow();
  if (last < CFG.DATA_ROW) return '<i>No data yet.</i>';

  const q    = String(query).toLowerCase().trim();
  const data = sh.getRange(CFG.DATA_ROW, 1,
                             last - CFG.DATA_ROW + 1, 20).getValues();
  /* Columns to search across */
  const SEARCH = [CFG.C.ID_NUMBER, CFG.C.NAME, CFG.C.PRIMARY,
                  CFG.C.SECONDARY, CFG.C.CUSTOMER_NO];

  const hits = [];
  data.forEach((row, i) => {
    const r = i + CFG.DATA_ROW;
    if (SEARCH.some(c => String(row[c-1]).toLowerCase().includes(q))) {
      hits.push({
        r,
        name:   row[CFG.C.NAME     - 1],
        id:     row[CFG.C.ID_NUMBER - 1],
        branch: row[CFG.C.BRANCH   - 1],
        dec:    String(row[CFG.C.DECISION - 1]).trim() || '—',
      });
    }
  });

  if (hits.length === 0) return '<i>No results for <b>' + query + '</b></i>';

  /* Jump to first hit */
  sh.getRange(hits[0].r, 1).activate();
  SpreadsheetApp.getActive().setActiveSheet(sh);

  const CHIP = { Approved:'#2E7D32', Rejected:'#B71C1C',
                 Hold:'#E65100', '—':'#757575' };
  const rows = hits.slice(0, 20).map(h => {
    const col = CHIP[h.dec] || '#37474F';
    return '<tr><td>' + h.r + '</td><td>' + h.name + '</td><td>' + h.id +
           '</td><td>' + h.branch + '</td><td>' +
           '<span class="chip" style="background:' + col + '">' + h.dec +
           '</span></td></tr>';
  }).join('');

  return '<b>' + hits.length + ' result(s)</b> — jumped to row ' + hits[0].r +
         '<table><tr><th>Row</th><th>Name</th><th>ID</th><th>Branch</th><th>Decision</th></tr>' +
         rows + '</table>' +
         (hits.length > 20 ? '<br><i>Showing first 20 of ' + hits.length + '</i>' : '');
}
