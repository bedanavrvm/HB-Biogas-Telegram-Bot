# Standalone browser UI

Follow the root repository rules and `DESIGN.md`. The user explicitly requires
consulting the current official Atlassian documentation for every browser UI
change. Read the relevant usage/design guidance and the exact installed APIs;
do not rely on memory, import names, lint success or old screenshots as proof
of design adoption. Record applicable source links and deliberate exceptions.

Keep focused access tasks separate from the workspace navigation shell and
the `/review.html` design harness. Use ADS components for their documented
purpose. Keep essential descriptions/errors in the form reading sequence,
one primary action, meaningful surfaces and coherent page grids. Do not put
sunken surfaces on raised/overlay surfaces. Avoid repeated helper warnings,
disabled mock navigation and button collections that replace selection controls.

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
Native file selection is the narrow documented exception in DESIGN.md; visible
controls remain ADS. Never connect this write simulator to the native read API.
Keep its build distinct from the zero-connect preview and native staff client.
This review availability never authorizes production mounting or real staff access.
