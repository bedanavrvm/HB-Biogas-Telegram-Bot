# Placement-driven Origination forms

Accepted - 13 October 2026.

## Context

Publishing an unfinished alignment is deliberately allowed (ADR 0046), but
unplaced required fields still appear in the application and can block staff.
Hiding them only in JavaScript would leave validation and PDF values inconsistent.

## Decision

Compile one server-owned form projection from the exact captured PDF layout.
Only placed document fields and necessary identity, signing, lending, calculation
and applicability inputs remain active. Empty input sections disappear. Shared
values remain shared only under the existing version-2 value contract; legacy
document-local values are not silently merged.

New applications capture projection version 1. Existing editable drafts with a
captured PDF layout use it too; the first successful write records adoption in
existing event metadata so later submission keeps the same interpretation without
rewriting schema/layout snapshots. Previously submitted records retain their old
interpretation. No model, migration, provider call or new publication gate is added.

Inactive answers remain recoverable, but cannot be changed through the active
form or influence current validation, calculations or generated documents.
Publishing a newer layout affects new applications only. Required signature
geometry, consent, authorization and commercial checks remain enforced.

## Consequences

Removing a placement also removes its non-essential input and required check.
An essential input may still appear in a clearly named operational section.
Selected supporting documents contribute only their active fields. Submitted
and signed snapshots are never backfilled or reconstructed from current templates.

## Alternatives considered

A separate visibility checkbox would create two competing definitions of the
form. Filtering only in the browser would retain hidden-field blockers. Editing
existing schemas or signed packets would destroy historical reproducibility.
