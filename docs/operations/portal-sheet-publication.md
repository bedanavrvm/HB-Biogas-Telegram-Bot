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
For these tabs, row 1 is headers and row 2 onward is data. Each new case
appends after the last occupied row. Existing case rows are never shifted.

## Request-assisted sync (no cron)

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
