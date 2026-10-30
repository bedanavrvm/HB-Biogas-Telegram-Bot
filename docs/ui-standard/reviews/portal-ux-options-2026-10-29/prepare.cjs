/* Package known synthetic evidence and display-only facts. No Django initialization. */
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {execFileSync}=require('node:child_process');
const base=__dirname,root=path.resolve(base,'../../../..');
const context={window:{}};vm.runInNewContext(fs.readFileSync(path.join(base,'catalogue.js'),'utf8'),context);
const catalogue=context.window.PORTAL_UX;
const read=relative=>JSON.parse(fs.readFileSync(path.join(root,relative),'utf8'));
const snapshots=read(path.relative(root,path.join(base,'baseline-context.json')));
const inputs=read('test-results/portal-state-recovery-review/ux-review-inputs.json');
for(const s of catalogue.scenarios){
 if(s.before==='fresh')continue;
 const target=path.join(base,'assets','before',s.id+'.png');fs.mkdirSync(path.dirname(target),{recursive:true});
 fs.copyFileSync(path.join(root,'test-results',s.before),target);
}
const payment60=read('test-results/portal-workflow-review/payment-60-state.json');
const payment61=read('test-results/portal-workflow-review/payment-61-final.json');
const five=read('test-results/portal-state-recovery-review/identity-payment-final.json');
const compactPayment=c=>Object.fromEntries(['case_reference','customer_name','national_id','branch','invoice_number','order_number','amount','preferred_repayment_date','payment_mode'].map(k=>[k,c[k]]));
const firstVisit=inputs.queue[0];
const credit=inputs.credit.find(c=>c.customer_name==='SYNTHETIC EXTRA COMPETING')||inputs.credit[0];
const field=(kind,part)=>snapshots[kind].formFields.find(f=>f.id.includes(part))?.value||'';
const fieldLabel=(kind,part)=>{const f=snapshots[kind].formFields.find(f=>f.id===part);return f?.options?.find(o=>o.value===f.value)?.label||f?.value||'';};
const pipeline=read('test-results/portal-workflow-review/report-pipeline.json').result;
const rejected=read('test-results/portal-workflow-review/report-rejected.json').result;
const recovery=read('test-results/portal-workflow-review/recovery-before-final.json').data;
const charts=pipeline.charts||pipeline.visualizations||[];
const farmupRows=JSON.parse(execFileSync(path.join(root,'.venv/Scripts/python.exe'),['-c','import csv,json,sys; f=open(sys.argv[1],newline="",encoding="utf-8-sig"); print(json.dumps(list(csv.DictReader(f))))',path.join(root,'test-results/portal-workflow-review/farmup-november-505.csv')],{encoding:'utf8'}));
const sysupRows=JSON.parse(execFileSync(path.join(root,'.venv/Scripts/python.exe'),['-c','import csv,json,sys; f=open(sys.argv[1],newline="",encoding="utf-8-sig"); print(json.dumps(list(csv.DictReader(f))[50:]))',path.join(root,'test-results/portal-workflow-review/sysup-1045.csv')],{encoding:'utf8'}));
const reportRow=r=>({reference:r.case_id,name:r.customer_name,stage:r.workflow_state,id:r.national_id||''});
const facts={
 names:{visit:firstVisit.customer_name,credit:credit.customer_name},
 facts:{visit:{reference:firstVisit.case_reference||firstVisit.case_id||'',national_id:firstVisit.national_id,phone:firstVisit.primary_phone,branch:firstVisit.branch||'Kiambu',county:fieldLabel('visit','jbl-county')||'Kiambu',village:field('visit','village'),sub_county:field('visit','constituency')||field('visit','sub-county')||''},credit:{reference:credit.case_reference||credit.case_id||'',national_id:credit.national_id,phone:credit.primary_phone,branch:credit.branch||'Kiambu'}},
 queue:inputs.queue.map(c=>({name:c.customer_name,reference:c.case_reference||c.case_id||'Unit 1',national_id:c.national_id,phone:c.primary_phone,branch:c.branch||c.county||'Kiambu'})),
 revisit:snapshots.revisit.farmer,
 payment60:payment60.cases.map((c,i)=>({...compactPayment(c),payment_mode:i%3===0?'CASH':'LOAN-JAWABU'})),payment61:payment61.cases.map(compactPayment),
 paymentFive:five.cases.map((c,i)=>({...compactPayment(c),payment_mode:i===1||i===3?'CASH':'LOAN-JAWABU'})),
 reportRows:pipeline.rows.slice(0,5).map(reportRow),rejectedRows:rejected.rows.map(reportRow),reportCharts:charts,
 sysupRows:sysupRows.map((r,i)=>({name:r.Name,id:r['ID NO'],index:i+51})),
 farmupRows: farmupRows.map((r,i)=>({name:r['Customer Name'],id:r['National ID'],index:i+2})),
 reportSummaries:{pipeline:pipeline.summary,rejected:rejected.summary},
 recoveryItems:recovery.items.map(i=>({title:i.title,detail:i.detail,status:i.status,action:i.action?.label,steps:i.steps})),
 baselineDates:Object.fromEntries(Object.entries(snapshots).map(([id,s])=>[id,s.captured_at])),
 replacement:[{number:'770992',name:'SYNTHETIC DIFFERENT HOLDER',id:'99889922',note:'The national ID does not match the applicant.'},{number:'770991',name:'SYNTHETIC HB60 0001',id:'Not provided',note:'The national ID does not match the applicant.'},{number:'779991',name:'SYNTHETIC ECO75 0186',id:'99000186',note:'The national ID does not match the applicant.'},{number:'881102',name:'SYNTHETIC CORRECTED APPLICANT',id:'99000062',note:'This invoice is already matched to another applicant.'}]
};
const historyText=snapshots['history-desktop'].text;
facts.orders=[...historyText.matchAll(/Order ([A-Z]+-\d+)\n(HB|Eco-conserve) · (\d+) cases · v(\d+)\n([^\n]+)\n([^\n]+)/g)].map((m,i)=>({number:m[1],partner:m[2],count:Number(m[3]),version:Number(m[4]),date:m[5],status:m[6],signed:m[6]==='Signed copy',workspaceLabel:'Retained workspace '+(i+1)}));
fs.writeFileSync(path.join(base,'fixtures.js'),'/* Display-only data from isolated synthetic review snapshots. */\nwindow.PORTAL_FIXTURES = '+JSON.stringify(facts,null,2)+';\n');
const docs=path.join(base,'assets','documents');fs.mkdirSync(docs,{recursive:true});
for(let i=1;i<=3;i++)fs.copyFileSync(path.join(root,'test-results/portal-workflow-review/payment-61-after-page0'+i+'.png'),path.join(docs,'payment-61-page-'+i+'.png'));
console.log(JSON.stringify({beforeImages:catalogue.scenarios.length,recaptured:Object.keys(snapshots),payments:payment60.cases.length,documents:3,chartKeys:Object.keys(charts),recoveryItems:facts.recoveryItems.length,orders:facts.orders.length,sourceInputs:Object.keys(inputs)}));
