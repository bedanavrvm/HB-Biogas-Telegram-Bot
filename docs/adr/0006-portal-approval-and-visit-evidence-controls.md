# ADR 0006: Portal approval gates and controlled visit evidence

Status: Accepted - 30-July-2026

## Context

The Jawabu Portal moves a case through JBL visit, credit, Head of Rural final
review, order, invoice, and payment review. A simple text decision did not
show the accountable authority, reason, validity, conditions, or whether
material case data had changed afterwards. Visit evidence was also stored as
unstructured links, which made it impossible to prove which case, media type,
and access event a link related to.

## Decision

Use append-only `JawabuApprovalRecord` rows for credit, final-review, and
payment-review decisions. A forward approval carries a structured reason code
and optional conditions. Conditions must be individually cleared before the
approval becomes effective. New approvals are valid for 90 days. Changing a
material controlled field invalidates the active approval and requires the
appropriate gate to be reviewed again; older decisions without an approval
record remain visible as legacy records rather than being silently rewritten.

Credit must be effective before final review; final review must be effective
before order assignment; a payment document records a separate, per-case
payment-review approval. The Portal exposes only the established LAF and JBL
visit-photo categories. A forward JBL-visit outcome requires both categories
and either captured coordinates or a supplied reason why location was not
available.

Temporary approval delegation is scoped to a gate, optional branch/product,
and a maximum 14-day time window. It is authorised and revocable only by the
controlled Portal Admin authority, cannot be self-granted, and is append-only
audited. Media rows bind directly to the case, use a non-PII `case-<uuid>`
storage reference, track content hashes, and log every Portal retrieval. No
new live external writes are introduced by the change.

## Consequences

- A decision is now queryable by gate, authority, reason, validity, condition,
  and invalidation cause rather than inferred from one mutable text field.
- A valid outcome can deliberately be returned for re-review after an
  authorised material correction; the original approval remains auditable.
- A device with GPS unavailable can still record an evidence-backed visit, but
  must make the operational reason explicit.
- Existing legacy media is read through a compatibility fallback. New media
  must use its direct case attachment; no destructive migration of older Drive
  records occurs.
- A read-only orphan-candidate report distinguishes linkable legacy rows from
  unlinked evidence. Retention/deletion and automated escalation delivery are
  intentionally deferred; the current release does not delete Drive files.

## Alternatives considered

1. Keep approval state in the live customer fields only - rejected: it cannot
   preserve authority, expiry, conditions, or post-approval invalidation.
2. Let a delegated staff member inherit unrestricted Admin access - rejected:
   gate/scope/time limits must be enforced server-side.
3. Continue accepting arbitrary evidence labels and raw Drive links - rejected:
   that prevents reliable stage guards and case/media audit evidence.

## Release and rollback

No production migration or Render deployment is authorised by this ADR. Before
production application, verify a PostgreSQL backup and test: a direct
authorised approval, a denied approval, conditional release, invalidation after
a controlled system export, a scoped delegation, both visit media types, media
retrieval audit, and an expired approval.

Migration `core.0081_jawabuapprovalcondition_jawabuapprovaldelegation_and_more`
adds approval, delegation, and media-audit tables plus the controlled
delegation capability. To undo after an approved migration, first export the
approval/delegation/media access evidence that must be retained, then run:

```powershell
python manage.py migrate core 0080_physical_document_signoffs
```

The reverse migration removes only the new control schema and seeded policy;
it does not delete Drive files, workbooks, existing farmer records, or Sheets.
