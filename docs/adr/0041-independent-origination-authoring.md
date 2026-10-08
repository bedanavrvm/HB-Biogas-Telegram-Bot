# Independent Origination product and document workspaces

Status: Accepted - 8 October 2026

## Context

The guided product stepper mixed commercial decisions with PDF authoring and exposed two competing form/signer definitions. A custom PDF could be uploaded but its signers could not be repaired in the placement editor.

## Decision

Products configure details, lending terms and catalogue document selections through a non-linear task list. An independent Document editor owns the PDF, signers, fields and placement. Both autosave drafts and expose one Publish action for their own aggregate. Product publication never publishes documents. Server readiness is also the navigation/to-do projection.

Published content remains immutable. Editing a shared document explicitly chooses a shared update or an independent product-only copy. Shared publication validates all affected products atomically; copies replace only the selected product's choice. Existing applications retain exact snapshots and signing policy. No new persistent setup state or permission policy is introduced.

## Consequences

Incomplete authoring is saveable, but missing consent, incompatible commercial fields or incomplete required placements still prevent publication. Terms publication and document publication are separate recoverable operations, not a half-enabled combined action. Existing advanced routes remain compatible but normal navigation uses the two workspaces.

## Alternatives considered

Adding more steps or automatic product-owned forks preserves the confusing ownership and repair gates. Removing publication checks would hide invalid signing contracts rather than fix authoring.
