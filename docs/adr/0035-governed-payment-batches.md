# ADR 0035: Governed Payment Batches

## Status

Accepted.

## Context

The earlier payment screen generated document snapshots directly from a temporary selection. It did not provide a durable view of work in progress, made the official payment number user-entered, and could make a generated workbook appear final before a signed copy existed.

## Decision

Payments are owned by the bounded `payments` Django app. A `PaymentBatch` is the authoritative workflow record and has one mode: `LOAN-JAWABU` or `CASH`.

The lifecycle is:

1. Draft: Operations selects ready Portal cases.
2. In Head of Rural review: the server allocates the next group-scoped payment number exactly once and each current case receives an explicit decision and comment.
3. Review complete: every current case is approved against an exact digest of payment-relevant values.
4. Awaiting signed scan: an immutable workbook version has been generated. Cases may still be added or removed, but doing so supersedes that workbook and sends the batch back through review.
5. Completed: an authorized user uploads the signed scan for the exact current workbook. Membership and mode are then locked.

Cancelled unfinished batches retain their membership and event history but release their cases for a different active batch. A completed batch cannot be cancelled.

Payment numbers are allocated under a database row lock. They are unique within a workflow group, are never manually entered in the Mini App, and are never reused. Any IT repair must move the next number above every allocated value and record an attributed reason.

`PaymentDocument` remains the immutable binary workbook store. Drive is a publication target; Django batch state, revisions, reviews, digests, and event records remain authoritative.

## Data and retention

Payment batches, memberships, reviews, official sequence events, and batch events are permanent financial workflow evidence. Event metadata avoids customer data. Foreign keys use `PROTECT` for governed business evidence and `SET_NULL` only for staff attribution when an account is removed.

The explicit `(group_configuration, status)` and `(batch, is_active)` indexes support the monitored batch list and current-membership reads. The indexed decision field supports review-progress queries. Request-ID indexes support idempotent retry lookup.

## Consequences

Changing a case, mode, or membership after review invalidates approval for affected data and supersedes an existing unsigned workbook. Completion cannot occur from workbook generation alone. The Mini App can show batch counts, individual decisions, activity, and signed-scan readiness without reconstructing state from document artifacts.
