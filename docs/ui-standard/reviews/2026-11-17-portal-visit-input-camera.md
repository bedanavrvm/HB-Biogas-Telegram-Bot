# Portal deposit lock, entered names and visit controls — 17/11/2026

The user requested that deposit-pending cards cannot open Log visit, names entered
in Portal use consistent capitalization in the app and Sheets, Repayment Terms
match adjacent sections without nested cards, the repayment-day hint say
**5th or 12th**, and camera recovery work without reopening the Mini App.

## Sources and behaviour

Both the native fragment and JavaScript queue renderer retain the existing grey
deposit card, supply `aria-disabled`, omit phone links and block its click handler.
The shared case-sheet entry point checks the freshly fetched deposit state too,
so a stale cleared card cannot open a newly held case. A fresh Create lead form
remains usable. The existing server deposit gate and HB deposit authority remain.

Portal intake, case-name corrections and entered visit-officer names use the same
format-only name helper. It collapses whitespace, capitalizes ordinary uppercase,
lowercase or inverted-initial words, preserves punctuation and intentionally mixed
case such as McDonald, and retains HB/JBL abbreviations. Saved canonical values
feed both the Mini App and the Master Data/Eco-conserve and internal-order Sheet
projections, without forcing entered names back to uppercase. Historical records are not bulk
rewritten; IDs, identity matching and signed document bytes are unchanged.

Repayment Terms uses the existing external section label and paired field rows,
with one field container, matching Visit Details and Comment. Only its redundant
outer support card is removed. Both visit and final-correction day inputs use the
requested hint; the accepted day range remains 1–31. LAF readiness, negative-outcome
requirements, saved terms and explicit final-review correction are unchanged.

Camera startup is single-flight. Closing during a permission prompt invalidates
the request and releases a late stream. Playback failure retains an acquired
stream for explicit Retry, without another permission request. Acquisition failure
also offers Retry in place with conditional settings guidance. Playback and
acquisition are distinct: [`play()` may reject with NotAllowedError](https://developer.mozilla.org/en-US/docs/Web/API/HTMLMediaElement/play).
The retry control matches existing compact buttons. These are reproduced failure
paths, not a confirmed diagnosis from a physical Telegram handset.

Changed UI sources: `portal.js`, `portal_farmer_sheet.js`, `portal.css`, the native
Portal page, the farmer-card fragment and `base_shell.html` asset versions.
Existing source-bound patterns are reused; no candidate tokens, baseline changes,
new permissions, schema change or Phase 6 migration is introduced.

## Browser evidence

Playwright ran the actual Django Portal shell on isolated PostgreSQL with signed
synthetic Telegram credentials. Native queue/detail, metadata, location and draft
APIs were used. A second native journey entered uppercase customer and mixed-case
salesperson names, saved an awaiting-deposit lead, read the normalized values back
from its authorized detail API, and verified the saved card stayed disabled.
The initial synthetic owner configuration was corrected before that final journey.

The layout was inspected at 390px and 1280px in light mode, and 320px in native
dark mode. Repayment labels and border hierarchy were compared with surrounding
Comment/evidence controls. No horizontal overflow or JavaScript page errors were
recorded. `23/11/2026` and `03/12/2026` round-tripped under an en-US browser locale
with ISO hidden transport values. Camera streams/playback were simulated;
external sockets/provider requests were blocked.

- [Deposit-held queue](portal-visit-2026-11-17/deposit-locked-mobile.png).
- [Repayment mobile](portal-visit-2026-11-17/repayment-390-light.png).
- [Repayment desktop](portal-visit-2026-11-17/repayment-1280-light.png).
- [Repayment dark, 320px](portal-visit-2026-11-17/repayment-320-dark.png).
- [Camera preview recovery](portal-visit-2026-11-17/camera-preview-retry.png).

Automated checks cover both queue renderers, stale detail, deposit boundaries,
camera playback/acquisition recovery, overlapping permission requests, late-stream
release, required-field rules, LAF readiness, retained drafts, date format, scoped
corrections and canonical name/Sheet projection equality. The previous server-card
test allowing held-card entry was updated to the user's new non-clickable rule.
The Sheet tests now expect the canonical name case; two older queue-card date
assertions were aligned with the existing required dd/mm/yyyy display.

Verification completed: 148 PostgreSQL tests across Portal input names, case
corrections, deposits, visit repayment/outcome requirements, identifiers and the
JBL pipeline service; 20 focused Playwright tests across camera, deposits, case
navigation and visit controls. The separate native Django journeys described
above also passed. UI source ratchet, 221-route write inventory, 180-file
first-party JavaScript syntax, selected Ruff checks, migration drift check,
233-table database catalogue check and Git whitespace check passed.

Not verified: actual phone camera/Telegram permission lifecycle, live Google Sheet
writes or production deployment. No production data or grants were changed.
