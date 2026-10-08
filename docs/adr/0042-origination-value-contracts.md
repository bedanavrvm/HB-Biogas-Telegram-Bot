# Versioned Origination field meanings and shared values

Status: Accepted - 8 October 2026

## Context

Canonical keys alone do not distinguish a request from approval or receipt,
nor prevent supporting-document overrides of shared application information.
Existing signed packets must retain their exact interpretation and bytes.

## Decision

Extend the existing field catalogue with validated semantic contracts. Reviewed
documents explicitly select value-contract version 2. A shared module resolves
application, document-instance, calculated and workflow values; snapshots retain
the selected contracts and each document's resolved context. Existing flat keys,
commercial quotes, document-defined signers and authoring workspaces remain.

## Consequences

Legacy applications are not backfilled. Later-event values remain unavailable
without evidence, incomplete drafts remain saveable, and unresolved paper wording
is a repair task rather than a guessed mapping. No company-applicant, dynamic
guarantor, disbursement or receipt workflow is introduced. Metadata changes require
an additive Origination migration; no production activation is automatic.

## Alternatives considered

Renaming all fields or adding a model for every PDF/entity would duplicate existing
contracts. Globally changing the renderer would reinterpret historical packets.
Keeping document-local shared overrides would leave the original inconsistency.
