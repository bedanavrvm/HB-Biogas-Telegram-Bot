# Complaints: Stitch component adoption and durable publication

28 October 2026. User-authorized browser implementation following review of the
new Stitch folders. Supplied HTML/CSS and images govern appearance; ADS styling
is optional. This does not approve a Telegram migration, replace screenshot
baselines or activate browser release flags.

## Design and scope

The [design decision record](../../../browser/STITCH-DESIGN-DECISIONS.md) inventories
all supplied sources and records the approved adoption/exclusion decisions.
Playwright inspected the exports' hidden tabs, error/restricted forms, category
and status menus, cascading locations, activity drawer and older activity.
The original single-column lavender case layout remains at desktop widths.
Conversation and History remain tabs. Technician assignment, new statuses,
operational deletion, permission requests, a notification centre, new case
exports and diagnostic fields are excluded. Existing identity/category/file
validation remains authoritative. GPS capture is creation-only.

Adopted behavior includes real loading skeletons with reduced-motion support,
retained data during refresh, filtered empty states, recoverable errors,
clipboard success/failure, dropdown menus, file selection/removal and drag/drop.
Semantic feedback and portal toasts use the supplied palette in both themes.
SLA uses retained calendar-time deadlines and server-anchored elapsed time,
explicit unavailable/late/on-time states and explanatory help. Reopening keeps
the original deadline. Highest priority and Overdue first sort the entire
authorized queue, with stable paging and previous/next navigation; Overdue first
does not filter out other complaints.

## Canonical save and background publication

Native browser file uploads reserve a command/owner/request-key-bound manifest,
receive bounded raw bytes and verify SHA-256 and the existing signature rules.
One transaction binds those bytes to canonical evidence, the authorized action
and durable integration jobs. A confirmed browser save needs no further browser
request to publish. Exact retries retain the same case/evidence identities.
No credential, private Drive URL or file bytes enter browser storage or Admin.

Each file shows a single measured end-to-end percentage: incoming bytes 0–49%,
validated Django receipt 50%, acknowledged Drive transfer 50–99%, and verified
publication 100%. An independent fenced worker resumes uploads, reconciles
uncertain acceptance, respects retry delays and escalates permanent/exhausted
jobs to scoped Complaints IT. Successful files and canonical history survive
other failures. IT retry creates an audited successor; failure history remains.
Workspace and Admin attention views clear recovered failures. No outbound alert
is sent. Worker setup, retention and rollback:
[publication runbook](../../runbooks/complaints-browser-publications.md).

The bounded `complaint_publications` app owns temporary bytes and receipts. It
declares table/column comments, retention, reverse names and index reasons;
checked-in migrations and the generated database catalogue describe it. A
populated migration reversal is refused. Telegram retains its existing
publication path; workflow-wide adoption remains a separate follow-up.

## Playwright evidence

Open the [screenshot gallery](../../../test-results/complaints-stitch-components/index.html).
It contains 101 captures, including the 62-image final matrix; other captures
retain incremental state/recovery evidence and may precede final backend edits.
The same folder contains `journeys.jsonl`, exact source/build/screenshot hashes
in `evidence-manifest.json`, worker logs and the disposable review harness.
These are local, ignored review artifacts. The `final/` matrix contains 62
captures of detail, queue, creation, metadata, publication, composer, History,
resolution dialogs and dropzones: light/dark, 320/390/454/768/1440/1920 pixels
and 200% zoom. Additional captures show SLA boundaries, failure/retry, incoming
and outgoing measured progress, cleanup and interaction states.

Journeys use the actual production artifact/routes, password plus recovery MFA,
CSRF, current owning-workflow permissions, native PostgreSQL security state and
a disposable PostgreSQL database. All people, records, grants, files and
provider responses are synthetic. The shared Drive uploader/resumable loop and
independent management-command workers execute; only provider transport/storage
and map tiles are substituted. Map tiles are visibly labelled synthetic.

Verified journeys include:

- Four whole-queue sorts across more than 30 records/four pages, stable neighbors
  and persisted navigation; SLA overdue, approaching, unavailable and closed
  on-time/late states with help.
- Required creation fields, dependent locations, creation GPS, canonical save
  before publication and concurrent exact creation replays returning one case.
- Incoming network-throttled percentages; acknowledged Drive progress; partial
  multi-file failure; publication after closing the originating browser context;
  interrupted worker/resume; uncertain remote acceptance without a second object.
- Transient retry/backoff, permanent failure, the eighth-attempt boundary,
  Complaints IT recovery, Manager/Portal/foreign-workspace denial, independent
  Sheet failure and removal of recovered attention entries.
- Cleanup before/after the 24-hour boundary: successful bytes/URLs removed,
  unpublished originals intact, abandoned staging expired, published receipts
  still at 100%; populated rollback refused and forward migrations restored.
- Clipboard success and denial, empty search/reset, reduced-motion skeletons,
  invalid drop selection, removal, dialog Escape, History draft retention,
  reply/reaction/permalink and exact-request collision handling.
- Native Admin attention/retry and read-only metadata, with Manager denial and
  raw bytes/private resumable URLs/delete actions excluded; offline/password-MFA
  draft recovery and uncertain-save replay without another comment.
- A Google-style rate-limit 403 with a 20-minute `Retry-After`, followed by an
  authorized retry using the retained original bytes.
- Native upload receipt rejects missing CSRF, changed manifests, mismatched
  bytes and Portal-only access; exact reservation replay retains one receipt
  and progress responses exclude private fields.

Checks found and repaired a nullable-join PostgreSQL lock, an incorrect case
identity passed to authorization, obsolete lint suppressions, the ledger retry
status mismatch and stale attention entries after recovery. Failures discovered
in the synthetic harness were corrected before the corresponding final journey
was counted. Retry clocks/attempt counters and cleanup time are advanced only
in the disposable fixture; the evidence does not claim real elapsed-day testing.

## Verification limits

Full browser lint, TypeScript, production/closed-operations builds, Django
system/migration checks, database catalogue consistency, UI source ratchet and
`git diff --check` pass. Both native build manifests match current sources,
vendor assets and output bytes. These checks supplement Playwright.
No new unit-test files or approved-baseline updates were added.
Source ratchet entries describe reviewed candidates/nonvisual changes only.

No deployment, production migration, worker schedule commissioning, real
Drive/Sheet/email writes, physical-device or screen-reader acceptance occurred.
Live Google credentials, real resumable-session behavior, quota headers and
network infrastructure still require deployment acceptance. The legacy Sheet
adapter may report only a boolean failure; these use bounded generic retries.
Existing browser release/admission gates and all Telegram workflow authority
remain unchanged.
