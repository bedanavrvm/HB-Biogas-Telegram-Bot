/**
 * TAT register hygiene only. Django owns all workflow values and timestamps.
 * Every field resolves by unique live header; reorder/insert columns freely.
 */
const TAT_CONFIG = {HEADER_ROW: 1, DATA_START_ROW: 2, DEFAULT_MAX_ROWS: 500,
  DATE_TIME_FORMAT: 'dd-mmm-yyyy hh:mm', TRACKER_SHEETS: ['TAT Register']};
const TAT_STAGES = [
  ['mpesa_to_admin','MPESA Sent to Admin'],
  ['bm_analysis_approval','BM analysis approval','BM analysis approval timestamp'],
  ['mpesa_verified','MPESA Verified and Sent to CA'],
  ['ca_analysis_sent','Credit Analysis Sent'],
  ['bro_response','BRO Response to CA'],
  ['bm_response','BM Response to CA','BM Response Timestamp'],
  ['valuation_ready','Valuation Ready'], ['bm_hocc_request','BM HOCC Request'],
  ['tat_scheduled','HOCC Scheduled'], ['tat_held','HOCC Held'],
  ['decision','Decision','Decision Timestamp'],
  ['minutes_shared','Minutes Shared','Minutes Shared Timestamp'],
  ['sanctions','Sanctions','Sanctions Timestamp'],
  ['bro_applied','BRO Applied on System','BRO Applied Timestamp'],
  ['disbursement_register','Disbursement Register','Register Timestamp'],
  ['register_approved','Register Approved','Register approved timestamp'], ['disbursement','Finance Disbursement']
];
const TAT_HEADERS = [
  'Case ID','Client Name','ID NUMBER','PHONE NUMBER','Branch','BRO Name','Requested Amount',
  'Case Created','Product','Loan Cycle Path',
  ...TAT_STAGES.flatMap(stage => stage.slice(1)),
  'Final Loan Amount','Status','Remarks / Delays','TAT Hours','TAT Days','Total TAT Minutes',
  ...TAT_STAGES.map(stage => stage[1] + ' TAT Minutes'), 'Product Key'
];
const TAT_COLUMN_ALIASES = {
  'Client Name':['Customer Name'], 'ID NUMBER':['National ID'], 'PHONE NUMBER':['Primary Phone'],
  'Requested Amount':['Amount'], 'Case Created':['Created'],
  'MPESA Verified and Sent to CA':['MPESA verified by Business Admin and sent to CA'],
  'BRO Applied on System':['BRO applied loan on system'],
  'Disbursement Register':['Business Admin disbursement register'],
  'Total TAT Minutes':['TAT Minutes','Case TAT Minutes'], 'Remarks / Delays':['Remarks']
};
TAT_STAGES.forEach(stage => {
  TAT_COLUMN_ALIASES[stage[1]+' TAT Minutes'] = [
    ...(TAT_COLUMN_ALIASES[stage[1]]||[]).map(name=>name+' TAT Minutes'),
    stage[1]+' TAT',stage[0]+' TAT Minutes'
  ];
});
function normalizeColumnName_(value) {
  return String(value || '').normalize('NFKC').trim().toLowerCase().replace(/\s+/g, ' ');
}
function namedColumns_(sheet, row) {
  const headers = sheet.getRange(row || 1, 1, 1, Math.max(sheet.getLastColumn(), 1)).getDisplayValues()[0];
  const map = Object.create(null);
  headers.forEach((header, index) => {
    const key = normalizeColumnName_(header);
    if (!key) return;
    if (map[key]) throw new Error('Duplicate column name: ' + header + '. Rename before continuing.');
    map[key] = index + 1;
  });
  return {headers, column(name) {
    const matches=[...new Set([name,...(TAT_COLUMN_ALIASES[name]||[])].map(candidate=>map[normalizeColumnName_(candidate)]).filter(Boolean))];
    if(matches.length>1)throw new Error('Ambiguous column: '+name+'. Keep one named field.');
    const value = matches[0];
    if (!value) throw new Error('Required named column missing: ' + name);
    return value;
  }};
}
function ensureNamedHeaders_(sheet, names) {
  if (!sheet.getLastRow()) {
    ensureRowsAndColumns_(sheet, 500, names.length);
    sheet.getRange(1, 1, 1, names.length).setValues([names]);
  }
  const columns = namedColumns_(sheet);
  names.forEach(name => columns.column(name));
  return columns;
}
function onOpen() {
  SpreadsheetApp.getUi().createMenu('TAT Tracker')
    .addItem('Setup / refresh workbook', 'setupTatTrackerWorkbook')
    .addItem('Setup TAT Register only', 'setupCurrentTatTrackerSheet')
    .addItem('Refresh validations only', 'refreshTatValidations')
    .addItem('Refresh TAT value formatting', 'refreshTatFormulas')
    .addItem('Refresh TAT highlighting', 'refreshTatHighlighting')
    .addItem('Remove legacy TAT formulas (safe)', 'clearLegacyTatFormulas')
    .addItem('Create support tabs', 'setupTatSupportTabs')
    .addItem('Show setup notes', 'showTatSetupNotes').addToUi();
}
function tracker_() {
  const ss = SpreadsheetApp.getActive();
  return ss.getSheetByName('TAT Register') || ss.insertSheet('TAT Register');
}
function setupTatTrackerWorkbook() {
  setupCurrentTatTrackerSheet(); setupTatSupportTabs();
}
function setupCurrentTatTrackerSheet() {
  const sheet = tracker_();
  ensureNamedHeaders_(sheet, TAT_HEADERS);
  refreshTatValidations(); refreshTatFormulas(); refreshTatHighlighting();
  sheet.setFrozenRows(1);
}
function refreshTatValidations() {
  const sheet = tracker_(), columns = namedColumns_(sheet);
  const choices = {
    'BM analysis approval':['Approved','Declined'], 'BM Response to CA':['Approved','Declined'],
    'Decision':['Approved','Rejected','Deferred'], 'Minutes Shared':['Yes','No'],
    'Sanctions':['Met','Not Met'], 'BRO Applied on System':['Met','Not Met'],
    'Disbursement Register':['10:00am','1:00pm','3:30pm'],
    'Register Approved':['Approved','Declined'], 'Status':['Active','Stalled','Declined','Disbursed']
  };
  Object.entries(choices).forEach(([name, values]) => {
    sheet.getRange(2, columns.column(name), Math.max(sheet.getMaxRows()-1,1), 1)
      .setDataValidation(SpreadsheetApp.newDataValidation().requireValueInList(values,true).setAllowInvalid(false).build());
  });
}
function refreshTatFormulas() {
  const sheet = tracker_(), columns = namedColumns_(sheet), count = Math.max(sheet.getMaxRows()-1,1);
  ['Case Created', ...TAT_STAGES.flatMap(stage => stage.length > 2 ? [stage[2]] :
    ['register_approved'].includes(stage[0]) ? [] : [stage[1]])].forEach(name => {
      sheet.getRange(2, columns.column(name), count,1).setNumberFormat(TAT_CONFIG.DATE_TIME_FORMAT);
    });
  ['TAT Hours','TAT Days','Total TAT Minutes',...TAT_STAGES.map(stage=>stage[1]+' TAT Minutes')]
    .forEach(name=>sheet.getRange(2,columns.column(name),count,1).setNumberFormat('0.00'));
  ['ID NUMBER','PHONE NUMBER'].forEach(name=>sheet.getRange(2,columns.column(name),count,1).setNumberFormat('@'));
  ['Requested Amount','Final Loan Amount'].forEach(name=>sheet.getRange(2,columns.column(name),count,1).setNumberFormat('#,##0.00'));
}
function refreshTatHighlighting() {
  const sheet=tracker_(), columns=namedColumns_(sheet), count=Math.max(sheet.getMaxRows()-1,1);
  const status=sheet.getRange(2,columns.column('Status'),count,1);
  const managed=new Set([columns.column('Status'),...TAT_STAGES.map(stage=>columns.column(stage[1]+' TAT Minutes'))]);
  const rules=sheet.getConditionalFormatRules().filter(rule=>!rule.getRanges().some(range=>
    range.getSheet().getSheetId()===sheet.getSheetId() && managed.has(range.getColumn()) && range.getNumColumns()===1));
  Object.entries({Active:'#dbeafe',Stalled:'#fef3c7',Declined:'#fee2e2',Disbursed:'#dcfce7'}).forEach(([value,color])=>{
    rules.push(SpreadsheetApp.newConditionalFormatRule().whenTextEqualTo(value).setBackground(color).setRanges([status]).build());
  });
  // Stage timing is Django-calculated. Targets are explicitly configured;
  // missing targets never receive an invented success/failure colour.
  const targetSheet=SpreadsheetApp.getActive().getSheetByName('TAT TARGETS');
  if(targetSheet && targetSheet.getLastRow()>1) {
    const targets=namedColumns_(targetSheet);
    const targetRows=targetSheet.getRange(2,1,targetSheet.getLastRow()-1,targetSheet.getLastColumn()).getValues();
    targetRows.forEach(row=>{
      const key=row[targets.column('Stage Key')-1];
      const stage=TAT_STAGES.find(item=>item[0]===key), minutes=Number(row[targets.column('Target Minutes')-1]);
      if(!stage || !(minutes>0))return;
      const product=String(row[targets.column('Product Key')-1]);
      const near=Number(row[targets.column('Near Ratio')-1])||0.8;
      const minuteCol=columns.column(stage[1]+' TAT Minutes');
      const range=sheet.getRange(2,minuteCol,count,1);
      const value='$'+colLetter_(minuteCol)+'2';
      const match='$'+colLetter_(columns.column('Product Key'))+'2="'+product.replace(/"/g,'""')+'"';
      [[value+'<'+minutes*near,'#dcfce7'],['AND('+value+'>='+minutes*near+','+value+'<='+minutes+')','#fef3c7'],
        [value+'>'+minutes,'#fee2e2']].forEach(([condition,color])=>{
          rules.push(SpreadsheetApp.newConditionalFormatRule().whenFormulaSatisfied('=AND('+match+',ISNUMBER('+value+'),'+condition+')')
            .setBackground(color).setRanges([range]).build());
        });
    });
  }
  sheet.setConditionalFormatRules(rules);
}
function clearLegacyTatFormulas() {
  const ui=SpreadsheetApp.getUi();
  if(ui.alert('Clear legacy formulas','Clear formulas only from named TAT value columns?',ui.ButtonSet.OK_CANCEL)!==ui.Button.OK)return;
  const sheet=tracker_(), columns=namedColumns_(sheet);
  ['TAT Hours','TAT Days','Total TAT Minutes',...TAT_STAGES.map(stage=>stage[1]+' TAT Minutes')].forEach(name=>{
    const range=sheet.getRange(2,columns.column(name),Math.max(sheet.getMaxRows()-1,1),1);
    range.getFormulas().forEach((row,index)=>{if(row[0])sheet.getRange(index+2,columns.column(name)).clearContent();});
  });
}
function setupTatSupportTabs() {
  const ss=SpreadsheetApp.getActive();
  const definitions={
    CASE_INDEX:['Case ID','Tracker Sheet','Row Number','Client Name','ID NUMBER','PHONE NUMBER','Branch','BRO Name','Status','Created At','Last Updated At'],
    'AUDIT LOG':['Event ID','Timestamp','Actor','Tracker Sheet','Case ID','Row Number','Stage','New Value','Old Value','Source'],
    'TAT TARGETS':['Product Key','Stage Key','Target Minutes','Near Ratio']
  };
  Object.entries(definitions).forEach(([name,headers])=>ensureNamedHeaders_(ss.getSheetByName(name)||ss.insertSheet(name),headers));
}
function showTatSetupNotes() {
  SpreadsheetApp.getUi().alert('Django owns workflow updates. Column names must be unique. Existing populated sheets are validated, never relabelled. Add the three BM columns manually before refreshing. Do not edit worksheet structure during publication or cleanup.');
}
function ensureRowsAndColumns_(sheet,rows,cols) {
  if(sheet.getMaxRows()<rows)sheet.insertRowsAfter(sheet.getMaxRows(),rows-sheet.getMaxRows());
  if(sheet.getMaxColumns()<cols)sheet.insertColumnsAfter(sheet.getMaxColumns(),cols-sheet.getMaxColumns());
}
function colLetter_(column) {
  let result=''; while(column>0){const remainder=(column-1)%26;result=String.fromCharCode(65+remainder)+result;column=Math.floor((column-1)/26);}
  return result;
}
