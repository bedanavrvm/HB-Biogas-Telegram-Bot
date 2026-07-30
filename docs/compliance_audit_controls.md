# Compliance audit control evidence map

This is a technical control/evidence map for JBL operations. It is **not** a
legal opinion or a statement of CBK/DPA compliance. Have the final mapping and
retention schedule reviewed by JBL's compliance/legal adviser before presenting
it to an examiner.

| Control objective | Implemented evidence | Operator check |
|---|---|---|
| Append-only audit evidence | `ComplianceAuditEvent`, Django read-only Admin, PostgreSQL immutability trigger | `python manage.py verify_compliance_audit --strict` |
| Who/what/when and before/after | workflow/action, actor/authority, origin, request ID, subject, timestamps, before/after JSON | Search **Compliance audit events** in Django Admin |
| Sensitive-record access | Portal media access, sign-off actions, audit ledger search/view/export events | Filter Admin by `Sensitive = Yes` |
| Cross-workflow investigation | Portal, Complaint Cases, TAT, SPIN adapters use one ledger taxonomy | Filter by subject, customer reference, actor, action, or date |
| Evidence export | Authorized CSV/PDF exports with a corresponding audit event | Grant `core.export_complianceauditevent` deliberately; retain export ticket |
| Tamper-evidence | Hash-chain position/hash plus daily checkpoint records | Create locally: `python manage.py checkpoint_compliance_audit --apply` |
| Independent checkpoint delivery | Explicit mailbox configuration and `--apply --deliver` only | Keep disabled until recipient, mail service, owner, and escalation runbook are approved |
| Periodic self-audit | Read-only sensitive-event sampling command | `python manage.py sample_compliance_audit --strict` |
| Retention | All new ledger events are `legal_hold`; no automatic deletion | Do not add deletion jobs before approved schedule and ADR |

## Clock and source conventions

Django stores timezone-aware timestamps and displays them in `Africa/Nairobi`.
Every ledger event identifies a human, system, or external-sync origin. An
external system timestamp is evidence supplied by that source; the ledger's
`recorded_at` remains Django's receipt time. Sheet and IMAB clock reconciliation
is an operational control still requiring documented source-system ownership.
