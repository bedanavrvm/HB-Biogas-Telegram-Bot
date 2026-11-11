# FarmUp source formats and monthly loading

## Owning workflow

FarmUp is the Portal's scoped, month-labelled farmer intake worklist. It uses
`portal_imports.stage_portal_import` and `stage_portal_farmup_version`, the
shared `jawabu_master` CSV parser, revision-bound validation/commit, and durable
Portal publication. Telegram `/farmup` uses the same parser. It is separate
from the initial historical workbook/changeover and from SysUp reconciliation.

Each accepted version retains its exact source bytes, digest, uploader, period
and source row numbers. Upload stages a review; it creates no customer cases.
An exact upload retry reopens the existing worklist. Later monthly versions
retain earlier sources, recognize committed rows and preserve held work.

## HomeBiogas farmers export

The native parser accepts the export directly, without a separately edited CSV:

| Source | FarmUp interpretation |
| --- | --- |
| Full Name and ID NUMBER | Uppercase lead name; use the explicit numeric ID, otherwise the bracketed numeric ID in the name. Preserve ID leading zeroes. |
| Mobile / Phone | Normalize primary / secondary Kenyan mobile contacts. |
| HBG Hub | Uppercase county; never infer a JBL operational branch. |
| Sales Person | Uppercase HB salesperson, retaining original source evidence. |
| Sign Date, Sign Date | Distinct internal source keys; prefer the second export date, falling back to the first only when the second is blank. A named HBG Visit Date takes priority. |
| Actual Receipts Currency containing KES plus an amount | When there is no separate amount column, map to Deposit Paid to HB and validate/normalize through the shared Decimal-based KES policy. |
| Separate Actual Receipts and currency columns | Preserve their separate mappings. A currency code by itself is never an amount or an invented zero. |
| Count / Uploaded Date | Recognized export metadata; retain in source view without requiring manual column mapping. Neither sets visit timing or case numbering. |
| Empty source rows | Skip from the operational worklist count while retaining the entire uploaded file and original source row positions. |

The two repeated date headers are a bounded source-format allowance. Other
duplicate fields, a third Sign Date, generated-key collisions and populated
unnamed columns remain errors. Google register schemas still require unique
named columns. Reordered export fields continue to resolve by name.

Unknown headers still require explicit mapping or Ignore. Explicitly ignoring
the date/amount never silently restores it from another source. Invalid dates,
negative/over-precise amounts and foreign-currency amount strings remain visible
for correction and cannot be committed. Raw source content is never rewritten.

## Review, commit and publication

The existing Portal FarmUp capabilities and group scope govern upload and
commit. Authentication alone supplies no workflow authority. The server checks
the current signed revision, exact row selection, identity matches and explicit
acknowledgement of existing-unit updates. An additional physical unit requires
the existing explicit action and reason; a repeated customer is not automatically
a new unit. Missing required identity/contact details remain for correction.

Accepted rows commit through `commit_portal_farmup` and its native case service.
Django owns the resulting workflow. An HBG visit can schedule JBL work but never
records a completed JBL visit, approval, order or installation. Below-minimum HB
deposits retain the existing visit hold; do not fill missing money or dates to
make a row eligible. Earlier-month HBG dates remain their actual dates even
when the worklist month is later.

Canonical commit and Google publication are separate checkpoints. Commit
reserves UUID-bound work for the configured Master Data/Eco-conserve register
and any other already-enabled native target. Native publication preserves FIFO,
pacing, leases and provider backoff. Resume the saved operation after failure;
never recommit the case to fix a Sheet error. Source archival uses the existing
restricted Drive archive operation. Show synced only after publication succeeds.

## 11 November 2026 verification

The bounded source-format fix passes 137 synthetic tests covering raw export
acceptance, source retention, date/amount validation, explicit mapping,
authorization/scope regressions, commit replay, monthly reconciliation, visit
eligibility, partner routing and publication. The untouched private November
CSV parses as 18 valid rows plus 189 skipped blank rows, with all IDs extracted
by the native parser. Its canonical intake values equal the previously reviewed
copy; 17 deposits meet the existing minimum and one remains held. Three October
visit dates are retained. No customer source data is checked into this repository.

After explicit approval, release `e50f7f53` was merged and deployed. The untouched
original became version 2 of the existing November worklist; all 18 source
fingerprints reconciled unchanged, and the earlier staged file remains retained.
Native FarmUp committed 18 new cases, published all 18 UUID-bound rows and
archived the original CSV. Thirteen rows went to Master Data and five to
Eco-conserve, giving 4,248 cases/register UUIDs overall (4,087 and 161).

The new cases comprise 17 awaiting JBL visit and one minimum-deposit hold.
The global visit queue is 17 Awaiting Visit and nine Deposit Pending; staff scope
and filters still apply. The production job verified that all 4,230 prior case
hashes and Sheet rows were unchanged, with the completed legacy changeover and
three source exceptions retained. Native pacing/backoff recovered Google 429s
and completed all 18 publication operations without recommit or checkpoint reset.
Independent read-only DB/Google readback confirms every new row's identity,
staff reference, calendar date, deposit and status labels, with exact unchanged
hashes on all 4,230 earlier cases and Sheet rows. The original source is archived,
both source versions remain retained and the worklist reports 18 of 18 synced.
Typed Sheet dates are read back as serial values; the verification compares
their underlying calendar dates, including all three October dates.

Native pre/post-deploy checks found no readiness errors or pending migrations,
and both public health endpoints returned 200. No migration, permission,
dependency, configuration or browser-admission change was needed. PostgreSQL
concurrency tests were not rerun for this parser-only change. Private evidence
retains the approval, exact source hashes, native jobs, publication checkpoints,
before/after fingerprints and readback results. Code rollback leaves retained
sources and committed cases intact; it does not reverse Google publication or
delete intake records. Never delete a staged version or repeat legacy cleanup.
