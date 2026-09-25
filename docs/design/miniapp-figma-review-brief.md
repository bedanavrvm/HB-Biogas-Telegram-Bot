# JBL Mini App design review: Figma production brief

Status: Figma review draft created at https://www.figma.com/design/ycGaOEBybxOPAc8WA0hw8e . Reviewer decisions are pending. This is a design artifact, not an approved UI specification. Do not change production Mini App components or their Playwright assertions until the Figma decision board is reviewed.

## Current Figma draft and remaining work

- The connected Figma Starter workspace limits the file to three pages, so the draft uses `00 Decisions and coverage`, `01 Shared candidates`, and `02 App comparisons` rather than one page per Mini App. Light and dark tokens use separate collections because the Starter plan permits only one mode per collection.
- `02 App comparisons` contains current-template/CSS reconstructions and proposed primary-workflow screens for Portal, TAT Tracker, Complaint Cases, SPIN, FCA Review, Order Approval, Farmer Review, and Loan Origination. Each app has a 320 x 568 and a 430 x 932 current/proposed pair. All displayed names and references are synthetic. These are *not* live screenshots or verified pixel-perfect captures.
- The Portal 320 px pair was visually inspected for overflow. The overall comparison board was inspected, but its 430 px layouts still have excess empty space and need density refinement. Loan Origination's third workspace tab is absent in its cloned draft and must be added before review sign-off.
- The shared-candidate board has light/dark token swatches and type references. The decision board has six candidate areas, all explicitly pending; no Keep/Adapt/Do not share choice has been made.
- Still needed: app-specific detail/form/overlay frames, loading/empty/error/disabled/expanded states, interaction and permission annotations, better 430 px density, a full visual QA pass, and reviewer decisions. Figma MCP hit the Starter call limit before those could be completed.

## Review file structure

Create one Figma file named **JBL Mini Apps — Current UI and Shared Design Review**. Use pages in this order: `00 Decisions and coverage`, `01 Shared candidates`, `02 Portal`, `03 TAT Tracker`, `04 Complaint Cases`, `05 SPIN`, `06 FCA Review`, `07 Order Approval`, `08 Farmer Review`, `09 Loan Origination`.

For each unique pattern, pair an **As used now** frame with a **Proposed** frame at 320 × 568 and 430 × 932. Add a desktop/tablet frame only where a grid, report, or split layout materially changes. The current frame must be captured from a running local/test-data app or faithfully reconstructed from its current template and styles; label reconstructions so they cannot be mistaken for screenshots. Use synthetic names, identifiers, documents, and counts throughout. Include light and dark variants for shared candidates. Show states that affect the choice: idle, active/selected, loading, empty, success, error, disabled, and expanded where applicable.

The decision board has one row per candidate pattern, with source app/screen, current variants, proposed variant, and a reviewer decision of **Keep**, **Adapt**, or **Do not share**. An empty decision is not approval. Preserve each Mini App's own workflow labels and permissions even if its presentation becomes shared.

## Source inventory and required comparison frames

| Mini App | Screens/contexts to represent | Distinct UI to compare with shared candidates | Source of current UI |
|---|---|---|---|
| Portal | Home and pipeline queues; case detail/history; FarmUp and SysUp import review; order/invoice/payment preparation and approval; HB installation/commissioning; reports; settings | Shell and notification bell; four-hub mobile navigation; queue toolbar/search/filter sheet/chips; cards and counters; compact payment and HB detail; dense AG Grid review; document preview; sticky actions; loading/empty/error | `core/templates/base_shell.html`, `core/templates/portal/portal.html`, `core/static/miniapp/portal.css`, `components.css/js` |
| TAT Tracker | Cases and task inbox; stage detail/correction; create/search; reports; recognition; settings | Header/bell; workspace and queue tabs; stage/status chips; stage-action form; filter sheets; charts and AG Grid; recognition cards; document preview; notice toast | `core/templates/tat_tracker/app.html`, `core/static/miniapp/tat_tracker.css` |
| Complaint Cases | Queue; create/reopen/resolve; detail/history/evidence; management overview; export | Header/refresh; workspace and status tabs; search; complaint card; voice/media capture; location; sticky submit; confirmation and camera sheets; toast/error; report charts and grid | `core/templates/complaint_cases/app.html`, `core/static/miniapp/complaint_cases.css` |
| SPIN | New request; dashboard; settings; review/submit | Branded header and draft state; tabs; grouped form fields; uploads; review summary; validation and status banner; modal | `core/templates/spin/form.html`, `core/static/miniapp/spin_form.css` |
| FCA Review | Batch review and commit | Header; four summary metrics; approve/skip/commit toolbar; editable dense table; row review and error feedback | `core/templates/fca_review/review.html`, `core/static/miniapp/fca_review.css` |
| Order Approval | New/update order record; review and submit; offline/recovery | Form header; grouped fields; document/media controls; review dialog; draft/offline feedback; disabled/in-flight submit | `core/templates/order_approval/form.html` and its inline styles |
| Farmer Review | Farmer upload and system-export batch review | Header; summary metrics; search and review-only filter; editable table; row approval; commit toolbar/status | `core/templates/jawabu_farmers/review.html`, `core/static/miniapp/farmup_review.css` |
| Loan Origination | Application queues; capture/review; packet preview; signing/review decisions | Header; queue tabs/search/filters; application cards; dynamic form; bottom sheet; correction dialog; document preview controls; toast and review feedback | `core/templates/loan_origination/app.html`, `core/static/miniapp/loan_origination.css`, `loan_origination.js` |

## Shared candidates to put on the decision board

1. **Foundation:** brand use, type scale, spacing/density, color and semantic states, borders/radii, icon sizes, 44 px touch targets, focus rings, light/dark tokens, safe-area handling.
2. **Navigation:** app header, notification/inbox trigger, top-level workspace tabs, status tabs, back control, refresh control, sidebar/bottom navigation where appropriate.
3. **Finding work:** search input, filter trigger and sheet, active chips, counters, queue/list row, pagination, no-results and no-access state.
4. **Doing work:** section/card, labelled input, help/error text, upload/preview row, primary/secondary/destructive action, sticky action dock, progress/loading state.
5. **Feedback and overlays:** toast/notice, actionable error with retry/reference, confirmation dialog, bottom sheet, document/media viewer, retained-draft/conflict notice.
6. **Data presentation:** compact metric, status badge, timeline/event group, dense table controls, chart header and empty state. A shared visual wrapper must not alter AG Grid semantics or each app's data/permission rules.

Before proposing a shared component, record the behavior each current version performs (for example, whether Back closes an overlay, how a dirty form survives a refresh, and whether a hidden tab's space collapses). Do not standardize away those behaviors by copying appearance alone.

## Design acceptance and implementation gate

- Every active app above has current/proposed comparisons for its unique patterns; identical patterns may link to one shared candidate rather than repeat frames.
- The decision board identifies what is shared and what stays workflow-specific, including any rejected alternatives.
- A reviewer can inspect 320 px density, text readability, control alignment, touch targets, light/dark contrast, and error/empty states without using real customer data.
- Only after explicit review decisions: update `components.css/js` and Portal first, then migrate other apps in bounded passes and tighten Playwright checks at 320, 360, 390, 430, 768, and desktop widths. Keep current routes, authorization, state transitions, and idempotency unchanged.

Figma creation requires a connected Figma account. The repository currently has no Figma connection available to this agent; this brief is preparation, not a substitute for the requested Figma file.
