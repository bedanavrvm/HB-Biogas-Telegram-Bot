# Portal Reporting Data Map v1

## Approved source

`core.JawabuFarmerMaster` is the sole v1 report root. Each run uses live,
canonical Django data and the caller's current Portal branch scope.

## Approved field groups

- Customer: case ID, customer name, national ID, primary phone, customer number
- Location: branch, county, constituency/sub-county, village
- Workflow: HBG/JBL visit dates and status, credit/final decisions, current
  pipeline state
- Operations: requisition/order/invoice fields, record status and timestamps
- Finance: HBG/JBL deposit, invoice amount, discount, payment, balance due
- Named safe aggregates: matched-invoice count and successful JBL-media count

The exact client contract lives in `core.services.portal_reporting.PORTAL_REPORT_FIELDS`.

## Deliberately excluded

Raw messages and comments, GPS coordinates, media content, Drive IDs/links,
document scans, audit payloads, integration metadata and arbitrary model fields
are not exposed by the report catalogue.

## Relationship policy

`ParsedInvoice` and `MediaAttachment` are reachable from a Portal case only as
the named count aggregates above. TAT Tracker, SPIN, Complaint Case message/
evidence models and other workflow records do not currently have a safe
canonical case foreign key for reporting. They are listed as identity-only in
the relationship inventory and must never be linked by name, phone, national
ID, or another mutable key.

Inspect the current model topology without reading customer rows:

```text
python manage.py inspect_reporting_relationships --json
```

Any addition to this map needs an ADR that names the data owner, source of
truth, access scope, cardinality/fan-out rule, audit impact, retention policy,
and release/rollback plan.
