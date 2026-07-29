# ADR 0003: Governed Jawabu customer data quality

## Context

Jawabu customer values enter through FarmUp, the Portal, and the IMAB system
export (`/sysup`).  A national ID, customer number, or phone number can point
to the same person, while a changed SIM or a differently ordered name can make
otherwise valid records look unrelated.  Sheets are operational views and must
not become an uncontrolled second source of truth.

## Decision

Django resolves customer identity using one service.  A single exact national
ID, customer number, or current/historical normalized phone may link an
existing case.  Conflicting exact identifiers and all name-based candidates
remain in a staff review queue; fuzzy similarity never performs a merge.

National IDs are normalized to digits.  Seven through nine digits are treated
as the supported Kenyan format; other non-empty values create a review issue
instead of forcing staff to invent a replacement value.

The system export owns customer number, IMAB display name, system branch, loan
officer, product, and JBL deposit.  Django owns workflow and staff-entered
operational fields.  Every cross-system field update records append-only
provenance.  Branches/counties remain centrally configured, while a new
operational product catalogue governs system-export product values.

## Consequences

Existing records are preserved and reconciliation is review-first.  Active
Jawabu cases and `/sysup` are the first rollout boundary; Complaint Cases,
TAT, and SPIN are not retrospectively migrated by this change.  Admin users
gain a compact exception queue and operational quality metrics.

## Alternatives considered

- Auto-merge high-scoring names: rejected because matching errors would
  corrupt CRB/KYC identity and payment records.
- Treat Sheets as an equal writer: rejected because it weakens auditability and
  creates silent conflict behaviour.
- Hard-reject unusual IDs: rejected because historical and exceptional values
  need supervised correction rather than workarounds at the form boundary.
