# Known Gaps and Verified Workarounds

## Scheduled Portal email rollout - 5 October 2026

Resend delivery is disabled by default. Local checks use synthetic cases and
mocked provider responses; they do not establish verified-domain DNS, inbox
delivery, production webhook reachability or scheduler operation. Configure
and verify these using [the operator steps](report_delivery/README.md) before
enabling sending. PostgreSQL lease/isolation parity has not been run in this
session because no local `TEST_DATABASE_URL` was configured; use the existing
PostgreSQL test runner before production rollout. No production migrations or
real report emails were sent.

## Complaints, TAT and Portal depth review - 3 October 2026

See [the focused implementation review](docs/miniapp-depth-review-2026-10-03.md)
for source locations, reproduction details, test selections and failure
classification. Python 3.12.10, the pinned Python dependencies, Playwright
1.62.1 and Chromium are now installed locally. This supersedes the initial
source assessment's unavailable-runtime limitation below.

- Reproduced a TAT report authorization defect: its queryset combines scopes
  from grants that do not authorize reports. Report access must retain the
  capability and scope of one complete eligible grant.
- Reproduced an empty Portal case queue for group-scoped staff even though
  individual case permission allows their owned case. The central queryset
  omits the group relation required by the generic scope resolver.
- Reproduced complaint file-selection loss after a failed finish-created
  upload, Pending cursor traversal dropping newer rows, and changed TAT retry
  payloads returning unchanged state as successful receipt replays.
- The full browser suite ran 186 tests: 185 passed and one stale Complaints
  report fixture failed. The fixture lacks the current report summary/module
  contract and assumes two chart slides; the current report has eight.
- Two broad isolated SQLite backend selections ran 960 tests. Initial results
  were 12 failure entries/6 errors/2 skips and 25 failure entries/3 errors/3
  skips. Two logging failures came from the diagnostic harness and passed after
  correcting it. Other failures/errors remain classified in the review.
  Selected complaint modules had no failure/error entries; their concurrency
  check was skipped. No PostgreSQL concurrency success is claimed.
- Four focused synthetic database reproductions and the additional Node
  finish-upload probe passed by asserting the observed defects. These are
  reproduction results, not evidence of fixes.
- System checks, migration drift, migration graph, architecture boundaries,
  dependency parity, Python compilation and package consistency pass. The
  official write inventory fails with 27 routes; environment-template parity
  fails with 116 entries; the dependency exception expired before audit runs.
- Local Node 26 is outside the repository's supported range, and Windows
  Pango is absent, so native WeasyPrint import/layout is not verified. No live
  Telegram/Google integration or production resource was changed.

## Cross-workflow source assessment — 3 October 2026

See [the codebase assessment](docs/codebase-review-2026-10-03.md) for the
reviewed commit, source evidence, functional map and priorities. This was an
analysis session; application behavior and production resources were not changed.

- Legacy message deduplication hashes sender/content/time without group context.
  Identical inputs in separate groups can share a globally unique processing
  key. No production incident was reproduced. Review the intended scope and
  historical retry compatibility before changing the key.
- Unparsed invoice pages can log a 300-character document-text preview. Avoid
  treating ordinary logs as sanitized evidence; review access/retention and
  replace content diagnostics in a separately scoped fix.
- Legacy deposit fallback parsing uses `float` before document preparation.
  Canonical product quotes use Decimal; this finding does not establish an
  incorrect payment. Review fallback normalization and output compatibility.
- Database catalogue/checker app-label lists do not cover all installed local
  apps. QA models are outside the checked-in catalogue, and the additional
  bounded-model metadata checks omit the installed extracted-app labels.
- Legacy unbound Telegram profiles can retain username-based initial binding
  without activation proof. Review eligible enrollments before changing the
  identity contract. Atomic rejection tests also deliberately retain no raw
  intake rows; clarify rejection-evidence policy separately from case creation.
- The dependency exception expired on 30 September. A supplemental source
  cross-check identified 28 write-route inventory candidates; the official
  Python checker and a fresh dependency audit were not run in this shell.
- Fresh JavaScript syntax checks passed for 91 files, all nine Node test groups
  passed, and all seven tracked Apps Scripts passed syntax checks. Python
  discovery was retried but found only Windows Store aliases. Playwright was
  unavailable. No fresh backend, browser, PostgreSQL, migration, restore or
  live-integration success is claimed.

## Portal shared controls verification - 2 October 2026

- The focused PostgreSQL inbox/dashboard suite passes all 18 tests; JavaScript
  syntax and all nine Node test commands pass. No migration is generated.
- All 77 Portal browser tests pass on the final implementation without
  updating baselines. Results: `test-results/portal-shared-controls-browser.txt`;
  database results: `test-results/portal-inbox-postgres-final.txt`.
- Full-shell visual fixtures use synthetic API responses, not a live Django
  page/Telegram session. Browser coverage checks mobile/desktop geometry and
  light/dark themes. Linux CI rendering and production behavior are not yet
  verified by this local Windows run.
- Reviewed synthetic visual baselines are SHA-256-pinned. The tracked-artifact
  audit cannot count these new files until they are added to Git. Separately,
  HEAD already has a logo hash mismatch: `jawabu-logo.png` is `23a08f62...`
  while the existing allowlist expects `06c1d7e3...`. This unrelated asset was
  neither replaced nor re-approved by this UI change.
- Inbox responses are paginated, but their scoped task list is assembled in
  memory before pagination. Very large workloads may warrant a separately
  measured server-side task-query optimization; no new persistent inbox model
  has been introduced here.

## Complaints unified history verification - 2 October 2026

- Fresh PostgreSQL run: 94 tests, 92 passed, two failures. The local ignored
  log is `test-results/complaint-history-postgres-fresh-final.txt`.
- `test_customer_id_is_digits_only_and_preserves_leading_zeroes` expects
  "numbers only" while the unchanged validator says "1 to 9 digits only".
- `test_compact_two_state_workspace_has_only_supported_actions` expects the
  old `[0-9]*` template pattern. HEAD already uses `[0-9]{1,9}`; later assertions
  also contain outdated input labels and asset versions. These unrelated tests
  were not weakened to obtain a green suite.
- Browser feedback/draft/voice/queue regression, nine Node groups, JavaScript
  syntax and migration checks passed. Screenshots were inspected. No live
  Telegram or Google integration was exercised.
- Old history without immutable affiliation evidence is labelled Staff, not
  guessed from current grants. Existing Sheet comment cells change format on
  their next successful synchronization, not through an automatic bulk rewrite.

## Portal compact controls verification - 2 October 2026

The focused document-signoff/payment PostgreSQL suite passed 77 tests using
synthetic data and mocked integrations. Scan replacements retain previous bytes
and preserve workflow progress; preview scope and removable-duplicate selection
have regression coverage. No production Google/Telegram integration was called.
The 59 selected browser tests passed, including compact finance layouts,
notification scrolling, phone links and nested navigation. Performance screenshots
were manually inspected at 320px after the compact-height correction.

The wider `core.tests_pipeline` PostgreSQL run is not green: 192 tests ran with
25 failures and one error. Evidence is in the local ignored artifact
`test-results/portal-pipeline-postgres.txt`. Failures include outdated-client 426
responses, stale shell assertions and invoice fixtures without official orders.
This pass has not independently reproduced those failures on unchanged HEAD;
do not classify all of them as unrelated or claim a full-repository pass.

Duplicate removal is operational soft deletion, not evidence erasure. Payment
receipt, payment-history and identity-change references remain protected. Real
Drive movement and dialler handoff inside Telegram still need deployment smoke tests.

## Portal engineering remediation — 2 October 2026

Local prevention/recovery changes cover EQ-01/02/03/04/05/07/08/09/10/12.
EQ-06 (invoice diagnostic privacy) and EQ-11 (broad refactor) were excluded by
the user and remain open. See the implementation table in
[the remediation plan](docs/portal-engineering-remediation-plan-2026-10-01.md).

Focused PostgreSQL verification now includes real separate-connection claims,
fresh migrations and a representative prior payment schema upgrade. The earlier
197-test PostgreSQL selection and final 199-test run passed.
The 134 browser tests and nine Node groups passed. These are scoped results,
not a full-repository pass. The interrupted coverage run has no completed
verdict; its replacement focused run completed with bounded-domain reporting
(22.52% overall, not full-suite coverage). A reviewed full-suite coverage
baseline is still absent, and working-tree changed-branch gaps remain recorded
in `remediation-working-tree-coverage.txt`.

Existing full-suite failures were reproduced on unchanged HEAD. The existing
unsafe Mini App route inventory gaps and the dependency exception that expired
on 30 September still block full CI. They were not waived. Supported Python
3.12/PostgreSQL 16 Linux CI execution, clean dependency installation, physical
Telegram behavior, hosted capacity and an isolated backup restore drill remain
release checks (local verification used Python 3.14/PostgreSQL 18 on Windows).

Request-assisted publication does not guarantee progress when all clients are
closed. Legacy invoice attempts with unknown Drive outcomes require reviewed
reconciliation, not blind resend. Windows PDF workers have parent-enforced
timeouts and render budgets, but not Linux `RLIMIT_AS` memory enforcement.
Drain old workers at rollout; no production repairs or Google writes were made.

## Portal usability and cross-workflow audit - 1-October-2026

The audit's identified product defects have local fixes: background publication
is non-blocking and timeout-bounded, payment reviews bind to payment facts,
commissioning chronology is enforced, payment/HB edits have unsaved-leave
protection, payment lists are paginated, and expanded names wrap. Final-review
null handling was also corrected. Historical payment review digests have not
been migrated or restored; affected old open reviews need an explicit new review.

See [the audit report](docs/portal-usability-workflow-audit-2026-10-01.md) for
reproductions, priorities and the repair evidence. The post-repair selection
passed 318 backend tests on isolated SQLite, 84 browser tests and all nine Node
test groups. The 51 local rendered-page samples had no document overflow or
page exceptions; targeted interactions confirmed timeout lease release and
preservation of a second unsaved payment comment. PostgreSQL parity is still
unverified because local test credentials were unavailable. Live Telegram,
Google integration and physical-device checks remain separate release checks;
these results are not a claim that the entire repository suite passed.

## TAT credit assessment first release - 18-September-2026

SPIN and Metropol reports are still produced manually outside this platform;
the platform governs their evidence, questions, responses, and decisions after
upload. The future engine job boundary is deliberately dormant. Gmail polling
uses scheduled command execution rather than push notifications. Enable
`SPIN_HARD_CUTOVER` only after the new migration, personal Gmail OAuth, existing
restricted media Drive folder, staff roles, and live-device smoke test pass.


## JBL Visit document capture - 14-September-2026

Client ID currently uses existing protected Portal media-view scope, not a new
ID-only permission. No role matrix was changed. Local captures survive Case
History inspection but not closing/reloading the app; recapture after a reload.
Camera framing does not certify legibility or that the two images are distinct
document sides; staff must review both before submitting.

Local Windows rendering was verified with WeasyPrint 68.0 and MSYS2 UCRT Pango,
using `WEASYPRINT_DLL_DIRECTORIES=C:\msys64\ucrt64\bin`. The focused test checks
actual one-page Client ID and two-page LAF PDFs, embedded image draw commands,
and deterministic retry output. Live Telegram camera behavior still requires
device validation before release.

## Portal validation scope - 14-September-2026

Case-inspection navigation is locally covered with intercepted browser tests,
including the actual Portal card controllers. Live Android/iOS Telegram device
validation remains an operator release check. A cold/reloaded case link cannot
recover in-memory search or an unfinished local attachment selection; its
visible/Telegram Back uses the allowed source route instead.

The older Django test
`JblPipelineApiTestCase.test_portal_requisition_generate_requires_a_revision_for_each_new_assignment`
targets the retired `/requisition-queue/generate/` path. With a current request
key it returns 426 before revision validation, rather than the old expected
428. It is not evidence for the current preview/finalize path. New inspection
tests verify captured revisions through preview, and a service test verifies
that a changed case cannot be assigned an order. Unrelated old generation
fixtures were not rewritten as part of this navigation change.

The full intercepted browser run passed 49/50 tests. Its unrelated Complaints
report test (`miniapp_flows.spec.js`, date_reported assertion) still expects
`01-09-26`, while the approved current UI renders `01-Sep-2026`. Complaint
formatting was not changed in this Portal-only work.

## Portal reporting v1 scope

The IT-only Portal reporting workspace is deliberately limited to live
`JawabuFarmerMaster` case data, a server-owned field catalogue, named safe
aggregate counts, in-app aggregate visualisations, and local XLSX export. It is not an
arbitrary query builder and currently has no cross-workflow customer joins,
PDF/print output, Drive/Sheets publishing, scheduled delivery, saved data
snapshots, or historical version-diff renderer. TAT, SPIN, Complaint Case and
raw message models are listed through a read-only relationship inventory only;
they must not be joined by name, phone, national ID, or another mutable identity
until a separate ADR, data-owner rule, and release approval exist.

## Free Render publication reliability

The free Render service has no durable worker process. Portal writes therefore
do not wait for Google Sheets or Drive before committing canonical Django
state. A still-open Mini App performs one bounded follow-up publication
attempt; pending work is retained in `IntegrationOperation` or the document
sync fields and resumes on a later relevant Portal visit. This is durable but
not a replacement for a dedicated worker: a Render background worker remains
the recommended future upgrade for guaranteed scheduled retries and alerting.

## Portal import staging is intentionally not a commit workflow

The IT-only Portal Imports screen parses, stores, and reviews FarmUp/SysUp
source files only. It does not expose the existing customer-commit routines.
A future commit workflow needs its own approved maker-checker decision,
explicit row selection, and separate release authorization. Until then, any
Drive archive marked `needs attention` remains retriable from the authorised
Imports screen or support tooling. Archives use their own Imports path beneath
the existing approved Shared Drive root and remain visible only to its
approved members.

## JBL visit evidence after a Telegram/WebView return

Portal restores the current JBL visit's text, date, location and GPS-fallback
reason while the same browser session remains available. Telegram/mobile
browsers do not permit selected `FileList` handles to be retained or restored,
so an officer who temporarily opens the media selector or another screen may
need to reselect the LAF and visit photo before completing the atomic request.
The server validates both categories before it uploads either one; it never
records a forwarded visit without the required evidence.

## Android PDF rendering inside Telegram

Telegram's Android WebView can render a protected image stream in the Portal,
but may display a blank panel for a PDF served through a blob iframe. The
Portal therefore renders the authorized PDF server-side as bounded page images
inside its client-media overlay. It does not use an external Drive link,
browser activity, or Google document viewer. Very large or unusually detailed
PDFs may be rejected for in-app preview and can be retried after a smaller scan
is uploaded through the normal evidence process.

## Pending JBL scheduling backfill

`backfill_jbl_schedule_status` is intentionally dry-run by default. It may be
reviewed locally/staging with `python manage.py backfill_jbl_schedule_status`.
Its `--apply` and `--revert-run` paths change canonical Django status only and
are not authorised for production use until a separate rollout approval.

## Personal notification delivery preferences

`UserMiniAppPreference.alert_mode` remains stored for backward compatibility,
but recipient-level Telegram delivery does not yet apply immediate, digest, or
quiet choices. The Mini Apps intentionally do not render that selector until a
delivery worker enforces the shared mandatory-alert catalogue. Assignment,
approval, security, and overdue-breach alerts are not suppressible.

## Sentry production verification

The Django SDK is pinned, installed, initialized from `SENTRY_DSN`, and tested
with a synthetic DSN. Render's strict production-readiness gate passed on
31-July-2026 after Sentry configuration. The remaining operator verification
is a safe staging synthetic exception: confirm its alert rule fires and that
the event contains no customer/staff payload.

## Business Administrator role cutover

`core.0088_business_admin_role_cutover` was applied in production by the
31-July-2026 recorded migration baseline. It renames effective Portal/TAT/SPIN workflow access from legacy
`ADMIN` to `BUSINESS_ADMIN`, without rewriting historical audit evidence. Run
`python manage.py check_business_admin_cutover --strict` before the production
migration; it blocks unresolved pending legacy access-policy requests or
duplicate effective grant scopes. Capability seed-row overlaps are merged by
preserving the existing allow/deny policy. To undo after a controlled release, run
`python manage.py migrate core 0087_repair_tat_stage_target_snapshot_backfill`;
the reverse migration stops if a legacy-role collision would make rollback
ambiguous.

## Access-control checker bootstrap

`core.0090_accesscontrolcheckerassignment` is accepted for code merge and
local/staging validation only. It records independent checker appointments and
backfills legacy approver-group members without changing Users, Access Grants,
workflow state, financial records, or Mini App access. Before any approved
production rollback, export checker appointment and compliance-audit evidence,
then run `python manage.py migrate core 0089_portalcaseworkspace_portalsavedview`.

## Portal private workspace hold

`core.0091_pause_portal_workspace_to_it` is accepted for code merge and
local/staging validation only. It preserves existing private saved views, pins,
and recents. The Portal Mini App does not render any workspace control for any
role, including IT. The retained endpoint remains IT-gated only for controlled
technical validation; it is not a staff-facing feature. The migration
increments the policy version when it creates policy rows, forcing connected
Mini Apps to refresh permissions on their next metadata poll. It does not
alter customer cases, financial values, Drive/Sheets, or workspace records.

Do not roll back application code to re-open this feature. A future UI
re-enable requires an explicitly approved rollout and the existing capability
review; it must preserve the IT server-side gate. The migration's reverse is
intentionally a no-op so policy and compliance evidence remain retained.

## Portal workspace migration and retention

`core.0089_portalcaseworkspace_portalsavedview` was applied in production by
the 31-July-2026 recorded migration baseline. It adds only private, user-owned saved-view and case-workspace
metadata; it never changes Jawabu cases, workflow state, financial values, or
audit evidence. Django live scope checks hide inaccessible/closed pins
immediately. Until an authorised scheduler is configured, an operator may run
the read-only preview `python manage.py prune_portal_workspace`, then the
explicitly approved `python manage.py prune_portal_workspace --apply` on the
agreed daily cadence to release pins unavailable for 30 days and remove
un-pinned recent metadata older than 90 days. To undo after an approved
release, run:

```powershell
python manage.py migrate core 0088_business_admin_role_cutover
```

The reverse migration drops only the two private workspace tables; it does not
alter case, workflow, financial, or audit tables.

## TAT Settings migration

`core.0085_tattrackercase_stage_target_snapshots_and_more`,
`core.0086_seed_tat_target_snapshots`, and
`core.0087_repair_tat_stage_target_snapshot_backfill` were applied in
production by the 31-July-2026 recorded migration baseline. They add user-owned Mini App
preferences, maker-checker TAT setting proposals, escalation-rule storage, and
target snapshots for active stages. Before any rollback, export approved
configuration requests for audit evidence. To undo the schema locally or after
an approved release, run `python manage.py migrate core 0084_integrationcircuitstate_integrationoperation`.

## Mini App notification preferences

TAT stores an individual user's immediate/daily-digest/quiet preference for
non-critical alerts. Durable TAT action tasks now support shadow evaluation,
existing group alerts, and private delivery with retry and ranked backup
escalation. Production private delivery still requires the approved one-minute
platform scheduler and must pass `check_tat_production_readiness --strict`.
Legacy non-task TAT stage alerts may still be posted to the
configured shared Telegram group, not to individual recipients, so this
preference does not suppress, digest, or reroute those group alerts yet. A
recipient-level notification delivery ledger and scheduled business-day digest
job must be approved and implemented before enabling that behavior. Mandatory
assignment, security, approval, and overdue-breach alerts must remain outside
personal suppression in that future design.

## Bounded integration reliability

`core.0084_integrationcircuitstate_integrationoperation` was applied in
production by the 31-July-2026 recorded migration baseline. It records redacted external
operation/circuit state only; it does not start Celery, Redis, a scheduler, or
any automatic retry worker. Operators can run `probe_integrations` without
side effects for a configuration dry-run. `--execute` makes real read-only
metadata calls and must be an explicitly authorised maintenance action.

The current release routes shared Google Sheets batch writes, Drive uploads,
and Telegram launcher publishing through the durable register. Other legacy
direct outbound calls remain outside it and are listed in `TECH_DEBT.md`; they
must be migrated one bounded workflow at a time with replay tests. Strict Mini
App retry-key enforcement remains disabled until all refreshed cached clients
are verified in real Telegram clients. Do not set
`REQUIRE_MINIAPP_IDEMPOTENCY_KEY=True` during a production release without
that explicit verification and approval.

Last reviewed: 27-August-2026

## Compliance audit evidence

`core.0083_complianceauditchainstate_complianceauditcheckpoint_and_more` is
included in the pending release worktree but is not authorised for production
application. It adds an
append-only cross-workflow ledger, a PostgreSQL application-role immutability
trigger, read-only Admin investigation/export tools, and explicitly generated
daily checkpoint records. PostgreSQL database owners can still alter database
objects, so the ledger is tamper-evident rather than an absolute guarantee.

No automated retention deletion is implemented: every new compliance event is
on legal hold until JBL approves a legally validated retention schedule. No
mailbox delivery, scheduler, or scheduled sampling is enabled. Before enabling
those operations, approve a controlled recipient and mail configuration, test
the PostgreSQL trigger in staging, name an evidence owner, and record a tested
response path for failed delivery. Use `verify_compliance_audit --strict` and
`sample_compliance_audit --strict` only as supervised read-only checks.

## Sheet/Drive publication governance

`core.0082_sheet_register_governance` is committed but is not authorised for
production application. It adds local, publication-only Sheet contracts and
audit evidence; it does not alter Google Sheets/Drive or re-enable inbound
Sheet imports. Before relying on strict audit results, an authorised operator
must review each target tab and create contracts with
`python manage.py seed_sheet_register_contracts` (dry run) followed by the
explicit `--apply` only after the layout is confirmed. Run
`python manage.py audit_sheet_registers --strict` and
`python manage.py audit_drive_permissions --strict` as supervised read-only
checks. No scheduled audit, alert routing, automatic Drive-permission repair,
or periodic Sheets snapshot export is introduced; those need approved
recipients, a durable scheduler, rate-limit handling, and a retention design.

The TAT duplicate repair now verifies and re-publishes each linked survivor,
but it still deletes rows from the chosen live Sheet when `--apply` is used.
Use a copied Sheet first and keep the resulting `LiveSheetRecordChange` audit
evidence. A failed post-delete verification must be investigated manually; do
not rerun a destructive cleanup blindly.

## Portal approval controls and visit evidence

`core.0081_jawabuapprovalcondition_jawabuapprovaldelegation_and_more` is
committed but is not authorised for production application. Approval records,
conditions, temporary delegation, direct case-media links, and retrieval audit
are live only after the approved migration. Legacy farmer decisions and media
remain visible through compatibility reads; they are not retrospectively
asserted to meet the new evidence or authority controls.

The release deliberately does not delete Drive media. Run
`python manage.py audit_jawabu_visit_media --strict` to report unlinked
controlled evidence; it never changes attachments or Drive. Candidate review
and a separately approved retention/deletion policy are still required.
In-app SLA escalation remains an operational signal;
automatic Telegram/SMS/email delivery requires approved recipients, retry
handling, and a scheduled production job.

## Cross-workflow customer data cleanup

The governed customer-resolution rollout currently covers active Jawabu cases
and staged `/sysup` system exports. Complaint Cases, TAT, and SPIN retain
their present records and validations until a separately approved migration
maps their identity fields into the same customer-resolution service. Run
`python manage.py audit_jawabu_data_quality --strict` before a controlled
Jawabu cleanup; the command is read-only and must not be mistaken for a merge
or backfill tool.

## Telegram WebView printing

Telegram's mobile WebView does not provide a dependable browser print stack;
live canvas/browser print previews can be blank. The supported workflow is:
preview the document values in-app, then use **Open Excel** to download/open
the generated workbook in a proper spreadsheet application for printing. Do
not reintroduce `window.print()` as a production document workflow without a
new verified Telegram-client test and ADR.

## Physical document signing

Requisitions and final payment schedules support retention of a physically
signed-and-stamped PDF/JPG/PNG scan. The system records the authorised staff
attestation, source-workbook hash, scan hash, and Drive outcome; it does **not**
verify handwritten signatures, stamps, or legal e-signature validity. The
external e-signature integration remains deliberately on hold. Existing
documents without locally retained source workbook bytes are legacy records and
must be regenerated before a new traceable physical sign-off can be attached.

## Mini App recovery drafts

`core.0072_miniapp_drafts` is applied in the current production migration
baseline. Recovery requires verified Telegram identity and the form's existing
scoped authorization; it cannot promise an offline save. Offline edits remain
in the current open screen and become durable only after the UI shows that the
server saved the draft. Attachments are intentionally excluded.

Required verification before release:

1. A real Telegram mobile test for Portal JBL Visit, SPIN, FCA, FarmUp, and
   System Export draft restore, conflict behaviour, expiration, and attachment
   re-selection.
2. A future form must reuse the shared server draft service and enforce its
   own capability/scope before saving any field state.

### Order Approval browser draft remains

During the draft audit, `core/templates/order_approval/form.html` was found to
retain its own browser-local recovery draft. It was not converted in this
change because its form-token/Telegram authorization path and customer/media
field boundary need a dedicated review before server persistence is introduced.
Do not copy that local-storage pattern into another Mini App. A follow-up must
reuse the `MiniAppDraft` service only after it has a capability/scoped-token
authorization test and confirms attachments stay out of the draft.

## Workflow SLA delivery

The workflow-integrity command records or previews overdue-stage escalations
without sending Telegram messages by default. This is intentional: automatic
notification delivery needs approved recipient routing, rate-limit/backoff
handling, and an explicitly approved Render schedule. Until that operating
change is approved, run the command in dry-run mode and use the resulting
pending escalation records for supervised follow-up.

## Business-calendar and TAT trend operations

Official TAT/SLA time now excludes only dates entered and kept active in Django
Admin under **Business calendar holidays**. The platform deliberately does not
download Kenya public holidays from an external source, so an authorised
operator must confirm the year’s dates before relying on SLA reporting. Run
`python manage.py snapshot_workflow_tat --json` to review the current
projection; `--apply` is an internal, idempotent database write and still
needs an explicitly approved scheduler before it becomes a routine job.
Individual trend rows are emitted only where a workflow has recorded a named
responsible actor. They must be interpreted with the recorded branch, role,
product and paused/deferred-time context; absent attribution stays
role/branch-level rather than being guessed.

## Backup and recovery evidence

The production runbook requires Render daily PostgreSQL backups and quarterly
restore drills, but this repository contains no recorded successful drill or
measured recovery time. Treat the following as operating targets, **not proven
service levels**, until a drill is recorded:

| Store | RPO target | RTO target | Evidence required |
|---|---:|---:|---|
| PostgreSQL | 24 hours | 4 hours | Restore a current backup to staging and record elapsed time. |
| Google Sheets / Drive | 24 hours | 8 hours | Restore a copied/versioned spreadsheet or Drive document to staging and record the result. |

No production data reset, destructive Sheet cleanup, or migration is routine
until the relevant recovery path has been checked.

## Origination separation verification (4 October 2026)

See [the ownership and reference release notes](docs/origination-separation-release.md)
for the independent grant cutover, migration sequence and rollback limits.
Local verification uses synthetic SQLite databases with external network access
blocked. PostgreSQL table/column comments require the wired PostgreSQL CI job
or staging verification; Windows also lacks the native Pango libraries needed
for a full local WeasyPrint integration run.

Six existing Origination tests fail on the unchanged `092ead8` baseline as well
as the separated implementation: three legacy template-add presentation tests,
the former product-bound template upload test, the supporting-document activation
fixture with an empty form contract, and the packet-demo application fixture
without a governed product version. These remain separate from the ownership
change and must be reconciled with the current document catalogue contract.
The repository also retains pre-existing broad gate failures in the Portal
Ruff check, Mini App write inventory, environment parity and dependency exception
expiry. A passing focused check does not establish a passing full release gate.
