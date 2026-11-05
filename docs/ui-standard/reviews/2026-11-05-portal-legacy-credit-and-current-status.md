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
