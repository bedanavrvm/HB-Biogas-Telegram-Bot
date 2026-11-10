# Reviewed workbook amendments

Initial loading and later comparison are separate operations. Keep the initial
upload, committed `LegacyRow.values`, source chunks and pending review rows.
Amendments use `mode=updates` and append `fields_updated` events. They never
replace a register or release an unfinished changeover.

## Cleaning and comparison

`portal_legacy.cleaning` provides value-only helpers for the retained v5 review.
It does not automatically clean arbitrary uploads or authorize workflow actions.
Retain original cells beside cleaned proposals; bind each to its source digest,
register, incoming row, matched case and revision.

- Reuse Original cells, normalization logs and location mapping evidence through
  the matched case's original source row. New physical row positions are not case
  identities. Constituency, sub-county and locality remain separate meanings.
- Done/Commissioned, Pending/Not commissioned and Pending Installation/Open
  compare equally. Staff-label separator spacing is insignificant. Retain a
  reviewed complete name when the source merely shortens it.
- Normalize order references within their HB/ECO register. Payment references
  cannot carry an order prefix. Formatting alone is not an amendment.
- Use Decimal, actual HB plus legacy JBL receipts for Total, and the Not on SF
  exception with no Total. Never infer a receipt from a balance. New blanks do
  not clear existing values. Malformed values and Excel errors stay flagged.
- A partial date supplies no year. It may retain an existing complete date only
  when day and month agree. Unknown milestones remain unknown.
- Preserve historical comments and append distinct source notes once, including
  November comments. Do not attribute an old action to the present importer.
- Later canonical corrections remain unselected even when the workbook also
  changed the field. Resolve conflicts explicitly against the current revision.

## November 10 operation scope

The authorized production operation requires a restorable PostgreSQL dump, an
actual local restore, formula-preserving Sheet snapshots, and a rehearsal with
provider access blocked. Private workbooks, database copies and row manifests
stay outside Git.

For this operation, missing/invalid IDs, repeated incoming IDs and multiple case
candidates remain pending. A known Original-to-Cleaned ID correction requires
retained evidence. Do not fall back to a name/phone match, choose a duplicate, or
create new November cases. One incoming row matching one existing case is normal.

The initial review identified eight eligible Master Data records. The remaining
245 stay pending: 187 missing/invalid IDs, 56 duplicate-ID rows across both
registers, and two names not established by either workbook. A historical order
establishes post-order continuation; conflicting dates and unavailable contacts
remain unconfirmed. No modern approval actor/date, accepted scan, settlement or
signed-order handover follows from that reference.

The newer Eco-conserve workbook contains a shifted financial block. Retained
invoice amounts occur under Discount and payment references under the
installation-date heading. Row-specific repair requires exact agreement with
retained invoice/payment evidence and preservation of the original cells.
Unknown layouts remain flagged. Dates under comment headings do not become
milestones. This is not a general column-shifting heuristic.

## Apply and recovery

Use `updates.apply_row` with reviewed selected fields and an authorized Portal
actor. Native correction, deposit and HB services validate changes. Retain
independent valid fields when another field needs review, recording the rejected
field and native validator reason in the private manifest.

Finance-reference amendments use an amendment-specific allocator audit key. The
initial event survives; a later amendment gets another event; replaying an
applied draft creates none. Occupied/released claims, live finance evidence,
commissioning chronology and completed-installation locks still apply.

Publish initial cases through FIFO upserts and verify remote receipts before
amending them. Publish updates through their reserved canonical operations and
verify each Master Data result. Keep pending rows and the register hold. Never
force Complete or use full-sheet replacement to finish this operation.

Recompare stale revisions before retrying. After later staff activity, recover
through audited corrections instead of restoring all production data. Code
rollback does not undo accepted amendments. This patch has no schema migration.

Focused synthetic regression boundary:

```text
python manage.py test portal_legacy.tests_cleaning portal_legacy.tests_updates portal_legacy.tests_row_sync portal_legacy.tests_review
```

Run financial-reference tests on PostgreSQL: SQLite lacks the financial evidence
guard's JSON containment operation. Tests use synthetic data and fake providers.
