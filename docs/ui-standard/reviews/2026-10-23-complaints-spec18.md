# Complaints browser Specification 18 candidate

This implements [Specification 18](https://github.com/bedanavrvm/HB-Biogas-Telegram-Bot/issues/18)
on `Platform-Interdependence`, including the previously authorized browser task
recovery and PostgreSQL security-state work. It is a review candidate.
Production browser routes remain disabled and unmounted.

## Source and visual evidence

The comparison uses the same synthetic native-session Django fixture, with
separate browser contexts for each build. The before UI is the clean
`f4a37ded8373f84b6d327fcd94ed431c40fe29e9` source, rebuilt separately under
`test-results/spec18-before/`; it is not a reconstruction of every earlier
uncommitted recovery change. The after UI is the current working source. Both
manifests validate source and asset hashes before capture. No human review
server is restarted, and no operational data or credentials are captured.

| Correction | Before and after evidence under `test-results/spec18-comparison/{before,after}/` | Interaction evidence |
|---|---|---|
| Queue and detail | `queue-{light,dark}-{390,1366}.png`, `detail-{light,dark}-{390,1366}.png` | 31 open cases, oldest/newest server order, page boundary positions, explicit resolution and next-case reconciliation |
| Shared controls and feedback | `create-{light,dark}-{390,1366}.png`; recovery captures under `complaints-task-recovery/` | Product confirmations, retained entries/files, same-request retry, sign-out protection, independent notification ownership and timed/paused success feedback |
| Protected evidence | Native rendered `complaints-spec18/<build>/evidence.png` | Image/PDF thumbnails, two-page navigation, original filename, unsupported/pending/unavailable items; colliding cross-group message IDs deny both bytes and incorrect audit writes |
| Reports | `reports-{light,dark}-{390,1366}.png`; `complaints-spec18/<build>/reports-*.png` and `timing-line-gaps.png` | Six cards, table-only search, 25 server rows, scoped export/email, keyboard tabs, real scrollport header, timing alternatives and missing-period gaps |

Each comparison directory's `manifest.json` records the exact source/artifact
hashes, capture time and screenshot SHA-256 values. The native journeys also
cover 320, 360, 390, 768, 1366 and 1920px, both themes, a 768px-high laptop,
200% text, reduced motion and a shortened mobile viewport. Fresh candidate
screenshots are inspected visually; their existence is not human design approval.
No approved screenshot baseline is replaced.

## Design references and boundaries

Applied official usage guidance and explicit first-party compositions are in
[browser/DESIGN.md](../../../browser/DESIGN.md). They cover modal tasks and
dismissal, notifications, tooltips, elevation, typography, icon buttons, selects
and AG Grid auto-height layout. The installed dependency graph is unchanged.
Green positive actions, existing upload authority, full authorized identifiers,
Excel/email outputs and existing workflow roles follow the specification.

Images and PDF pages use bounded authenticated previews. Unsupported legacy
originals download only as attachments with an allowlisted safe fallback type;
they never become previewable HTML. Evidence belongs to its actual owning case,
even when two Telegram groups have the same source message number. No provider
error, Drive identifier or private storage URL reaches the browser.

## Verification and rollback

Executed command results and known unrelated failures are recorded in the
[channel runbook](../../runbooks/browser-channel-parity.md#specification-18-verification).
Tests use isolated synthetic databases and block external delivery. They do not
repeat the separately authorized earlier Gmail smoke check.

For each UI correction, restore the corresponding previously accepted browser
sources/artifact, rebuild both modes and rerun its native journey before serving
it. Reports and queue API additions are backward-compatible projections; keep
the evidence ownership fix, canonical saves and native authorization in place.
Do not roll back shared security state to process-local caches. ADR 0074 documents
the separate migration rollback boundary: browser off/unmounted first, preserve
live claims and revocation state, and never clear a live store for a UI rollback.
No production migration or deployment is part of this implementation.

Physical phones, camera/download/dialer integration, a screen reader, named
privacy acceptance and deployed M1/support acceptance remain unverified. Local
Playwright and visual review do not accept those operational gates.
