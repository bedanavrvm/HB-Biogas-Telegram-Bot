# Complaints browser workflow corrections, 28 October 2026

The user authorized the seven corrections identified in the repository audit,
with incremental Playwright verification. This is a source-bound browser
correction under ADRs 0073 and 0075. It does not approve a new visual baseline,
enable browser release flags, deploy a service or migrate a Telegram Mini App.

## Delivered behavior and browser evidence

Evidence is local under `test-results/complaints-port-fix/`. Files prefixed
`production-` exercise the final `dist-production` artifact, the real production
entry/assets/CSP and native API routes on an isolated loopback Django host.
Earlier unprefixed captures are intermediate review evidence.

| Audit finding | Corrected behavior | Playwright observation |
| --- | --- | --- |
| Historical completion cannot supply a required category | Complete missing details includes the current available categories and submits the selected category with the existing identifiers/revision/request key. | Required-field feedback appears before selection; choosing a category and saving returns HTTP 200 and moves the historical case to Open. `production-legacy-category-ready.png` |
| Location request failure is swallowed | Current parent selections bind location results. Loading/failure clears stale dependent choices, disables unavailable dependent inputs and submission, and exposes Retry. Entries remain intact. | A deliberately injected location HTTP 503 shows the failure and Retry. Retrying real catalogue reads retains the customer name; county/constituency selection and actual complaint creation succeed with HTTP 201. `production-location-failure-retry.png`, `production-created-after-location-retry.png` |
| Saved contact/location information is omitted | Operational details and read-only report details reuse the same contact/address presentation. Alternate phone and map links are available; map links accept only HTTP(S). | Saved alternate phone, county, constituency and landmark appear. The map has the saved URL. A legacy JavaScript map reference creates no link. `production-contact-and-location.png` |
| Activity omits recorded changes | The activity projection retains typed `display_changes` and renders recorded before/after values and human catalogue labels. Missing earlier values remain distinct from recorded blanks; redundant resolution text/empty initial fields are omitted. | The actual completion response and visible activity show the changed status, phone and category. `production-recorded-changes.png` |
| Queue omits HB feedback count | Rows display the existing total HB comment count, with an accessible label. It is not an unread counter. | The synthetic contact row displays its one saved HB comment. HB feedback also saves through the normal action dialog. `production-details-light-1366.png` |
| Laptop navigation disappears and desktop width is capped too tightly | Queue/detail split starts at the existing 64rem breakpoint; the work area grows to 120rem. Narrow layouts retain the one-pane Back journey. Facts reflow at enlarged text sizes. | Light/dark captures at 320, 390, 768, 1024, 1280, 1366, 1440 and 1920 CSS pixels. Queue remains visible at 1024 and wider; content width reaches 1920. Enlarged-text inspection is retained in `production-details-enlarged-text.png`. |
| Global report references lead nowhere | Authorized report rows outside the current operational workspace open a read-only detail with paged history. A bounded UUID in `report_case` restores the dialog on reload. The canonical table retains its existing fields; `report_links` carries navigation metadata. | Desktop and mobile reference opening work, reload restores the selected report, and all 65 synthetic notes load across three pages. `production-global-report-desktop.png`, `production-global-report-all-history.png`, `production-global-report-mobile-reload.png` |

Representative laptop/mobile, light/dark, location-error, recorded-change and
report-detail screenshots were visually inspected. Viewport fit supports this
review; it is not a substitute for the completed task journeys above.

## Authorization and data boundaries

The report detail/history endpoints require the existing current
`complaint.reports.view` capability and native browser assurance. Their records
come from the canonical Complaint register, and history reuses the existing
bounded case-bound cursor implementation. They expose no case actions, evidence
downloads, raw messages or private storage identifiers. Operational links and
writes retain their owning-workspace checks.

The report dialog also retained keyboard focus during Tab navigation; Escape
closed it, removed the report selection from the URL, and returned focus to the
reference button that opened it.

Playwright exercised the same synthetic admitted account with disposable
Complaints grants for Officer, HB staff, Manager, IT and no access. Officer
report reads/history were denied; the report deep link explains the missing
permission. HB note/resolution and Manager reopen completed through their actual
dialogs. Foreign-workspace writes, revoked workflow reads, anonymous report
reads, missing CSRF, unregistered records and tampered/wrong-case history cursors
were rejected. The foreign complaint remained Open. These are workflow-boundary
checks, not an independent-worker/concurrency acceptance claim.

## Verification and artifacts

- Playwright used native company password/recovery-code sign-in, real Django
  actions and isolated synthetic SQLite records. No successful workflow response
  was replaced by a browser mock. Only the intentional location failure was
  injected; geolocation used a browser-supplied sample position.
- Final production browser journeys and observations are in `journeys.jsonl`;
  `production-binding.json` binds the reviewed source/production manifests and
  captures. The browser reported no JavaScript runtime errors in these journeys.
- Node 22 TypeScript, ADS/styling lint, both native operations/production builds,
  dependency/archive/notice guards, Python Ruff/compilation, workspace navigation,
  architecture boundaries and the 206-route Mini App inventory passed.
- The existing 40 Complaint browser API/read checks passed unchanged. No unit
  tests or test assertions were added or edited to establish these fixes.

No dependency, schema migration, deployment configuration or production grant
was added. Release flags remain default-off. Sheets/Drive/email/Telegram provider
writes were blocked; the fixture uses a dedicated disposable database.

## Design references and limits

Applied official references are recorded in `browser/DESIGN.md`. The existing
ADS controls, tokens, native TaskDialog composition and AG Grid remain the
implementation patterns; no new palette, type scale or component package is
introduced. The source ratchet records this candidate without changing approved
baselines or the Phase 6 hold.

Production deployment, PostgreSQL execution for this correction, physical
devices, screen readers and real GPS/dialer/provider behavior were not verified.
Existing release commissioning gates still apply. Rollback restores the prior
browser/API code and rebuilds its immutable artifact; no data reversal or grant
change is required.
