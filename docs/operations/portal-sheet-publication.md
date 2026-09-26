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

## FarmUp operator-driven sync

FarmUp can advance its queued Master Data and Internal Order Sheet publications while an authorized
operator keeps its screen open and visible. The screen submits one operation at
a time, waits at least five seconds between requests, refreshes status, and
stops when the worklist is synced or needs attention. The server still owns
FIFO order, pacing, backoff, leases, and retries. Saving the FarmUp worklist
never waits for Google. If the operator closes the screen, pending work stays
in Django and resumes when FarmUp opens again. The operator must check for
**Sheet synced** before leaving if no independent scheduler is configured.
The supplied `start.sh` allows a bounded Google attempt up to 120 seconds and
keeps a second web thread available. Confirm the deployed web service uses
that start command before relying on operator-driven attempts.

This covers publications linked to FarmUp cases. Other Portal Sheet publications,
including unrelated later case changes, still need an independent
runner if they must finish without a FarmUp session. A production scheduler is
optional for FarmUp but recommended for all-workflow unattended publication.
Configure schedule `* * * * *` to run:

```sh
python manage.py drain_portal_publications --apply --limit 10 --max-seconds 50
```

Before enabling it, inspect the queue without external calls:

```sh
python manage.py drain_portal_publications
```

The command does not install a scheduler by itself. If one is provisioned,
confirm its first successful run and monitor it. Runs record a privacy-safe heartbeat
in `DurableJobRunnerHeartbeat` under `portal_sheet_publications`. When queued
work exists with neither a recent runner heartbeat nor a recent Sheet attempt,
the Portal Operations/IT dashboard shows an inactivity warning. Overlapping
runs and FarmUp requests use the database operation lease and pacing.
Do not run the `--apply` form against production as an ad hoc test unless a
real Sheet write is intended.

## Timing and limits

- The first FarmUp attempt is eligible while its screen remains visible,
  usually within a few seconds. This is an estimate; pacing, queue depth,
  backoff, and Google availability can extend it.
- Portal publication operations are paced at least 5 seconds apart by default
  across FarmUp requests and overlapping scheduled runs. A normal new-row publication uses one RAW
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
  completion time. Status refreshes when FarmUp opens or staff tap Refresh.
  If there is no due time, it says `Sheet sync queued`.
- The drainer's limit bounds operation attempts, not individual Google HTTP
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
If no scheduler runs, reopen FarmUp to resume its pending work and confirm the
**Sheet synced** badge. Manual **Retry sync** creates a reviewed queued
replacement for an exhausted operation and returns without contacting Google.
