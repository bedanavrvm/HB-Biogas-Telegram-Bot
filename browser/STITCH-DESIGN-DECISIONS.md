# Complaints Stitch design decisions

Decision date: 28 October 2026. Supplied HTML/CSS and screenshots govern browser
appearance, including interactive states hidden in a resting screenshot. ADS
components may supply behavior; ADS styling does not override these references.
This record applies to the Complaints browser. Telegram adoption is a follow-up.

## Reference inventory

| Reference under `Stitch/` | Design contribution | Decision |
| --- | --- | --- |
| `Create Complaint/` | Customer detail, lavender insets, green resolution, staff notes, evidence, map and expanded dialogs | Retain the approved single-column composition and working interactions. |
| `enterprise_service_system/DESIGN.md` | Typography, semantic colors, density, elevation, field grids, buttons and overlays | Use the supplied tokens and images first. Its gray-surface/split-pane prose is an alternative, not a new baseline. |
| `interactive_dialogs_error_feedback_ads/` | Missing-details form, validation, selected categories, recoverable errors, restricted reports and cascading locations | Adopt using actual validation, catalogues, authority and location hierarchy. |
| `loading_skeletons_interaction_states/` | Skeletons, loading/loaded transitions, focus/required states, upload progress, empty/restricted states | Adopt real asynchronous states and measured upload percentages. Showcase tabs and sample workflows remain reference-only. |
| `toasts_menus_activity_drawer_ads/` | Dismissible feedback, menus, clipboard confirmation, sorting, SLA help, timeline and drawer | Adopt feedback/menu/SLA/sort patterns. Retain Conversation/History tabs; record the drawer without mounting it. |

Each HTML and accompanying PNG was inspected. Playwright inspection also opened
the hidden form/restricted tabs, status menu, action menu, history drawer and
older activity, and exercised the cascading location selector. The export uses
mock timers and static data; production interactions must use actual outcomes.

## Visual choices

- Canvas `#FAF9FF`, white cards, lavender insets `#F1F3FF`, body `#051A3E`.
- Blue `#004FB6` links/focus and `#0C66E4` primary form actions; green `#006C47`
  for resolution; semantic amber/red for warnings and failures.
- Inter body 14/20, small body 12/16, heading 22/28, tracked 11/14 field labels.
- Compact 4/8/12/16px spacing, 12px card padding, modest radii and hairline borders.
- One vertical case stack at all widths. Preserve dark-mode contrast, keyboard
  focus, enlarged-text scrolling and reduced motion. No CDN runtime is added.

## Behavior and backend decisions

| Pattern | Existing support | Approved adoption |
| --- | --- | --- |
| Skeletons and saving states | Native reads and idempotent task state | Initial-load skeletons; retained content on refresh; actual busy/error/success states. |
| Missing details and classification | Revision-checked completion, real category catalogue | Restyle without changing required fields or introducing sample category codes. |
| Identity validation | Kenyan mobile normalization and digits-only National ID | Retain current rules; no passport claim, fixed eight-digit limit, IPRS claim or 07-only restriction. |
| Locations/GPS | Dependent locations and intake GPS | Capture at creation only; saved detail location remains read-only. Display actual accuracy only when available. |
| Evidence | Signature validation; 10 files, 10 MB each, 30 MB total | Keep limits, support picker/camera/drop selection, per-file measured progress and independent outcomes. |
| Clipboard and menus | Native clipboard, scoped case actions | Confirm successful copying; retain fallback errors and current action authority. |
| History | Paginated audit API and draft-preserving tabs | Keep current tabs. Drawer and recent-preview composition are documented alternatives. |
| SLA | Canonical target/start/deadline and calendar-time timing service | Add authorized read projection, countdown/outcome/help; preserve existing deadlines on reopen. |
| Queue sorting | Oldest/newest only | Add whole-queue Highest priority and Overdue first, including stable pagination and previous/next navigation. |
| Assignment | Legacy database fields, no browser action | Excluded by user. |
| Status palette | Open/Reopened/Closed; historical Needs details condition | Keep current workflow; no In Review/In Progress or separate Resolved state. |
| Deletion | Separate governed Admin testing deletion | No operational browser delete action. |
| Permission request/notification bell | No matching Complaint browser workflow/feed | Record only; do not mount inactive controls or imply a request was sent. |
| Print/audit export | Existing report Excel export | Keep existing exports; no new case print/audit export. |
| Diagnostic notes/replacement serial | No corresponding workflow requirement | No new technician fields. |

## Publication contract

Browser saves succeed after Django commits the canonical record, validated
evidence bytes and durable jobs. Drive and Sheet publication continue after the
page closes. Each file has one 0–100% percentage with an honest stage label:
receipt contributes 0–50%, acknowledged Drive transfer 50–99%, and confirmed
publication reaches 100%. No timer invents progress and no Drive credentials or
resumable session URL enters the browser.

Transient failures use bounded exponential backoff/jitter and `Retry-After`,
with eight attempts and a one-hour delay cap. Permanent/exhausted failures go to
Complaints IT through persistent workspace/Admin Needs attention views, without
outbound alerts or a new notification centre. Manual retry preserves the failed
attempt history. Canonical saves and successful files survive other failures.

Temporary file bytes expire **24 hours after verified publication**. Unpublished
bytes remain until IT resolves the failure. Uncommitted abandoned upload attempts
expire after 24 hours. Metadata and audit receipts follow their owning records.

Telegram intake/updates retain their current publication behavior. A future
follow-up should consider adopting this contract across the Complaint workflow;
this browser change does not authorize that migration or activate production.

## Acceptance evidence

The user's subsequent UI-only instruction supersedes the automated acceptance
workflow below for ongoing appearance fixes: use direct browser interaction and
screenshots, with no test suites, assertion scripts or new test files. Build only
as needed to display the UI. Iterate from visual review and user feedback.
Historical checks below describe the earlier publication implementation.

Verify through Playwright against native Django authentication and disposable
PostgreSQL: both themes, phone/desktop sizes, zoom, hidden/expanded states,
validation, drafts, allowed/denied roles, SLA boundaries and sorting across pages.
For publication, cover measured progress, leaving after commit, worker restart,
duplicate and uncertain retries, partial failures, escalation and 24-hour cleanup.
Retain source/build/screenshot hashes and a gallery in the linked review record.
Build/type/migration/source-ratchet checks supplement browser evidence; screenshots
and mocked providers do not establish deployment or live-provider commissioning.

## Detail corrections after visual feedback

- HB Feedback is a visible authorized action. The overflow menu stays at the far
  right; phone layouts wrap the actions rather than hiding feedback.
- Each metadata label/value pair gets its own light-grey inset card. The map is
  taller and its external pin link is an outlined footer action. Conversation
  and History divide their row equally with centred labels.
- Conversation cards wrap names, dates, content, quotes, files and actions.
  Replies preserve their exact selected parent, including the author's own
  replies. Shallow indentation and parent excerpts keep long chains readable.
  Historical flattened replies are retained as recorded.
- Notifications stay at the top of the viewport below the app header, including
  over a dialog. Warning confirmations open near the top. Copy success is a
  two-second tooltip attached to the clicked control.
- Internal notes/replies save only to the conversation. Their attachment progress
  appears on the corresponding message. HB Feedback remains an official register
  update, along with creation/corrections/resolution/reopen. Register jobs have a
  compact status by the operational toolbar; no generic publication panel or
  publisher-health warning appears when replying. Health diagnostics stay with IT.

Visual review: [detail corrections](../docs/ui-standard/reviews/2026-10-28-complaints-ui-corrections.md).
