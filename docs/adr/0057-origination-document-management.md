# Manage application documents and clean Main LAF changes

Accepted - 16 October 2026.

## Context

The Main LAF action required an alternative form even when an officer only
wanted to change supporting documents. Its replacement flow copied answers,
which the user explicitly rejected: a different Main LAF invalidates the draft.

## Decision

One Manage documents chooser presents the captured Main LAF and supporting
documents, plus newly published product-compatible document types. Existing
types retain their captured versions; this is not an implicit upgrade tool.
Supporting-only changes retain the application and recoverable document answers.
Their selected contracts govern visible fields, evidence and signing obligations.
The supporting form uses its captured placed fields and section labels, with
shared inputs collected once and document-local inputs retained on that document.
Removing a selection removes its inputs and required checks, not saved answers.

A confirmed Main LAF change atomically cancels the source and creates a blank
replacement with the chosen documents. Only officer, group, branch and product
context survive. Answers, uploads and configured application signers do not move.
Previously completed restart requests still replay their original result.

## Consequences

Only the assigned officer can change an editable draft. Submitted applications
use existing withdrawal rules; signed and completed documents remain unchanged.
New attachments capture published contracts and validate against the retained
Main LAF, without rewriting its schema or commercial terms. Selection changes
invalidate prior previews and download links. No external calls or schema changes
are required.

## Alternatives considered

Separate document controls obscure a single task. Updating the Main LAF in place
would preserve the reference but obscure the deliberate clean restart. Copying
compatible answers was rejected by the user, even when their types match.
