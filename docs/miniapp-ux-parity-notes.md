# Mini App UX Parity Notes

## Purpose

This note records the mobile and operational UX patterns proven in Loan Origination and TAT Tracker, and how they apply to Complaint Case Management. It is a presentation and interaction guide; workflow authorization, state transitions, audit rules, and external integrations remain owned by each workflow.

## Shared form contract — 8 October 2026

- Open and type without premature error messages. Validate the visible,
  enabled requirements on submission; hidden and disabled controls must not
  block an unrelated action.
- Use `MiniAppUtils.bindAccessibleForm(container, options)` for inline errors,
  a keyboard-focusable summary and links to fields. Preserve existing helper
  `aria-describedby` values. Revalidate only previously flagged fields while
  correcting; do not reveal new errors for untouched fields.
- Use `installAccessibleForms()` once per app for dynamically mounted forms.
  Non-form workspaces such as Portal's visit sheet and Origination's editor
  bind explicitly after rendering. Dispose controllers before replacing an
  editor's fields. Supply `resolveField` for domain/repeating-row error keys.
- Visible labels, red required markers, text-based errors, visible keyboard
  focus, 16px editable input text and 44px field targets share `base.css`.
  Do not disable copy/paste or replace a visible label with a placeholder.
- Supported Kenyan phone formats normalize after leaving a phone field.
  Invalid values remain intact for correction; ID fields are never reformatted.
- Retain input and selected attachments after a failed action. After canonical
  complaint creation, retry evidence/publication for that same complaint;
  never create a second complaint or clear a newer form's selected files.
- Creation drafts are private, seven-day, field-only and revision-checked.
  Offer Restore / Discard. Never persist files, signing material or authentication
  secrets. A failed draft save is not a claim that workflow data was submitted.

| Surface | Integration |
|---|---|
| Complaints | Create, complete legacy details, HB comment, resolve/reopen, filters and email settings; ID/phone/location checks and complaint-reference confirmation |
| TAT | Create, dynamic stage/assessment forms, settings and filters; product amount checks and field-only recovery |
| Portal | Shared forms/dialogs, JBL visit field summaries and HB action date errors; existing workflow draft/permission rules retained |
| Origination | Editor, repeated-row error targeting, cross-section error links and signer/OTP validation; existing encrypted recovery and signature gates retained |

Verification commands:

```powershell
npm run check:js
npm run test:node
npx playwright test core/tests_browser/miniapp_forms.spec.js
.\.venv\Scripts\python.exe manage.py test core.tests_miniapp_drafts --noinput
```

The tests use synthetic data. Screenshots cover 320–430px mobile, 768px and
1280px; real Telegram keyboard/voice/camera and assistive-technology testing
remain explicit release checks, not claims of complete WCAG certification.

## Proven patterns across workflows

| Pattern | Origination | TAT Tracker | Complaint Case application |
|---|---|---|---|
| Compact mobile-first shell | Uses the viewport efficiently and keeps primary work above the fold | Uses compact horizontal metrics and queue tabs | Adopt the same compact header, horizontal metrics, and dense queue tools |
| Bounded queues | Ten applications per numbered page | Explicit Previous/Next page navigation | Ten numbered complaint cases per page, with total and page count |
| Search behavior | Filters after 250 ms and resets immediately when cleared | Queue state is server-filtered and page-aware | Use 250 ms search, immediate clear, page reset, and stale-response suppression |
| Filter discovery | Bottom sheet with active chips | Bottom sheet, one Apply path, removable chips | Move Branch, Priority, Assignment, and SLA to one opaque accessible sheet |
| Navigation state | Preserves list position after opening an application | Consumes one-shot task focus and returns safely to the queue | Preserve complaint filters, page, and list scroll after opening a case |
| Telegram controls | Back closes overlays before leaving workflow screens | Back closes sheets before navigating | Use the same sheet-first BackButton state machine |
| Keyboard handling | Tracks the visual viewport and keeps focused fields above actions | Uses compact controls and viewport-safe sheets | Keep sticky Create/Update actions and focused fields above the keyboard |
| Write safety | Single-flight saves and idempotent server writes | One action produces one stage update | Retain existing single-flight, retry-key, and revision protections |
| Feedback | Clear success/error feedback without redundant controls | In-place refresh and compact status feedback | Replace full reload with in-place refresh and safe-area notifications |

## Workflow-specific exclusions

- Origination signing, document preview, archival, correction, and immutable packet behavior do not apply to complaint cases.
- TAT responsibility rosters, private task inboxes, Telegram DM escalation, stage stamping, and business-hours controls remain TAT-specific.
- Complaint permissions, manager-only closure/reopening, evidence rules, SLA calculations, Google Sheet publication, and Drive access are unchanged by UX parity work.

## Complaint Case queue contract

- The current Mini App requests numbered pages with a fixed maximum of ten cases.
- Queue numbering is continuous across pages.
- Search, status, Branch, Priority, Assignment, and SLA filters are evaluated server-side within the authenticated actor's group and access scope.
- Older cursor clients keep receiving `next_cursor`; numbered clients receive `pagination` and `start_index` in the same response.
- Homepage metrics are actor-scoped and status-focused: Open, In progress, Closed, Total, and Overdue.

## Regression standard

Every future Complaint Case UI change should be checked at 320 px, 390 px, and tablet width. Tests should assert no document-level horizontal overflow, at most ten rendered queue cards, correct numbering and pagination, an opaque and accessible filter sheet, one write for repeated taps, and keyboard-safe primary actions.

## Shared report controls

- Excel opens one shared dialog: **Download filtered** keeps current filters and chart selection; **Download all** includes all dates within that report and the viewer's authorized scope. Export size limits still apply. Switching tabs never widens access.
- Current workload means unfinished work now. Period performance measures dated actions and outcomes; no recorded completions means no completed-action breakdown, not a fallback to backlog.
- Chart explanations live under `?`. Missing-target/timing and repair warnings remain visible. Chart type and time-grouping controls stay in a compact options menu.
- Temporal trends start as lines; comparisons as bars; small outcome proportions as doughnuts; SLA category comparisons as stacked bars. Compatible user-selected alternatives survive refresh.
- Heatmap percentages and distinct contributing-case counts occupy separate lines. Target-met rates use green at 80%+, amber at 60%+, red below 60%; duration and target usage do not reuse this success scale. Missing measurements remain neutral.
- Heatmap selection is computed server-side using the same scoped sample cohort as its cell. The table and filtered export contain those distinct cases, not an action count mistaken for cases. Known stages follow the canonical loan-cycle sequence across product paths.
- Copy feedback retains the complete multiline cell value. Long feedback wraps and scrolls rather than truncating it.
- Keep icon glyphs small and lightly stroked inside mobile-safe tap targets. Inspect synthetic screenshots in both themes at 320–430 px and larger screens; do not accept layout changes from source inspection alone.

Focused browser checks: `npm run test:browser -- report_controls.spec.js complaint_reporting.spec.js portal_reporting.spec.js portal_recognition_layout.spec.js tat_recognition_layout.spec.js`.
