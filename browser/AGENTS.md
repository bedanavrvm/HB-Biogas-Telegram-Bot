# Standalone browser UI

ADR 0075 supersedes the historical unmounted-route boundary below for the
user-authorized conditional Complaints release. Read
`docs/runbooks/staff-browser-production.md` before production routing, onboarding
or deployment. Flags remain default-off until explicit release approval; local
demo/preview graphs and Telegram migration approval remain separate.

Follow the root repository rules and `DESIGN.md`.

## Styling authority

The user's 28 October 2026 instruction supersedes the earlier ADS styling and
full-adoption requirement, now and for future browser UI requests. Use the
user's supplied code/CSS for structure and interactive states and their images
for visual appearance; inspect both before implementation. Current Complaints
reference: `Stitch/Create Complaint/code.html`, `screen.png` and `DESIGN.md`.
Retain the actual workflow permissions, validation, recovery and accessibility
when adapting a reference. Previously agreed feature exclusions remain unless
the user changes them. Reuse installed controls where useful; ADS appearance,
tokens and design-conformance lint are optional. Consult official component API
docs when changing component behavior. Record deliberate reference adaptations
and source-bound Playwright evidence in `DESIGN.md` and the UI source ratchet.

Keep focused access tasks separate from workspace navigation and `/review.html`.
Keep errors in the reading sequence, actions meaningful and layouts responsive.

Check normal/error states visually in both themes and at laptop/mobile sizes.
Preserve readability, keyboard/focus and enlarged-text scrolling. Viewport fit
and source/lint/build tests support review; they do not certify design quality
or authorize operational access. Never update an approved baseline to pass.

Production browser authentication remains disabled and routes unmounted.
Preserve fixed read-only values and zero API/cookie/storage behavior on the
synthetic preview. ADR 0067 separately authorizes a dormant auth build exercised
only against isolated Django tests: same-origin cookie/CSRF, no secret storage,
no workflow authority or operational mount. Keep routine sign-in short, resume
sessions automatically, retain usernames after errors and keep recovery inline;
never add unnecessary confirmations or resend credentials automatically.
ADR 0068 extends that dormant build with guided existing-account setup and
one-time recovery handoff. Native credential QR data is local/transient, never
a remote image or build asset; mask QR/key/codes in screenshots and diagnostics.
Dependency/archive/notice/asset review and Telegram compatibility remain binding.

ADR 0071 additionally authorizes a separate persistent synthetic Complaints demo
on loopback 8767. Reuse the workspace with an injected fixture reader and explicit
demo context; no credential UI or simulated company assurance. Its standalone
server opens only the dedicated integrity-checked fixture SQLite file and
demo-only routes, without Django/settings or operational databases. ADR 0072
extends this simulator with role-based creation, uploads, feedback, resolution,
reopen and missing-details completion. Demo-only POSTs require the local Origin
and custom request header. Mutations and uploaded bytes stay in process memory;
the integrity-checked v2 SQLite seed stays immutable. Persona selection is a
simulator control, never company identity or real authority. Preserve revision,
request-key/payload, reset-generation, group and built-in capability checks.
Native file selection remains governed by the upload limits in DESIGN.md. Never connect this write simulator to the native read API.
Keep its build distinct from the zero-connect preview and native staff client.
This review availability never authorizes production mounting or real staff access.

ADR 0073 adds a separate closed native Complaints operations candidate, not a
simulator upgrade or restricted-v1 change. Before editing channel authentication,
operations routes, SPA navigation or artifacts, read
`docs/runbooks/browser-channel-parity.md`. Keep native/synthetic graphs separate,
customer searches out of URLs and production off/unmounted until release
acceptance. Report verified behavior and remaining parity separately.
