# Origination readiness review — 15 October 2026

## Verdict and scope

**Not ready for an unconditional production sign-off, even excluding actual OTP signing.**
The main capture, document and access-control paths have substantial working coverage.
However, an interrupted evidence upload can remain stuck and falsely show success,
ordinary application cancellation is missing, queue work scales with the entire
authorized workload, and deployed recovery/device/concurrency checks remain unverified.

Reviewed baseline: `d9e8ba3c`, followed by the explicitly requested Origination-only
card/identity and signature-free document-publication changes in this worktree.
Portal was not changed. TAT, Complaints, Portal and Origination grants remain independent.

No real SMS, Telegram notification, Drive/Sheet write, production database inspection,
deployment or migration was performed. Test documents and identities were synthetic.
Actual OTP/carrier delivery and the legal sufficiency of e-signing are outside this review.
Mocked signature/configuration tests do not certify either of those things.

## What is working locally

| Area | Current behavior and evidence | Limit |
| --- | --- | --- |
| Product/document setup | Product terms and the independent document editor remain separate. Copying a published document retains placement; publication keeps historical versions. Unsigned document publication passes service and browser tests. | A published document is not automatically compatible with a product's application/signing contract. |
| Application capture | A selected Main LAF, supporting documents, schema, terms and signer rules are captured on the application. Placement-driven inputs hide unplaced nonessential fields without deleting historical answers. | This is not an end-to-end certification of every configured product. |
| Validation and drafts | Typed server validation, field-keyed errors, revision conflicts, conditional/repeating fields and saved local recovery have focused coverage. Browser checks retain input on failure. | Physical Telegram keyboard/autofill and interrupted mobile sessions remain unverified. |
| Identity evidence | Genuine file-content checks, size/hash limits, optional borrower/guarantor ID pairs and front/back collation exist. Changed identities cannot silently reuse old ID evidence. | Interrupted upload recovery has the confirmed defect below. |
| Access and privacy | Owner, branch, group, product and capability checks use Origination grants. Full-access cards now show complete IDs/phones; explicitly restricted views remain masked. | PostgreSQL and live staff-grant variations still require staging checks. |
| Queues and filters | Two primary queues, contextual product/status filters, ten-row paging, owned-case restrictions and actionable signing tasks have tests. | Paging limits response rows, not all work done to calculate the queue. |
| Preview/download | Local PDF rendering, unsigned/approved application copies, access-checked expiring links, revision checks and private responses have coverage. Toolbar zoom/navigation and mobile ID capture have browser checks. | A browser response is not proof a file saved/opened successfully on an Android/iOS Telegram device. |
| Approval/history | Existing completion-policy snapshots remain authoritative. Revisions, signed bytes and previously captured requirements are not silently converted by authoring edits. | Actual OTP and end-to-end production signing were excluded. |
| Background publication | Durable integration operations retain attempts and leases. Archival is separate from approval; recovery settings expose the existing archive action. | An always-running deployed processor and idle/restart recovery were not verified. |

## Confirmed findings and priorities

### OR-01 — Evidence upload can falsely report success (high)

`origination/views.py` deliberately returns HTTP 202 with `ok: false` and
`pending: true` while an evidence upload is incomplete. In
`loan_origination.js::uploadEvidenceFile`, a successful HTTP transport is enough
to show **“Evidence uploaded securely.”** The application response's pending/error
state is not checked before that toast.

Reproduction executed the actual JavaScript upload handler with a synthetic XHR
response: HTTP 202, `ok: false`, `pending: true`. Observed toast:
`Evidence uploaded securely.` This is a real response-contract defect, not a
visual opinion or an inference from a failing wording assertion.

Fix boundary: distinguish uploaded, pending and failed results; preserve the
selected file until confirmed; refresh the saved evidence state without claiming
success. A pending response must not unlock a requirement or imply storage is complete.

### OR-02 — Interrupted evidence uploads have no resumable recovery (high)

`origination_evidence._reserve_upload` returns an existing request-keyed upload
reservation. `upload_requirement_evidence` immediately returns on replay, even
if that reservation is still pending. If a worker dies after reservation but before
storage/finalization, the same retry never resumes that upload.

Synthetic database probe: reserved a pending upload, retried the same request key
with the same PDF, and mocked the storage call. Result:
`status=pending`, `replayed=true`, **zero storage calls**. Existing recovery covers
approved-document archival, not these abandoned evidence reservations.

Fix boundary: a bounded lease/reconciliation protocol for the same upload identity;
do not blindly re-upload on every replay. Concurrent retries must not duplicate
Drive files, and a provider success followed by database failure needs reconciliation.
Known failed uploads may use a new user request today; that does not repair an
abandoned pending reservation or prove an earlier external upload never happened.

### OR-03 — Normal officers cannot discard an unwanted application (medium)

There is no ordinary cancel/discard route or officer action. “Withdraw for changes”
returns eligible applications to Draft; it does not close them. `cancelled` is used
when replacing an application with a new Main LAF, not as a general officer action.
Superuser-only testing deletion is not a substitute for business cancellation.

Fix boundary: explicit, revision-checked cancellation with confirmation and clear
eligibility. Retain history, retire outstanding links/tasks, and do not let this
become deletion of approved documents. Keep withdrawal-for-editing distinct.

### OR-04 — Ten-row pagination still does workload-wide processing (medium)

The application list calculates actionability and counts before pagination.
Legacy review work performs package queries per authorized candidate.

Measured with the real list view and an Operations user, synthetic legacy
`ready_for_review` applications, returning ten rows in both runs:

| Authorized applications | SQL queries after the card change |
| --- | --- |
| 10 | 162 |
| 100 | 267 |

These are query-count probes, not production latency measurements. The card change
removes double serialization of each returned row (previously 171/276 queries in
the same probe), but does not solve the workload-wide scan.

Fix boundary: aggregate counts, prefetch the actual package/action facts, and bound
candidate work while preserving complete grant tuples and exact next-action semantics.
Add a query-growth budget and realistic PostgreSQL load checks.

### OR-05 — Regression and live-authoring assurance are not yet clean (medium)

The broad baseline audit ran 545 checks: **525 passed, 12 failed, 3 errored,
5 skipped**. These are baseline results, not the result of a clean full rerun after
the present changes. The concise queue-label failure is fixed and rechecked here.

The remaining non-passing baseline checks include stale static asset/copy assertions,
old product-owned document setup expectations, an outdated model inventory,
validation-message assertions and demo/activation fixtures that no longer supply
the governed product/document contract. They must be updated or investigated at
their actual boundary; they are not fifteen demonstrated production defects.

Three real HTTP/Admin browser journeys were also attempted:

- Edit/review/apply/withdraw maintenance: passed.
- Custom PDF journey: stopped at the obsolete `document-lending-fields` button,
  which was intentionally removed. The script cannot certify the current journey.
- Published-document attachment journey: selection autosaved, but product Publish
  stayed disabled. Screenshot triage showed that its synthetic document had only
  an Officer signer: the current product contract requires an applicant and a JBL
  signer. This fixture does not demonstrate a valid product being blocked.

Replace the obsolete steps/fixtures and repeat real-server custom upload → signer
configuration → field placement → preview → document publish → product attachment
→ product publish → application creation. Do not remove application safety checks
merely to make an outdated fixture pass.

### OR-06 — Deployment assurance remains incomplete (release prerequisite)

Local execution used Python 3.14/SQLite; the release pins Python 3.12.3 and uses
PostgreSQL. SQLite cannot establish row-lock/concurrent-first-request correctness.
The build has signature-asset and PDF smoke checks, Django checks, migration drift
checks and static collection. Those are useful but are not deployed workflow proof.

Durable Origination work can be woken by a bounded thread, a later authorized
request or `process_origination_deliveries`. No evidence was obtained that the
deployed environment drains it reliably when nobody opens the app. Verify the
runner, leases, retries, dead-letter monitoring and worker-restart behavior.

Before release, exercise the production-like PostgreSQL/Python stack, native
Telegram downloads/camera/pinch/swipe on Android and iOS, and cold/idle/restart
recovery with synthetic staging records and explicitly authorized provider writes.

## Explicitly requested changes implemented with this review

- Origination cards show full IDs and clickable phone numbers for users with
  existing full-case authority. A separate phone link does not also open the card.
- Cards use the compact identity/status/metadata arrangement from the TAT/Complaint
  pattern. ID/phone align; repeated queue heading/count is hidden accessibly;
  header Settings remains on its row; dark-mode card links have readable contrast.
- Removed duplicate competing card styles instead of adding another override layer.
- Documents may publish with no signers, only optional signers, or unfinished
  signature placements. Removed the generic “Add a signer” warning and display
  “No signatures required” when appropriate.
- Removing all signers from an editable copy removes that copy's signing placements;
  the original published version and historical application requirements survive.
- Source integrity, valid supplied geometry, authorization, revision and shared-change
  confirmation checks remain. Publishing a document does not approve an application.

The other audit findings are recorded, **not silently implemented**: the audit request
did not authorize a new cancellation policy or a wider upload/recovery refactor.

## Verification and handoff

The final focused run on a fresh database passed **127 backend checks**, with one
PostgreSQL-only skip. All **46 Playwright checks** passed. Python/JavaScript syntax,
Django configuration, migration drift and diff checks passed. Details are recorded
in `CHANGELOG.md` and `KNOWN_GAPS.md`.
The three Playwright suites use actual templates/controllers/styles with mocked
API data; they are separate from the real-server Admin attempts above. Screenshots
were inspected at narrow mobile, dark mode and desktop widths. Only synthetic
names/IDs appear in these artifacts under ignored `test-results/`.

The repository-wide route inventory still reports 34 omissions and the actual
artifact checker reports 17 existing hash mismatches. The affected routes/assets
were not changed here. These global gates are not claimed to pass.

Recommended order: repair upload response handling and resumability first; define
ordinary application cancellation; bound queue calculations; restore a trustworthy
current-contract end-to-end suite; then perform production-like/device/recovery
checks. Keep OTP/carrier sign-off separate from this non-OTP readiness work.
