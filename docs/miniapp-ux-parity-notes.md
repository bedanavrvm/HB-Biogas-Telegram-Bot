# Mini App UX Parity Notes

## Purpose

This note records the mobile and operational UX patterns proven in Loan Origination and TAT Tracker, and how they apply to Complaint Case Management. It is a presentation and interaction guide; workflow authorization, state transitions, audit rules, and external integrations remain owned by each workflow.

## Proven patterns

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
