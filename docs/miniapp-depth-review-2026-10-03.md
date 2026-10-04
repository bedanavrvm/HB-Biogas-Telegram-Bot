# Complaints, TAT Tracker and Portal: implementation review

Review date: 3 October 2026. Source baseline:
`092ead81c97b6195168a3293c6f2ddd9d1fa23ee`.

This follows the [whole-codebase assessment](codebase-review-2026-10-03.md).
It traces the three Mini Apps through their browser code, authentication,
authorization, persistence, transitions, evidence, reporting and publication.
Executable results below supersede the earlier report's unavailable-runtime
limitations. This review changes documentation and the local development
environment; it does not change application behavior or production resources.

## Review boundaries and environment

- Installed Python 3.12.10 through the official Python winget package and
  created the ignored repository `.venv`.
- Installed the pinned `requirements.txt` packages. `pip check` passes.
- Installed the locked Node dependencies using `npm ci`, including Playwright
  1.62.1, and installed its Chromium browser and headless shell.
- Existing Node is 26.7.0, outside this repository's declared `>=20 <25`
  range. The browser run succeeded substantially, but it is not equivalent to
  the Node 22 CI environment.
- Django checks and migration-drift inspection ran with synthetic settings.
  Backend tests use isolated SQLite databases, not a customer database.
  SQLite does not implement the PostgreSQL table/column comments and produces
  warnings for these declarations. It cannot verify PostgreSQL row-lock
  contention, concurrent sequence allocation or production migration timing.
- The test harness blanks external-service credentials and blocks non-loopback
  socket connections in the parent Django process. Integration tests use
  mocked gateways; local PDF subprocesses receive synthetic input.
- Browser tests use sanitized fixtures and mocked API responses. They do not
  prove a live Telegram WebView, signed production session, Google Drive/Sheets
  integration or real mobile camera/voice behavior.
- Python WeasyPrint is installed, but its import currently fails because the
  Windows Pango DLL is absent. Successful Python package installation does not
  establish working native PDF rendering. The upstream
  [Windows installation instructions](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#windows)
  document the additional Pango/MSYS2 requirement; the repository pin was not
  upgraded during this review.

Local logs, JSON results, traces and synthetic reproduction helpers are under
ignored `test-results/miniapp-depth/` and `test-results/playwright/`. They are
diagnostic artifacts, not production evidence or checked-in customer records.

## Architecture and responsibilities

These are three related operational clients over Django, not three independent
databases. Shared identity and capability services govern access. Each domain
retains its own case state, revision rules, events and publication contracts.
Google Sheets is an external projection; private Drive files are evidence or
published documents rather than authoritative workflow state.

| Concern | Complaints | TAT Tracker | Portal |
|---|---|---|---|
| Primary API | `core/api/complaint_case_views.py` | TAT endpoints in `core/api/views.py` | `core/api/portal_views.py` |
| Domain rules | `complaint_cases.py`, `case_updates.py`, `complaint_timing.py`, `complaint_register.py` | `tat_tracker.py`, `tat_configuration.py`, `tat_responsibilities.py`, `tat_notifications.py`, `tat_update_dispatch.py`, `tat_reporting.py` | `jawabu_pipeline.py`, `jawabu_approvals.py`, `portal_imports.py`, `portal_publication.py`, plus bounded payments/requisition/HB domains |
| Canonical case | `ParsedMessage` with `ComplaintCaseControl` | `TatTrackerCase` with frozen configuration/product snapshots | `JawabuFarmerMaster` with customer/product/location references |
| Native history | `CaseUpdate`, `ComplaintCaseEvent`, evidence records | `TatTrackerEvent`, responsibility/task/dispatch events | `JawabuPipelineEvent`, approval/signoff events, bounded payment/HB events |
| Browser | `complaint_cases.js`, reporting chart module, API wrapper | `tat_tracker.js`, report and recognition modules | `portal.js`, `portal_api.js`, navigation, shared components and feature modules |
| Publication | Complaint snapshot updates, deferred creation finish | Durable update dispatch reservations, Sheet contracts | Durable register reservations and request-assisted publication pump |

The canonical route catalogue is `core/api/urls.py`. Browser entry routes and
logged compatibility aliases are separately declared. Reading a public shell
does not itself authorize private API reads or mutations.

Common request flow is: verify Telegram identity, resolve an active canonical
staff account and grants, authorize the capability and resource scope, bind
the request identity, validate the revision and domain rules, commit Django
state/events, and perform or reserve external publication. The precise order
and replay safeguards differ between services; that variation matters.

## Complaints: end-to-end behavior

### Intake and identity

Complaints arrive through Telegram/forwarded content, an authorized import, or
the Mini App. The Mini App is a structured staff intake path. New intake
requires a primary Kenyan mobile number and a 1-to-9-digit National ID/Maisha
Namba. Identifiers remain strings so leading zeroes survive. Governed complaint
categories and location selections control the remaining validation.

`create_case` normalizes the fields, validates approved voice/category-inference
references when supplied, and creates raw/processed/parsed records, control,
creation history and compliance evidence inside a database transaction.
Mini App creation deduplication includes group plus request identity and a
normalized payload hash. This is stronger than the separate legacy Telegram
deduplication hash discussed in the whole-codebase report.

Staff use sequential references such as `CMP-1`; internal message IDs and UUIDs
remain integration identifiers. Historical Pending rows missing required
identifiers are represented as Needs details and completed through a scoped,
audited, revision-checked action. New incomplete intake is rejected rather
than creating another incomplete workflow row.

### Queue, detail and state transitions

The normal workspace separates Pending and Resolved. Pending is oldest first;
Resolved orders by resolution date descending, then report timestamp and ID.
The active UI uses bounded numbered pages of at most ten rows. The service
also retains cursor pagination; its inconsistent ordering is a finding below.

The complaint group is the deliberate queue boundary: the service does not
filter the shared queue by an officer's branch. This must not be confused with
Portal's capability-specific branch/product scopes. Detail and evidence reads
recheck group ownership and the relevant capability.

| Default business role | Main complaint authority |
|---|---|
| Complaint Officer | View queue/evidence, create, complete historical missing details |
| Complaint Manager | View, create, complete details, reopen, and source-inspection capabilities |
| Complaint HB resolver (`HB_STAFF`) | View queue/evidence, append comments, resolve Pending complaints |
| IT | All complaint capabilities within its active grant scope |
| Active Django Superuser | Explicit technical override with actual actor attribution |

These are code defaults; persisted capability policy remains authoritative.
A Portal HB grant does not provide Complaint HB authority. An HB comment does
not close a complaint, alter resolution details, restart SLA time or represent
an unread-message counter. Badge counts include all saved comments.

Resolve/reopen applies the transition on a locked case/control pair, validates
the expected revision, advances the revision and retains native/compliance
history. Resolving requires HB resolution capability and a resolution note.
Reopening requires its distinct capability and a reason. Closed-to-Closed is
not another resolution. Client-selected state alone is insufficient.

Comment replay compares actor and normalized comment payload. Some older
transition replays compare fewer fields; a single shared transport key does
not mean every service has the same payload-binding contract.

### Timing, reports and evidence

Complaint SLA targets use elapsed calendar hours, not the optional Nairobi
business-hours calculations used elsewhere. `complaint_timing.py` hydrates
history in batches and derives resolution, reopen, first HB response and
on-time facts. Historical HB affiliation comes from retained audit evidence,
not the staff member's current grant. Unknown historical attribution remains
unknown rather than creating false performance facts.

The organization-wide management register is an intentional, capability-gated
read model with allowlisted fields, bounded paging and audited XLSX export.
Charts, drill-down filters and exports share reporting semantics. The current
report has eight chart slides and a separate chart JavaScript module.

Evidence is validated against count, type, per-file and aggregate budgets,
stored privately in Drive and represented by case-linked upload metadata.
Preview checks access, downloads allowed image/PDF formats, records a native
evidence-open event and returns private/no-store content. Portal's stronger
transactional native-plus-compliance media auditing should not be assumed to
exist identically in the Complaints preview path.

Creation has two phases in the current UI: save the complaint first, then
`finish-created` uploads selected evidence and completes deferred publication.
This improves responsiveness but creates a separate recovery boundary. A
complaint may be durably saved while its files/publication remain unfinished.
The selected-file loss on failure is reproduced below.

### Usability and recovery

The UI includes phone normalization, dependent location choices, geolocation,
photo/PDF previews, loading states, duplicate-submit prevention, voice
acceptance/cancellation, close protection and stable plain-language errors.
Content inserted into dynamic markup is generally escaped; generated server
fragments and vendored widget HTML have separate trust boundaries.

Field recovery cannot reconstruct file bytes. A truthful saved-state indicator
must distinguish the complaint commit, evidence acceptance and publication.
Clearing a form after the first phase is safe only if the remaining operation
has a usable recovery mechanism; the current finish handler does not retain
one when its request fails.

## TAT Tracker: end-to-end behavior

### Creation and immutable governing configuration

The Tracker creates a case in a configured group/product/branch after staff
authorization, identity normalization, Decimal amount validation, product
availability checks and requirement/custom-field validation.

Cases retain selected product/version, commercial/quote snapshots, exact TAT
configuration and stage targets. Configuration binding distinguishes versioned,
legacy-assumed and unresolved cases. Unresolved cases are read-only until an
audited reconciliation establishes their governing definition.

The Standard, Standard + Valuation, HOCC and HOCC + Valuation path is selected
from the product version and original requested amount. A later permitted BRO
final amount does not change the frozen path. Product publication and case
creation therefore must not be treated as a mutable global stage array.

Pilot/Production mode and Pilot-cycle scope are immutable creation attributes.
Operational query helpers determine which records are visible; closed cycles
are read-only. Mode-version validation rejects stale clients. A Pilot purge
or testing reset is a separate controlled operation, not normal Mini App
delete behavior.

### Progression and role ownership

Each stage defines its key, kind, responsible role, predecessor and target.
Authoritative stamps complete a stage and start the next. Later-stage edits
depend on predecessor completion, actor capability/scope and current stage
state. Existing completed stamps need correction authority rather than a
normal completion. Final amount and evidence rules remain server-side.

Responsibility routing chooses who should receive the work; it does not grant
authorization. An eligible assignee still needs an active scoped AccessGrant.
Credit-assessment ownership is another explicit boundary: when the governed
assessment owns a milestone, raw manual stage edits must not provide a
parallel route around its evidence/decision controls.

`update_case` locks the case, checks data-mode writability and case access,
validates the expected revision, applies all submitted changes atomically and
records a transition receipt with actor, authority and before/after revision.
The HTTP layer requires revision/request identity under its applicable policy;
the Python service's optional parameters are not a universal permission to
perform unrestricted writes.

Existing receipt replay currently occurs before inspecting the new update
payload. It prevents duplicate transitions but does not distinguish an exact
retry from reuse of the same key for different changes. That is a finding,
not evidence of repeated state mutation.

### Time, reports and recognition

Canonical TAT is elapsed wall-clock time between authoritative timestamps.
`minutes_between` uses Decimal and clamps negative durations; stage/overall
seconds derive from the same persisted clock. Business-time figures use the
Nairobi calendar as a separately governed, optional presentation. Enabling
business-hours visibility does not silently redefine canonical TAT.

Reports cover workload, stage/role/branch/product cohorts, SLA state, duration,
target use, corrections, backlog and heatmaps, with bounded date/filter
contracts and audited exports. Named-person views need their own capability.
Statistical target-review signals are informational, not automatic policy
changes. There is no persisted pickup timestamp, so reports must not invent
handoff lag by subtracting arbitrary UI events.

Recognition is distinct from raw workload reports. Final period snapshots
freeze group facts after the defined post-period window, while current grants
still filter what each viewer may see. Live rank checkpoints are expiring,
viewer-scoped movement aids; they are not authoritative final scores.

The report queryset has an important exception to the usual grant-tuple
discipline: it combines all active TAT grant scopes without selecting only
grants that authorize the report capability. The reproduction and impact are
described below.

### Private tasks and external effects

TAT maintains durable private tasks and recipients, opaque deep-link locators,
delivery attempts, retries, backup escalation and privacy-reduced group
exceptions. Task visibility and action authority are checked independently.

Updates reserve durable external dispatches by case/revision/effect. Sheet
publication, certificate work and notifications can retry without reapplying
the workflow transition. Claims and leases prevent multiple processors from
owning the same attempt. Failure or needs-attention state remains inspectable.

Request-assisted processing improves ordinary responsiveness but cannot prove
unattended delivery when no eligible request or configured runner executes.
Production readiness must include scheduler/heartbeat evidence and expired
lease/retry behavior; source presence alone is insufficient.

Creation differs from these durable update effects: the ordinary create
endpoint calls atomic `create_case`, which synchronously publishes when its
group has Sheet projection enabled, unless the defer flag is supplied. A
sync error rolls back that Django transaction. Django-only groups bypass the
publication, and batch intake uses the deferred path. An external write
accepted just before a timeout cannot be rolled back with the database;
orphaned publication and uncertain retry outcomes are therefore a source-based
reliability concern, not a reproduced live incident. Preserve case-ID-led row
matching and review this creation boundary separately from the update outbox.

The frontend keeps pending creation identity in session storage and report
preferences locally, cancels stale report requests, handles conflict/reload
messages and renders authorized stage controls. These are recovery aids,
not substitutes for server-side revision or replay binding.

## Portal: end-to-end behavior

### Canonical pipeline and domain boundaries

Portal projects the Jawabu/HomeBiogas customer pipeline. Its surface includes
dashboard tasks, FarmUp/SysUp intake, JBL visits, credit, final decisions,
requisitions/orders, invoices, payment batches, HB installation/commissioning,
history, scoped reports, recognition and authorized Origination access.

Canonical cases retain UUID integration identity, short staff reference,
immutable intake identity/provenance and current applicant/customer identity.
`JawabuFarmerMaster` has a group owner as well as branch/product references.
Exact normalized National ID is the automatic customer reuse key; household
links preserve distinct legal identities rather than merging by phone.

| Step | Governing behavior |
|---|---|
| FarmUp/SysUp | Stage immutable file versions, review/validate, commit canonical rows, archive privately; Google publication is a separate outcome |
| JBL visit | Validate actor, case revision, required visit facts and current capture contract; retain case-linked ID/LAF/photo evidence |
| Credit/final review | Enforce stage eligibility and scoped capability; retain approval conditions, exact reviewed facts and invalidation history |
| Requisition/order | Finalize the exact workbook, allocate group sequence transactionally, require acceptance of its signed/stamped scan |
| Invoices | Parse within shared delivery/page/time budgets, bind original bytes/hash and resumable acceptance checkpoints; preserve identity review/replacement chains |
| Payment | Each case chooses LOAN-JAWABU or CASH; Head of Rural reviews payment facts, then a reviewed workbook receives the official number; signed scan locks membership/finality |
| HB Action | Enter only through the accepted official requisition version; validate installation/commissioning chronology and correction rules; publish one way |

This is a workflow with explicit gates, not a collection of editable Sheet
cells. Correcting financial, identity or evidence facts may invalidate approvals
and generated documents. Changing an unrelated pipeline revision should not
invalidate a payment review when its governing payment facts are unchanged.

### Authorization and administrative separation

Portal capabilities are resolved from complete grant tuples. A role, its
branch/product/group restrictions and the requested resource must belong to
the same eligible grant. Scoped IT is powerful within its scope; Django staff
status is not that workflow role. An active Superuser is the explicit technical
override. Business users do not acquire every capability from their UI label.

Head of Rural maps to `BUSINESS_ADMIN` and owns final/payment approvals.
Operations Administrator prepares operational items without inheriting those
approvals or JBL visit logging. Origination BM/Management signer roles do not
inherit TAT responsibilities or packet preparation/dispatch authority.
Temporary delegations and exceptional corrections retain separate audited
authority, expiry and scope contracts.

The central Portal case queryset currently supplies branch and product fields
to the generic resolver but omits the case group field. The generic resolver
correctly rejects grants whose group cannot be enforced; the result is an
empty queue for a group-only staff grant even when item authorization permits
its case. This is a functionality defect that fails closed, not a demonstrated
cross-group disclosure.

Maintenance mode is a durable, IT-controlled read-only policy. It blocks
applicable writes through the API boundary rather than relying on disabled
buttons. Controlled Portal reports are IT-only and catalogue-constrained;
they are not an arbitrary SQL builder or an automatic cross-workflow identity
join.

### Documents, identity and financial integrity

Current visit intake requires separate front/back Client ID and two LAF page
captures. Local collation generates protected case-linked PDFs; stale clients
using the older aggregate LAF field are deliberately rejected. Photograph
type/size validation and generated-document page budgets are meaningful
boundaries in addition to multipart request size.

`jawabu_media_access.py` performs fail-closed transactional native and
compliance auditing for Portal evidence retrieval. Private preview endpoints
recheck capability and case ownership and do not make Drive IDs public access
credentials.

Invoice-name changes preserve the original invoice, applicant/household link,
letter versions and replacement relationship. SysUp owns canonical applicant
identity; payment remains blocked until the required corrected invoice is
confirmed. Restricted cleanup must preserve payment/identity evidence and
shared PDFs.

Canonical quotes, payment facts and financial database fields use Decimal.
The legacy `actual_receipts` fallback before requisition preparation still
parses through float, as identified in the broader report. This inconsistency
requires a bounded normalization fix; this review did not reproduce an
incorrect disbursement.

### Reliability, recovery and presentation

`portal_api.js` applies a 20-second ordinary request timeout, abort/retry
handling and request identity retention for ambiguous writes. A timed-out
client is not proof that the server rolled back. Multipart operations can
choose a distinct timeout policy while the server enforces its own budgets.

The publication pump uses a cross-tab local lease and server claims; it runs
only when a tab is visible/online. Canonical commits remain successful when
Google publication fails. The durable reservation can be retried, but its
existence does not guarantee eventual publication without an executing
request/processor.

Recovery drafts are user-owned, field-only, revision-aware and expire after
seven days, with a 250 KB payload budget. Attachment keys and data URLs are
rejected. Users must select files again after recovery. The bounded Case
History detour preserves the originating form in memory and guards stale
responses; it is not an unlimited navigation cache or durable attachment
store.

Dashboard/inbox counts and paged responses are scoped, but the complete task
list is assembled in memory before pagination. Large groups can therefore
pay query/object-building cost even when requesting ten items. This is a
scaling hypothesis supported by the query structure, not a measured production
latency or memory incident.

Pinned local HTMX, Lucide, Leaflet, Chart.js and shared framework-free controls
avoid runtime CDN dependence. Network-independent assets do not make the
business API offline-capable. Navigation, server fragments, maps and evidence
still need their respective runtime data contracts.

## Findings and reproducibility

| Priority | Finding | Evidence status | Operational effect |
|---|---|---|---|
| High | TAT report scopes include non-reporting grants | Reproduced against isolated synthetic rows | A report-authorized staff member can see cases from a second grant that permits ordinary TAT work but not reports |
| Medium | Group-scoped Portal case queues omit group mapping | Reproduced against isolated synthetic rows | Eligible staff receive empty queues despite being allowed to open the same owned case |
| Medium | Failed complaint finish clears selected evidence | Executed current handler with a synthetic rejected upload | Complaint remains saved, while selected files and a usable retry action are lost |
| Medium | TAT replay does not bind changed update payload | Reproduced with a synthetic legacy-assumed case | Reusing a key for a different change returns success without applying the submitted change |
| Medium | Complaint compatibility cursor disagrees with queue sort | Pending case reproduced; resolved case is a source finding | Pending cursor traversal loses later rows; resolved cursor does not encode the primary sort key |
| Release gate | Mini App write inventory misses 27 routes | Official Python checker failed | Governance/readiness checks are stale; this does not establish that each endpoint is unguarded |
| Release gate | Dependency exception expired 30 September | Official checker failed before audit invocation | CI vulnerability gate stops; no fresh advisory-resolution conclusion is claimed |
| Release gate | Environment template differs from settings | Official parity checker failed | Operators lack a complete current template for configuring the deployed workflows |
| Verification | Backend/browser tests are not all green | Fresh result details below | Passing selected suites cannot be presented as a complete release acceptance |

### TAT report scope composition

Give a user MANAGEMENT/report authority for Nakuru and BRO authority for Embu
in the same TAT group. Embu is outside the user's report-capability grant.
`workflow_access_decision(..., 'tat.reports.view', resource=embu_case)` denies
that case. However, `tat_reporting.scoped_cases` ORs both grants and includes
it. Report endpoints first authorize report entry and then call this queryset
without passing only the report-eligible grants.

An entirely unscoped ordinary TAT grant can widen the same queryset further.
Named-person export scope deserves the same capability-specific treatment.
The corrective boundary is the reporting queryset and metrics/snapshot scope,
using complete eligible grants; changing only the UI or endpoint-entry check
does not address row visibility.

### Portal group scope mismatch

Create a synthetic case owned by a Portal group and give an active user a
group-scoped IT grant. Individual `portal.case.read` resolution accepts the
case. `scope_portal_case_queryset` returns zero rows because it passes no
`group_field`, and `scope_workflow_queryset` skips a grant whose group it cannot
filter. A fix must provide the correct group relation and preserve the
existing branch/product tuple semantics; removing the restriction is unsafe.

### Complaint evidence recovery

The current `finishCreatedCase` catches a failed `finish-created` request,
shows a needs-attention notification, and always invokes
`clearEvidence('create')` in `finally`. Creation already reset the form and
settled its pending creation key. The executed disposable Node probe extracts
the current function and verifies that a rejected upload clears the selection
without offering a retry callback. It does not emulate a live Drive failure.

Preserve selected files and the original creation identity until upload
acceptance is confirmed, offer a retry that cannot create another complaint,
and show publication separately. Server drafts must remain field-only unless
a separately governed evidence-staging design is introduced.

### TAT receipt identity

For a successful update, repeat its request ID with a different/invalid field
value and the original revision. The service finds the transition receipt,
reserves effects and returns detail before it examines that new value. The
row remains unchanged and the response looks successful. Bind actor and a
canonical update/evidence payload digest to the receipt, preserving exact
retries and rejecting mismatched reuse. Existing client key generation lowers
the accidental collision likelihood but does not enforce the server contract.

### Complaint cursor order

With two Pending cases at distinct timestamps, request `limit=1` without a
numbered page and follow its nonempty cursor. The first page chooses the
oldest row; the cursor then filters for timestamps older than that row and
the next page is empty. Numbered page 2 returns the missing newer case.
For Resolved, the order begins with `date_resolved` but the cursor contains
only report timestamp and ID. The active numbered UI limits present impact;
the advertised compatibility/API path remains inconsistent.

## Verification record

The isolated runs completed. Result logs are kept separately so failure traces
do not become customer-facing operational documentation. Failure counts below
are unittest failure entries: several are subtests of one test method, so they
must not be subtracted from `tests_run` to infer a precise passed-method count.

| Check | Result |
|---|---|
| Python requirements | Installed; `pip check` passes |
| Playwright/Chromium | Installed and executable |
| Full existing browser suite | 186 tests: 185 passed, 1 failed, 0 skipped/flaky |
| Complaints/TAT/shared backend selection | 504 tests: 12 failure entries, 6 errors, 2 PostgreSQL-only skips in the initial run |
| Portal/finance/HB backend selection | 456 tests: 25 failure entries, 3 errors, 3 skips |
| Four focused defect reproductions | Four passed; assertions document the observed defects, not corrected behavior |
| Logging-contract recheck | Two passed after correcting the diagnostic harness's logging suppression |
| Django system check | Pass with synthetic settings |
| Model/migration drift | `makemigrations --check --dry-run`: no changes |
| Migration graph | Pass: 240 migrations including Django dependencies, 13 leaves; both broad test databases applied migrations |
| Python syntax | Local app/config compilation passes |
| Architecture boundaries | Pass |
| Direct dependency parity | Pass, 27 direct packages |
| Database governance checker | Pass; app-label coverage limitations from the broader review still apply |
| Mini App write inventory | Fail: 27 uninventoried unsafe-method routes |
| Environment-template parity | Fail: 116 missing/unread environment-template entries |
| Dependency vulnerability gate | Fail before audit: expired `PYSEC-2026-3412` exception |
| WeasyPrint native import | Fail: missing Windows `libpango-1.0-0` |

The browser failure is
`miniapp_flows.spec.js:1062`, Complaint management report scrolling/back
navigation. Its fixture strips template scripts but does not load the current
`complaint_report_charts.js`, supplies an older summary without timing metrics,
and still expects `1 of 2` charts while the current template has eight.
The captured page shows a missing-metric exception before carousel setup.
This is evidence of a stale fixture/contract test, not proof that the live
report renders eight slides simultaneously. All eight newer
`complaint_reporting.spec.js` tests pass.

Browser coverage also passes all 26 TAT recognition layout tests, 26 Portal
case-navigation tests, 17 inbox tests, 14 nested-finance layout tests, eight
finance-action tests and the asynchronous guard checks. Most cases use
mocked data, so passing them does not validate backend permissions or commits.

### Backend failure classification

The two broad selections executed **960 tests**, without claiming a full
repository test run. The first selection covers Complaints case services,
timing/register/category inference; TAT workflow, notifications, dispatch,
production/report presentation and recognition; data modes, authentication,
capabilities, history/SLA, messages, diagnostics and drafts. The second covers
pipeline, Portal dashboard/roles/publication/engineering/approvals/imports/
reporting/navigation/corrections, invoice identity, signoffs, visit documents,
payments and HB operations.

Two of the first run's 12 failures were caused by the diagnostic harness
globally disabling logging. That prevented `assertLogs` from observing
expected events. The harness was corrected without changing application code;
both logging-contract tests pass on recheck. These two are **not application
defects**. The remaining broad-run failures/errors were not made green by
changing validation or weakening tests.

| Group | Observed evidence and classification |
|---|---|
| Complaint modules | No failure/error entries in the selected complaint modules. One comment/resolve concurrency test is skipped because SQLite lacks PostgreSQL row locks. The older complaint failures recorded in `KNOWN_GAPS.md` were not reproduced by this selection. |
| TAT templates/notifications | Five assertions expect older CSS/JS cache versions, recognition wording or an earlier report presentation string. These are source-string expectations requiring contract review, not demonstrated workflow corruption. |
| TAT identity fixtures | Two errors submit identifiers rejected by the current 1-to-9-digit policy. One error uses a mocked Sheet sync that supplies no accepted row number. The validator and creation checkpoint must not be bypassed to satisfy these fixtures. |
| TAT stage/signature progression | Two failing predecessor assertions and three stage-update errors remain around BRO application/Register approval. Fixtures and governed stage/timestamp expectations need reconciliation; this review does not declare them harmless or remove gates. |
| Capability manifest test | The test looks for Portal endpoints in `core.api.views`, while `portal_invoice_receipt_item_preview` exists in `portal_views.py`. Its module resolver is stale; the missing write inventory is a separate, real governance failure. |
| History and daily metrics | A timeline test expects a provenance entry and a daily snapshot test gets no rows. Both remain unresolved regression/fixture-policy questions; no performance or audit correctness claim relies on their passing. |
| Portal stale client/shell contracts | Requisition tests receive the current 426 response; several assertions expect old CDN text, retired Case History screens, report route contexts, date labels or exact markup classes. They need contract-aware fixture updates. |
| Portal invoice prerequisites | Matching/confirmation fixtures lack a finalized official requisition or its current membership. Existing gating rejects them; one fixture raises `InvoiceMatchEligibilityError`. |
| Portal remaining behavior assertions | Protected invoice preview returns 503 in its mocked test; order-validation error precedence differs; an IMAB rejection expects `Pending` but retains a blank prior decision. These need narrow investigation rather than being automatically assigned to the native PDF limitation. |
| HB acceptance hook | Two errors are the same inherited test: the fixture sets source checksum to 64 `a` characters for bytes `workbook`. The actual SHA-256 differs, so the exact-workbook acceptance guard correctly rejects the mismatch. |
| Platform skips | Two Portal PostgreSQL claim/schema tests, two Complaints/TAT concurrency tests, and one native WeasyPrint layout test were skipped. |

The final four reproduction checks use tables created from current models and
explicit synthetic capability fixtures, without replaying historical data
migrations. The two broad selections did apply the migration history. This
distinction prevents the quick reproduction harness from being presented as
an independent migration test. An earlier diagnostic discovery also included
existing fixture test classes; its repeated results are excluded from the
960-test total.

The four probes demonstrate: an empty second Pending cursor page while
numbered page 2 contains its missing case; a group-scoped Portal item allowed
but absent from its queue; a TAT report row admitted although report capability
denies that row; and a changed TAT retry returning unchanged state/success.
The additional disposable Node probe demonstrates the finish-upload selection
loss. Their success indicates successful reproduction of the defects.

### Source locations for bounded fixes

- [TAT reporting scope](../core/services/tat_reporting.py#L85) and
  [report entry authorization](../core/api/views.py#L760).
- [Portal case queryset mapping](../core/services/portal_permissions.py#L94)
  and [generic group enforcement](../core/services/workflow_access.py#L197).
- [Complaint finish-upload handler](../core/static/miniapp/complaint_cases.js#L1040).
- [TAT update receipt replay](../core/services/tat_tracker.py#L1670).
- [Complaint page/cursor ordering](../core/services/complaint_cases.py#L351).
- [Write-route checker](../scripts/check_miniapp_write_inventory.py),
  [environment parity checker](../scripts/check_settings_env_parity.py), and
  [dependency exception gate](../scripts/check_dependency_vulnerabilities.py).

## Quality assessment and bounded follow-up

| Quality | Assessment |
|---|---|
| Functionality | Rich domain-specific workflows with strong canonical state ownership; the group-queue and cursor inconsistencies need narrow fixes |
| Security/privacy | Signed identity, persisted capabilities, private evidence and explicit administrative overrides are substantial safeguards; TAT report scope composition is a concrete authorization concern |
| Integrity/idempotency | Revision locks, immutable snapshots and append-only native/compliance history are well established; receipt payload binding is inconsistent across services |
| Reliability | Durable effects, leases, retry states and independent publication protect local commits; unattended completion still depends on running processors |
| Usability/recoverability | Mobile layouts, close protection, drafts and navigation preservation have broad fixture coverage; failed complaint evidence recovery is incomplete |
| Scalability | Bounded API paging and batched timing reads help; full in-memory inbox assembly and report object hydration require workload measurement |
| Maintainability | Domain services and extracted financial/HB apps improve boundaries; large views/admin/legacy models and duplicated retry contracts increase regression risk |
| Testability | Extensive backend and real Chromium suites exist; stale fixtures, environment differences and failing governance checks currently weaken a release-wide green signal |
| Observability/auditability | Native history, compliance evidence, dispatch status and durable runner health exist; evidence-open and rejection retention policies differ between workflows |
| Portability/deployability | Python/JS pins are reproducible, but native PDF libraries, PostgreSQL semantics, Node version, settings parity and runtime runners remain separate prerequisites |
| Interoperability | Telegram, Drive and Sheets have explicit gateways and projection contracts; local tests cannot establish current external permissions or delivery health |

Recommended order: first close the TAT report row-scope defect with a denied
scope/export regression; then fix Portal group-query mapping and complaint
evidence retry recovery separately; then bind TAT replay payloads and correct
the compatibility cursor. Reconcile the write inventory and stale fixtures
without weakening their assertions, and review the expired dependency
exception against a fresh audit. Verify each bounded fix on PostgreSQL and
the supported CI runtime before a controlled live acceptance run.

No application patches, migrations, external publications, messages, webhook
changes or production resets were performed by this review.
