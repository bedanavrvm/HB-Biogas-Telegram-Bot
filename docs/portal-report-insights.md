# Portal report insights

Reports retains its existing `portal.reports.view` access policy. The server
rechecks current grants and complete branch/product/group scopes for report
data, available filter choices, chart selections and download generation.
No role grants, persistent models or database migrations are added.

The screen retains three sections:

- **Pipeline:** current stage, cases received over time, current-stage backlog
  age and branch/county comparisons. Any Time is the default; a date filter
  selects cases by their received date, while backlog remains a current snapshot.
- **Visits & decisions:** dated visit/credit/final decisions, activity trends,
  completed-stage median/P90 turnaround and performance against recorded targets.
  Each milestone uses its own Nairobi date. Each case's currently recorded
  milestone counts once, including after corrections.
- **Orders & finance:** order/invoice case activity and invoice-value trends,
  plus current invoice, recorded payment, deposit and balance totals and
  branch/county comparisons. A case is in the period when its order or invoice
  date matches. Current payments and balances are not historical cash flow.

Outcomes and Finance default to the current month through today. All sections
support Any Time, Specific Month or Custom Range, and day/week/month/year
grouping. Week buckets start on Monday. Missing or reversed timing is excluded
from duration samples; missing targets are excluded from target comparisons.
Median and P90 use linear interpolation over valid stage-hour samples.
Timing uses the existing Portal case-TAT calculator, frozen targets and approved
deferral exclusions, including accepted HB milestones. No TAT/Complaints/SPIN
customer identity join or alternative timing formula is introduced.

Chart selection narrows Supporting cases and XLSX export; charts and summary
cards retain the filter-wide overview so other selections remain available.
Chart clicks have equivalent series/bucket selectors and a Show cases button.
Clear returns to the full filtered case list. Cases open the existing Case
History detour; returning preserves filters/page and rechecks current access.

Charts use the pinned local Chart.js 4.5.1 asset and support carousel/list views,
swipe/keyboard navigation, theme changes and permitted chart-type switches.
Only the display preference is saved locally. Failed chart assets leave tables,
selectors and exports usable. No external reporting service is called.

Existing workspace and export URLs and preset keys are retained. Additive
filters are `product`, `search`, `date_mode`, `month`, `granularity`, `chart_key`,
`bucket_key` and `series_key`. Selections must match a current server-generated
chart, bucket and series. Responses retain existing fields and add stable chart
IDs, datasets, bucket keys, units, context, sample counts and table record IDs.
Old `from`/`to` filters remain accepted as custom ranges.

Graphs cover the full authorized cohort. Tables use the existing 50-row pages
and 2,000-case limit; exports have the same 2,000-case cap and disclose matching
counts, limits and applied filters. Financial calculations remain Decimal;
chart plotting converts values only in the browser. Exported text remains text,
including values starting with `=`.

Timing fetches pipeline events, relevant HB events and configuration in batches,
with one holiday-calendar read per report rather than per case. Added optional
inputs to the existing calculator preserve its ordinary single-case behavior.

Deployment requires normal code/static-asset publication only. No schema or
environment changes and no Telegram, Google Sheets or Drive publication are
required. To roll back, restore the prior curated report service/UI and static
asset versions together.

## Verification

Focused verification covers 29 reporting/insight/existing case-timing tests in
isolated SQLite with external connections blocked and 17 Playwright browser
tests using synthetic responses and the actual local Chart.js asset. Browser
checks cover 320/390/430/1280px widths, light/dark charts, display/type controls,
keyboard/modal handling, filter cancellation, drill/export parity, stale
responses, missing assets, empty results and retained Case History return.
Synthetic screenshots were visually reviewed. Python correctness lint,
first-party JavaScript syntax, Django system checks and migration consistency
are also checked. No real Telegram WebView, production PostgreSQL or live
external integration is exercised; existing repository-wide gate failures
remain documented in `KNOWN_GAPS.md`.
