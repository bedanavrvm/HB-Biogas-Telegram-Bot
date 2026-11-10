# Portal Google Sheet publication

Portal changes commit to Django first. Sheet publication is a separate durable
operation. A saved case is usable even while the Sheet update is queued.

Both `Master Data` and `Eco-conserve` must have their column headers in row 1
and their first case in row 2. Set the Jawabu group configuration's Master
header row to `1` and data start row to `2` after confirming the tabs have
that layout. Publication detects valid row-1 headers in each tab and uses row 2
even when an old group configuration still says `3`/`5`. Tabs whose headers
remain in the old position retain that configured layout; this release does
not move live spreadsheet rows automatically. Do not change the two settings
until the actual Sheet headers have been moved to row 1.
If historical `No.` values are already inconsistent,
run the dedicated number-repair command once after checking its dry-run plan;
ordinary case publication no longer rescans the entire tab to repair history.
For these tabs, row 1 is headers and row 2 onward is data. A new case uses the
first entirely empty data row, including a gap left by deletion. A header-only
tab starts at row 2. A row containing any value or formula is occupied, even
when its customer name is blank. Existing identified cases update in place;
rows are never automatically moved or compacted.

## Compact current pipeline status

`Current Pipeline State` remains the existing backend-owned column in both
registers. It publishes only these twelve labels (in uppercase, as other
short Sheet labels do). No extra status column or dropdown is added. The
catalogue is `core.services.portal_sheet_status.PortalSheetStatus`.

Credit Decision and the structured HB installation, readiness, installation-report
and commissioning labels follow the same uppercase convention in both initial
legacy projection and later case publication. Comments, retained source values
and Mini App labels keep their original case. Committed initial-import credit
history publishes LEGACY until native Portal visit/credit activity or a recorded
credit actor/date takes precedence. A release-time repair must examine every
imported case's existing Sheet credit cell, including blank historical decisions;
selecting only cases with a nonblank stored verdict misses older PENDING cells.
Correct those labels by immutable Master Record ID without rewriting workflow
decisions or replaying whole-row publication.

| Status | Meaning |
| --- | --- |
| Awaiting JBL Visit | Waiting for the JBL visit after meeting the deposit requirement. |
| Pending Minimum Deposit | Before the JBL visit, the recorded HB deposit is below KES 5,000 or unknown. |
| Under Review | Credit analysis or Head of Rural review is outstanding. Credit approval alone stays here. |
| Deferred | Temporarily held or rescheduled; stage, reason and reappraisal timing are in the Mini App. |
| Rejected | A current or explicit historical rejection, without inventing an unknown rejection stage. |
| Cancelled/Withdrawn | A cancellation, withdrawal or closed installation; the exact reason remains in the Mini App. |
| Opted for Other | The customer chose cash or another partner; the chosen route remains in the Mini App. |
| Approved — Order Processing | Final approval is established and the case is awaiting its order number. |
| Installation in Progress | An order number has been issued; the case is in the installation phase, including waiting for installation to begin. |
| Installed — Awaiting Commissioning | Installation is recorded complete and commissioning remains outstanding. |
| Commissioned | Current or explicit historical commissioning is recorded complete. |
| Legacy | Retained facts do not establish a consistent current position. |

Initial legacy loading and later publication use the same status mapping.
Known reported outcomes remain visible even when the historical decision
stage is unknown. Date warnings stay in the Mini App and do not hide otherwise
explicit installation/commissioning facts. Conflicting outcomes and fulfilment,
or conflicting linked sources, still display Legacy.

An unqualified historical Approved without a decision stage or order number
stays Legacy until reviewed continuation establishes its meaning. The business
accepts a recorded legacy order number as evidence that the case was approved
and order processing has finished. It displays Installation in Progress until
installation or commissioning completion is known. Approved — Order Processing
is reserved for approved cases still awaiting an order number.
HB handover and signed-order evidence remain separate. None of these labels creates an
approval event, HB action, actor, decision date or workflow transition. Minimum
deposit checks apply only to the pre-visit stage; they never move installed or
commissioned cases backwards. Unknown historical credit continues to use its
separate Legacy credit marker; these twelve values are the overall status.

The Mini App retains its detailed stage labels, comments and review warnings.
Existing Sheet rows adopt the compact label through publication; deploying
code alone does not rewrite all rows. A separately approved refresh must write
only the existing Current Pipeline State cells, match immutable Master Record
IDs, preserve other fields/formulas and initial-import checkpoints, and verify
the resulting labels by readback. Do not rerun business actions or finish
outstanding imports to refresh this display.

Visible **Case ID** is the Portal's readable `JBL-…` reference. The immutable
UUID belongs in hidden **Master Record ID**, which remains the ownership key
for updates, retries and reset deletion. Legacy imports follow this same split;
their original **Source Row** is historical provenance, not a destination address.

## Request-assisted sync (no cron)

An unfinished legacy changeover deliberately holds normal publication. The
visible-session pump reports a successful **paused** response rather than an
unexpected 503; it does not bypass the hold. Open the saved **Legacy import**
and follow its Sheet status: saved cases sync automatically in FIFO order;
**Sync imported rows to Sheet** or **Resume processing** retries unfinished work.
The synced counter advances only when rows are verified by readback. The owner
is released only when the changeover completes. See the
[legacy importer guide](../runbooks/portal-legacy-importer.md).

While an authorized Portal screen is visible, its shared background request
advances one eligible Sheet update at a time. This covers FarmUp and later
Portal case changes, including both Master Data and Eco-conserve. Users can
leave the worklist and continue using Portal; saving and navigation do not wait
for Google. The server owns FIFO order, pacing, backoff, leases, and retries.
Overlapping browser tabs cannot publish the same operation twice. If every
Portal session closes, queued work remains durable in Django and resumes when
someone next opens Portal. There is no cron job or unattended scheduler.

The supplied `start.sh` permits a bounded Google attempt up to 120 seconds
and keeps a second web thread available. Confirm the deployed service uses it.

Previously published case corrections can advance ahead of unrelated new-case
imports. The publisher requires evidence of a real successful write to the same
destination, preserves order between revisions of that case, and only updates
an existing row. A missing row stops for review rather than being appended.
New rows still use destination FIFO.

Explicit retry displays a countdown and resumes after pacing, provider backoff,
cooldown, FIFO or an active worker. Stop or leaving the screen ends the page's
loop without removing queued work. Bad headers, missing published rows and
configuration/permission failures need review; they no longer masquerade as
transient Google outages. Recovery shows the safe failure category and HTTP
status when available. A cooldown entry alone does not identify the original
provider failure.

For diagnosis, inspect the queue without external calls:

```sh
python manage.py drain_portal_publications
```

The command is a manual recovery tool only. Its `--apply` form writes to the
real Sheet; use it only when explicitly intended. When queued work has no
recent attempt, Operations/IT see an inactivity warning directing them to
open Portal. A failed update can be requeued from the authorized worklist or
case; opening Portal alone cannot repair a permanent configuration error.

## Timing and limits

- The first attempt is eligible while any Portal screen remains visible,
  usually within a few seconds. This is an estimate; pacing, queue depth,
  backoff, and Google availability can extend it.
- Portal publication operations are paced at least 5 seconds apart by default
  across visible Portal sessions. A normal new-row publication uses one RAW
  row write, one combined USER_ENTERED date/money batch, and one combined
  formatting batch. At the 10-attempt ceiling this is about 30 writes and up
  to 33 reads per minute for one Master/Eco tab, before other workflows and
  retries. Override `PORTAL_PUBLICATION_MIN_SPACING_SECONDS` if the shared
  Google account needs more quota headroom.
- A transient failure persists its next eligible retry time. HTTP 429 waits at
  least 60 seconds plus jitter, and honors a longer numeric `Retry-After` up
  to 10 minutes. A circuit opens for 10 minutes after repeated failures.
- Each operation has at most four attempts; an exhausted operation requires
  a reviewed manual retry. Newer case revisions supersede older publications.
- The FarmUp badge counts down to **retry eligibility**, not a guaranteed
  completion time. Status refreshes as background attempts finish and on Refresh.
  If there is no due time, it says `Sheet sync queued`.
- The manual drainer's limit bounds operation attempts, not individual Google HTTP
  requests. A single publication can read headers/rows and then write. The
  5-second default leaves quota headroom under Google's published per-user
  limits, but other workflows sharing the service account must also be
  monitored in Google Cloud quotas.
- Master Data and Eco-conserve publications retain their case commit reservation
  order across all attempts. A later case waits while an
  earlier one is retrying; a failed case can therefore delay the queue until
  it succeeds or reaches its retry limit. Internal Order publication is paced
  separately and does not determine case row order.
- A new case receives its next `No.` during its own append. Full-tab number
  repairs are reserved for explicit repair work or a partner-tab move, avoiding
  an extra full Sheet read after every monthly-upload case.

If work remains queued longer than expected, inspect the operation's `status`,
`attempts`, `next_retry_at`, and `last_error_code` in Django Admin. A persistent
`needs_attention` state means it has exhausted automatic retries; repeated
refreshes will not fix a bad tab name, permissions, or schema mismatch.
Open any Portal screen to resume pending work and confirm the
**Sheet synced** badge in FarmUp. Manual **Retry failed sync** creates a reviewed queued
replacement for an exhausted operation and returns without contacting Google.

## Legacy imported-case FIFO

Legacy cutover now publishes each saved chunk automatically through its own
register-bound, leased importer queue, ordered by commit time. Selecting a saved
upload resumes earlier unsynced cases. Bounded provider batches have retained
target/checksum plans and readback receipts; unknown acknowledgements retry the
same rows. Unimported source rows are preserved. This path does not enable the
normal publisher during the cutover hold or add a background worker. Keep the
legacy page visible, or resume it after closing.

A global `portal_read_only_maintenance` 503 after a failed Admin reset is a
separate operator maintenance lock. Fix/retry the reset and review maintenance
state before attempting writes. Do not clear it automatically to force sync.
