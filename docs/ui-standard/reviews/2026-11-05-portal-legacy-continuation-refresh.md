# Legacy continuation refresh

User-reported issue: a successful continuation displayed "Saved. Refresh this
case to continue in its owning workflow." while retaining the obsolete form.
The save endpoint already committed correctly; the client had no success handoff.

## Source and behaviour

- `portal_legacy.js` retains the request key and records successful saving before
  invoking the caller's completion action. While updating, it displays a short
  saved/loading status and disables already-confirmed inputs.
- In `portal_farmer_sheet.js`, the case page fetches current authorized details
  and renders them in place. The obsolete confirmation controls disappear and
  the updated stage/actions become available without a document reload. Queue
  and dashboard counts refresh using existing loaders.
- The queue drawer opens the same case's current detail page through existing
  Portal navigation, preserving the source queue in the return URL.
- If saving succeeds but fetching updated details fails, the form explicitly
  says the confirmation is retained and offers **Retry loading case**. This path
  retries only the read, never a second confirmation POST. An unsuccessful save
  retains the entered values and original request key for its retry.
- A case page left during loading is not overwritten by an older result. Existing
  roles, revision validation, audit events, workflow/deposit gates and publication
  reservation remain owned by the server. No schema or permission changes.
- Existing compact disclosures, feedback and navigation are reused. See the
  [case-notice design record](2026-11-05-portal-compact-case-notices.md). Asset cache
  versions bind the changed scripts; no new styling or dependencies.

## Verification boundary

Source-bound Playwright uses signed Telegram authentication, real Django pages
and dedicated local PostgreSQL with synthetic imports. External provider traffic
is denied. Journey evidence is retained in the
[screenshot gallery](../../../test-results/continuation-refresh-browser/index.html).

All four journeys passed: in-place case refresh, queue drawer handoff, an
interrupted save with its input/request key retained, and a committed save whose
follow-up read fails before succeeding on retry. The latter sends only one
confirmation POST. Each journey's database readback confirms exactly one
stage-confirmation event and one workflow-revision increment. Case-page success
does not reload the document, and no page script errors were recorded.

No production deployment or live provider write was performed. Approved UI
baselines and the Phase 6 migration hold remain unchanged.
