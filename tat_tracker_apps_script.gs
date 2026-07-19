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
  HEADER_ROW: 2,
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
    productKey: 'sme',
    title: 'TAT TRACKER - SME',
    maxAmount: null,
    minAmount: 5000,
    headers: [
      'Case ID', 'Client Name', 'ID NUMBER', 'PHONE NUMBER', 'Branch', 'BRO Name', 'Amount',
      'Case Created', 'MPESA Sent to Admin', 'MPESA Verified and Sent to CA',
      'Credit Analysis Sent', 'BRO Response to CA', 'BM Response to CA',
      'BRO Applied Loan on System', 'Disbursement Register', 'Register Timestamp',
      'Register Approved', 'Finance Disbursement', 'Status', 'Remarks / Delays',
      'TAT Hours', 'TAT Days'
    ].concat(smeStageTatHeaders_()),
    cols: {
      amount: 7,
      created: 8,
      register: 15,
      registerTs: 16,
      registerApproved: 17,
      disbursement: 18,
      status: 19,
      remarks: 20,
      tatHours: 21,
      tatDays: 22,
    },
    dateCols: [8, 9, 10, 11, 12, 13, 14, 16, 18],
    stageCols: [8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
    stageTatKeys: smeStageTatKeys_(),
  },
  'TRACKER-LOGBOOK': {
    productKey: 'logbook',
    title: 'TAT TRACKER - LOGBOOK',
    maxAmount: 500000,
    minAmount: 50000,
    headers: [
      'Case ID', 'Client Name', 'ID NUMBER', 'PHONE NUMBER', 'Branch', 'BRO Name', 'Amount',
      'Case Created', 'MPESA Sent to Admin', 'MPESA Verified and Sent to CA',
      'Credit Analysis Sent', 'BRO Response to CA', 'Valuation Ready',
      'BM TAT Request Sent', 'HOCC Scheduled', 'HOCC Held', 'Decision',
      'Decision Timestamp', 'Minutes Shared', 'Sanctions', 'Sanctions Timestamp',
      'BRO Applied on System', 'Disbursement Register', 'Register Timestamp',
      'Register Approved', 'Finance Disbursement', 'Status', 'Remarks / Delays',
      'TAT Hours', 'TAT Days'
    ].concat(logbookStageTatHeaders_()),
    cols: {
      amount: 7,
      created: 8,
      decision: 17,
      decisionTs: 18,
      sanctions: 20,
      sanctionsTs: 21,
      register: 23,
      registerTs: 24,
      registerApproved: 25,
      disbursement: 26,
      status: 27,
      remarks: 28,
      tatHours: 29,
      tatDays: 30,
    },
    dateCols: [8, 9, 10, 11, 12, 13, 14, 15, 16, 18, 19, 21, 22, 24, 26],
    stageCols: [8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26],
    stageTatKeys: logbookStageTatKeys_(),
  },
  'TRACKER-MJENGO': null,
  'TRACKER-KILIMO': null,
  'TRACKER-MICRO-ASSET': null,
};

PRODUCT_LAYOUTS['TRACKER-MJENGO'] = noValuationLayout('mjengo', 'TAT TRACKER - MJENGO', 50000, 300000);
PRODUCT_LAYOUTS['TRACKER-KILIMO'] = noValuationLayout('kilimo', 'TAT TRACKER - KILIMO', 50000, 300000);
PRODUCT_LAYOUTS['TRACKER-MICRO-ASSET'] = noValuationLayout('micro_asset', 'TAT TRACKER - MICRO-ASSET', 50000, 300000);

function noValuationLayout(productKey, title, minAmount, maxAmount) {
  return {
    title: title,
    minAmount: minAmount,
    maxAmount: maxAmount,
    headers: [
      'Case ID', 'Client Name', 'ID NUMBER', 'PHONE NUMBER', 'Branch', 'BRO Name', 'Amount',
      'Case Created', 'MPESA Sent to Admin', 'MPESA Verified and Sent to CA',
      'Credit Analysis Sent', 'BRO Response to CA', 'BM TAT Request Sent',
      'HOCC Scheduled', 'HOCC Held', 'Decision', 'Decision Timestamp',
      'Minutes Shared', 'Sanctions', 'Sanctions Timestamp',
      'BRO Applied on System', 'Disbursement Register', 'Register Timestamp',
      'Register Approved', 'Finance Disbursement', 'Status', 'Remarks / Delays',
      'TAT Hours', 'TAT Days'
    ].concat(noValuationStageTatHeaders_()),
    cols: {
      amount: 7,
      created: 8,
      decision: 16,
      decisionTs: 17,
      sanctions: 19,
      sanctionsTs: 20,
      register: 22,
      registerTs: 23,
      registerApproved: 24,
      disbursement: 25,
      status: 26,
      remarks: 27,
      tatHours: 28,
      tatDays: 29,
    },
    dateCols: [8, 9, 10, 11, 12, 13, 14, 15, 17, 18, 20, 21, 23, 25],
    stageCols: [8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25],
    stageTatKeys: noValuationStageTatKeys_(),
  };
}

function smeStageTatKeys_() {
  return ['mpesa_to_admin', 'mpesa_verified', 'ca_analysis_sent', 'bro_response', 'bm_response', 'bro_applied', 'disbursement_register', 'register_approved', 'disbursement'];
}

function noValuationStageTatKeys_() {
  return ['mpesa_to_admin', 'mpesa_verified', 'ca_analysis_sent', 'bro_response', 'bm_tat_request', 'tat_scheduled', 'tat_held', 'decision', 'minutes_shared', 'sanctions', 'bro_applied', 'disbursement_register', 'register_approved', 'disbursement'];
}

function logbookStageTatKeys_() {
  return ['mpesa_to_admin', 'mpesa_verified', 'ca_analysis_sent', 'bro_response', 'valuation_ready', 'bm_tat_request', 'tat_scheduled', 'tat_held', 'decision', 'minutes_shared', 'sanctions', 'bro_applied', 'disbursement_register', 'register_approved', 'disbursement'];
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
  sheet.getRange(TAT_CONFIG.HEADER_ROW, 1, 1, layout.headers.length).setValues([layout.headers]);
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
  sheet.getRange(TAT_CONFIG.DATA_START_ROW, 5, rows, 1).setDataValidation(branchRule);
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
  const dataRows = TAT_CONFIG.DEFAULT_MAX_ROWS - TAT_CONFIG.DATA_START_ROW + 1;
  const row = TAT_CONFIG.DATA_START_ROW;
  const tatHours = colLetter_(layout.cols.tatHours);
  const totalTarget = tatTargetFormula_(layout.productKey, '__total__');
  const rules = trafficLightRules_(
    sheet.getRange(TAT_CONFIG.DATA_START_ROW, layout.cols.tatHours, dataRows, 2),
    tatHours,
    row,
    totalTarget
  );
  (layout.stageTatKeys || []).forEach(function(stageKey, index) {
    const column = layout.cols.tatDays + 1 + index;
    const stage = colLetter_(column);
    trafficLightRules_(
      sheet.getRange(TAT_CONFIG.DATA_START_ROW, column, dataRows, 1),
      stage,
      row,
      tatTargetFormula_(layout.productKey, stageKey)
    ).forEach(function(rule) { rules.push(rule); });
  });
  sheet.setConditionalFormatRules(rules);
}

function tatTargetFormula_(productKey, stageKey) {
  // Conditional-format rules cannot directly reference another tab. INDIRECT keeps
  // the cross-tab ranges inside a string while still recalculating from TAT TARGETS.
  return `SUMIFS(INDIRECT("'TAT TARGETS'!C:C"),INDIRECT("'TAT TARGETS'!A:A"),"${productKey}",INDIRECT("'TAT TARGETS'!B:B"),"${stageKey}")`;
}

function trafficLightRules_(range, column, row, targetFormula) {
  const value = `${column}${row}`;
  const target = `(${targetFormula})`;
  return [
    colorRule_(range, `=AND(${value}<>"",${target}>0,${value}<=${target}*0.8)`, '#d9ead3'),
    colorRule_(range, `=AND(${value}<>"",${target}>0,${value}>${target}*0.8,${value}<=${target})`, '#fff2cc'),
    colorRule_(range, `=AND(${value}<>"",${target}>0,${value}>${target})`, '#f4cccc'),
  ];
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
  const headers = ['Case ID', 'Tracker Sheet', 'Row Number', 'Client Name', 'ID NUMBER', 'PHONE NUMBER', 'Branch', 'BRO Name', 'Status', 'Created At', 'Last Updated At'];
  setupSimpleSheet_(sheet, 'TAT CASE INDEX', headers, '#274e13');
}

function setupAuditLog_(sheet) {
  const headers = ['Timestamp', 'Actor', 'Tracker Sheet', 'Case ID', 'Row Number', 'Stage', 'New Value', 'Old Value', 'Source'];
  setupSimpleSheet_(sheet, 'TAT AUDIT LOG', headers, '#4c1130');
}

function setupTatTargets_(sheet) {
  ensureRowsAndColumns_(sheet, 50, 4);
  sheet.getRange(1, 1, 1, 4).setValues([['Product Key', 'Stage Key', 'Target Minutes', 'Near Ratio']]);
  sheet.getRange(1, 1, 1, 4).setFontWeight('bold').setBackground('#1c4587').setFontColor('#ffffff');
  sheet.setFrozenRows(1);
  if (sheet.getLastRow() < 2) {
    const rows = Object.keys(PRODUCT_LAYOUTS).map(function(sheetName) {
      return [PRODUCT_LAYOUTS[sheetName].productKey, '__total__', TAT_CONFIG.TAT_HOURS_TARGET * 60, 0.8];
    });
    sheet.getRange(2, 1, rows.length, 4).setValues(rows);
  }
}
function setupDashboard_(sheet) {
  setupSimpleSheet_(sheet, 'TAT DASHBOARD', ['Metric', 'Value', 'Notes'], '#1c4587');
  sheet.getRange(5, 1, 6, 3).setValues([
    ['Open cases', '=COUNTIF(CASE_INDEX!I:I,"Active")', 'Synced by Django into CASE_INDEX'],
    ['Disbursed', '=COUNTIF(CASE_INDEX!I:I,"Disbursed")', ''],
    ['Rejected / Declined', '=COUNTIF(CASE_INDEX!I:I,"Rejected")+COUNTIF(CASE_INDEX!I:I,"Declined")', ''],
    ['Deferred', '=COUNTIF(CASE_INDEX!I:I,"Deferred")', ''],
    ['Stalled', '=COUNTIF(CASE_INDEX!I:I,"Stalled")', ''],
    ['Pending Docs', '=COUNTIF(CASE_INDEX!I:I,"Pending Docs")', ''],
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
