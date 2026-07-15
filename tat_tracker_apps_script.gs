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
 * - format Django-calculated TAT values
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
  DEFAULT_MAX_ROWS: 500,
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
      'Biogas Unit',
      'Embu',
      'Nakuru',
      'West Nairobi',
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
    ].concat(smeStageTatHeaders_()),
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
    stageCols: [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16],
  },
  'TRACKER-LOGBOOK': {
    title: 'TAT TRACKER - LOGBOOK',
    maxAmount: 500000,
    minAmount: 50000,
    headers: [
      'Case ID', 'Client Name', 'Branch', 'BRO Name', 'Amount',
      'Case Created', 'MPESA Sent to Admin', 'MPESA Verified and Sent to CA',
      'Credit Analysis Sent', 'BRO Response to CA', 'Valuation Ready',
      'BM TAT Request Sent', 'HOCC Scheduled', 'HOCC Held', 'Decision',
      'Decision Timestamp', 'Minutes Shared', 'Sanctions', 'Sanctions Timestamp',
      'BRO Applied on System', 'Disbursement Register', 'Register Timestamp',
      'Register Approved', 'Finance Disbursement', 'Status', 'Remarks / Delays',
      'TAT Hours', 'TAT Days'
    ].concat(logbookStageTatHeaders_()),
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
    stageCols: [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24],
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
      'HOCC Scheduled', 'HOCC Held', 'Decision', 'Decision Timestamp',
      'Minutes Shared', 'Sanctions', 'Sanctions Timestamp',
      'BRO Applied on System', 'Disbursement Register', 'Register Timestamp',
      'Register Approved', 'Finance Disbursement', 'Status', 'Remarks / Delays',
      'TAT Hours', 'TAT Days'
    ].concat(noValuationStageTatHeaders_()),
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
    stageCols: [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23],
  };
}

function smeStageTatHeaders_() {
  return [
    'MPESA sent to Admin TAT Minutes',
    'MPESA verified and sent to CA TAT Minutes',
    'Credit analysis sent TAT Minutes',
    'BRO response to CA TAT Minutes',
    'BM response to CA TAT Minutes',
    'BRO applied loan on system TAT Minutes',
    'Disbursement register TAT Minutes',
    'Register approved TAT Minutes',
    'Finance disbursement TAT Minutes',
  ];
}

function noValuationStageTatHeaders_() {
  return [
    'MPESA sent to Admin TAT Minutes',
    'MPESA verified and sent to CA TAT Minutes',
    'Credit analysis sent TAT Minutes',
    'BRO response to CA TAT Minutes',
    'BM TAT request sent TAT Minutes',
    'HOCC scheduled TAT Minutes',
    'HOCC held TAT Minutes',
    'Decision TAT Minutes',
    'Minutes shared TAT Minutes',
    'Sanctions TAT Minutes',
    'BRO applied on system TAT Minutes',
    'Disbursement register TAT Minutes',
    'Register approved TAT Minutes',
    'Finance disbursement TAT Minutes',
  ];
}

function logbookStageTatHeaders_() {
  return [
    'MPESA sent to Admin TAT Minutes',
    'MPESA verified and sent to CA TAT Minutes',
    'Credit analysis sent TAT Minutes',
    'BRO response to CA TAT Minutes',
    'Valuation ready TAT Minutes',
    'BM TAT request sent TAT Minutes',
    'HOCC scheduled TAT Minutes',
    'HOCC held TAT Minutes',
    'Decision TAT Minutes',
    'Minutes shared TAT Minutes',
    'Sanctions TAT Minutes',
    'BRO applied on system TAT Minutes',
    'Disbursement register TAT Minutes',
    'Register approved TAT Minutes',
    'Finance disbursement TAT Minutes',
  ];
}

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('TAT Tracker')
    .addItem('Setup / refresh workbook', 'setupTatTrackerWorkbook')
    .addItem('Setup current tracker tab only', 'setupCurrentTatTrackerSheet')
    .addItem('Setup SME tab', 'setupTatSmeSheet')
    .addItem('Setup Logbook tab', 'setupTatLogbookSheet')
    .addItem('Setup Mjengo tab', 'setupTatMjengoSheet')
    .addItem('Setup Kilimo tab', 'setupTatKilimoSheet')
    .addItem('Setup Micro Asset tab', 'setupTatMicroAssetSheet')
    .addItem('Remove legacy protections', 'removeLegacyTatProtectionsMenu')
    .addItem('Refresh validations only', 'refreshTatValidations')
    .addItem('Refresh TAT value formatting', 'refreshTatFormulas')
    .addItem('Refresh TAT highlighting', 'refreshTatHighlighting')
    .addItem('Create support tabs', 'setupTatSupportTabs')
    .addSeparator()
    .addItem('Show setup notes', 'showTatSetupNotes')
    .addToUi();
}

function setupTatTrackerWorkbook() {
  const ss = SpreadsheetApp.getActive();
  removeLegacyTatProtections_(ss);
  TAT_CONFIG.TRACKER_SHEETS.forEach(function(sheetName) {
    const sheet = getOrCreateSheet_(ss, sheetName);
    setupTrackerSheet_(sheet, PRODUCT_LAYOUTS[sheetName]);
  });
  setupTatSupportTabs();
  SpreadsheetApp.getUi().alert('TAT Tracker setup complete. Django/Mini App remains the source of workflow writes.');
}

function setupCurrentTatTrackerSheet() {
  const sheet = SpreadsheetApp.getActiveSheet();
  setupSingleTatTrackerSheet_(sheet.getName());
}

function setupTatSmeSheet() {
  setupSingleTatTrackerSheet_('TRACKER-SME');
}

function setupTatLogbookSheet() {
  setupSingleTatTrackerSheet_('TRACKER-LOGBOOK');
}

function setupTatMjengoSheet() {
  setupSingleTatTrackerSheet_('TRACKER-MJENGO');
}

function setupTatKilimoSheet() {
  setupSingleTatTrackerSheet_('TRACKER-KILIMO');
}

function setupTatMicroAssetSheet() {
  setupSingleTatTrackerSheet_('TRACKER-MICRO-ASSET');
}

function setupSingleTatTrackerSheet_(sheetName) {
  const layout = PRODUCT_LAYOUTS[sheetName];
  if (!layout) {
    SpreadsheetApp.getUi().alert('The active sheet is not a configured TAT tracker tab.');
    return;
  }
  const ss = SpreadsheetApp.getActive();
  const sheet = getOrCreateSheet_(ss, sheetName);
  setupTrackerSheet_(sheet, layout);
  SpreadsheetApp.getUi().alert(sheetName + ' setup complete.');
}

function refreshTatValidations() {
  const ss = SpreadsheetApp.getActive();
  removeLegacyTatProtections_(ss);
  TAT_CONFIG.TRACKER_SHEETS.forEach(function(sheetName) {
    const sheet = ss.getSheetByName(sheetName);
    if (sheet) applyValidations_(sheet, PRODUCT_LAYOUTS[sheetName]);
  });
  SpreadsheetApp.getUi().alert('TAT Tracker validations refreshed.');
}

function refreshTatFormulas() {
  const ss = SpreadsheetApp.getActive();
  removeLegacyTatProtections_(ss);
  TAT_CONFIG.TRACKER_SHEETS.forEach(function(sheetName) {
    const sheet = ss.getSheetByName(sheetName);
    if (sheet) applyTatFormulas_(sheet, PRODUCT_LAYOUTS[sheetName]);
  });
  SpreadsheetApp.getUi().alert('TAT value formatting refreshed. Django writes calculated TAT values.');
}

function refreshTatHighlighting() {
  const ss = SpreadsheetApp.getActive();
  TAT_CONFIG.TRACKER_SHEETS.forEach(function(sheetName) {
    const sheet = ss.getSheetByName(sheetName);
    if (sheet) applyStatusConditionalFormatting_(sheet, PRODUCT_LAYOUTS[sheetName]);
  });
  SpreadsheetApp.getUi().alert('TAT value highlighting refreshed from row 5 downward. Rows 1-3 were not touched.');
}

function removeLegacyTatProtectionsMenu() {
  removeLegacyTatProtections_(SpreadsheetApp.getActive());
  SpreadsheetApp.getUi().alert('Legacy JBL/HOCC protections removed where your account has permission.');
}

function setupTatSupportTabs() {
  const ss = SpreadsheetApp.getActive();
  removeLegacyTatProtections_(ss);
  setupCaseIndex_(getOrCreateSheet_(ss, 'CASE_INDEX'));
  setupAuditLog_(getOrCreateSheet_(ss, 'AUDIT LOG'));
  setupDashboard_(getOrCreateSheet_(ss, 'DASHBOARD'));
}

function removeLegacyTatProtections_(ss) {
  const sheetNames = TAT_CONFIG.TRACKER_SHEETS.concat(TAT_CONFIG.SUPPORT_SHEETS);
  sheetNames.forEach(function(sheetName) {
    const sheet = ss.getSheetByName(sheetName);
    if (!sheet) return;
    removeLegacyProtectionsFromSheet_(sheet);
  });
}

function removeLegacyProtectionsFromSheet_(sheet) {
  const legacyPrefixes = ['JBL-', 'HOCC-'];
  [SpreadsheetApp.ProtectionType.RANGE, SpreadsheetApp.ProtectionType.SHEET].forEach(function(type) {
    try {
      sheet.getProtections(type).forEach(function(protection) {
        const description = String(protection.getDescription() || '');
        const isLegacy = legacyPrefixes.some(function(prefix) {
          return description.indexOf(prefix) === 0;
        });
        if (isLegacy && protection.canEdit()) {
          protection.remove();
        }
      });
    } catch (err) {
      Logger.log('Skipped legacy protection cleanup on ' + sheet.getName() + ': ' + err.message);
    }
  });
}

function setupTrackerSheet_(sheet, layout) {
  ensureRowsAndColumns_(sheet, TAT_CONFIG.DEFAULT_MAX_ROWS, layout.headers.length);
  sheet.getRange(TAT_CONFIG.DATA_START_ROW, 1, TAT_CONFIG.DEFAULT_MAX_ROWS - TAT_CONFIG.DATA_START_ROW + 1, layout.headers.length).setWrap(true);
  sheet.getRange(TAT_CONFIG.DATA_START_ROW, layout.cols.amount, TAT_CONFIG.DEFAULT_MAX_ROWS - TAT_CONFIG.DATA_START_ROW + 1, 1).setNumberFormat(TAT_CONFIG.MONEY_FORMAT);
  layout.dateCols.forEach(function(col) {
    sheet.getRange(TAT_CONFIG.DATA_START_ROW, col, TAT_CONFIG.DEFAULT_MAX_ROWS - TAT_CONFIG.DATA_START_ROW + 1, 1).setNumberFormat(TAT_CONFIG.DATE_TIME_FORMAT);
  });
  applyValidations_(sheet, layout);
  applyTatFormulas_(sheet, layout);
  applyStatusConditionalFormattingIfEmpty_(sheet, layout);
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
  const tatHoursCol = layout.cols.tatHours;
  const tatDaysCol = layout.cols.tatDays;
  const tatHoursRange = sheet.getRange(start, tatHoursCol, rows, 1);
  const tatDaysRange = sheet.getRange(start, tatDaysCol, rows, 1);
  removeLegacyFormulaProtections_(sheet);
  clearStaleFormulaValidation_(tatHoursRange);
  clearStaleFormulaValidation_(tatDaysRange);
  tatHoursRange.setNumberFormat('0.00');
  tatDaysRange.setNumberFormat('0.00');
  if (layout.headers.length > tatDaysCol) {
    sheet.getRange(start, tatDaysCol + 1, rows, layout.headers.length - tatDaysCol).setNumberFormat('0');
  }
}

function clearStaleFormulaValidation_(range) {
  try {
    range.clearDataValidations();
  } catch (err) {
    Logger.log('Skipped stale formula validation cleanup on ' + range.getSheet().getName() + ': ' + err.message);
  }
}

function removeLegacyFormulaProtections_(sheet) {
  try {
    sheet.getProtections(SpreadsheetApp.ProtectionType.RANGE).forEach(function(protection) {
      if (protection.getDescription() === 'JBL-COL-FORMULAS') {
        protection.remove();
      }
    });
  } catch (err) {
    Logger.log('Skipped legacy formula protection cleanup on ' + sheet.getName() + ': ' + err.message);
  }
}

function applyStatusConditionalFormatting_(sheet, layout) {
  const width = layout.headers.length;
  const dataRows = TAT_CONFIG.DEFAULT_MAX_ROWS - TAT_CONFIG.DATA_START_ROW + 1;
  const tatValueRange = sheet.getRange(TAT_CONFIG.DATA_START_ROW, layout.cols.tatHours, dataRows, 2);
  const row = TAT_CONFIG.DATA_START_ROW;
  const status = colLetter_(layout.cols.status);
  const tatHours = colLetter_(layout.cols.tatHours);
  const target = layout.tatHoursTarget || TAT_CONFIG.TAT_HOURS_TARGET;
  const nearTarget = Math.round(target * 0.8);
  const rules = [
    colorRule_(tatValueRange, `=AND($${tatHours}${row}<>"",$${tatHours}${row}>${nearTarget},$${tatHours}${row}<=${target})`, '#fff2cc'),
    colorRule_(tatValueRange, `=AND($${tatHours}${row}<>"",$${tatHours}${row}>${target})`, '#f4cccc'),
  ];
  sheet.setConditionalFormatRules(rules);
}

function addStageTrafficLightRules_(rules, sheet, layout, row, openStatusCheck, target) {
  const rows = TAT_CONFIG.DEFAULT_MAX_ROWS - TAT_CONFIG.DATA_START_ROW + 1;
  const created = colLetter_(layout.cols.created);
  (layout.stageCols || []).forEach(function(col) {
    const stage = colLetter_(col);
    const stageRange = sheet.getRange(TAT_CONFIG.DATA_START_ROW, col, rows, 1);
    rules.push(colorRule_(stageRange, `=AND($${stage}${row}="",$${created}${row}<>"",${openStatusCheck},((NOW()-$${created}${row})*24)<=${target})`, '#fff2cc'));
    rules.push(colorRule_(stageRange, `=AND($${stage}${row}="",$${created}${row}<>"",${openStatusCheck},((NOW()-$${created}${row})*24)>${target})`, '#f4cccc'));
    rules.push(colorRule_(stageRange, `=$${stage}${row}<>""`, '#d9ead3'));
  });
}

function applyStatusConditionalFormattingIfEmpty_(sheet, layout) {
  if (sheet.getConditionalFormatRules().length > 0) return;
  applyStatusConditionalFormatting_(sheet, layout);
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
}

function setupSimpleSheet_(sheet, title, headers, color) {
  ensureRowsAndColumns_(sheet, TAT_CONFIG.DEFAULT_MAX_ROWS, headers.length);
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


function getOrCreateSheet_(ss, name) {
  return ss.getSheetByName(name) || ss.insertSheet(name);
}

function ensureRowsAndColumns_(sheet, rows, cols) {
  if (sheet.getMaxRows() < rows) sheet.insertRowsAfter(sheet.getMaxRows(), rows - sheet.getMaxRows());
  if (sheet.getMaxColumns() < cols) sheet.insertColumnsAfter(sheet.getMaxColumns(), cols - sheet.getMaxColumns());
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
