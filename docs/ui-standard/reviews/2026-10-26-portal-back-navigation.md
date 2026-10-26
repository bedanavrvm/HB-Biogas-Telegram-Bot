# Portal Back navigation corrections — 26 October 2026

The user's instruction to fix the five reported Back-navigation issues authorizes this bounded repair. Existing Portal arrows, navigation drawer, form guards, native payment dialogs and `PortalDialogs.confirmAction` remain the interaction sources. No new visual pattern, token set, permission, workflow transition or persistent navigation state is introduced.

## Corrected behavior

| Finding | Correction | Regression evidence |
|---|---|---|
| Cancelling photo discard still closed the JBL visit | The shared shell leaves farmer-sheet closure to its controller, which retains the open form and local files when the user cancels. Confirmed discard still closes and clears the selection. | `Portal sheet-back/telegram keeps visit photos when discard is cancelled` |
| Invoice/HB arrows opened All Cases or showed an unrelated permission error | Case History interception now requires `data-return-screen`; invoice/HB links retain their own destinations and the existing navigation guard. | Invoice, installation, commissioning and deposit Back tests, each with and without All Cases access |
| Telegram Back returned to Home or the wrong HB workstream | Payment detail returns to its preparation/review list with current URL filters; FarmUp returns to its monthly list. HB uses its rendered parent link, including inferred commissioning, with an allowlisted workstream fallback. | Six parent-route cases and an inferred commissioning deep link |
| Telegram Back skipped a payment confirmation | Open native dialogs receive a cancellable `cancel` event, then close with a cancellation result if permitted. Existing receipt-preview cleanup retains priority. Custom Portal confirmations invoke their existing Cancel control and announce open/close state. Main actions remain unavailable underneath confirmations. | Native payment cancellation without submission, cancellation veto, and custom-confirmation tests |
| Telegram Back could not dismiss navigation | An open drawer gets a Back handler using its existing close/focus-restoration action, before page navigation. Closing restores the screen's normal Back state. | Top-level and nested-page drawer tests |

The HB parent link now contains the server-selected workstream before its API response arrives. This covers direct entry, delayed/failed loading and installed cases whose workstream was inferred by Django. Django route-rendering checks assert installation and commissioning parent URLs.

## Source-bound nonvisual exception

The ratchet's `changes` entries bind the current hashes for:

- `core/static/miniapp/miniapp-nav.js`: parent resolution and dismissal priority.
- `core/static/miniapp/portal.js`: Case History selector scope.
- `core/static/miniapp/portal_dialogs.js`: existing dialog lifecycle notifications.
- `core/templates/portal/portal.html`: server-selected HB parent URL.
- `core/templates/base_shell.html`: cache versions for the corrected scripts.

These are behavioral repairs to existing controls. Their appearance, styles and DOM composition remain unchanged. Previous review context, including [HB Deposits](../../../codebase-analysis-docs/assets/HB_DEPOSITS.md#ui-candidate-and-evidence), remains applicable. Original legacy hashes, candidate status, visual baselines and the Phase 6 migration hold are retained. This record is implementation evidence, not human visual approval or production-device acceptance.

## Verification

Automated evidence is produced by `core/tests_browser/portal_case_navigation.spec.js`, the broader `portal_` Playwright suites, `core.tests_portal_navigation` and the HB mobile-route test. Tests use synthetic values and mocked Telegram controls. Backend checks ignore deployment `.env` values and block network connections through the existing local audit harness.

The actual Portal shell/CSS and confirmation controller were captured at 320px in light and dark themes. Theme colors are asserted before capture; tests cancel the confirmation while retaining the parent sheet. Local review captures:

- `test-results/portal-back-fixes/guards-and-themes/portal_case_navigation-Por-47e7f--before-its-parent-in-light/back-confirmation-light.png`
- `test-results/portal-back-fixes/guards-and-themes/portal_case_navigation-Por-9c3fd-n-before-its-parent-in-dark/back-confirmation-dark.png`

The navigation tests also exercise existing Case History Back/Forward, selection/revision recovery, denied/timeout responses, unsaved-change rejection and foreground-write blocking. Raw suite evidence is retained locally under `test-results/portal-back-fixes/`.

- The full `portal_` browser run passed **293 tests**, with no failures, skips or retries.
- The additional guard and corrected light/dark checks passed **3 tests**. Two theme cases also appear in the full run; the unsaved-change/active-write case is additional, for **294 distinct browser checks**.
- First-party JavaScript syntax validation passed for **164 files**; the Node client suites passed.
- All **9 isolated Django checks passed** for navigation and rendered HB parent URLs, using local SQLite with deployment settings ignored and networking blocked. SQLite's unsupported table/column-comment warnings are expected; PostgreSQL was not exercised.
- `scripts/check_ui_standard.py` and `git diff --check` passed. The ratchet retains its original legacy source hashes and Phase 6 hold.

Physical Android/iOS Telegram, device gestures and WebView process restoration are not certified by Chromium or a mocked BackButton. No live Sheet, Drive, email or Telegram operation was performed.

## Rollback

Revert these navigation corrections and their cache-version/ratchet records together. No migration or data repair is required; reverting reintroduces the five reported defects, including the local-photo discard bug.
