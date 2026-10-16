# Design Lab implementation status - 16 October 2026

## What is ready to review

The restricted lab, evidence/decision storage, source inventory, candidate
foundations, diagnostics and review queue are implemented. None of the designs
is approved, no standard release is seeded, and no operational UI is migrated.
The four apps' existing CSS, JavaScript and templates are unchanged.

| Plan area | Delivered | Still requires work or a human decision |
| --- | --- | --- |
| Preparation | Four-app scope, 31-pattern catalogue, screen inventory, synthetic profiles and fixtures | Staff-device shortlist; final theme, density and control-ownership choices |
| Read-only audit | Source hashes/pointers, declared-value counts, browser captures and computed measurements | Specialised journeys and all role/state combinations; manual accessibility and native checks |
| Review | Mobile comparison board, previous/next, compare-all, review filters, notes and immutable evidence/decision history | The reviewer must select, request changes, decline or defer each pattern |
| Foundations | Lab-only token candidates, three densities, Telegram/JBL and automatic/light/dark modes | Approve a scale; extract production consumers only after migration approval |
| Design Lab slices | Source gallery, explicit device diagnostics, persisted review queue and standard export | Notification delivery remains off; real Telegram/device outcomes are not assumed |
| Guardrails | Component index, agent rule, 90-file legacy ratchet, new-file review checks, release digest/source checks and scoped token lint | Approved visual baselines and consumer-specific exception decisions |
| Migration | Hold and migration-package checklist | **Not started. Separate explicit approval required.** |

## Reproducible evidence

`export_ui_audit` writes 224 synthetic source scene documents plus the pattern,
screen, source and declared-CSS manifests. No operational views or records are
used. The browser capture tool verifies source hashes before and after a run.

The local review sets are ignored artifacts, not committed approved baselines:

- `test-results/ui-audit/index.html`: eight scene categories, one-item and
  long-text states, 360x740 and 390x844, both appearances.
- `test-results/ui-audit-states/index.html`: queues in all seven states (one,
  empty, many, long, loading, failure, denied), both sizes and appearances.
- `test-results/ui-lab-final/`: browser-test screenshots of the review board
  at 320/390/1280 and each app's actual card renderer.

The JSON capture reports distinguish successful file capture from a visible
component. Missing selectors, unsupported requests, blocked redirects, overflow,
target dimensions, computed values and runtime errors remain visible. Current
app templates and renderers are reused; the synthetic adapter changes I/O only.

## Coverage limits - do not infer approval

Source queue/card renderers work for all four apps. Portal uses its actual
server-rendered farmer-card partial. TAT's synthetic create form has a BRO
roster matching the actual frontend contract. Capability profiles are synthetic
presentation profiles, **not** real user accounts or a workflow-policy audit.

Detailed histories, signing/OTP journeys, camera/media previews, report datasets,
settings/recovery and application-specific dynamic form sections are not fully
modelled. A shell or empty chart is not evidence for its complete behaviour.
Patterns which do not exist in an app are excluded from its alternatives.

Remote fonts are blocked during automated captures. Font-family declarations
are not proof of the rendered face. Verify the actual font before approval.
Native Telegram controls, real file-download behaviour, 200% text enlargement,
keyboard/safe-area changes and physical haptics need staff-device review.

Private screenshot uploads use the existing configured Drive media storage
only after an explicit reviewer upload. Provider success/outage is tested with
mocks; no real upload, Telegram notification or production database write was
performed. Verify the configured storage folder's private access before use.

## Verification

- Focused Design Lab plus launcher tests: 21 passed on isolated SQLite.
- Browser checks: 15 passed, including source-backed cards for all four apps,
  opaque-frame access/write protection, captured original redirects, mobile
  light/dark layouts, review filtering and upload-failure recovery.
- UI guard tests: five passed; source ratchet passed.
- Source hash tests cover Windows/Linux text endings without ignoring actual
  content changes. The review registry is explicitly allowed by `.gitignore`.
- Changed-file Ruff, JavaScript syntax, Django check, migration drift and
  database governance passed. The generated 209-table catalogue verified.
- Broader selected Django run: 24 passed, one existing duplicate-index failure
  in `core.RequisitionBatch.order_number`. Neither that model nor its test changed.
- Script-test discovery with isolated Django settings: 27 passed, one failure
  caused by the existing 34 uninventoried write routes.
- Starting-commit comparison confirms the same 34 inventory issues, 119 settings
  absent from `.env.example`, and one API ORM-boundary finding before this work.
  The four new lab write routes are inventoried; none adds a new inventory issue.

This is not a full-suite green result. PostgreSQL, real Telegram, actual Drive
upload and deployment were not exercised. PostgreSQL coverage is wired into
the existing CI job, not claimed as locally executed.

## Next human gate

Deploy through the normal authorised migration/static pipeline, enable
`UI_DESIGN_LAB_ENABLED=True`, and open `/ui-lab/` as an active Superuser. Begin
with the foundations and actual queue cards; leave uncovered behaviours
unapproved. Complete their fixtures/device evidence before adopting them.

Once decisions are complete, prepare/export a reviewed standard, identify exact
consumers and intentional variants, and present the Phase 6 migration package.
Do not begin that migration until the user explicitly approves it.
