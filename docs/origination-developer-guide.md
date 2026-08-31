# Loan Origination Mini App: Developer Guide

Last verified against the repository on **20 August 2026**.

This guide describes the current implementation and the invariants a developer
must preserve. Code, migrations, settings, and tests remain authoritative if
this document drifts.

## Purpose and boundaries

Loan Origination is a product-neutral, revision-controlled Telegram Mini App. A
field officer captures an application against a published product contract; a
separate actor reviews it; Django freezes a local signing package before any
external signing integration.

The core boundaries are:

- Django owns workflow state, permissions, audit history, versions, and
  application/document snapshots.
- Global `Product` records provide stable product identity across workflows.
- Google Drive stores approved PDF sources and uploaded evidence. Drive is not a
  workflow database.
- Telegram `initData` proves identity; `AccessGrant`, capabilities, ownership,
  branch, and product scope determine authorization.
- Published configuration and submitted historical snapshots are never silently
  rewritten.

## Architecture and data flow

```text
Django Admin configuration
  Product -> ProductVersion -> OriginationProductDefinition
                                  |                 |
                                  |                 +-> supporting assignments
                                  v                          |
                            primary LAF                reusable templates
                                  \__________________________/
                                               |
                                               v
Telegram Mini App -> authenticated/scoped API -> application service
                                               |
                         +---------------------+---------------------+
                         |                     |                     |
                         v                     v                     v
                 application snapshots   append-only events   Drive files
                         |
                         v
                 reviewed immutable signing package
```

An application snapshots the selected `ProductVersion`, product terms and
requirements, the main form schema, document packet, template configuration,
document-specific fields, and signer rules. Latest-version lookup happens while
creating the application packet, not each time a historical application is
rendered.

## Main records

| Record | Responsibility | Mutability |
|---|---|---|
| `Product` | Stable global identity, aliases, and optional availability restrictions. | Code is immutable; deactivate instead of repurposing. |
| `ProductVersion` | Effective-dated amount, tenor, interest, repayment, fees, requirements, attributes, and TAT configuration. | Draft editable; published/scheduled/retired versions immutable. |
| `OriginationDataField` | Global typed semantic variable used across forms and PDFs. | Key is immutable. Type correction is limited to draft-only usage and rewrites editable schemas atomically; frozen contracts block it. Repeating structure and existing choice codes remain immutable. |
| `OriginationProductDefinition` | Versioned Origination form, signer contract, and document packet owner. | Draft editable; published version immutable. |
| `OriginationDocumentTemplate` | Drive-backed PDF plus versioned placement configuration and document schema. | Draft calibration revisions; activated publication becomes governed. |
| `OriginationProductDocumentAssignment` | Attaches a reusable primary or supporting family to one draft product and controls applicability/order. | Primary assignments are version-pinned; supporting assignments may resolve the latest compatible publication. Editable only while the product definition is draft. |
| `LoanOriginationApplication` | Canonical application state, payloads, status, revision, and frozen product/schema terms. | Changed only through services and validated transitions. |
| `OriginationApplicationDocument` | Per-application primary/supporting template, schema, mapping, field payload, selection, and preview snapshot. | Bound to the application revision/workflow. |
| Evidence, correction, signing, reporting, and event records | Supporting workflow state and audit evidence. | Append-oriented or state-transition controlled. |

The testing-only God-mode service deliberately covers only Origination models.
It must never expand to Global Products, locations, users, access control, Drive
deletion, or another Mini App.

## Source map

| Area | Primary source |
|---|---|
| Models and constraints | `core/models.py` |
| Admin screens and actions | `core/admin.py`, `core/admin_navigation.py` |
| Application lifecycle | `core/services/loan_origination.py` |
| Document selection/rendering | `core/services/origination_documents.py` |
| PDF upload/calibration/publication | `core/services/origination_templates.py` |
| Canonical field governance | `core/services/origination_fields.py` |
| Product terms and availability | `core/services/product_catalog.py` |
| Officer-entered commercial contract, quote comparison and exact exceptions | `core/services/origination_commercial_terms.py` |
| Authorization and scoping | `core/services/origination_access.py`, `core/services/workflow_capabilities.py` |
| HTTP boundary | `core/api/origination_views.py`, `core/api/urls.py` |
| Mini App | `core/templates/loan_origination/app.html`, `core/static/miniapp/loan_origination.*` |
| Admin builders | `core/templates/admin/core/origination*/`, `core/static/admin/origination_*` |

Business rules belong in services. Views should parse requests, authenticate,
authorize, call a service, and translate known errors into stable responses.
Templates and JavaScript must not decide workflow transitions or access.

## Configuration lifecycle

### Global product and terms

`Product.code` is the stable lower-snake-case identity used by access scopes and
external mapping. `ProductAvailability` is optional: no active assignments means
global availability; once assignments exist, a branch/workflow/channel must
match at least one active row.

`ProductVersion` holds all commercial values as database decimals and typed
configuration. Publication is Superuser-only and effective-dated. Overlap and
supersession behavior belongs in `product_catalog.py`; do not implement a second
version resolver in a view or Mini App.

The Origination definition may reference a Product Version. When linked, its
`product_key` and `name` must equal the Global Product code and name.

### Governed Commercial Terms v2

`origination_commercial_terms.py` owns the shared versioned field contract and
the comparison boundary. New/cloned definitions and both reviewed LAF seeds
merge this contract idempotently. `create_application()` snapshots it; no
existing application is rewritten when a definition later changes.

The officer enters only `loan_amount` and `repayment_tenor`. Currency, tenor
unit, interest configuration, repayment frequency, installment schedule,
mandatory fees, financed principal, interest, and totals are system-derived
from the frozen ProductVersion. Derived canonical fields remain active for PDF
mapping but are not attached to the Mini App form schema.

The non-mutating quote-preview endpoint calculates the same Decimal quote used
by save and submission. On every Draft save, the service stores that quote in
`product_quote_snapshot` and appends the two entered values, expected quote,
findings, and stable hashes to `OriginationApplicationEvent.metadata`.

`OriginationCommercialException` is append-only and matches only the exact
application revision, ProductVersion, entered-terms hash, expected-quote hash,
and named amount/tenor bound mismatch codes. A revision/hash change makes it
inapplicable without mutating the historical approval. Pricing, interest,
frequency, and fee exceptions require a new ProductVersion. The frozen `product_quote_snapshot` carries
the consumed exception into review/signing package context.

The dry-run-first `upgrade_origination_commercial_contract` command signs its
exact target/fingerprint manifest with Django signing. Apply locks every target
and aborts the entire transaction on drift. It changes Draft definitions and
their editable primary template schema only; published definitions and all
application snapshots are excluded.

### Canonical fields and schemas

`OriginationDataField` separates semantic identity from product presentation:

- canonical: key, type, source, sensitivity, masking, reporting policy, choice
  codes, and repeating-group structure;
- product/document presentation: label, help text, required state, section,
  width, order, and permitted choice display; and
- application: typed value stored under the canonical key in a frozen schema
  snapshot.

### Origination terminology contract

Use **Applicant** for the pre-execution operational role. **Customer** refers
only to the optional `JawabuCustomer` identity linked to an application, and
**Borrower** refers to the contractual obligor or signer. Use **Party** when a
rule applies collectively to applicants, guarantors, spouses, or other document
participants. Do not introduce Client or Farmer as generic Origination person
labels.

`core.services.origination_terminology` owns conservative synonym matching for
canonical-field governance. It must not be used as a blanket code renamer:
`client_request_id`, the application `customer` foreign key, borrower signer
roles, legal PDF text, and historical canonical keys have distinct contracts.
`preferred_field` records an explicitly reviewed duplicate; consolidation
deactivates it while immutable application and template snapshots keep their
original keys.

Supported types are `text`, `textarea`, `number`, `money`, `date`, `phone`,
`national_id`, `choice`, `boolean`, `branch`, `county`, `sub_county`, and
`repeating_group`. Use `Decimal`, ISO date values, shared phone/ID normalization,
and canonical choice codes. A `metric` reporting field must be numeric or money.

System-derived fields may be mapped into a PDF but must not become user input.
Sensitive fields must not be copied into logs or audit metadata. Reporting uses
typed `OriginationReportingValue` projections rather than repeatedly aggregating
raw JSON payloads.

### PDF templates and calibration

PDF upload must:

1. enforce the configured byte limit;
2. validate content as PDF and determine page count/hash;
3. create a safe database record;
4. upload to the restricted Drive root;
5. retain a useful `upload_failed` state when Drive fails; and
6. create audit events without logging document content.

Placement configuration uses PDF page coordinates. Browser pointer/touch deltas
must be converted through the current pan/zoom transform before updating these
canonical coordinates. Rendering must use the published configuration revision,
not an unapproved calibration draft.

Product-definition creation supports three explicit main-LAF sources: attach an
eligible reusable global primary template, upload a new primary PDF, or configure
the draft later. Configure-later drafts remain unpublishable until exactly one
ready primary exists. A reusable primary assignment pins the exact published
template version selected at attachment time. It never follows a later
publication silently; a Superuser must explicitly upgrade the editable draft,
which merges the compatible contract and records an append-only product event.
Supporting assignments retain latest-compatible resolution so new application
snapshots can adopt compatible published supporting revisions automatically.

`clone_reusable_template_version` is the idempotent Admin path for editing an
active global template without uploading duplicate bytes. It creates at most one
ready successor, reuses the immutable Drive source/hash, deep-copies the governed
schema, signer rules, applicability and published placement configuration, and
records `editable_version_created`. Activation still retires the previous family
version through the normal publication service. Product-owned documents must use
the product successor workflow instead.

A primary LAF has document key `primary`, role `primary`, and required inclusion.
A reusable supporting template has no product-definition owner, role
`supporting`, a stable document family/type, and an active published calibration.

Assignments normally use `latest_compatible`. The resolver may adopt a later
published template only when its governed field/signer contract is compatible
with the baseline family. The resolved template and configuration are then
snapshotted into each new application document.

### Publication

Publication must remain transactional and server-authoritative. Readiness
includes successful Drive upload, published mapping, one primary document,
complete fields/signers, valid supporting assignments, compatible active
templates, valid applicability rules, and no unresolved legacy-field blockers.

When locking rows in PostgreSQL, lock the base model queryset first. Do not use
`select_for_update()` on a queryset that outer-joins a nullable relation;
PostgreSQL rejects `FOR UPDATE` on the nullable side of an outer join. Load
optional related records after acquiring the base-row lock.

## Application lifecycle

The principal states are:

```text
Legacy:      draft -> ready_for_review -> reviewed -> signing_pending -> fully_signed
Conditional: draft -> ready_for_review -> signing_pending -> partially_signed
                                                        -> signed_pending_approval
                                                        -> approved
                                                        -> correction_required / declined

Other outcomes: expired and cancelled.
```

The conditional path is disabled by default. It is available only when
`ORIGINATION_CONDITIONAL_APPROVAL_ENABLED=True` and exactly one immutable,
compliance-approved `OriginationConsentPolicyVersion` is active. Existing
partially or fully signed legacy packets retain their original consent and
pre-sign review path; they are never silently converted.

Preserve these behaviors:

1. Creation resolves an active, available product and freezes its configuration.
2. The assigned officer saves the main form against an expected revision.
3. Officers may choose applicable optional supporting documents without first
   leaving the flow for a separate primary-LAF preview.
4. Required/conditional documents are server-selected; officers may toggle only
   applicable officer-selectable documents.
5. Supporting fields validate against that document's frozen schema. Shared
   canonical values remain synchronized through governed keys.
6. One complete full-packet preview marks the primary LAF and every selected
   supporting document previewed for that revision. Any later edit or document
   selection invalidates that preview.
7. Submission enters `ready_for_review`, but Operations must first freeze the
   complete data, evidence, participant, signer, template, manifest and PDF
   scope into a hash-bound review package. A checker reviews that exact PDF.
8. A reviewer can approve, decline, or return exact fields with mandatory
   inline instructions; maker-checker separation is enforced server-side.
   `correction_required` never exposes the broad recall/edit path.
9. Before signing dispatch, the assigned officer may recall a submitted or
   approved application. A prepared packet requires explicit hash-bound
   confirmation; an approved recall cancels the packet, invalidates approval,
   alerts the original checker, and preserves that checker for continuity.
10. Requirements/evidence must satisfy their configured enforcement stage.
11. `prepare-signing` is a compatibility alias that starts signing only for an
   already approved frozen package. It never renders or replaces a package.
12. In the conditional path, the assigned officer confirms the latest preview,
   the server freezes the packet, and the approved clause is placed inside the
   exact PDF bytes before hashing. A source PDF may skip the prepended notice
   page only when its exact SHA-256 has a recorded native-clause attestation.
13. Conditional signatures are provisional until an independent checker opens
   and approves the exact signed hash. Approval moves the case to `approved`
   and only then schedules permanent archival. Data/evidence corrections cancel
   and supersede the packet; signature-only corrections append an invalidation
   and require only the selected slot to sign again.

All transitions record actor, timestamp, request ID, revision, and safe before/
after metadata. Original application and document snapshots remain available for
audit.

## Authentication, authorization, and concurrency

The shell is public HTML at `/origination/`; its APIs are protected through the
shared Portal Telegram authenticator. Production must keep
`PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True`. Never add a separate or weaker
`initData` verifier.

The `jawabu_portal` capability defaults are:

| Capability | Default roles |
|---|---|
| `portal.origination.view` | `JBL_OFFICER`, `OPERATIONS_ADMIN`, `BUSINESS_ADMIN` |
| `portal.origination.create` | `JBL_OFFICER` |
| `portal.origination.review` | `OPERATIONS_ADMIN`, `BUSINESS_ADMIN` |
| `portal.origination.signing.start` | `OPERATIONS_ADMIN` |

Capabilities are only the first layer. Enforce branch, product, application
ownership, and full/masked/denied presentation through `origination_access.py`.
An officer with create access sees their own applications; elevated review/
signing roles receive their allowed scoped queue. A view-only result may be
masked. Active Superusers have the explicit technical override, which remains
audited.

Every write must carry a bounded request identifier (`Idempotency-Key`,
`X-Request-ID`, `client_request_id`, or `request_id` as supported by the HTTP
boundary). Services check existing events/records so retries do not duplicate
state. Every update also supplies the expected application revision. A stale
revision returns a conflict (HTTP 409) and the client must refresh; never perform
last-write-wins over a newer revision.

## HTTP interface

The browser uses the canonical `/api/origination/api` prefix:

| Method/path | Purpose |
|---|---|
| `GET /products/` | Active products, branches, location manifest, and queue capabilities. |
| `GET, POST /applications/` | Scoped queue or idempotent application creation. |
| `GET, PATCH /applications/<id>/` | Scoped detail or revision-aware main-form save. |
| `POST /applications/<id>/preview/` | Render/mark the primary LAF preview. |
| `POST /applications/<id>/documents/selection/` | Change optional document selection. |
| `POST /applications/<id>/documents/<key>/fields/` | Save supporting fields for the current revision. |
| `POST /applications/<id>/documents/<key>/preview/` | Validate and render one selected document. |
| `POST /applications/<id>/packet/preview/` | Validate and render the selected packet. |
| `POST /applications/<id>/submit/` | Submit a complete, previewed revision. |
| `POST /applications/<id>/confirm-signing/` | Assigned officer validates, freezes, and starts a governed conditional packet. |
| `POST /applications/<id>/recall/` | Officer recall to Draft; prepared/approved packets require explicit package/hash confirmation. |
| `POST /applications/<id>/prepare-review-packet/` | Operations freezes the complete unsigned review scope. |
| `POST /applications/<id>/review-packet/preview/` | Hash-verifies and records checker inspection of the frozen packet. |
| `POST /applications/<id>/review/` | Decide the exact frozen package; package ID and both hashes are mandatory. |
| `POST /applications/<id>/final-review/` | Independently approve, correct, or decline the exact fully signed conditional packet. |
| `POST /applications/<id>/correction/takeover/` | Reassign a correction re-check with an audited reason. |
| `POST /reviewer-notices/<id>/seen/` | Mark an approval-invalidation alert seen by its recipient. |
| `POST /applications/<id>/signing-requirements/` | Save signing requirements for the current revision. |
| `POST /applications/<id>/prepare-signing/` | Compatibility route: start signing for the approved frozen package. |
| `POST /applications/<id>/signer-sessions/` | Idempotently create a self-service or assisted external-signer session. |
| `POST /applications/<id>/signer-sessions/reset/` | Revoke and replace a signer session with an audited reason. |
| `POST /applications/<id>/staff-signature/` | Apply one authenticated staff capture to all assigned staff signature slots. |
| `POST /applications/<id>/production-stamp/` | Apply one governed production stamp to a calibrated stamp slot. |
| `POST /applications/<id>/archive-signed/` | Idempotently archive the frozen fully signed PDF. |
| `POST /applications/<id>/test-signing/action/` | Record one watermarked non-production slot action. |
| `POST /applications/<id>/test-signing/preview/` | Render the current watermarked test packet. |
| evidence upload/remove/download routes | Govern requirement evidence within scope and configured limits. |

Keep response errors stable and staff-safe. Log exceptions with correlation and
record IDs, never raw form payloads, PDF contents, Telegram signed data, tokens,
or evidence.

## Evidence and signing

Evidence uploads are untrusted. Validate size, count, total application bytes,
extension/content type, requirement applicability, actor scope, and revision.
Storage filenames must be generated safely. A user removal is a governed logical
state transition; it must not silently erase the audit trail.

Drive failure remains distinguishable from local signing success and retains
retry/error metadata. `OriginationSigningPackage` is the immutable local
snapshot of the reviewed revision. A fully signed package stores the exact
rendered bytes and SHA-256 before archival. Drive retry uploads those retained
bytes; it never rerenders from current application or product state.

Signature and stamp appearance is part of each published template configuration
snapshot, not a mutable signing-time preference. The visual calibration builder
stores validated alignment, padding, rotation, and type-specific appearance
settings in `signature_overlay_manifest.slots`. Signature slots additionally
govern ink colour, typed font/size, and drawn stroke width; stamp slots govern
contain-versus-stretch image fitting. The signing renderer must apply those
snapshotted properties and must never allow appearance controls to remove the
non-production watermark.

The optional no-OTP simulator is intentionally separate from production
signing. It accepts only test-classified controlled stamps, records append-only
slot actions, accepts a bounded normalized drawn-stroke payload or typed test
name for signature slots, watermarks every page, and never transitions the
application to `fully_signed`. Capture content and its SHA-256 digest remain on
the append-only action metadata because the test PDF must be reproducible; the
normal serializer exposes only the capture method, never raw strokes or the
typed name. Reusing an idempotency key with different capture content is
rejected. The simulator is denied unless `SENTRY_ENVIRONMENT` is explicitly one of
`development`, `dev`, `local`, `test`, `testing`, or `staging`; missing and
unknown values fail closed. Correction writes similarly enforce the open correction's
target keys server-side; disabled controls are only presentation, not the
security boundary.

Verified external signing uses `OriginationSignerSession` as a revocable opaque
bearer link, `OriginationOtpChallenge` for a salted OTP hash and immutable packet
binding, and `OriginationSigningRequestEvent` for database-backed token/IP
throttling. Consent binds the packet hash, signer role, frozen identity,
consent version, signature-capture hash, and complete reviewed-page list. One
successful challenge creates append-only verified actions for all signature
slots belonging to that role in one transaction. The code and raw token are
never stored; normal serializers expose only masked/status evidence.

The public ceremony is rooted at the compact `/s/#<opaque-token>` route. The
legacy `/origination/sign/#<opaque-token>` route remains available for existing
links. The URL fragment is removed from the address bar on load and sent only
as an `Authorization: Bearer` header, so it does not enter normal HTTP access
logs. Public writes require the bearer token, are rate limited, and do not use
staff cookie authorization.

Authorized Mini App users retrieve completed documents through
`GET /api/origination/api/applications/<application-id>/signed-packet/`.
`preview_format=image&page=N` returns a page for the in-app viewer, while
`download=1` returns the PDF as an attachment. Archived bytes are downloaded
from restricted Drive and checked against `signed_document_hash` before they
are returned. Staff session creation/reset, staff signing, stamping, and
archival remain behind Telegram authentication, capabilities, and application
scope. `/api/origination/webhooks/africastalking/delivery/` accepts idempotent
provider receipts, but updates only OTP delivery fields. It cannot set
`verified_at`, create a signing action, or advance a package/application.

OTP limits are 60 seconds between sends, three sends per session in 30 minutes,
five sends per phone per hour, ten per phone per day, and five verification
attempts per challenge. Attempt exhaustion locks the signer session for 30
minutes. Operations reset/reissue requires a request ID and a nonblank audited
reason. Shared external phone numbers require a reasoned Superuser approval;
that approval is retained when Operations reissues the same signer session.

## Environment variables

| Setting | Purpose/default posture |
|---|---|
| `APP_BASE_URL` | Public HTTPS origin used for fallback launch URLs. |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME` | Telegram authentication/launcher identity; secrets stay outside Git. |
| `ORIGINATION_MINI_APP_SHORT_NAME` | BotFather short name; falls back to the direct web URL if unavailable. |
| `PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH` | Keep `True` in production. |
| `PORTAL_WEBAPP_AUTH_MAX_AGE_SECONDS`, `TELEGRAM_AUTH_MAX_AGE_SECONDS` | Maximum accepted signed-session age. |
| `GOOGLE_DRIVE_MEDIA_FOLDER_ID` plus Google credentials | Restricted root for template/evidence files. |
| `ORIGINATION_TEMPLATE_MAX_FILE_SIZE_MB` | Template PDF limit; default 15 MB. |
| `ORIGINATION_EVIDENCE_MAX_FILE_SIZE_MB` | Evidence per-file limit; default 10 MB. |
| `ORIGINATION_EVIDENCE_MAX_FILES_PER_REQUIREMENT` | Default 5. |
| `ORIGINATION_EVIDENCE_MAX_TOTAL_UPLOAD_MB` | Default 30 MB per application. |
| `ORIGINATION_TEST_SIGNING_ENABLED` | Watermarked simulator outside production only; default `False`. |
| `ORIGINATION_ESIGN_ENABLED` | Explicit master gate for verified signing; default `False`. |
| `ORIGINATION_CONDITIONAL_APPROVAL_ENABLED` | Enables post-sign independent approval only after an approved consent policy is active; default `False`. |
| `AFRICASTALKING_SMS_ENVIRONMENT` | `sandbox` or `production`; must agree with the application environment. |
| `AFRICASTALKING_USERNAME`, `AFRICASTALKING_API_KEY` | Server-only provider credentials. Sandbox requires username `sandbox`. |
| `AFRICASTALKING_SENDER_ID` | Optional approved production Sender ID. |
| `ORIGINATION_SIGNING_LINK_TTL_HOURS` | Opaque signing-link lifetime, bounded to 1-168 hours; default 48. |
| `ORIGINATION_SIGNING_BASE_URL` | Optional HTTPS origin for compact signer links; blank falls back to `APP_BASE_URL`. |
| `REQUIRE_MINIAPP_IDEMPOTENCY_KEY` | Required `True` in production; local/test compatibility may be explicit. |
| `MINIAPP_IDEMPOTENCY_OBSERVATION_DAYS` | 1–90 day anonymous missing-key readiness lookback; default 14. |
| `ORIGINATION_FULL_RESET_ENABLED` | Testing-only Admin reset; default and normal production value is `False`. |

If a setting is added or renamed, update `config/settings.py`, `.env.example`,
the repository `AGENTS.md` environment table, and this guide in the same change.

## Local development

Use the repository virtual environment on Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver
```

Use only synthetic data. To exercise a fully published main/supporting packet,
first dry-run and then explicitly apply the seed:

```powershell
.\.venv\Scripts\python.exe manage.py seed_origination_packet_demo --actor <active-superuser>
.\.venv\Scripts\python.exe manage.py seed_origination_packet_demo --actor <active-superuser> --apply
```

`--apply` requires a configured restricted Drive folder and creates synthetic
PDFs there. It does not create a customer application.

The reviewed Invoice Finance contract has its own idempotent, dry-run-first
seed. Its source PDF remains ignored under `LAFS/` and coordinates are never
auto-published:

Its canonical field/type/validation/rendering and signer contract is documented
in [Invoice Finance LAF seed reference](origination/invoice-finance-laf-seed.md).

```powershell
.\.venv\Scripts\python.exe manage.py seed_invoice_finance_origination --actor <active-superuser>
.\.venv\Scripts\python.exe manage.py seed_invoice_finance_origination --actor <active-superuser> --apply
```

The command requires an existing global `Product` and `ProductVersion`, updates
mutable canonical-field governance, fails on frozen type conflicts, replaces a
draft contract or creates a successor, and records field/product/template audit
events. Tests must mock the Drive upload; do not seed a real environment from
the automated test suite.

The reusable Generic Jawabu LAF has a separate dry-run-first seed and mapping
reference: [Generic Jawabu LAF seed reference](origination/generic-jawabu-laf-seed.md).

```powershell
.\.venv\Scripts\python.exe manage.py seed_generic_jawabu_laf --actor <active-superuser>
.\.venv\Scripts\python.exe manage.py seed_generic_jawabu_laf --actor <active-superuser> --apply
```

It creates or reuses a global primary-template family, but deliberately leaves
product assignment, PDF coordinates, calibration, and publication to explicit
Django Admin actions.

Preview Telegram launchers without external writes:

```powershell
.\.venv\Scripts\python.exe manage.py sync_telegram_launchers --dry-run
```

## Verification

Run the narrow Origination suite first:

```powershell
.\.venv\Scripts\python.exe manage.py test core.tests_loan_origination core.tests_origination_commercial_terms core.tests_loan_origination_frontend core.tests_origination_templates core.tests_origination_fields core.tests_origination_safe_workflow core.tests_origination_command core.tests_origination_seed_command core.tests_origination_god_mode core.tests_invoice_finance_origination_seed core.tests_laf_seed_documentation
```

Check migration drift:

```powershell
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

Run the synthetic mobile/desktop Playwright audit:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify_origination_ui.ps1
```

The script creates a temporary SQLite database, installs Playwright 1.62.1 in a
temporary directory if needed, starts a temporary Django server, runs synthetic
API mocks at 320, 360, 390, 430, and 768 pixel widths, writes screenshots to a
temporary output directory, and removes the temporary database. It requires
Node/npm and may require network access on its first run.

For a change that affects shared access control, products, locations, storage,
or Telegram authentication, also run the focused tests for that shared module
before the broad suite.

## Deployment and operational checks

1. Review migrations and back up the production database before schema changes.
2. Deploy code and migrations before publishing configuration that depends on
   them.
3. Confirm Drive credentials/folder access with a synthetic PDF, not a customer
   document.
4. Run `sync_telegram_launchers --dry-run`; publish only when the target group is
   explicitly approved.
5. Test with newly created applications because old ones correctly retain old
   snapshots.
6. Monitor 400 validation errors, 403 scope failures, 409 revision conflicts,
   500 errors, template `upload_failed` records, and external-operation retries.
7. Roll back application code through the production runbook. Do not “roll back”
   a published contract by editing it; publish a corrective successor version.

Do not enable the full reset as a routine recovery mechanism. If it is used for
an explicitly approved testing reset, disable the flag immediately afterward.

## Safe extension recipes

### Add a product

Use the existing Product/ProductVersion publication service, then build a linked
Origination draft. Do not introduce a product-type discriminator or a new
per-product table merely to hold fields that the canonical schema can express.

### Add a canonical field

Search aliases and semantics first. Add the type to the canonical catalogue only
when no existing type can validate/normalize it. A new type requires model
choices/migration, schema validation and snapshot support, Mini App rendering,
PDF rendering, reporting projection policy, Admin builder support, and tests for
old snapshots.

### Add or version a supporting document

Create a global supporting template family, map and publish it, then attach it to
a draft product with latest-compatible resolution. If the new version breaks
canonical fields, types, or signer expectations, treat it as an incompatible
contract that needs an explicit product version/update rather than transparent
adoption.

### Change the API

Keep old application snapshots readable, require authentication plus capability
and resource scope, preserve request-ID idempotency and expected revisions, and
return safe structured validation errors. Update the vanilla JavaScript client,
API/service tests, frontend contract tests, and this guide together.

## Invariants checklist

- No money uses `float`.
- No client chooses its own status, role, branch authorization, or product
  availability.
- No valid Telegram identity bypasses staff authorization.
- No repeated write produces duplicate state.
- No stale revision silently overwrites a newer revision.
- No published product/template contract is edited in place.
- No existing application dynamically adopts a newer schema/template.
- No raw PII, signed Telegram data, document content, or credentials enter logs.
- No Drive failure is reported as full synchronization success.
- No Origination purge/reset touches Drive or another workflow.
- No external Telegram/Drive/Sheets side effect is performed by a test unless it
  is explicitly requested, configured, and isolated.
