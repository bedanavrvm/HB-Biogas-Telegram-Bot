# ADR 0070: closed Complaints browser reads

Date: 20 October 2026. Status: accepted for isolated development under the
user's agreement to start Complaints now. Operational admission remains gated.

## Decision

Develop P2a alongside the remaining M1 operational work. Build a separate,
dormant React/ADS Complaints entry and test it against native company
password/MFA sessions and synthetic Django cases. This changes development
sequencing only: M1, named existing readers, privacy/display review and human
acceptance still precede any real staff pilot. Production authentication stays
off, business/auth URLs unmounted, and E006 remains blocking.

The browser boundary requires company assurance on every request, then the
owning Complaints canonical-user actor and `complaint.queue.view` capability.
Groups are enabled database configurations, discovered through current owning
authorization. Opaque configuration/case keys convey no authority. Complaint
reads retain the existing shared-across-branches policy within a permitted
group; unrelated workflow grants convey no authority. Telegram handlers remain
separate and unchanged.

Reuse the owning list/detail/history services with a browser-only allowlisted
projection. Expose case UUID, operational reference, customer display name,
branch/category, status and reported date; detail adds description and bounded
history action/status/time/staff display. Do not return phone/National ID,
Telegram identifiers/raw messages, location, evidence/Drive URLs, sync errors,
field changes or free-text history notes. Names/descriptions remain personal
free text: this is a candidate projection, not privacy acceptance or automatic
redaction. Restrict browser search to names and operational references.

Existing reads may idempotently initialize a missing complaint control/reference;
they do not transition cases or publish to external services. Deny before those
reads. Reuse existing audit/policy machinery, without creating browser grants.

## UI and verification

Use the reviewed dependency graph, actual Navigation System Root/TopNav/Main,
ADS Grid/Stack/Inline/Box/Text/Heading, labelled Form/Textfield/Select and persistent
SectionMessage feedback. The queue sits beside detail at laptop widths, stacks
on mobile, and permits natural scrolling for long history and enlarged text.
No new dependency, font, brand asset, production route, schema or setting.

Official guidance consulted on 20 October 2026:
- https://atlassian.design/components/select/usage
- https://atlassian.design/components/form/usage
- https://atlassian.design/components/form/code
- https://atlassian.design/components/section-message/usage
- https://atlassian.design/components/navigation-system/layout/code
- https://atlassian.design/components/primitives/grid
- https://atlassian.design/components/primitives/grid/code
- https://atlassian.design/foundations/grid-beta/applying-grid

Some layout pages are client-rendered in the text browser; inspect their
installed versioned APIs as well. The layout/Grid code pages were subsequently
read directly. DESIGN.md records the intentional compact desktop filter toolbar
exception to long-form single-column guidance. Technical checks and synthetic real-shell
captures bind a candidate; they do not certify full design conformance or
authorize Telegram UI migration.

Validate native session/CSRF and mixed-credential rejection, missing/unrelated/
revoked grants, group isolation, shared-branch reads, payload exclusions,
search/paging/history, stale-request cancellation, themes, keyboard and mobile.
Keep the pure fixed-value preview disconnected. Rollback removes this separate
entry and dormant boundary; no operational data or Telegram migration is needed.
