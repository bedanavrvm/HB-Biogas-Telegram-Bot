# Origination compact application UI - scoped candidate

22 October 2026. Implements the user's corrective plan, not a shared-standard
approval or Phase 6 migration. Supersedes the header and reused-value presentation
in [the earlier candidate](origination-application-sections.md). Existing type
sizes, input sizing, application ownership and document snapshots are retained.

## Changes

- Applicant identity and borderless document actions share the first compact
  header row. Saved dial/copy contacts follow without repeated labels. Only
  genuine device safe-area padding remains above the header. Phone-check details
  expand on demand; outcomes still use toasts. Provider confirmations and scope
  remain unchanged.
- Main LAF/supporting forms share one field renderer, the existing accessible
  feedback controller and aligned label/control/feedback tracks. Helper/error
  text sits below inputs. Narrow/unsupported layouts fall back to one column.
- Shared supporting values use grey read-only controls, never source links or
  independent submitted copies. False, zero, dates, choices and repeating rows
  retain their meaning. Each supporting document remains one section page.
- Cards retain aligned ID/phone slots when values are absent and omit empty
  officer content. Readable references are secondary to applicant names.
- Combined/individual incomplete previews require explicit confirmation and
  return `X-Preview-Complete: false`. They do not mark documents complete or
  unlock submission/signing. Invalid supplied values remain validation errors;
  signed documents retain exact original bytes.
- ID Front/Back each offer Take photo, Retake and Choose photo. The shared camera
  capture uses a video/canvas dialog, releases streams on cancellation (including
  delayed permission responses), and keeps staged photos when saving fails.
  Existing validated two-image PDF collation is reused, not replaced.

## References and deployment

Migration `origination.0012_application_display_references` introduces the
Origination-owned permanent sequence and `display_reference`. New applications
allocate ORG-1, ORG-2, etc. transactionally; idempotent replay does not allocate.
Cancellation/testing deletion never resets the sequence. Existing applications
receive deterministic display aliases without changing their original reference,
timestamps, revision, schema, signing evidence or captured document bytes.

Application API responses add `display_reference`; `reference_number` remains
compatible. UI/Admin show the alias and search accepts either. UUID routes and
authorization stay unchanged. No staff shell command, external synchronization,
provider configuration change or cross-Mini-App access grant is required. Apply
the checked-in migration through the existing release procedure. Back up the
allocator before any deliberate schema rollback; do not reset it with test data.

## Evidence

`core/tests_browser/origination_application_forms.spec.js` renders the complete
Django application template, preserving actual CSS/JS load order. Operational
API data, Telegram identity and camera streams are synthetic. Font/shell metadata
is attached to matrix tests; remote font fallback is not production-font proof.
The backend preview test uses actual PDF rendering/combination with only the
external source-file read replaced by synthetic PDFs.

```powershell
npx playwright test core/tests_browser/origination_application_forms.spec.js core/tests_browser/origination_phone_identity.spec.js core/tests_browser/origination_queues.spec.js core/tests_browser/origination_signing_plans.spec.js --workers=2 --output=test-results/origination-oct22-verified
```

Inspect the phone-sized light/dark `header.png`, `supporting-fields.png`,
`aligned-validation.png`, `captured-front-back.png`, `missing-card-values.png`
and `phone-check-details.png` captures. Tests also operate dial/copy actions,
incomplete preview/refresh/submission guards, camera capture/retake/denial,
delayed permission cancellation and retained-photo upload retries. Matrix widths
are 320, 360, 390 and 430px, including long labels, missing values and 200% text.

These are review evidence, not approved image baselines. Physical Telegram
camera permissions, native dialler behaviour, keyboard/safe areas and staff-device
font rendering remain real-device checks. SQLite does not prove PostgreSQL row
locking; the concurrent allocation test is PostgreSQL-only.

## Verification results

- Final related browser run: **139 passed**, with current-source screenshots in
  `test-results/origination-oct22-acceptance`. Screenshot inspection included
  light/dark alignment, reused fields, camera capture and the corrected popover
  boundaries. The separate 430px font capture recorded loaded Plus Jakarta Sans
  faces in both themes, not merely a requested font-family string.
  A final screenshot caught a cramped empty Phone value; max-content label
  tracks fixed it. All **9 focused card checks** then passed, including explicit
  no-overlap assertions; the corrected capture is under
  `test-results/origination-oct22-card-spacing`.
- Fresh isolated backend run: **161 run, 159 passed, 2 PostgreSQL-only skips**.
  Covers reference replay/backfill/search, invalid/incomplete preview distinction,
  authenticated warning-code handling, actual PDF rendering, retained signed
  copies, document selection and ID evidence. No external providers were used.
- Additional migration/phone/field/frontend run: **58 run, 52 passed, 2 skips,
  4 pre-existing source-string failures** in `core.tests_loan_origination_frontend`.
  The ownership upgrade/rollback test completed. Rewinding migration tests can
  remove seeded rows from a retained SQLite test database; the final acceptance
  run deliberately used `--fresh-database`, not that retained state.
- Ruff, JavaScript syntax/field-rule checks, Django checks, migration drift,
  UI source ratchet and `git diff --check` passed. Local Python 3.14.6/Django
  5.1.6 differs from deployment pins; PostgreSQL execution remains unverified.

No production deployment, message/provider dispatch, document upgrade, baseline
approval or cross-app UI migration was performed.
