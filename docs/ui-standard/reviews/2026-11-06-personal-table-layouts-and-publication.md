# Personal tables, retained report setup and small Sheet corrections

## Authorized scope

The user requested Deposit Pending / Awaiting Visit checkbox filters in the JBL
queue, shared report filters without losing chart setup, and account-owned table
ordering/freezing in Portal and Complaints Settings. Numbering stays first.
Frozen columns form an Excel-style left prefix and occupy at most half the
viewport; smaller screens temporarily shorten that prefix without changing the
saved preference. The user also reported small case Sheet corrections waiting
behind historical imports and repeated deferred retries.

The implementation reuses current Settings, compact disclosure, checkbox,
AG Grid and recovery patterns. No candidate tokens, permission grants, browser
activation flags or Phase 6 migration are introduced. The source ratchet records
these specific changes; approved baselines stay untouched.

## Presentation and persistence

- JBL filtering happens before pagination, including blank deposits as pending.
  Filtering never enables a financially held case's workflow action.
- Portal report filters are shared across tabs; each tab retains chart type,
  focused chart, hidden series/buckets and drill selection. A selected bucket
  absent from refreshed data yields no matching rows rather than broadening
  the selection. Explicit granularity changes reset incompatible drill keys.
- Complaint report filters retain their existing URL/session ownership. Chart
  presentation and table visibility survive refresh/tab navigation; native
  browser presentation is scoped by server continuity key and workspace.
- Layouts are account/workflow preferences in Django. Authorized catalogues
  cover Portal report presets, FarmUp and legacy review, plus Complaints reports
  and legacy review. Source-only import columns are discovered at runtime.
- Saves are revision checked. Conflicts retain edits and offer reload. Other
  preference forms preserve layouts. Layouts store no customer row values;
  table keys do not authorize data access.
- AG Grid renderers, sorting, editing, selection and row navigation retain their
  existing owners. The shared helper changes order/pinning only.

The native build admits exactly the shared first-party layout JS/CSS outside
`browser/`, hashes them in its source manifest, and verifies those hashes on
load. Other build-root and excluded asset checks remain in force.

## Publication diagnosis and behavior

The supplied logs confirm `circuit_cooldown` deferred attempts until 13:50:47
EAT; they do not disclose the original Google failure. A local reproduction
showed bad register headers classified as transient `network`, opening the
shared circuit after five attempts. The corrected failures become `sheet_schema`
requiring attention, with no provider circuit failure. Initialization permission
and configuration failures retain a safe phase and HTTP status. Google 429,
network and server failures retain their backoff and cooldown.

A real prior successful publication to the same destination allows a correction
to that existing case row ahead of unrelated inserts. Earlier revisions of the
same case still serialize. New rows retain per-destination FIFO. A missing
previously published row requires review and cannot append through the priority
path. Superseded operations do not count as publication evidence. Typed writes
are limited to changed fields; interrupted-write recovery still reasserts types.

Foreground retry waits and resumes after pacing, backoff, cooldown, FIFO or an
active lease. Stop or leaving the screen ends that loop; the queue survives.
Legacy holds and permanent errors require their own recovery. Request-assisted
publishing still requires a visible authorized Portal session; no unattended
worker or cron was introduced.

## Local evidence and limits

Evidence is ignored under `test-results/table-layout-review/`, with synthetic
customers only. Real Django/PostgreSQL, signed Telegram requests and native
company password/MFA handlers were exercised. External network calls were
denied; an in-memory Sheet transport exercised the actual publisher, schema
validation, writes and readback.

| Journey | Evidence |
| --- | --- |
| JBL checkboxes; layout save/reload; report focus/filter/tab retention; mobile half-width pinning | `portal-browser-result.json`, captures 01–04 |
| Same-account Telegram/native layouts and Complaint ID navigation | `complaints-browser-result.json`, captures 05–09 |
| Countdown resumes; small update passes inserts; same row updated without duplicate | `publication-browser-result.json`, captures 10–11 |
| FarmUp edit after reorder; Portal legacy resume/order/detail | `import-browser-result.json`, captures 12–14 |
| Complaints legacy staging and source-row detail | `complaint-import-browser-result.json`, capture 15 |
| Officer Settings access; account isolation; invalid/stale saves rejected; failed save retains draft | `preference-boundary-result.json` |
| Missing previously published row stops without appending | `missing-row-probe.log` |
| Portal chart legend selection survives filter changes, tab switching and reload | `report-legend-result.json` |

The native report journey additionally checks chosen chart type and visible
columns after a filter refresh, reload and case-detail back navigation. Five
focused publisher regression tests passed, including initialization 403/429,
non-transient register errors, pacing and same-case/destination ordering.

Commands: `node test-results/layout_browser.cjs`,
`node test-results/complaint_layout_browser.cjs`,
`node test-results/publication_update_browser.cjs`,
`node test-results/import_layout_browser.cjs`, and
`node test-results/complaint_import_layout_browser.cjs`, against loopback harness
`test-results/layout_review_server.py` and database `hb_table_layout_review`.
No production data, Google connectivity, deployment, provider recovery or
unattended completion is certified by these local checks. Supporting checks
include the native build, TypeScript, scoped lint, migration drift, source
ratchet and narrow publisher regressions; they do not replace browser evidence.
