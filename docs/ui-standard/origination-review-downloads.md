# Origination review, previews and Mini App download delivery

22 October 2026. Scoped user-requested corrections, alongside the compact-card
candidate in `origination-compact-cards.md`. This is not shared-token migration,
Design Lab approval or authority to deploy to production.

## Review layout

`origination_compact.css` keeps review section cards in two equal, min-width-zero
columns, including at 320px. Long labels wrap inside the card; at narrow widths
the Edit/Open affordance sits beneath its text rather than squeezing it. The
preview action spans the review content width. Larger text wraps without
horizontal overflow. Main/supporting form input sizes and typefaces are untouched.

## Preview diagnosis and bounded fix

The real-shell browser test with a synthetic 1.2-second save reproduced a hidden
viewer while the eye action waited. Opening now shows Saving changes/Loading
preview immediately, guards duplicate opens and checks request/application
identity after saving. Closing remains effective during a save or render. No
preview request is permitted before saving succeeds. No background PDF warming
or automatic provider call is introduced.

The actual packet-preview view also rendered the entire PDF before reporting
missing fields. `test_incomplete_bundle_warning_does_not_generate_a_pdf` failed
with one real renderer call before confirmation; it now requires zero. The
confirmed preview still renders normally, and incomplete viewing never marks
the application ready. Existing page prefetch/cache and signing checks remain.
This removes a demonstrated wasted render, not a promise about production
network/storage latency or per-page rendering speed.

`render_packet` now sorts primary documents first, then configured supporting
display order and a stable key tie-break. Its real-renderer regression gives the
Main LAF a later display order and checks extracted PDF page text. Preview,
unsigned combined downloads and newly prepared signing bundles share this path.
Historical frozen/signed bundles and manifest-bound individual extracts retain
their exact original order and bytes; they must not be regenerated to reorder.

## Download audit

The four native `downloadFile` call sites were traced through their producers
and delivery endpoints. All already use Telegram's correct `file_name` property.
No credential, customer document or live download link was recorded.

| Consumer | Finding and correction | Regression boundary |
| --- | --- | --- |
| Origination combined/individual application PDF | Whitespace-only metadata passed the truthiness check. Trim and reject blank/unsafe filename before native handoff or anchor fallback. Normal filenames remain descriptive. | Actual download chooser, confirmation and Telegram stub payload |
| Complaints register/reports Excel | Whitespace-only metadata bypassed the default name. Trim before display, File/anchor creation and native handoff; use `complaints.xlsx` when blank. | Actual report/export controls, result text and native stub payload |
| TAT report Excel | Already trims, checks `.xlsx` and rejects path/newline characters. Named fallback link and cancellation remain. No production change needed. | Existing actual export flow with accepted, cancelled, unsupported and throwing clients |
| Portal reports, orders, payments, history and correction letters | All use `downloadPortalFile`, which already trims/falls back. Four signed download views lacked some Telegram Web CORS/attachment/length metadata; use one local response helper after each view's existing authorization. Whitespace retained workbook/letter names get a descriptive server fallback. | Real GET/HEAD views with synthetic storage/authority dependencies; existing actual correction-letter UI handoff |

Direct browser/blob downloads also checked: Origination evidence/signed-PDF open,
Portal fixed/custom reports and requisition exports, Complaints desktop Excel,
TAT credit-assessment evidence. These use explicit anchor filenames, response
attachment names or their existing fallbacks rather than the native popup.
No native download call was found in the current SPIN/order-approval scripts.
This is a source audit, not an end-to-end claim for every external document type.

Telegram's [official download contract](https://core.telegram.org/bots/webapps#downloadfileparams)
requires `file_name` and recommends named attachment metadata plus the specific
`https://web.telegram.org` origin. Portal responses now include that origin,
exposed attachment/length/type headers, actual full length on GET and HEAD,
private no-store caching and an empty HEAD body. Tokens, expiry, authorization,
scope checks and document finality remain at their existing owning view.

The whitespace-name bug and missing headers are reproduced local findings.
They are not proof of which caused the user's particular native blank prompt;
the exact app/client/screenshot was requested. A real Telegram confirmation
dialog is outside Chromium's SDK stub. Confirm its displayed name and native
accept/cancel behaviour on staff devices after normal code/static deployment.
Native acceptance is not proof that a file finished downloading.

## Evidence

- `test-results/origination-review-before`: six layout failures, silent-save
  viewer failure and blank-name handoff reproduced before the fixes.
- `test-results/download-names-before`: Complaints handed whitespace to Telegram.
- `core.tests_download_delivery`: four real views initially lacked GET/HEAD
  metadata; its denial check verifies no attachment escapes an unauthorized call.
- `test-results/origination-review-first`: nine checks passed, including inspected
  320px light/390px dark review screenshots and the earlier 320px dark header
  timeout rerun. The screenshots use the real Django Origination shell/assets,
  synthetic records and actual browser-computed layout, not a recreated mockup.
- Final combined browser regression: **270 passed** under
  `test-results/origination-review-downloads-verified`, spanning real-shell
  Origination forms/cards/queues, phone checks, signing/download UI, Complaints
  reports, TAT queue/native export and Portal media/letter controls. No cases
  failed or were skipped in that run.
- Server verification: **26 application-copy tests passed** on isolated SQLite,
  including actual PDF rendering, signing-byte integrity, incomplete previews,
  download authorization/expiry/revision checks and Main-LAF-first ordering.
  The first combined server run passed those plus five metadata tests (31 total);
  the final metadata suite passed six after adding whitespace workbook coverage.
- First-party JavaScript syntax (148 files), Ruff, UI source ratchet and diff
  whitespace checks passed. Database comment warnings are SQLite limitations,
  not proof of PostgreSQL execution; PostgreSQL was not used.

Inspected review evidence: final `review.png` captures at 320px light and
390px dark. The preview button aligns with both columns. Native phone behaviour
and production rendering timings remain unverified; no production access was
used. No claim is made that every signed download type was exercised in Telegram.

No baseline images are updated. No schema migration, new dependency, role
change, SMS, Telegram message, Sheet/Drive write or production deployment occurs.
