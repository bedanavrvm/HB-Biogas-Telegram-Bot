# ADR 0072: role-based Complaints demo journeys

Date: 20 October 2026. Accepted for synthetic local implementation under the
user's request for realistic role/action journeys, specifically creation/uploads.

## Decision

Extend only the separate loopback demo. Model Officer, Complaint Manager,
HB Resolver and scoped IT, plus a Portal-only persona with no Complaint access.
Read built-in Complaint capabilities from the checked-in catalogue using AST;
do not import Django or claim to reproduce deployment policy overrides. Preserve
group isolation and shared-across-branches reads within a permitted group.

Support the complete synthetic handoff: Officer/Manager create a complaint with
required customer/location/category/description and optional local evidence;
Officer/Manager complete historical Needs details; HB adds append-only feedback
and resolves; Manager reopens with a reason. IT explicitly simulates the existing
technical override. Officer/Manager/HB/IT can attach genuine JPEG/PNG/WebP/PDF
evidence and inspect authorized attachments. No Complaint authority comes from
the Portal-only persona. Reports/export, voice, maps and external publication
are not simulated as successful features.

Keep a verified version-2 seed SQLite fixture, separate from the old fixture.
All entered values, uploaded bytes and mutations live only in bounded process
memory. Changes are shared across demo roles/tabs and survive refresh until
Reset demo or server restart. Never write uploads, entered identifiers or action
bodies to disk/logs. Reset increments the sandbox generation; server revision,
request-key/payload checks and group/capability checks reject stale or forbidden
actions. Reset is confined to this sandbox. No production model or migration.

Demo POSTs require exact same-origin Origin, a custom demo request header, JSON,
bounded request/file sizes and the existing Host/auth-header restrictions. The
persona header is an explicit simulator control, never authentication. Genuine
file signatures/extensions, per-file and total limits are checked. Repeated
files are reused per case; stale/retried submissions never duplicate effects.
Images preview through transient blob URLs; PDFs download on explicit request.
Neither files nor workflow effects reach Drive, Sheets, Telegram or Django.

## UI and evidence

Reuse ADS navigation, primitives, labelled Select/Form/Textfield/Button and
persistent SectionMessage feedback. Use one role selector and one contextual
action selector, not a collection of mock permission buttons. Creation uses two
short, single-column steps with sample-fill helpers and a side summary. A native
file chooser is a narrow documented exception because the reviewed dependency
graph has no upload component; its visible control uses ADS Button. File-picker
behavior, validation, preview/removal and role permissions must actually work.

Official sources consulted: https://atlassian.design/components/select/usage,
https://atlassian.design/components/form/usage,
https://atlassian.design/components/button/usage,
https://atlassian.design/components/section-message/usage and
https://atlassian.design/components/navigation-system/layout/code.

Validate role handoffs and denials, creation requirements, uploads/signatures/
limits/deduplication, evidence scope, audit attribution, comments vs resolution,
reopen, revisions/replays/reset, keyboard, normal/errors and laptop/mobile themes.
Keep native P2a read/auth tests separate. This does not activate P3 browser writes,
accept M1/M2, grant staff access or migrate Telegram. Rollback restarts the prior
read demo; old immutable fixtures and all operational records remain untouched.
