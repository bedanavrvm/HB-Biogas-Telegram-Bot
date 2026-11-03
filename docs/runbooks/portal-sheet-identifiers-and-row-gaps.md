# Portal Sheet identifiers and row gaps

The 3 November legacy writer bypassed the normal Portal reference projection:
it put the case UUID into both Case ID and Master Record ID. Its fallback
destination was the workbook's Source Row. A clean tab therefore received
source rows 100 and 200 at physical rows 100 and 200. Normal publication also
appended after the last occupied row, leaving earlier gaps unused.

## Corrected behavior

- Case ID uses the existing staff reference, such as JBL-123. Master Record ID
  retains the exact immutable UUID and is hidden. FIFO sync, full replacement
  and the reviewed binding command follow the same rule. Reset still proves
  ownership using the UUID; the readable reference is not a replacement key.
- Existing identified rows update in place. An unbound raw source row must
  still pass identity checks before it is updated. New rows without an existing
  counterpart use the first fully empty data row, starting at row 2 on the
  standard header-only tab. Source Row remains historical provenance in Django.
- Formula-only rows and cells containing zero remain occupied. Normal Portal,
  FarmUp and FCA allocation consult formulas when identifying available rows.
  No existing case is moved automatically, and unrelated rows/registers survive.
- FIFO scans are bounded to 250 rows. Writes remain bounded to 50 cases,
  three seconds of planning and 512 KiB. Allocation checkpoints stay in Django
  and are omitted from summary responses. Plans survive lost acknowledgements.
- Resuming a held partial upload rechecks old receipts that still use the UUID
  presentation. Old uncertain writes finish verification before their readable
  IDs are corrected in place. An older full replacement can also finish readback
  and upgrade both identity columns without repeating the replacement.

Deploying code does not directly change a production Sheet. Resume an unfinished
saved import to continue its bounded corrections. Do not delete cases or upload
again merely to change the displayed reference. Existing gaps are available to
new rows; this change does not compact historical case rows.

## Local evidence

`test-results/legacy-row-allocation-red.log` reproduces UUID exposure and sparse
source positions leaving rows 2 and 3 empty. Regression cases use real signed
Portal requests, XLSX parsing and PostgreSQL; only Google transport is simulated.

The real Django/Playwright workflow imports 61 Eco-conserve cases from source
rows 100–160 and checks physical rows 2–62, preserves a pre-existing row 64 and
the Master Data counterpart, and verifies the short/UUID split for every case.
It includes the 50-row partial save, a lost provider acknowledgement, a lost
browser request, reload/resume, and 320/390/1280-pixel captures.

Artifacts: `test-results/legacy-importer-automated-browser/`, including the
synthetic `projected-synthetic-sheet.xlsx`, and
`test-results/legacy-identifiers-rows-final.log`.

The final focused run passed 36 checks, including verified Sheet deletion,
explicit authorized return to Live mode, and a fresh import starting at row 2.
The wider run passed 88 of 91 checks, including the Playwright workflow; its
three older FarmUp failures were also reproduced with the unchanged HEAD writer
and allocator. Two fixtures supply a duplicate key where the existing reference
helper requires a UUID, and one expects two provider writes rather than three.

A fourth, broader existing pipeline test expects an integer 7000 but its fake Sheet
returns the equivalent text 7000.00. The failure was independently reproduced
with the HEAD publication/allocator functions restored in process, without
changing workspace files: `test-results/legacy-row-publication-head-baseline.log`.
These four pre-existing failures are separate from this change. Their assertions
and the production money rules were not weakened.

No production reset, database change, Sheet write or deployment was performed.
