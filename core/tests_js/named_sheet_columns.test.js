'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function sheet(headers) {
  return {getLastColumn:()=>headers.length,
    getRange:()=>({getDisplayValues:()=>[headers]})};
}

for (const filename of ['order_approval_apps_script.gs', 'current orders/script.gs', 'complaint_management_apps_script.gs']) {
  const context = vm.createContext({console});
  const source = fs.readFileSync(path.resolve(__dirname, '../..', filename), 'utf8');
  vm.runInContext(source, context, {filename});
  assert.equal(context.namedColumn_(sheet(['Notes', 'Case ID', 'Phone Number']), 1, ' case  id '), 2);
  assert.throws(()=>context.namedColumn_(sheet(['Notes']), 1, 'Case ID'), /missing/i);
  assert.throws(()=>context.namedColumn_(sheet(['Case ID', ' case  id ']), 1, 'Case ID'), /Duplicate/i);
  assert.throws(()=>context.namedColumn_(sheet(['Case ID', 'Ｃａｓｅ ID']), 1, 'Case ID'), /Duplicate/i);
  assert.equal(context.namedColumn_(sheet(['constructor', 'Case ID']), 1, 'constructor'), 1);
  const writes=[];
  const reordered = {...sheet(['Notes','Phone Number','Case ID']),getRange:(row,column)=>row===1
    ? {getDisplayValues:()=>[['Notes','Phone Number','Case ID']]}
    : {setValue:value=>writes.push([row,column,value])}};
  context.writeNamedRows_(reordered, 1, ['Case ID','Phone Number'], 2, [['synthetic-case','test-phone']]);
  assert.deepEqual(writes, [[2,3,'synthetic-case'],[2,2,'test-phone']]);
  console.log(`${filename}: named columns and reordered sample writes passed`);
  if (filename !== 'complaint_management_apps_script.gs') {
    assert.throws(()=>context.expandEditableToken('3', ['Case ID','Phone Number']), /column names, not numbers/);
    assert.throws(()=>context.expandEditableToken('B', ['Case ID','Phone Number']), /column names, not letters/);
    assert.deepEqual(Array.from(context.expandEditableToken('Phone Number', ['Notes','Phone Number'])), [2]);
    assert.deepEqual(Array.from(context.expandEditableToken('All', ['Notes','','Phone Number'])), [1,3]);
  }
}

{
  const context = vm.createContext({console});
  vm.runInContext(fs.readFileSync(path.resolve(__dirname, '../../tat_tracker_apps_script.gs'),'utf8'), context);
  assert.equal(context.namedColumns_(sheet(['Notes','Case ID'])).column('Case ID'),2);
  assert.throws(()=>context.namedColumns_(sheet(['Case ID',' case id '])),/Duplicate/i);
  assert.throws(()=>context.namedColumns_(sheet(['Notes'])).column('Case ID'),/missing/i);
  console.log('TAT maintenance: unique named columns passed');
}

{
  const context = vm.createContext({console});
  vm.runInContext(fs.readFileSync(path.resolve(__dirname, '../../master_data_script.gs'),'utf8'), context);
  assert.equal(context.col_(sheet(['Notes','National ID']),'NATIONAL_ID'),2);
  assert.throws(()=>context.col_(sheet(['National ID','ID No.']),'NATIONAL_ID'),/Ambiguous/i);
  assert.throws(()=>context.col_(sheet(['National ID',' national id ']),'NATIONAL_ID'),/Duplicate/i);
  console.log('Master Data: named aliases and ambiguity protection passed');
}
