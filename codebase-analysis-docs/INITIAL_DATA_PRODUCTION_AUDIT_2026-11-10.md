# Production initial-data audit ? 10 November 2026 (UTC)

The initial production inspection used PostgreSQL transactions with transaction_read_only=on. The subsequent deployment and bounded publication recovery were explicitly authorized by the user and are recorded below. Outstanding initial-import rows remain under review.

The audited production deployment was commit b84433a60f34a78d64973562c3df1fc124df0352 on main. The source inspected and tested is the isolated checkout C:\Users\be\AppData\Local\Temp\hb-production-analysis-oav9ufcb. The user's original checkout is an older Platform-Interdependence branch; the production fix was built directly on the deployed main commit.

## What production actually contains

| Register | Staged source rows | Canonical cases | Verified initial Sheet receipts | Awaiting initial sync | Not imported | Saved phase | Hold |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| Master Data | 4,077 | 3,827 | 3,827 | 0 | 250 | ready | frozen |
| Eco-conserve | 156 | 153 | 153 | 0 | 3 | ready | frozen |
| Total | 4,233 | 3,980 | 3,980 | 0 | 253 | | |

Both imports have completed their cleanup step, have row_sync.stage=done, and have no saved initial-sync error. All 3,980 committed LegacyRows have publication_ready=True. Each has a verified receipt using the staff-reference format.

The live workbook independently contains 3,827 Master Data and 153 Eco-conserve cases. Every populated Portal row carries a valid UUID in Master Record ID and a JBL staff reference in Case ID. No duplicate UUIDs were found across the two tabs.

PortalMaintenanceState is live, and Master Data sync is enabled for the correct spreadsheet. Maintenance mode is not the current blocker.

## Initial import versus later publication

The initial importer and ordinary Portal publisher are separate paths.

1. The importer retains the original workbook, mapping, source rows, selected proposals and audit history.
2. Committing creates canonical Django cases and retained LegacyRow provenance. Historical decisions, actors and dates are not manufactured to replay the modern workflow.
3. Initial row sync matches immutable identity, writes bounded batches, reads them back and saves a verified receipt.
4. Verified cases can then use ordinary case actions even while other rows remain unimported.
5. Later case changes save to Django and reserve IntegrationOperation publication work. The visible Sheet is a projection, not the authoritative workflow state.
6. Later workbook corrections use Update Existing Cases, separately for Master Data and Eco-conserve. Starting another initial import is not the recovery path for these 3,980 cases.

A verified initial receipt proves initial publication. It does not prove that every later change has reached Google.

## Confirmed ordinary-publication defect

Production retains 25 failed jawabu_master_publish operations affecting 14 existing cases. All have the same saved verification detail: the selected Master Data row changed before publication. Eleven older failures were classified as network; fourteen use sheet_row_changed.

Every affected case has a different original source-row number from its verified destination-row number. None has a successful normal-publication row pointer. Consequently, the publisher must locate its UUID through a whole-sheet read. A fresh read of the supplied Sheet, matched using the saved receipt row numbers, confirmed that all 14 affected rows have 10 trailing blank cells: 56 headers, with the last populated value at column 46. The 111 older successful ordinary-publication operations refer to cases no longer in the current canonical case table.

The pinned gspread 6.0.2 client returns:
- get_all_values(): rectangular rows padded with trailing empty strings;
- row_values(): a row with trailing empty cells omitted.

The audited b84433a6 version of core/services/jawabu_pipeline.py compared those lists directly before writing. Identical populated cells could therefore fail the stale-row guard simply because the list widths differed.

This was reproduced offline with the real pinned Google client and the actual inner Portal publication function. The proposed comparison pads only absent trailing cells during comparison. Existing cell positions and nonempty changes remain significant.

The fix is commit 353f831fb3d630afabbd258d11053c4dd9e5630b, built on branch fix/portal-status-sheet-sync. The exported assets/PORTAL_LEGACY_ROW_PADDING.patch includes the row-comparison correction, signed workflow regressions, adjacent test-fixture corrections and changelog. The user approved deployment and retries for the 14 affected publications. The change requires no migration, new package, permission change or Sheet-header change.

The authorized recovery below retried only the 14 affected publications. Exhausted operations are not automatically revived merely by loading new code. Recovery preserved failure history and did not replay the underlying business actions.

## Why the import sessions still matter

The 253 remaining rows are unapproved/uncommitted, not pending Google writes. They are not merely empty worksheet formatting: 251 have customer names, and many are missing an ID. The saved proposals include 12 warnings across the two registers, principally historical chronology and incomplete-contact checks.

row_sync only marks an import complete and releases its hold when no unimported drafts remain. These sessions therefore remain frozen.

The fence correctly releases verified existing cases. However, non-case writes and unresolved targets retain the administrative hold. In particular, the production flags and request-admission code show that new lead creation and owner-wide operations remain blocked even though all selected cases synced successfully. This conclusion comes from the live flags and source guard; no production write was submitted to demonstrate it.

Do not toggle frozen in SQL, delete retained drafts, or import unreviewed rows merely to clear the hold. The remaining rows need an explicit business disposition: review/import the intended cases, or implement a reviewed close-with-exclusions operation retaining their source evidence. The current started-cutover cancellation path does not provide that finalization.

## Current operational positions

Django currently has:
- 2,605 commissioned cases and 4 installation-closed cases;
- 212 HB actions still open or awaiting commissioning;
- 144 ordered legacy cases without an HB action, needing handover confirmation;
- 641 cases in Legacy review;
- 362 withdrawn, 7 rejected, 4 deferred and 1 at JBL visit.

These figures total 3,980. The case-specific exceptions do not require rebuilding the initial data.

Some historical completion dates are unknown. The importer retains unknowns rather than fabricating the modern workflow's evidence. Appropriate stage confirmation and later actions remain auditable.

## Complaints

The configured Complaints Register points to the supplied spreadsheet, is enabled, and has Sheet projection enabled.

There are currently:
- zero Complaints cases and ComplaintCaseControl rows;
- zero saved complaint legacy upload sessions or committed import rows;
- zero retained WhatsApp ComplaintCaseImportBatch records;
- zero browser upload attempts or retained publication files;
- zero populated complaint rows in the live Sheet.

The integration ledger retains 966 failed complaint sheet jobs marked source_deleted. They refer to deleted source records, not a current live backlog that should be replayed into the register. The ledger alone does not establish who deleted the cases or why.

Thus the Portal initial upload did not populate Complaints, and no current saved complaint import can be resumed. If historical complaints are intended, their reviewed source needs the dedicated Complaints importer. Portal workflow roles and Portal rows do not supply Complaint cases or Complaint authority.

## Publication execution and access

The only configured Render cron is scheduled daily and runs snapshot_workflow_tat. Its historical name mentions Complaints Report, but its actual command does not drain either publisher. start.sh only launches Gunicorn.

Portal's current code intentionally supports request-assisted publication from an open Portal session; its manual drain command is optional. No Portal scheduled-runner heartbeat is present. This is a limitation for unattended progress, separate from the exhausted row-comparison failures.

The Complaint publication runner last reported success on 4 November. Its durable publication runbook specifies an every-minute drain_complaint_publications worker for unattended jobs. No such Render worker/cron was found. There is no current complaint backlog to process, but reliable future retries require commissioning that runner.

Active Portal grant rows currently contain IT and HB_STAFF only. Ordinary visit, credit, Operations and Head-of-Rural staff access needs an explicit access review before wider rollout. Superuser override remains separate. Complaints has its own Officer, Manager, HB_STAFF and IT grants; none supplies Portal authority.

## Pre-release verification and separate rollout considerations

- Earlier focused current-main validation: 30 import/sync/case-release tests passed on isolated SQLite with network blocked. This does not establish PostgreSQL concurrency or live Google writes.
- Four additional offline regression checks passed using gspread 6.0.2 and the actual inner publisher: deployed failure reproduction, proposed same-row update with reordered headers, refusal of a real cell edit, and refusal of a newly added numeric zero. Database/Google writes were mocked and network disabled.
- git apply --check accepts the proposed patch against the audited production commit.
- No end-to-end signed production staff action or real Google write was performed.

Rollout status and separate future work:
1. The approved padding-comparison fix and 14-case publication recovery are complete; see live verification below.
2. The user is still reviewing the 253 outstanding source rows. Their eventual disposition and cutover completion are separate work and were not performed.
3. Confirm Portal staff roles through the existing governed access process.
4. Commission bounded unattended publishers if progress must continue with all app pages closed.
5. Import reviewed historical complaints separately if they are expected in the Complaints Mini App.

No production deployment, access-grant change, re-import, retry or scheduler creation is authorized merely by this audit.

## Implementation follow-up: saved status changes only

The user confirmed that the remaining source data is still being reviewed. Completing, excluding, approving, importing or releasing those outstanding rows is outside this correction. The continued review does not prevent publication of a verified case's saved status.

The new signed-HTTP regression reproduced the deployed failure before the fix: a verified imported case could save its status but enter dead-letter publication because of row padding. With the fix, all 70 focused checks pass in 36.426 seconds on SQLite, including Master Data and reordered Eco-conserve status publication during a partial import, duplicate prevention, protected formulas, genuine concurrent edits, quota backoff, identity conflicts, and preservation of saved state. Four pre-existing test-fixture failures were reproduced with the unchanged production function, then corrected to use its current signatures, service metadata and Decimal representation. Ruff and git diff --check pass.

The existing statuses must not be submitted again: recovery uses only their owning publication service and retains original failed operations. The change does not alter database locking. Dedicated PostgreSQL concurrency stress testing and a signed production staff action are not part of this bounded repair.

## Approved production release and recovery

- Authority: the user approved deploying the tested fix and retrying only the 14 affected publications. Completing, excluding, approving, importing or releasing outstanding source rows remains outside that approval.
- Deployment: main was fast-forwarded from b84433a6 to 353f831f. Render's existing automatic deployment created dep-dbp8qovavr4c73eecs40, live at 03:23:39 UTC on 10 November 2026. No duplicate manual deployment was triggered.
- Preflight: no pending migrations. Existing Superuser bootstrap was already satisfied, and the optional LAF bootstrap already had durable completion evidence. Existing release configuration retained its no-backup override; this repair did not change release settings or claim a new backup.
- Health: /api/health/ returned HTTP 200, app version 1.1.55, database connected. Existing TAT-repair runner warnings remain separate from this Portal comparison repair.
- Scope checkpoint: exactly 14 current revision-2 failed Master Data publications were captured. Every saved canonical case and initial-import checkpoint was fingerprinted for post-recovery comparison. The initial sessions remained ready/frozen with 250 and 3 unapproved rows.
- Authenticated Google read: all 14 cases had exactly one existing Master Data row, and all 14 saved status projections differed from the Sheet. The workbook retained 3,827 Master Data and 153 Eco-conserve case rows. Header, unaffected-row and formula fingerprints were captured without retaining customer values in this report.
- Operator recovery: the first local attempt passed row comparison but hit a separate publication timeout, leaving an audited retryable successor and the normal ten-minute circuit cooldown. Canonical case data did not change. The batch was stopped before advancing other cases; the circuit was not manually cleared.
- Native recovery: temporary Render job job-dbp8vvgn74is73d86j40 uses the deployed build, native credentials and internal database. It is restricted to the captured 14 cases, validates the tested publisher source fingerprint, respects cooldown and pacing, uses existing idempotent recovery services, and exits after bounded completion. No recurring worker or schedule was added.
- Native recovery completed successfully at 03:39:56 UTC. The first successor succeeded on its second attempt; each of the other thirteen succeeded on its first attempt. The temporary job exited and no recurring workload was created.
- Independent read-only verification: all 14 current publication successors succeeded and all 14 live Sheet statuses match Django. Fourteen successful update audit receipts point to the original physical rows. Zero rows were appended or duplicated. Master Data remains 3,827 cases and Eco-conserve 153.
- The complete canonical case fingerprints, initial-import session fingerprints, unapproved counts, headers and every non-cohort Sheet row match their pre-recovery fingerprints. Original failures remain retained. All outstanding rows remain ready/frozen and under review. No affected row contained a formula; formula preservation was covered in offline regressions, while unaffected live Sheet rows were compared in FORMULA mode.
- The Sheets circuit closed through normal successful execution; its last success was 03:39:53 UTC. The production release audit completed with its post-check passed and zero pending migrations. No dedicated production concurrency stress test or signed production staff submission was performed.

## Follow-up analysis: credit decisions, negative outcomes and the progress graphic

The user asked this question while recovery was running. This follow-up is read-only; no continuation stage, historical outcome, approval or UI behavior was changed.

The retained source values for all 3,980 committed import rows contain no dedicated credit-decision key. Known overall statuses are retained in legacy_outcome. Current canonical credit fields are blank on 3,975 cases and Rejected on five cases. Blank imported credit is displayed as Legacy by credit_decision_label when no subsequent recorded visit/credit event supplies a current decision; it is not evidence of credit approval or a reason to replay historical approvals.

Among 641 current legacy_review cases, retained proposals report 189 Rejected, 244 Deferred / On Hold and 185 Approved outcomes. Of those 641 cases, 639 have no recorded decision stage. The current label returns Legacy review - stage not confirmed before considering the retained reported outcome, so it hides information that is already known.

The same 641 include 107 source rows reporting installation. Existing proposal warnings flag 79 installation/commissioning chronology reversals and 27 future completion dates; these warning categories may overlap. These are different review reasons from an absent decision stage. Date warnings should be specific and a known reported physical status should remain visible as reported evidence.

Source-bound execution of the actual caseStageFlow JavaScript function with synthetic values reproduced three presentation defects:

- A credit rejection renders Credit Analysis complete and Head of Rural Review current.
- A credit deferral renders the same misleading progression.
- A withdrawal at credit renders Credit Analysis current with the active clock icon, rather than a closed outcome.

The cause is explicit: only active workflow states are in stateIndex. Rejected and deferred cases fall back to field presence, where any non-Pending credit decision counts as completion. Withdrawn cases select a stage but retain the ordinary current-step presentation. The caller also passes withdrawn_stage but not deferred_stage. No rejected, paused or closed visual state is rendered by this function.

Recommended correction:

1. Keep a historical reported outcome separate from the known decision stage and current action gate. An unqualified historical Rejected must not become Rejected at credit without evidence. An absent credit decision should say Historical credit decision not recorded, with an imported provenance label, rather than imply a pending modern assessment.
2. Show the known reported outcome in Portal and Sheet projections: for example Rejected - historical stage not recorded, or Approved - continuation stage needs confirmation. Retain existing review restrictions until continuation is actually established.
3. Represent rejection as a stopped negative outcome, deferral as paused at its known stage, and withdrawal as closed. No later stage should appear active. When the terminal stage is unknown, show that limitation without placing a rejection at an invented stage.
4. Preserve reported installation/commissioning evidence with a specific date/conflict warning. Do not manufacture prior credit/final approvals, actors, dates, signatures or completed modern workflow events from downstream physical evidence.

These are a separate mapping/presentation correction from the deployed row-padding repair. Existing Legacy Continuation confirmation remains the supported way to establish a stage from reviewed evidence; the outstanding import review is unaffected.

## User-approved compact Sheet catalogue and order-number clarification

The user selected eleven concise statuses and accepted Under Review as the
twelfth for Credit/Head of Rural processing. They then clarified that a recorded
legacy order number implies historical approval. That instruction supersedes
the earlier conservative recommendation for historical order-number display.
The user then clarified the stage boundary: Approved — Order Processing is
only for an approved case still awaiting an order number. Once an order number
exists, the case displays Installation in Progress until installed/commissioned.
No historical approver/date, signed scan or HB handover is manufactured.

The display correction is implemented locally on feat/portal-sheet-statuses,
based directly on the live 353f831f code. It changes the existing Sheet column
through the shared initial/normal publication plan and retains detailed Mini App
labels and workflow authority. There is no new column, dropdown, dependency,
configuration or migration. Both live status columns currently have no data
validation rule, so there is no dropdown installation to perform.

Read-only review produced this proposed aggregate distribution:

| Proposed status | Cases |
| --- | ---: |
| Commissioned | 2,679 |
| Rejected | 196 |
| Deferred | 251 |
| Opted for Other | 332 |
| Cancelled/Withdrawn | 34 |
| Approved — Order Processing | 0 |
| Installation in Progress | 302 |
| Installed — Awaiting Commissioning | 85 |
| Legacy | 99 |
| Under Review | 1 |
| Pending Minimum Deposit | 1 |
| Awaiting JBL Visit | 0 |

Exactly 3,979 existing status cells differ from the new uppercase projection:
3,826 Master Data and all 153 Eco-conserve cases. A private local review manifest
retains UUIDs, cell addresses, safe status values and hashes for canonical/source
facts, headers, other cells and import checkpoints; no customer values or secrets
are included in this report. No production statuses have been changed by this
preview and all 253 unapproved rows remain untouched.

Final local verification: 135 focused checks executed, 133 passed and two
PostgreSQL-only tests skipped. Ruff, Django checks, migration drift and diff
checks pass. A prior local overlapping-run SQLite lock was corrected by
serializing test runs; the final combined run passed with the two skips. Full repository testing,
remote CI, PostgreSQL concurrency stress and live publication of this catalogue
have not been performed by the focused local run. The user subsequently
explicitly requested merging both branches to main and production deployment.
The fix branch was already included; the feature merged by fast-forward and
code d5d7cb3e was pushed to main. Render deploy dep-dbpa726417fc739epjn0 became
live at 04:57:42 UTC on 10 November. Production release pre/post-checks passed,
no migrations were pending, and API/ops health returned 200 with the database
connected. The existing no-backup release override was retained without change.

The approved status refresh updated exactly 3,979 cells in three single-column
RAW ranges at 04:59:36 UTC. All 3,980 projected labels passed readback; headers,
row ownership, other Sheet cells, canonical/source facts and import-session
fingerprints were unchanged. The 253 unapproved rows remain under review. A
private completion receipt retains the bounded request hash and Google update
count. No case actions, approvals, import completion or Telegram sends ran.

Remote CI still reports artifact-audit/browser-review failures also present on
353f831f; those inputs were not changed by this release. PostgreSQL CI was still
running at release verification. The negative Mini App progress graphic remains
a separate known gap. See the checked-in release checklist for remaining gates.
