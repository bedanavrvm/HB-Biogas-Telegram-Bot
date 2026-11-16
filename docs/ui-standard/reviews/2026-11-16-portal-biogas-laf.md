# Portal Biogas LAF and shared signing — 16/11/2026

## Requested behaviour and sources

Upload/camera remains primary. Form filling is a secondary action on the same
Portal case. Reuse current section labels, paired form rows, native controls,
date display/calendar pattern, compact status and the existing typed signature
appearance. The dedicated signing surface shares its renderer/mark control
with Origination. No candidate tokens, approved baselines or Phase 6 migration
are adopted. Origination template changes only select shared asset paths.

Sources: `core/static/miniapp/portal_farmer_sheet.js`, `core/templates/base_shell.html`,
`portal_lafs/static/portal_lafs/`, `document_signing/static/document_signing/`, and
the two existing Origination shell templates. Shared backend extraction does
not change grants, signing links or retained Origination document bytes.

## Browser evidence

Playwright exercised the real Django Portal shell against isolated PostgreSQL
with actual signed synthetic Telegram initData and a canonical technical actor.
The case was opened through the existing case-sheet entrypoint after fetching
its authorized native detail endpoint. Subsequent filling, saving, previewing,
signing and source selection used the rendered controls and native HTTP APIs.
No authentication bypass or screenshot-only mock page was used.

The fixture uses a small synthetic published Biogas document and four test fields;
its source PDF is supplied locally instead of Drive. External sockets are blocked.
This verifies the implementation's controls, not the production document's actual
field mappings, complete content or live signer configuration.

- [Existing upload plus secondary form action](portal-biogas-laf-2026-11-16/visit-options-final.png).
- [Desktop paired-field form](portal-biogas-laf-2026-11-16/form-desktop-final.png).
- [Mobile form](portal-biogas-laf-2026-11-16/form-mobile-final.png).
- [Shared in-app signing](portal-biogas-laf-2026-11-16/in-app-signature.png).
- [In-person client signing on mobile](portal-biogas-laf-2026-11-16/in-person-signature-mobile.png).
- [Signed mobile form in native dark theme](portal-biogas-laf-2026-11-16/signed-mobile-dark.png).

Verified: server-saved draft survives page reload; opening/closing the LAF retains
the underlying visit comment; `23/11/2026` and `03/12/2026` round-trip without locale
reversal; BRO typed mark previews and commits against the reviewed page; signed
answers lock; selecting filled evidence changes the active source; later credit
signature remains pending. Desktop 1280×900 and mobile 390×844 were inspected.
The final browser journey recorded zero JavaScript page errors and no horizontal
overflow in the mobile form. The actual Telegram theme-change callback was invoked
for dark review. Early fixture-only missing Telegram stub methods were corrected
before the final clean browser run.

The revised journey also signed both a client and guarantor directly through the
authenticated Portal API. Client consent plus the officer's witness are required;
the confirm button stays disabled without both. There are no OTP controls, requests
or SMS configuration prerequisites. Backend checks cover missing consent/witness,
remote-mode rejection, unauthorized witnesses and replay without duplicate signatures.

Automated backend coverage separately verifies role/group scope, replay/conflict,
stage gates, in-person consent plus authenticated officer witnessing, negative outcomes,
replacement/history, concurrent workers, unsigned adoption and archive failure.
Two stale JBL API expectations were aligned with the already-current slash date
format and the existing `portal_credit_decision_blocked` code; business behaviour
was not changed to satisfy those assertions.

Final local validation: 193 focused Portal/Origination/catalogue regression tests
passed on fresh PostgreSQL, including the 18 Portal LAF tests. UI-source, write-route
inventory (221 routes), migration-drift, Ruff and JavaScript syntax checks passed.
The unrelated existing duplicate `RequisitionBatch.order_number` index check is
documented in `KNOWN_GAPS.md` and was excluded from this focused passing run.

Not verified here: native handset hardware/camera, production
template readiness or live Drive publication. Portal remote invitations are
deliberately outside this release.
