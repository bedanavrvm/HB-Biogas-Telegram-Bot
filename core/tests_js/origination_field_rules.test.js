'use strict';
const assert = require('node:assert/strict');
const rules = require('../../origination/static/miniapp/origination_field_rules.js');
for (const [field, good, bad] of [
  [{type:'text', validation:{format:'email'}}, 'synthetic+tag@example.test', 'bad'],
  [{type:'number', validation:{integer:true,min:0}}, '2', '2.5'],
  [{type:'number', validation:{decimal_places:2}}, '1.250', '1.251'],
  [{type:'date', validation:{max_date:'2026-01-01'}}, '2025-12-31', '2026-02-01'],
  [{type:'date'}, '2024-02-29', '2026-02-29'],
  [{type:'choice', options:[{code:'ke',label:'Kenya'},{code:'ug',label:'Uganda',active:false}]}, 'ke', 'ug'],
  [{type:'boolean'}, false, 'false'],
  [{type:'national_id'}, '001234567', 'KE-123'],
]) {
  assert.equal(rules.validate(field, good), '', JSON.stringify(field));
  assert.notEqual(rules.validate(field, bad), '', JSON.stringify(field));
  assert.equal(rules.validate(field, ''), '');
}
assert.equal(rules.validate({type:'number'}, 0), '');
assert.equal(rules.validate({type:'money'}, '-100'), '');
for (const value of [true,'NaN','Infinity','1e20']) assert.notEqual(rules.validate({type:'number'}, value), '');
assert.equal(rules.validate({type:'date',validation:{no_future:true}}, rules.today()), '');
assert.notEqual(rules.validate({type:'date',validation:{no_future:true}}, '2200-01-01'), '');
console.log('Origination field rule tests passed');
