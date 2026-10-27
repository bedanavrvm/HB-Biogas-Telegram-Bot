# Origination ID capture, lifecycle and numeric PDF formatting

The user approved these changes on 27 October 2026: simplify National ID copies
only; physically delete never-signed applications without a reason or quota;
invalidate and archive signed applications with a reason; permit the assigned
officer and scoped Origination IT; and choose words per numeric PDF placement.
An additional reported duplicate-signature error is included in this correction.

## Behaviour and implementation

Each saved person's ID requirement has Camera and Upload. Camera stays open for
several captures, with thumbnails, retake/remove and Save. Upload accepts mixed
images/PDFs in one selection, without a front/back wizard. Up to ten source files
and twenty pages are combined in source order as one private PDF, within existing
file and application byte limits. Images reuse Portal's decoder, EXIF correction,
metadata removal and size limits. PDFs must be readable and unencrypted.
Combined images/PDFs and a single already-combined file are valid. Human staff
remain responsible for confirming that the copy includes the necessary ID detail;
there is no OCR assertion that an image contains both sides.

ID replacement switches the current copy only after successful storage. Prior
copies and their Drive references remain in the retained evidence history;
failed replacement leaves the old copy current. Subject checks bind copies to the
saved person. Retries keep their key while the selected files stay unchanged.
An overlapping product requirement and optional ID collection render one card;
the existing captured optional-ID policy is preserved. Other evidence requirements
retain their configured required flags, enforcement stages and existing flow.

The existing dialog, camera, buttons and requirement rows are reused. The camera
viewport is shorter for multi-capture and the three-action footer stays visible;
thumbnail strips scroll within their own area. No lab tokens, approved baselines,
production browser routes or Phase 6 migration gates change.

The Mini App exposes Delete application on never-signed work, including submitted
unsigned work, and Invalidate application on any signing history. One explicit
confirmation suffices for deletion; invalidation requires a 1-500 character reason.
Historical or invalidated signatures still count as signing history, including on
recalled drafts. No quota applies. Independent Origination capabilities and exact
ownership/scope are rechecked server-side. TAT/Portal/Complaints grants do not
transfer authority. Active Superusers retain the approved technical override.

Deletion uses the reviewed child-before-parent deletion mechanism only for the
selected application's own rows and blocks outside/unreviewed dependencies. Its
independent compliance result survives deletion for replay. Shared products,
templates, customer identities and external files are preserved. Invalidation is a
terminal read-only status, closes live links/tasks, retains signed evidence and
records actor/time/reason. Partial signed copies are frozen locally before closing
live work; original final signed copies and their hashes remain unchanged. The
Archived / Invalidated filter provides history under existing read permissions;
invalidated records do not appear in active work by default. Details show the
reason and warn that old signatures no longer authorize further processing.
Historical downloads return retained bytes; they do not restore authority.

The two POST actions are `/api/origination/api/applications/<id>/delete-draft/`
and `/invalidate/`, both revision/request-key bound. The latter accepts `reason`.
Application details include `lifecycle` action availability and invalidation
metadata for full-authority viewers. The write inventory includes both actions.

The Document editor's numeric placement checkbox stores
`value_format: number_words` in its existing configuration. Numeric table columns
offer the same choice. One Decimal-based English formatter serves preview and
generated PDF; data entry, validation and calculations stay numeric. Whole numbers,
zero, negatives and fractional digits are supported without rounding or currency
labels. Non-finite values and unsupported magnitudes fail clearly. Words never
silently truncate. Existing capitalization and fit controls still apply.
Signed layouts/bytes are not backfilled.

Duplicating a signature now waits for signer autosave before filled-preview
validation. Older product-owned editable drafts detach their document authoring
contract into the existing independent document record on an authorized edit,
retaining eligibility and leaving product configuration unchanged. Published
documents/products remain immutable. Copied signatures retain their own paired
date slots and the same person.

## Validation and evidence

All work uses synthetic records and local storage mocks. The safe helper ignores
`.env` and blocks remote network. PostgreSQL uses the dedicated port-55439 test
instance. Regression coverage is in `origination/tests_workflow_improvements.py`;
existing identity, signer, document, application-copy and deletion suites are also
exercised. Cases include mixed input order, malformed/encrypted documents, limits,
deterministic PDF bytes, replacement failure, historical signatures, blank reasons,
owner/IT branch and workflow isolation, stale revisions, audit rollback, signed-byte
integrity, independent replay, and concurrent signature/deletion exclusion.

Local logs are `test-results/origination-improvements-*.log`. Real-shell synthetic
Chromium evidence is under `test-results/origination-improvements-live/`:

- `camera-390.png`: multiple captures, retake/remove and visible Save.
- `requirements-390.png` and `requirements-1280.png`: one ID card per person, two source buttons and one current PDF.
- `numeric-words-1280.png`: numeric placement formatting in the actual Admin shell.

The native signature-copy journey also runs in Filled sample mode, autosaves and
reloads the copied signature/date. The API journey uses a synthetic local Django
session with Telegram authentication explicitly disabled only in test settings;
normal production Telegram authentication is unchanged. Playwright's independent
form suite covers camera denial/cancellation, failed upload retention/retry,
invalidation reason/retry and archived read-only presentation across its existing
mobile/desktop and light/dark fixtures. Browser evidence does not certify physical
Telegram devices, screen readers or live providers.

The later setup-footer correction displays every unfinished task's existing
server-owned label and detail next to its count, with a link to the owning setup
step. It updates after autosave, handles singular/plural counts and hides an empty
list. It does not change publication readiness rules. A real Admin journey covers
one remaining Documents task, an unrelated autosave, and navigation using the
footer link. Capture: `setup-remaining-task-390.png` in the same evidence folder.

Verification totals: the focused PostgreSQL run passed 198 tests; SQLite ran
the same 198 with six PostgreSQL-only skips and no failures. A later 21-test
workflow run passed on PostgreSQL, including decimal-context precision and both
removal concurrency checks. All 59 Playwright form scenarios passed. Three
real-shell upload/deletion/signature-copy/words journeys passed; three additional
setup-footer and write-inventory checks passed. Static syntax, no-migration-drift,
whitespace and UI source-ratchet checks also passed. These are focused checks,
not execution of the full repository suite.
The final combined workflow/footer/inventory rerun passed all 23 PostgreSQL tests.

A separate fresh-database capability run completed 44 checks with one pre-existing
failure: `PortalAccessHardeningTests.test_multi_role_policy_change_is_one_atomic_request`
expects only `portal.case.read`, while the historical
`portal.origination.signing.staff` row from core migration 0129 remains. The same
single failure was reproduced at unchanged base commit `caad976d` with that exact
migration-owned legacy row present. The new Origination capabilities do not alter
this Portal policy. Evidence is in `origination-improvements-policy-fresh.log` and
`origination-improvements-policy-baseline.log` under `test-results/`.

## Deployment and rollback

Apply checked-in migration `origination.0015_application_invalidation`, then
deploy code and collect static assets. It adds the status choice and idempotent
built-in capability defaults for JBL_OFFICER and IT; it preserves later explicit
policy decisions. There are no new models, dependencies, settings or usage charges.
No reseed, reset, live deletion, provider write or production deployment was run.

Monitor errors/durations on evidence uploads and both lifecycle endpoints, and
check one actor-scoped workflow audit result per successful removal. After
invalidation, verify old links refuse signing and current queues exclude the case.
Watch ID replacement failures without treating prior evidence as removed.

Rollback must retain handling for already-invalidated rows and frozen words
formats; do not relabel records or rewrite historical signed bytes to fit older
code. Capability rows intentionally survive migration reversal, as existing
capability migrations do. Deletion is permanent except recovery from a verified
backup. Live SMS/Drive, real Telegram devices and screen-reader checks remain
outside this synthetic validation.
