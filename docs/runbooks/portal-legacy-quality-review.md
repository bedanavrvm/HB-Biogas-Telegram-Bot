# Historical Portal identity and source review

## Verified changeover completion - 11 November 2026

After explicit approval, release `3812279c` was merged and deployed. The native
completion service closed the Master Data review, retaining two missing-name
records and one potential identical unit repeat as three unimported exceptions.
Both initial uploads are complete and unfrozen. All 4,230 previously synced
cases remain: 4,074 Master Data and 156 Eco-conserve. The administrative import
hold is cleared, including new/non-case admission; normal workflow permissions,
deposit eligibility and validation still apply.

The production transaction verified unchanged complete case hashes, all 4,077
Master Data source drafts, source workbook chunks and counterpart uploads. It
recorded one compliance event and the exact retained-exception manifest, with
no case, financial, identity, Google or Drive writes. Native pre/post-deploy
checks found no readiness errors or pending migrations; both public health
endpoints returned 200. No schema, configuration, dependency, permission or
browser-admission change was required. The separate 90 November candidates
remain outside this operation. Private evidence retains approval, source-bound
jobs, a source/case snapshot, completion receipt and readback results.
Independent read-only verification confirms both complete/unfrozen uploads,
zero blocked cases, one completion audit and unchanged case, draft, workbook,
import-checkpoint and publication-receipt fingerprints.

## Verified production result — 10 November 2026

After explicit approval, commit `1953568f` was merged and deployed. The native
run imported 239 Master Data rows and three Eco-conserve rows. All 242 have
verified publication receipts; all 3,988 previous cases and Sheet rows retain
their pre-import values. The total is 4,230 cases. The new cases retain 187
missing-ID warnings, 55 potential-additional-unit findings without confirmed
customer links, and 32 source/contact findings. Two unnamed records and one
identical unit repeat remain held. The separate 90 November candidates were
not imported by this operation.

Eco-conserve initially stopped because its saved 55-column checkpoint predated
the reviewed HB Deposit Date addition. Read-only header review confirmed exactly
that one appended column, with no missing or reordered existing headers. An
audited native rescan refreshed UUID bindings and empty-row allocation, retained
all old receipts, and published only the three saved cases. Eco-conserve is
complete; Master Data remains available with its three explicit holds.

Pre/post-deploy checks had no readiness errors or pending migrations; 118 focused
PostgreSQL tests passed before deployment. Private completion evidence retains
the approved plan, case/Sheet checks and backup receipts. The full database
export connection failed; the verified prior full archive plus a fresh,
transaction-consistent snapshot of Portal models/import evidence/number registers
and exact pre-write Sheet cells were retained. No destructive reset was used.

This procedure covers Master Data and Eco-conserve only. Django remains the
workflow source of truth. Private workbooks, identities and case-level decisions
belong in the retained private review evidence, never this repository.

## Closing initial loading with retained source exceptions

Verified imported cases can be used while review remains partial, but a frozen
initial upload still blocks owner-wide/new-case actions. A finished sync is not
the same as closing that administrative hold. The 11 November live audit found
all 4,230 cases synced, Eco-conserve complete and Master Data still frozen with
three unimported exceptions: two missing names and one potential identical unit
repeat. No case-specific write was blocked; non-case actions remained blocked.

The `complete_review` upload action closes a ready initial import
without creating, deleting or changing cases or Google rows. Existing whole-group
Portal IT authority and the normal upload lease are required. Every imported
draft must have a committed, publication-ready case and a verified staff-reference
receipt matching the saved Sheet/register binding. Outstanding selections,
uncertain write plans, changed source facts, stale revisions, failed receipts and
cross-register/duplicate bindings stop completion.
Original verified receipts may predate the later optional case-revision tag;
their named register, immutable case binding and digest remain mandatory. A
present revision must be valid and cannot exceed the case's current revision.

POST to the existing `/api/portal/legacy/uploads/<upload_id>/complete_review/`
with the current `revision`, stable `request_id`, original `source_sheet` and an
`exceptions` list covering exactly every unimported draft. Each entry needs its
`id`, a nonblank review `reason` and `values_sha256` produced by
`portal_legacy.completion.values_digest`. Retain this manifest privately. The
service remains available as `complete_review(upload, actor=..., access=...,
expected_revision=..., request_key=..., exceptions=...)` inside
`importer.leased(upload)` for a reviewed operator run.

Completion retains drafts, original workbook bytes, source rows, receipts and
case history. It records one transactional compliance event and a private
`state.review_completion` receipt, sets only that upload to complete and releases
its hold. Payload still reports the exceptions as not imported. A closed upload
cannot select, edit or commit them; any later intake requires separate reviewed
handling. The same request and facts replay without another audit or revision;
different facts cannot reuse the completion key. Other register holds remain.

Before execution, verify the exact source/revision manifest and native receipts;
after execution, verify no frozen cutover remains for this operation and compare
case, source, exception and receipt fingerprints. No Google write is needed.
Never delete the held drafts or blindly flip `frozen` to bypass these checks.
Code rollback requires no migration and does not automatically reopen a completed
review. Preserve its audit and use the owning reviewed recovery if evidence is
later disputed. The exact 11 November completion was explicitly approved and
applied as recorded above; later operations require their own reviewed scope.

## Import semantics

Blank historical National IDs are permitted by initial legacy loading. New
Portal intake requirements do not change. A blank-ID historical case receives a
`national_id / review_required` warning and no inferred customer identity.

The existing signed, scoped import selection accepts
`potential_additional_unit: true` with an explanatory `note`. Commit requires a
valid reported ID and rejects combining this choice with an existing-case link.
The reported ID remains on the historical case, but customer linkage and
customer-unit allocation are deferred. It is not a confirmed second unit.
The import event retains the selection and note. Replaying a committed source
row never creates another case, event or unit.

The selection may also include up to 40 distinct `review_flags` with `field`,
`code` and `message`. Only `legacy_source_conflict` is accepted through this
input; `potential_additional_unit` is generated by the explicit unit selection.
Messages must be nonblank and at most 2,000 characters. No model fields, roles
or capabilities can be assigned through a flag. Identity/scope edits invalidate
the prior review selection, flags and approval.

Normal validation preserves these two manual historical-review codes. Case 360
uses its existing Data Quality tab and the quality report reads the findings
without writing. Portal IT verifies the source and hands a documented resolution
to an authorized Django administrator through the existing data-quality issue
resolution workflow. Correcting a blank ID clears its computed missing-ID
warning; it does not automatically resolve an additional-unit finding or merge
customers.

## Source comparison policy

- Match retained units through normalized full name plus phone, or several
  independent unit facts. Source row numbers are provenance, not identity.
  Order numbers can cover several units and are not unique customer keys.
- Retain reviewed initial cleaning when November repeats an old raw spelling or
  supplies an unsupported replacement. Blank updates never erase known values.
- Keep HB and JBL receipts separate. Do not replace reviewed financial amounts
  solely because a later workbook differs, derive a balancing receipt, or
  assign shifted Eco-conserve fields without source evidence.
- Preserve known physical completion and coherent chronology. Record conflicting
  dates for review without inventing a date, decision actor, signature or HB
  handover. Credit Decision remains Legacy until actual native activity.
- An exact repeat of identity, contacts and unit facts needs evidence of a
  distinct unit before another operational case is created.

## Explicit historical pre-visit statuses

An explicit JBL/Jawabu To Schedule Visit, Awaiting JBL Visit or Pending Minimum
Deposit outcome can establish `jbl_visit` during initial loading when a valid,
nonfuture HBG visit/sign date is present. A recorded JBL visit, downstream
stage/decision, order/payment reference, installation/commissioning evidence or
conflicting comment keeps the source from creating a new visit. Valid later
decisions and fulfilment facts retain their existing precedence. Blank status
or unqualified approval never establishes a visit by absence of a JBL date.

Queue membership and deposit eligibility are distinct. Blank/zero HB deposits
and totals below KES 5,000 appear under Deposit Pending, with visit logging
disabled. Sufficient recorded HB deposits appear under Awaiting Visit. JBL
receipts never satisfy the HB deposit gate. Credit Decision stays Legacy until
actual native visit/credit activity; no historical decision actor/date is added.

For already committed cases, do not rerun import, modify source cells or include
all Legacy review cases in the queue. After approval of the exact reviewed
selection, use `portal_legacy.services.confirm_stage` with `state='jbl_visit'`,
the current LegacyRow revision, an explanatory source-review note, the current
authorized Portal actor/access, and a stable per-case request key. Recheck the
case revision and all decision/physical facts under locks before the call. This
records a current review event and reserves normal UUID-bound Sheet publication;
it does not claim a historical visit or credit decision occurred. Replaying the
same request must retain one confirmation and one pipeline event.

Retain private before/after canonical fields, source hashes, revisions and exact
Sheet cells. Keep unrelated fields, identity findings and held imports unchanged;
resume native publication with its existing freshness checks and pacing, then
verify the queue filters and Legacy credit labels independently. Code rollback
does not undo reviewed stage confirmations. If evidence changes or a later staff
action exists, stop and use the owning audited correction workflow; never
delete cases or erase history as rollback.

The approved 10 November pre-visit repair is complete at release `1bf68903`.
Seven existing Master Data cases received one audited continuation confirmation
and one native publication each. Independent read-only checks confirm eight
Deposit Pending and zero Awaiting Visit cases, all 4,230 Sheet credit labels
LEGACY, unchanged protected target fields/findings and unchanged full hashes on
the other 4,223 cases. Pipeline status and publication timestamps changed on the
seven Sheet rows; dates/amounts on five rows changed scalar type with exactly
equal calendar dates and numeric values. Google throttled the last update; native
backoff completed all seven publication operations without resetting an operation
or creating another case/event. The operator job's strict final cell-type check
stopped after publication; independent read-only verification resolved the type
differences and completed acceptance, retaining the original failed job receipt.
Three completed-visit cases and the already confirmed queue case
were excluded. The separate November candidates and three initial source holds
remain outside this operation. No migration, configuration or permission change
was needed; both pre/post-deploy readiness and public health checks passed.

Within the separately reviewed November additive candidates, 16 have supported
pre-visit source evidence and 14 have at least KES 5,000 recorded HB deposit.
They are not existing-case stage corrections. Review exact unit identity and
approve their separate additive intake before importing; never turn an unrelated
existing case into one of these candidates to fill the visit queue.

## Prepared review and evidence

The private 10 November review has 245 initial holds. The reviewed native plan
selects 239 Master Data rows and three Eco-conserve rows: 187 missing-ID rows
and 55 potential additional units. Two unnamed initial rows and one identical
unit repeat remain held. Supported November descriptive/reference evidence is
used for 49 rows; no reviewed financial amount is replaced.

An isolated PostgreSQL production-copy rehearsal created exactly 242 cases and
verified exactly 242 native Sheet receipts using a substituted Google transport.
All 3,988 existing canonical cases retained their complete field hashes, existing
Sheet cells were unchanged, and replay retained one case/import event per source
row. The selected cases retain 187 missing-ID findings, 55 potential-unit
findings and 32 source/contact findings. Physical/status chronology still uses
the existing server rules. This is rehearsal evidence, not live publication.

Of 330 previously held November rows, 240 correlate with initial source rows.
Ninety are reviewed separately: 81 cleaned candidates for additive intake and
nine evidence holds. Those rows are not part of the 242-row initial plan and
must never be loaded through a replacement/cleanup operation. A cleaned
candidate is not proof that a unit is new.

The private workbook records decisions, original/updated/chosen field values,
matching evidence, retained warnings and the exact held rows. It is a focused
review artifact, not a full workbook replacement. The original workbook and
earlier sealed comparison remain unchanged.

## Production execution

1. Obtain explicit approval for the exact tested release and 242-row historical
   import. Repository `AGENTS.md` requires this for production deployment and
   operations affecting customer financial data.
2. Recheck the deployed commit, release checks, unapplied migrations and backup
   evidence. This patch requires no migration or configuration change. Retain
   the existing browser configuration and independent workflow authority.
3. Verify each selected draft's retained source hash, original-value fingerprint,
   upload, owner and register. Stop for changed source/case evidence. Use the
   existing active scoped actor and current importer authorization.
4. Apply only reviewed changes through native `importer.edit`, select bounded
   batches, and commit through `importer.commit_step` under its existing lease.
   Retain the original source, correction audit and review-plan digest. Never
   repeat cleanup, replacement or source deletion.
5. Resume native `row_sync` with the existing pacing, retries and readback
   verification. Bind by immutable case UUID; preserve existing receipts and all
   nonselected rows. Do not claim completion while receipts remain outstanding.
6. Verify exactly 242 added cases and receipts, Legacy credit labels, absent
   fabricated actors/dates, visible durable flags, unchanged existing-case
   hashes and three remaining initial holds. Eco-conserve may finish its
   register while Master Data retains those holds.

## Validation and rollback

Focused PostgreSQL tests cover signed authorization, denial, invalid selections,
missing-ID warnings, unconfirmed-unit identity separation, persistence, explicit
resolution, correction invalidation, idempotency, existing import/update/sync
behavior and Sheet labels. Run the normal source lint and Django checks too.

Code rollback reverts this release's commit; no schema reversal is needed.
Never delete imported operational cases as an automatic rollback. Keep private
source, audit and publication receipts, stop further selected commits, and use
the owning audited correction workflow after assessing any later staff actions.
