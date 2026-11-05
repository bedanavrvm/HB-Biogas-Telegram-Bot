# Complaints changeover and verified Sheet sync

The user's 5 November request makes Complaints follow the Master Data changeover:
remove the existing test cases, clear the selected register and start publishing
the imported cases. This adapts the existing compact importer; no new design
system, dependency, approved baseline or Phase 6 migration is introduced.

## Behaviour and scope

- A Superuser reviews a signed, actor-bound test selection and exact Sheet tab.
  Confirmation preserves existing imported cases and their source/provenance.
  Non-imported cases in that disclosed workspace are explicitly treated as test
  data. Other groups, shared processing envelopes and Drive files survive.
- Values below the header are backed up in private retained chunks, then cleared.
  The header and formatting survive. Writes begin immediately below the header;
  source row numbers remain provenance. Consumed CMP references remain consumed.
- Imported cases automatically reserve durable publication. The page interleaves
  commits and FIFO sync in batches of at most 50. The existing scheduled publisher
  also drains saved import rows after the app closes.
- Sticky feedback distinguishes saved cases from complete-cell Sheet readback.
  The active workbook's verified count and workspace-wide awaiting count are
  explicit. Previously saved imports can be resumed and synced without reupload.
- A lost acknowledgement keeps unverified rows pending. Complaint-ID upserts
  recover the same rows. Changed Sheet values/test records require re-review;
  earlier backup versions remain available. A completed changeover cannot clear
  the tab again. Confirmed changeover cannot be discarded halfway through.
- Table/Cards, compact controls, mobile sticky feedback, source comparison and
  the real native cookie/MFA/CSRF versus signed-Telegram boundaries are retained.

## Evidence

Real Playwright used actual Django routes and an isolated PostgreSQL database.
Only the Google boundary was simulated; browser HTTP responses were not mocked.
The journey removed three test cases, retained one earlier import, imported 61
valid rows plus one through the native browser, and read back all 63 projected
rows with consecutive ordinals from row 2. One invalid row remained blocked.

The journey also covered confirmation cancellation, saved approval/reload,
320/390 px layouts, dark appearance, an applied provider write with a lost
acknowledgement, error visibility, reload/resume and final verified counts.
Fifteen captures and a synthetic projected workbook are available locally:

- `test-results/complaints-legacy-browser/index.html`
- `test-results/complaints-legacy-browser/results.json`
- `test-results/complaints-legacy-browser/projected-complaints.xlsx`
- `test-results/complaint-projection-browser-final.log`

The 83 PostgreSQL API/regression checks additionally cover scoped cleanup, retained originals,
stale confirmation, shared-destination rejection, interrupted changeover
re-review, duplicate prevention, FIFO batch limits, readback failure and closed-page
worker recovery. Existing reset/deletion regression checks cover the shared seam.
Three separate live-server checks passed, including the two independent sync
requests that produced 62 unique, consecutive rows without an allocation collision.

No production deletion, Google write, deployment or physical-device acceptance
occurred. Closed-page delivery requires the documented scheduled publisher.
