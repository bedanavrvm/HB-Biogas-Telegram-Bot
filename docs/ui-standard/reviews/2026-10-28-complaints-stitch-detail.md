# Complaints browser detail: Stitch implementation candidate

This implements the approved detail-first plan using `Stitch/Create complaint.txt` as the visual reference. Queue, creation, reporting and settings retain their existing workflows. The selected complaint uses the same vertical section order on mobile and wide screens; there is no desktop queue sidebar. This is a source-bound review candidate, not approval of a screenshot baseline or production activation.

## Features and interactions

| Area | Behaviour |
| --- | --- |
| Navigation | Complaint reference and status sit above the title. Back returns to the queue with its in-memory search, filters and scroll position. Previous/next follow the filtered queue and keep its order/page. Copy link copies an opaque complaint URL; phone values use telephone links. |
| Customer information | A two-column grid shows the actual customer, National ID, primary/alternative phone, branch, category, reported date, age and stored priority. Initials replace stock portraits. Long values wrap. |
| Description | Read-only saved description. Description editing and assignment were explicitly excluded. |
| Location | Reuses the Portal's vendored Leaflet 1.9.4 and configured CARTO Voyager street tiles. The saved marker supports pan, zoom and refresh, with OpenStreetMap/CARTO attribution. No coordinate editing or GPS capture is added. Missing coordinates/configuration, unavailable assets or failed tiles retain an HTTP(S)-only external map link and appropriate guidance. |
| Attachments | The protected gallery retains thumbnails, image/PDF preview, file/page navigation, zoom, fit controls and original download. File metadata comes from the owning complaint service. Private Drive IDs/URLs do not cross the conversation projection. |
| Conversation | One staff discussion visible to staff with access to this complaint. Officer, Manager, HB staff and scoped IT may add append-only comments. There is no customer/public channel or outbound notification. Text has a 5,000-character limit and supports basic `**bold**`; HTML is rendered as text. |
| Replies | Reply quotes the same-case parent. Replies to replies are attached to their root, retaining one indentation level. Older comments load through a signed, case-bound cursor. |
| Mentions | Search only returns active Complaint staff authorized for this case. Up to ten selected mentions retain server-captured names and identities. A mention grants no authority and sends no email/Telegram notification. |
| Reactions and links | Each actor has one reversible thumbs-up per comment. Revision and request-key checks protect concurrent requests. Comment links retain a UUID fragment; older linked comments are fetched through the same authorization check. |
| History | A separate tab retains existing state changes, actor attribution and HB feedback. Reading History preserves the unfinished conversation. Staff conversation entries do not become HB resolution feedback, change the HB badge count, restart SLA timing or add resolution/reopen events to Sheets/reports. |
| Saving and recovery | Exact request IDs bind the author, text, parent, mentions and attachment bytes. A double submit creates one comment. Offline work stays in the current tab and is not sent automatically. The same admitted account can resume text/files after native password/MFA reauthentication. An uncertain response exposes an explicit exact retry. Resolve-and-open-next holds automatic navigation when another staff comment is unfinished, retaining that draft. |
| File failure | Canonical comment text commits before Drive publication. Failed publication retains the selected files and a Retry attachments action. An exact retry reuses the evidence row and comment. Closing the complaint does not discard an already-saved comment's publication recovery. |
| Resolution | Existing HB resolution, Manager reopen, missing-details completion and publication recovery remain available through the real action dialogs. Resolution requires the existing free-text note and retains evidence upload; no sample resolution-code catalogue or new business requirement is introduced. Closed complaints have read-only conversations until reopened. |

## Implementation boundaries

`complaint_conversations` owns author/reply/retry context, explicit mention links and reaction state. `CaseUpdate` remains canonical text/history/evidence ownership, using the distinct `browser_staff_comment` source. The existing `mini_app_comment` source and `complaint.case.comment` capability retain HB resolution-feedback semantics.

The checked-in `0210_complaint_conversation_capability` migration adds `complaint.conversation.participate` for the four existing Complaint roles only. The new app migration declares table/column comments and retention. FK indexes and the two uniqueness constraints support ownership/actor lookups; no extra explicit index was added. Account removal preserves historical names, while scoped complaint testing deletion includes the owned context/mentions/reactions and retains external files.

Browser production delivery verifies the reused Leaflet source/output hashes and ships its licence. CSP permits only the existing same-origin application assets and three specific CARTO tile hosts for map images. Default-off browser flags and deployment/onboarding approvals are unchanged.

## Design sources and deliberate compositions

Official guidance consulted on 28 October 2026:

- [Comment usage](https://atlassian.design/components/comment/usage/): author/time, contextual actions, limited nesting and familiar local time. The installed stack has no Comment package; the thread composes pinned ADS primitives, text, icons and buttons with semantic articles instead of adding a dependency.
- [Tabs usage](https://atlassian.design/components/tabs/usage/): two local views, keyboard navigation and important complaint facts outside the tabs.
- [Form usage](https://atlassian.design/components/form/usage/): labels, required legend, character count and field errors in the reading sequence. The existing token-styled native textarea and hidden native file input remain documented compositions; visible controls use ADS.
- [Button usage](https://atlassian.design/components/button/usage/): one main action within each task, short labels and labelled icon buttons.
- [Modal dialog usage](https://atlassian.design/components/modal-dialog/usage/): existing bounded task dialogs retain focus, footer, cancellation and server errors.
- [Leaflet reference](https://leafletjs.com/reference.html): recorded marker, map lifecycle, tile failure and size invalidation. Tile configuration follows the existing Portal implementation.

No Tailwind CDN, remote portrait, external font, new npm dependency, candidate Mini App token migration or approved-baseline update is included.

## Evidence and validation

Local screenshots and interaction records are in `test-results/complaints-stitch-detail/`; the gallery is `index.html`. Before screenshots bind to HEAD `f3bdd01a`. Final build/source and screenshot hashes are recorded in the evidence manifest. Synthetic staff/customer values only; password/MFA proof is kept out of screenshots and logs.

Verification uses Chromium Playwright against the production browser artifact, native password/recovery-code MFA, actual Django endpoints and an isolated PostgreSQL 18 instance. Drive upload/download are deterministic local substitutes, including an explicit outage. Live CARTO returned an API-key placeholder image despite HTTP 200; no CARTO key is configured locally. Map interaction captures use visibly labelled synthetic tiles. The missing-key and failed-tile fallbacks are verified separately; live cartography remains unverified until a valid deployment key is supplied. No operational database or real staff/customer messaging is used.

The existing 132-check Complaint regression run has three failures also reproduced on unchanged HEAD: two older global-register expectations (timing columns and sort validation) and one Telegram asset-string expectation. They were not edited to make this candidate pass. Full logs: `existing-checks.log` and `baseline-checks.log` in the evidence directory.

The additional boundary run passes 20 of 21 existing checks, including native PostgreSQL security state, five-process rate limiting, two-process TOTP reuse prevention, production artifact delivery, catalogue metadata and complaint deletion ownership. Its one failure is an existing duplicate `RequisitionBatch.order_number` index, also reproduced on unchanged HEAD (`baseline-catalogue-check.log`). The new conversation tables introduce no explicit duplicate index. The existing production asset fixture was extended to carry the three required vendor hash bindings; no unit test was added to certify the new UI.

Final browser observations, screenshot matrix and remaining limitations are recorded with the evidence manifest; screenshots support review and do not constitute human design approval, physical-device acceptance or a release decision.

The final responsive matrix contains 42 captures covering 320, 390, 768, 1440 and 1920 CSS-pixel widths, both themes and 200% CSS zoom, including each main section and the composer. Targeted captures record mentions, reply/reaction links, attachment failure/retry and preview, expired/uncertain saves, actual HB resolution and Manager reopen, concurrent closure, denied roles, older-message links and queue return. Queue search/previous/next and the mobile scroll return were exercised; the recorded scroll position returned from 257 to 257 pixels. Keyboard tabs and the conversation shortcut's editor focus were checked. The final map retry loop records zero page errors.

Open the [local screenshot gallery](../../../test-results/complaints-stitch-detail/index.html) or [source/evidence manifest](../../../test-results/complaints-stitch-detail/evidence-manifest.json). The gallery labels the superseded and provider-placeholder diagnostics separately from the final matrix.
