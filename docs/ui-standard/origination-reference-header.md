# Origination reference header and main page - source-bound candidate

22 October 2026. Implements the user's supplied mobile-header HTML, explicitly
excluding a phone/National ID header row. This scoped approval is not a shared
UI-standard approval, token rollout or Design Lab Phase 6 migration. Supersedes
the header/contact-row portion of `origination-ui-corrections.md`; its other
form, capture and document behaviours remain unchanged.

The user subsequently supplied the application-list reference and explicitly
removed the redundant Complete application card action. The main page adopts
that hierarchy without importing the reference's real identifiers, fake JB
logo, device frame, user-selection/zoom restrictions or Tailwind runtime.

## Scope and source

- `origination/static/miniapp/loan_origination.js`: one integrated header with
  applicant name, product/status badges and the existing Manage documents,
  Preview and Download actions. No duplicated contacts/reference strip.
- The second row contains the real dynamic section count/title, an anchored
  section chooser and previous/next controls at opposite ends. The progress
  line is navigation position, not a claim that earlier sections are complete.
- The chooser uses ordinary labelled navigation/buttons, an explicit expanded
  state and current step. Arrow keys, Home/End, Escape, outside pointer/focus,
  and Telegram Back close/navigation are supported. Saves still precede section
  changes. Parallel navigation clicks are joined; failure preserves answers.
- Existing scoped phone-registration checks move beside their Applicant fields;
  read-only applications keep a collapsed Phone registration body section.
  No provider requests, permission changes or automatic paid checks are added.
- `origination/static/miniapp/origination_compact.css`: scoped header styles
  override the shared generic `header` flex rules. Small unboxed action glyphs
  retain separate 44px targets and visible keyboard focus. Long titles truncate
  visually but retain their full accessible text/title; section labels wrap.
- The main page has a compact real-logo header, Start/Refresh controls, segmented
  queues, search icon and separate filter button. White/theme-surface cards show
  applicant/status, product/branch/readable reference, then two aligned labelled
  identifier columns. Missing values keep the same tracks. The whole card is a
  keyboard-operable button; its independent phone link retains a 44px target.
  No Complete application, View application or arrow action row is repeated.
  Authorized officer attribution is shown only when available; specific review
  feedback remains. Scope, filters, role grants and API field disclosure do not
  change. The accent uses existing JBL/Telegram theme variables, not a new theme.
- Main LAF/supporting input and body typography/sizing are unchanged. No fake
  device frame/status bar, Tailwind/CDN dependency, zoom lock or candidate tokens.
- `origination/templates/loan_origination/app.html`: asset cache versions only.
  Document options, preview warnings, downloads, signing policy and the earlier
  automatic unsigned document refresh retain their current service contracts.
  Automatic refresh does not replace the form while the section chooser is open.

## Evidence

Actual Django shell, ordered production CSS/JS, synthetic application data and
Telegram/API I/O are exercised by
`core/tests_browser/origination_application_forms.spec.js`. The phone-check
interaction suite is `core/tests_browser/origination_phone_identity.spec.js`;
existing queue/filter/document journeys are `origination_queues.spec.js`.

```powershell
npx playwright test --config=playwright.config.js core/tests_browser/origination_application_forms.spec.js core/tests_browser/origination_phone_identity.spec.js core/tests_browser/origination_queues.spec.js --workers=1 --output=test-results/origination-reference-final
```

Captures cover mobile light/dark, 320/360/390/430px, expanded section chooser,
200% text, aligned validation and supporting fields. Font/source metadata is
retained alongside captures. Initial screenshot inspection exposed the generic
header flex rules constraining the navigation row; the scoped override fixes
this and leaves the surrounding form scale alone. A second inspected capture
shows the full-width navigator and no contact strip.
Main-page light/dark captures also cover full, missing and long-name cards,
independent dial links, keyboard card activation, filter alignment and removal
of the redundant action. Compact-card bounds are tested, not relaxed to mask
spacing regressions. A final pass improves the dark accent/draft contrast and
limits the navigation label to two visual lines at enlarged text settings;
the chooser and accessible label still retain the complete section name.

## Local acceptance

- **92 browser tests passed** across the three suites, under
  `test-results/origination-reference-verified`. This includes document
  selection/reselection, save failures, draft recovery, incomplete previews,
  downloads, ID capture, native-action stubs, filters and phone verification.
- After the final responsive-only polish, **18 focused layout checks passed**
  under `test-results/origination-reference-layout-final`. Final source-bound
  captures include `main-page-light.png`, `main-page-dark.png` and their enlarged
  text counterparts in the `reference main page` test directories. Both card
  columns share label/value tracks even when labels wrap. At enlarged text,
  segmented controls stack rather than overlap. The desktop/mobile compact-card
  height guard remains unchanged. Font metadata at 430px in both themes records
  five loaded Plus Jakarta Sans faces alongside the real shell asset URLs.
- Header and section-menu light/dark screenshots were inspected in
  `test-results/origination-reference-polish` and
  `test-results/origination-reference-verified`. The 200% header label stays at
  most two visual lines; the chooser still exposes the full title.
- Isolated backend: **63 run, 61 passed, 2 PostgreSQL-only skips** across
  `origination.tests_document_refresh`, `origination.tests_document_management`
  and `origination.tests_form_projection`. SQLite does not verify PostgreSQL
  locking/concurrency. Existing unsigned refresh work remains in this worktree.
- JavaScript syntax (148 files), Ruff on the touched Python refresh boundary,
  Django checks, migration drift, UI source ratchet and `git diff --check` passed.
  The new header/main-page work itself makes no Python/schema changes.

These captures do not approve shared baselines. Real Telegram webview/device
behaviour and deployment are not claimed by browser fixtures. No production
database, SMS/provider dispatch, external file change, commit or deployment was
performed. Normal code/static deployment is needed to expose this UI to staff.
