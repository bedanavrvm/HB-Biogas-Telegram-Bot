/* Build the human review and source manifest from existing browser evidence. */
const fs=require('node:fs');const path=require('node:path');const crypto=require('node:crypto');const vm=require('node:vm');
const base=__dirname,root=path.resolve(base,'../../../..');const relative=path.relative(root,base).replaceAll('\\','/');
const sandbox={window:{}};vm.runInNewContext(fs.readFileSync(path.join(base,'catalogue.js'),'utf8'),sandbox);const {groups,scenarios}=sandbox.window.PORTAL_UX;
const read=file=>JSON.parse(fs.readFileSync(path.join(base,file),'utf8'));
const hash=(file,normalize=false)=>crypto.createHash('sha256').update(normalize?fs.readFileSync(file,'utf8').replaceAll('\r\n','\n'):fs.readFileSync(file)).digest('hex');
const baselines=read('baseline-context.json');const captures=read('capture-observations.json');const interactions=read('interaction-observations.json');
const inventory=directory=>fs.readdirSync(directory,{withFileTypes:true}).flatMap(entry=>entry.isDirectory()?inventory(path.join(directory,entry.name)):[path.join(directory,entry.name)]);
const sourceFiles=['catalogue.js','fixtures.js','preview.js','preview.css','preview.html','gallery.js','gallery.css','index.html'];
const owningSources=['core/services/portal_navigation.py','core/services/jawabu_pipeline.py','core/services/invoice_identity.py','core/static/miniapp/portal_farmer_sheet.js','core/static/miniapp/portal_farmup.js','core/static/miniapp/portal_invoices.js','core/static/miniapp/portal_payments.js','core/static/miniapp/portal_imports.js','core/templates/base_shell.html','core/static/miniapp/portal.css','Stitch/Main Page/code.html','Stitch/Main Page/DESIGN.md','Stitch/Main Page/screen.png'];
const lines=[
 '# Portal UI/UX: current, refinement and redesign','',
 'Review prepared 29–30 October 2026. Baseline source: `53b4e8fa`. **Design options for review; no operational UI migration.**','',
 '[Open the comparison gallery](index.html). Every recommendation below has actual Before images and browser-rendered A/B proposals. The gallery supports enlarged images, view switching and interactive previews.','',
 '## What is included','',
 `- ${groups.length} improvement areas; ${scenarios.length} captured task scenarios.`,
 `- ${scenarios.length} actual baselines, ${scenarios.length*2} primary option images and ${scenarios.length} comparison boards, plus narrow/desktop/dark and interaction captures.`,
 '- A refines the familiar layout. B reorganizes the task using the supplied Stitch surfaces, blue/green semantics, card hierarchy and spacing.',
 '- Both use local Arial/system fallbacks rather than fetching remote fonts, logos, scripts or map tiles.',
 '- Realistic states include rejection, expired appraisal, held import rows, returned payment, missing replacement, revoked access, queued publication and completed records.','',
 '## Recommendations at a glance','',
 '| Area | Priority | Preferred option | Why |','|---|---|---|---|',
 ...groups.map(g=>`| [${g.id} · ${g.title}](#area-${g.id}) | ${g.priority} | ${g.recommended} | ${g.reason} |`),'',
 'P1 means frequent-task friction; P2 means secondary workflow clarity. These are design priorities, not new production release blockers. No option is automatically approved.','',
 '## Read the comparisons fairly','',
 '- Before images are actual synthetic Portal captures, not recreated wireframes. Ten were recaptured after loading/animations settled; the others preserve the original walkthrough state. The old blank Performance/loading archive frames were not used as defects.',
 '- Core records, case counts, IDs, amounts and review states come from those synthetic snapshots. Draft payment modes were restored from the original preparation driver, rather than using the later reviewed values.',
 '- The refreshed Performance baseline shows the recorded officer with 20 points, nine cases and nine visits. An empty-period interaction is explicitly a local preview state; it is not claimed historical ranking evidence.',
 '- The import previews include all 505 FarmUp source rows and all 995 held SysUp rows. Only the visible viewport is in each primary image. Remaining rows and filters can be inspected in the preview.',
 '- After images are proposed presentation. They do not certify backend operations, authentication, integrations or a completed workflow.',''
];
for(const g of groups){
 lines.push(`<a id="area-${g.id}"></a>`,`## ${g.id}. ${g.title}`,'',`**Observed opportunity:** ${g.problem}`,'',`**A — Refinement:** ${g.a}`,'',`**B — Redesign:** ${g.b}`,'',`**Recommendation: ${g.recommended}.** ${g.reason}`,'');
 for(const s of scenarios.filter(s=>s.group===g.id)){
  lines.push(`### ${s.title}`,'',`Role: **${s.role}**. State: **${s.state}**. Viewport: ${s.width} × 844.`,
   '',`[Comparison board](assets/boards/${s.id}.png) · [Interactive A](preview.html?case=${s.id}&variant=a) · [Interactive B](preview.html?case=${s.id}&variant=b)`,'',
   '| Before: actual Portal | A: refinement | B: redesign |','|---|---|---|',
   `| [![Before ${s.title}](assets/before/${s.id}.png)](assets/before/${s.id}.png) | [![Option A ${s.title}](assets/after/${s.id}-a.png)](assets/after/${s.id}-a.png) | [![Option B ${s.title}](assets/after/${s.id}-b.png)](assets/after/${s.id}-b.png) |`,'');
 }
}
lines.push('## Interactions observed in Playwright','',
 '[Raw interaction observations](interaction-observations.json) · [Capture observations](capture-observations.json)','',
 '- Queue search shows an explicit empty state; clearing it restores rows. Opening the second case keeps that case’s ID and phone, rather than displaying the first record.',
 '- Credit outcome changes reveal the relevant fields. Cancelling confirmation keeps the typed note. Optional visit/evidence sections keep entered values and local file selection.',
 '- Final rejection reveals its reason and hides the approval phrase shortcut. Clicking the approval shortcut twice adds its exact phrase once.',
 '- Deselecting one of 500 FarmUp rows leaves 499 selected in both the summary and confirmation. The held filter shows five held rows.',
 '- Returned-payment filtering shows the single returned case. A local mode change remains visible after closing the case panel; it does not approve the case.',
 '- Both upload variants retain the chosen filename and confirmation after denied retry. The external review control can simulate restored access without changing any grant.',
 '- Document navigation reaches the exact retained page-three image. Zoom scrolls inside the document viewport and does not widen the app.',
 '- Empty Performance period and restoring the recorded period are distinct. Settings categories retain the selected preference.',
 '- Gallery search, Before/A/B switching, image enlargement and Escape-to-close were exercised.','',
 'Selected interaction frames:','',
 '| Interaction | Image |','|---|---|',
 '| Visit evidence section | [B](assets/interactions/visit-evidence-section-b.png) |',
 '| Approved credit fields | [B](assets/interactions/credit-approval-fields-b.png) |',
 '| Rejected final-review fields | [B](assets/interactions/final-rejected-fields-b.png) |',
 '| Bulk confirmation after deselection | [B](assets/interactions/farmup-confirmation-b.png) |',
 '| Returned payment detail | [B](assets/interactions/payment-returned-case-b.png) |',
 '| Denied upload keeps file | [A](assets/interactions/upload-denied-retained-a.png) · [B](assets/interactions/upload-denied-retained-b.png) |',
 '| Retained page three | [B](assets/interactions/retained-document-page-three-b.png) |',
 '| Explicit empty Performance period | [B](assets/interactions/performance-empty-period-b.png) |','',
 '## Workflow boundaries','',
 '- Role-filtered Portal navigation remains server-owned. Preview navigation offers only local comparisons for the shown role. It grants no operational access.',
 '- Lead/applicant display deduplication never merges customer identities. Verification, ID discrepancies, notes and current-letter binding remain required.',
 '- No bulk approval, automatic warning acknowledgement, customer-verification badge, new messaging, new scoring policy, financial recalculation or invented backend field was added.',
 '- Reused order numbers do not combine independent workspaces. Document preview displays the actual retained synthetic exported page images unchanged.',
 '- The preview makes no operational API calls, sends no file, requests no camera/GPS and prevents prototype phone links from launching a call. Controls show local interactions or a clearly labelled simulated response.',
 '- Existing deposit eligibility, case revisions, approval ordering, source checksums and signed-document finality are not replaced by a visual stepper.','',
 '## Open or reproduce','',
 'Open `index.html` directly; all gallery, preview, fixture and image assets are local. For an HTTP preview from the repository root:','',
 '```powershell',
 '.venv/Scripts/python.exe -m http.server 8778 --bind 127.0.0.1 --directory docs/ui-standard/reviews/portal-ux-options-2026-10-29',
 '```','',
 'Then open `http://127.0.0.1:8778/`. The static server never initializes Django or deployment settings. To recapture the after options while that server is running:','',
 '```powershell',
 'node docs/ui-standard/reviews/portal-ux-options-2026-10-29/capture.cjs',
 'node docs/ui-standard/reviews/portal-ux-options-2026-10-29/interactions.cjs',
 'node docs/ui-standard/reviews/portal-ux-options-2026-10-29/export.cjs',
 '```','',
 'These are direct Playwright capture/review drivers, with recorded observations and errors, no assertions and no test runner. They do not produce a passing-test certificate. The generator `prepare.cjs` and actual-baseline driver require the original ignored synthetic review inputs/server; the completed pack and after captures do not.','',
 '## Provenance and limits','',
 '- [Manifest](manifest.json) records source and image hashes, source screenshot paths, roles, states, viewports and dates. Synthetic PNGs are individually hash-pinned under an exact-folder artifact classification; approved visual baseline hashes are unchanged.',
 '- The code/CSS and screenshot under `Stitch/Main Page` informed B. No remote reference asset was copied into an operational app. This review does not constitute Phase 6 adoption.',
 '- This pack covers the approved thirteen improvement areas. It is not a newly designed page for every Portal destination: unaffected HB commissioned records, for example, retain their existing summary/evidence pattern.',
 '- No production UI, API, schema, grants, financial state or release flags were changed. The only non-document edits register the synthetic assets and candidate sources.',
 '- Physical Telegram, camera/GPS, screen readers, real providers and deployment were not checked. No test suites, lint, type checks or visual-baseline updates were run.','');
fs.writeFileSync(path.join(base,'README.md'),lines.join('\n')+'\n');
const sources=Object.fromEntries(sourceFiles.map(f=>[f,hash(path.join(base,f),true)]));
const assets=Object.fromEntries(inventory(path.join(base,'assets')).map(file=>[path.relative(base,file).replaceAll('\\','/'),{bytes:fs.statSync(file).size,sha256:hash(file)}]));
const manifest={format:1,created_at:new Date().toISOString(),baseline_date:'2026-10-29',render_date:captures.captured_at,base_commit:'53b4e8fa',status:'design_options_for_review',operational_adoption:false,groups:groups.length,scenarios:scenarios.map(s=>({id:s.id,group:s.group,role:s.role,state:s.state,viewport:{width:s.width,height:844},source:s.before==='fresh'?{kind:'recaptured_actual_portal',...baselines[s.id]}:{kind:'retained_actual_portal',path:'test-results/'+s.before,date:'2026-10-29'},before:'assets/before/'+s.id+'.png',after:{a:'assets/after/'+s.id+'-a.png',b:'assets/after/'+s.id+'-b.png'}})),sources_lf_sha256:sources,owning_sources_sha256:Object.fromEntries(owningSources.map(f=>[f,hash(path.join(root,f),!f.endsWith('.png'))])),assets,browser_observations:{capture_errors:captures.errors,interaction_errors:interactions.errors,blocked_external_requests:[...captures.blockedRequests,...interactions.blockedRequests],automated_tests_run:false}};
fs.writeFileSync(path.join(base,'manifest.json'),JSON.stringify(manifest,null,2)+'\n');
const registryPath=path.join(root,'docs/ui-standard/registry.json');const registry=JSON.parse(fs.readFileSync(registryPath,'utf8'));
if(!registry.source_roots.includes(relative))registry.source_roots.push(relative);
for(const source of sourceFiles){const entry={path:relative+'/'+source,sha256:sources[source],review_reference:relative+'/README.md',reason:'Isolated user-requested Before/A/B design comparison candidate. Direct Playwright captures and interactions use synthetic data; no operational UI, grants, approved baseline or Phase 6 migration.'};const i=registry.changes.findIndex(v=>v.path===entry.path);if(i<0)registry.changes.push(entry);else registry.changes[i]=entry;}
fs.writeFileSync(registryPath,JSON.stringify(registry,null,2)+'\n');
const allowlistPath=path.join(root,'scripts/tracked_artifact_allowlist.json');const allowlist=JSON.parse(fs.readFileSync(allowlistPath,'utf8'));
for(const [file,meta] of Object.entries(assets))if(file.endsWith('.png'))allowlist.artifacts[relative+'/'+file]={sha256:meta.sha256,classification:'synthetic_ui_review',purpose:'User-requested synthetic Portal Before/A/B review evidence; proposed options only, no design-baseline acceptance. Source and capture context: '+relative+'/manifest.json'};
fs.writeFileSync(allowlistPath,JSON.stringify(allowlist,null,2)+'\n');
console.log(JSON.stringify({groups:groups.length,scenarios:scenarios.length,assets:Object.keys(assets).length,sourceFiles:sourceFiles.length,readmeBytes:Buffer.byteLength(lines.join('\n'))}));
