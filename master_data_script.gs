/*******************************************************************
 * JBL × HOMEBIOGAS — MASTER DATA SHEET MAINTENANCE SCRIPT
 *
 * Keeps the "Master Data" tab healthy as the bot / staff add rows:
 *   - Reapplies all 9 dropdown validations (extends as sheet grows)
 *   - Forces Text format on ID / phone / invoice / serial columns
 *     so leading zeros and alphanumeric values are never mangled
 *   - Refreshes the auto-formula columns by header name
 *   - Flags likely duplicate entries (same National ID entered twice)
 *   - Trims stray whitespace, standardises County/Constituency casing
 *
 * INSTALL
 *   1. Open the Google Sheet -> Extensions -> Apps Script
 *   2. Delete any boilerplate code, paste this whole file in
 *   3. Save (Ctrl+S), name the project, then reload the spreadsheet
 *   4. A "🛠 Data Maintenance" menu will appear on next open
 *   5. Menu -> "Install Daily Auto-Maintenance" (one-time) to schedule
 *      a nightly sweep. onEdit() also does light fixes in real time.
 *
 * NOTE ON THE TEXT-FORMAT FIX
 *   Setting a column to Text format only protects values typed AFTER
 *   the format is applied. It cannot restore a leading zero that a
 *   phone/ID number already lost before this script ran. Run
 *   "Fix Column Formats" once immediately after install, then the
 *   onEdit hook keeps new entries safe going forward.
 *******************************************************************/

const CONFIG = {
  SHEET_NAME: 'Master Data',
  REF_SHEET_NAME: '_REFERENCE',
  SETTINGS_SHEET_NAME: 'Settings',
  STAFF_SHEET_NAME: 'Staff Permissions',
  IMPORT_LOG_SHEET_NAME: 'Farmers Upload Log',
  HEADER_ROW: 3,          // row with field names (e.g. "National ID")
  DATA_START_ROW: 5,      // first row of real data
  MAX_ROW: 504,           // template's pre-built row count
  BUFFER_ROWS: 100,       // keep this many empty rows ahead pre-formatted

  // Never use physical column numbers for Master Data. Staff may insert
  // useful business columns (for example Current Pipeline State), so every
  // operation resolves the current column from the row-3 header instead.
  HEADER_ALIASES: {
    NO: ['No.', 'No'], NAME: ['Customer Name', 'Name'], NATIONAL_ID: ['National ID', 'ID No.', 'ID No'],
    PHONE1: ['Primary Phone', 'Mobile No', 'Phone'], PHONE2: ['Secondary Phone', 'Alternative Phone'],
    COUNTY: ['County'], CONSTITUENCY: ['Constituency', 'Sub-County', 'Sub County'], VILLAGE: ['Village'],
    LEAD_SOURCE: ['Lead Source'], HB_AGENT: ['HB Sales Person', 'HB Agent'], HBG_VISIT_DATE: ['HBG Visit Date', 'Sign Date'],
    HBG_COMMENT: ['HBG Visit Comment', 'HBG Comment'], JAWABU_VISIT_DATE: ['JBL Visit Date', 'Jawabu Visit Date'],
    BRO: ['JBL Officer', 'BRO'], JAWABU_OUTCOME: ['Jawabu Comment After Visit', 'JBL Visit Status'],
    ADD_COMMENTS: ['Additional Comments'], CREDIT_DECISION: ['Credit Decision'],
    HBG_DEPOSIT_DATE: ['Deposit Date to HBG'], HB_DEPOSIT_PAID: ['Deposit Paid to HB', 'Deposit Paid to HBG'],
    REQUISITION_DATE: ['Jawabu Requisition Date', 'Requisition Date'], ORDER_NO: ['Order No.', 'Order No'],
    MODE_OF_PAYMENT: ['Mode of Payment'], LOAN_REPAY_START: ['Loan Repayment Start Date'],
    INVOICE_NO: ['Invoice No.', 'Invoice Number'], INVOICE_DATE: ['Invoice Date'], INVOICE_AMT: ['Invoice Amount'],
    DISCOUNT: ['Discount'], PAYMENT: ['Payment'], BALANCE_DUE: ['Balance Due'], INSTALL_STATUS: ['Installation Status'],
    INSTALL_DATE: ['Installation Date'], SERIAL_NO: ['Serial No.', 'Serial Number'], READINESS: ['Readiness'],
    PENDING_INSTALL_COMMENT: ['Pending Installation Comment'], INSTALL_REPORT: ['Installation Report'],
    COMMISSION_STATUS: ['Commission Status'], COMMISSION_DATE: ['Commission Date'],
    PENDING_COMMISSION_COMMENT: ['Pending Commission Comment'], CS_REMARKS: ['CS Remarks'], SLA_FLAG: ['SLA Flag'],
    CLIENT_SEQ: ['Client Unit Sequence'], REPEAT_CLIENT: ['Repeat Client?'], DUPLICATE_FLAG: ['Duplicate Flag'],
    CURRENT_PIPELINE_STATE: ['Current Pipeline State'],
    MASTER_RECORD_ID: ['Master Record ID'], IMPORT_BATCH_ID: ['Import Batch ID'], SOURCE_FILENAME: ['Source Filename'],
    SOURCE_ROW: ['Source Row'], DUPLICATE_KEY: ['Duplicate Key'], IMPORT_STATUS: ['Import Status'],
    REVIEW_NOTES: ['Review Notes'], REVIEWED_BY: ['Reviewed By'], REVIEWED_AT: ['Reviewed At'],
    LAST_UPDATED_AT: ['Last Updated At']
  },

  SYSTEM_COL_KEYS: [
    'MASTER_RECORD_ID', 'IMPORT_BATCH_ID', 'SOURCE_FILENAME', 'SOURCE_ROW',
    'DUPLICATE_KEY', 'IMPORT_STATUS', 'REVIEW_NOTES', 'REVIEWED_BY',
    'REVIEWED_AT', 'LAST_UPDATED_AT'
  ],

  SYSTEM_HEADERS: {
    MASTER_RECORD_ID: 'Master Record ID',
    IMPORT_BATCH_ID: 'Import Batch ID',
    SOURCE_FILENAME: 'Source Filename',
    SOURCE_ROW: 'Source Row',
    DUPLICATE_KEY: 'Duplicate Key',
    IMPORT_STATUS: 'Import Status',
    REVIEW_NOTES: 'Review Notes',
    REVIEWED_BY: 'Reviewed By',
    REVIEWED_AT: 'Reviewed At',
    LAST_UPDATED_AT: 'Last Updated At'
  },

  BACKEND_OWNED_COL_KEYS: ['CURRENT_PIPELINE_STATE', 'ADD_COMMENTS'],

  // Columns that must always be stored as text (leading zeros, alphanumerics)
  TEXT_COLS: ['NATIONAL_ID', 'PHONE1', 'PHONE2', 'INVOICE_NO', 'SERIAL_NO'],

  // Columns that get trimmed / case-normalised on maintenance
  TIDY_COLS: ['NAME', 'NATIONAL_ID', 'COUNTY', 'CONSTITUENCY', 'VILLAGE'],
  UPPERCASE_COLS: ['COUNTY', 'CONSTITUENCY'],

  // Dropdown source ranges on _REFERENCE, keyed by target column
  DROPDOWNS: [
    { col: 'LEAD_SOURCE',       ref: 'A2:A3'  },
    { col: 'MODE_OF_PAYMENT',   ref: 'B2:B3'  },
    { col: 'CREDIT_DECISION',   ref: 'C2:C6'  },
    { col: 'JAWABU_OUTCOME',    ref: 'D2:D14' },
    { col: 'INSTALL_STATUS',    ref: 'E2:E6'  },
    { col: 'READINESS',         ref: 'F2:F5'  },
    { col: 'INSTALL_REPORT',    ref: 'G2:G4'  },
    { col: 'COMMISSION_STATUS', ref: 'H2:H3'  },
    { col: 'CS_REMARKS',        ref: 'I2:I5'  }
  ]
};

/* ============================== MENU ============================== */

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('🛠 Data Maintenance')
    .addItem('▶ Run Full Maintenance Now', 'runFullMaintenance')
    .addSeparator()
    .addItem('Reapply Dropdowns', 'reapplyDropdowns')
    .addItem('Fix Column Formats (Text)', 'enforceColumnFormats')
    .addItem('Refresh Auto Formulas', 'refreshFormulas')
    .addItem('Tidy Text (trim / case)', 'tidyTextColumns')
    .addItem('Normalize Phone Numbers', 'normalisePhoneColumns')
    .addItem('Flag Duplicates', 'flagDuplicates')
    .addSeparator()
    .addItem('Update Support Tabs / System Columns', 'setupMasterWorkflow')
    .addItem('Hide System Columns', 'hideSystemColumns')
    .addSeparator()
    .addItem('Install Daily Auto-Maintenance', 'createDailyTrigger')
    .addToUi();
}

/* ======================== FULL MAINTENANCE ========================= */

function runFullMaintenance() {
  const sheet = getSheet_();
  const lastRow = getLastDataRow_(sheet);

  ensureHeaders_(sheet);
  setupSupportTabs();
  hideSystemColumns(sheet);
  enforceColumnFormats(sheet, lastRow);
  reapplyDropdowns(sheet, lastRow);
  refreshFormulas(sheet, lastRow);
  tidyTextColumns(sheet, lastRow);
  normalisePhoneColumns(sheet, lastRow);
  flagDuplicates(sheet, lastRow);

  sheet.getRange(1, 1).setNote(
    'Last full maintenance run: ' + new Date().toLocaleString()
  );
  Logger.log('Full maintenance complete through row ' + lastRow);
}

/* ============================ DROPDOWNS ============================ */

function reapplyDropdowns(sheet, lastRow) {
  ({ sheet, lastRow } = resolveArgs_(sheet, lastRow));
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const refSheet = ss.getSheetByName(CONFIG.REF_SHEET_NAME);
  if (!refSheet) throw new Error(`Sheet "${CONFIG.REF_SHEET_NAME}" not found.`);

  const targetLastRow = Math.max(lastRow + CONFIG.BUFFER_ROWS, CONFIG.MAX_ROW);
  ensureCapacity_(sheet, targetLastRow);

  CONFIG.DROPDOWNS.forEach(dd => {
    const colIndex = col_(sheet, dd.col);
    const targetRange = sheet.getRange(
      CONFIG.DATA_START_ROW, colIndex,
      targetLastRow - CONFIG.DATA_START_ROW + 1, 1
    );
    const rule = SpreadsheetApp.newDataValidation()
      .requireValueInRange(refSheet.getRange(dd.ref), true)
      .setAllowInvalid(false)
      .setHelpText('Select a value from the list.')
      .build();
    targetRange.setDataValidation(rule);
  });

  Logger.log('Dropdowns reapplied through row ' + targetLastRow);
}

/* ========================= COLUMN FORMATS =========================== */

function enforceColumnFormats(sheet, lastRow) {
  ({ sheet, lastRow } = resolveArgs_(sheet, lastRow));
  const targetLastRow = Math.max(lastRow + CONFIG.BUFFER_ROWS, CONFIG.MAX_ROW);
  ensureCapacity_(sheet, targetLastRow);

  CONFIG.TEXT_COLS.concat(CONFIG.SYSTEM_COL_KEYS).forEach(key => {
    const colIndex = col_(sheet, key);
    sheet.getRange(
      CONFIG.DATA_START_ROW, colIndex,
      targetLastRow - CONFIG.DATA_START_ROW + 1, 1
    ).setNumberFormat('@');
  });

  Logger.log('Text formats enforced through row ' + targetLastRow);
}

/* ============================ FORMULAS =============================== */

function refreshFormulas(sheet, lastRow) {
  ({ sheet, lastRow } = resolveArgs_(sheet, lastRow));
  const targetLastRow = Math.max(lastRow + CONFIG.BUFFER_ROWS, CONFIG.MAX_ROW);
  ensureCapacity_(sheet, targetLastRow);
  if (targetLastRow < CONFIG.DATA_START_ROW) return;
  const n = targetLastRow - CONFIG.DATA_START_ROW + 1;

  const L = {
    name:          colLetter_(col_(sheet, 'NAME')),
    installDate:   colLetter_(col_(sheet, 'INSTALL_DATE')),
    installStatus: colLetter_(col_(sheet, 'INSTALL_STATUS')),
    invoiceNo:     colLetter_(col_(sheet, 'INVOICE_NO')),
    reqDate:       colLetter_(col_(sheet, 'REQUISITION_DATE')),
    natId:         colLetter_(col_(sheet, 'NATIONAL_ID')),
    clientSeq:     colLetter_(col_(sheet, 'CLIENT_SEQ'))
  };

  const noFormulas = [], wFormulas = [], anFormulas = [], aoFormulas = [], apFormulas = [];
  for (let r = CONFIG.DATA_START_ROW; r <= targetLastRow; r++) {
    // No. auto-increments only populated customer rows; survives row inserts/deletions.
    noFormulas.push([`=IF($${L.name}${r}="","",COUNTA($${L.name}$${CONFIG.DATA_START_ROW}:$${L.name}${r}))`]);

    // Loan Repayment Start Date = Installation Date
    wFormulas.push([`=IFERROR(IF(NOT(ISBLANK(${L.installDate}${r})),${L.installDate}${r},""),"")`]);

    // SLA / Invoice Flag — anchored on Requisition Date; adjust if your
    // SLA clock should start elsewhere (e.g. Installation or Invoice Date)
    anFormulas.push([
      `=IF(AND(${L.installStatus}${r}="Installed",ISBLANK(${L.invoiceNo}${r})),"MISSING INVOICE",` +
      `IFERROR(IF(ISBLANK(${L.reqDate}${r}),"",IF(TODAY()-${L.reqDate}${r}>90,"BREACHED",` +
      `IF(TODAY()-${L.reqDate}${r}>60,"AT RISK",""))),""))`
    ]);

    // Client Unit Sequence
    aoFormulas.push([`=IF(${L.natId}${r}="","",COUNTIF($${L.natId}$${CONFIG.DATA_START_ROW}:${L.natId}${r},${L.natId}${r}))`]);

    // Repeat Client?
    apFormulas.push([`=IF(${L.clientSeq}${r}="","",IF(${L.clientSeq}${r}>1,"Yes","No"))`]);
  }

  sheet.getRange(CONFIG.DATA_START_ROW, col_(sheet, 'NO'), n, 1).setFormulas(noFormulas);
  sheet.getRange(CONFIG.DATA_START_ROW, col_(sheet, 'LOAN_REPAY_START'), n, 1).setFormulas(wFormulas);
  sheet.getRange(CONFIG.DATA_START_ROW, col_(sheet, 'SLA_FLAG'), n, 1).setFormulas(anFormulas);
  sheet.getRange(CONFIG.DATA_START_ROW, col_(sheet, 'CLIENT_SEQ'), n, 1).setFormulas(aoFormulas);
  sheet.getRange(CONFIG.DATA_START_ROW, col_(sheet, 'REPEAT_CLIENT'), n, 1).setFormulas(apFormulas);

  Logger.log('Formulas refreshed through row ' + targetLastRow);
}

/* ============================ TEXT TIDY =============================== */

function tidyTextColumns(sheet, lastRow) {
  ({ sheet, lastRow } = resolveArgs_(sheet, lastRow));
  if (lastRow < CONFIG.DATA_START_ROW) return;
  const n = lastRow - CONFIG.DATA_START_ROW + 1;

  CONFIG.TIDY_COLS.forEach(key => {
    const colIndex = col_(sheet, key);
    const range = sheet.getRange(CONFIG.DATA_START_ROW, colIndex, n, 1);
    const values = range.getValues();
    const upper = CONFIG.UPPERCASE_COLS.includes(key);

    const cleaned = values.map(row => {
      let v = row[0];
      if (typeof v === 'string') {
        v = v.trim().replace(/\s+/g, ' ');
        if (upper) v = v.toUpperCase();
      }
      return [v];
    });
    range.setValues(cleaned);
  });

  Logger.log('Text columns tidied through row ' + lastRow);
}

/* =========================== DUPLICATE FLAGS ============================ */
/*
 * Two independent checks, combined into one flag column:
 *  1. Same National ID + same Order No. (or same Visit Date if no Order
 *     No. yet) appearing on more than one row = likely accidental
 *     double-entry, NOT a legitimate second unit (that's what the
 *     Client Unit Sequence / Repeat Client columns already track).
 *  2. Same phone number attached to two different National IDs =
 *     probable typo in one of the IDs, worth a manual check.
 */
function flagDuplicates(sheet, lastRow) {
  ({ sheet, lastRow } = resolveArgs_(sheet, lastRow));
  ensureHeaders_(sheet);
  if (lastRow < CONFIG.DATA_START_ROW) return;
  const n = lastRow - CONFIG.DATA_START_ROW + 1;

  const ids    = sheet.getRange(CONFIG.DATA_START_ROW, col_(sheet, 'NATIONAL_ID'), n, 1).getValues();
  const orders = sheet.getRange(CONFIG.DATA_START_ROW, col_(sheet, 'ORDER_NO'), n, 1).getValues();
  const visits = sheet.getRange(CONFIG.DATA_START_ROW, col_(sheet, 'JAWABU_VISIT_DATE'), n, 1).getValues();
  const phones = sheet.getRange(CONFIG.DATA_START_ROW, col_(sheet, 'PHONE1'), n, 1).getValues();

  const flags = new Array(n).fill('');
  const rowKeyMap = {};
  const phoneToIds = {};

  for (let i = 0; i < n; i++) {
    const id = String(ids[i][0] || '').trim();
    if (!id) continue;

    const order = String(orders[i][0] || '').trim();
    const visitRaw = visits[i][0];
    const visit = visitRaw instanceof Date ? visitRaw.getTime() : String(visitRaw || '');
    const key = order ? `${id}|${order}` : `${id}|${visit}`;
    (rowKeyMap[key] = rowKeyMap[key] || []).push(i);

    const phone = String(phones[i][0] || '').trim();
    if (phone) {
      (phoneToIds[phone] = phoneToIds[phone] || new Set()).add(id);
    }
  }

  Object.values(rowKeyMap).forEach(rows => {
    if (rows.length > 1) {
      rows.forEach(i => {
        flags[i] = 'Possible duplicate entry (same ID + Order No./Visit Date)';
      });
    }
  });

  Object.entries(phoneToIds).forEach(([phone, idSet]) => {
    if (idSet.size > 1) {
      for (let i = 0; i < n; i++) {
        if (String(phones[i][0] || '').trim() === phone) {
          flags[i] = flags[i]
            ? flags[i] + '; phone reused across different IDs'
            : 'Phone number reused across different IDs — check for a typo';
        }
      }
    }
  });

  const flagRange = sheet.getRange(CONFIG.DATA_START_ROW, col_(sheet, 'DUPLICATE_FLAG'), n, 1);
  flagRange.setValues(flags.map(f => [f]));
  flagRange.setBackgrounds(flags.map(f => [f ? '#FCE8E6' : null]));

  Logger.log('Duplicate flags refreshed through row ' + lastRow);
}

/* ============================== onEdit =============================== */
/*
 * Lightweight real-time hook — keeps freshly typed rows safe without
 * waiting for the nightly sweep. Runs as a simple trigger (no extra
 * authorization needed) since it only touches this same spreadsheet.
 */
function onEdit(e) {
  try {
    if (!e || !e.range) return;
    const sheet = e.range.getSheet();
    if (sheet.getName() !== CONFIG.SHEET_NAME) return;

    const row = e.range.getRow();
    const col = e.range.getColumn();
    if (row < CONFIG.DATA_START_ROW) return;

    // Force text format on the edited cell if it's in a text-required column
    CONFIG.TEXT_COLS.forEach(key => {
      if (col_(sheet, key) === col) {
        e.range.setNumberFormat('@');
      }
    });

    if ([col_(sheet, 'PHONE1'), col_(sheet, 'PHONE2')].includes(col)) {
      const normalized = normalizeKenyaPhone_(e.range.getValue());
      if (normalized) e.range.setValue(normalized);
    }

    // Re-run duplicate check only when a key field changed
    const watchCols = [
      col_(sheet, 'NATIONAL_ID'), col_(sheet, 'ORDER_NO'),
      col_(sheet, 'JAWABU_VISIT_DATE'), col_(sheet, 'PHONE1')
    ];
    if (watchCols.includes(col)) {
      flagDuplicates();
    }
  } catch (err) {
    Logger.log('onEdit error: ' + err);
  }
}


/* ======================= MASTER WORKFLOW SETUP ======================= */

function setupMasterWorkflow() {
  const sheet = getSheet_();
  ensureHeaders_(sheet);
  setupSupportTabs();
  hideSystemColumns(sheet);
  normalisePhoneColumns(sheet, getLastDataRow_(sheet));
  SpreadsheetApp.getUi().alert('Master workflow tabs, system columns, and phone formats were updated without clearing existing rows.');
}

function setupSupportTabs() {
  ensureSheetWithHeaders_(CONFIG.SETTINGS_SHEET_NAME, ['Setting', 'Value', 'Notes'], [
    ['master_sheet_name', CONFIG.SHEET_NAME, 'Django /farmup target tab'],
    ['master_header_row', CONFIG.HEADER_ROW, 'Header row with field names'],
    ['master_data_start_row', CONFIG.DATA_START_ROW, 'First real data row'],
    ['master_import_log_sheet_name', CONFIG.IMPORT_LOG_SHEET_NAME, 'Upload audit tab'],
    ['phone_format', '254XXXXXXXXX', 'Primary/secondary phone normalization target'],
    ['system_columns_start', 'Header resolved', 'Hidden Django sync metadata is resolved by header name']
  ]);
  ensureSheetWithHeaders_(CONFIG.STAFF_SHEET_NAME, [
    'Name', 'Email', 'Role', 'Branch / County', 'Active', 'Can Run Maintenance', 'Notify On'
  ], [[
    'Example Admin', 'admin@example.com', 'Owner', 'All', 'Yes', 'Yes', 'import_errors,duplicates'
  ]]);
  ensureSheetWithHeaders_(CONFIG.IMPORT_LOG_SHEET_NAME, [
    'Batch ID', 'Source Filename', 'Group ID', 'Uploaded By', 'Committed At',
    'Total Rows', 'Created', 'Updated', 'Conflicts', 'Errors'
  ], []);
}

function ensureSheetWithHeaders_(name, headers, sampleRows) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(name);
  if (!sheet) sheet = ss.insertSheet(name);

  if (headers.length > sheet.getMaxColumns()) {
    sheet.insertColumnsAfter(sheet.getMaxColumns(), headers.length - sheet.getMaxColumns());
  }

  // Non-destructive setup: keep all existing rows, only refresh row 1 headers
  // and append sample rows when the tab is genuinely empty.
  sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  sheet.setFrozenRows(1);
  sheet.getRange(1, 1, 1, headers.length)
    .setFontWeight('bold')
    .setBackground('#1F4E78')
    .setFontColor('#FFFFFF');

  const hasDataRows = sheet.getLastRow() > 1 && sheet
    .getRange(2, 1, sheet.getLastRow() - 1, Math.min(headers.length, sheet.getMaxColumns()))
    .getValues()
    .some(row => row.some(value => String(value || '').trim()));

  if (!hasDataRows && sampleRows && sampleRows.length) {
    sheet.getRange(2, 1, sampleRows.length, headers.length).setValues(sampleRows);
  }
}

function hideSystemColumns(sheet) {
  ({ sheet } = resolveArgs_(sheet, null));
  CONFIG.SYSTEM_COL_KEYS.forEach(key => {
    const index = col_(sheet, key, false);
    if (index) sheet.hideColumns(index);
  });
  protectBackendOwnedColumns_(sheet);
}

function normalisePhoneColumns(sheet, lastRow) {
  ({ sheet, lastRow } = resolveArgs_(sheet, lastRow));
  if (lastRow < CONFIG.DATA_START_ROW) return;
  const n = lastRow - CONFIG.DATA_START_ROW + 1;
  [col_(sheet, 'PHONE1'), col_(sheet, 'PHONE2')].forEach(colIndex => {
    const range = sheet.getRange(CONFIG.DATA_START_ROW, colIndex, n, 1);
    const values = range.getValues().map(row => [normalizeKenyaPhone_(row[0]) || row[0]]);
    range.setNumberFormat('@');
    range.setValues(values);
  });
}

function normalizeKenyaPhone_(value) {
  let digits = String(value || '').replace(/\D/g, '');
  if (!digits) return '';
  if (digits.startsWith('254') && digits.length === 12) return digits;
  if (digits.startsWith('0') && digits.length === 10) return '254' + digits.slice(1);
  if (digits.startsWith('7') && digits.length === 9) return '254' + digits;
  if (digits.startsWith('1') && digits.length === 9) return '254' + digits;
  return String(value || '').trim();
}

/* ========================== SCHEDULED TRIGGER ========================== */

function createDailyTrigger() {
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === 'runFullMaintenance') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('runFullMaintenance')
    .timeBased()
    .everyDays(1)
    .atHour(5)
    .create();
  SpreadsheetApp.getUi().alert('Daily maintenance scheduled for ~5 AM.');
}

/* =============================== HELPERS =============================== */

function getSheet_() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(CONFIG.SHEET_NAME);
  if (!sheet) throw new Error(`Sheet "${CONFIG.SHEET_NAME}" not found.`);
  return sheet;
}

function resolveArgs_(sheet, lastRow) {
  if (!sheet) sheet = getSheet_();
  if (lastRow === undefined || lastRow === null) lastRow = getLastDataRow_(sheet);
  return { sheet, lastRow };
}

function getLastDataRow_(sheet) {
  const numRows = sheet.getMaxRows() - CONFIG.DATA_START_ROW + 1;
  if (numRows <= 0) return CONFIG.DATA_START_ROW - 1;
  const values = sheet.getRange(CONFIG.DATA_START_ROW, col_(sheet, 'NAME'), numRows, 1).getValues();
  let lastRow = CONFIG.DATA_START_ROW - 1;
  values.forEach((row, i) => {
    if (row[0] !== '' && row[0] !== null) lastRow = CONFIG.DATA_START_ROW + i;
  });
  return lastRow;
}

function ensureCapacity_(sheet, neededRow) {
  const maxRows = sheet.getMaxRows();
  if (neededRow > maxRows) {
    sheet.insertRowsAfter(maxRows, neededRow - maxRows);
  }
}

function ensureHeaders_(sheet) {
  // This script must never repair headers by writing to a presumed column.
  // A human may have inserted a business column; report missing headers rather
  // than moving or overwriting data in a regulated operational register.
  const required = [
    'NAME', 'NATIONAL_ID', 'PHONE1', 'JAWABU_VISIT_DATE', 'ORDER_NO',
    'CREDIT_DECISION', 'REPEAT_CLIENT', 'DUPLICATE_FLAG'
  ];
  const missing = required.filter(key => !col_(sheet, key, false));
  if (missing.length) {
    throw new Error('Master Data maintenance stopped: missing required header(s): ' +
      missing.map(key => CONFIG.HEADER_ALIASES[key][0]).join(', ') +
      '. Restore the exact header text; do not move business columns.');
  }
}

function normalizeHeader_(value) {
  return String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim().replace(/\s+/g, ' ');
}

function headerMap_(sheet) {
  const values = sheet.getRange(CONFIG.HEADER_ROW, 1, 1, sheet.getLastColumn()).getDisplayValues()[0];
  const map = {};
  values.forEach((value, index) => {
    const normalized = normalizeHeader_(value);
    if (normalized && !map[normalized]) map[normalized] = index + 1;
  });
  return map;
}

function col_(sheet, key, required) {
  if (required === undefined) required = true;
  const aliases = CONFIG.HEADER_ALIASES[key] || [];
  const map = headerMap_(sheet);
  for (let i = 0; i < aliases.length; i++) {
    const index = map[normalizeHeader_(aliases[i])];
    if (index) return index;
  }
  if (required) throw new Error('Master Data header not found for ' + key + ' (' + aliases.join(' / ') + ').');
  return 0;
}

function protectBackendOwnedColumns_(sheet) {
  CONFIG.BACKEND_OWNED_COL_KEYS.forEach(key => {
    const index = col_(sheet, key, false);
    if (!index) return;
    const range = sheet.getRange(CONFIG.DATA_START_ROW, index, Math.max(1, sheet.getMaxRows() - CONFIG.DATA_START_ROW + 1), 1);
    const existing = range.getProtections(SpreadsheetApp.ProtectionType.RANGE)
      .some(protection => protection.getDescription() === 'JBL backend-owned: ' + key);
    if (!existing) {
      // Warning-only is safe for the configured Django service account. It
      // clearly prevents accidental staff editing without locking the
      // integration out of its own synchronized publication column.
      range.protect().setDescription('JBL backend-owned: ' + key).setWarningOnly(true);
    }
    sheet.getRange(CONFIG.HEADER_ROW + 1, index).setNote('BACKEND-OWNED: Django publishes the current state. Do not edit manually.');
  });
}

function colLetter_(colIndex) {
  let letter = '';
  while (colIndex > 0) {
    const rem = (colIndex - 1) % 26;
    letter = String.fromCharCode(65 + rem) + letter;
    colIndex = Math.floor((colIndex - 1) / 26);
  }
  return letter;
}
