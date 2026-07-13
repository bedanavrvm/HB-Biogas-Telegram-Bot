/**
 * JBL TAT Tracker - Google Sheets setup and validation script
 *
 * Purpose
 * -------
 * This script prepares the TAT tracker workbook used by the Django/Telegram
 * Mini App workflow. It intentionally does NOT create cases, assign case IDs,
 * stamp workflow timestamps, enforce staff permissions, send emails, or process
 * web app submissions. Django owns that logic.
 *
 * Use this script for workbook hygiene only:
 * - create/format expected tracker tabs
 * - set dropdown validations
 * - set TAT formulas
 * - freeze header rows
 * - add filters and notes
 * - hide/protect support areas lightly
 * - rebuild validations after manual sheet edits
 *
 * Install
 * -------
 * 1. Open the TAT tracker Google Sheet.
 * 2. Extensions -> Apps Script.
 * 3. Paste this file into Code.gs or a new file.
 * 4. Save.
 * 5. Run setupTatTrackerWorkbook().
 * 6. Grant permissions.
 */

const TAT_CONFIG = {
  DATA_START_ROW: 5,
  DEFAULT_MAX_ROWS: 2000,
  DATE_TIME_FORMAT: 'dd-mmm-yyyy hh:mm',
  MONEY_FORMAT: '#,##0',
  TAT_HOURS_TARGET: 336,
  TRACKER_SHEETS: [
    'TRACKER-SME',
    'TRACKER-LOGBOOK',
    'TRACKER-MJENGO',
    'TRACKER-KILIMO',
    'TRACKER-MICRO-ASSET',
  ],
  SUPPORT_SHEETS: [
    'CASE_INDEX',
    'AUDIT LOG',
    'DASHBOARD',
  ],
  DROPDOWNS: {
    BRANCHES: [
      'Corporate',
      'Thika Road',
      'East Nairobi',
      'West Nairobi',
      'Nakuru',
      'Embu',
      'Limuru',
    ],
    DECISION: ['Approved', 'Rejected', 'Deferred'],
    SANCTIONS: ['Pending', 'Met', 'Not Met'],
    REGISTER: ['10:00am', '1:00pm', '3:30pm'],
    REGISTER_APPROVED: ['Approved', 'Pending'],
    STATUS: ['Active', 'Disbursed', 'Rejected', 'Declined', 'Deferred', 'Stalled', 'Pending Docs'],
  },
};

const PRODUCT_LAYOUTS = {
  'TRACKER-SME': {
    title: 'TAT TRACKER - SME',
    maxAmount: null,
    minAmount: 5000,
    headers: [
      'Case ID', 'Client Name', 'Branch', 'BRO Name', 'Amount',
      'Case Created', 'MPESA Sent to Admin', 'MPESA Verified and Sent to CA',
      'Credit Analysis Sent', 'BRO Response to CA', 'BM Response to CA',
      'BRO Applied Loan on System', 'Disbursement Register', 'Register Timestamp',
      'Register Approved', 'Finance Disbursement', 'Status', 'Remarks / Delays',
      'TAT Hours', 'TAT Days'
    ],
    cols: {
      amount: 5,
      created: 6,
      register: 13,
      registerTs: 14,
      registerApproved: 15,
      disbursement: 16,
      status: 17,
      remarks: 18,
      tatHours: 19,
      tatDays: 20,
    },
    dateCols: [6, 7, 8, 9, 10, 11, 12, 14, 16],
    stageCols: [6, 7, 8, 9, 10, 11, 12, 14, 16],
  },
  'TRACKER-LOGBOOK': {
    title: 'TAT TRACKER - LOGBOOK',
    maxAmount: 500000,
    minAmount: 50000,
    headers: [
      'Case ID', 'Client Name', 'Branch', 'BRO Name', 'Amount',
      'Case Created', 'MPESA Sent to Admin', 'MPESA Verified and Sent to CA',
      'Credit Analysis Sent', 'BRO Response to CA', 'Valuation Ready',
      'BM TAT Request Sent', 'TAT Scheduled', 'TAT Held', 'Decision',
      'Decision Timestamp', 'Minutes Shared', 'Sanctions', 'Sanctions Timestamp',
      'BRO Applied on System', 'Disbursement Register', 'Register Timestamp',
      'Register Approved', 'Finance Disbursement', 'Status', 'Remarks / Delays',
      'TAT Hours', 'TAT Days'
    ],
    cols: {
      amount: 5,
      created: 6,
      decision: 15,
      decisionTs: 16,
      sanctions: 18,
      sanctionsTs: 19,
      register: 21,
      registerTs: 22,
      registerApproved: 23,
      disbursement: 24,
      status: 25,
      remarks: 26,
      tatHours: 27,
      tatDays: 28,
    },
    dateCols: [6, 7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 20, 22, 24],
    stageCols: [6, 7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 20, 22, 24],
  },
  'TRACKER-MJENGO': null,
  'TRACKER-KILIMO': null,
  'TRACKER-MICRO-ASSET': null,
};

PRODUCT_LAYOUTS['TRACKER-MJENGO'] = noValuationLayout('TAT TRACKER - MJENGO', 50000, 300000);
PRODUCT_LAYOUTS['TRACKER-KILIMO'] = noValuationLayout('TAT TRACKER - KILIMO', 50000, 300000);
PRODUCT_LAYOUTS['TRACKER-MICRO-ASSET'] = noValuationLayout('TAT TRACKER - MICRO-ASSET', 50000, 300000);

function noValuationLayout(title, minAmount, maxAmount) {
  return {
    title: title,
    minAmount: minAmount,
    maxAmount: maxAmount,
    headers: [
      'Case ID', 'Client Name', 'Branch', 'BRO Name', 'Amount',
      'Case Created', 'MPESA Sent to Admin', 'MPESA Verified and Sent to CA',
      'Credit Analysis Sent', 'BRO Response to CA', 'BM TAT Request Sent',
      'TAT Scheduled', 'TAT Held', 'Decision', 'Decision Timestamp',
      'Minutes Shared', 'Sanctions', 'Sanctions Timestamp',
      'BRO Applied on System', 'Disbursement Register', 'Register Timestamp',
      'Register Approved', 'Finance Disbursement', 'Status', 'Remarks / Delays',
      'TAT Hours', 'TAT Days'
    ],
    cols: {
      amount: 5,
      created: 6,
      decision: 14,
      decisionTs: 15,
      sanctions: 17,
      sanctionsTs: 18,
      register: 20,
      registerTs: 21,
      registerApproved: 22,
      disbursement: 23,
      status: 24,
      remarks: 25,
      tatHours: 26,
      tatDays: 27,
    },
    dateCols: [6, 7, 8, 9, 10, 11, 12, 13, 15, 16, 18, 19, 21, 23],
    stageCols: [6, 7, 8, 9, 10, 11, 12, 13, 15, 16, 18, 19, 21, 23],
  };
}

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('TAT Tracker')
    .addItem('Setup / refresh workbook', 'setupTatTrackerWorkbook')
    .addItem('Refresh validations only', 'refreshTatValidations')
    .addItem('Refresh formulas only', 'refreshTatFormulas')
    .addItem('Create support tabs', 'setupTatSupportTabs')
    .addSeparator()
    .addItem('Show setup notes', 'showTatSetupNotes')
    .addToUi();
}

function setupTatTrackerWorkbook() {
  const ss = SpreadsheetApp.getActive();
  TAT_CONFIG.TRACKER_SHEETS.forEach(function(sheetName) {
    const sheet = getOrCreateSheet_(ss, sheetName);
    setupTrackerSheet_(sheet, PRODUCT_LAYOUTS[sheetName]);
  });
  setupTatSupportTabs();
  SpreadsheetApp.getUi().alert('TAT Tracker setup complete. Django/Mini App remains the source of workflow writes.');
}

function refreshTatValidations() {
  const ss = SpreadsheetApp.getActive();
  TAT_CONFIG.TRACKER_SHEETS.forEach(function(sheetName) {
    const sheet = ss.getSheetByName(sheetName);
    if (sheet) applyValidations_(sheet, PRODUCT_LAYOUTS[sheetName]);
  });
  SpreadsheetApp.getUi().alert('TAT Tracker validations refreshed.');
}

function refreshTatFormulas() {
  const ss = SpreadsheetApp.getActive();
  TAT_CONFIG.TRACKER_SHEETS.forEach(function(sheetName) {
    const sheet = ss.getSheetByName(sheetName);
    if (sheet) applyTatFormulas_(sheet, PRODUCT_LAYOUTS[sheetName]);
  });
  SpreadsheetApp.getUi().alert('TAT Tracker formulas refreshed.');
}

function setupTatSupportTabs() {
  const ss = SpreadsheetApp.getActive();
  setupCaseIndex_(getOrCreateSheet_(ss, 'CASE_INDEX'));
  setupAuditLog_(getOrCreateSheet_(ss, 'AUDIT LOG'));
  setupDashboard_(getOrCreateSheet_(ss, 'DASHBOARD'));
}

function setupTrackerSheet_(sheet, layout) {
  ensureRowsAndColumns_(sheet, TAT_CONFIG.DEFAULT_MAX_ROWS, layout.headers.length);
  mergedTitleRange_(sheet, layout.headers.length)
    .setValue(layout.title)
    .setFontWeight('bold')
    .setFontSize(13)
    .setHorizontalAlignment('center')
    .setBackground('#1f4e3d')
    .setFontColor('#ffffff');
  sheet.getRange(2, 1, 1, layout.headers.length)
    .setValues([layout.headers])
    .setFontWeight('bold')
    .setWrap(true)
    .setVerticalAlignment('middle')
    .setBackground('#d9ead3')
    .setFontColor('#1f1f1f');
  sheet.getRange(3, 1, 1, layout.headers.length)
    .setValues([roleRow_(layout.headers)])
    .setFontStyle('italic')
    .setFontSize(9)
    .setWrap(true)
    .setBackground('#f3f6f4')
    .setFontColor('#555555');
  sheet.setFrozenRows(3);
  sheet.setFrozenColumns(2);
  sheet.getRange(1, 1, Math.max(sheet.getMaxRows(), TAT_CONFIG.DEFAULT_MAX_ROWS), layout.headers.length).setVerticalAlignment('middle');
  sheet.getRange(4, 1, 1, layout.headers.length).setValues([helperRow_(layout)]).setFontSize(9).setFontColor('#777777').setBackground('#fafafa').setWrap(true);
  sheet.getRange(TAT_CONFIG.DATA_START_ROW, 1, TAT_CONFIG.DEFAULT_MAX_ROWS - TAT_CONFIG.DATA_START_ROW + 1, layout.headers.length).setWrap(true);
  sheet.getRange(TAT_CONFIG.DATA_START_ROW, layout.cols.amount, TAT_CONFIG.DEFAULT_MAX_ROWS - TAT_CONFIG.DATA_START_ROW + 1, 1).setNumberFormat(TAT_CONFIG.MONEY_FORMAT);
  layout.dateCols.forEach(function(col) {
    sheet.getRange(TAT_CONFIG.DATA_START_ROW, col, TAT_CONFIG.DEFAULT_MAX_ROWS - TAT_CONFIG.DATA_START_ROW + 1, 1).setNumberFormat(TAT_CONFIG.DATE_TIME_FORMAT);
  });
  applyValidations_(sheet, layout);
  applyTatFormulas_(sheet, layout);
  applyStatusConditionalFormatting_(sheet, layout);
  applyFilter_(sheet, layout.headers.length);
  autoResize_(sheet, layout.headers.length);
}

function applyValidations_(sheet, layout) {
  const rows = TAT_CONFIG.DEFAULT_MAX_ROWS - TAT_CONFIG.DATA_START_ROW + 1;
  const branchRule = listRule_(TAT_CONFIG.DROPDOWNS.BRANCHES, true);
  const statusRule = listRule_(TAT_CONFIG.DROPDOWNS.STATUS, true);
  sheet.getRange(TAT_CONFIG.DATA_START_ROW, 3, rows, 1).setDataValidation(branchRule);
  sheet.getRange(TAT_CONFIG.DATA_START_ROW, layout.cols.status, rows, 1).setDataValidation(statusRule);
  if (layout.cols.decision) sheet.getRange(TAT_CONFIG.DATA_START_ROW, layout.cols.decision, rows, 1).setDataValidation(listRule_(TAT_CONFIG.DROPDOWNS.DECISION, true));
  if (layout.cols.sanctions) sheet.getRange(TAT_CONFIG.DATA_START_ROW, layout.cols.sanctions, rows, 1).setDataValidation(listRule_(TAT_CONFIG.DROPDOWNS.SANCTIONS, true));
  if (layout.cols.register) sheet.getRange(TAT_CONFIG.DATA_START_ROW, layout.cols.register, rows, 1).setDataValidation(listRule_(TAT_CONFIG.DROPDOWNS.REGISTER, true));
  if (layout.cols.registerApproved) sheet.getRange(TAT_CONFIG.DATA_START_ROW, layout.cols.registerApproved, rows, 1).setDataValidation(listRule_(TAT_CONFIG.DROPDOWNS.REGISTER_APPROVED, true));

  const amountBuilder = SpreadsheetApp.newDataValidation();
  if (layout.maxAmount) {
    amountBuilder.requireNumberBetween(layout.minAmount, layout.maxAmount);
  } else {
    amountBuilder.requireNumberGreaterThanOrEqualTo(layout.minAmount);
  }
  const amountRule = amountBuilder
    .setAllowInvalid(false)
    .setHelpText('Amount must be at least KES ' + layout.minAmount + (layout.maxAmount ? ' and not more than KES ' + layout.maxAmount : '') + '.')
    .build();
  sheet.getRange(TAT_CONFIG.DATA_START_ROW, layout.cols.amount, rows, 1).setDataValidation(amountRule);
}

function applyTatFormulas_(sheet, layout) {
  const start = TAT_CONFIG.DATA_START_ROW;
  const rows = TAT_CONFIG.DEFAULT_MAX_ROWS - start + 1;
  const createdCol = colLetter_(layout.cols.created);
  const endCol = colLetter_(layout.cols.disbursement);
  const tatHoursCol = layout.cols.tatHours;
  const tatDaysCol = layout.cols.tatDays;
  const formulasHours = [];
  const formulasDays = [];
  for (let i = 0; i < rows; i++) {
    const row = start + i;
    formulasHours.push([`=IF(OR($${createdCol}${row}="",$${endCol}${row}=""),"",ROUND(($${endCol}${row}-$${createdCol}${row})*24,2))`]);
    formulasDays.push([`=IF(${colLetter_(tatHoursCol)}${row}="","",ROUND(${colLetter_(tatHoursCol)}${row}/24,2))`]);
  }
  sheet.getRange(start, tatHoursCol, rows, 1).setFormulas(formulasHours).setNumberFormat('0.00');
  sheet.getRange(start, tatDaysCol, rows, 1).setFormulas(formulasDays).setNumberFormat('0.00');
}

function applyStatusConditionalFormatting_(sheet, layout) {
  const width = layout.headers.length;
  const range = sheet.getRange(TAT_CONFIG.DATA_START_ROW, 1, TAT_CONFIG.DEFAULT_MAX_ROWS - TAT_CONFIG.DATA_START_ROW + 1, width);
  const status = colLetter_(layout.cols.status);
  const rules = [
    colorRule_(range, `=$${status}${TAT_CONFIG.DATA_START_ROW}="Disbursed"`, '#d9ead3'),
    colorRule_(range, `=$${status}${TAT_CONFIG.DATA_START_ROW}="Rejected"`, '#f4cccc'),
    colorRule_(range, `=$${status}${TAT_CONFIG.DATA_START_ROW}="Declined"`, '#f4cccc'),
    colorRule_(range, `=$${status}${TAT_CONFIG.DATA_START_ROW}="Deferred"`, '#fff2cc'),
    colorRule_(range, `=$${status}${TAT_CONFIG.DATA_START_ROW}="Stalled"`, '#fce5cd'),
    colorRule_(range, `=$${status}${TAT_CONFIG.DATA_START_ROW}="Pending Docs"`, '#d9eaf7'),
  ];
  sheet.setConditionalFormatRules(rules);
}

function setupCaseIndex_(sheet) {
  const headers = ['Case ID', 'Tracker Sheet', 'Row Number', 'Client Name', 'Branch', 'BRO Name', 'Status', 'Created At', 'Last Updated At'];
  setupSimpleSheet_(sheet, 'TAT CASE INDEX', headers, '#274e13');
}

function setupAuditLog_(sheet) {
  const headers = ['Timestamp', 'Actor', 'Tracker Sheet', 'Case ID', 'Row Number', 'Stage', 'New Value', 'Old Value', 'Source'];
  setupSimpleSheet_(sheet, 'TAT AUDIT LOG', headers, '#4c1130');
}

function setupDashboard_(sheet) {
  setupSimpleSheet_(sheet, 'TAT DASHBOARD', ['Metric', 'Value', 'Notes'], '#1c4587');
  sheet.getRange(5, 1, 6, 3).setValues([
    ['Open cases', '=COUNTIF(CASE_INDEX!G:G,"Active")', 'Synced by Django into CASE_INDEX'],
    ['Disbursed', '=COUNTIF(CASE_INDEX!G:G,"Disbursed")', ''],
    ['Rejected / Declined', '=COUNTIF(CASE_INDEX!G:G,"Rejected")+COUNTIF(CASE_INDEX!G:G,"Declined")', ''],
    ['Deferred', '=COUNTIF(CASE_INDEX!G:G,"Deferred")', ''],
    ['Stalled', '=COUNTIF(CASE_INDEX!G:G,"Stalled")', ''],
    ['Pending Docs', '=COUNTIF(CASE_INDEX!G:G,"Pending Docs")', ''],
  ]);
  sheet.autoResizeColumns(1, 3);
}

function setupSimpleSheet_(sheet, title, headers, color) {
  ensureRowsAndColumns_(sheet, TAT_CONFIG.DEFAULT_MAX_ROWS, headers.length);
  mergedTitleRange_(sheet, headers.length).setValue(title).setFontWeight('bold').setFontSize(13).setHorizontalAlignment('center').setBackground(color).setFontColor('#ffffff');
  sheet.getRange(2, 1, 1, headers.length).setValues([headers]).setFontWeight('bold').setWrap(true).setBackground('#eeeeee');
  sheet.setFrozenRows(2);
  applyFilter_(sheet, headers.length, 2);
  sheet.autoResizeColumns(1, headers.length);
}

function showTatSetupNotes() {
  SpreadsheetApp.getUi().alert(
    'TAT Tracker setup notes\n\n' +
    '1. Django/Mini App is the source of workflow writes.\n' +
    '2. Do not add Apps Script triggers that stamp dates or send approvals.\n' +
    '3. Run Setup / refresh workbook after changing columns or adding tabs.\n' +
    '4. Share this spreadsheet with the Render Google service account.'
  );
}

function roleRow_(headers) {
  return headers.map(function(header) {
    if (['Case ID', 'Status', 'TAT Hours', 'TAT Days'].indexOf(header) >= 0) return 'System';
    if (header.indexOf('MPESA Sent') >= 0 || header.indexOf('BRO') >= 0) return 'BRO';
    if (header.indexOf('Verified') >= 0 || header.indexOf('Register') >= 0) return 'Admin';
    if (header.indexOf('Credit Analysis') >= 0) return 'Credit Analyst';
    if (header.indexOf('BM') >= 0 || header.indexOf('Valuation') >= 0) return 'BM';
    if (header.indexOf('TAT Scheduled') >= 0 || header.indexOf('TAT Held') >= 0 || header.indexOf('Minutes') >= 0) return 'Secretary';
    if (header === 'Decision') return 'Chair';
    if (header.indexOf('Sanctions') >= 0 || header.indexOf('Approved') >= 0) return 'Loan Approver';
    if (header.indexOf('Finance') >= 0) return 'Finance';
    return 'Input';
  });
}

function helperRow_(layout) {
  return layout.headers.map(function(header, index) {
    const col = index + 1;
    if (col === 1) return 'Written by Django. Do not edit manually.';
    if (col === 3) return 'Dropdown.';
    if (col === layout.cols.amount) return 'Numeric amount.';
    if (layout.stageCols.indexOf(col) >= 0) return 'Timestamp/stage value written by Mini App.';
    if (col === layout.cols.status) return 'Dropdown/status from workflow.';
    if (col === layout.cols.remarks) return 'Staff comments / delays.';
    if (col === layout.cols.tatHours || col === layout.cols.tatDays) return 'Formula.';
    return '';
  });
}

function listRule_(values, strict) {
  return SpreadsheetApp.newDataValidation()
    .requireValueInList(values, true)
    .setAllowInvalid(!strict)
    .build();
}

function colorRule_(range, formula, color) {
  return SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied(formula)
    .setBackground(color)
    .setRanges([range])
    .build();
}

function mergedTitleRange_(sheet, width) {
  unmergeIntersectingMergedRanges_(sheet, 1, 1, 1, width);
  const range = sheet.getRange(1, 1, 1, width);
  range.merge();
  return range;
}

function unmergeIntersectingMergedRanges_(sheet, row, column, numRows, numColumns) {
  const target = {
    rowStart: row,
    rowEnd: row + numRows - 1,
    colStart: column,
    colEnd: column + numColumns - 1,
  };
  sheet.getDataRange().getMergedRanges().forEach(function(range) {
    const current = {
      rowStart: range.getRow(),
      rowEnd: range.getLastRow(),
      colStart: range.getColumn(),
      colEnd: range.getLastColumn(),
    };
    if (rangesIntersect_(target, current)) {
      range.breakApart();
    }
  });
}

function rangesIntersect_(a, b) {
  return a.rowStart <= b.rowEnd && a.rowEnd >= b.rowStart && a.colStart <= b.colEnd && a.colEnd >= b.colStart;
}
function getOrCreateSheet_(ss, name) {
  return ss.getSheetByName(name) || ss.insertSheet(name);
}

function ensureRowsAndColumns_(sheet, rows, cols) {
  if (sheet.getMaxRows() < rows) sheet.insertRowsAfter(sheet.getMaxRows(), rows - sheet.getMaxRows());
  if (sheet.getMaxColumns() < cols) sheet.insertColumnsAfter(sheet.getMaxColumns(), cols - sheet.getMaxColumns());
}

function applyFilter_(sheet, width, headerRow) {
  headerRow = headerRow || 2;
  const existing = sheet.getFilter();
  if (existing) existing.remove();
  sheet.getRange(headerRow, 1, Math.max(sheet.getMaxRows() - headerRow + 1, 1), width).createFilter();
}

function autoResize_(sheet, width) {
  for (let col = 1; col <= width; col++) {
    sheet.autoResizeColumn(col);
    if (sheet.getColumnWidth(col) > 220) sheet.setColumnWidth(col, 220);
    if (sheet.getColumnWidth(col) < 90) sheet.setColumnWidth(col, 90);
  }
}

function colLetter_(column) {
  let temp = '';
  let letter = '';
  while (column > 0) {
    temp = (column - 1) % 26;
    letter = String.fromCharCode(temp + 65) + letter;
    column = (column - temp - 1) / 26;
  }
  return letter;
}