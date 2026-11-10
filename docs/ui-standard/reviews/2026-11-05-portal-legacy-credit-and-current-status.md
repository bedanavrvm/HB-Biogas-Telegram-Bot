# Legacy credit marker and confirmed current status

The user requested a Legacy credit-analysis value and a current pipeline status
that reflects the reviewed continuation. Existing Case 360 fields, dropdowns,
badges, queues, progress strip and Sheet projection use the shared pipeline
formatters; no new control, spacing or visual component is introduced.

Missing credit decisions on committed legacy imports display Legacy. Actual
recorded credit decisions remain unchanged. Native activity takes precedence;
the marker cannot authorize approval, populate a decision actor/date, or satisfy
new-case prerequisites. The importer accepts a projected Legacy marker as an
unknown historical credit decision and retains the original source text.

Confirmed legacy stages now control current labels and stage numbers even when
historical dates are missing or older visit outcomes remain. Deferred/rejected
continuations retain their stage-specific status; Withdrawn remains Withdrawn.
Actual HB delivery evidence still takes precedence for installation/commissioning.
Existing automatic post-confirmation refresh and publication are reused.

The real signed-Django/PostgreSQL Playwright baseline selected JBL Visit but
displayed Awaiting HBG Visit. Its failing output is retained in
`test-results/legacy-status-before.log`. The corrected browser journey imports
synthetic XLSX rows through the actual review/commit/sync workflow, confirms
JBL, credit, final-review, order, rejected/deferred and withdrawn continuations,
and checks detail/API/Sheet state. It also covers an explicit historical approval,
roundtrip Legacy marker, native Pending, and Pending after native credit activity.
Dates, decision actors, source facts and canonical unknown decisions are checked
separately from display labels. Desktop/mobile captures, source hashes and
readback results are under `test-results/legacy-pipeline-browser/`.

No static UI source, approved baseline, migration hold or production record is
changed. Google transport is simulated; live Sheet delivery is not claimed.

## 10 November: include known historical credit outcomes

The user confirmed that initial-load Credit Decision should display Legacy even
when the retained source says Approved, Rejected or Deferred. The shared backend
formatter now marks that provenance without changing the stored decision,
pipeline state, revision, actors, dates or source row. Native Portal activity
still takes precedence. This is distinct from the twelve-value pipeline status.

Queue badges and the requisition preview now consume the existing display label;
Legacy reuses the existing neutral badge. The actual credit submission controls
and their values remain unchanged. The three script cache versions advance.
These are content/formatter corrections using existing components, with source
exceptions recorded in the UI ratchet; no design baseline or migration approval
is implied.

Reproduce the synthetic signed Portal check with
`RUN_PORTAL_LEGACY_CREDIT_E2E=1 python manage.py test core.tests_portal_legacy_credit_browser`
against an isolated PostgreSQL test database and the committed Node dependency
lock. It opens the real All Cases queue, checks the legacy rejection badge,
opens its Credit Analysis section, and checks historical/native API values in
light/dark 390×844 shells, including the JSON fallback during a simulated
fragment outage. Native Telegram theme colors are supplied by the synthetic
host; computed backgrounds are asserted before capture. Captures and observations are retained under ignored
`test-results/legacy-credit-labels/`. Focused PostgreSQL tests separately cover
both registers, initial and normal Sheet projections, formulas and native
precedence. Google transport is simulated; this does not establish live delivery.

Local verification: 28 focused PostgreSQL tests passed, including the four
light/dark × fragment/fallback browser scenarios. Changed Python Ruff checks,
JavaScript syntax, Django system checks, migration dry run and the UI source
ratchet passed. No model changes were detected. Real Telegram devices, full CI
and production publication of this updated label were not exercised here.
