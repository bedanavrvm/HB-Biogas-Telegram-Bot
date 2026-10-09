# Selected Mini App testing deletion

Testing requires removing selected records across Origination, Portal, Complaints,
TAT and SPIN without performing a group reset. An opt-in active-Superuser action
uses a reviewed ownership registry and a signed, expiring impact confirmation.
Keep-history mode retires in-use configuration; delete-linked mode removes the
explicitly disclosed closure, including the owner of selected signing evidence.
Unknown relationships block rather than enlarge deletion. No manual note is needed.

All row values and surviving detached references bind the confirmation fingerprint.
Exact rows are locked and the impact recomputed before mutation. Deletion, work
cancellation, independent compliance evidence, publication tombstones and cleanup
reservations commit together. Confirmation requests are actor/selection-bound and
idempotent. The transaction bypasses immutable model hooks only inside this boundary.

## External projections and protected records

Django deletion does not wait for Google. A bounded server-side wake performs
durable Sheet cleanup after commit; failed or interrupted work is retried explicitly
in Integration operations. No cron is added. Cleanup identifies rows only by their
immutable case/request/message reference and verifies removal. Missing or conflicting
IDs require repair, never a guessed customer-name/phone match. A shared DB mutex
serializes cleanup with the guarded publication entry points. Staff edits in Google
remain outside that mutex; pause concurrent manual row editing during cleanup.

Drive files, shared customer/related-person identities, access grants, raw ingestion,
final recognition facts, finance sequences and independent compliance evidence survive.
Deleting a shared order/payment member may require deleting its entire evidence-owning
workspace: the preview must disclose that expansion. Post-order evidence can also
include its owning cases; every affected case is disclosed before confirmation.
Surviving cases are detached only on explicitly reviewed nullable edges.
Number claims are retired, never released for reuse;
explicit operational cancellation remains the sole number-release path (ADR 0039).
Historical aggregate metrics and captured recognition snapshots are not rewritten.

## Release and rollback

Default `MINIAPP_TEST_DELETION_ENABLED=False`. Enable only intentionally for testing,
back up first and review the confirmation. The existing narrower permanent-product
action retains its separate gate and policy. Apply payments.0008 and requisitions.0005
with `python manage.py migrate` before enabling this action; neither migration calls
external providers. Turning the flag off hides and rejects new confirmations but does
not discard already committed cleanup tasks or publication tombstones.

Code rollback must preserve cleanup operations and tombstones. Before any schema
reversal stop finance writes and inspect retired number claims. Reversing the retired
fields after deletion makes those claims reusable by older allocators and is unsafe.
Only when no retired claims exist may an authorized operator reverse payments to
0007_invoicenameagreement and requisitions to 0004_bind_order_workspaces. Deletion is
not reversible by a migration: recover canonical records from a verified backup.
