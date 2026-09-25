# Portal Google Sheet publication

Portal changes commit to Django first. Sheet publication is a separate durable
operation. A saved case is usable even while the Sheet update is queued.

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

If work remains queued longer than expected, inspect the operation's `status`,
`attempts`, `next_retry_at`, and `last_error_code` in Django Admin. A persistent
`needs_attention` state means it has exhausted automatic retries; repeated
refreshes will not fix a bad tab name, permissions, or schema mismatch.
