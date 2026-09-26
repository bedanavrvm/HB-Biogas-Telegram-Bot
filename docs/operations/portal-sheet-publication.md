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
If row 2 contains only the exact backend descriptions left by the old header
layout and no later cases exist, the first case replaces those descriptions in
row 2. Any other row-2 content is preserved and reported as a schema issue
rather than overwritten. Existing case rows are never shifted automatically.

## Scheduling

The browser makes an immediate best-effort publication attempt and helps drain
due work while an authorized Portal session is open. To progress work when no
staff are online, configure a scheduler to run this command **every minute**:

```sh
python manage.py drain_portal_publications --apply --limit 5 --max-seconds 50
```

Before enabling it, inspect the queue without external calls:

```sh
python manage.py drain_portal_publications
```

The command does not install a scheduler by itself. Configure a single
production scheduler invocation outside Django; overlapping invocations are
safe but waste capacity. Do not run the `--apply` form against production as
an ad hoc test unless a real Sheet write is intended.

## Timing and limits

- The first browser attempt is immediate when a Portal write returns.
- Portal publication operations are paced at least 10 seconds apart by default
  across web workers and the scheduled drainer. Override with
  `PORTAL_PUBLICATION_MIN_SPACING_SECONDS` if the spreadsheet becomes slow.
- A transient failure persists its next eligible retry time. HTTP 429 waits at
  least 60 seconds plus jitter, and honors a longer numeric `Retry-After` up
  to 10 minutes. A circuit opens for 10 minutes after repeated failures.
- Each operation has at most four attempts; an exhausted operation requires
  a reviewed manual retry. Newer case revisions supersede older publications.
- The FarmUp badge counts down to **retry eligibility**, not a guaranteed
  completion time. If there is no due time, it says `Sheet sync queued`.
- The drainer's limit bounds operation attempts, not individual Google HTTP
  requests. A single publication can read headers/rows and then write. The
  10-second default is intentionally conservative but other workflows sharing
  the service account must also be monitored in Google Cloud quotas.
- Master Data and Eco-conserve publications retain their case commit reservation
  order across browser and scheduler attempts. A later case waits while an
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
