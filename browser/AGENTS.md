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
Dependency/archive/notice/asset review and Telegram compatibility remain binding.
