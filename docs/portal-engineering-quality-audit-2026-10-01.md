# Portal engineering-quality audit

Date: 1 October 2026. Scope: Portal services, publication, invoices, payments, previews, deployment and test tooling.

This is an engineering audit, not a second visual-design review. No application behavior, production data, access policy, or external service was changed. Findings below distinguish reproduced behavior, code-confirmed weaknesses, and operational questions that cannot be answered from the repository.

## Overall assessment

The Portal has useful foundations: canonical Django records, explicit workflow services, capability-scoped access, durable publication reservations, governed documents, and substantial automated checks. Its main weakness is not missing features. It is that several recovery and concurrency contracts are less robust than their surrounding workflow contracts.

**The first priorities are external-operation claim correctness, invoice recovery/privacy, and restoring meaningful CI gates.** Cosmetic cleanup or a large architecture rewrite would not address these risks.

| Quality | Assessment | Main concern |
| --- | --- | --- |
| Stability | Needs hardening | PDF processing and external calls consume web-request resources. |
| Reliability | Confirmed defects | Terminal work can be reclaimed; old attempts can overwrite newer outcomes. |
| Recoverability | Partial | Interrupted invoice ingestion can replay unfinished state without resuming. |
| Availability | Conditional | Automatic Sheet progress depends on visible, online Portal sessions. |
| Scalability | Predictable bottlenecks | Global queue coupling and full payment-list materialization. |
| Maintainability | Uneven | Bounded services coexist with oversized views and direct business writes. |
| Upgradeability | Needs work | Dependency manifests disagree; some dependency/update coverage is incomplete. |
| Testability | Good breadth, incomplete fidelity | CI is not PostgreSQL-backed; important bounded apps are outside coverage measurement. |
| Security/privacy | Specific confirmed concern | Unparsed invoice content is included in warning logs. |
| Observability | Useful foundation, incomplete proof | Durable status exists, but operational recovery/latency guarantees need evidence. |
| Deployability | Current blockers | Two checks invoked by CI fail on this checkout. |

No numerical quality score is assigned: there was no production load measurement, incident dataset, or service-level objective against which to calculate one.

## Evidence and verification

- Inspected current services, endpoints, database-related contracts, frontend publication behavior, CI, dependencies and startup scripts.
- Ran isolated synthetic Django characterization probes with Google storage mocked.
- Ran dependency-parity and architecture-boundary checks.
- Result: **4 characterization probes passed**, reproducing four unwanted behaviors; **both governance checks failed** with the findings listed in EQ-09. Diagnostic Python compilation and whitespace checks passed.
- Django emitted SQLite table/column-comment compatibility warnings during the isolated run. Those warnings are not counted as additional Portal defects.
- Test output: `test-results/portal-journey-audit/engineering-probes.txt`.
- Check output: `engineering-dependency-parity.txt` and `engineering-architecture.txt` in the same directory.
- Diagnostic source: `scripts/portal_engineering_audit_probes.py`.
- Characterization probes deliberately assert current defective behavior. A passing probe means the risk was reproduced, **not** that it is an acceptable regression contract. Convert these to desired-behavior assertions when implementing fixes.
- SQLite was used for these deterministic state interleavings. They do not establish PostgreSQL locking correctness or reproduce real simultaneous workers.
- Previous usability-audit test counts were not rerun or counted as evidence for this audit.
- No production/Google/Telegram calls, load tests, real customer fixtures, destructive resets, or backup restorations were performed.

## Findings

### EQ-01 — A stale claimant can reopen completed work

**Priority: P1. Qualities: reliability, idempotency, financial/document integrity. Reproduced.**

Evidence: `core/services/external_resilience.py:193`, `:271`.

- `execute_operation()` checks terminal status before obtaining the operation's execution lock.
- `_mark_attempt()` locks the row but does not recheck success, dead-letter status, remaining attempts, or the operation's retry deadline under that lock.
- A second caller that read pending state earlier can claim an operation after another caller has completed it.
- The synthetic probe marked an operation successful, then claimed it again: status became Running and attempts increased to two.
- Impact: duplicate external work is possible even though durable reservations exist. Whether a particular duplicate causes a second file/row depends on that gateway's separate idempotency behavior.

Fix direction:

- Revalidate terminal state, attempt budget and eligibility inside the locked claim transaction.
- Return an explicit already-completed/no-op outcome to stale claimants.
- Keep network calls outside database transactions.
- Test two PostgreSQL connections racing to claim one operation, including completion between the initial read and claim.

### EQ-02 — An expired attempt can overwrite the replacement attempt

**Priority: P1. Qualities: reliability, consistency, recoverability. Reproduced.**

Evidence: `core/services/external_resilience.py:235`, `:256`.

- Running work can be reclaimed after a lease expires.
- Success and failure updates identify only the operation, not the attempt that owns its current lease.
- A late failure from the original attempt can overwrite the replacement's success.
- The probe produced Retryable status with an existing successful completion timestamp: contradictory operational evidence.
- The current lease is at least 30 seconds, derived from an individual API timeout rather than a verified bound on the entire operation.

Fix direction:

- Issue an attempt identifier and require it on completion/failure updates.
- Ignore stale completions through a conditional update or equivalent fenced transition.
- Define a whole-operation deadline; use lease renewal only if genuinely needed.
- Test old-success/new-failure and old-failure/new-success interleavings, process termination, and budget exhaustion.

### EQ-03 — One delayed destination holds up unrelated Master/Eco work

**Priority: P2. Qualities: availability, fault isolation, scalability. Reproduced selection behavior.**

Evidence: `core/services/portal_publication.py:27`.

- The oldest Master publication is selected globally, not by group, spreadsheet or tab.
- If that operation is waiting for a retry deadline, newer due Master operations are not eligible.
- The probe reserved two separate source operations, delayed the first, and found no eligible work for the second.
- This proves global coupling, not a production cross-group outage. No live multi-group experiment was performed.
- FIFO is a valid requirement, but ordering all destinations together is stronger than ordering rows within a destination.

Fix direction:

- Define the ordering boundary explicitly: group + spreadsheet + target register/tab.
- Preserve FIFO within that boundary, while retaining shared API quota pacing.
- Verify Master and Eco row ordering, routing changes, and one failing destination alongside one healthy destination.
- Do not silently bypass older work within the same ordered register.

### EQ-04 — Automatic publication has no independent liveness guarantee

**Priority: P2. Qualities: availability, operability, capacity. Code-confirmed design limitation.**

Evidence: `core/static/miniapp/portal_api.js:40`; `core/api/portal_views.py:4141`; `start.sh`.

- The client pumps work only while the page is visible and online.
- The pump performs the external publication in a normal Django request. It is background activity from the user's perspective, not a separate worker execution pool.
- A closed/backgrounded Portal cannot drive automatic progress; a manual drain command remains available.
- External calls occupy Gunicorn request capacity. The checked-in startup command specifies two threads and no explicit worker count; deployment environment overrides were not inspected.
- A browser timeout does not constitute proof that the server-side Google call stopped.

Fix direction within the agreed no-cron constraint:

- Describe the availability contract honestly: durable save now, request-assisted publication when a session is available, explicit manual recovery otherwise.
- Keep user workflow saves independent of publication.
- Bound each assisted execution and avoid nested retry loops multiplying request duration.
- Measure queue age, in-flight duration, retries and request saturation before selecting capacity settings.
- If unattended completion becomes mandatory, obtain an explicit decision about an independent execution mechanism; no browser-only mechanism can guarantee it after every client closes.

### EQ-05 — Interrupted invoice ingestion can become stuck behind its replay key

**Priority: P1. Qualities: recoverability, reliability, idempotency. Reproduced.**

Evidence: `core/services/invoice_parser.py:677`.

- A batch is committed as Uploaded before Drive upload and parsing finish.
- Reusing its request key returns the existing batch without checking whether processing finished.
- Ordinary caught upload errors clear the hash/request key, but abrupt process termination does not take that path.
- The synthetic process-stop probe left an Uploaded batch with no Drive file ID. Retrying the same request returned that unfinished batch without another upload attempt.
- A new request for the same bytes can encounter duplicate-file protection instead of a useful resume path.
- A stop after Drive accepts a file but before its ID is saved also creates an orphan-file risk; that particular timing was not exercised here.

Fix direction:

- Distinguish reservation, upload, parsing and completed states with explicit resumability.
- Replay a completed result; resume or clearly report unfinished processing instead of presenting it as complete.
- Bind recovery to the same group, content hash and request identity.
- Use existing durable-operation patterns after fixing EQ-01/EQ-02; do not create a second competing retry architecture.
- Test termination before/after file acceptance and before/after parsed-row persistence.

### EQ-06 — Invoice parser warnings can expose customer data

**Priority: P1. Qualities: privacy, security, supportability. Code-confirmed.**

Evidence: `core/services/invoice_parser.py:659`.

- An unparsed page logs the first 300 characters of extracted invoice text.
- That text can contain names, national IDs, phone numbers and financial values.
- This contradicts the repository's privacy-safe diagnostic requirement. This audit did not access production logs or establish what they currently contain.

Fix direction:

- Log a safe batch reference, page number, parser version and failure classification—not extracted document text.
- Restrict any deliberate diagnostic document inspection to authorized evidence access.
- Add a log-capture regression test containing synthetic identity/financial markers and assert none are emitted.
- Review log retention/access and any historic exposure with the responsible administrator; do not delete operational logs without a governed decision.

### EQ-07 — PDF limits do not bound all expensive processing

**Priority: P1 hardening. Qualities: stability, resource efficiency, abuse resistance. Code-confirmed missing bounds; exhaustion not executed.**

Evidence: `core/services/secure_media_preview.py:15`; `core/services/invoice_parser.py:659`; `core/api/portal_views.py:6730`.

- Preview limits source bytes, pages and compressed rendered output, which is useful.
- Page rendering occurs before any explicit page-dimension/pixel-allocation check. A small PDF can describe very large pages.
- Invoice parsing iterates every page synchronously. The upload endpoint processes multiple files serially in one request.
- Per-file size checks do not establish an aggregate byte, page, rendering-memory or processing-time budget.
- Framework upload limits still apply; this is not a claim that arbitrary file counts are accepted.

Fix direction:

- Check page dimensions and total pixel budget before rendering; release page/bitmap resources explicitly.
- Define aggregate request limits and a parser page/time budget with clear partial-processing feedback.
- Move genuinely large batch parsing into bounded resumable work, without making canonical intake depend on a long browser request.
- Exercise many small files, high-page-count PDFs, giant page dimensions, corrupt/encrypted PDFs and cancellation using synthetic fixtures.

### EQ-08 — Payment pagination is presentation-only

**Priority: P2. Qualities: scalability, performance, maintainability. Code-confirmed.**

Evidence: `core/api/portal_views.py:5436`, `:5502`.

- Payment batches and related memberships/reviews are prefetched before the visible page is selected.
- Each eligible batch is scope-checked and serialized, counts are calculated in Python, and only then are ten results sliced out.
- Correct authorization is essential, and the recent scope exclusion is valuable. However, the cost grows with all eligible historical batches, not the ten displayed.
- No production latency or memory benchmark was run; this is an identifiable growth pattern, not a measured outage.

Fix direction:

- Express whole-batch authorization and queue membership in scoped queries/services before pagination.
- Aggregate counts separately; serialize only the selected page.
- Preserve the complete-grant scope contract—do not optimize by combining unrelated branch/product grants.
- Establish query-count and response-size checks at 10, 100 and 1,000 synthetic batches.

### EQ-09 — Checks configured in CI currently fail

**Priority: P1. Qualities: deployability, upgradeability, governance. Reproduced.**

Evidence: `.github/workflows/ci.yml`; `scripts/check_dependency_parity.py`; `scripts/check_architecture_boundaries.py`.

- Dependency parity reports `cryptography` missing from Poetry even though it is declared in `requirements.txt`.
- It also labels six repository-owned domain packages as unmapped external imports. These are checker-classification gaps, not six missing third-party libraries.
- Architecture checking reports five direct ORM creation sites in Portal views: lead/customer creation, order finalization and order numbering.
- The configured CI runs both checks. This checkout therefore fails those gates when executed as configured; this is not a claim to have inspected a remote CI run.

Fix direction:

- Align dependency manifests and teach the checker about the existing first-party apps.
- Move the identified business mutations into their owning services; do not simply bless a new baseline to make the check green.
- Add small tests for first-party dependency discovery and service-boundary enforcement.

### EQ-10 — Database and coverage checks do not fully mirror production architecture

**Priority: P1 validation gap. Qualities: testability, reliability, portability. Code-confirmed.**

Evidence: `.github/workflows/ci.yml:94`; `config/settings_test_postgres.py`; `scripts/test_postgres.ps1`.

- The checked-in CI has no PostgreSQL service/test URL configuration; its Django run uses the default SQLite path.
- PostgreSQL-specific locks, joins, constraints and concurrent transitions cannot be established by SQLite results.
- Coverage is collected with `--source=core`: tests can still execute bounded apps, but their code is outside that measured coverage source.
- The correctness lint step similarly names `config core scripts`, not all bounded domain apps.
- A guarded local PostgreSQL test runner already exists; production-shaped testing need not introduce another hosting service.

Fix direction:

- Add a disposable PostgreSQL CI job for affected transactional boundaries and migrations.
- Include owned domain apps in lint and coverage accounting.
- Retain fast SQLite/unit tests where useful; do not mistake them for locking tests.
- Test fresh-database migrations and upgrade from a representative prior schema with synthetic records.

### EQ-11 — Architecture is expensive to change safely

**Priority: P2. Qualities: maintainability, modifiability, comprehensibility. Code-confirmed structure.**

- `portal_views.py` is about 9,500 lines; `core/admin.py` about 12,600; `core/models.py` about 9,200.
- Several individual views span more than 100 lines and mix authorization, query assembly, orchestration, mutation and response formatting.
- Size alone is not a defect, but EQ-09 demonstrates that business-boundary drift is already occurring.
- Existing bounded apps for payments, HB operations, requisitions and recognition provide a sound incremental direction.
- Repository guidance also contains an older new-workflow instruction to put models in `core`, conflicting with its newer quick-reference rule requiring bounded-domain apps.

Fix direction:

- Extract one workflow boundary at a time behind unchanged endpoint contracts.
- Centralize queue/state projections rather than copying state rules into views, cards, reports and notifications.
- Keep shared authorization and complete-grant scoping explicit in service interfaces.
- Reconcile contradictory contributor instructions. Avoid a big-bang rewrite or new frontend framework.

### EQ-12 — Upgrade and restore readiness need a stronger operational contract

**Priority: P2. Qualities: upgradeability, reproducibility, recoverability. Mixed code evidence and unverified operations.**

- Requirements and Poetry disagree (EQ-09); `psycopg[binary]>=3.1.0` remains broadly ranged.
- Python metadata targets 3.12; CI runs 3.12. Local interpreter/deployment parity must be deliberately controlled rather than inferred from a successful install.
- Dependabot currently covers pip only, monthly; npm dependencies and GitHub Actions are not covered by that configuration.
- Vendored UI assets have useful pinned versions/licenses, but require a coordinated update process separate from npm updates.
- Release tooling records migration plans and backup evidence, and an explicit no-backup override. This is better than ungoverned startup migrations.
- Backup evidence does not prove restore success. Real restore duration, recovery-point objective, hosting worker settings and external orphan reconciliation were not verified.
- Not attempting automatic migration rollback is not itself a defect: destructive reverse migrations can make recovery worse.

Fix direction:

- Choose a canonical dependency/lock policy and test supported Python/Node/PostgreSQL versions explicitly.
- Extend existing update tooling to the missing ecosystems; review vendored licenses/version fixtures alongside upgrades.
- Rehearse restore into an isolated environment and record achievable recovery time/data-loss bounds.
- Document forward-fix versus restore decisions and how to reconcile Django document references with existing Drive files after recovery.

## Preserve these strengths

- Django remains the workflow source of truth; publication is represented separately.
- Capability checks are separate from Telegram identity verification; scoped services exist rather than relying only on hidden buttons.
- Exact signed-document/version governance, Decimal money handling, official numbering and append-only workflow evidence are valuable integrity boundaries.
- Durable operation and circuit records provide a useful base for recovery and support, once claim fencing is corrected.
- Local vendored assets, browser failure artifacts and synthetic integration fixtures reduce field-connectivity and privacy risks.
- Release migration inspection, database catalogue checks and explicit administrative overrides improve operational accountability.

These are foundations to retain, not a certification that every call site was exhaustively verified.

## Recommended remediation sequence

1. **Restore trustworthy gates:** dependency classification/parity, architecture violations, bounded-app coverage/lint and PostgreSQL transactional tests.
2. **Fix operation ownership:** locked claim eligibility and fenced completion, including late workers and exhausted budgets.
3. **Fix invoice recovery/privacy:** resumable unfinished batches, safe logging and aggregate PDF processing bounds.
4. **Improve queue isolation/capacity:** destination FIFO, bounded assisted execution and honest liveness/status feedback without adding cron implicitly.
5. **Bound list costs:** database-backed scoped payment pagination and representative synthetic scale checks.
6. **Reduce change risk incrementally:** workflow service extraction, contributor-rule alignment, dependency-update and restore rehearsals.

## Exit criteria for a future fix pass

- Concurrent PostgreSQL tests cannot execute completed/dead-letter work again or overwrite a newer result with an old attempt.
- An interrupted invoice upload can be resumed safely, without false success, duplicate rows/files, or permanent duplicate-hash lockout.
- Parser logs contain no synthetic customer identity/financial markers.
- Every processing request has explicit byte/page/time/memory budgets before expensive work.
- Healthy destinations progress while an unrelated destination backs off; FIFO remains correct within each register.
- Payment page cost is bounded by its page size plus deliberate aggregate queries, not all historical memberships.
- CI gates pass for actual first-party modules and exercise PostgreSQL-specific behavior.
- Queue liveness, supported runtime versions and recovery expectations are documented and tested, not implied by UI wording.

## Still unverified

- Production throughput, queue-age distribution, Google quota use and external call duration.
- Actual multi-process PostgreSQL interleavings and production worker configuration.
- Real Telegram WebView memory/lifecycle behavior under these processing loads.
- Hosting backup policy, restore time, historic parser-log exposure and orphan Drive files.
- Any claim of full penetration testing, exhaustive workflow verification or production readiness.
