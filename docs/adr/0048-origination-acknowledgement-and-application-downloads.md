# Short Origination acknowledgement and application copies

Accepted - 13 October 2026.

## Context

An independently activated consent-policy record and an appended notice page
obstruct testing and add configuration that staff do not need. Officers also
need an application copy before signatures are complete. Existing consent and
signed evidence must not be reinterpreted.

## Decision

New applications capture a server-versioned short acknowledgement in existing
snapshot metadata. Editable drafts adopt it on an audited save, not on a read.
New packages bind that exact acknowledgement and the configured completion
policy into their integrity hash, without adding a notice page or requiring an
active policy record. Historical prepared packages and sessions retain their
captured consent. OTP, individual signing obligations, authorization, geometry,
revision checks and approval rules remain enforced.

Application copies are prepared through an authorized request and delivered by
an expiring, actor-bound link that rechecks access and the captured revision.
Before approval their copy type is labelled unsigned (the red page overlay was
removed by ADR 0049); after approval they contain
the exact signed bytes. Copies do not count as review or signing.

Signature dates belong to the same verified action, not the time of opening a
preview. New authoring placements pair signatures with date slots. Missing date
placements remain authoring warnings; existing published documents are not
silently changed.

## Consequences

No new model, migration, permission, provider or scheduler is required. Old
packages cannot acquire new consent through retries. Updating a published PDF
still requires its editable copy and normal publication; signed files remain
immutable. Native download handoff is not reported as completed download.

## Alternatives considered

Removing consent validation from every historical package would weaken existing
evidence. Keeping a policy activation screen or embedding another notice page
would retain the friction the user explicitly rejected.
