# Portal state and recovery review

29 October 2026. Follow-up to the [bulk workflow review](portal-miniapp-workflow-review-2026-10-29.md) at commit `29351f9f`, covering its acknowledged gaps: expired deferrals, invoice identity/household letters, accepted requests with lost responses, changing access, concurrent decisions and connected state machines.

**This additional review found real dead ends and repaired them.** The listed recovery journeys were exercised against actual Django/PostgreSQL with Playwright. This is bounded evidence for those transitions, not certification of every combination of states, timing, historical data and external failure.

## Environment and method

- Isolated PostgreSQL database `portal_state_recovery_review`, copied from the earlier synthetic review. Neither production nor the original review database was changed by this follow-up.
- Actual Telegram Portal shell, ordinary synthetic grants and signed-launch validation at loopback 8777. Playwright supplied a local Telegram bridge; this was Chromium, not physical Telegram.
- Visible forms/confirmations for representative paths; authenticated browser requests for repeated approvals, scope denial and simultaneous writes. Final database observations used a read-only connection.
- Google transports were local fixtures. Domain logic, parser, permissions, transitions, generation and retained bytes were real. Remote connections and deployment `.env` loading were blocked, including parser subprocesses. No real messages/provider writes.
- No test runners, assertions, lint, type checks or deployment. Manual drivers and observations remain in the ignored evidence directory.

Open the [screenshots and observations](../test-results/portal-state-recovery-review/index.html). The [previous gallery](../test-results/portal-workflow-review/index.html) retains the 252-case order and 61-case payment Excel/PDF exports.

## Defects reproduced and resulting changes

| Defect | Before | Result and observed verification |
|---|---|---|
| FarmUp response lost after commit | Saved rows remained selected; retry validation produced a false reviewer conflict. | Retain the exact uncertain payload/key and confirm that save before new validation. Six saved rows replayed without duplication. Another run saved 50, lost the response, recovered 11 selected and one held, then reached 61 saved/one held. |
| Unclear expired-deferral handoff | Revisit did not explain who restarts the case or where. | Name Operations, a fresh FarmUp appraisal for the existing unit, then a new JBL visit. Only authorized actors get Open FarmUp; it reached the existing workspace. |
| Old appraisal contact update releases deferral | An unchanged old appraisal date with other source edits could restart the case. | Same/older-date updates retained the expired deferral while saving the contact change. A newer appraisal restarted both guard cases. No new appraisal-age policy was introduced. |
| Naturally expired approvals missing from queues | Stored active status persisted until a detail read, so queues omitted the case. | Queue lookup projects expiry without that incidental read. Both credit/final cases appeared before opening details and were renewed through their forms. |
| Simultaneous first iMAB-number claims | Two unlinked legacy cases both acquired the same unused number; row locks cannot protect a missing row. | PostgreSQL transaction advisory locking serializes that number's claim. One request succeeded, the other got the duplicate message and retried with a different number. Two units of the same canonical customer still shared their number. |
| No explicit resolution of corrected identity flag | Correcting a flagged invoice to the exact applicant ID left it permanently held. | User-approved, note-required action for existing identity managers including Operations. It checks IDs, current review/revision and open correction, then appends verification. Wrong role 403, missing note 400, stale revision 409, valid save/replay 200; original flag retained. |
| Inline correction recovery actions missing | Redirected legacy page left cancel, withdraw, verification and unbatched follow-up preparation unreachable. | Expose existing actions on current invoice detail. Cancel, withdraw, confirmation dismissal, follow-up, verification and preparation were driven there, with existing grants/states/endpoints. |
| Follow-up accepted but lost response causes retry 500 | Retry attempted another pending review; cancellation could also leave the old pending review blocking a successor. | Return the existing active follow-up; cancelling a pending draft closes its pending review. Dropped response/retry returned the same UUID with verification available. |
| Obsolete replacement-invoice dead end | Superseded source retained misleading correction guidance and editing. | Explain replacement, hide obsolete editing, provide Open corrected invoice. It opened the exact current invoice and retained the source/history. |
| Agreement failure discards file | After grant revocation, upload returned 403 after the form had closed. | Keep submission sheet open until success. File/confirmation survived 403 with inline error; restored grant allowed retry without reselecting. Expected agreement errors retain specific guidance. |
| Payment upload contradicts sign-off policy | General capability offered Operations an upload rejected by the configured Head of Rural policy. | Batch response exposes existing policy/scope decision. Operations sees handoff; configured approver sees upload. Mid-confirmation revocation retained file; restored access completed payment. No role added. |

Number-claim concurrency protection is PostgreSQL-specific, not a new SQLite guarantee. Cache versions bind the changed scripts in `base_shell.html`; no schema migration or permission expansion.

## State families, outcomes and next actions

“Earlier” means evidence from the linked bulk review, not a silently repeated run. A row present in a copied database is not an executed transition. `state-inventory.json` lists model choices used for the inventory.

| Family | Exercised outcomes / boundary | Next action or intentional stopping point | Evidence |
|---|---|---|---|
| Pipeline | `jbl_visit`, `credit`, `final_review`, `order`, `ordered`, `deferred`, `rejected`, `withdrawn` | Owning role advances its stage. Rejected/withdrawn remain inspectable. Ordered delegates to financial/HB workspaces. | Earlier review; expiry/renewal results. |
| Deposit / visit | Blank/short/funded/locked deposit; forward/reschedule/defer/reject/cash/other partner; invalid evidence/chronology | Correct deposit before first visit; JBL records outcome. Negative outcomes do not silently enter credit. | Earlier deposit/visit observations and office lead. |
| Expired deferral | JBL, credit and final deferrals reappraised/revisited/reapproved on original UUIDs | Fresh FarmUp update, new JBL visit, new credit/final decisions. | `fresh-reappraisal-*`, `reappraisal-new-visits`, `reappraisal-approved-again` results; handoff images. |
| Old source | Same/older appraisal date with contact edit; later newer appraisal | Contact change does not release expired deferral; newer appraisal resumes at JBL. Comparison uses last saved appraisal. | `appraisal-guards-ui.js.result.json`. |
| Approval validity | Natural credit/final expiry, re-review, supersession, competing approve/reject | Credit must be current before final review. Competing decisions yielded one 200/one 409; revision advanced once. | Expiry queue images before detail; renewal; `concurrency-shared-and-stale` result. |
| FarmUp | Blocked/held/warning/excluded/committed, revised/archived source; committed response lost | Acknowledge explicitly, confirm uncertain save, commit remaining selection. Invalid held row intentionally remains held. | `farmup-recovery-after`, `lost-response-partial`; earlier 500-row run. |
| Orders | Preview/generated unsigned/amendment/stale scan/cancel/reuse/signed current version | Generate current version; signed work is locked; retain old workbooks. | Earlier archive, 252-case exports, stale-source and cancellation evidence. |
| Invoice intake | Missing/mismatched ID; name variance/equal ID; unmatched/matched; duplicate/ignore/restore/superseded | Correct parsed data or explicitly match authorized applicant. Name/phone do not prove identity. | Invoice match/missing/flagged results and `replacement-final.json`; earlier parser negatives. |
| Identity review | Pending/different person/insufficient/flagged/resolved same person/cancelled pending | Missing ID needs correction; flag needs explicit verification; distinct IDs need household workflow. Remaining pending draft has Verify household identity. | `flag-resolution-ui`, review history, follow-up images. |
| Household correction | Draft/sent/awaiting replacement/cancelled/withdrawn/completed; follow-up; corrected sent version | Verify household, prepare/send current letter, accept exact agreement or confirm replacement. Closure does not approve identity. | `followup-ui-recovery`, `followup-lost-response-after`, `withdraw-sequence-ui`, `withdraw-followup-letter-ui`. |
| Agreement | Sent alone keeps hold; accepted agreement clears only identity; old version rejected; revoked grant | Use current sent artifact; retry retained file after restoring authorized access. Corrected invoice remains outstanding. | `agreement-grant-revoked-after`, `withdrawn-final.json`. |
| Replacement | Wrong ID 409; changed phone without note 400; valid replacement | Preserve old invoice; current corrected invoice becomes matched; explicit link continues there. | `replacement-confirm-ui`, `replacement-current-handoff`. |
| Payment | Draft/review/returned correction/review complete/awaiting scan/unsigned cancel-reuse/completed | Operations prepares; Head of Rural reviews facts; configured sign-off approver uploads. Completed cancellation 400. | Payment return/correction/generation/finality and policy UI results. |
| Identity to payment | Agreement/replacement/missing-ID correction/flag resolution/equal-ID variance together | All five reviewed and completed in one mixed payment for KES 222,500. Withdrawn follow-up then completed a separate payment. | `identity-payment-final.json`, `identity-payment-upload.json`, `payment-policy-ui-after`. |
| HB Action | Delay/not ready/installed/commissioned; invalid dates/order/premature commissioning; final lock | HB records readiness, installation, commissioning. Commissioned installation is read-only. | Earlier office lead and HB negatives. Administrative correction/reopen permutations not replayed here. |
| Access/stale request | Expired launch, revoked credit grant, revoked invoice/payment upload grant, stale revision | Refuse write, retain values/file, restore valid authority, retry. | Auth/grant recovery; agreement/payment revocation results. |
| Independent scope | Wrong group/branch/product; Operations scope plus separate Credit Analyst scope; Origination-only IT | Require a complete action-specific Portal grant. Other scope/app role did not authorize correction. | `scope-matrix`, `scope-authority-tuples`. |
| Publication | Canonical commit before Google; outage/dead letter/reviewed retry earlier; active/abandoned lease here | Retain saved data; executor skips live lease and reclaims expired lease. IT retry preserves failed history. | `lease-service-recovery`; earlier IT recovery/reconciliation. |
| Shell/forms | Earlier late response/offline/reconnect/reload/history; modal Cancel; 320/390/1280 widths here | Keep work, return to owning screen, display errors within current form. | `identity-sheet-layout-settled`; earlier shell captures. |

No conditional approval was newly created: that path is retired in current decision choices. Historical `conditions_pending`/`legacy` handling was inspected in code, not represented as a newly executed journey. Draft/failed parser internals and every receipt-status combination likewise are not separately certified by the invoice row.

## Connected workflows and finality

Three deferred cases retained their UUIDs, received fresh source/visit evidence, new credit/final approvals and reached the order queue. Opening a recovery screen alone did not count as recovery.

Sending a household letter did not release payment eligibility. Accepted agreement cleared only identity; corrected invoice remained outstanding. Wrong-ID replacement and unexplained changed phone were rejected. Valid replacement superseded its source and became current. These recovery types then passed review in one five-case payment.

Unsigned cancellation released Payment #2. A new workspace UUID reused that number, retained new review/workbook evidence and completed after its accepted scan. Completed cancellation returned 400. The withdrawn-follow-up case separately completed Payment #3 after accepting its current version-2 agreement. Old letters could not clear that hold.

Lease setup explicitly simulated an abandoned worker in the isolated fixture. The native bounded executor did zero work during its live 120-second lease. After that fixture lease was moved past expiry, it reclaimed the operation, replaced its attempt token and completed attempt two. This used local review control to execute the native service, not a production worker kill or deployed scheduler check.

## Final read-only reconciliation

`final-state.json` records:

- 73 new lost-response cohort cases, all projected to the local register; no duplicate projected Case ID in either case register.
- No pending/running/retryable case-publication operations at the final read.
- No duplicate open corrections/pending reviews, or pending review attached to a closed correction.
- Original identity flag and later verification both retained. One deliberately unfinished correction remains pending with its recovery action visible.
- Pre-fix counterexample retained: two unlinked synthetic cases hold `96550001`. Protected later claims are unique across different customers; the same-customer/two-unit control is shared intentionally. No automatic historical/production duplicate repair.
- Retained order and signed-scan byte hashes match. All 104 local Drive blobs match their hashes. Prior completed bulk evidence remains.

The gallery preserves failures/intermediate states. Driver mistakes are not product defects or successful verification: an initial agreement probe used the wrong confirmation value, a lease probe omitted its required operation ID, and a payment observation cancelled before checking upload success. The latter cancelled an unsigned synthetic batch after a genuine policy rejection. History remains; the successor reused the released number, was reviewed and completed. Later observations establish the actual outcomes. Initial modal captures were recaptured after opening animation settled.

The manifest binds final source/artifact hashes. Evidence is local/ignored: copy its directory when sharing outside this checkout. This report and the UI source record are repository files.

## Remaining boundaries

- The named recovery gaps and state families were reviewed; the unbounded cross-product of states, historical inconsistencies and request orderings was not. Every late-worker completion race, household/payment edit interleaving, administrative HB reopen path and historical conditional approval was not replayed.
- Bulk/Excel evidence of 252 cases per order and 61 per payment belongs to the earlier review. It was not repeated here and does not establish production throughput. The earlier large-order SQL count and 20-file invoice time-budget limitation remain.
- No physical Telegram/camera/GPS, screen reader, real Google quotas/permissions, email/SMS, scheduled report delivery, deployment or multiple deployed workers were checked. Local bridge refresh is not physical Telegram relaunch.
- Synthetic scans establish binding/retention/finality, not real signatures/stamps, completeness or attestation quality.
- Existing shell/components are reused. [UI source record](ui-standard/reviews/2026-10-29-portal-state-recovery.md). Captures do not approve visual baselines or Phase 6 migration.
