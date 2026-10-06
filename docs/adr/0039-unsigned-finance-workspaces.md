# Unsigned finance workspaces

## Context

Generating a workbook is not acceptance of a signed order or payment. Staff
need to amend unsigned orders, cancel mistakes and reuse released numbers
without confusing historical evidence with a different batch.

## Decision

- Batch UUIDs identify workspaces; display numbers identify printed paperwork.
- An accepted signed scan of the exact current version defines finality.
- Unsigned orders may receive explicitly confirmed additions for the same
  group, partner and request date. Every generated version is retained.
- Cancellation releases a number through a locked allocator; counters never
  move backwards. Only numbers explicitly released by the new workflow are
  reusable. Historical cancellations are not automatically recycled.
- Invoice linking and new payment work require an accepted current signed
  order. Historical completed financial evidence is never rewritten.
- Archiving an invoice delivery hides its workspace, not its invoices.
- SysUp review retains the uploaded source and records explicit field choices;
  supplementary system facts do not invalidate pipeline approvals.

## Consequences

Number-only legacy links must reject ambiguous matches. Cancelled and
superseded workbooks cannot accept scans. Allocation, cancellation, appending
and acceptance must use the same transaction locks and revision checks.
Schema rollback after a number has been reused requires reconciliation:
restoring old unique constraints without that reconciliation is unsafe.

## Alternatives considered

Permanently consuming every generated number was rejected by the operational
owner. Rewinding sequence counters loses evidence and risks concurrent reuse.
Silently appending to a daily order was rejected in favour of explicit preview
and confirmation. Deleting deliveries would destroy invoice evidence.

## Operator release and rollback

- Back up the database and review the migration plan before authorizing a release.
  Apply with `python manage.py migrate`: core.0202, requisitions.0003/0004 and
  payments.0005/0006 retain current order bytes, bind exact case assignments and
  bind existing number claims. They do not fabricate signed scans or recycle old
  cancelled work. No Google or Telegram writes occur in these migrations.
- Run `python manage.py audit_finance_order_links --configuration <id>` to inspect
  historical invoice/payment cases lacking an exact signed current order. This
  is read-only and reports UUIDs, not customer names. Resolve legacy ownership
  and accepted paperwork explicitly; never erase completed payment evidence.
- Preview saved Operations permission repair with
  `python manage.py repair_portal_operations_policy`. Only an authorized operator
  may apply it using `--apply --actor <active-superuser-id>`. It adds the approved
  import/invoice capabilities, keeps other denials and staff scopes, records the
  change, and increments the policy version so sessions refresh their access.
  Existing access-control notification behavior applies.
- Before rolling back, stop writes and inspect reused numbers across all orders
  and within each payment group. Preserve the new version/event evidence in the
  backup. If no numbers were reused, reverse in order with
  `python manage.py migrate payments 0004_payment_receipt_batches`,
  `python manage.py migrate requisitions 0002_fulfillment_partner_orders`, then
  `python manage.py migrate core 0201_credit_decision_voice_field`.
  Reversal removes the new evidence tables, so this requires a verified backup.
  Reused numbers deliberately block restoration of old unique constraints;
  reconcile historical display numbering under a separately approved procedure
  or restore the verified backup. Do not bypass the guards.
- Exercise signed/unsigned orders, append, cancel/reuse, invoice linking and
  payment sign-off on PostgreSQL with synthetic data before production release.
  SQLite passing results do not verify row locks or concurrent PostgreSQL behavior.
