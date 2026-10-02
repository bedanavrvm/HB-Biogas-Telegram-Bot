# Portal engineering remediation plan

Date: 1 October 2026.

Source: [Engineering-quality audit](portal-engineering-quality-audit-2026-10-01.md).

Status: authorized local implementation, excluding EQ-06 and EQ-11. The
implementation record below distinguishes delivered changes from remaining
release checks. The original detailed plan is retained for traceability;
production repairs, deployment and hosting changes are not authorized here.

## Implementation record — 2 October 2026

The authorized code changes are implemented locally. EQ-06 and EQ-11 are
explicitly excluded; D1 and D9 below remain proposals, not delivered changes.
The narrow extraction of lead creation and finalized-order persistence belongs
to EQ-09's existing architecture gate, not the excluded broad refactor.

| Finding | Delivered change | Verification / remaining boundary |
| --- | --- | --- |
| EQ-01 | Locked claim checks for terminal state, retry time, budget and active lease | Desired-behavior tests, including a live final attempt and separate PostgreSQL connections |
| EQ-02 | Unique attempt tokens fence success, failure and auxiliary failure evidence | Late old success/failure cannot replace the current owner's outcome |
| EQ-03 | Destination-bound FIFO, group-bound configuration and reconfiguration supersession | Independent Master/Eco destinations progress without publishing to an obsolete destination |
| EQ-04 | Composed Google-call budgets, recoverable circuit probes and server-derived polling deadlines | Canonical saves remain independent of Sheets; no cron or unattended-progress promise |
| EQ-05 | Invoice processing ownership, Drive acceptance checkpoints and resumable parsing | Interrupted synthetic uploads tested; read-only `inventory_invoice_recovery` exposes legacy cases needing review |
| EQ-06 | Excluded | Invoice diagnostic privacy cleanup was not applied |
| EQ-07 | Delivery byte/file caps, isolated PDF workers, hard parent timeouts and render pixel/page budgets | Real synthetic PDF worker tested locally; Linux resource limits need the Linux CI lane |
| EQ-08 | Scoped payment query/count/filter before ten-row paging | Historical scale fixture verifies only the selected page is serialized; current review digests still checked exactly |
| EQ-09 | Correct first-party dependency discovery, aligned manifests and narrow owning-service extraction | Dependency parity and architecture checks pass without expanding the mutation baseline |
| EQ-10 | Required disposable PostgreSQL CI lane; bounded-domain lint and branch-coverage collection | Fresh schema, concurrent claims and a representative payment schema upgrade tested; full-suite coverage baseline is not established |
| EQ-11 | Excluded | Broad service decomposition was not applied |
| EQ-12 | Runtime/update/release/recovery contract and monthly dependency checks | Runbook delivered; clean supported-runtime install, hosted capacity and backup restore drill remain unverified |

Evidence is under `test-results/portal-journey-audit/` (ignored generated output,
not customer fixtures). The final focused PostgreSQL run passed 199 tests,
including the two final-attempt regressions; its result is in
`remediation-postgres-final.txt`. Browser tests
passed 134 tests and all nine Node groups passed. Tooling verification passed
nine dependency/coverage contract tests (including Windows path normalization), dependency parity, architecture,
Python compilation and first-party JavaScript syntax checks.

The interrupted `remediation-final.txt` coverage run has no final verdict and
must not be counted as a pass. A replacement focused PostgreSQL branch-coverage
run completed and reported all bounded domains in `remediation-coverage-domains.json`.
Its total is 22.52%, not a full-suite coverage claim. The default local gate
checked no committed diff; working-tree branch gaps are reported separately in
`remediation-working-tree-coverage.txt` and must be covered before claiming the
changed-code release gate passes. Earlier broad runs reproduced existing failures
against unchanged HEAD; see `remediation-head-baseline.txt` and
`remediation-order-approval-baseline.txt`. Full CI is not green: the existing
unsafe-route inventory gaps and expired dependency-audit exception still need
separate review. No baseline or security exception was fabricated to hide them.

No production data repair, external publication, deployment or backup restore
was performed. Drain old unfenced workers before deploying the new executor.
Historical defect-characterization probes are audit evidence only; the permanent
desired-behavior tests are the acceptance checks for these changes.

## 1. Objective and boundaries

Make the existing Portal dependable under retries, interrupted uploads, concurrent users, growing datasets and routine upgrades. Preserve its business rules and approved mobile interactions.

Non-negotiables:

- Django remains the source of truth; Sheets/Drive remain projections and document storage.
- Workflow saves commit locally without waiting for Google.
- No cron, Celery, Redis, new hosted service or frontend rewrite is introduced by this plan.
- Request-assisted publication remains available; unattended completion is not promised when every client is closed.
- Preserve capability checks, complete-grant branch/product scope, explicit technical overrides and media-access auditing.
- Preserve approval validity rules, official numbering, Decimal values, exact signed-document binding and workflow progress.
- No automatic deletion of customer records, Drive files, logs or audit history.
- New persistent models, if unavoidable, belong in a bounded-domain app with catalogue metadata. Existing model alterations require checked-in migrations.
- Implement one bounded change per reviewable delivery. Do not combine dependency upgrades, schema changes and workflow refactoring without a concrete dependency.

## 2. Coverage and order

| Delivery | Audit findings | Main output | Dependency |
| --- | --- | --- | --- |
| D1 | EQ-06 | Privacy-safe invoice diagnostics | None; urgent containment |
| D2 | EQ-09, EQ-10 | Trustworthy CI and PostgreSQL test lane | None |
| D3 | EQ-01, EQ-02 | Safe claim and fenced completion | D2 concurrency lane |
| D4 | EQ-07 | PDF/request resource budgets | D2 validation; before larger upload processing |
| D5 | EQ-05 | Resumable invoice ingestion | D3 and D4 |
| D6 | EQ-03 | Destination-bound FIFO and quota-safe progress | D3 |
| D7 | EQ-04 | Bounded assisted execution and accurate status | D3 and D6 |
| D8 | EQ-08 | Scoped database-backed payment pagination | D2 |
| D9 | EQ-11 | Incremental service-boundary cleanup | Relevant earlier delivery contracts |
| D10 | EQ-12 | Runtime/update/restore operating contract | Stable preceding changes |

Privacy containment can ship first. Do not postpone it until every architecture improvement is finished. D2 should be split into small checker, service-boundary and test-lane changes where needed.

## 3. Preparation: establish evidence before changing behavior

Tasks:

- Record the exact commit, runtime versions, migration state and dirty-worktree status for the implementation pass.
- Rerun the two failing checks and confirm that the audited findings still apply.
- Preserve the four characterization probes as diagnostic evidence; create desired-behavior regression tests in the established test locations. Do not silently treat tests that reproduce defects as acceptance tests.
- Inventory callers of `execute_operation`, claim/completion helpers and invoice ingestion across Portal, Drive, Telegram and other workflows.
- Identify all replay consumers and current response expectations before changing return values.
- Record baseline payment query counts, queue-selection queries and representative PDF-processing time using synthetic fixtures.
- Use isolated databases and mocked external gateways. Never point this work at production customer data.

Output:

- A finding-to-test checklist showing reproduced, code-confirmed, fixed, verified or operationally unverified status.
- A short baseline of timings/query counts and runtime configuration, not an invented production SLA.

## 4. D1 — Stop customer data entering invoice diagnostics

Primary files: `core/services/invoice_parser.py`, invoice tests, shared error handling where affected.

Changes:

- Remove extracted invoice text from parser warnings.
- Use safe batch reference, page number, parser version and reviewed failure category.
- Inspect nearby parser/matcher/storage exception paths for raw names, IDs, phone numbers, amounts, PDF text and provider response bodies.
- Preserve useful support references and actionable staff messages without echoing document contents.
- Ensure diagnostics are not the only record of a failed page; retain safe processing outcomes on the upload batch.

Tests:

- Put unique synthetic identity and amount markers in an unparseable page; capture every emitted log and assert the markers are absent.
- Exercise corrupt/encrypted PDFs and mocked provider errors containing token-like strings.
- Confirm normal parsing, matching and staff failure feedback remain unchanged.

Acceptance:

- Parsing failures remain diagnosable by batch/page/category.
- No synthetic customer/document marker reaches normal logs or error responses.

Operational follow-up:

- An authorized administrator reviews log access, retention and potential historic exposure.
- Historical logs are not automatically deleted or rewritten by this patch.

## 5. D2 — Restore meaningful CI and production-shaped tests

### 5.1 Dependency and architecture gates

Primary files: `scripts/check_dependency_parity.py`, its tests, `requirements.txt`, `pyproject.toml`, `core/api/portal_views.py`, owning services.

- Align the declared `cryptography` dependency without bundling an unrelated version upgrade.
- Discover/classify first-party domain packages correctly; test the six packages flagged by the audit and detection of a genuinely undeclared external import.
- Move the five flagged customer/lead/order mutations out of views into the appropriate existing services.
- Preserve transaction boundaries, numbering locks, request identity, permissions and response contracts during extraction.
- Keep the architecture gate strict; do not add blanket exceptions or approve the violations as a new baseline.

### 5.2 PostgreSQL validation

Primary files: `.github/workflows/ci.yml`, `config/settings_test_postgres.py`, `scripts/test_postgres.ps1`, relevant test modules.

- Add a disposable local-to-job PostgreSQL service in CI, separate from all production databases.
- Reconcile the existing localhost/test-name safety guards with the CI connection; do not weaken them to accept arbitrary remote databases.
- Keep a fast unit lane, plus a required PostgreSQL lane for transactions, locks, numbering, claims, publication and migrations.
- Use `TransactionTestCase` or equivalent separate-connection tests with controlled synchronization barriers. Avoid sleep-based race tests.
- Include fresh migrations and a representative prior-schema upgrade with synthetic records.
- Make the existing local runner write a clear result and return a nonzero exit code on failure; keep credentials out of output.

### 5.3 Coverage and lint

- Include bounded domain apps in coverage collection and lint discovery.
- Update `scripts/check_coverage_quality.py`: it currently filters out files outside `core`, so changing only `--source` would not fix the gap.
- Report each domain separately; introduce thresholds from measured baselines rather than pretending newly measured code already meets an arbitrary target.
- Preserve meaningful changed-code checks and do not exclude failing business code simply to pass CI.

Acceptance:

- Dependency parity and architecture checks pass for the corrected reasons.
- Domain apps appear in coverage reports.
- PostgreSQL tests demonstrably use PostgreSQL and independent connections.
- Both clean-database creation and the selected upgrade path succeed.

## 6. D3 — Make execution ownership safe under concurrency

Primary files: `core/services/external_resilience.py`, existing operation model/metadata, callers, concurrency tests.

### 6.1 Locked claim eligibility

- Recheck terminal state, retry deadline, attempt budget and active ownership inside the locked transaction.
- Treat success as an idempotent replay, not executable work.
- Treat dead-letter state as terminal until the owning workflow explicitly reserves a reviewed replacement.
- Do not spend attempts when pacing or another valid claim prevents execution.
- Handle initially missing pacing/circuit mutex rows safely under concurrent creation.
- Establish consistent lock order to reduce deadlock risk.

### 6.2 Attempt identity and fenced completion

- Persist a unique claim identifier for each execution and pass it through success/failure handling.
- Prefer existing durable metadata/fields if they support a clear atomic ownership contract. Add dedicated fields only if required for enforceability or query performance, through an additive migration.
- Accept an outcome only if the operation is still Running and the completing attempt owns its current claim.
- Reject/ignore stale outcomes without rewriting a newer completion timestamp, status or result.
- Update circuit outcomes consistently with accepted attempt outcomes; an obsolete worker must not incorrectly reopen/close shared circuit state.
- Preserve old dead-letter operations and the existing replacement retry chain rather than resetting evidence in place.

### 6.3 Lease and external-side-effect boundary

- Define an overall execution budget, not merely a timeout per individual network call.
- Ensure the lease cannot expire during a normally bounded active operation; use narrowly scoped renewal only when justified.
- Keep external calls outside long-held database locks.
- Do not claim exactly-once Google effects: a timed-out request may already have been accepted remotely.
- Verify Sheets retries use Case ID and guarded row updates; verify Drive recovery uses a stable operation/content identity before creating another file.
- Where remote outcome is uncertain, reconcile before resending rather than blindly duplicating the action.

Tests:

- Two callers race from the same pending read: exactly one receives an executable claim.
- A caller tries to claim after another has completed: no external call.
- Active lease, expired lease, future retry, exhausted budget and dead-letter states.
- Old failure after new success; old success after new failure; both outcomes arriving after reviewed replacement.
- Exceptions during claim and completion, missing mutex creation, process termination and simulated remote acceptance followed by timeout.
- Smoke-test every shared integration consumer, not only Portal.

Acceptance:

- Stale workers cannot change current outcomes.
- Terminal work cannot be reopened by stale reads.
- Attempts, deadlines and timestamps remain internally consistent.
- No network call is made while holding a broad workflow/database lock.

Deployment:

- If ownership fields are added, apply the additive migration before activating new ownership enforcement.
- Existing Running records require a compatibility strategy: allow old workers to drain before new workers reclaim them, or use a controlled maintenance transition. Do not mix unfenced old executors with newly fenced execution and call it safe.
- Include caller/API compatibility tests before deploying the shared change.

## 7. D4 — Bound uploads, parsing and preview rendering

Primary files: `core/services/secure_media_preview.py`, `core/services/invoice_parser.py`, upload endpoints/settings and synthetic fixtures.

Changes:

- Define per-file and aggregate request byte limits, file count, page count, per-page pixel allocation and total processing budgets.
- Retain existing accepted invoice behavior; choose initial thresholds from representative synthetic invoice batches and available worker memory, documenting the rationale.
- Validate PDF page dimensions and estimated rendering allocation before creating a bitmap.
- Release documents, pages, bitmaps and images through library-appropriate cleanup even on exceptions.
- Reject unsupported/encrypted/corrupt input with safe, clear guidance.
- Avoid treating compressed output size as a memory limit; allocation occurs earlier.
- A cooperative loop deadline cannot interrupt a single native extraction/render call. Use an existing supported isolated execution mechanism with hard bounds if required; do not describe post-call checks as a hard timeout.
- For oversized legitimate work, split it into bounded resumable units rather than rejecting an entire delivery without recovery guidance.

Tests:

- Boundary-size files and batches; many small files; high page count; large page dimensions.
- Empty, corrupt, password-protected and unsupported PDFs.
- Cleanup after parser/render failures and quota exhaustion.
- Safe stubbed dimension tests first; run hostile/native-resource tests only in an isolated process with memory/time limits.
- Confirm existing workbook, order and invoice previews remain readable and accessible in the app.

Acceptance:

- Expensive allocations have preflight bounds.
- A failed document cannot monopolize or crash the main test/web process.
- Partial results identify what succeeded and what remains; no false overall success.

## 8. D5 — Resume invoice ingestion instead of replaying unfinished state

Primary files: invoice ingestion service, batch metadata/status projection, relevant invoice endpoints and upload UI.

Processing contract:

- Track reservation, file acceptance, parsing and completion separately from invoice matching/review state.
- Do not repurpose Matched/Ignored/Deleted invoice states as processing states.
- On replay, verify group, content hash and request identity before returning or resuming anything.
- Completed batch: replay the completed result without additional external calls.
- Currently owned processing: report processing without starting another worker.
- Expired/interrupted processing: resume from the last verified boundary.
- Store enough durable evidence to distinguish file accepted from file not yet accepted.
- If bytes are needed after the request ends, use an existing governed durable source or a bounded-domain recovery artifact with explicit retention/access rules. A hash alone cannot reconstruct a PDF.
- Reuse a known accepted Drive file; reconcile uncertain uploads through stable operation identity rather than filename alone.
- Commit parsed rows and the completed parse checkpoint atomically; replays must not create duplicate invoice rows or parse events.
- Persist intentional partial parsing distinctly, with page-level progress only if justified by the selected processing model.
- Retain content-hash duplicate protection; recovery must not disable it for completed batches.

User behavior:

- Keep the current invoice workflow/screens.
- Display Processing, Completed, Partially processed or Retry needed through the existing compact feedback patterns.
- Provide one scoped retry/resume action where needed; avoid a new mandatory note form.
- Preserve selected files/results and support references on ordinary errors.

Existing records:

- Produce a read-only inventory of old unfinished batches first.
- Classify those with a known Drive ID, recoverable source, uncertain external outcome or unavailable bytes.
- Repair only through a reviewed, idempotent command/action with dry-run support and retained history.
- Never clear completed hashes globally or delete suspected orphan files automatically.

Tests:

- Stop before upload, after remote acceptance, after saving file identity, during parsing and after committing rows but before responding.
- Repeat the same request, repeat with a new request key, change bytes/order/group, and double-submit concurrently.
- Confirm matching routes and payment eligibility remain correct after recovery.

Acceptance:

- Retry either resumes safely or explains the exact recovery requirement.
- No unfinished batch is returned as a successful completed upload.
- No duplicate parsed rows/events/files from replayed processing.

## 9. D6 — Isolate Sheet destinations while preserving FIFO

Primary files: `core/services/portal_publication.py`, canonical target resolution, Sheet gateway and queue tests.

Changes:

- Resolve the originating group and destination explicitly; remove reliance on a globally selected first configuration where it affects publication.
- Bind each reservation to its destination identity: group, spreadsheet and register/tab, plus the canonical revision and Case ID.
- Select the oldest eligible operation within each ordering boundary, then choose between ready boundaries fairly.
- Recheck ordering when claiming, not only in an earlier queue-list read.
- Keep quota pacing coordinated across destinations using the shared integration controls.
- Preserve same-register FIFO even while another register progresses.
- Define routing-change handling: supersede stale work, reserve the correct destination and follow the existing controlled relocation contract. Never leave an old operation writing to a destination that is no longer valid.
- Do not collapse separate destinations into one scope or expose another group's cases in queue feedback.

Compatibility:

- Backfill/infer destination identity for pending legacy work only where its canonical group and configuration are unambiguous.
- Mark unresolved work for explicit technical review rather than guessing a destination.
- Preserve row 1 as headers, row 2 as first data, Case ID update identity, numeric amount formatting and agreed date formats.

Tests:

- Same-sheet first-commit FIFO, including backoff and active claims.
- Eco retrying while Master progresses, and the reverse.
- Two groups, identical customer names/IDs, different sheet configurations.
- Concurrent claims for one destination and simultaneous claims for different destinations.
- Routing changes, missing configuration, stale revisions, row-2 placement and retry without duplicates.
- Shared quota exhaustion pauses/resumes safely without multiplying Google calls.

Acceptance:

- One destination's document/configuration failure does not unnecessarily stall another healthy destination.
- Rows remain correctly ordered within each target register.
- No accidental cross-group publication.

## 10. D7 — Make assisted sync bounded and its feedback truthful

Primary files: publication pump endpoint, `portal_api.js`, queue/status projections, existing admin recovery command.

Changes:

- Preserve immediate canonical saves and navigation while synchronization runs independently of the user's form.
- Limit one pump request to a documented bounded execution budget; prevent inner retry loops from multiplying that budget.
- Respect persisted retry deadlines, shared pacing and provider cooldowns across clients.
- Coalesce overlapping pump requests; avoid every open device racing repeatedly for the same work.
- Expose safe state: queued, processing, retry due, paused or needs repair, with a concrete recovery action for authorized staff.
- Distinguish a retry deadline from an estimated completion time. Queue length, operation duration and open-session availability affect completion.
- Render a countdown from the server-provided deadline; do not issue a new API request every second merely to update the label.
- Make Retry resume/requeue the existing reviewed work, not create arbitrary duplicate work or bypass cooldowns.
- No customer form, local draft or unrelated navigation waits for the pump response.

Observability:

- Track aggregate oldest queue age, ready/in-flight counts, claim conflicts, stale outcomes ignored, execution duration, failure category and retry count.
- Keep technical details in Operations/IT surfaces; do not add operational alarms to officer customer tasks.
- Reuse durable operation/heartbeat records where appropriate; avoid a new monitoring platform or storing customer data in metrics.

Tests:

- Slow Google call while navigating, editing and opening another screen.
- Background/foreground, offline/online, page close, two devices and repeated refresh.
- Long cooldown, exhausted budget, reviewed retry, stale work and missing source.
- Countdown accuracy without excessive requests and no repeated success/error toast spam.

Acceptance:

- The Portal remains usable during assisted publication.
- Staff can see when a retry is due and what they can do, without a false completion guarantee.
- Manual drain remains available and uses the same claim/order/quota contracts.

Decision not silently made:

- Guaranteed completion while no client is open requires an independently running mechanism. It can be non-cron, but changes hosting/operations scope and needs a separate decision.

## 11. D8 — Paginate payment data before loading the full history

Primary files: payment queue query/service and Portal payment endpoints.

Changes:

- Express group eligibility and whole-batch scope in database queries before selecting the page.
- Preserve existing visibility semantics: every active member must be authorized according to its complete grant rules; never borrow a branch from one grant and product from another.
- Preserve empty-draft behavior and review/prepare capability differences explicitly.
- Express approval queue membership in the owning payment service, using annotations/subqueries where appropriate.
- Count authorized queues separately; prefetch/serialize only the selected ten batches and their needed active members.
- Use stable ordering with a unique tie-breaker and predictable handling of an empty/out-of-range page.
- Add indexes only after inspecting representative query plans; each index needs a documented reason.

Tests:

- 10, 100 and 1,000 synthetic batches with realistic memberships/reviews.
- Assert bounded serialized/prefetched rows; measure query plans, response size and memory rather than assuming a constant query count means constant cost.
- Every role/capability and mixed branch/product grants; one unauthorized active member; inactive members and empty drafts.
- Queue counts match linked results; review-complete, awaiting review, cancelled and finalized batches retain their meaning.
- Concurrent queue changes between pages do not leak unauthorized records.

Acceptance:

- Display stays at ten entries with unchanged permission behavior.
- Response construction does not load every historical membership/review.
- Counts remain consistent with the filtered queue.

## 12. D9 — Improve maintainability without a disruptive rewrite

Changes:

- Finish only the view/service extractions necessary for earlier fixes first.
- Establish thin endpoint responsibilities: authenticate, authorize, validate request shape, invoke service, return the established response.
- Move workflow mutation, transactional orchestration and reusable queue rules into their owning services.
- Share state projections across queues, Home, notifications, history and reports where the meaning is genuinely the same.
- Keep distinct workflows distinct; no generic state engine replacing established payment/order/HB rules.
- Reconcile the conflicting new-model guidance in `AGENTS.md` with the bounded-domain requirement.
- Document invariants and failure recovery next to services/tests rather than adding more unsupported root-level status claims.
- Extract one workflow boundary per delivery; do not relocate thousands of lines simply to reduce a file-size metric.

Acceptance:

- Architecture checks enforce the intended boundary.
- Existing route, response, permission and business-state tests remain unchanged in meaning.
- No new frontend component vocabulary or incidental redesign is introduced.

## 13. D10 — Upgrade, release and restore safely

### Runtime and dependency contract

- Record supported Python, Node and PostgreSQL versions from tested configuration and actual deployment settings when authorized.
- Make clean install and test commands reproducible; align manifests and choose an explicit lock/constraints approach compatible with the current package workflow.
- Separate version pinning from version upgrading; do not install the latest versions merely because an audit found drift.
- Add npm and GitHub Actions update coverage to the existing dependency-update mechanism.
- Document vendored asset version/license updates and their affected browser tests.
- Maintain a small upgrade checklist: install, migration graph, DB constraints, PDF/parser output, browser behavior and rollback/forward-fix considerations.

### Deployment and recovery

- Review additive migrations and backup evidence before deployment.
- Check worker/thread/memory settings against measured bounded-operation duration and representative synthetic load.
- Document failed-deploy handling: which failures are safe to forward-fix, when to restore and who can authorize either action.
- Rehearse restoration into an isolated database and storage namespace using authorized synthetic/sanitized material.
- Measure actual restoration time and data-loss window before claiming recovery-time/recovery-point targets.
- Verify restored access control, numbering, signed-document references and integration retry behavior before serving writes.
- Reconcile DB references and external files conservatively after restore; external files may outlive the restored DB snapshot.
- Keep automatic reverse migrations and destructive orphan cleanup out of the default recovery path.

Acceptance:

- A new contributor can install and test against the supported runtime without undocumented environment guessing.
- Upgrade gates cover all relevant packages/domains.
- A tested runbook exists for restoring service; repository backup evidence is not mistaken for a successful restoration exercise.

## 14. Combined verification matrix

Run focused tests first, then wider suites. Every delivery records passed, failed, skipped and unverified scope.

- Unit/service: request identity, state validation, safe logs, parser boundaries and scope projections.
- PostgreSQL: claims, leases, lock ordering, official sequences, unique constraints and concurrent retries.
- Fault injection: process termination, remote acceptance followed by timeout, late outcomes and stale revisions.
- Integration: FarmUp → visit → credit → final review → signed order → installation → commissioning, with invoice/payment work at their valid independent points.
- Regression invariants: SysUp enrichment does not invalidate decisions; LGF stays payment-only; County remains canonical; signed scans govern finality.
- Sheets: Master/Eco routing, row 2, Case ID identity, FIFO within destination, date/amount formatting and no duplicate rows on retry.
- Payment: matching routes, review visibility, membership changes, workbook invalidation, previews and ten-entry pagination.
- Browser: existing 320–430px viewport checks, larger screens, themes, slow/offline networking, back navigation and draft survival. Use current shared fixtures/components.
- Resource/scale: representative large invoice deliveries and growing payment history on an isolated local system.
- Deployment: fresh migrations, prior-schema upgrade, clean dependency install and all configured CI gates.

No local mocked test is presented as proof of Google quota behavior, real Telegram WebView behavior, hosted capacity or production restoration.

## 15. Data repair, rollout and completion rules

- Distinguish prevention patches from repair of already inconsistent records.
- Start every repair with a read-only inventory and a dry-run plan; require explicit authority for production application.
- Preserve failed-operation history, invoice identity and signed-document evidence.
- Introduce compatibility adapters only where needed for existing records; remove them after a documented migration/verification window, not immediately.
- Stop a rollout if duplicates, incorrect destinations, missing scope checks or contradictory operation states appear.
- Rollback means a reviewed compatible application version or planned forward fix—not blind schema reversal or deleting audit records.
- Observe queue age, retry volume, claim conflicts and upload completion before declaring recovery complete.
- Close each EQ finding only when its acceptance tests pass and any operationally unverified part is separately recorded.

Final deliverables:

- Fixed code in bounded deliveries, checked-in migrations only where necessary.
- Permanent desired-behavior regression tests, including PostgreSQL concurrency tests.
- Green meaningful CI gates, expanded domain coverage and synthetic scale evidence.
- Scoped repair tools where legacy inconsistent records need recovery.
- Updated contributor/runtime/recovery guidance.
- An audit closure table with evidence per finding and no unsupported “production ready” claim.

## 16. Operational choices requiring a separate decision

These do not prevent the local code/test work above:

- Whether unattended synchronization is mandatory when every Portal client is closed; if so, which non-cron hosting mechanism is acceptable.
- Actual production worker/memory budget and allowable processing/request sizes, based on measurement.
- Backup retention, recovery objectives and authorization to rehearse against hosted backup material.
- Any production data repair, historic-log handling or Drive orphan reconciliation.

Until decided, preserve the existing no-cron/request-assisted design, use isolated synthetic verification, and make no external production changes.
