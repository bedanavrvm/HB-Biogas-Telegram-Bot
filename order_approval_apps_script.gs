/**
 * Config.gs - single source of truth for column layout.
 * Row 1 = visual title banner (ignored by bot).
 * Row 2 = header row (bot reads this).
 * Row 3+ = data rows.
 */
const CFG = {
  TAB:         'Orders',
  HEADER_ROW:  2,
  DATA_ROW:    3,

  /* Column positions - 1-based, matching scripts/create_order_approval_workbook.py */
  C: {
    ORDER_RECORD_ID: 1,  /* A - bot-managed stable record ID */
    DATE_VISITED:   2,  /* B */
    NAME:           3,  /* C */
    BRANCH:         4,  /* D */
    ID_NUMBER:      5,  /* E - dedup key */
    PRIMARY:        6,  /* F */
    SECONDARY:      7,  /* G */
    COUNTY:         8,  /* H */
    LANDMARK:       9,  /* I */
    VISITED_BY:    10,  /* J */
    HB_STAFF:      11,  /* K */
    DEP_HB:        12,  /* L */
    DEP_JBL:       13,  /* M */
    COMMENT:       14,  /* N */
    IMAB:          15,  /* O */
    CUSTOMER_NO:   16,  /* P */
    CREDIT:        17,  /* Q */
    DECISION:      18,  /* R */
    MEDIA_URLS:    19,  /* S - bot-managed */
  },

  /* Columns the Telegram bot owns - show warning before manual edit */
  BOT_COLS: [1, 19],

  /* Minimum columns needed for a row to count as complete */
  REQUIRED: [2, 3, 5, 6, 8],   /* Date, Name, ID, Primary, County */

  /* FINAL DECISION -> row highlight colour */
  COLOURS: {
    'Approved':     { bg:'#E8F5E9', accent:'#1B5E20' },
    'Rejected':     { bg:'#FFEBEE', accent:'#B71C1C' },
    'Deferred':     { bg:'#FFF8E1', accent:'#E65100' },
    'Under Review': { bg:'#E3F2FD', accent:'#0D47A1' },
  },

  /* Days before a pending row is flagged as stale */
  STALE_DAYS: 7,

  /*
   * Staff notification and permission directory.
   *
   * Create a sheet/tab named "Staff" with these columns:
   * Name | Email | Role | Branch | Notify On | Editable Columns | Active
   *
   * Role examples: BRO, Manager, Back-office, IT, All
   * Branch examples: Embu, Muranga, All
   * Notify On examples: decision_approved, decision_rejected, stale_digest, all
   * Editable Columns examples: All, BRO, Back-office, DATE VISITED, F, 18
   * Active examples: Yes, No
   */
  STAFF_TAB: 'Staff',
  OPTIONS_TAB: 'Dropdown Options',
  STAFF_HEADERS: ['Name', 'Email', 'Role', 'Branch', 'Notify On', 'Editable Columns', 'Active'],
  OPTION_HEADERS: ['Branch', 'County', 'Visited By', 'HB Staff'],
  /* Optional bootstrap/admin allowlist. Fill this if the menu does not appear before authorization. */
  OWNER_EMAILS: [],
  STAFF: {
    NAME:             1,
    EMAIL:            2,
    ROLE:             3,
    BRANCH:           4,
    NOTIFY_ON:        5,
    EDITABLE_COLUMNS: 6,
    ACTIVE:           7,
  },

  ROLE_EDIT_GROUPS: {
    BRO: [
      'DATE VISITED', 'CUSTOMER NAME', 'BRANCH', 'ID NUMBER',
      'CONTACTS / PRIMARY', 'CONTACTS / SECONDARY', 'COUNTY',
      'LOCATION AND NEAREST LANDMARK', 'VISITED BY', 'HB STAFF',
      'DEPOSIT / HB', 'DEPOSIT / JBL', 'COMMENT',
    ],
    'BACK-OFFICE': [
      'IS CUSTOMER CREATED ON IMAB?', 'CUSTOMER NO', 'CREDIT ANALYSIS',
      'FINAL DECISION', 'COMMENT',
    ],
    MANAGER: ['All'],
    IT: ['All'],
    ALL: ['All'],
  },
};

/** onOpen: build the custom menu. */
function onOpen() {
  if (!isOrderAdminUser_()) return;

  SpreadsheetApp.getUi()
    .createMenu('Orders')
    .addItem('Search by ID / Name / Phone', 'showSearch')
    .addSeparator()
    .addItem('Highlight pending decisions', 'highlightPending')
    .addItem('Highlight stale rows', 'highlightStale')
    .addItem('Validate required fields', 'validateRequired')
    .addSeparator()
    .addItem('Apply validation + formatting', 'applyOrderValidationAndFormatting')
    .addItem('Repair media links', 'repairMediaLinks')
    .addSeparator()
    .addItem('Refresh dashboard', 'buildDashboard')
    .addSeparator()
    .addItem('Send stale digest now', 'sendStaleDigestNow')
    .addItem('Send decision alert for selected row', 'sendDecisionAlertForSelectedRow')
    .addSeparator()
    .addItem('Setup order sheet support', 'setupOrderSheetSupport')
    .addItem('Create/update Staff tab', 'ensureStaffSheet')
    .addItem('Validate Staff tab', 'validateStaffSheetSetup')
    .addItem('Show Staff tab', 'showStaffSheet')
    .addSeparator()
    .addItem('Protect bot columns', 'protectBotCols')
    .addItem('Apply Staff permissions', 'applyStaffPermissions')
    .addItem('Remove order protections', 'removeOrderProtections')
    .addItem('Install daily triggers', 'installTriggers')
    .addToUi();
}

function requireOrderAdmin_(showAlert) {
  if (isOrderAdminUser_()) return true;
  if (showAlert !== false) {
    try {
      SpreadsheetApp.getUi().alert(
        'Access denied.\n\n' +
        'Only the sheet owner or active IT staff can use the Orders menu.'
      );
    } catch (err) {
      Logger.log('Access denied: only sheet owner or active IT staff can use this action.');
    }
  }
  return false;
}

function isOrderAdminUser_() {
  const email = currentUserEmail_();
  if (!email) return false;
  if (CFG.OWNER_EMAILS.map(normalizeStaffToken).includes(normalizeStaffToken(email))) {
    return true;
  }
  if (normalizeStaffToken(email) === normalizeStaffToken(spreadsheetOwnerEmail_())) {
    return true;
  }
  return activeStaffUserHasRole_(email, ['it', 'all']);
}

function currentUserEmail_() {
  const candidates = [];
  try { candidates.push(Session.getActiveUser().getEmail()); } catch (err) {}
  try { candidates.push(Session.getEffectiveUser().getEmail()); } catch (err) {}
  return String(candidates.find(email => String(email || '').trim()) || '').trim();
}

function spreadsheetOwnerEmail_() {
  try {
    return DriveApp.getFileById(SpreadsheetApp.getActive().getId()).getOwner().getEmail();
  } catch (err) {
    return '';
  }
}

function activeStaffUserHasRole_(email, allowedRoles) {
  const sh = SpreadsheetApp.getActive().getSheetByName(CFG.STAFF_TAB);
  if (!sh || sh.getLastRow() < 2) return false;
  const targetEmail = normalizeStaffToken(email);
  const roles = (allowedRoles || []).map(normalizeStaffToken);
  const rows = sh.getRange(2, 1, sh.getLastRow() - 1, CFG.STAFF_HEADERS.length).getValues();
  return rows.some(row => {
    const active = normalizeStaffToken(row[CFG.STAFF.ACTIVE - 1]) === 'yes';
    const staffEmail = normalizeStaffToken(row[CFG.STAFF.EMAIL - 1]);
    const role = normalizeStaffToken(row[CFG.STAFF.ROLE - 1]);
    return active && staffEmail === targetEmail && roles.includes(role);
  });
}

/**
 * onEdit: fires on every cell change.
 * Keeps logic fast - no external calls here.
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

  /* 4. Keep operational names in uppercase */
  if ([CFG.C.NAME, CFG.C.BRANCH, CFG.C.COUNTY, CFG.C.VISITED_BY, CFG.C.HB_STAFF].includes(col))
    upperCaseText(sh, row, col);

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
  if (!requireOrderAdmin_()) return;
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
  cell.setValue(new Date()).setNumberFormat('dd-mmm-yyyy');
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
        .setNote('Duplicate ID - also in row(s): ' + dupes.join(', '));
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
 * Normalise Kenyan phone numbers to 254XXXXXXXXX format.
 * Handles +254..., 254..., 07..., and 7... inputs.
 */
function normalisePhone(sh, row, col) {
  const cell = sh.getRange(row, col);
  const raw  = String(cell.getValue()).replace(/\D/g, '');
  if (!raw || raw.length < 9) return;
  let n = raw;
  if (n.startsWith('0') && n.length === 10) n = '254' + n.slice(1);
  else if ((n.startsWith('7') || n.startsWith('1')) && n.length === 9) n = '254' + n;
  if (n !== raw) cell.setValue(n);
}

/** Convert operational names to uppercase on entry. */
function upperCaseText(sh, row, col) {
  const cell = sh.getRange(row, col);
  const val  = String(cell.getValue()).trim();
  if (!val) return;
  const upper = val.replace(/\s+/g, ' ').toUpperCase();
  if (upper !== val) cell.setValue(upper);
}

/**
 * Menu action: scan all rows and alert on any missing required fields.
 * Required: DATE VISITED, CUSTOMER NAME, ID NUMBER, PRIMARY CONTACT, COUNTY.
 */
function validateRequired() {
  if (!requireOrderAdmin_()) return;
  const sh   = SpreadsheetApp.getActive().getSheetByName(CFG.TAB);
  const last = sh.getLastRow();
  if (last < CFG.DATA_ROW) { SpreadsheetApp.getUi().alert('No data yet.'); return; }

  const data = sh.getRange(CFG.DATA_ROW, 1,
                             last - CFG.DATA_ROW + 1, orderLastColumn()).getValues();
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
 * Apply dropdowns, data type validation and final-decision conditional colours.
 * Staff maintain Branch/County/Visited By/HB Staff choices in Dropdown Options.
 */
function applyOrderValidationAndFormatting(showAlert) {
  if (!requireOrderAdmin_()) return;
  showAlert = showAlert !== false;
  const ss = SpreadsheetApp.getActive();
  const sh = ss.getSheetByName(CFG.TAB);
  if (!sh) {
    SpreadsheetApp.getUi().alert('Orders sheet not found: ' + CFG.TAB);
    return;
  }

  const optionsSheet = ensureDropdownOptionsSheet();
  applyOrderDataValidation(sh, optionsSheet);
  applyDecisionConditionalFormatting(sh);
  if (showAlert) {
    SpreadsheetApp.getUi().alert(
      'Validation and conditional formatting applied.\n\n' +
      'Add or edit dropdown values in the "' + CFG.OPTIONS_TAB + '" tab.'
    );
  }
}

function ensureDropdownOptionsSheet() {
  const ss = SpreadsheetApp.getActive();
  let sh = ss.getSheetByName(CFG.OPTIONS_TAB);
  if (!sh) sh = ss.insertSheet(CFG.OPTIONS_TAB, ss.getNumSheets());

  sh.getRange(1, 1, 1, CFG.OPTION_HEADERS.length)
    .setValues([CFG.OPTION_HEADERS])
    .setBackground('#37474F')
    .setFontColor('#FFFFFF')
    .setFontWeight('bold');
  sh.setFrozenRows(1);
  sh.setColumnWidths(1, CFG.OPTION_HEADERS.length, 160);
  if (sh.getLastRow() < 2) {
    sh.getRange(2, 1, 3, CFG.OPTION_HEADERS.length).setValues([
      ['MURANGA', 'MURANGA', 'JOHN', 'THOMAS'],
      ['EMBU', 'EMBU', 'KIBINGE', ''],
      ['', '', '', ''],
    ]);
  }
  return sh;
}

function applyOrderDataValidation(sh, optionsSheet) {
  const rows = Math.max(sh.getMaxRows() - CFG.DATA_ROW + 1, 1);
  const listRules = [
    [CFG.C.IMAB, ['Yes', 'No', 'Pending']],
    [CFG.C.CREDIT, ['Approved', 'Pending', 'Rejected']],
    [CFG.C.DECISION, ['Approved', 'Rejected', 'Deferred', 'Under Review']],
  ];

  listRules.forEach(([col, values]) => {
    sh.getRange(CFG.DATA_ROW, col, rows, 1).setDataValidation(
      SpreadsheetApp.newDataValidation()
        .requireValueInList(values, true)
        .setAllowInvalid(false)
        .build()
    );
  });

  applyOptionsDropdown(sh, optionsSheet, CFG.C.BRANCH, 1);
  applyOptionsDropdown(sh, optionsSheet, CFG.C.COUNTY, 2);
  applyOptionsDropdown(sh, optionsSheet, CFG.C.VISITED_BY, 3);
  applyOptionsDropdown(sh, optionsSheet, CFG.C.HB_STAFF, 4);

  applyFormulaValidation(sh, CFG.C.PRIMARY, rows, '=OR(F3="",REGEXMATCH(TO_TEXT(F3),"^254[0-9]{9}$"))', 'Use 254XXXXXXXXX format.');
  applyFormulaValidation(sh, CFG.C.SECONDARY, rows, '=OR(G3="",REGEXMATCH(TO_TEXT(G3),"^254[0-9]{9}$"))', 'Use 254XXXXXXXXX format.');
  applyFormulaValidation(sh, CFG.C.DEP_HB, rows, '=OR(L3="",REGEXMATCH(TO_TEXT(L3),"^[0-9]+(\\.[0-9]{1,2})?$"))', 'Use a non-negative amount.');
  applyFormulaValidation(sh, CFG.C.DEP_JBL, rows, '=OR(M3="",REGEXMATCH(TO_TEXT(M3),"^[0-9]+(\\.[0-9]{1,2})?$"))', 'Use a non-negative amount.');
  applyFormulaValidation(sh, CFG.C.CUSTOMER_NO, rows, '=OR(P3="",REGEXMATCH(TO_TEXT(P3),"^[0-9]+$"))', 'Use digits only.');

  sh.getRange(CFG.DATA_ROW, CFG.C.DATE_VISITED, rows, 1).setDataValidation(
    SpreadsheetApp.newDataValidation()
      .requireDateBetween(new Date(2020, 0, 1), new Date(2099, 11, 31))
      .setAllowInvalid(false)
      .build()
  ).setNumberFormat('dd-mmm-yyyy');
}

function applyOptionsDropdown(sh, optionsSheet, targetCol, optionsCol) {
  const rows = Math.max(sh.getMaxRows() - CFG.DATA_ROW + 1, 1);
  const optionRows = Math.max(optionsSheet.getMaxRows() - 1, 1);
  const source = optionsSheet.getRange(2, optionsCol, optionRows, 1);
  sh.getRange(CFG.DATA_ROW, targetCol, rows, 1).setDataValidation(
    SpreadsheetApp.newDataValidation()
      .requireValueInRange(source, true)
      .setAllowInvalid(true)
      .build()
  );
}

function applyFormulaValidation(sh, col, rows, formula, helpText) {
  sh.getRange(CFG.DATA_ROW, col, rows, 1).setDataValidation(
    SpreadsheetApp.newDataValidation()
      .requireFormulaSatisfied(formula)
      .setHelpText(helpText)
      .setAllowInvalid(false)
      .build()
  );
}

function applyDecisionConditionalFormatting(sh) {
  const rows = Math.max(sh.getMaxRows() - CFG.DATA_ROW + 1, 1);
  const dataRange = sh.getRange(CFG.DATA_ROW, 1, rows, orderLastColumn());
  const dataA1 = dataRange.getA1Notation();
  const existing = sh.getConditionalFormatRules().filter(rule => {
    return !rule.getRanges().some(range =>
      range.getSheet().getSheetId() === sh.getSheetId()
      && range.getA1Notation() === dataA1
    );
  });

  const rules = Object.keys(CFG.COLOURS).map(decision => {
    const style = CFG.COLOURS[decision];
    return SpreadsheetApp.newConditionalFormatRule()
      .whenFormulaSatisfied('=$R3="' + decision + '"')
      .setBackground(style.bg)
      .setFontColor(style.accent)
      .setRanges([dataRange])
      .build();
  });

  sh.setConditionalFormatRules(existing.concat(rules));
}

function repairMediaLinks() {
  if (!requireOrderAdmin_()) return;
  const sh = SpreadsheetApp.getActive().getSheetByName(CFG.TAB);
  if (!sh) {
    SpreadsheetApp.getUi().alert('Orders sheet not found: ' + CFG.TAB);
    return;
  }
  const last = sh.getLastRow();
  if (last < CFG.DATA_ROW) {
    SpreadsheetApp.getUi().alert('No media links to repair.');
    return;
  }

  let repaired = 0;
  const range = sh.getRange(CFG.DATA_ROW, CFG.C.MEDIA_URLS, last - CFG.DATA_ROW + 1, 1);
  const values = range.getValues();
  values.forEach((row, index) => {
    const text = String(row[0] || '');
    if (!text || !text.match(/https?:\/\/\S+/g)) return;
    const rich = richTextWithLinks(text);
    if (!rich) return;
    sh.getRange(CFG.DATA_ROW + index, CFG.C.MEDIA_URLS).setRichTextValue(rich);
    repaired++;
  });

  SpreadsheetApp.getUi().alert('Repaired media links in ' + repaired + ' cell(s).');
}

function setupOrderSheetSupport() {
  if (!requireOrderAdmin_()) return;
  ensureStaffSheet(false);
  ensureDropdownOptionsSheet();
  applyOrderValidationAndFormatting(false);
  const result = validateStaffSheetSetup_(false);
  SpreadsheetApp.getUi().alert(
    'Order sheet support setup complete.\n\n' +
    staffValidationSummaryText(result) + '\n\n' +
    'Next: review Staff and Dropdown Options, then run Apply Staff permissions if you want strict edit controls.'
  );
}

function richTextWithLinks(text) {
  const builder = SpreadsheetApp.newRichTextValue().setText(text);
  const matches = text.matchAll(/https?:\/\/\S+/g);
  let found = false;
  for (const match of matches) {
    const rawUrl = match[0];
    const url = rawUrl.replace(/[.,;]+$/, '');
    const start = match.index;
    const end = start + url.length;
    builder.setLinkUrl(start, end, url);
    found = true;
  }
  return found ? builder.build() : null;
}

/**
 * Colour the entire row based on FINAL DECISION value.
 * Leaves unset rows as alternating white/light-grey.
 */
function colourRow(sh, row) {
  const dec   = String(sh.getRange(row, CFG.C.DECISION).getValue()).trim();
  const style = CFG.COLOURS[dec];
  const rng   = sh.getRange(row, 1, 1, orderLastColumn());

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

/** Recolour every data row - useful after a bulk import. */
function refreshAllColours() {
  if (!requireOrderAdmin_()) return;
  const sh   = SpreadsheetApp.getActive().getSheetByName(CFG.TAB);
  const last = sh.getLastRow();
  for (let r = CFG.DATA_ROW; r <= last; r++) colourRow(sh, r);
}

/** Menu action: yellow-highlight rows with no FINAL DECISION. */
function highlightPending() {
  if (!requireOrderAdmin_()) return;
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
  if (!requireOrderAdmin_()) return;
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
      sh.getRange(r, 1, 1, orderLastColumn()).setBackground('#FFCCBC');
      sh.getRange(r, CFG.C.DATE_VISITED)
        .setNote(days + ' days since visit - no decision yet');
      n++;
    }
  }
  SpreadsheetApp.getUi().alert(
    n > 0
      ? n + ' stale row(s) highlighted in orange.'
      : 'No stale rows (all within ' + CFG.STALE_DAYS + ' days).'
  );
}

/** Time-based trigger: daily stale scan -> email digest. */
function protectBotCols() {
  if (!requireOrderAdmin_()) return;
  const sh = SpreadsheetApp.getActive().getSheetByName(CFG.TAB);
  if (!sh) {
    SpreadsheetApp.getUi().alert('Orders sheet not found: ' + CFG.TAB);
    return;
  }

  const existing = sh.getProtections(SpreadsheetApp.ProtectionType.RANGE)
    .filter(p => String(p.getDescription() || '').startsWith('Bot-managed column:'));
  existing.forEach(p => p.remove());

  const rowCount = Math.max(sh.getMaxRows() - CFG.DATA_ROW + 1, 1);
  CFG.BOT_COLS.forEach(col => {
    const header = sh.getRange(CFG.HEADER_ROW, col).getValue() || ('Column ' + col);
    const range = sh.getRange(CFG.DATA_ROW, col, rowCount, 1);
    range.protect()
      .setDescription('Bot-managed column: ' + header)
      .setWarningOnly(true);
  });

  SpreadsheetApp.getUi().alert(
    'Bot columns are protected with edit warnings:\n\n' +
    CFG.BOT_COLS.map(col => sh.getRange(CFG.HEADER_ROW, col).getValue()).join(', ')
  );
}

function dailyStaleScan() {
  const sh = SpreadsheetApp.getActive().getSheetByName(CFG.TAB);
  if (!sh) return;
  const stale = collectStaleOrders_(sh);
  if (stale.length > 0) sendStaleDigest(stale);
}

function sendStaleDigestNow() {
  if (!requireOrderAdmin_()) return;
  const sh = SpreadsheetApp.getActive().getSheetByName(CFG.TAB);
  if (!sh) {
    SpreadsheetApp.getUi().alert('Orders sheet not found: ' + CFG.TAB);
    return;
  }
  const staffResult = validateStaffSheetSetup_(false);
  if (!staffResult.exists || staffResult.activeRows === 0) {
    SpreadsheetApp.getUi().alert(
      'No active Staff recipients found.\n\n' +
      'Open the Staff tab, add destination emails, set Notify On, and set Active=Yes.'
    );
    return;
  }
  const stale = collectStaleOrders_(sh);
  if (stale.length === 0) {
    SpreadsheetApp.getUi().alert('No stale rows found for the current threshold.');
    return;
  }
  const result = sendStaleDigest(stale);
  SpreadsheetApp.getUi().alert(
    'Stale digest sent now.\n\n' +
    'Rows included: ' + stale.length + '\n' +
    'Emails sent to: ' + result.recipientCount
  );
}

function sendDecisionAlertForSelectedRow() {
  if (!requireOrderAdmin_()) return;
  const ss = SpreadsheetApp.getActive();
  const sh = ss.getActiveSheet();
  if (!sh || sh.getName() !== CFG.TAB) {
    SpreadsheetApp.getUi().alert('Select a row on the ' + CFG.TAB + ' sheet first.');
    return;
  }
  const row = sh.getActiveRange().getRow();
  if (row < CFG.DATA_ROW) {
    SpreadsheetApp.getUi().alert('Select a data row, not the header.');
    return;
  }
  const decision = String(sh.getRange(row, CFG.C.DECISION).getValue()).trim();
  if (!['Approved', 'Rejected'].includes(decision)) {
    SpreadsheetApp.getUi().alert(
      'Selected row has no alertable FINAL DECISION.\n\n' +
      'Only Approved and Rejected send decision alerts.'
    );
    return;
  }
  const staffResult = validateStaffSheetSetup_(false);
  if (!staffResult.exists || staffResult.activeRows === 0) {
    SpreadsheetApp.getUi().alert(
      'No active Staff recipients found.\n\n' +
      'Open the Staff tab, add destination emails, set Notify On, and set Active=Yes.'
    );
    return;
  }
  const result = notifyDecision(sh, row, decision);
  SpreadsheetApp.getUi().alert(
    'Decision alert sent.\n\n' +
    'Row: ' + row + '\n' +
    'Decision: ' + decision + '\n' +
    'Emails sent to: ' + result.recipientCount
  );
}

function collectStaleOrders_(sh) {
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
  return stale;
}

/**
 * Create or repair the Staff tab used for email notification routing.
 * Staff can edit rows 2+ directly in the spreadsheet.
 */
function ensureStaffSheet(showAlert) {
  if (!requireOrderAdmin_()) return;
  showAlert = showAlert !== false;
  const ss = SpreadsheetApp.getActive();
  let sh = ss.getSheetByName(CFG.STAFF_TAB);
  if (!sh) sh = ss.insertSheet(CFG.STAFF_TAB, ss.getNumSheets());

  const previousHeaders = sh.getLastColumn() > 0
    ? sh.getRange(1, 1, 1, Math.max(sh.getLastColumn(), CFG.STAFF_HEADERS.length)).getValues()[0]
    : [];
  const legacyActiveInEditableColumn = (
    normalizeStaffToken(previousHeaders[CFG.STAFF.EDITABLE_COLUMNS - 1]) === 'active'
    && normalizeStaffToken(previousHeaders[CFG.STAFF.ACTIVE - 1]) !== 'active'
  );

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
      ['Manager Name', 'manager@example.com', 'Manager', 'All', 'decision_approved,decision_rejected,stale_digest', 'All', 'No'],
      ['Back Office Name', 'backoffice@example.com', 'Back-office', 'All', 'decision_approved,decision_rejected,stale_digest', 'Back-office', 'No'],
      ['BRO Name', 'bro@example.com', 'BRO', 'Embu', 'decision_approved,decision_rejected,stale_digest', 'BRO', 'No'],
      ['Render Bot Service Account', 'service-account@example.iam.gserviceaccount.com', 'IT', 'All', 'all', 'All', 'No'],
    ]);
  } else if (legacyActiveInEditableColumn) {
    migrateLegacyStaffPermissionsSheet(sh);
  }

  applyStaffSheetValidation(sh);

  if (showAlert) {
    SpreadsheetApp.getUi().alert(
      'Staff tab is ready.\n\n' +
      'Edit rows 2+ with real staff names, emails, roles, branches, notification events, editable columns, and Active=Yes.'
    );
  }
}

function migrateLegacyStaffPermissionsSheet(sh) {
  const rowCount = sh.getLastRow() - 1;
  if (rowCount <= 0) return;
  const rows = sh.getRange(2, 1, rowCount, CFG.STAFF_HEADERS.length).getValues();
  const migrated = rows.map(row => {
    const legacyActive = row[CFG.STAFF.EDITABLE_COLUMNS - 1];
    row[CFG.STAFF.EDITABLE_COLUMNS - 1] = defaultEditableColumnsForRole(row[CFG.STAFF.ROLE - 1]);
    row[CFG.STAFF.ACTIVE - 1] = legacyActive || 'No';
    return row;
  });
  sh.getRange(2, 1, rowCount, CFG.STAFF_HEADERS.length).setValues(migrated);
}

function defaultEditableColumnsForRole(role) {
  const normalized = normalizeEditableToken(role).replace(/\s+/g, '-');
  if (normalized === 'BRO') return 'BRO';
  if (normalized === 'BACK-OFFICE') return 'Back-office';
  if (['MANAGER', 'IT', 'ALL'].includes(normalized)) return 'All';
  return '';
}

function applyStaffSheetValidation(sh) {
  const roleRule = SpreadsheetApp.newDataValidation()
    .requireValueInList(['BRO', 'Manager', 'Back-office', 'IT', 'All'], true)
    .setAllowInvalid(false)
    .build();
  const branchRule = SpreadsheetApp.newDataValidation()
    .requireValueInList(['All', 'Embu', 'Muranga', 'Nairobi', 'Kiambu', 'Nyeri', 'Kirinyaga'], true)
    .setAllowInvalid(true)
    .build();
  const activeRule = SpreadsheetApp.newDataValidation()
    .requireValueInList(['Yes', 'No'], true)
    .setAllowInvalid(false)
    .build();

  sh.getRange(2, CFG.STAFF.ROLE, Math.max(sh.getMaxRows() - 1, 1), 1).setDataValidation(roleRule);
  sh.getRange(2, CFG.STAFF.BRANCH, Math.max(sh.getMaxRows() - 1, 1), 1).setDataValidation(branchRule);
  sh.getRange(2, CFG.STAFF.ACTIVE, Math.max(sh.getMaxRows() - 1, 1), 1).setDataValidation(activeRule);
  sh.getRange(1, CFG.STAFF.EDITABLE_COLUMNS).setNote(
    'Use comma-separated headers, column letters, column numbers, All, BRO, Back-office, Manager, or IT.'
  );
}

function validateStaffSheetSetup() {
  if (!requireOrderAdmin_()) return;
  const result = validateStaffSheetSetup_(true);
  SpreadsheetApp.getUi().alert(staffValidationSummaryText(result));
}

function validateStaffSheetSetup_(showToast) {
  const ss = SpreadsheetApp.getActive();
  const staffSheet = ss.getSheetByName(CFG.STAFF_TAB);
  const orderSheet = ss.getSheetByName(CFG.TAB);
  const result = {
    exists: Boolean(staffSheet),
    orderSheetExists: Boolean(orderSheet),
    rows: 0,
    activeRows: 0,
    invalidEmails: [],
    unknownRoles: [],
    blankEditable: [],
    invalidEditable: [],
    activeFullAccessRows: 0,
  };

  if (!staffSheet) return result;
  if (staffSheet.getLastRow() < 2) return result;

  const headers = orderSheet ? orderHeaders(orderSheet) : [];
  const rows = staffSheet.getRange(2, 1, staffSheet.getLastRow() - 1, CFG.STAFF_HEADERS.length).getValues();
  result.rows = rows.length;

  rows.forEach((row, index) => {
    const sheetRow = index + 2;
    const active = normalizeStaffToken(row[CFG.STAFF.ACTIVE - 1]) === 'yes';
    if (!active) return;
    result.activeRows++;

    const email = String(row[CFG.STAFF.EMAIL - 1] || '').trim();
    if (!isValidEmail(email)) result.invalidEmails.push('Row ' + sheetRow + ': ' + (email || 'blank email'));

    const role = normalizeEditableToken(row[CFG.STAFF.ROLE - 1]).replace(/\s+/g, '-');
    if (!CFG.ROLE_EDIT_GROUPS[role]) result.unknownRoles.push('Row ' + sheetRow + ': ' + (row[CFG.STAFF.ROLE - 1] || 'blank role'));

    const editable = String(row[CFG.STAFF.EDITABLE_COLUMNS - 1] || '').trim();
    if (!editable) {
      result.blankEditable.push('Row ' + sheetRow + ': ' + (email || 'blank email'));
    } else {
      const tokens = editable.split(',').map(token => token.trim()).filter(Boolean);
      tokens.forEach(token => {
        if (headers.length && expandEditableToken(token, headers).length === 0) {
          result.invalidEditable.push('Row ' + sheetRow + ': ' + token);
        }
      });
      if (tokens.some(token => normalizeEditableToken(token) === 'ALL')) {
        result.activeFullAccessRows++;
      }
    }
  });

  if (showToast) {
    ss.toast('Staff validation complete.', 'Orders', 4);
  }
  return result;
}

function staffValidationSummaryText(result) {
  const lines = [
    'Staff tab: ' + (result.exists ? 'Found' : 'Missing'),
    'Orders tab: ' + (result.orderSheetExists ? 'Found' : 'Missing'),
    'Staff rows: ' + result.rows,
    'Active staff rows: ' + result.activeRows,
    'Active full-access rows: ' + result.activeFullAccessRows,
  ];

  if (result.invalidEmails.length) {
    lines.push('', 'Invalid emails:', result.invalidEmails.slice(0, 10).join('\n'));
  }
  if (result.unknownRoles.length) {
    lines.push('', 'Unknown roles:', result.unknownRoles.slice(0, 10).join('\n'));
  }
  if (result.blankEditable.length) {
    lines.push('', 'Active rows missing Editable Columns:', result.blankEditable.slice(0, 10).join('\n'));
  }
  if (result.invalidEditable.length) {
    lines.push('', 'Invalid Editable Columns tokens:', result.invalidEditable.slice(0, 10).join('\n'));
  }
  if (result.activeFullAccessRows === 0) {
    lines.push('', 'Warning: no active full-access row found. Add the Render service account as IT / All / All before strict protections.');
  }
  if (!result.exists) {
    lines.push('', 'Run Orders > Create/update Staff tab.');
  }
  return lines.join('\n');
}

function showStaffSheet() {
  if (!requireOrderAdmin_()) return;
  const sh = SpreadsheetApp.getActive().getSheetByName(CFG.STAFF_TAB);
  if (!sh) {
    SpreadsheetApp.getUi().alert('Staff tab not found. Run Orders > Create/update Staff tab.');
    return;
  }
  SpreadsheetApp.getActive().setActiveSheet(sh);
}

function removeOrderProtections() {
  if (!requireOrderAdmin_()) return;
  const sh = SpreadsheetApp.getActive().getSheetByName(CFG.TAB);
  if (!sh) {
    SpreadsheetApp.getUi().alert('Orders sheet not found: ' + CFG.TAB);
    return;
  }
  const prefixes = ['Order approval permission:', 'Bot-managed column:'];
  const protections = sh.getProtections(SpreadsheetApp.ProtectionType.RANGE)
    .filter(p => prefixes.some(prefix => String(p.getDescription() || '').startsWith(prefix)));
  protections.forEach(p => p.remove());
  SpreadsheetApp.getUi().alert('Removed ' + protections.length + ' order approval protection(s).');
}

/**
 * Apply strict column permissions from the Staff tab.
 *
 * This follows the JBL pattern: STAFF is the source of truth. Add every human
 * editor and the Render Google service account to Staff, set Active=Yes, then
 * put allowed headers/groups in Editable Columns.
 */
function applyStaffPermissions() {
  if (!requireOrderAdmin_()) return;
  const ss = SpreadsheetApp.getActive();
  const sh = ss.getSheetByName(CFG.TAB);
  if (!sh) {
    SpreadsheetApp.getUi().alert('Orders sheet not found: ' + CFG.TAB);
    return;
  }

  ensureStaffSheet(false);
  const permissionMap = staffPermissionMap();
  if (Object.keys(permissionMap).length === 0) {
    SpreadsheetApp.getUi().alert(
      'No active Staff rows with Editable Columns were found.\n\n' +
      'No strict permissions were applied. Fill Staff rows first, including the Render service account if the bot writes to this sheet.'
    );
    return;
  }

  const existing = sh.getProtections(SpreadsheetApp.ProtectionType.RANGE)
    .filter(p => String(p.getDescription() || '').startsWith('Order approval permission:'));
  existing.forEach(p => p.remove());

  const currentUser = Session.getEffectiveUser().getEmail();
  const rowCount = Math.max(sh.getMaxRows() - CFG.DATA_ROW + 1, 1);
  const headers = orderHeaders(sh);
  let protectedCount = 0;

  headers.forEach((header, index) => {
    const col = index + 1;
    if (CFG.BOT_COLS.includes(col)) return;

    const editors = uniqueEmails((permissionMap[col] || []).concat(currentUser));
    if (editors.length === 0) return;

    const protection = sh.getRange(CFG.DATA_ROW, col, rowCount, 1)
      .protect()
      .setDescription('Order approval permission: ' + header);
    protection.removeEditors(protection.getEditors());
    protection.addEditors(editors);
    if (protection.canDomainEdit()) protection.setDomainEdit(false);
    protectedCount++;
  });

  protectBotCols();
  SpreadsheetApp.getUi().alert(
    'Staff permissions applied to ' + protectedCount + ' editable column(s).\n\n' +
    'Bot-managed columns remain warning-only. Make sure the Render Google service account is Active=Yes with Editable Columns=All if strict protections are used.'
  );
}

function staffPermissionMap() {
  const ss = SpreadsheetApp.getActive();
  const staffSheet = ss.getSheetByName(CFG.STAFF_TAB);
  const orderSheet = ss.getSheetByName(CFG.TAB);
  if (!staffSheet || !orderSheet || staffSheet.getLastRow() < 2) return {};

  const rows = staffSheet.getRange(2, 1, staffSheet.getLastRow() - 1, CFG.STAFF_HEADERS.length).getValues();
  const headers = orderHeaders(orderSheet);
  const map = {};

  rows.forEach(row => {
    if (normalizeStaffToken(row[CFG.STAFF.ACTIVE - 1]) !== 'yes') return;
    const email = String(row[CFG.STAFF.EMAIL - 1] || '').trim();
    if (!isValidEmail(email)) return;

    const editable = String(row[CFG.STAFF.EDITABLE_COLUMNS - 1] || '').trim();
    if (!editable) return;

    editableColumnsToIndexes(editable, headers).forEach(col => {
      if (!map[col]) map[col] = [];
      map[col].push(email);
    });
  });

  return map;
}

function editableColumnsToIndexes(value, headers) {
  const tokens = String(value || '')
    .split(',')
    .map(token => token.trim())
    .filter(Boolean);
  const columns = new Set();

  tokens.forEach(token => expandEditableToken(token, headers).forEach(col => columns.add(col)));
  return Array.from(columns).sort((a, b) => a - b);
}

function expandEditableToken(token, headers) {
  const normalized = normalizeEditableToken(token);
  if (!normalized) return [];
  if (normalized === 'ALL') {
    return headers.map((_, index) => index + 1);
  }
  if (CFG.ROLE_EDIT_GROUPS[normalized]) {
    return editableColumnsToIndexes(CFG.ROLE_EDIT_GROUPS[normalized].join(','), headers);
  }
  if (/^\d+$/.test(normalized)) {
    const col = Number(normalized);
    return col >= 1 && col <= headers.length ? [col] : [];
  }

  const headerIndex = headers
    .map(normalizeEditableToken)
    .indexOf(normalized);
  if (headerIndex >= 0) return [headerIndex + 1];

  if (/^[A-Z]+$/.test(normalized)) {
    const col = columnLetterToNumber(normalized);
    return col >= 1 && col <= headers.length ? [col] : [];
  }

  return [];
}

function normalizeEditableToken(value) {
  return String(value || '').trim().toUpperCase().replace(/\s+/g, ' ');
}

function orderHeaders(sh) {
  return sh.getRange(CFG.HEADER_ROW, 1, 1, orderLastColumn()).getValues()[0]
    .map(header => String(header || '').trim());
}

function orderLastColumn() {
  return Math.max.apply(null, Object.keys(CFG.C).map(key => CFG.C[key]));
}

function columnLetterToNumber(value) {
  let number = 0;
  String(value || '').toUpperCase().split('').forEach(char => {
    number = number * 26 + char.charCodeAt(0) - 64;
  });
  return number;
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
 * Called from onEdit - keep it fast.
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
    return { sent: false, recipientCount: 0 };
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
  return { sent: true, recipientCount: to.length };
}

/**
 * Send a digest listing all stale orders.
 * Called by dailyStaleScan() time-based trigger.
 */
function sendStaleDigest(rows) {
  const url   = SpreadsheetApp.getActive().getUrl();
  const allRecipients = [];
  const managerRecipients = uniqueEmails(getStaffEmails({
    event: 'stale_digest',
    roles: ['Manager', 'Back-office', 'All'],
    branch: 'All',
  }));
  if (managerRecipients.length > 0) {
    sendStaleDigestEmail(managerRecipients, rows, url);
    allRecipients.push(...managerRecipients);
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
    if (recipients.length > 0) {
      sendStaleDigestEmail(recipients, branchRows, url);
      allRecipients.push(...recipients);
    }
  });
  return {
    sent: allRecipients.length > 0,
    recipientCount: uniqueEmails(allRecipients).length,
  };
}


/** Build (or refresh) the Dashboard sheet. Called by menu and hourly trigger. */
function buildDashboard() {
  if (!requireOrderAdmin_()) return;
  const ss = SpreadsheetApp.getActive();
  const src = ss.getSheetByName(CFG.TAB);
  const last = src.getLastRow();

  let dash = ss.getSheetByName('Dashboard');
  if (!dash) dash = ss.insertSheet('Dashboard', ss.getNumSheets());
  dash.clearContents().clearFormats();

  if (last < CFG.DATA_ROW) { dash.getRange('A1').setValue('No data yet.'); return; }

  const data = src.getRange(CFG.DATA_ROW, 1,
                              last - CFG.DATA_ROW + 1, orderLastColumn()).getValues();

  /* -- Aggregate -------------------------------------- */
  const tot = { total:0, approved:0, rejected:0, deferred:0, pending:0 };
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
    else if (dec === 'Deferred') tot.deferred++;
    else                          tot.pending++;
    if (!byBranch[branch]) byBranch[branch] = {total:0,approved:0,rejected:0,deferred:0,pending:0};
    byBranch[branch].total++;
    if (dec === 'Approved') byBranch[branch].approved++;
    else if (dec === 'Rejected') byBranch[branch].rejected++;
    else if (dec === 'Deferred') byBranch[branch].deferred++;
    else byBranch[branch].pending++;
    if (dv instanceof Date) {
      const mk = Utilities.formatDate(dv, Session.getScriptTimeZone(), 'MMM yyyy');
      byMonth[mk] = (byMonth[mk] || 0) + 1;
    }
  });

  /* -- Title ------------------------------------------ */
  const cols = 6;
  dash.setRowHeight(1, 30);
  const titleRng = dash.getRange(1, 1, 1, cols);
  titleRng.merge();
  titleRng.setValue('Order Approval Dashboard - ' +
    Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'dd MMM yyyy HH:mm'));
  _hdr(titleRng, '#0D47A1', '#FFFFFF', 12);

  /* -- Summary tiles ---------------------------------- */
  const tiles = [
    ['Total',    tot.total,    '#1565C0'],
    ['Approved', tot.approved, '#2E7D32'],
    ['Rejected', tot.rejected, '#B71C1C'],
    ['Deferred', tot.deferred, '#E65100'],
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

  /* -- By Branch -------------------------------------- */
  let r = 6;
  _hdrRow(dash, r, ['Branch','Total','Approved','Rejected','Deferred','Pending'], '#1A7744');
  Object.entries(byBranch).sort((a,b)=>b[1].total-a[1].total).forEach(([br,s],i) => {
    r++;
    const vals = [br,s.total,s.approved,s.rejected,s.deferred,s.pending];
    vals.forEach((v,ci) => {
      const c = dash.getRange(r,ci+1).setValue(v).setFontFamily('Arial').setFontSize(10)
        .setBackground(i%2===0?'#E8F5E9':'#FFFFFF').setVerticalAlignment('middle');
      if(ci>0) c.setHorizontalAlignment('center');
    });
    dash.setRowHeight(r, 18);
  });

  /* -- By Month --------------------------------------- */
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
  if (!requireOrderAdmin_()) return;
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
    document.getElementById('out').innerHTML='Searching...';
    google.script.run
      .withSuccessHandler(r=>{document.getElementById('out').innerHTML=r;})
      .withFailureHandler(e=>{document.getElementById('out').innerText='Error: '+e.message;})
      .runSearch(q);
  }
<\/script>
  `).setWidth(380).setHeight(320);
  SpreadsheetApp.getUi().showModalDialog(html, 'Search orders');
}

/** Server-side search - called by the dialog. Returns HTML string. */
function runSearch(query) {
  if (!isOrderAdminUser_()) return '<i>Access denied.</i>';
  const sh   = SpreadsheetApp.getActive().getSheetByName(CFG.TAB);
  const last = sh.getLastRow();
  if (last < CFG.DATA_ROW) return '<i>No data yet.</i>';

  const q    = String(query).toLowerCase().trim();
  const data = sh.getRange(CFG.DATA_ROW, 1,
                             last - CFG.DATA_ROW + 1, orderLastColumn()).getValues();
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
        dec:    String(row[CFG.C.DECISION - 1]).trim() || '-',
      });
    }
  });

  if (hits.length === 0) return '<i>No results for <b>' + query + '</b></i>';

  /* Jump to first hit */
  sh.getRange(hits[0].r, 1).activate();
  SpreadsheetApp.getActive().setActiveSheet(sh);

  const CHIP = { Approved:'#2E7D32', Rejected:'#B71C1C',
                 Deferred:'#E65100', '-':'#757575' };
  const rows = hits.slice(0, 20).map(h => {
    const col = CHIP[h.dec] || '#37474F';
    return '<tr><td>' + h.r + '</td><td>' + h.name + '</td><td>' + h.id +
           '</td><td>' + h.branch + '</td><td>' +
           '<span class="chip" style="background:' + col + '">' + h.dec +
           '</span></td></tr>';
  }).join('');

  return '<b>' + hits.length + ' result(s)</b> - jumped to row ' + hits[0].r +
         '<table><tr><th>Row</th><th>Name</th><th>ID</th><th>Branch</th><th>Decision</th></tr>' +
         rows + '</table>' +
         (hits.length > 20 ? '<br><i>Showing first 20 of ' + hits.length + '</i>' : '');
}

