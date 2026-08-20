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
| `OriginationDataField` | Global typed semantic variable used across forms and PDFs. | Key/type and repeating structure immutable; choice codes cannot be removed. |
| `OriginationProductDefinition` | Versioned Origination form, signer contract, and document packet owner. | Draft editable; published version immutable. |
| `OriginationDocumentTemplate` | Drive-backed PDF plus versioned placement configuration and document schema. | Draft calibration revisions; activated publication becomes governed. |
| `OriginationProductDocumentAssignment` | Attaches a reusable supporting family to one draft product and controls applicability/order. | Editable only while the product definition is draft. |
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
draft -> ready_for_review -> reviewed -> signing_pending
   ^            |
   |            v
   +--- correction_required

Terminal/other outcomes: declined, expired, cancelled, partially_signed,
fully_signed.
```

Preserve these behaviors:

1. Creation resolves an active, available product and freezes its configuration.
2. The assigned officer saves the main form against an expected revision.
3. Primary LAF preview is required for the saved revision before supporting
   selection/submission.
4. Required/conditional documents are server-selected; officers may toggle only
   applicable officer-selectable documents.
5. Supporting fields validate against that document's frozen schema. Shared
   canonical values remain synchronized through governed keys.
6. Each selected document must be complete and previewed for the relevant
   revision before submission.
7. A reviewer can approve or return explicit corrections; maker-checker
   separation is enforced server-side.
8. Requirements/evidence must satisfy their configured enforcement stage.
9. Signing preparation freezes the reviewed revision locally and does not imply
   successful external e-sign dispatch.

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
| `POST /applications/<id>/review/` | Approve or return corrections. |
| `POST /applications/<id>/correction/takeover/` | Reassign a correction re-check with an audited reason. |
| `POST /applications/<id>/signing-requirements/` | Save signing requirements for the current revision. |
| `POST /applications/<id>/prepare-signing/` | Freeze a reviewed signing package. |
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

Drive failure must remain distinguishable from local transaction success and
must retain retry/error metadata. `OriginationSigningPackage` is an immutable
local snapshot of the reviewed revision. A future e-sign adapter must be a
separate idempotent external operation and may not mark local signing complete
before the provider confirms it.

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
| `REQUIRE_MINIAPP_IDEMPOTENCY_KEY` | Strict retry-key enforcement rollout flag; enable only after cached clients are verified. |
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

Preview Telegram launchers without external writes:

```powershell
.\.venv\Scripts\python.exe manage.py sync_telegram_launchers --dry-run
```

## Verification

Run the narrow Origination suite first:

```powershell
.\.venv\Scripts\python.exe manage.py test core.tests_loan_origination core.tests_loan_origination_frontend core.tests_origination_templates core.tests_origination_fields core.tests_origination_safe_workflow core.tests_origination_command core.tests_origination_seed_command core.tests_origination_god_mode
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
