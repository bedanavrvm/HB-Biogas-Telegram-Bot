# Media spacing, Complaints corrections, image loading and queue order

User direction: place Portal's media heading outside its card with a visible gap;
retain only the Complaints pencil; pair appropriate fields; provide date/time
pickers; improve image loading; put Oldest/Newest inside queue filters.

## Changed controls

Portal's disclosure heading now sits above the inner media card with the same
11px separation and typography as Comment and Visit details. Required/optional
outcome handling and deposit holds are retained. The camera regression checks
the actual gap, heading outside the card and matching section-label typography.

Telegram correction previously became a third flex item inside the case header,
squeezing the customer heading and form. The editor now sits below that header
at full card width. Its accessible pencil has no redundant visible label.
Short identity/contact/location fields pair in two columns; name and description
span the form. Native datetime-local controls show reported/resolved times in
EAT, spanning phones and pairing on wider screens. Unchanged timestamps retain
their precision; edited times explicitly submit +03:00 regardless of device
timezone. Existing revision checks, request keys, permission and audit remain.

Browser Complaints uses the same pencil and field arrangement in its existing
dialog, with Edit Complaint and Save changes. Existing field styling is reused.
No workflow, capability, channel or deployment flag was added.

Telegram queue filters now offer Oldest first/Newest first, passing the choice
to the existing actor-scoped ordering service and resetting pagination. The
selection survives case inspection and view/status changes in the running app.
Browser filters share the existing queue-order state and remain synchronized
with its visible sort selector; priority/overdue options remain available.

## Image latency

The shared Drive reader now uses 8 MiB ranges instead of 256 KiB. With the real
Google MediaIoBaseDownload and a synthetic HTTP transport, a 2 MiB image needs
one request instead of eight; 9 MiB needs two instead of 36. Complete bytes and
retries are retained. This proves fewer round trips, not live production speed.

The browser viewer immediately displays the thumbnail already loaded for the
selected gallery tile while fetching the authorized full-size image. Closing or
failure clears that viewer state. No bytes enter persistent browser storage or
a shared cache, and access checks/auditing remain at the existing endpoint.
Cold downloads and initial thumbnails still depend on Drive/network latency.

## Playwright and backend evidence

The running Django app and isolated PostgreSQL database used synthetic records
and explicit Complaint IT grants. Telegram used signed synthetic identity. The
browser review injected a local actor/session, so it does not certify production
MFA/admission. Owning services handled reads, correction saves, audit and sorting;
Google transport returned synthetic images and non-local hosts were blocked.

The explicit loopback-only COMPLAINT_UI_REVIEW_CONFIG enables
`core/tests_browser/complaint_correction_review.spec.js`. It checks:

- Full-width Telegram forms and paired inputs at 320, 390 and 1280px.
- Date/time picker types and successful Telegram/browser EAT correction saves,
  retaining an unchanged resolution timestamp.
- Oldest/Newest request payloads, reverse result ordering and retained selection.
- Browser filter/dialog layouts at 320/390px light and 1280px dark, including the
  date controls lower in the scrolling form.
- A deliberately blocked full-size request: the existing thumbnail is visible
  within one second while the loading status remains active.

Screenshots in `test-results/playwright/complaint_correction_revie-*` include
`complaint-correction-*`, `browser-correction-*`, `browser-date-pickers-*` and
`thumbnail-before-full-image.png`. Portal states are in
`test-results/optional-media-real-review/empty-*` and `required-*`. These were
visually inspected; column count/viewport fit alone are not acceptance.

The existing backend correction suite also checks unauthorized actors, stale
revisions, invalid/future times and idempotency. Drive range tests use synthetic
HTTP, not a mock of the downloader. The browser build uses the pinned Node 22
runtime and existing dependency review; no dependency or approved baseline changed.

Physical Telegram pickers/camera, live Drive speed and deployment remain unchecked.
No Phase 6 migration or production browser activation is implied.

Final checks: all 14 focused Playwright tests and six backend tests passed.
Browser typecheck, lint and the pinned-runtime build passed, as did the UI source
ratchet and diff whitespace checks. Stable selected screenshots are copied to
`test-results/complaint-ui-final/` for review without relying on the next test
runner's output directory.
