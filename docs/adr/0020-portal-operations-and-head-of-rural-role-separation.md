# 0020 — Portal Operations and Head of Rural role separation

**Status:** Accepted for code merge and local/staging migration validation on 03-August-2026. Production migration application and Portal release remain subject to the approved release gate.

## Context

The historical `BUSINESS_ADMIN` Portal role mixed two different business responsibilities: Head of Rural approval decisions and operational processing. That made least-privilege review difficult and could give an approver routine invoice, order, or document-generation controls they do not need. JBL Officers also needed a safe way to follow cases after recording a visit, without receiving order-generation access.

## Decision

- Keep the stable `BUSINESS_ADMIN` code for historical grants and audit evidence, but label it **Head of Rural** in the Jawabu Portal UI.
- Add `OPERATIONS_ADMIN` as a separate Portal business role.
- Define Portal capabilities centrally and enforce them server-side:
  - **Head of Rural:** final and payment review, approval delegation, read-only case/media/document access, and physical sign-off where the approved document policy permits it.
  - **Operations Administrator:** operational queues, credit recording, order/requisition generation, invoices, payment preparation, document regeneration, and physical sign-off where the approved policy permits it. It cannot log JBL visits or record Head of Rural decisions.
  - **JBL Officer:** JBL visit logging/media upload, read-only `My Submitted Visits`, read-only Orders queue, and no requisition selection, preview, or generation.
  - **Credit Analyst:** credit queue/decision and read-only JBL evidence for review.
  - **IT:** Imports, maintenance, health, and the held private-workspace support functions only.
- An active Django `is_superuser` is an explicitly requested technical break-glass override across Mini App capabilities and Portal branch scope. It remains visibly technical, does not turn ordinary staff into Head of Rural, and actions continue to record the authenticated actor.
- Physical sign-off policies may list one or more Portal roles. Changing that list still requires the existing independent maker-checker process.

## Consequences

- Existing `BUSINESS_ADMIN` grants immediately become the narrower Head of Rural policy once `core.0098_portal_role_separation` is applied; no grant is silently converted to Operations Administrator.
- The migration creates an append-only `WorkflowRoleCapabilityAuditEvent` for every changed role and increments the policy version, so pending policy proposals become stale rather than applying over the new baseline.
- Production operators must review current Head of Rural grants and create maker-checker-approved Operations Administrator grants for staff who genuinely need operational processing.

## Alternatives considered

- Continue using one broad Business Admin role: rejected because approval and operational processing have different conflict-of-interest and least-privilege requirements.
- Rename the database role code: rejected because rewriting historical grants/events would weaken audit continuity.
- Make ordinary Django `is_staff` users Portal superusers: rejected. `is_staff` only enables Django Admin; only active `is_superuser` is a break-glass override.

## Migration and rollback

- Apply in order: `python manage.py migrate core 0098_portal_role_separation`.
- `0097` is conventionally reversible: `python manage.py migrate core 0096_portal_import_archives` before any approved multi-role policy use.
- Do **not** reverse `0098` blindly. It intentionally has a no-op reverse because restoring an unknown historical capability matrix could grant stale access. To undo the policy change, redeploy the prior code and submit an audited maker-checker matrix restoration using the recorded before/after event evidence.
