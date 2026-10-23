# Placement-driven Origination forms

Accepted - 13 October 2026.

Amended - 23 October 2026: the user's strict placement-only requirement removes
all operational exceptions for editable forms. Submitted version-1 packets keep
the original projection through the isolated version-1 reconstruction service.

## Context

Publishing an unfinished alignment is deliberately allowed (ADR 0046), but
unplaced required fields still appear in the application and can block staff.
Hiding them only in JavaScript would leave validation and PDF values inconsistent.

## Decision

Compile one server-owned form projection from the exact captured PDF layout.
Version 2 keeps only placed document fields active, including identity, signing,
lending, calculation and applicability inputs. No dependency may expose an
unplaced field. Empty input sections disappear. Shared
values remain shared only under the existing version-2 value contract; legacy
document-local values are not silently merged.

New applications capture projection version 2. Existing editable drafts and
correction forms use it too, including an empty projection when no placement
exists; the first successful write records adoption in
existing event metadata so later submission keeps the same interpretation without
rewriting schema/layout snapshots. Previously submitted records retain their old
interpretation. No model, migration, provider call or new publication gate is added.
The API's existing projection wire format remains version 1 for client compatibility;
version 2 identifies the stored/audited server policy, not a new client protocol.

Inactive answers remain recoverable, but cannot be changed through the active
form or influence current validation, calculations or generated documents.
Publishing a newer layout affects new applications only. Required signature
geometry, consent, authorization and commercial checks remain enforced.

## Consequences

Removing a placement removes its input and required check. Required signer
identity inputs must be placed to collect them; OTP dispatch still requires a
valid saved phone and required signing geometry remains enforced.
Selected supporting documents contribute only their active fields. Submitted
and signed snapshots are never backfilled or reconstructed from current templates.

## Alternatives considered

A separate visibility checkbox would create two competing definitions of the
form. Filtering only in the browser would retain hidden-field blockers. Editing
existing schemas or signed packets would destroy historical reproducibility.
