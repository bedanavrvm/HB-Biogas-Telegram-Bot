/**
 * ════════════════════════════════════════════════════════════════════════════
 *  JBL HOCC TAT TRACKER — Google Apps Script v5.3
 *  Jawabu Biashara Limited | IT Department
 * ════════════════════════════════════════════════════════════════════════════
 *
 *  MULTI-PRODUCT ARCHITECTURE
 *  ──────────────────────────
 *  Four TRACKER sheets in one workbook:
 *    • TRACKER-LOGBOOK     (includes Valuation column)
 *    • TRACKER-MJENGO      (no Valuation)
 *    • TRACKER-KILIMO    (no Valuation)
 *    • TRACKER-MICRO-ASSET (no Valuation)
 *
 *  CHANGES FROM v5:
 *  ────────────────
 *  1. Added "BRO: MPESA Sent to Admin" (col 7) — BRO sends MPESA to admin
 *  2. Added "Admin: MPESA Verified & Sent to CA" (col 8) — Admin verifies + forwards
 *  3. Admin sends documents directly to CA; BRO Docs-to-CA stage removed
 *  4. Admin owns both MPESA verification and disbursement register
 *
 *  INSTALL:
 *  ────────
 *  Extensions → Apps Script → paste → Save
 *  → Run setupWebAppSupport()
 *  → Add real staff to the STAFF sheet
 *  → Run setupAllTriggers() once → grant permissions
 * ════════════════════════════════════════════════════════════════════════════
 */


// ════════════════════════════════════════════════════════════════════════════
//  GLOBAL CONFIG
// ════════════════════════════════════════════════════════════════════════════
const CONFIG = {
  DATA_START_ROW: 5,
  MIN_AMOUNT: 50000,
  DATE_TIME_FORMAT: "dd-mmm-yyyy hh:mm",
  VALIDATION_START_DATE: new Date(2025, 0, 1),
  DEFAULT_EXTEND_TO_ROW: 2000,
  CASE_INDEX_SHEET_NAME: "CASE_INDEX",
  CORRECTION_LOG_SHEET_NAME: "CORRECTION LOG",
  ANOMALY_REPORT_SHEET_NAME: "AUDIT ANOMALIES",

  EMAILS: {
    MD:    "bedanaurum@gmail.com",
    DOO:   "bedanaurum@gmail.com",
    ADMIN: "bedanaurum@gmail.com",
  },
  MANAGEMENT_VIEWER_EMAILS: [
    "bedanaurum@gmail.com",
    "bedanaurum@gmail.com",
  ],

  TARGETS_HRS: {
    TOTAL: 336,  // 14 days
  },

  // Case ID prefixes per product
  CASE_ID_PREFIX: {
    "TRACKER-LOGBOOK":     "JBL-LB",
    "TRACKER-MJENGO":      "JBL-MJ",
    "TRACKER-KILIMO":    "JBL-KI",
    "TRACKER-MICRO-ASSET": "JBL-MA",
    "TRACKER-Business":         "JBL-BS",
  },
};


// ════════════════════════════════════════════════════════════════════════════
//  PRODUCT CONFIGURATIONS
//  Each product has its own column map based on whether it has Valuation
//
//  NEW FLOW (cols 6-9):
//    ① Case Created (6) → ② MPESA Sent to Admin (7) → ③ Admin Verified & Sent to CA (8)
// ════════════════════════════════════════════════════════════════════════════

/**
 * LOGBOOK — includes Valuation column (col 12)
 */
const LOGBOOK_CONFIG = {
  SHEET_NAME: "TRACKER-LOGBOOK",
  HAS_VALUATION: true,
  MAX_AMOUNT: 500000,

  COL: {
    CASE_ID:           1,   // A
    CLIENT_NAME:       2,   // B — triggers auto Case ID + Created TS
    BRANCH:            3,   // C
    LO_NAME:           4,   // D
    AMOUNT:            5,   // E

    TS_CREATED:        6,   // F — AUTO
    TS_MPESA_TO_ADMIN: 7,   // G — BRO: MPESA Sent to Admin
    TS_MPESA_VERIFIED: 8,   // H — Admin: MPESA Verified & Sent to CA (NEW)
    TS_CA:             9,   // I — Credit Analyst
    TS_LO_RESP:        10,  // J — BRO Response
    TS_VALUATION:      11,  // K — BM: Valuation Ready (LOGBOOK ONLY)
    TS_BM_REQ:         12,  // L — BM: HOCC Request
    TS_SCHEDULED:      13,  // M — Secretary: Scheduled
    TS_HELD:           14,  // N — Secretary: Held
    DECISION:          15,  // O — Chair: Decision dropdown
    TS_DECISION:       16,  // P — AUTO
    TS_MINUTES:        17,  // Q — Secretary: Minutes Shared
    SANCTIONS:         18,  // R — Loan Approver: Sanctions dropdown
    TS_SANCTIONS:      19,  // S — AUTO (when Sanctions = Met)
    TS_LO_APPLY:       20,  // T — BRO: Applied on System (BLOCKED if Sanctions != Met)
    REGISTER:          21,  // U — Admin: Disbursement Register dropdown
    TS_REGISTER:       22,  // V — AUTO
    REGISTER_APPROVED: 23,  // W — Loan Approver: Approved/Pending
    TS_DISBURSE:       24,  // X — Finance: Disbursement (BLOCKED if Register != Approved)

    STATUS:            25,  // Y
    REMARKS:           26,  // Z

    TAT_HRS:           27,  // AA
    TAT_DAYS:          28,  // AB
    // Lags: 29-42 (AC-AP)
  },

  // Timestamp sequence for date-flow validation
  TS_SEQUENCE: [
    [6,  "Case Created"],
    [7,  "MPESA Sent to Admin"],
    [8,  "MPESA Verified & Sent to CA"],
    [9,  "CA Analysis Sent"],
    [10, "BRO Response to CA"],
    [11, "Valuation Ready"],
    [12, "BM HOCC Request"],
    [13, "HOCC Scheduled"],
    [14, "HOCC Held"],
    [16, "Decision Recorded"],
    [17, "Minutes Shared"],
    [19, "Sanctions Met"],
    [20, "BRO Applied on System"],
    [22, "Disbursement Register"],
    [24, "Disbursement"],
  ],

  // Lock col X once col Y is filled
  LOCK_ON_NEXT: {
    6:  7,   // Case Created locked once MPESA sent
    7:  8,   // MPESA Sent locked once Admin verified
    8:  9,   // Admin Verified locked once CA stamps
    9:  10,  // CA locked once BRO responds
    10: 11,  // BRO Response locked once Valuation stamped
    11: 12,  // Valuation locked once BM request sent
    12: 13,  // BM request locked once Scheduled
    13: 14,  // Scheduled locked once Held
    14: 16,  // Held locked once Decision stamped
    16: 17,  // Decision locked once Minutes shared
    17: 19,  // Minutes locked once Sanctions stamped
    19: 20,  // Sanctions locked once BRO applies
    20: 22,  // BRO Apply locked once Register stamped
    22: 24,  // Register locked once Disbursed
  },

  // Stage names for audit log
  STAGE_NAMES: {
    6:  "Case Created",
    7:  "MPESA Sent to Admin",
    8:  "MPESA Verified & Sent to CA",
    9:  "CA Analysis Sent",
    10: "BRO Response to CA",
    11: "Valuation Ready",
    12: "BM HOCC Request",
    13: "HOCC Scheduled",
    14: "HOCC Held",
    15: "Decision",
    16: "Decision TS",
    17: "Minutes Shared",
    18: "Sanctions",
    19: "Sanctions TS",
    20: "BRO Applied on System",
    21: "Disbursement Register",
    22: "Register TS",
    23: "Register Approved",
    24: "Disbursement",
  },
};


/**
 * NO VALUATION — MJENGO, Kilimo, MICRO-ASSET
 * No valuation column; Admin sends documents directly to CA.
 */
const NO_VALUATION_CONFIG = {
  HAS_VALUATION: false,

  COL: {
    CASE_ID:           1,   // A
    CLIENT_NAME:       2,   // B
    BRANCH:            3,   // C
    LO_NAME:           4,   // D
    AMOUNT:            5,   // E

    TS_CREATED:        6,   // F — AUTO
    TS_MPESA_TO_ADMIN: 7,   // G — BRO: MPESA Sent to Admin
    TS_MPESA_VERIFIED: 8,   // H — Admin: MPESA Verified & Sent to CA (NEW)
    TS_CA:             9,   // I — Credit Analyst
    TS_LO_RESP:        10,  // J — BRO Response
    // NO VALUATION
    TS_BM_REQ:         11,  // K — BM: HOCC Request (direct, no valuation)
    TS_SCHEDULED:      12,  // L — Secretary: Scheduled
    TS_HELD:           13,  // M — Secretary: Held
    DECISION:          14,  // N — Chair: Decision dropdown
    TS_DECISION:       15,  // O — AUTO
    TS_MINUTES:        16,  // P — Secretary: Minutes Shared
    SANCTIONS:         17,  // Q — Loan Approver: Sanctions dropdown
    TS_SANCTIONS:      18,  // R — AUTO
    TS_LO_APPLY:       19,  // S — BRO: Applied on System
    REGISTER:          20,  // T — Admin: Disbursement Register
    TS_REGISTER:       21,  // U — AUTO
    REGISTER_APPROVED: 22,  // V — Loan Approver
    TS_DISBURSE:       23,  // W — Finance

    STATUS:            24,  // X
    REMARKS:           25,  // Y

    TAT_HRS:           26,  // Z
    TAT_DAYS:          27,  // AA
    // Lags: 28-40 (AB-AN)
  },

  TS_SEQUENCE: [
    [6,  "Case Created"],
    [7,  "MPESA Sent to Admin"],
    [8,  "MPESA Verified & Sent to CA"],
    [9,  "CA Analysis Sent"],
    [10, "BRO Response to CA"],
    [11, "BM HOCC Request"],
    [12, "HOCC Scheduled"],
    [13, "HOCC Held"],
    [15, "Decision Recorded"],
    [16, "Minutes Shared"],
    [18, "Sanctions Met"],
    [19, "BRO Applied on System"],
    [21, "Disbursement Register"],
    [23, "Disbursement"],
  ],

  LOCK_ON_NEXT: {
    6:  7,   // Case Created locked once MPESA sent
    7:  8,   // MPESA Sent locked once Admin verified
    8:  9,   // Admin Verified locked once CA stamps
    9:  10,  // CA locked once BRO responds
    10: 11,  // BRO Response locked once BM request sent (no valuation)
    11: 12,  // BM request locked once Scheduled
    12: 13,  // Scheduled locked once Held
    13: 15,  // Held locked once Decision stamped
    15: 16,  // Decision locked once Minutes shared
    16: 18,  // Minutes locked once Sanctions stamped
    18: 19,  // Sanctions locked once BRO applies
    19: 21,  // BRO Apply locked once Register stamped
    21: 23,  // Register locked once Disbursed
  },

  STAGE_NAMES: {
    6:  "Case Created",
    7:  "MPESA Sent to Admin",
    8:  "MPESA Verified & Sent to CA",
    9:  "CA Analysis Sent",
    10: "BRO Response to CA",
    11: "BM HOCC Request",
    12: "HOCC Scheduled",
    13: "HOCC Held",
    14: "Decision",
    15: "Decision TS",
    16: "Minutes Shared",
    17: "Sanctions",
    18: "Sanctions TS",
    19: "BRO Applied on System",
    20: "Disbursement Register",
    21: "Register TS",
    22: "Register Approved",
    23: "Disbursement",
  },
};

// Create product-specific configs
const MJENGO_CONFIG = { ...NO_VALUATION_CONFIG, SHEET_NAME: "TRACKER-MJENGO", MAX_AMOUNT: 300000 };
const KILIMO_CONFIG = { ...NO_VALUATION_CONFIG, SHEET_NAME: "TRACKER-KILIMO", MAX_AMOUNT: 300000 };
const MICRO_ASSET_CONFIG = { ...NO_VALUATION_CONFIG, SHEET_NAME: "TRACKER-MICRO-ASSET", MAX_AMOUNT: 300000 };

/**
 * Business - shorter non-HOCC flow.
 * The workbook does not define a Business upper amount cap, so MAX_AMOUNT is null.
 */
const BUSINESS_CONFIG = {
  SHEET_NAME: "TRACKER-Business",
  HAS_VALUATION: false,
  HAS_HOCC_FLOW: false,
  MIN_AMOUNT: 5000,
  MAX_AMOUNT: null,
  FORMULA_END_COL: 28,

  COL: {
    CASE_ID:           1,   // A
    CLIENT_NAME:       2,   // B
    BRANCH:            3,   // C
    LO_NAME:           4,   // D
    AMOUNT:            5,   // E

    TS_CREATED:        6,   // F - AUTO
    TS_MPESA_TO_ADMIN: 7,   // G - BRO: MPESA Sent to Admin
    TS_MPESA_VERIFIED: 8,   // H - Admin: MPESA Verified & Sent to CA
    TS_CA:             9,   // I - Credit Analyst
    TS_LO_RESP:        10,  // J - BRO Response
    TS_BM_RESP:        11,  // K - BM Response to CA
    TS_LO_APPLY:       12,  // L - BRO: Applied Loan on System
    REGISTER:          13,  // M - Admin: Disbursement Register
    TS_REGISTER:       14,  // N - AUTO
    REGISTER_APPROVED: 15,  // O - Loan Approver
    TS_DISBURSE:       16,  // P - Finance

    STATUS:            17,  // Q
    REMARKS:           18,  // R

    TAT_HRS:           19,  // S
    TAT_DAYS:          20,  // T
    // Lags: 21-28 (U-AB)
  },

  TS_SEQUENCE: [
    [6,  "Case Created"],
    [7,  "MPESA Sent to Admin"],
    [8,  "MPESA Verified & Sent to CA"],
    [9,  "CA Analysis Sent"],
    [10, "BRO Response to CA"],
    [11, "BM Response to CA"],
    [12, "BRO Applied Loan on System"],
    [14, "Disbursement Register"],
    [16, "Disbursement"],
  ],

  LOCK_ON_NEXT: {
    6:  7,
    7:  8,
    8:  9,
    9:  10,
    10: 11,
    11: 12,
    12: 14,
    14: 16,
  },

  STAGE_NAMES: {
    6:  "Case Created",
    7:  "MPESA Sent to Admin",
    8:  "MPESA Verified & Sent to CA",
    9:  "CA Analysis Sent",
    10: "BRO Response to CA",
    11: "BM Response to CA",
    12: "BRO Applied Loan on System",
    13: "Disbursement Register",
    14: "Register TS",
    15: "Register Approved",
    16: "Disbursement",
  },
};

// Map sheet names to configs
const PRODUCTS = {
  "TRACKER-LOGBOOK":     LOGBOOK_CONFIG,
  "TRACKER-MJENGO":      MJENGO_CONFIG,
  "TRACKER-KILIMO":    KILIMO_CONFIG,
  "TRACKER-MICRO-ASSET": MICRO_ASSET_CONFIG,
  "TRACKER-Business":         BUSINESS_CONFIG,
};

const TRACKER_SHEETS = Object.keys(PRODUCTS);


// ════════════════════════════════════════════════════════════════════════════
//  LEGACY ROLE MAP
//  KEY:   Google account email
//  VALUE: { sheets: [...], cols_logbook: [...], cols_other: [...], cols_business: [...] }
//         sheets = which TRACKER sheets they can edit (or "*" for all)
//         cols_logbook = column indices for LOGBOOK (with valuation)
//         cols_other = column indices for MJENGO/KILIMO/MICRO-ASSET (no valuation)
//         cols_business = column indices for Business's shorter flow
//
//  STAFF is the default source of truth. This map is used only if
//  WEB_APP_CONFIG.USE_ROLE_MAP_FALLBACK is set to true.
//  Admin owns MPESA verification (col 8) and disbursement register (22/21)
// ════════════════════════════════════════════════════════════════════════════
const ROLE_MAP = {

  // ── IT (maintainer — all columns on all sheets) ─────────────────────
  "admin@jawabubiz.co.ke": {
    sheets: "*",
    cols_logbook: [1,2,3,4,5,7,8,9,10,11,12,13,14,15,17,18,20,21,23,24],
    cols_other:   [1,2,3,4,5,7,8,9,10,11,12,13,14,16,17,19,20,22,23],
    cols_business:     [1,2,3,4,5,7,8,9,10,11,12,13,15,16],
  },

  // ── BRO ─────────────────────────────────────────────────────────────
  // Identity cols (1-5), MPESA to Admin (7), BRO Response (10), Applied on System (20/19)
  "lo1@jawabubiz.co.ke": {
    sheets: "*",
    cols_logbook: [1,2,3,4,5,7,10,20],
    cols_other:   [1,2,3,4,5,7,10,19],
    cols_business:     [1,2,3,4,5,7,10,12],
  },
  "lo2@jawabubiz.co.ke": {
    sheets: "*",
    cols_logbook: [1,2,3,4,5,7,10,20],
    cols_other:   [1,2,3,4,5,7,10,19],
    cols_business:     [1,2,3,4,5,7,10,12],
  },

  // ── Credit Analyst ──────────────────────────────────────────────────
  // CA Analysis (9)
  "ca@jawabubiz.co.ke": {
    sheets: "*",
    cols_logbook: [9],
    cols_other:   [9],
    cols_business:     [9],
  },

  // ── Branch Managers ─────────────────────────────────────────────────
  // Valuation (11 — LOGBOOK only), BM HOCC Request (12/11)
  "bm.westlands@jawabubiz.co.ke": {
    sheets: "*",
    cols_logbook: [11,12],
    cols_other:   [11],
    cols_business:     [11],
  },
  "bm.ngong@jawabubiz.co.ke": {
    sheets: "*",
    cols_logbook: [11,12],
    cols_other:   [11],
    cols_business:     [11],
  },

  // ── HOCC Secretary ──────────────────────────────────────────────────
  // Scheduled (13/12), Held (14/13), Minutes (17/16)
  "secretary@jawabubiz.co.ke": {
    sheets: "*",
    cols_logbook: [13,14,17],
    cols_other:   [12,13,16],
    cols_business:     [],
  },

  // ── HOCC Chair ──────────────────────────────────────────────────────
  // Decision dropdown (15/14)
  "chair@jawabubiz.co.ke": {
    sheets: "*",
    cols_logbook: [15],
    cols_other:   [14],
    cols_business:     [],
  },

  // ── Loan Approver ───────────────────────────────────────────────────
  // Sanctions dropdown (18/17), Register Approved (23/22)
  "approver@jawabubiz.co.ke": {
    sheets: "*",
    cols_logbook: [18,23],
    cols_other:   [17,22],
    cols_business:     [15],
  },

  // ── Admin ───────────────────────────────────────────────────────────
  // MPESA Verified & Sent to CA (8), Disbursement Register (21/20)
  "operations.admin@jawabubiz.co.ke": {
    sheets: "*",
    cols_logbook: [8,21],
    cols_other:   [8,20],
    cols_business:     [8,13],
  },

  // ── Finance ─────────────────────────────────────────────────────────
  // Disbursement (24/23)
  "finance@jawabubiz.co.ke": {
    sheets: "*",
    cols_logbook: [24],
    cols_other:   [23],
    cols_business:     [16],
  },

  // ── Management (view-only — no edit columns) ────────────────────────
  "md@jawabubiz.co.ke": {
    sheets: "*",
    cols_logbook: [],
    cols_other:   [],
    cols_business:     [],
  },
  "doo@jawabubiz.co.ke": {
    sheets: "*",
    cols_logbook: [],
    cols_other:   [],
    cols_business:     [],
  },
};


// ════════════════════════════════════════════════════════════════════════════
//  1. SETUP — run once
// ════════════════════════════════════════════════════════════════════════════
// Web app constants. Keep these ASCII-only so future Apps Script edits are easy.
const WEB_APP_CONFIG = {
  STAFF_SHEET_NAME: "STAFF",
  CASE_INDEX_SHEET_NAME: CONFIG.CASE_INDEX_SHEET_NAME,
  CORRECTION_LOG_SHEET_NAME: CONFIG.CORRECTION_LOG_SHEET_NAME,
  ANOMALY_REPORT_SHEET_NAME: CONFIG.ANOMALY_REPORT_SHEET_NAME,
  AUDIT_SOURCE: "WEB_FORM",
  SEARCH_LIMIT: 25,
  RECENT_LIMIT: 10,
  LOCK_WAIT_MS: 10000,
  HEADER_ROW: 2,
  WEB_COMPATIBLE_PROTECTIONS: true,

  BRANCHES: ["Corporate", "Thika Road", "East Nairobi", "West Nairobi",
             "Nakuru", "Embu", "Limuru"],
  PRODUCTS: [
    { sheetName: "TRACKER-LOGBOOK", label: "Logbook" },
    { sheetName: "TRACKER-MJENGO", label: "Mjengo" },
    { sheetName: "TRACKER-KILIMO", label: "Kilimo" },
    { sheetName: "TRACKER-MICRO-ASSET", label: "Micro Asset" },
    { sheetName: "TRACKER-Business", label: "Business" },
  ],
  DROPDOWNS: {
    DECISION: ["Approved", "Rejected", "Deferred"],
    SANCTIONS: ["Pending", "Met", "Not Met"],
    REGISTER: ["10:00am", "1:00pm", "3:30pm"],
    REGISTER_APPROVED: ["Approved", "Pending"],
  },
  STATUS_VALUES: ["Active", "Disbursed", "Rejected", "Declined", "Deferred", "Stalled", "Pending Docs"],
  STAFF_HEADERS: ["Email", "Name", "Role", "Active", "Sheets", "Branch", "Notes"],
  STAFF_ROLES: ["IT", "BRO", "CA", "BM", "SECRETARY", "CHAIR",
                "LOAN_APPROVER", "ADMIN", "FINANCE", "MANAGEMENT"],
  STAFF_ACTIVE_VALUES: ["Yes", "No"],
  USE_ROLE_MAP_FALLBACK: false,
};

const STAFF_ROLE_TEMPLATES = {
  IT: {
    cols_logbook: [1,2,3,4,5,7,8,9,10,11,12,13,14,15,17,18,20,21,23,24],
    cols_other:   [1,2,3,4,5,7,8,9,10,11,12,13,14,16,17,19,20,22,23],
    cols_business:     [1,2,3,4,5,7,8,9,10,11,12,13,15,16],
  },
  BRO: {
    cols_logbook: [1,2,3,4,5,7,10,20],
    cols_other:   [1,2,3,4,5,7,10,19],
    cols_business:     [1,2,3,4,5,7,10,12],
  },
  CA: { cols_logbook: [9], cols_other: [9], cols_business: [9] },
  BM: { cols_logbook: [11,12], cols_other: [11], cols_business: [11] },
  SECRETARY: { cols_logbook: [13,14,17], cols_other: [12,13,16], cols_business: [] },
  CHAIR: { cols_logbook: [15], cols_other: [14], cols_business: [] },
  LOAN_APPROVER: { cols_logbook: [18,23], cols_other: [17,22], cols_business: [15] },
  ADMIN: { cols_logbook: [8,21], cols_other: [8,20], cols_business: [8,13] },
  FINANCE: { cols_logbook: [24], cols_other: [23], cols_business: [16] },
  MANAGEMENT: { cols_logbook: [], cols_other: [], cols_business: [] },
};





function setupAllTriggers() {
  requireOwnerUser_();

  // Replace only JBL-managed triggers; leave unrelated project triggers intact.
  const managedHandlers = ["onEditHandler", "dailyMorningRun", "sendWeeklyReport"];
  ScriptApp.getProjectTriggers()
    .filter(trigger => managedHandlers.includes(trigger.getHandlerFunction()))
    .forEach(trigger => ScriptApp.deleteTrigger(trigger));

  const ss = SpreadsheetApp.getActiveSpreadsheet();

  // Create triggers
  ScriptApp.newTrigger("onEditHandler").forSpreadsheet(ss).onEdit().create();

  ScriptApp.newTrigger("dailyMorningRun")
    .timeBased().atHour(8).everyDays(1).inTimezone("Africa/Nairobi").create();

  ScriptApp.newTrigger("sendWeeklyReport")
    .timeBased().onWeekDay(ScriptApp.WeekDay.MONDAY)
    .atHour(7).inTimezone("Africa/Nairobi").create();

  // Apply protections to all sheets
  applyAllProtections();
  applyAllTimestampFormats();
  applyAllDataValidations();

  // Hide management sheets
  hideManagementSheets_();

  try {
    SpreadsheetApp.getUi().alert(
      "Setup complete!\n\n" +
      "Column protections applied to all TRACKER sheets.\n" +
      "Daily run: 8:00 AM EAT | Weekly report: Monday 7:00 AM EAT\n\n" +
      "With the current 'User accessing the web app' deployment, staff who create/update cases need spreadsheet Editor access.\n" +
      "Range and sheet protections restrict each editor to their assigned areas."
    );
  } catch(e) { Logger.log("UI alert skipped (likely running headless)."); }
}


// ════════════════════════════════════════════════════════════════════════════
//  2. COLUMN PROTECTIONS — for all TRACKER sheets
// ════════════════════════════════════════════════════════════════════════════
function setupWebAppSupport() {
  requireOwnerOrItUser_();

  setupStaffSheet();
  ensureAuditLogSourceColumn_();
  ensureCaseIndexSheet_();
  ensureCorrectionLogSheet_();
  applyAllProtections();
  applyAllTimestampFormats();
  applyAllDataValidations();
  refreshCaseIndex();
  SpreadsheetApp.getActiveSpreadsheet().toast(
    "Web app support is ready. Deploy the web app as user accessing the app.",
    "JBL TAT Mobile",
    6
  );
}

function setupStaffSheet() {
  requireOwnerOrItUser_();

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(WEB_APP_CONFIG.STAFF_SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(WEB_APP_CONFIG.STAFF_SHEET_NAME);
    sheet.getRange(1, 1, 1, WEB_APP_CONFIG.STAFF_HEADERS.length)
      .setValues([WEB_APP_CONFIG.STAFF_HEADERS]);
    sheet.getRange(2, 1, 2, WEB_APP_CONFIG.STAFF_HEADERS.length).setValues([
      ["bro1@jawabubiz.co.ke", "Sample BRO", "BRO", "No", "*", "Head Office", "Replace sample row"],
      ["approver@jawabubiz.co.ke", "Sample Loan Approver", "LOAN_APPROVER", "No", "*", "Head Office", "Replace sample row"],
    ]);
  } else {
    const width = Math.max(sheet.getLastColumn(), WEB_APP_CONFIG.STAFF_HEADERS.length);
    const existingHeaders = sheet.getRange(1, 1, 1, width).getValues()[0];
    WEB_APP_CONFIG.STAFF_HEADERS.forEach((header, idx) => {
      if (!existingHeaders[idx]) sheet.getRange(1, idx + 1).setValue(header);
    });
  }

  formatStaffSheet_(sheet);
  applyStaffSheetValidation_(sheet);
  SpreadsheetApp.getActiveSpreadsheet().toast("STAFF sheet is ready.", "JBL TAT Mobile", 4);
}

function validateStaffSheetSetup() {
  requireOwnerOrItUser_();

  const result = validateStaffSheetSetup_();
  const lines = [
    `STAFF sheet: ${result.exists ? "Found" : "Missing"}`,
    `Active staff: ${result.activeCount}`,
    `Inactive staff: ${result.inactiveCount}`,
    `Unknown role values: ${result.unknownRoles.length ? result.unknownRoles.join(", ") : "None"}`,
    `Duplicate emails: ${result.duplicateEmails.length ? result.duplicateEmails.join(", ") : "None"}`,
  ];
  SpreadsheetApp.getUi().alert("Web App Staff Validation", lines.join("\n"), SpreadsheetApp.getUi().ButtonSet.OK);
  return result;
}

function runWebAppDiagnostics() {
  requireOwnerOrItUser_();

  const result = buildWebAppDiagnostics_();
  const lines = [
    `STAFF sheet: ${result.staff.exists ? "Found" : "Missing"}`,
    `Active staff: ${result.staff.activeCount}`,
    `Unknown role values: ${result.staff.unknownRoles.length ? result.staff.unknownRoles.join(", ") : "None"}`,
    `Duplicate emails: ${result.staff.duplicateEmails.length ? result.staff.duplicateEmails.join(", ") : "None"}`,
    `AUDIT LOG source column: ${result.auditSourceColumn ? "OK" : "Missing"}`,
    `WebApp.html file: ${result.webAppHtml ? "OK" : "Missing in Apps Script project"}`,
    `Products configured: ${result.productsOk ? "OK" : "Missing tracker sheet(s)"}`,
    `Protection mode: ${WEB_APP_CONFIG.WEB_COMPATIBLE_PROTECTIONS ? "Web-compatible" : "Strict owner-only auto stamps"}`,
    `Current user email visible: ${result.currentUserEmail || "No"}`,
  ];
  SpreadsheetApp.getUi().alert("Mobile Web App Diagnostics", lines.join("\n"), SpreadsheetApp.getUi().ButtonSet.OK);
  return result;
}

function formatStaffSheet_(sheet) {
  sheet.setFrozenRows(1);
  sheet.getRange(1, 1, 1, WEB_APP_CONFIG.STAFF_HEADERS.length)
    .setBackground("#1B3A6B")
    .setFontColor("#FFFFFF")
    .setFontWeight("bold");
  [28, 22, 20, 12, 28, 18, 34].forEach((width, idx) => sheet.setColumnWidth(idx + 1, width * 7));
}

function applyStaffSheetValidation_(sheet) {
  const maxRows = Math.max(sheet.getMaxRows() - 1, 1);
  const emailRule = SpreadsheetApp.newDataValidation()
    .requireTextIsEmail()
    .setAllowInvalid(false)
    .setHelpText("Enter one valid Gmail or organization email address.")
    .build();
  const activeRule = SpreadsheetApp.newDataValidation()
    .requireValueInList(WEB_APP_CONFIG.STAFF_ACTIVE_VALUES, true)
    .setAllowInvalid(false)
    .setHelpText("Choose Yes or No.")
    .build();
  const roleRule = SpreadsheetApp.newDataValidation()
    .requireValueInList(WEB_APP_CONFIG.STAFF_ROLES, true)
    .setAllowInvalid(true)
    .setHelpText("Choose a role. For multiple roles, type comma-separated roles, for example ADMIN,LOAN_APPROVER.")
    .build();
  const sheetRule = SpreadsheetApp.newDataValidation()
    .requireValueInList(["*"].concat(TRACKER_SHEETS), true)
    .setAllowInvalid(true)
    .setHelpText("Choose * for all tracker sheets, or type comma-separated tracker sheet names.")
    .build();
  const branchRule = SpreadsheetApp.newDataValidation()
    .requireValueInList(WEB_APP_CONFIG.BRANCHES, true)
    .setAllowInvalid(true)
    .setHelpText("Choose a branch, or type a branch name if it is not yet in the list.")
    .build();

  sheet.getRange(2, 1, maxRows, 1).setDataValidation(emailRule);
  sheet.getRange(2, 3, maxRows, 1).setDataValidation(roleRule);
  sheet.getRange(2, 4, maxRows, 1).setDataValidation(activeRule);
  sheet.getRange(2, 5, maxRows, 1).setDataValidation(sheetRule);
  sheet.getRange(2, 6, maxRows, 1).setDataValidation(branchRule);
}

function ensureAuditLogSourceColumn_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName("AUDIT LOG");
  if (!sheet) {
    sheet = ss.insertSheet("AUDIT LOG");
    sheet.appendRow(["Logged At", "Editor Email", "Product Sheet", "Case ID", "Row",
                     "Stage Name", "Value Entered", "Hours Since Prev Stage", "Source"]);
    sheet.hideSheet();
    return;
  }
  if (!sheet.getRange(1, 9).getValue()) sheet.getRange(1, 9).setValue("Source");
  sheet.getRange(1, 1, 1, 9).setBackground("#3D3D3D").setFontColor("#FFFFFF").setFontWeight("bold");
}

function ensureCaseIndexSheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(WEB_APP_CONFIG.CASE_INDEX_SHEET_NAME);
  if (!sheet) sheet = ss.insertSheet(WEB_APP_CONFIG.CASE_INDEX_SHEET_NAME);
  sheet.getRange(1, 1, 1, 9).setValues([[
    "Case ID", "Product Sheet", "Row", "Client Name", "Branch", "BRO", "Status", "Created At", "Updated At"
  ]]);
  sheet.getRange(1, 1, 1, 9).setBackground("#3D3D3D").setFontColor("#FFFFFF").setFontWeight("bold");
  sheet.hideSheet();
  return sheet;
}

function ensureCorrectionLogSheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(WEB_APP_CONFIG.CORRECTION_LOG_SHEET_NAME);
  if (!sheet) sheet = ss.insertSheet(WEB_APP_CONFIG.CORRECTION_LOG_SHEET_NAME);
  sheet.getRange(1, 1, 1, 10).setValues([[
    "Logged At", "IT Email", "Product Sheet", "Case ID", "Row", "Column", "Field", "Old Value", "New Value", "Reason"
  ]]);
  sheet.getRange(1, 1, 1, 10).setBackground("#3D3D3D").setFontColor("#FFFFFF").setFontWeight("bold");
  sheet.hideSheet();
  return sheet;
}

function validateStaffSheetSetup_() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(WEB_APP_CONFIG.STAFF_SHEET_NAME);
  const result = {
    exists: Boolean(sheet),
    activeCount: 0,
    inactiveCount: 0,
    unknownRoles: [],
    duplicateEmails: [],
  };
  if (!sheet) return result;

  const lastRow = sheet.getLastRow();
  const lastCol = sheet.getLastColumn();
  if (lastRow < 2 || lastCol < 1) return result;

  const values = sheet.getRange(1, 1, lastRow, lastCol).getValues();
  const header = webHeaderMap_(values[0]);
  const activeEmails = {};

  values.slice(1).forEach(row => {
    const email = String(row[header.email] || "").trim().toLowerCase();
    if (!email) return;

    const active = String(row[header.active] || "").trim().toLowerCase();
    const isActive = ["yes", "y", "true", "active"].includes(active);
    if (isActive) {
      result.activeCount++;
      if (activeEmails[email] && !result.duplicateEmails.includes(email)) result.duplicateEmails.push(email);
      activeEmails[email] = true;
    } else {
      result.inactiveCount++;
    }

    webParseRoles_(row[header.role]).forEach(role => {
      if (!STAFF_ROLE_TEMPLATES[role] && !result.unknownRoles.includes(role)) result.unknownRoles.push(role);
    });
  });
  return result;
}

function buildWebAppDiagnostics_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const missingSheets = TRACKER_SHEETS.filter(name => !ss.getSheetByName(name));
  const auditLog = ss.getSheetByName("AUDIT LOG");

  let webAppHtml = true;
  try {
    HtmlService.createHtmlOutputFromFile("WebApp");
  } catch (e) {
    webAppHtml = false;
  }

  return {
    staff: validateStaffSheetSetup_(),
    auditSourceColumn: Boolean(auditLog && auditLog.getRange(1, 9).getValue() === "Source"),
    webAppHtml,
    productsOk: missingSheets.length === 0,
    missingSheets,
    currentUserEmail: Session.getActiveUser().getEmail() || "",
    webCompatibleProtections: WEB_APP_CONFIG.WEB_COMPATIBLE_PROTECTIONS,
  };
}

function applyAllProtections() {
  requireOwnerOrItUser_();

  TRACKER_SHEETS.forEach(sheetName => {
    applyColumnProtections_(sheetName);
  });
  applyManagementSheetProtections_();
  Logger.log("All tracker and management/support protections applied.");
}

function applyAllTimestampFormats() {
  requireOwnerOrItUser_();

  TRACKER_SHEETS.forEach(sheetName => {
    applyTimestampFormats_(sheetName);
  });
  SpreadsheetApp.getActiveSpreadsheet().toast(
    `Timestamp columns formatted as ${CONFIG.DATE_TIME_FORMAT}.`,
    "Date Format",
    4
  );
}

function applyTimestampFormats_(sheetName) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(sheetName);
  const pConfig = PRODUCTS[sheetName];
  if (!sheet || !pConfig) return;

  const lastRow = Math.max(sheet.getMaxRows(), CONFIG.DATA_START_ROW);
  const numRows = lastRow - CONFIG.DATA_START_ROW + 1;
  pConfig.TS_SEQUENCE.forEach(([col]) => {
    sheet.getRange(CONFIG.DATA_START_ROW, col, numRows, 1).setNumberFormat(CONFIG.DATE_TIME_FORMAT);
  });
}

function applyAllDataValidations() {
  requireOwnerOrItUser_();

  TRACKER_SHEETS.forEach(sheetName => {
    applyTrackerDataValidations_(sheetName);
  });

  const staffSheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(WEB_APP_CONFIG.STAFF_SHEET_NAME);
  if (staffSheet) applyStaffSheetValidation_(staffSheet);

  SpreadsheetApp.getActiveSpreadsheet().toast(
    "Data validation rules applied to tracker and STAFF sheets.",
    "Data Validation",
    5
  );
}

function applyTrackerDataValidations_(sheetName) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(sheetName);
  const pConfig = PRODUCTS[sheetName];
  if (!sheet || !pConfig) return;

  const C = pConfig.COL;
  const lastRow = Math.max(sheet.getMaxRows(), CONFIG.DATA_START_ROW);
  const numRows = lastRow - CONFIG.DATA_START_ROW + 1;

  const branchRule = SpreadsheetApp.newDataValidation()
    .requireValueInList(WEB_APP_CONFIG.BRANCHES, true)
    .setAllowInvalid(false)
    .setHelpText("Choose a valid branch.")
    .build();
  const amountRule = buildAmountDataValidationRule_(pConfig);
  const dateRule = SpreadsheetApp.newDataValidation()
    .requireDateOnOrAfter(CONFIG.VALIDATION_START_DATE)
    .setAllowInvalid(false)
    .setHelpText(`Enter a valid date/time on or after ${formatDate_(CONFIG.VALIDATION_START_DATE)}.`)
    .build();
  const decisionRule = trackerListRule_(WEB_APP_CONFIG.DROPDOWNS.DECISION, "Choose a valid HOCC decision.");
  const sanctionsRule = trackerListRule_(WEB_APP_CONFIG.DROPDOWNS.SANCTIONS, "Choose Pending, Met, or Not Met.");
  const registerRule = trackerListRule_(WEB_APP_CONFIG.DROPDOWNS.REGISTER, "Choose a valid disbursement register batch.");
  const registerApprovedRule = trackerListRule_(WEB_APP_CONFIG.DROPDOWNS.REGISTER_APPROVED, "Choose Approved or Pending.");
  const statusRule = trackerListRule_(WEB_APP_CONFIG.STATUS_VALUES, "Status is system managed. IT corrections must use a valid status.");

  sheet.getRange(CONFIG.DATA_START_ROW, C.BRANCH, numRows, 1).setDataValidation(branchRule);
  sheet.getRange(CONFIG.DATA_START_ROW, C.AMOUNT, numRows, 1).setDataValidation(amountRule);
  applyDataValidationForConfiguredColumn_(sheet, pConfig, "DECISION", numRows, decisionRule);
  applyDataValidationForConfiguredColumn_(sheet, pConfig, "SANCTIONS", numRows, sanctionsRule);
  applyDataValidationForConfiguredColumn_(sheet, pConfig, "REGISTER", numRows, registerRule);
  applyDataValidationForConfiguredColumn_(sheet, pConfig, "REGISTER_APPROVED", numRows, registerApprovedRule);
  sheet.getRange(CONFIG.DATA_START_ROW, C.STATUS, numRows, 1).setDataValidation(statusRule);

  pConfig.TS_SEQUENCE.forEach(([col]) => {
    sheet.getRange(CONFIG.DATA_START_ROW, col, numRows, 1).setDataValidation(dateRule);
  });

  const firstFormulaA1 = columnToLetter_(C.TAT_HRS) + CONFIG.DATA_START_ROW;
  const formulaRule = SpreadsheetApp.newDataValidation()
    .requireFormulaSatisfied(`=OR(ISBLANK(${firstFormulaA1}),ISFORMULA(${firstFormulaA1}))`)
    .setAllowInvalid(false)
    .setHelpText("Formula column. Do not type manual values here.")
    .build();
  const maxFormulaCol = formulaEndColumn_(sheetName, pConfig);
  sheet.getRange(CONFIG.DATA_START_ROW, C.TAT_HRS, numRows, maxFormulaCol - C.TAT_HRS + 1)
    .setDataValidation(formulaRule);
}

function extendTrackerRowsTo2000() {
  extendTrackerRowsTo(CONFIG.DEFAULT_EXTEND_TO_ROW);
}

function extendTrackerRowsTo5000() {
  extendTrackerRowsTo(5000);
}

function extendTrackerRowsTo(targetRow) {
  const target = Number(targetRow);
  if (!Number.isFinite(target) || target < CONFIG.DATA_START_ROW) throw new Error("Invalid target row.");

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  TRACKER_SHEETS.forEach(sheetName => {
    const sheet = ss.getSheetByName(sheetName);
    const pConfig = PRODUCTS[sheetName];
    if (!sheet || !pConfig) return;

    const currentMax = sheet.getMaxRows();
    if (currentMax < target) {
      sheet.insertRowsAfter(currentMax, target - currentMax);
    }

    const templateRow = Math.max(CONFIG.DATA_START_ROW, Math.min(currentMax, getLastDataRow_(sheet, pConfig)));
    const rowsToFill = target - templateRow;
    if (rowsToFill > 0) {
      const source = sheet.getRange(templateRow, pConfig.COL.TAT_HRS, 1, sheet.getLastColumn() - pConfig.COL.TAT_HRS + 1);
      const destination = sheet.getRange(templateRow + 1, pConfig.COL.TAT_HRS, rowsToFill, sheet.getLastColumn() - pConfig.COL.TAT_HRS + 1);
      source.copyTo(destination, SpreadsheetApp.CopyPasteType.PASTE_FORMULA, false);
      source.copyTo(destination, SpreadsheetApp.CopyPasteType.PASTE_FORMAT, false);
    }
  });

  applyAllTimestampFormats();
  applyAllDataValidations();
  applyAllProtections();
  refreshCaseIndex();
  SpreadsheetApp.getActiveSpreadsheet().toast(`Tracker rows extended to row ${target}.`, "Rows Extended", 6);
}

function configuredMaximumAmount_(pConfig) {
  if (!pConfig || pConfig.MAX_AMOUNT === null || pConfig.MAX_AMOUNT === undefined || pConfig.MAX_AMOUNT === "") {
    return null;
  }

  const maximumAmount = Number(pConfig.MAX_AMOUNT);
  return Number.isFinite(maximumAmount) ? maximumAmount : null;
}

function configuredMinimumAmount_(pConfig) {
  if (pConfig && pConfig.MIN_AMOUNT !== null && pConfig.MIN_AMOUNT !== undefined && pConfig.MIN_AMOUNT !== "") {
    const minimumAmount = Number(pConfig.MIN_AMOUNT);
    if (Number.isFinite(minimumAmount)) return minimumAmount;
  }
  return Number(CONFIG.MIN_AMOUNT);
}

function buildAmountDataValidationRule_(pConfig) {
  const builder = SpreadsheetApp.newDataValidation();
  const minimumAmount = configuredMinimumAmount_(pConfig);
  const maximumAmount = configuredMaximumAmount_(pConfig);
  if (Number.isFinite(maximumAmount)) {
    builder.requireNumberBetween(minimumAmount, maximumAmount);
  } else {
    builder.requireNumberGreaterThanOrEqualTo(minimumAmount);
  }
  return builder
    .setAllowInvalid(false)
    .setHelpText(amountHelpText_(pConfig))
    .build();
}

function amountHelpText_(pConfig) {
  const minimumAmount = configuredMinimumAmount_(pConfig);
  const maximumAmount = configuredMaximumAmount_(pConfig);
  if (Number.isFinite(maximumAmount)) {
    return `Amount must be between KES ${minimumAmount.toLocaleString()} and KES ${maximumAmount.toLocaleString()}.`;
  }
  return `Amount must be at least KES ${minimumAmount.toLocaleString()}.`;
}

function amountValidationError_(amount, pConfig, sheetName) {
  const minimumAmount = configuredMinimumAmount_(pConfig);
  const maximumAmount = configuredMaximumAmount_(pConfig);
  if (!Number.isFinite(minimumAmount)) return "The minimum loan amount is not configured correctly.";
  if (!Number.isFinite(amount)) return "Enter a valid loan amount.";
  if (amount < minimumAmount || (Number.isFinite(maximumAmount) && amount > maximumAmount)) {
    const product = sheetName.replace("TRACKER-", "");
    if (Number.isFinite(maximumAmount)) {
      return `Amount for ${product} must be between KES ${minimumAmount.toLocaleString()} and KES ${maximumAmount.toLocaleString()}.`;
    }
    return `Amount for ${product} must be at least KES ${minimumAmount.toLocaleString()}.`;
  }
  return "";
}

function applyDataValidationForConfiguredColumn_(sheet, pConfig, key, numRows, rule) {
  if (!hasConfiguredColumn_(pConfig, key)) return;
  sheet.getRange(CONFIG.DATA_START_ROW, pConfig.COL[key], numRows, 1).setDataValidation(rule);
}

function trackerListRule_(items, helpText) {
  return SpreadsheetApp.newDataValidation()
    .requireValueInList(items, true)
    .setAllowInvalid(false)
    .setHelpText(helpText)
    .build();
}

function columnToLetter_(column) {
  let temp = Number(column);
  let letter = "";
  while (temp > 0) {
    const mod = (temp - 1) % 26;
    letter = String.fromCharCode(65 + mod) + letter;
    temp = Math.floor((temp - mod) / 26);
  }
  return letter;
}

function applyColumnProtections_(sheetName) {
  const ss    = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(sheetName);
  if (!sheet) { Logger.log(`Sheet ${sheetName} not found.`); return; }

  const owner   = ss.getOwner().getEmail();
  const pConfig = PRODUCTS[sheetName];
  const C       = pConfig.COL;
  const lastRow = sheet.getMaxRows();
  const systemCols = systemManagedColumns_(pConfig);
  const staffEditors = new Set([owner]);

  // Remove existing JBL protections on this sheet
  sheet.getProtections(SpreadsheetApp.ProtectionType.RANGE)
    .filter(p => p.getDescription().startsWith("JBL-"))
    .forEach(p => p.remove());

  // Build col -> Set<email> from STAFF. ROLE_MAP is used only if fallback is enabled.
  const colEditors = {};
  for (const [email, roleInfo] of getRoleAssignments_()) {
    const sheets = roleInfo.sheets;
    if (sheets !== "*" && !sheets.includes(sheetName)) continue;
    staffEditors.add(email);

    const cols = roleColumnsForSheet_(roleInfo, sheetName);
    for (const c of cols) {
      if (systemCols.has(c)) continue;
      if (!colEditors[c]) colEditors[c] = new Set();
      colEditors[c].add(email);
      colEditors[c].add(owner);
    }
  }
  // Owner always in every col
  const maxCol = formulaEndColumn_(sheetName, pConfig);
  for (let i = 1; i <= maxCol; i++) {
    if (!colEditors[i]) colEditors[i] = new Set();
    colEditors[i].add(owner);
  }

  // Protect cols 1 to STATUS (skip REMARKS — unprotected)
  const lastProtectedCol = C.STATUS;
  for (let colIdx = 1; colIdx <= lastProtectedCol; colIdx++) {
    const range = sheet.getRange(CONFIG.DATA_START_ROW, colIdx,
                                 lastRow - CONFIG.DATA_START_ROW + 1, 1);
    const prot  = range.protect();
    prot.setDescription(`JBL-COL-${colIdx}`);
    prot.removeEditors(prot.getEditors());
    if (prot.canDomainEdit()) prot.setDomainEdit(false);

    if (systemCols.has(colIdx)) {
      if (WEB_APP_CONFIG.WEB_COMPATIBLE_PROTECTIONS) {
        prot.addEditors(Array.from(staffEditors));
      } else {
        prot.addEditor(owner);
      }
    } else {
      const eds = colEditors[colIdx];
      if (eds && eds.size > 0) prot.addEditors(Array.from(eds));
      else prot.addEditor(owner);
    }
  }

  // Formula cols — owner only
  const remarksProtection = sheet.getRange(CONFIG.DATA_START_ROW, C.REMARKS,
                                           lastRow - CONFIG.DATA_START_ROW + 1, 1).protect();
  remarksProtection.setDescription("JBL-COL-REMARKS");
  remarksProtection.removeEditors(remarksProtection.getEditors());
  remarksProtection.addEditors(Array.from(staffEditors));
  if (remarksProtection.canDomainEdit()) remarksProtection.setDomainEdit(false);
  const formulaRange = sheet.getRange(CONFIG.DATA_START_ROW, C.TAT_HRS,
                                      lastRow - CONFIG.DATA_START_ROW + 1, maxCol - C.TAT_HRS + 1);
  const fp = formulaRange.protect();
  fp.setDescription("JBL-COL-FORMULAS");
  fp.removeEditors(fp.getEditors());
  fp.addEditor(owner);
  if (fp.canDomainEdit()) fp.setDomainEdit(false);

  Logger.log(`Protections applied to ${sheetName}.`);
}

function applyManagementSheetProtections_() {
  const ownerItEditors = getOwnerItEmails_();
  const webWritableEditors = WEB_APP_CONFIG.WEB_COMPATIBLE_PROTECTIONS
    ? normalizeEmailList_(ownerItEditors.concat(getActiveWorkflowStaffEmails_()))
    : ownerItEditors;

  OWNER_IT_PRIVATE_SHEETS_().forEach(sheetName => {
    protectWholeSheet_(sheetName, ownerItEditors, `JBL-SHEET-OWNER-IT-${sheetName}`);
  });

  WEB_WRITABLE_SUPPORT_SHEETS_().forEach(sheetName => {
    protectWholeSheet_(sheetName, webWritableEditors, `JBL-SHEET-WEB-WRITABLE-${sheetName}`);
  });

  MANAGEMENT_VIEW_SHEETS_().forEach(sheetName => {
    protectWholeSheet_(sheetName, ownerItEditors, `JBL-SHEET-MANAGEMENT-VIEW-${sheetName}`);
  });
}

function OWNER_IT_PRIVATE_SHEETS_() {
  return [
    WEB_APP_CONFIG.STAFF_SHEET_NAME,
    WEB_APP_CONFIG.CORRECTION_LOG_SHEET_NAME,
    WEB_APP_CONFIG.ANOMALY_REPORT_SHEET_NAME,
  ];
}

function WEB_WRITABLE_SUPPORT_SHEETS_() {
  return [WEB_APP_CONFIG.CASE_INDEX_SHEET_NAME, "AUDIT LOG"];
}

function MANAGEMENT_VIEW_SHEETS_() {
  return ["DASHBOARD", "PERFORMANCE"];
}

function HIDDEN_SUPPORT_SHEETS_() {
  return OWNER_IT_PRIVATE_SHEETS_().concat(WEB_WRITABLE_SUPPORT_SHEETS_()).concat(MANAGEMENT_VIEW_SHEETS_());
}

function protectWholeSheet_(sheetName, editorEmails, description) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(sheetName);
  if (!sheet) return;

  sheet.getProtections(SpreadsheetApp.ProtectionType.SHEET)
    .filter(p => p.getDescription().startsWith("JBL-SHEET-"))
    .forEach(p => p.remove());

  const protection = sheet.protect().setDescription(description);
  const effectiveUser = Session.getEffectiveUser();
  protection.addEditor(effectiveUser);
  protection.removeEditors(protection.getEditors());
  if (protection.canDomainEdit()) protection.setDomainEdit(false);

  const editors = normalizeEmailList_(editorEmails);
  if (editors.length) protection.addEditors(editors);
  protection.setUnprotectedRanges([]);
}

function configuredColumns_(pConfig, keys) {
  return keys
    .map(key => pConfig.COL[key])
    .filter(col => Number.isInteger(col) && col > 0);
}

function hasConfiguredColumn_(pConfig, key) {
  const col = pConfig.COL[key];
  return Number.isInteger(col) && col > 0;
}

function isConfiguredColumn_(pConfig, key, col) {
  return hasConfiguredColumn_(pConfig, key) && col === pConfig.COL[key];
}

function workflowActionColumns_(pConfig) {
  return configuredColumns_(pConfig, ["DECISION", "SANCTIONS", "REGISTER", "REGISTER_APPROVED"]);
}

function systemManagedColumns_(pConfig) {
  return new Set(configuredColumns_(pConfig, [
    "CASE_ID",
    "TS_CREATED",
    "TS_DECISION",
    "TS_SANCTIONS",
    "TS_REGISTER",
    "STATUS"
  ]));
}

function formulaEndColumn_(sheetName, pConfig) {
  if (Number.isInteger(pConfig.FORMULA_END_COL) && pConfig.FORMULA_END_COL >= pConfig.COL.TAT_HRS) {
    return pConfig.FORMULA_END_COL;
  }
  return sheetName === "TRACKER-LOGBOOK" ? 42 : 40;
}

function roleColumnsForSheet_(roleInfo, sheetName) {
  if (sheetName === "TRACKER-LOGBOOK") return roleInfo.cols_logbook || [];
  if (sheetName === "TRACKER-Business") return roleInfo.cols_business || [];
  return roleInfo.cols_other || [];
}

function canDirectlyEditTrackerColumn_(sheetName, col) {
  const email = getActiveEditorEmail_();
  if (!email || isOwnerEmail_(email)) return true;

  const user = webFindStaffUser_(email);
  if (!user || !user.authorized || !webCanAccessSheet_(user, sheetName)) return false;
  return webCanEditColumn_(user, sheetName, col);
}
function restoreEditedCell_(range, oldValue, pConfig) {
  const col = range.getColumn();
  const shouldKeepTimestampFormat = isTimestampColumn_(pConfig, col);
  const restoredValue = oldValue !== undefined ? normalizeOldValueForRestore_(oldValue, shouldKeepTimestampFormat) : "";
  range.setValue(restoredValue);
  if (shouldKeepTimestampFormat) range.setNumberFormat(CONFIG.DATE_TIME_FORMAT);
}

function normalizeOldValueForRestore_(oldValue, shouldParseDate) {
  if (!shouldParseDate || oldValue === "" || oldValue === null || oldValue === undefined) return oldValue || "";
  if (oldValue instanceof Date) return oldValue;

  const numeric = Number(oldValue);
  if (Number.isFinite(numeric) && numeric > 1) {
    return numeric;
  }

  const parsed = new Date(oldValue);
  return Number.isNaN(parsed.getTime()) ? oldValue : parsed;
}

function isTimestampColumn_(pConfig, col) {
  return pConfig.TS_SEQUENCE.some(stage => stage[0] === col);
}


// ════════════════════════════════════════════════════════════════════════════
//  3. onEdit HANDLER — automation for all products
// ════════════════════════════════════════════════════════════════════════════
function onEditHandler(e) {
  if (!e || !e.range) return;

  const range = e.range;
  const sheet = range.getSheet();
  const sheetName = sheet.getName();

  // Clear cache if STAFF sheet is edited
  if (sheetName === WEB_APP_CONFIG.STAFF_SHEET_NAME) {
    try {
      CacheService.getScriptCache().removeAll();
    } catch (err) {
      Logger.log("Failed to clear script cache: " + err.message);
    }
    return;
  }

  // Only process TRACKER sheets
  if (!TRACKER_SHEETS.includes(sheetName)) return;

  const pConfig = PRODUCTS[sheetName];
  const C = pConfig.COL;
  const row = range.getRow();
  const col = range.getColumn();

  // Ignore headers
  if (row < CONFIG.DATA_START_ROW) return;

  // Avoid processing multi-cell edits/pastes as a single workflow action
  if (range.getNumRows() !== 1 || range.getNumColumns() !== 1) {
    SpreadsheetApp.getActiveSpreadsheet().toast(
      "Please edit one workflow cell at a time.",
      "Single-Cell Edit Required",
      6
    );
    return;
  }

  const val = range.getValue();
  const oldVal = e.oldValue;

  if (!canDirectlyEditTrackerColumn_(sheetName, col)) {
    restoreEditedCell_(range, oldVal, pConfig);
    SpreadsheetApp.getActiveSpreadsheet().toast(
      "Your STAFF role is not allowed to edit this field. Entry reverted.",
      "Role Restricted",
      8
    );
    return;
  }

  // ────────────────────────────────────────────────────────────────────
  // a) Client Name → auto Case ID + auto Case Created
  // ────────────────────────────────────────────────────────────────────
  if (col === C.CLIENT_NAME && val !== "") {
    const idCell = sheet.getRange(row, C.CASE_ID);

    if (!idCell.getValue()) {
      idCell.setValue(generateCaseId_(sheet, sheetName));
    }

    const tsCell = sheet.getRange(row, C.TS_CREATED);

    if (!tsCell.getValue()) {
      tsCell.setValue(new Date());
      SpreadsheetApp.flush();
      tsCell.setNumberFormat(CONFIG.DATE_TIME_FORMAT);
    }

    const statusCell = sheet.getRange(row, C.STATUS);

    if (!statusCell.getValue()) {
      statusCell.setValue("Active");
    }
  }

  // ────────────────────────────────────────────────────────────────────
  // b) Amount validation — minimum and sheet-specific maximum
  // ────────────────────────────────────────────────────────────────────
  if (col === C.AMOUNT && val !== "") {
    const amountError = amountValidationError_(Number(val), pConfig, sheetName);

    if (amountError) {
      restoreEditedCell_(range, oldVal, pConfig);

      SpreadsheetApp.getActiveSpreadsheet().toast(
        `${amountError} Entry reverted.`,
        "Invalid Amount",
        8
      );

      return;
    }
  }

  // ────────────────────────────────────────────────────────────────────
  // c) Block direct editing of system-managed fields
  // ────────────────────────────────────────────────────────────────────
  if (col === C.CASE_ID) {
    restoreEditedCell_(range, oldVal, pConfig);

    SpreadsheetApp.getActiveSpreadsheet().toast(
      "Case ID is system managed. Enter Client Name to generate it.",
      "Case ID Locked",
      6
    );

    return;
  }

  if (col === C.STATUS) {
    restoreEditedCell_(range, oldVal, pConfig);

    SpreadsheetApp.getActiveSpreadsheet().toast(
      "Status is system managed. Use the workflow fields instead.",
      "Status Locked",
      6
    );

    return;
  }

  if (configuredColumns_(pConfig, ["TS_CREATED", "TS_DECISION", "TS_SANCTIONS", "TS_REGISTER"]).includes(col)) {
    restoreEditedCell_(range, oldVal, pConfig);

    SpreadsheetApp.getActiveSpreadsheet().toast(
      "This timestamp is system managed. Use the related workflow field instead.",
      "System Managed",
      8
    );

    return;
  }

  // ────────────────────────────────────────────────────────────────────
  // d) Prevent changes to completed workflow actions
  // ────────────────────────────────────────────────────────────────────
  const FINAL_ACTION_COLS = new Set([
    ...pConfig.TS_SEQUENCE.map(stage => stage[0]),
    ...workflowActionColumns_(pConfig),
  ]);

  if (
    FINAL_ACTION_COLS.has(col) &&
    oldVal !== undefined &&
    oldVal !== "" &&
    val !== oldVal
  ) {
    restoreEditedCell_(range, oldVal, pConfig);

    SpreadsheetApp.getActiveSpreadsheet().toast(
      "This workflow action is final and cannot be changed.",
      "Action Locked",
      8
    );

    return;
  }

  // ────────────────────────────────────────────────────────────────────
  // e) Validate manual timestamp workflow sequence
  // ────────────────────────────────────────────────────────────────────
  if (
    pConfig.TS_SEQUENCE.some(stage => stage[0] === col) &&
    val instanceof Date
  ) {
    if (oldVal !== undefined && oldVal !== "") {
      restoreEditedCell_(range, oldVal, pConfig);

      SpreadsheetApp.getActiveSpreadsheet().toast(
        "This timestamp is final and cannot be changed.",
        "Stamp Locked",
        8
      );

      return;
    }

    if (!webPreviousStagesComplete_(sheet, row, pConfig, col)) {
      restoreEditedCell_(range, oldVal, pConfig);

      SpreadsheetApp.getActiveSpreadsheet().toast(
        "The previous workflow stage must be completed first. Entry reverted.",
        "Sequence Required",
        8
      );

      return;
    }
  }

  // ────────────────────────────────────────────────────────────────────
  // f) Validate dropdown workflow sequence
  // ────────────────────────────────────────────────────────────────────
  if (
    workflowActionColumns_(pConfig).includes(col) &&
    val !== ""
  ) {
    if (oldVal !== undefined && oldVal !== "") {
      restoreEditedCell_(range, oldVal, pConfig);

      SpreadsheetApp.getActiveSpreadsheet().toast(
        "This workflow action is final and cannot be changed.",
        "Action Locked",
        8
      );

      return;
    }

    if (!webPreviousStagesComplete_(sheet, row, pConfig, col)) {
      restoreEditedCell_(range, oldVal, pConfig);

      SpreadsheetApp.getActiveSpreadsheet().toast(
        "The previous workflow stage must be completed first. Entry reverted.",
        "Sequence Required",
        8
      );

      return;
    }
  }

  // ────────────────────────────────────────────────────────────────────
  // g) HOCC Decision → auto-stamp Decision timestamp
  // ────────────────────────────────────────────────────────────────────
  if (isConfiguredColumn_(pConfig, "DECISION", col) && val !== "") {
    const tsCell = sheet.getRange(row, C.TS_DECISION);

    if (!tsCell.getValue()) {
      const now = new Date();

      tsCell.setValue(now);
      SpreadsheetApp.flush();
      tsCell.setNumberFormat(CONFIG.DATE_TIME_FORMAT);

      writeAuditLog_(
        sheetName,
        sheet.getRange(row, C.CASE_ID).getValue(),
        row,
        "Decision TS",
        now
      );
    }

    if (val === "Rejected") {
      sheet.getRange(row, C.STATUS).setValue("Rejected");
    }

    if (val === "Deferred") {
      sheet.getRange(row, C.STATUS).setValue("Deferred");
    }
  }

  // ────────────────────────────────────────────────────────────────────
  // h) Sanctions dropdown → auto-stamp Sanctions timestamp
  // ────────────────────────────────────────────────────────────────────
  if (isConfiguredColumn_(pConfig, "SANCTIONS", col)) {
    if (val === "Met") {
      const tsCell = sheet.getRange(row, C.TS_SANCTIONS);

      if (!tsCell.getValue()) {
        const now = new Date();

        tsCell.setValue(now);
        SpreadsheetApp.flush();
        tsCell.setNumberFormat(CONFIG.DATE_TIME_FORMAT);

        writeAuditLog_(
          sheetName,
          sheet.getRange(row, C.CASE_ID).getValue(),
          row,
          "Sanctions TS",
          now
        );
      }
    }

    if (val === "Not Met") {
      const remarksCell = sheet.getRange(row, C.REMARKS);
      const existingRemarks = remarksCell.getValue();

      if (!String(existingRemarks).includes("Sanctions Not Met")) {
        remarksCell.setValue(
          `[${formatDate_(new Date())}: Sanctions Not Met — ` +
          `conditions unfulfilled] ${existingRemarks}`
        );
      }
    }
  }

  // ────────────────────────────────────────────────────────────────────
  // i) BRO Apply blocked unless Sanctions = Met
  // ────────────────────────────────────────────────────────────────────
  if (col === C.TS_LO_APPLY && val instanceof Date && hasConfiguredColumn_(pConfig, "SANCTIONS")) {
    const sanctionsValue = sheet
      .getRange(row, C.SANCTIONS)
      .getValue();

    if (sanctionsValue !== "Met") {
      restoreEditedCell_(range, oldVal, pConfig);

      SpreadsheetApp.getActiveSpreadsheet().toast(
        "Sanctions must be marked 'Met' before applying on the system. " +
        "Entry reverted.",
        "Sanctions Required",
        8
      );

      return;
    }
  }

  // ────────────────────────────────────────────────────────────────────
  // j) Disbursement Register → auto-stamp Register timestamp
  // ────────────────────────────────────────────────────────────────────
  if (isConfiguredColumn_(pConfig, "REGISTER", col) && val !== "") {
    const tsCell = sheet.getRange(row, C.TS_REGISTER);

    if (!tsCell.getValue()) {
      const now = new Date();

      tsCell.setValue(now);
      SpreadsheetApp.flush();
      tsCell.setNumberFormat(CONFIG.DATE_TIME_FORMAT);

      writeAuditLog_(
        sheetName,
        sheet.getRange(row, C.CASE_ID).getValue(),
        row,
        "Register TS",
        now
      );
    }
  }

  // ────────────────────────────────────────────────────────────────────
  // k) Disbursement blocked unless Register Approved = Approved
  // ────────────────────────────────────────────────────────────────────
  if (col === C.TS_DISBURSE && val instanceof Date) {
    const registerApproval = sheet
      .getRange(row, C.REGISTER_APPROVED)
      .getValue();

    if (registerApproval !== "Approved") {
      restoreEditedCell_(range, oldVal, pConfig);

      SpreadsheetApp.getActiveSpreadsheet().toast(
        "The loan must be Register-Approved before disbursement. " +
        "Entry reverted.",
        "Approval Required",
        8
      );

      return;
    }

    // Automatically mark the case as disbursed
    sheet.getRange(row, C.STATUS).setValue("Disbursed");
  }

  // ────────────────────────────────────────────────────────────────────
  // l) Timestamp formatting, time injection and date-flow validation
  // ────────────────────────────────────────────────────────────────────
  const AUTO_TS = new Set(configuredColumns_(pConfig, ["TS_CREATED", "TS_DECISION", "TS_SANCTIONS", "TS_REGISTER"]));

  const ALL_TS = new Set(
    pConfig.TS_SEQUENCE.map(stage => stage[0])
  );

  if (ALL_TS.has(col) && val instanceof Date) {
    let timestampValue = val;

    // If a user entered only a date, inject the current time
    if (
      !AUTO_TS.has(col) &&
      timestampValue.getHours() === 0 &&
      timestampValue.getMinutes() === 0
    ) {
      const now = new Date();

      timestampValue = new Date(timestampValue);
      timestampValue.setHours(
        now.getHours(),
        now.getMinutes(),
        now.getSeconds(),
        0
      );

      range.setValue(timestampValue);
      SpreadsheetApp.flush();
    }

    const violation = checkDateFlow_(
      sheet,
      row,
      col,
      pConfig
    );

    if (violation) {
      restoreEditedCell_(range, oldVal, pConfig);

      SpreadsheetApp.getActiveSpreadsheet().toast(
        `"${violation.thisLabel}" cannot be earlier than ` +
        `"${violation.prevLabel}" ` +
        `(${formatDate_(violation.prevDate)}). Entry reverted.`,
        "Date Sequence Error",
        10
      );

      return;
    }

    range.setNumberFormat(CONFIG.DATE_TIME_FORMAT);

    const stageName =
      pConfig.STAGE_NAMES[col] || `Column ${col}`;

    writeAuditLog_(
      sheetName,
      sheet.getRange(row, C.CASE_ID).getValue(),
      row,
      stageName,
      timestampValue
    );
  }

  // ────────────────────────────────────────────────────────────────────
  // m) Audit dropdown changes
  // ────────────────────────────────────────────────────────────────────
  if (
    workflowActionColumns_(pConfig).includes(col) &&
    val !== ""
  ) {
    const stageName =
      pConfig.STAGE_NAMES[col] || `Column ${col}`;

    writeAuditLog_(
      sheetName,
      sheet.getRange(row, C.CASE_ID).getValue(),
      row,
      stageName,
      val
    );
  }

  // Keep the searchable case index up to date
  try {
    updateCaseIndex_(sheetName, row, pConfig);
  } catch (error) {
    Logger.log(`Case index update failed: ${error.message}`);
  }
}


// ════════════════════════════════════════════════════════════════════════════
//  4. AUDIT LOG — tracks all timestamp entries
// ════════════════════════════════════════════════════════════════════════════
function writeAuditLog_(sheetName, caseId, row, stageName, value, source) {
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    let logSheet = ss.getSheetByName("AUDIT LOG");

    if (!logSheet) {
      logSheet = ss.insertSheet("AUDIT LOG");
      logSheet.appendRow(["Logged At", "Editor Email", "Product Sheet", "Case ID", "Row",
                          "Stage Name", "Value Entered", "Hours Since Prev Stage", "Source"]);
      logSheet.getRange(1, 1, 1, 9).setBackground("#3D3D3D").setFontColor("#FFFFFF").setFontWeight("bold");
      logSheet.hideSheet();
    } else if (!logSheet.getRange(1, 9).getValue()) {
      logSheet.getRange(1, 9).setValue("Source");
      logSheet.getRange(1, 1, 1, 9).setBackground("#3D3D3D").setFontColor("#FFFFFF").setFontWeight("bold");
    }

    const editorEmail = Session.getActiveUser().getEmail() || "unknown";
    const valueStr = value instanceof Date ? formatDate_(value) : String(value);

    // Calculate hours since previous stage (simplified)
    const hoursSincePrev = "—"; // Can be computed if needed

    logSheet.appendRow([
      new Date(),
      editorEmail,
      sheetName,
      caseId,
      row,
      stageName,
      valueStr,
      hoursSincePrev,
      source || "SHEET_EDIT"
    ]);
  } catch (e) {
    Logger.log(`Audit log error: ${e.message}`);
  }
}

function refreshCaseIndex() {
  const sheet = ensureCaseIndexSheet_();
  const values = [];
  const seenCaseIds = new Set();
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const now = new Date();

  TRACKER_SHEETS.forEach(sheetName => {
    const tracker = ss.getSheetByName(sheetName);
    const pConfig = PRODUCTS[sheetName];
    if (!tracker || !pConfig) return;

    const C = pConfig.COL;
    const lastRow = getLastDataRow_(tracker, pConfig);
    if (lastRow < CONFIG.DATA_START_ROW) return;

    const data = tracker.getRange(CONFIG.DATA_START_ROW, 1, lastRow - CONFIG.DATA_START_ROW + 1, C.REMARKS).getValues();
    data.forEach((rowValues, i) => {
      const caseId = String(rowValues[C.CASE_ID - 1] || "").trim();
      if (!caseId) return;
      if (seenCaseIds.has(caseId)) return;
      seenCaseIds.add(caseId);
      values.push([
        caseId,
        sheetName,
        CONFIG.DATA_START_ROW + i,
        rowValues[C.CLIENT_NAME - 1],
        rowValues[C.BRANCH - 1],
        rowValues[C.LO_NAME - 1],
        rowValues[C.STATUS - 1],
        rowValues[C.TS_CREATED - 1],
        now,
      ]);
    });
  });

  const maxRows = Math.max(sheet.getMaxRows() - 1, 1);
  sheet.getRange(2, 1, maxRows, 9).clearContent();
  if (sheet.getMaxRows() < values.length + 1) {
    sheet.insertRowsAfter(sheet.getMaxRows(), values.length + 1 - sheet.getMaxRows());
  }
  if (values.length) sheet.getRange(2, 1, values.length, 9).setValues(values);
  sheet.hideSheet();
  SpreadsheetApp.getActiveSpreadsheet().toast(`CASE_INDEX refreshed: ${values.length} cases.`, "Case Index", 5);
}

function generateAuditAnomalyReport() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const audit = ss.getSheetByName("AUDIT LOG");
  if (!audit || audit.getLastRow() < 2) {
    SpreadsheetApp.getUi().alert("No audit log rows found.");
    return;
  }

  let report = ss.getSheetByName(WEB_APP_CONFIG.ANOMALY_REPORT_SHEET_NAME);
  if (!report) report = ss.insertSheet(WEB_APP_CONFIG.ANOMALY_REPORT_SHEET_NAME);
  report.clear();
  report.getRange(1, 1, 1, 8).setValues([[
    "Detected At", "Severity", "Type", "Editor Email", "Product Sheet", "Case ID", "Audit Row", "Details"
  ]]);
  report.getRange(1, 1, 1, 8).setBackground("#3D3D3D").setFontColor("#FFFFFF").setFontWeight("bold");

  const rows = audit.getRange(2, 1, audit.getLastRow() - 1, Math.max(audit.getLastColumn(), 9)).getValues();
  const now = new Date();
  const anomalies = [];
  const userDayCounts = {};
  const userHourCounts = {};

  rows.forEach((row, i) => {
    const auditRow = i + 2;
    const loggedAt = row[0];
    const email = String(row[1] || "");
    const sheetName = String(row[2] || "");
    const caseId = String(row[3] || "");
    const stage = String(row[5] || "");
    const value = row[6];
    const source = String(row[8] || "");

    if (loggedAt instanceof Date) {
      const hour = loggedAt.getHours();
      const dayKey = `${email}|${Utilities.formatDate(loggedAt, Session.getScriptTimeZone(), "yyyy-MM-dd")}`;
      const hourKey = `${dayKey}|${hour}`;
      userDayCounts[dayKey] = (userDayCounts[dayKey] || 0) + 1;
      userHourCounts[hourKey] = (userHourCounts[hourKey] || 0) + 1;

      if (hour < 7 || hour > 20) {
        anomalies.push([now, "Medium", "Outside Working Hours", email, sheetName, caseId, auditRow, `${stage} logged at ${formatDate_(loggedAt)}`]);
      }
    }

    if (source === "SHEET_EDIT") {
      anomalies.push([now, "Medium", "Direct Sheet Edit", email, sheetName, caseId, auditRow, `${stage}: ${value}`]);
    }
    if (source === "IT_CORRECTION" || stage.indexOf("IT Correction") === 0) {
      anomalies.push([now, "High", "Correction", email, sheetName, caseId, auditRow, `${stage}: ${value}`]);
    }
  });

  Object.keys(userDayCounts).forEach(key => {
    if (userDayCounts[key] >= 25) {
      const [email, day] = key.split("|");
      anomalies.push([now, "Medium", "High Daily Stamp Volume", email, "", "", "", `${userDayCounts[key]} audit actions on ${day}`]);
    }
  });
  Object.keys(userHourCounts).forEach(key => {
    if (userHourCounts[key] >= 10) {
      const [email, day, hour] = key.split("|");
      anomalies.push([now, "Medium", "Burst Stamping", email, "", "", "", `${userHourCounts[key]} audit actions on ${day} during hour ${hour}`]);
    }
  });

  if (report.getMaxRows() < anomalies.length + 1) {
    report.insertRowsAfter(report.getMaxRows(), anomalies.length + 1 - report.getMaxRows());
  }
  if (anomalies.length) report.getRange(2, 1, anomalies.length, 8).setValues(anomalies);
  report.autoResizeColumns(1, 8);
  report.showSheet();
  report.activate();
  SpreadsheetApp.getActiveSpreadsheet().toast(`Audit anomalies generated: ${anomalies.length}.`, "Audit Report", 6);
}

function updateCaseIndex_(sheetName, row, pConfig) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const tracker = ss.getSheetByName(sheetName);
  if (!tracker) return;

  const C = pConfig.COL;
  const rowValues = tracker.getRange(row, 1, 1, C.REMARKS).getValues()[0];
  const caseId = String(rowValues[C.CASE_ID - 1] || "").trim();
  if (!caseId) return;

  const index = ensureCaseIndexSheet_();
  const lastRow = index.getLastRow();

  // Use CacheService to remember which index row a caseId lives on, avoiding
  // a full column-A scan on every stage stamp.
  const cache    = CacheService.getScriptCache();
  const cacheKey = "cidx_" + caseId;
  const cached   = cache.get(cacheKey);
  let targetRow  = lastRow + 1;
  const duplicateRows = [];

  if (cached) {
    // Fast path: trust the cached row number.
    targetRow = Number(cached);
  } else if (lastRow >= 2) {
    // Slow path: scan column A of the index to find any existing entry.
    const ids = index.getRange(2, 1, lastRow - 1, 1).getValues();
    for (let i = 0; i < ids.length; i++) {
      if (String(ids[i][0] || "") === caseId) {
        const indexRow = i + 2;
        if (targetRow === lastRow + 1) {
          targetRow = indexRow;
        } else {
          duplicateRows.push(indexRow);
        }
      }
    }
  }

  duplicateRows.reverse().forEach(indexRow => index.deleteRow(indexRow));

  if (index.getMaxRows() < targetRow) {
    index.insertRowsAfter(index.getMaxRows(), targetRow - index.getMaxRows());
  }
  index.getRange(targetRow, 1, 1, 9).setValues([[
    caseId,
    sheetName,
    row,
    rowValues[C.CLIENT_NAME - 1],
    rowValues[C.BRANCH - 1],
    rowValues[C.LO_NAME - 1],
    rowValues[C.STATUS - 1],
    rowValues[C.TS_CREATED - 1],
    new Date(),
  ]]);
  index.hideSheet();

  // Cache the confirmed index row number for 6 hours.
  try { cache.put(cacheKey, String(targetRow), 21600); } catch (e) { /* ignore */ }
}


// ════════════════════════════════════════════════════════════════════════════
//  5. DAILY MORNING RUN (8am EAT)
// ════════════════════════════════════════════════════════════════════════════
function dailyMorningRun() {
  TRACKER_SHEETS.forEach(sheetName => {
    lockCompletedStages_(sheetName);
    flagOverdueCases_(sheetName);
  });
  sendOverdueAlert_();
  hideManagementSheets_();
}


// ════════════════════════════════════════════════════════════════════════════
//  6. CELL-LEVEL LOCKING
// ════════════════════════════════════════════════════════════════════════════
function lockCompletedStages_(sheetName) {
  const ss      = SpreadsheetApp.getActiveSpreadsheet();
  const sheet   = ss.getSheetByName(sheetName);
  if (!sheet) return;

  const owner   = ss.getOwner().getEmail();
  const pConfig = PRODUCTS[sheetName];
  const lastRow = getLastDataRow_(sheet, pConfig);

  // Remove existing cell locks
  sheet.getProtections(SpreadsheetApp.ProtectionType.RANGE)
    .filter(p => p.getDescription().startsWith("JBL-LOCK"))
    .forEach(p => p.remove());

  for (let row = CONFIG.DATA_START_ROW; row <= lastRow; row++) {
    for (const [lockStr, triggerCol] of Object.entries(pConfig.LOCK_ON_NEXT)) {
      const lockCol    = parseInt(lockStr);
      const lockVal    = sheet.getRange(row, lockCol).getValue();
      const triggerVal = sheet.getRange(row, triggerCol).getValue();
      if (lockVal instanceof Date && triggerVal instanceof Date) {
        const prot = sheet.getRange(row, lockCol).protect();
        prot.setDescription(`JBL-LOCK-R${row}C${lockCol}`);
        prot.removeEditors(prot.getEditors());
        prot.addEditor(owner);
        if (prot.canDomainEdit()) prot.setDomainEdit(false);
      }
    }
  }
  Logger.log(`Stage cell locking done for ${sheetName}.`);
}


// ════════════════════════════════════════════════════════════════════════════
//  7. OVERDUE FLAGGING + ALERTS
// ════════════════════════════════════════════════════════════════════════════
function flagOverdueCases_(sheetName) {
  const ss      = SpreadsheetApp.getActiveSpreadsheet();
  const sheet   = ss.getSheetByName(sheetName);
  if (!sheet) return;

  const pConfig = PRODUCTS[sheetName];
  const C       = pConfig.COL;
  const lastRow = getLastDataRow_(sheet, pConfig);
  const now     = new Date();
  const prefix  = CONFIG.CASE_ID_PREFIX[sheetName];

  for (let row = CONFIG.DATA_START_ROW; row <= lastRow; row++) {
    const caseId = sheet.getRange(row, C.CASE_ID).getValue();
    if (!String(caseId).startsWith(prefix)) continue;

    const status  = String(sheet.getRange(row, C.STATUS).getValue() || "").trim();
    if (shouldSkipAutomatedOverdueFlag_(status)) continue;

    const created = sheet.getRange(row, C.TS_CREATED).getValue();
    if (!(created instanceof Date)) continue;

    if (sheet.getRange(row, C.TS_DISBURSE).getValue() instanceof Date) continue;

    const hrs = (now - created) / 3600000;
    if (hrs > CONFIG.TARGETS_HRS.TOTAL) {
      if (status === "Active") {
        sheet.getRange(row, C.STATUS).setValue("Stalled");
        updateCaseIndex_(sheetName, row, pConfig);
        writeAuditLog_(sheetName, caseId, row, "Auto Status Change", "Active -> Stalled", "DAILY_AUTO");
      }
      const rem = sheet.getRange(row, C.REMARKS).getValue();
      if (!String(rem).includes("AUTO-FLAGGED")) {
        sheet.getRange(row, C.REMARKS).setValue(
          `[AUTO-FLAGGED ${formatDate_(now)}: ${Math.round(hrs)}hrs elapsed] ${rem}`
        );
      }
    }
  }
}

function shouldSkipAutomatedOverdueFlag_(status) {
  return !["Active", "Stalled"].includes(status);
}

function sendOverdueAlert_() {
  const ss    = SpreadsheetApp.getActiveSpreadsheet();
  const now   = new Date();
  const cases = [];

  TRACKER_SHEETS.forEach(sheetName => {
    const sheet   = ss.getSheetByName(sheetName);
    if (!sheet) return;

    const pConfig = PRODUCTS[sheetName];
    const C       = pConfig.COL;
    const lastRow = getLastDataRow_(sheet, pConfig);
    const prefix  = CONFIG.CASE_ID_PREFIX[sheetName];

    for (let row = CONFIG.DATA_START_ROW; row <= lastRow; row++) {
      const caseId = sheet.getRange(row, C.CASE_ID).getValue();
      if (!String(caseId).startsWith(prefix)) continue;

      const status  = sheet.getRange(row, C.STATUS).getValue();
      if (!["Stalled", "Active"].includes(status)) continue;

      const created = sheet.getRange(row, C.TS_CREATED).getValue();
      if (!(created instanceof Date)) continue;

      const hrs = Math.round((now - created) / 3600000);
      if (hrs <= CONFIG.TARGETS_HRS.TOTAL) continue;

      cases.push({
        caseId, hrs, status,
        product: sheetName.replace("TRACKER-", ""),
        client: sheet.getRange(row, C.CLIENT_NAME).getValue(),
        branch: sheet.getRange(row, C.BRANCH).getValue(),
        stage:  currentStage_(sheet, row, pConfig),
      });
    }
  });

  if (!cases.length) return;

  const tableRows = cases.map(c =>
    `<tr style="background:${c.hrs > CONFIG.TARGETS_HRS.TOTAL * 1.5 ? "#FADBD8" : "#FEF9E7"}">
      <td>${c.caseId}</td><td>${c.product}</td><td>${c.client}</td><td>${c.branch}</td>
      <td style="font-weight:bold;color:#C0392B;text-align:center">${c.hrs}h</td>
      <td>${c.stage}</td><td>${c.status}</td></tr>`
  ).join("");

  MailApp.sendEmail({
    to:      `${CONFIG.EMAILS.ADMIN},${CONFIG.EMAILS.DOO}`,
    subject: `JBL TAT Alert — ${cases.length} Overdue Case(s) — ${formatDate_(now)}`,
    htmlBody: `
      <p style="font-family:Arial,sans-serif">
        <strong>${cases.length} case(s)</strong> exceed the ${CONFIG.TARGETS_HRS.TOTAL}hr TAT target.
      </p>
      <table border="1" cellpadding="6" cellspacing="0"
        style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:12px">
        <tr style="background:#1B3A6B;color:#fff">
          <th>Case ID</th><th>Product</th><th>Client</th><th>Branch</th>
          <th>TAT</th><th>Blocked At</th><th>Status</th>
        </tr>${tableRows}
      </table>
      <p style="color:#888;font-size:11px;font-family:Arial,sans-serif">
        Automated alert — JBL HOCC TAT Tracker v5.3</p>`
  });
}


// ════════════════════════════════════════════════════════════════════════════
//  8. WEEKLY REPORT
// ════════════════════════════════════════════════════════════════════════════
function sendWeeklyReport() {
  const ss  = SpreadsheetApp.getActiveSpreadsheet();
  const now = new Date();

  let total = 0, active = 0, disbursed = 0, stalled = 0, rejected = 0, deferred = 0;
  const productStats = {};
  const activeCases = [];

  TRACKER_SHEETS.forEach(sheetName => {
    const sheet   = ss.getSheetByName(sheetName);
    if (!sheet) return;

    const pConfig = PRODUCTS[sheetName];
    const C       = pConfig.COL;
    const lastRow = getLastDataRow_(sheet, pConfig);
    const prefix  = CONFIG.CASE_ID_PREFIX[sheetName];
    const product = sheetName.replace("TRACKER-", "");

    productStats[product] = { total: 0, active: 0, disbursed: 0, stalled: 0 };

    for (let row = CONFIG.DATA_START_ROW; row <= lastRow; row++) {
      const caseId = sheet.getRange(row, C.CASE_ID).getValue();
      if (!String(caseId).startsWith(prefix)) continue;

      total++;
      productStats[product].total++;

      const status = sheet.getRange(row, C.STATUS).getValue();
      if (status === "Active") {
        active++;
        productStats[product].active++;
        activeCases.push(buildSummary_(sheet, row, pConfig, product));
      }
      if (status === "Disbursed") { disbursed++; productStats[product].disbursed++; }
      if (status === "Stalled") {
        stalled++;
        productStats[product].stalled++;
        activeCases.push(buildSummary_(sheet, row, pConfig, product));
      }
      if (status === "Rejected" || status === "Declined") rejected++;
      if (status === "Deferred") deferred++;
    }
  });

  const productRows = Object.entries(productStats).map(([name, stats]) =>
    `<tr><td>${name}</td><td style="text-align:center">${stats.total}</td>
     <td style="text-align:center">${stats.active}</td>
     <td style="text-align:center;color:#27AE60;font-weight:bold">${stats.disbursed}</td>
     <td style="text-align:center;color:#C0392B;font-weight:bold">${stats.stalled}</td></tr>`
  ).join("");

  const caseRows = activeCases.map(c =>
    `<tr style="background:${c.status === "Stalled" ? "#FADBD8" : "#fff"}">
      <td>${c.caseId}</td><td>${c.product}</td><td>${c.client}</td><td>${c.branch}</td>
      <td style="text-align:center;font-weight:bold">${c.hrs || "-"}</td>
      <td>${c.stage}</td><td>${c.status}</td></tr>`
  ).join("");

  MailApp.sendEmail({
    to: CONFIG.EMAILS.MD,
    cc: CONFIG.EMAILS.DOO,
    subject: `JBL HOCC Weekly TAT Report — ${formatDate_(now)}`,
    htmlBody: `
      <p style="font-family:Arial,sans-serif">Dear MD,</p>
      <p style="font-family:Arial,sans-serif">Weekly HOCC TAT Summary — ${formatDate_(now)}</p>

      <h3 style="font-family:Arial,sans-serif;color:#1B3A6B">Overall Volume</h3>
      <table border="1" cellpadding="5" cellspacing="0"
        style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:12px">
        <tr style="background:#1B3A6B;color:#fff"><th>Metric</th><th>Count</th></tr>
        <tr><td>Total</td><td style="text-align:center;font-weight:bold">${total}</td></tr>
        <tr style="background:#D6E0F0"><td>Active</td><td style="text-align:center">${active}</td></tr>
        <tr style="background:#D5F5E3"><td>Disbursed</td><td style="text-align:center;color:#27AE60;font-weight:bold">${disbursed}</td></tr>
        <tr style="background:#FADBD8"><td>Stalled</td><td style="text-align:center;color:#C0392B;font-weight:bold">${stalled}</td></tr>
        <tr><td>Rejected</td><td style="text-align:center">${rejected}</td></tr>
        <tr style="background:#FBF3E0"><td>Deferred</td><td style="text-align:center">${deferred}</td></tr>
      </table>

      <h3 style="font-family:Arial,sans-serif;color:#1B3A6B;margin-top:20px">By Product</h3>
      <table border="1" cellpadding="5" cellspacing="0"
        style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:12px">
        <tr style="background:#1B3A6B;color:#fff">
          <th>Product</th><th>Total</th><th>Active</th><th>Disbursed</th><th>Stalled</th></tr>
        ${productRows}
      </table>

      <h3 style="font-family:Arial,sans-serif;color:#1B3A6B;margin-top:20px">Active & Stalled Cases</h3>
      <table border="1" cellpadding="5" cellspacing="0"
        style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:12px">
        <tr style="background:#1B3A6B;color:#fff">
          <th>Case ID</th><th>Product</th><th>Client</th><th>Branch</th>
          <th>TAT (hrs)</th><th>Stage</th><th>Status</th></tr>
        ${caseRows}
      </table>

      <p style="color:#888;font-size:11px;font-family:Arial,sans-serif;margin-top:20px">
        Automated weekly report — JBL HOCC TAT Tracker v5.3</p>`
  });
  Logger.log(`Weekly report sent to ${CONFIG.EMAILS.MD}`);
}


// ════════════════════════════════════════════════════════════════════════════
//  9. HIDE MANAGEMENT SHEETS
// ════════════════════════════════════════════════════════════════════════════
function hideManagementSheets_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  HIDDEN_SUPPORT_SHEETS_().forEach(name => {
    const sheet = ss.getSheetByName(name);
    if (sheet) sheet.hideSheet();
  });
}


// ════════════════════════════════════════════════════════════════════════════
//  10. CUSTOM MENU
// ════════════════════════════════════════════════════════════════════════════
function onOpen() {
  const access = getTatToolsMenuAccess_();
  if (!access.allowed) {
    if (access.managementViewer) {
      SpreadsheetApp.getUi().createMenu("JBL TAT Views")
        .addItem("Show Dashboard", "menuShowDashboard")
        .addItem("Show Performance Sheet", "menuShowPerformance")
        .addToUi();
    } else {
      try {
        hideManagementSheets_();
      } catch (e) {
        Logger.log(`Unable to hide management sheets on open: ${e.message}`);
      }
    }
    return;
  }

  const ui = SpreadsheetApp.getUi();
  const adminMenu = ui.createMenu("Admin & Setup")
    .addItem("Setup Mobile Web App Support", "setupWebAppSupport")
    .addItem("Setup / Refresh STAFF Sheet",  "setupStaffSheet")
    .addItem("Validate STAFF Sheet",         "validateStaffSheetSetup")
    .addItem("Run Mobile Web App Diagnostics", "runWebAppDiagnostics")
    .addSeparator()
    .addItem("Re-apply All Protections",   "applyAllProtections")
    .addItem("Re-apply Timestamp Formats", "applyAllTimestampFormats")
    .addItem("Re-apply Data Validations",  "applyAllDataValidations")
    .addItem("Refresh Case Index",         "menuRefreshCaseIndex")
    .addItem("Generate Audit Anomaly Report", "menuGenerateAuditAnomalyReport")
    .addItem("Extend Tracker Rows to 2,000", "menuExtendTrackerRowsTo2000")
    .addItem("Extend Tracker Rows to 5,000", "menuExtendTrackerRowsTo5000")
    .addItem("Unlock Cell Locks (corrections)", "unlockCellLocks")
    .addItem("IT Correct Selected Cell",   "menuItCorrectSelectedCell")
    .addItem("Unlock ALL Tracker Protections", "menuUnlockAll")
    .addSeparator()
    .addItem("Show Protection Summary",    "menuShowProtectionSummary");

  if (access.owner) {
    adminMenu
      .addSeparator()
      .addItem("Re-install All Triggers", "setupAllTriggers");
  }

  adminMenu
    .addSeparator()
    .addItem("Show Audit Log", "menuShowAuditLog")
    .addItem("Show STAFF Sheet", "menuShowStaffSheet")
    .addItem("Show Dashboard", "menuShowDashboard")
    .addItem("Show Performance Sheet", "menuShowPerformance");

  ui.createMenu("JBL TAT Tools")

    .addSubMenu(ui.createMenu("Case Tools")
      .addItem("Find Case by ID",            "menuFindCase")
      .addItem("Mark Selected Row — Stalled","menuMarkStalled")
      .addItem("Mark Selected Row — Rejected","menuMarkRejected")
      .addItem("Mark Selected Row — Deferred","menuMarkDeferred")
      .addSeparator()
      .addItem("Show Case Summary (selected row)", "menuShowCaseSummary")
    )

    .addSubMenu(ui.createMenu("Reports")
      .addItem("Send Weekly Report Now",     "sendWeeklyReport")
      .addItem("Send Overdue Alert Now",     "menuSendOverdueAlert")
      .addSeparator()
      .addItem("Export Active / Stalled Cases", "exportActiveCases")
      .addItem("Export ALL Cases",           "menuExportAllCases")
    )

    .addSubMenu(ui.createMenu("Daily Automation")
      .addItem("Run All Daily Checks",       "dailyMorningRun")
      .addItem("Flag Overdue Cases Only",    "menuFlagOverdue")
      .addItem("Lock Completed Stages Only", "menuLockStages")
    )

    .addSubMenu(adminMenu)

    .addToUi();
}


// ════════════════════════════════════════════════════════════════════════════
//  MENU ACTIONS
// ════════════════════════════════════════════════════════════════════════════
function menuFindCase() {
  const ui    = SpreadsheetApp.getUi();
  const resp  = ui.prompt("Find Case", "Enter Case ID (e.g. JBL-LB-2025-001):", ui.ButtonSet.OK_CANCEL);
  if (resp.getSelectedButton() !== ui.Button.OK) return;
  const query = resp.getResponseText().trim().toUpperCase();

  for (const sheetName of TRACKER_SHEETS) {
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(sheetName);
    if (!sheet) continue;
    const data  = sheet.getRange("A:A").getValues();
    for (let i = CONFIG.DATA_START_ROW - 1; i < data.length; i++) {
      if (String(data[i][0]).toUpperCase() === query) {
        const row = i + 1;
        sheet.activate();
        sheet.setActiveRange(sheet.getRange(row, 1));
        SpreadsheetApp.getActiveSpreadsheet().toast(
          `Found: ${query} at row ${row} in ${sheetName}`, "Case Found", 5);
        return;
      }
    }
  }
  ui.alert("Not Found", `No case matching "${query}" was found.`, ui.ButtonSet.OK);
}

function menuMarkStalled()  { menuSetStatus_("Stalled"); }
function menuMarkRejected() { menuSetStatus_("Rejected"); }
function menuMarkDeferred() { menuSetStatus_("Deferred"); }

function menuSetStatus_(newStatus) {
  const ui    = SpreadsheetApp.getUi();
  const sheet = SpreadsheetApp.getActiveSheet();
  const sheetName = sheet.getName();

  if (!TRACKER_SHEETS.includes(sheetName)) {
    ui.alert("Please select a row in a TRACKER sheet."); return;
  }

  const pConfig = PRODUCTS[sheetName];
  const C       = pConfig.COL;
  const row     = sheet.getActiveRange().getRow();

  if (row < CONFIG.DATA_START_ROW) {
    ui.alert("Select a data row (row 5 or below) first."); return;
  }

  const caseId = sheet.getRange(row, C.CASE_ID).getValue();
  const prefix = CONFIG.CASE_ID_PREFIX[sheetName];
  if (!String(caseId).startsWith(prefix)) {
    ui.alert("The selected row does not appear to contain a case."); return;
  }

  const oldStatus = String(sheet.getRange(row, C.STATUS).getValue() || "").trim();
  if (oldStatus === newStatus) {
    ui.alert("No Change", `Case ${caseId} is already marked ${newStatus}.`, ui.ButtonSet.OK);
    return;
  }

  const conf = ui.alert(
    `Mark as ${newStatus}?`,
    `Case: ${caseId}\nRow: ${row}\nCurrent status: ${oldStatus || "(blank)"}\nNew status: ${newStatus}\n\n` +
    "This updates only the Status and Remarks fields for the selected case. Continue?",
    ui.ButtonSet.YES_NO
  );
  if (conf !== ui.Button.YES) return;

  const now = new Date();
  sheet.getRange(row, C.STATUS).setValue(newStatus);
  const rem = sheet.getRange(row, C.REMARKS).getValue();
  sheet.getRange(row, C.REMARKS).setValue(
    `[${formatDate_(now)}: Manually marked ${newStatus} from ${oldStatus || "blank"}] ${rem}`
  );
  updateCaseIndex_(sheetName, row, pConfig);
  writeAuditLog_(sheetName, caseId, row, "Manual Status Change", `${oldStatus || "blank"} -> ${newStatus}`, "MENU_STATUS");
  SpreadsheetApp.getActiveSpreadsheet().toast(`Row ${row} marked as ${newStatus}.`, "Done", 4);
}

function menuItCorrectSelectedCell() {
  const ui = SpreadsheetApp.getUi();
  try {
    requireItUser_();
  } catch (e) {
    ui.alert("IT Correction", e.message, ui.ButtonSet.OK);
    return;
  }

  const sheet = SpreadsheetApp.getActiveSheet();
  const sheetName = sheet.getName();
  if (!TRACKER_SHEETS.includes(sheetName)) {
    ui.alert("Select a cell in a TRACKER sheet first.");
    return;
  }

  const range = sheet.getActiveRange();
  if (!range || range.getNumRows() !== 1 || range.getNumColumns() !== 1) {
    ui.alert("Select exactly one cell to correct.");
    return;
  }

  const pConfig = PRODUCTS[sheetName];
  const C = pConfig.COL;
  const row = range.getRow();
  const col = range.getColumn();
  if (row < CONFIG.DATA_START_ROW || col < 1 || col > C.REMARKS) {
    ui.alert("Select a data cell in the workflow area.");
    return;
  }

  const caseId = sheet.getRange(row, C.CASE_ID).getValue();
  if (!caseId) {
    ui.alert("Selected row does not have a Case ID.");
    return;
  }

  const reasonResponse = ui.prompt(
    "IT Correction Reason",
    `Case: ${caseId}\nField: ${pConfig.STAGE_NAMES[col] || sheet.getRange(WEB_APP_CONFIG.HEADER_ROW, col).getValue()}\n\nEnter the correction reason:`,
    ui.ButtonSet.OK_CANCEL
  );
  if (reasonResponse.getSelectedButton() !== ui.Button.OK) return;
  const reason = reasonResponse.getResponseText().trim();
  if (!reason) {
    ui.alert("A reason is required.");
    return;
  }

  const valueResponse = ui.prompt(
    "IT Correction New Value",
    "Enter the replacement value. For timestamps, use a Google Sheets-recognized date/time.",
    ui.ButtonSet.OK_CANCEL
  );
  if (valueResponse.getSelectedButton() !== ui.Button.OK) return;

  const oldValue = range.getValue();
  const newValue = valueResponse.getResponseText();
  range.setValue(newValue);
  if (pConfig.TS_SEQUENCE.some(stage => stage[0] === col)) range.setNumberFormat(CONFIG.DATE_TIME_FORMAT);

  logCorrection_(sheetName, row, col, pConfig, oldValue, newValue, reason);
  updateCaseIndex_(sheetName, row, pConfig);
  SpreadsheetApp.getActiveSpreadsheet().toast("Correction logged.", "IT Correction", 5);
}

function logCorrection_(sheetName, row, col, pConfig, oldValue, newValue, reason) {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(sheetName);
  const C = pConfig.COL;
  const caseId = sheet.getRange(row, C.CASE_ID).getValue();
  const field = pConfig.STAGE_NAMES[col] || sheet.getRange(WEB_APP_CONFIG.HEADER_ROW, col).getValue() || `Col ${col}`;
  const log = ensureCorrectionLogSheet_();
  log.appendRow([
    new Date(),
    Session.getActiveUser().getEmail() || "unknown",
    sheetName,
    caseId,
    row,
    col,
    field,
    oldValue instanceof Date ? formatDate_(oldValue) : oldValue,
    newValue instanceof Date ? formatDate_(newValue) : newValue,
    reason,
  ]);
  writeAuditLog_(sheetName, caseId, row, `IT Correction: ${field}`, `${oldValue} -> ${newValue}`, "IT_CORRECTION");
}

function menuShowCaseSummary() {
  const ui    = SpreadsheetApp.getUi();
  const sheet = SpreadsheetApp.getActiveSheet();
  const sheetName = sheet.getName();

  if (!TRACKER_SHEETS.includes(sheetName)) {
    ui.alert("Please select a row in a TRACKER sheet."); return;
  }

  const pConfig = PRODUCTS[sheetName];
  const C       = pConfig.COL;
  const row     = sheet.getActiveRange().getRow();

  if (row < CONFIG.DATA_START_ROW) { ui.alert("Select a data row first."); return; }

  const caseId  = sheet.getRange(row, C.CASE_ID).getValue();
  const prefix  = CONFIG.CASE_ID_PREFIX[sheetName];
  if (!String(caseId).startsWith(prefix)) {
    ui.alert("The selected row does not appear to contain a case."); return;
  }

  const summary = buildSummary_(sheet, row, pConfig, sheetName.replace("TRACKER-", ""));
  ui.alert(
    `Case Summary: ${caseId}`,
    `Client: ${summary.client}\nBranch: ${summary.branch}\n` +
    `Product: ${summary.product}\nStatus: ${summary.status}\n` +
    `TAT: ${summary.hrs ? summary.hrs + " hours" : "N/A"}\n` +
    `Current Stage: ${summary.stage}`,
    ui.ButtonSet.OK
  );
}

function menuSendOverdueAlert() {
  sendOverdueAlert_();
  SpreadsheetApp.getActiveSpreadsheet().toast("Overdue alert sent.", "Done", 4);
}

function menuFlagOverdue() {
  TRACKER_SHEETS.forEach(sheetName => flagOverdueCases_(sheetName));
  SpreadsheetApp.getActiveSpreadsheet().toast("Overdue cases flagged on all sheets.", "Done", 4);
}

function menuLockStages() {
  TRACKER_SHEETS.forEach(sheetName => lockCompletedStages_(sheetName));
  SpreadsheetApp.getActiveSpreadsheet().toast("Completed stages locked on all sheets.", "Done", 4);
}

function menuUnlockAll() {
  requireOwnerOrItUser_();

  const ui = SpreadsheetApp.getUi();
  const conf = ui.alert(
    "Unlock ALL Tracker Protections?",
    "This will remove all JBL-* protections on all TRACKER sheets.\n" +
    "You can re-apply them via 'Re-apply All Protections'.\n\nContinue?",
    ui.ButtonSet.YES_NO
  );
  if (conf !== ui.Button.YES) return;

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  TRACKER_SHEETS.forEach(sheetName => {
    const sheet = ss.getSheetByName(sheetName);
    if (!sheet) return;
    sheet.getProtections(SpreadsheetApp.ProtectionType.RANGE)
      .filter(p => p.getDescription().startsWith("JBL-"))
      .forEach(p => p.remove());
  });
  SpreadsheetApp.getActiveSpreadsheet().toast("All JBL protections removed.", "Done", 4);
}

function menuRefreshCaseIndex() {
  requireOwnerOrItUser_();

  refreshCaseIndex();
}

function menuGenerateAuditAnomalyReport() {
  requireOwnerOrItUser_();

  generateAuditAnomalyReport();
}

function menuExtendTrackerRowsTo2000() {
  requireOwnerOrItUser_();

  extendTrackerRowsTo2000();
}

function menuExtendTrackerRowsTo5000() {
  requireOwnerOrItUser_();

  extendTrackerRowsTo5000();
}

function unlockCellLocks() {
  requireOwnerOrItUser_();

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  TRACKER_SHEETS.forEach(sheetName => {
    const sheet = ss.getSheetByName(sheetName);
    if (!sheet) return;
    sheet.getProtections(SpreadsheetApp.ProtectionType.RANGE)
      .filter(p => p.getDescription().startsWith("JBL-LOCK"))
      .forEach(p => p.remove());
  });
  SpreadsheetApp.getActiveSpreadsheet().toast("Cell-level locks removed. Data can be corrected.", "Done", 4);
}

function menuShowProtectionSummary() {
  requireOwnerOrItUser_();

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let summary = [];
  TRACKER_SHEETS.forEach(sheetName => {
    const sheet = ss.getSheetByName(sheetName);
    if (!sheet) return;
    const prots = sheet.getProtections(SpreadsheetApp.ProtectionType.RANGE)
      .filter(p => p.getDescription().startsWith("JBL-"));
    summary.push(`${sheetName}: ${prots.length} protections`);
  });
  HIDDEN_SUPPORT_SHEETS_().forEach(sheetName => {
    const sheet = ss.getSheetByName(sheetName);
    if (!sheet) return;
    const prots = sheet.getProtections(SpreadsheetApp.ProtectionType.SHEET)
      .filter(p => p.getDescription().startsWith("JBL-SHEET-"));
    summary.push(`${sheetName}: ${prots.length} whole-sheet protections`);
  });
  SpreadsheetApp.getUi().alert("Protection Summary", summary.join("\n"), SpreadsheetApp.getUi().ButtonSet.OK);
}

function menuShowAuditLog() {
  requireOwnerOrItUser_();

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName("AUDIT LOG");
  if (sheet) {
    sheet.showSheet();
    sheet.activate();
  } else {
    SpreadsheetApp.getUi().alert("AUDIT LOG sheet not found.");
  }
}

function menuShowStaffSheet() {
  requireOwnerOrItUser_();

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(WEB_APP_CONFIG.STAFF_SHEET_NAME);
  if (sheet) {
    sheet.showSheet();
    sheet.activate();
  } else {
    SpreadsheetApp.getUi().alert("STAFF sheet not found.");
  }
}

function menuShowDashboard() {
  requireManagementViewerUser_();

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName("DASHBOARD");
  if (sheet) {
    sheet.showSheet();
    sheet.activate();
  } else {
    SpreadsheetApp.getUi().alert("DASHBOARD sheet not found.");
  }
}

function menuShowPerformance() {
  requireManagementViewerUser_();

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName("PERFORMANCE");
  if (sheet) {
    sheet.showSheet();
    sheet.activate();
  } else {
    SpreadsheetApp.getUi().alert("PERFORMANCE sheet not found.");
  }
}

function menuExportAllCases() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  SpreadsheetApp.getUi().alert(
    "Export All Cases",
    "This feature exports all cases to a new sheet for download.\n" +
    "Implementation: create a new sheet, copy all case data, and provide download link.",
    SpreadsheetApp.getUi().ButtonSet.OK
  );
}

function exportActiveCases() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  SpreadsheetApp.getUi().alert(
    "Export Active/Stalled Cases",
    "This feature exports active and stalled cases to a new sheet for download.\n" +
    "Implementation: filter cases and create export sheet.",
    SpreadsheetApp.getUi().ButtonSet.OK
  );
}


// ════════════════════════════════════════════════════════════════════════════
//  HELPER FUNCTIONS
// ════════════════════════════════════════════════════════════════════════════
// =============================================================================
//  MOBILE WEB APP
// =============================================================================
function doGet() {
  return HtmlService
    .createHtmlOutputFromFile("WebApp")
    .setTitle("JBL TAT Mobile")
    .addMetaTag("viewport", "width=device-width, initial-scale=1");
}

function webGetBootstrap() {
  const user = webCurrentUser_();
  const webAppUrl = getWebAppUrl_();

  if (!user.authorized) {
    return {
      ...user,
      webAppUrl
    };
  }

  const homeData = webBuildHomeData_(user);

  const products = WEB_APP_CONFIG.PRODUCTS
    .filter(product => webCanAccessSheet_(user, product.sheetName))
    .map(product => {
      const pConfig = PRODUCTS[product.sheetName];
      const maximumAmount = configuredMaximumAmount_(pConfig);

      return {
        sheetName: product.sheetName,
        label: product.label,
        minAmount: configuredMinimumAmount_(pConfig),
        maxAmount: Number.isFinite(maximumAmount)
          ? maximumAmount
          : null
      };
    });

  return {
    authorized: true,
    user: webPublicUser_(user),
    webAppUrl,
    products,
    recent: homeData.recent,
    actionRequired: homeData.actionRequired,
    branches: WEB_APP_CONFIG.BRANCHES,
    minAmount: CONFIG.MIN_AMOUNT
  };
}

function webGetHomeData() {
  const user = webRequireUser_();
  return webBuildHomeData_(user);
}

function getWebAppUrl_() {
  try {
    return ScriptApp.getService().getUrl() || "";
  } catch (e) {
    return "";
  }
}

function webSearchCases(query) {
  const user = webRequireUser_();
  const q = String(query || "").trim().toLowerCase();
  if (q.length < 2) return [];

  const results = [];
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const index = ss.getSheetByName(WEB_APP_CONFIG.CASE_INDEX_SHEET_NAME);
  if (index && index.getLastRow() >= 2) {
    const rows = index.getRange(2, 1, index.getLastRow() - 1, 9).getValues();

    // Group matched rows by sheet first to allow a single bulk read per sheet.
    const matchesBySheet = {};
    for (const indexRow of rows) {
      const caseId     = String(indexRow[0] || "");
      const sheetName  = String(indexRow[1] || "");
      const row        = Number(indexRow[2]);
      const client     = String(indexRow[3] || "");
      if (!caseId || !TRACKER_SHEETS.includes(sheetName) || !webCanAccessSheet_(user, sheetName)) continue;
      if (!caseId.toLowerCase().includes(q) && !client.toLowerCase().includes(q)) continue;
      const pConfig = PRODUCTS[sheetName];
      if (!pConfig || row < CONFIG.DATA_START_ROW) continue;
      if (!matchesBySheet[sheetName]) matchesBySheet[sheetName] = [];
      matchesBySheet[sheetName].push(row);
    }

    // One bulk read per matched sheet instead of one read per matched row.
    for (const [sheetName, matchedRows] of Object.entries(matchesBySheet)) {
      const sheet   = ss.getSheetByName(sheetName);
      const pConfig = PRODUCTS[sheetName];
      if (!sheet) continue;
      const sortedRows = matchedRows.slice().sort((a, b) => a - b);
      const minRow = sortedRows[0];
      const maxRow = sortedRows[sortedRows.length - 1];
      const bulk = sheet.getRange(minRow, 1, maxRow - minRow + 1, pConfig.COL.REMARKS).getValues();
      for (const row of sortedRows) {
        const values = bulk[row - minRow];
        results.push(webBuildCaseSummaryFromValues_(sheetName, row, pConfig, values));
        if (results.length >= WEB_APP_CONFIG.SEARCH_LIMIT) return results;
      }
    }
    if (results.length) return results;
  }

  for (const sheetName of TRACKER_SHEETS) {
    if (!webCanAccessSheet_(user, sheetName)) continue;

    const sheet = ss.getSheetByName(sheetName);
    if (!sheet) continue;

    const pConfig = PRODUCTS[sheetName];
    const C = pConfig.COL;
    const lastRow = getLastDataRow_(sheet, pConfig);
    if (lastRow < CONFIG.DATA_START_ROW) continue;

    const values = sheet.getRange(CONFIG.DATA_START_ROW, 1, lastRow - CONFIG.DATA_START_ROW + 1, C.REMARKS).getValues();
    for (let i = 0; i < values.length; i++) {
      const row = CONFIG.DATA_START_ROW + i;
      const rowValues = values[i];
      const caseId = String(rowValues[C.CASE_ID - 1] || "");
      if (!caseId) continue;

      const client = String(rowValues[C.CLIENT_NAME - 1] || "");
      if (!caseId.toLowerCase().includes(q) && !client.toLowerCase().includes(q)) continue;

      results.push(webBuildCaseSummaryFromValues_(sheetName, row, pConfig, rowValues));
      if (results.length >= WEB_APP_CONFIG.SEARCH_LIMIT) return results;
    }
  }
  return results;
}

function webGetCaseDetail(payload) {
  const user = webRequireUser_();
  const loc = webResolveCaseLocation_(payload);
  if (!webCanAccessSheet_(user, loc.sheetName)) throw new Error("You do not have access to this product sheet.");
  return webBuildCaseDetail_(user, loc.sheet, loc.row, loc.pConfig, loc.sheetName);
}

function webCreateCase(payload) {
  const user = webRequireUser_();

  const sheetName = String(
    payload && payload.sheetName || ""
  ).trim();

  if (!TRACKER_SHEETS.includes(sheetName)) {
    throw new Error("Invalid product sheet.");
  }

  if (!webCanAccessSheet_(user, sheetName)) {
    throw new Error(
      "You do not have access to this product sheet."
    );
  }

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(sheetName);
  const pConfig = PRODUCTS[sheetName];

  if (!sheet || !pConfig) {
    throw new Error(
      `The tracker configuration for ${sheetName} was not found.`
    );
  }

  const C = pConfig.COL;

  [
    C.CLIENT_NAME,
    C.BRANCH,
    C.LO_NAME,
    C.AMOUNT
  ].forEach(col => {
    if (!webCanEditColumn_(user, sheetName, col)) {
      throw new Error(
        "Your role cannot create cases for this product."
      );
    }
  });

  payload = payload || {};

  const clientName = String(
    payload.clientName || ""
  ).trim();

  const branch = String(
    payload.branch || ""
  ).trim();

  const loName = String(
    payload.loName || user.name || ""
  ).trim();

  const amount = Number(payload.amount);

  if (!clientName) {
    throw new Error("Client name is required.");
  }

  if (!WEB_APP_CONFIG.BRANCHES.includes(branch)) {
    throw new Error("Select a valid branch.");
  }

  if (!loName) {
    throw new Error("BRO name is required.");
  }

  const amountError = amountValidationError_(amount, pConfig, sheetName);
  if (amountError) throw new Error(amountError);

  const lock = LockService.getDocumentLock();
  lock.waitLock(WEB_APP_CONFIG.LOCK_WAIT_MS);

  try {
    const row = webNextDataRow_(sheet, pConfig);
    const caseId = generateCaseId_(sheet, sheetName);
    const now = new Date();

    // Batch all 7 field writes into a single setValues() call (1 API call vs 7).
    const rowData = Array(C.REMARKS).fill("");
    rowData[C.CASE_ID     - 1] = caseId;
    rowData[C.CLIENT_NAME - 1] = clientName;
    rowData[C.BRANCH      - 1] = branch;
    rowData[C.LO_NAME     - 1] = loName;
    rowData[C.AMOUNT      - 1] = amount;
    rowData[C.TS_CREATED  - 1] = now;
    rowData[C.STATUS      - 1] = "Active";
    sheet.getRange(row, 1, 1, C.REMARKS).setValues([rowData]);
    // Apply date formatting separately (cannot be included in setValues).
    sheet.getRange(row, C.TS_CREATED).setNumberFormat(CONFIG.DATE_TIME_FORMAT);

    SpreadsheetApp.flush();

    writeAuditLog_(
      sheetName,
      caseId,
      row,
      "Case Created",
      now,
      WEB_APP_CONFIG.AUDIT_SOURCE
    );

    updateCaseIndex_(
      sheetName,
      row,
      pConfig
    );

    return webBuildCaseDetail_(
      user,
      sheet,
      row,
      pConfig,
      sheetName
    );

  } finally {
    lock.releaseLock();
  }
}

function webSubmitCaseUpdate(payload) {
  const user = webRequireUser_();
  const loc = webResolveCaseLocation_(payload);
  if (!webCanAccessSheet_(user, loc.sheetName)) throw new Error("You do not have access to this product sheet.");

  const changes = Array.isArray(payload && payload.changes) ? payload.changes : [];
  if (!changes.length) throw new Error("No changes were submitted.");

  const lock = LockService.getDocumentLock();
  lock.waitLock(WEB_APP_CONFIG.LOCK_WAIT_MS);
  try {
    changes.forEach(change => webApplyCaseChange_(user, loc.sheet, loc.row, loc.pConfig, loc.sheetName, change));
    updateCaseIndex_(loc.sheetName, loc.row, loc.pConfig);
    return webBuildCaseDetail_(user, loc.sheet, loc.row, loc.pConfig, loc.sheetName);
  } finally {
    lock.releaseLock();
  }
}

function getRoleAssignments_() {
  const staffAssignments = webListActiveStaffRoleInfos_();
  if (staffAssignments.length || !WEB_APP_CONFIG.USE_ROLE_MAP_FALLBACK) return staffAssignments;
  return Object.entries(ROLE_MAP);
}

function webListActiveStaffRoleInfos_() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(WEB_APP_CONFIG.STAFF_SHEET_NAME);
  if (!sheet) return [];

  const lastRow = sheet.getLastRow();
  const lastCol = sheet.getLastColumn();
  if (lastRow < 2 || lastCol < 1) return [];

  const values = sheet.getRange(1, 1, lastRow, lastCol).getValues();
  const header = webHeaderMap_(values[0]);
  const emailIdx = header.email;
  const roleIdx = header.role;
  const activeIdx = header.active;
  if (emailIdx === undefined || roleIdx === undefined || activeIdx === undefined) return [];

  const sheetsIdx = header.sheets;
  return values.slice(1).reduce((assignments, row) => {
    const email = String(row[emailIdx] || "").trim().toLowerCase();
    const active = String(row[activeIdx] || "").trim().toLowerCase();
    if (!email || !["yes", "y", "true", "active"].includes(active)) return assignments;

    const roles = webParseRoles_(row[roleIdx]);
    const roleInfo = webMergeRoleTemplates_(roles);
    if (!roleInfo) return assignments;

    assignments.push([email, {
      sheets: sheetsIdx === undefined ? "*" : webParseSheets_(row[sheetsIdx]),
      cols_logbook: roleInfo.cols_logbook,
      cols_other: roleInfo.cols_other,
      cols_business: roleInfo.cols_business,
    }]);
    return assignments;
  }, []);
}

function webCurrentUser_() {
  const email = String(Session.getActiveUser().getEmail() || "").trim().toLowerCase();
  if (!email) {
    return {
      authorized: false,
      reason: "No Google account email was available. Deploy as 'user accessing the web app' and have staff authorize once.",
    };
  }

  const staffUser = webFindStaffUser_(email);
  if (staffUser) return staffUser;

  const roleInfo = WEB_APP_CONFIG.USE_ROLE_MAP_FALLBACK ? ROLE_MAP[email] : null;
  if (!roleInfo) {
    return { authorized: false, email, reason: "Access is not configured for this Google account." };
  }

  return {
    authorized: true,
    source: "ROLE_MAP",
    email,
    name: email,
    role: "ROLE_MAP",
    branch: "",
    sheets: roleInfo.sheets,
    cols_logbook: roleInfo.cols_logbook || [],
    cols_other: roleInfo.cols_other || [],
    cols_business: roleInfo.cols_business || [],
  };
}

function webRequireUser_() {
  const user = webCurrentUser_();
  if (!user.authorized) throw new Error(user.reason || "Unauthorized.");
  return user;
}

function getActiveEditorEmail_() {
  return String(Session.getActiveUser().getEmail() || "").trim().toLowerCase();
}

function normalizeEmailList_(emails) {
  return Array.from(new Set((emails || [])
    .map(email => String(email || "").trim().toLowerCase())
    .filter(Boolean)));
}

function getSpreadsheetOwnerEmail_() {
  return String(SpreadsheetApp.getActiveSpreadsheet().getOwner().getEmail() || "").trim().toLowerCase();
}

function isOwnerEmail_(email) {
  const ownerEmail = getSpreadsheetOwnerEmail_();
  return Boolean(email && ownerEmail && email === ownerEmail);
}

function isItEmail_(email) {
  if (!email) return false;
  const staffUser = webFindStaffUser_(email);
  if (!staffUser || !staffUser.authorized) return false;
  const roles = staffUser.roles || String(staffUser.role || "").split(",");
  return roles.includes("IT");
}

function isManagementViewerEmail_(email) {
  const normalized = String(email || "").trim().toLowerCase();
  return Boolean(normalized && getManagementViewerEmails_().includes(normalized));
}

function getOwnerItEmails_() {
  const emails = [getSpreadsheetOwnerEmail_()];
  getActiveStaffUsersByRole_("IT").forEach(user => emails.push(user.email));
  return normalizeEmailList_(emails);
}

function getManagementViewerEmails_() {
  const emails = getOwnerItEmails_()
    .concat(getActiveStaffUsersByRole_("MANAGEMENT").map(user => user.email))
    .concat(CONFIG.MANAGEMENT_VIEWER_EMAILS || [])
    .concat(Object.values(CONFIG.EMAILS || {}));
  return normalizeEmailList_(emails);
}

function getActiveWorkflowStaffEmails_() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(WEB_APP_CONFIG.STAFF_SHEET_NAME);
  if (!sheet) return [];

  const lastRow = sheet.getLastRow();
  const lastCol = sheet.getLastColumn();
  if (lastRow < 2 || lastCol < 1) return [];

  const values = sheet.getRange(1, 1, lastRow, lastCol).getValues();
  const header = webHeaderMap_(values[0]);
  const emailIdx = header.email;
  const roleIdx = header.role;
  const activeIdx = header.active;
  if (emailIdx === undefined || roleIdx === undefined || activeIdx === undefined) return [];

  return normalizeEmailList_(values.slice(1).reduce((emails, row) => {
    const email = String(row[emailIdx] || "").trim().toLowerCase();
    const active = String(row[activeIdx] || "").trim().toLowerCase();
    if (!email || !["yes", "y", "true", "active"].includes(active)) return emails;

    const roles = webParseRoles_(row[roleIdx]);
    if (roles.some(role => role !== "MANAGEMENT")) emails.push(email);
    return emails;
  }, []));
}

function getActiveStaffUsersByRole_(role) {
  const targetRole = webNormalizeRole_(role);
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(WEB_APP_CONFIG.STAFF_SHEET_NAME);
  if (!sheet) return [];

  const lastRow = sheet.getLastRow();
  const lastCol = sheet.getLastColumn();
  if (lastRow < 2 || lastCol < 1) return [];

  const values = sheet.getRange(1, 1, lastRow, lastCol).getValues();
  const header = webHeaderMap_(values[0]);
  const emailIdx = header.email;
  const roleIdx = header.role;
  const activeIdx = header.active;
  const nameIdx = header.name;
  if (emailIdx === undefined || roleIdx === undefined || activeIdx === undefined) return [];

  const users = [];
  const seen = new Set();
  values.slice(1).forEach(row => {
    const email = String(row[emailIdx] || "").trim().toLowerCase();
    const active = String(row[activeIdx] || "").trim().toLowerCase();
    if (!email || seen.has(email) || !["yes", "y", "true", "active"].includes(active)) return;
    const roles = webParseRoles_(row[roleIdx]);
    if (!roles.includes(targetRole)) return;
    seen.add(email);
    users.push({
      email,
      name: nameIdx === undefined ? email : String(row[nameIdx] || email).trim(),
      roles,
    });
  });
  return users;
}

function getTatToolsMenuAccess_() {
  const email = getActiveEditorEmail_();
  const owner = isOwnerEmail_(email);
  const it = isItEmail_(email);
  const managementViewer = isManagementViewerEmail_(email);
  return { allowed: owner || it, owner, it, managementViewer, email };
}

function requireOwnerOrItUser_() {
  const email = getActiveEditorEmail_();
  if (isOwnerEmail_(email) || isItEmail_(email)) return;
  throw new Error("Only the spreadsheet owner or an active IT role can run this tool.");
}

function requireOwnerUser_() {
  const email = getActiveEditorEmail_();
  if (isOwnerEmail_(email)) return;
  throw new Error("Only the spreadsheet owner can run this tool.");
}

function requireItUser_() {
  const user = webRequireUser_();
  const roles = user.roles || String(user.role || "").split(",");
  if (!roles.includes("IT")) throw new Error("Only IT users can perform this action.");
  return user;
}

function requireManagementViewerUser_() {
  const email = getActiveEditorEmail_();
  if (isManagementViewerEmail_(email)) return;
  throw new Error("Only owner, IT, or configured management viewers can open this sheet.");
}

function webFindStaffUser_(email) {
  const cache = CacheService.getScriptCache();
  const cacheKey = "staff_user_" + email.replace(/[^a-zA-Z0-9]/g, "_");
  try {
    const cached = cache.get(cacheKey);
    if (cached) {
      const parsed = JSON.parse(cached);
      return parsed;
    }
  } catch (err) {
    Logger.log("Failed to read script cache: " + err.message);
  }

  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(WEB_APP_CONFIG.STAFF_SHEET_NAME);
  if (!sheet) return null;

  const lastRow = sheet.getLastRow();
  const lastCol = sheet.getLastColumn();
  if (lastRow < 2 || lastCol < 1) return null;

  const values = sheet.getRange(1, 1, lastRow, lastCol).getValues();
  const header = webHeaderMap_(values[0]);
  const emailIdx = header.email;
  const roleIdx = header.role;
  const activeIdx = header.active;
  if (emailIdx === undefined || roleIdx === undefined || activeIdx === undefined) return null;

  let result = null;
  let foundInactive = false;
  for (let i = 1; i < values.length; i++) {
    const row = values[i];
    const rowEmail = String(row[emailIdx] || "").trim().toLowerCase();
    if (rowEmail !== email) continue;

    const active = String(row[activeIdx] || "").trim().toLowerCase();
    if (!["yes", "y", "true", "active"].includes(active)) {
      foundInactive = true;
      continue;
    }

    const roles = webParseRoles_(row[roleIdx]);
    const roleInfo = webMergeRoleTemplates_(roles);
    if (!roleInfo) {
      result = { authorized: false, email, reason: `Unknown STAFF role: ${roles.join(", ")}` };
      break;
    }

    const sheetsIdx = header.sheets;
    const nameIdx = header.name;
    const branchIdx = header.branch;
    result = {
      authorized: true,
      source: "STAFF",
      email,
      name: nameIdx === undefined ? email : String(row[nameIdx] || email).trim(),
      role: roles.join(","),
      roles,
      branch: branchIdx === undefined ? "" : String(row[branchIdx] || "").trim(),
      sheets: sheetsIdx === undefined ? "*" : webParseSheets_(row[sheetsIdx]),
      cols_logbook: roleInfo.cols_logbook,
      cols_other: roleInfo.cols_other,
      cols_business: roleInfo.cols_business,
    };
    break;
  }
  if (!result && foundInactive) {
    result = { authorized: false, email, reason: "Your staff account is inactive." };
  }

  try {
    cache.put(cacheKey, JSON.stringify(result), 600);
  } catch (err) {
    Logger.log("Failed to write script cache: " + err.message);
  }

  return result;
}

function webHeaderMap_(headers) {
  const map = {};
  headers.forEach((h, i) => {
    const key = String(h || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
    if (key) map[key] = i;
  });
  return map;
}

function webNormalizeRole_(role) {
  const normalized = String(role || "").trim().toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_|_$/g, "");
  return normalized === "LO" || normalized === "LO_BRO" ? "BRO" : normalized;
}

function webParseRoles_(value) {
  return String(value || "")
    .split(",")
    .map(webNormalizeRole_)
    .filter(Boolean);
}

function webMergeRoleTemplates_(roles) {
  if (!roles.length) return null;

  const colsLogbook = new Set();
  const colsOther = new Set();
  const colsSme = new Set();
  for (const role of roles) {
    const template = STAFF_ROLE_TEMPLATES[role];
    if (!template) return null;
    (template.cols_logbook || []).forEach(col => colsLogbook.add(col));
    (template.cols_other || []).forEach(col => colsOther.add(col));
    (template.cols_business || []).forEach(col => colsSme.add(col));
  }

  return {
    cols_logbook: Array.from(colsLogbook).sort((a, b) => a - b),
    cols_other: Array.from(colsOther).sort((a, b) => a - b),
    cols_business: Array.from(colsSme).sort((a, b) => a - b),
  };
}

function webParseSheets_(value) {
  const raw = String(value || "*").trim();
  if (!raw || raw === "*") return "*";
  return raw.split(",").map(s => s.trim()).filter(Boolean);
}

function webPublicUser_(user) {
  return {
    email: user.email,
    name: user.name,
    role: user.role,
    branch: user.branch,
    source: user.source,
  };
}

function webCanAccessSheet_(user, sheetName) {
  return user.sheets === "*" || (Array.isArray(user.sheets) && user.sheets.includes(sheetName));
}

function webAllowedColumns_(user, sheetName) {
  const pConfig = PRODUCTS[sheetName];
  if (!pConfig) return [];
  const cols = roleColumnsForSheet_(user, sheetName);
  const allowed = new Set(cols || []);
  systemManagedColumns_(pConfig).forEach(col => allowed.delete(col));
  allowed.add(pConfig.COL.REMARKS);
  return Array.from(allowed);
}

function webCanEditColumn_(user, sheetName, col) {
  return webAllowedColumns_(user, sheetName).includes(Number(col));
}

function webResolveCaseLocation_(payload) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheetName = String(payload && payload.sheetName || "");
  const caseId = String(payload && payload.caseId || "").trim();
  const requestedRow = Number(payload && payload.row);

  const sheets = sheetName ? [sheetName] : TRACKER_SHEETS;
  if (caseId) {
    const index = ss.getSheetByName(WEB_APP_CONFIG.CASE_INDEX_SHEET_NAME);
    if (index && index.getLastRow() >= 2) {
      const rows = index.getRange(2, 1, index.getLastRow() - 1, 3).getValues();
      for (const indexRow of rows) {
        if (String(indexRow[0] || "") !== caseId) continue;
        const indexedSheetName = String(indexRow[1] || "");
        const indexedRow = Number(indexRow[2]);
        if (!TRACKER_SHEETS.includes(indexedSheetName)) continue;
        if (sheetName && indexedSheetName !== sheetName) continue;
        const sheet = ss.getSheetByName(indexedSheetName);
        const pConfig = PRODUCTS[indexedSheetName];
        if (!sheet || !pConfig || indexedRow < CONFIG.DATA_START_ROW) continue;
        const rowCaseId = String(sheet.getRange(indexedRow, pConfig.COL.CASE_ID).getValue() || "");
        if (rowCaseId === caseId) return { sheetName: indexedSheetName, sheet, row: indexedRow, pConfig };
      }
    }
  }

  for (const name of sheets) {
    if (!TRACKER_SHEETS.includes(name)) continue;
    const sheet = ss.getSheetByName(name);
    if (!sheet) continue;
    const pConfig = PRODUCTS[name];
    const C = pConfig.COL;

    if (requestedRow >= CONFIG.DATA_START_ROW && caseId) {
      const rowCaseId = String(sheet.getRange(requestedRow, C.CASE_ID).getValue() || "");
      if (rowCaseId === caseId) return { sheetName: name, sheet, row: requestedRow, pConfig };
    }

    if (caseId) {
      const lastRow = getLastDataRow_(sheet, pConfig);
      const ids = sheet.getRange(CONFIG.DATA_START_ROW, C.CASE_ID, lastRow - CONFIG.DATA_START_ROW + 1, 1).getValues();
      for (let i = 0; i < ids.length; i++) {
        if (String(ids[i][0] || "") === caseId) {
          return { sheetName: name, sheet, row: CONFIG.DATA_START_ROW + i, pConfig };
        }
      }
    }
  }
  throw new Error("Case was not found.");
}

// Returns the header row for a sheet, caching it in CacheService for 1 hour.
// Headers are static at runtime so this eliminates a live sheet read on every
// case detail load.
function getSheetHeaders_(sheet, pConfig) {
  const cache = CacheService.getScriptCache();
  const key = "hdr_" + sheet.getName();
  const cached = cache.get(key);
  if (cached) return JSON.parse(cached);
  const headers = sheet.getRange(WEB_APP_CONFIG.HEADER_ROW, 1, 1, pConfig.COL.REMARKS).getValues()[0];
  try { cache.put(key, JSON.stringify(headers), 3600); } catch (e) { /* ignore cache size errors */ }
  return headers;
}

function webBuildCaseDetail_(user, sheet, row, pConfig, sheetName) {
  const C = pConfig.COL;
  const values = sheet.getRange(row, 1, 1, C.REMARKS).getValues()[0];
  const headers = getSheetHeaders_(sheet, pConfig);
  const editableCols = new Set(webAllowedColumns_(user, sheetName));

  return {
    summary: webBuildCaseSummaryFromValues_(sheetName, row, pConfig, values),
    fields: headers.map((header, idx) => {
      const col = idx + 1;
      const editable = editableCols.has(col) && webCanEditCaseFieldInMemory_(values, pConfig, col);
      return {
        col,
        label: webCleanHeader_(header, pConfig.STAGE_NAMES[col] || `Column ${col}`),
        value: webSerializeValue_(values[idx]),
        kind: webFieldKind_(pConfig, col),
        editable,
        options: webFieldOptions_(pConfig, col),
        lockedReason: editable ? "" : webFieldLockReasonInMemory_(values, pConfig, col, editableCols.has(col)),
      };
    }),
  };
}

function webCanEditCaseFieldInMemory_(rowValues, pConfig, col) {
  const C = pConfig.COL;
  if (systemManagedColumns_(pConfig).has(col)) return false;
  if (col === C.REMARKS) return true;

  const currentValue = rowValues[col - 1];
  if (currentValue !== "") return false;

  if (workflowActionColumns_(pConfig).includes(col)) {
    return webPreviousStagesCompleteInMemory_(rowValues, pConfig, col);
  }

  if (pConfig.TS_SEQUENCE.some(stage => stage[0] === col)) {
    return webPreviousStagesCompleteInMemory_(rowValues, pConfig, col);
  }

  return true;
}

function webFieldLockReasonInMemory_(rowValues, pConfig, col, hasRoleAccess) {
  const C = pConfig.COL;
  if (col === C.CASE_ID) return "Case ID is system managed.";
  if (col === C.STATUS) return "Status is system managed.";
  if (configuredColumns_(pConfig, ["CASE_ID", "TS_CREATED", "TS_DECISION", "TS_SANCTIONS", "TS_REGISTER"]).includes(col)) {
    return "System managed field.";
  }
  if (!hasRoleAccess) return "Not assigned to your role.";
  if (rowValues[col - 1] !== "") return "Already completed. ";
  if (!webPreviousStagesCompleteInMemory_(rowValues, pConfig, col)) return "Previous stage is not complete.";
  return "";
}

function webPreviousStagesCompleteInMemory_(rowValues, pConfig, col) {
  const targetCol = webComparableStageColumn_(pConfig, col);
  const seq = pConfig.TS_SEQUENCE.map(stage => stage[0]);
  const idx = seq.indexOf(targetCol);
  if (idx <= 0) return true;

  const previousCol = seq[idx - 1];
  const prevVal = rowValues[previousCol - 1];
  return prevVal instanceof Date || (typeof prevVal === "string" && prevVal !== "");
}

function webBuildCaseSummaryFromValues_(sheetName, row, pConfig, rowValues) {
  const C = pConfig.COL;
  const created = rowValues[C.TS_CREATED - 1];
  return {
    sheetName,
    row,
    caseId: rowValues[C.CASE_ID - 1],
    client: rowValues[C.CLIENT_NAME - 1],
    branch: rowValues[C.BRANCH - 1],
    amount: rowValues[C.AMOUNT - 1],
    status: rowValues[C.STATUS - 1],
    product: sheetName.replace("TRACKER-", ""),
    hrs: created instanceof Date ? Math.round((new Date() - created) / 3600000) : null,
    createdSort: created instanceof Date ? created.getTime() : 0,
  };
}

function webCleanHeader_(header, fallback) {
  return String(header || fallback || "").replace(/\s+/g, " ").trim();
}

function webSerializeValue_(value) {
  return value instanceof Date ? formatDate_(value) : value;
}

function webFieldKind_(pConfig, col) {
  const C = pConfig.COL;
  if (col === C.BRANCH || workflowActionColumns_(pConfig).includes(col)) return "dropdown";
  if (pConfig.TS_SEQUENCE.some(stage => stage[0] === col)) return "timestamp";
  if (col === C.AMOUNT) return "number";
  return "text";
}

function webFieldOptions_(pConfig, col) {
  const C = pConfig.COL;
  if (col === C.BRANCH) return WEB_APP_CONFIG.BRANCHES;
  if (isConfiguredColumn_(pConfig, "DECISION", col)) return WEB_APP_CONFIG.DROPDOWNS.DECISION;
  if (isConfiguredColumn_(pConfig, "SANCTIONS", col)) return WEB_APP_CONFIG.DROPDOWNS.SANCTIONS;
  if (isConfiguredColumn_(pConfig, "REGISTER", col)) return WEB_APP_CONFIG.DROPDOWNS.REGISTER;
  if (isConfiguredColumn_(pConfig, "REGISTER_APPROVED", col)) return WEB_APP_CONFIG.DROPDOWNS.REGISTER_APPROVED;
  return [];
}

function webCanEditCaseField_(sheet, row, pConfig, col) {
  const C = pConfig.COL;
  if (systemManagedColumns_(pConfig).has(col)) return false;
  if (col === C.REMARKS) return true;

  const currentValue = sheet.getRange(row, col).getValue();
  if (currentValue !== "") return false;

  if (workflowActionColumns_(pConfig).includes(col)) {
    return webPreviousStagesComplete_(sheet, row, pConfig, col);
  }

  if (pConfig.TS_SEQUENCE.some(stage => stage[0] === col)) {
    return webPreviousStagesComplete_(sheet, row, pConfig, col);
  }

  return true;
}

function webFieldLockReason_(sheet, row, pConfig, col, hasRoleAccess) {
  const C = pConfig.COL;
  if (col === C.CASE_ID) return "Case ID is system managed.";
  if (col === C.STATUS) return "Status is system managed.";
  if (configuredColumns_(pConfig, ["CASE_ID", "TS_CREATED", "TS_DECISION", "TS_SANCTIONS", "TS_REGISTER"]).includes(col)) {
    return "System managed field.";
  }
  if (!hasRoleAccess) return "Not assigned to your role.";
  if (sheet.getRange(row, col).getValue() !== "") return "Already completed. ";
  if (!webPreviousStagesComplete_(sheet, row, pConfig, col)) return "Previous stage is not complete.";
  return "";
}

function webPreviousStagesComplete_(sheet, row, pConfig, col) {
  const C = pConfig.COL;
  const targetCol = webComparableStageColumn_(pConfig, col);
  const seq = pConfig.TS_SEQUENCE.map(stage => stage[0]);
  const idx = seq.indexOf(targetCol);
  if (idx <= 0) return true;

  const previousCol = seq[idx - 1];
  return sheet.getRange(row, previousCol).getValue() instanceof Date;
}

function webComparableStageColumn_(pConfig, col) {
  const C = pConfig.COL;
  if (isConfiguredColumn_(pConfig, "DECISION", col)) return C.TS_DECISION;
  if (isConfiguredColumn_(pConfig, "SANCTIONS", col)) return C.TS_SANCTIONS;
  if (isConfiguredColumn_(pConfig, "REGISTER", col)) return C.TS_REGISTER;
  if (isConfiguredColumn_(pConfig, "REGISTER_APPROVED", col)) return C.TS_DISBURSE;
  return col;
}

function webBuildHomeData_(user) {
  const recent = [];
  const actionRequired = [];
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const SCAN_LIMIT = 100;
  
  TRACKER_SHEETS.forEach(sheetName => {
    if (!webCanAccessSheet_(user, sheetName)) return;
    const sheet = ss.getSheetByName(sheetName);
    if (!sheet) return;
    const pConfig = PRODUCTS[sheetName];
    const C = pConfig.COL;
    const lastRow = getLastDataRow_(sheet, pConfig);
    if (lastRow < CONFIG.DATA_START_ROW) return;
    
    const startScanRow = Math.max(CONFIG.DATA_START_ROW, lastRow - SCAN_LIMIT + 1);
    const numRowsToScan = lastRow - startScanRow + 1;
    const values = sheet.getRange(startScanRow, 1, numRowsToScan, C.REMARKS).getValues();
    values.forEach((rowValues, i) => {
      if (!rowValues[C.CASE_ID - 1]) return;
      const summary = webBuildCaseSummaryFromValues_(sheetName, startScanRow + i, pConfig, rowValues);
      recent.push(summary);

      const nextCol = webNextActionColumn_(pConfig, rowValues);
      if (nextCol && webCanEditColumn_(user, sheetName, nextCol)) {
        actionRequired.push({
          ...summary,
          nextCol,
          nextStage: `Next: ${pConfig.STAGE_NAMES[nextCol] || "Next action"}`,
          queueReason: webQueueReason_(pConfig, rowValues, nextCol),
        });
      }
    });
  });

  return {
    recent: recent.sort(webSortCaseSummaryNewestFirst_).slice(0, WEB_APP_CONFIG.RECENT_LIMIT),
    actionRequired: actionRequired.slice(0, WEB_APP_CONFIG.RECENT_LIMIT),
  };
}

function webSortCaseSummaryNewestFirst_(a, b) {
  const createdA = a.createdSort || 0;
  const createdB = b.createdSort || 0;
  if (createdA !== createdB) return createdB - createdA;
  return b.row - a.row;
}

function webListRecentCases_(user, limit) {
  return webBuildHomeData_(user).recent.slice(0, limit);
}

function webListActionRequired_(user, limit) {
  return webBuildHomeData_(user).actionRequired.slice(0, limit);
}

function webQueueReason_(pConfig, rowValues, nextCol) {
  const C = pConfig.COL;
  if (nextCol === C.REGISTER_APPROVED) return "Register approval pending";
  if (nextCol === C.DECISION) return "HOCC decision pending";
  if (nextCol === C.SANCTIONS) return "Sanctions update pending";
  if (nextCol === C.REGISTER) return "Disbursement register pending";
  if (nextCol === C.TS_DISBURSE) return "Disbursement pending";
  return "Your stage is ready";
}

function webNextActionColumn_(pConfig, rowValues) {
  const C = pConfig.COL;
  if (rowValues[C.STATUS - 1] && ["Disbursed", "Rejected", "Declined"].includes(String(rowValues[C.STATUS - 1]))) return null;

  if (rowValues[C.REGISTER - 1] && !rowValues[C.REGISTER_APPROVED - 1]) return C.REGISTER_APPROVED;

  for (let i = 0; i < pConfig.TS_SEQUENCE.length; i++) {
    const col = pConfig.TS_SEQUENCE[i][0];
    if (rowValues[col - 1] instanceof Date) continue;
    if (isConfiguredColumn_(pConfig, "TS_DECISION", col)) return C.DECISION;
    if (isConfiguredColumn_(pConfig, "TS_SANCTIONS", col)) return C.SANCTIONS;
    if (isConfiguredColumn_(pConfig, "TS_REGISTER", col)) return C.REGISTER;
    return col;
  }
  return null;
}

function webApplyCaseChange_(
  user,
  sheet,
  row,
  pConfig,
  sheetName,
  change
) {
  const C = pConfig.COL;
  const col = Number(change && change.col);

  if (
    !Number.isInteger(col) ||
    col < 1 ||
    col > C.REMARKS
  ) {
    throw new Error("Invalid field submitted.");
  }

  if (!webCanEditColumn_(user, sheetName, col)) {
    throw new Error(
      "Your role cannot edit one of the submitted fields."
    );
  }

  if (!webCanEditCaseField_(sheet, row, pConfig, col)) {
    throw new Error(
      webFieldLockReason_(
        sheet,
        row,
        pConfig,
        col,
        true
      ) || "This field cannot be edited."
    );
  }

  const kind = webFieldKind_(pConfig, col);
  const cell = sheet.getRange(row, col);
  const oldValue = cell.getValue();

  let nextValue = change ? change.value : "";

  if (kind === "timestamp") {
    nextValue = new Date();

  } else if (kind === "dropdown") {
    nextValue = String(nextValue || "").trim();

    const options = webFieldOptions_(
      pConfig,
      col
    );

    if (
      nextValue &&
      !options.includes(nextValue)
    ) {
      throw new Error("Invalid dropdown value.");
    }

  } else if (kind === "number") {
    nextValue = Number(nextValue);

    if (!Number.isFinite(nextValue)) {
      throw new Error("Enter a valid number.");
    }

    if (col === C.AMOUNT) {
      const amountError = amountValidationError_(nextValue, pConfig, sheetName);
      if (amountError) throw new Error(amountError);
    }

  } else {
    nextValue = String(nextValue || "").trim();
  }

  if (
    col === C.TS_LO_APPLY &&
    hasConfiguredColumn_(pConfig, "SANCTIONS") &&
    sheet.getRange(row, C.SANCTIONS).getValue() !== "Met"
  ) {
    throw new Error(
      "Sanctions must be marked Met before applying on system."
    );
  }

  if (
    col === C.TS_DISBURSE &&
    sheet
      .getRange(row, C.REGISTER_APPROVED)
      .getValue() !== "Approved"
  ) {
    throw new Error(
      "Register must be approved before disbursement."
    );
  }

  cell.setValue(nextValue);

  if (nextValue instanceof Date) {
    cell.setNumberFormat(CONFIG.DATE_TIME_FORMAT);
  }

  if (kind === "timestamp") {
    const violation = checkDateFlow_(
      sheet,
      row,
      col,
      pConfig
    );

    if (violation) {
      restoreEditedCell_(
        cell,
        oldValue,
        pConfig
      );

      throw new Error(
        `${violation.thisLabel} cannot be earlier than ` +
        `${violation.prevLabel}.`
      );
    }
  }

  const sideEffectAudits = webApplySideEffects_(
    sheet,
    row,
    pConfig,
    col,
    nextValue
  );

  writeAuditLog_(
    sheetName,
    sheet.getRange(row, C.CASE_ID).getValue(),
    row,
    pConfig.STAGE_NAMES[col] || `Column ${col}`,
    nextValue,
    WEB_APP_CONFIG.AUDIT_SOURCE
  );

  sideEffectAudits.forEach(audit => {
    writeAuditLog_(
      sheetName,
      sheet.getRange(row, C.CASE_ID).getValue(),
      row,
      audit.stageName,
      audit.value,
      WEB_APP_CONFIG.AUDIT_SOURCE
    );
  });
}

function webApplySideEffects_(sheet, row, pConfig, col, value) {
  const C = pConfig.COL;
  const now = new Date();
  const audits = [];

  if (isConfiguredColumn_(pConfig, "DECISION", col)) {
    const tsCell = sheet.getRange(row, C.TS_DECISION);
    if (value && !tsCell.getValue()) {
      tsCell.setValue(now).setNumberFormat(CONFIG.DATE_TIME_FORMAT);
      audits.push({ stageName: "Decision TS", value: now });
    }
    if (value === "Rejected") sheet.getRange(row, C.STATUS).setValue("Rejected");
    if (value === "Deferred") sheet.getRange(row, C.STATUS).setValue("Deferred");
  }

  if (isConfiguredColumn_(pConfig, "SANCTIONS", col)) {
    const tsCell = sheet.getRange(row, C.TS_SANCTIONS);
    if (value === "Met" && !tsCell.getValue()) {
      tsCell.setValue(now).setNumberFormat(CONFIG.DATE_TIME_FORMAT);
      audits.push({ stageName: "Sanctions TS", value: now });
    }
    if (value === "Not Met") {
      const remCell = sheet.getRange(row, C.REMARKS);
      const rem = remCell.getValue();
      if (!String(rem).includes("Sanctions Not Met")) {
        remCell.setValue(`[${formatDate_(now)}: Sanctions Not Met - conditions unfulfilled] ${rem}`);
      }
    }
  }

  if (isConfiguredColumn_(pConfig, "REGISTER", col)) {
    const tsCell = sheet.getRange(row, C.TS_REGISTER);
    if (value && !tsCell.getValue()) {
      tsCell.setValue(now).setNumberFormat(CONFIG.DATE_TIME_FORMAT);
      audits.push({ stageName: "Register TS", value: now });
    }
  }

  if (col === C.TS_DISBURSE) {
    sheet.getRange(row, C.STATUS).setValue("Disbursed");
  }
  return audits;
}

function webNextDataRow_(sheet, pConfig) {
  const lastRow = getLastDataRow_(sheet, pConfig);
  const caseIdAtLast = sheet.getRange(lastRow, pConfig.COL.CASE_ID).getValue();
  return caseIdAtLast ? lastRow + 1 : CONFIG.DATA_START_ROW;
}

function generateCaseId_(sheet, sheetName) {
  const prefix  = CONFIG.CASE_ID_PREFIX[sheetName];
  const year    = new Date().getFullYear();
  const pConfig = PRODUCTS[sheetName];
  const regex   = new RegExp(`^${prefix}-${year}-(\\d+)$`);
  let maxNum = 0;

  // Read only populated rows instead of the entire Column A.
  const lastRow = getLastDataRow_(sheet, pConfig);
  if (lastRow >= CONFIG.DATA_START_ROW) {
    const data = sheet
      .getRange(CONFIG.DATA_START_ROW, 1, lastRow - CONFIG.DATA_START_ROW + 1, 1)
      .getValues()
      .flat();
    data.forEach(id => {
      const match = String(id).match(regex);
      if (match) maxNum = Math.max(maxNum, parseInt(match[1]));
    });
  }

  return `${prefix}-${year}-${String(maxNum + 1).padStart(3, "0")}`;
}

function formatDate_(d) {
  if (!(d instanceof Date)) return "";
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return `${String(d.getDate()).padStart(2, "0")}-${months[d.getMonth()]}-${d.getFullYear()} ` +
         `${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`;
}

function checkDateFlow_(sheet, row, col, pConfig) {
  const seq = pConfig.TS_SEQUENCE;
  const idx = seq.findIndex(x => x[0] === col);
  if (idx <= 0) return null;

  const thisVal   = sheet.getRange(row, col).getValue();
  const [prevCol, prevLabel] = seq[idx - 1];
  const prevVal   = sheet.getRange(row, prevCol).getValue();

  if (prevVal instanceof Date && thisVal instanceof Date && thisVal < prevVal) {
    return { prevLabel, prevDate: prevVal, thisLabel: seq[idx][1] };
  }
  return null;
}

function getLastDataRow_(sheet, pConfig) {
  const data = sheet.getRange("A:A").getValues();
  for (let i = data.length - 1; i >= CONFIG.DATA_START_ROW - 1; i--) {
    if (data[i][0] !== "") return i + 1;
  }
  return CONFIG.DATA_START_ROW;
}

function currentStage_(sheet, row, pConfig) {
  const seq = pConfig.TS_SEQUENCE;
  for (let i = seq.length - 1; i >= 0; i--) {
    const [c, label] = seq[i];
    const val = sheet.getRange(row, c).getValue();
    if (val instanceof Date) {
      if (i === seq.length - 1) return "Disbursed";
      return `Awaiting: ${seq[i + 1][1]}`;
    }
  }
  return "Awaiting: Case Created";
}

function buildSummary_(sheet, row, pConfig, product) {
  const C = pConfig.COL;
  const caseId  = sheet.getRange(row, C.CASE_ID).getValue();
  const client  = sheet.getRange(row, C.CLIENT_NAME).getValue();
  const branch  = sheet.getRange(row, C.BRANCH).getValue();
  const status  = sheet.getRange(row, C.STATUS).getValue();
  const created = sheet.getRange(row, C.TS_CREATED).getValue();

  let hrs = null;
  if (created instanceof Date) {
    hrs = Math.round((new Date() - created) / 3600000);
  }

  return {
    caseId, client, branch, product, status, hrs,
    stage: currentStage_(sheet, row, pConfig),
  };
}
