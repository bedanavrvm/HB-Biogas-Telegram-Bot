# ADR 0021: Controlled Portal Reporting v1

**Status:** Accepted for merge and local/staging validation only; production
migration application requires separate explicit release approval.

## Context

The Portal needs operational reports and graphs without introducing a second
deployment, an unrestricted SQL/ORM interface, or unsafe joins between
workflows that currently share mutable customer identifiers rather than a
canonical foreign key. Staff use Telegram Mini Apps on mobile connections, so
the implementation must be local, bounded, auditable, and compatible with the
existing Django/Alpine stack.

## Decision

1. Reporting is a shared Portal service in this repository, initially exposing
   only the canonical `JawabuFarmerMaster` source.
2. The browser chooses only keys from a server-owned reporting catalogue. Raw
   comments/messages, GPS, Drive links/identifiers, media, scans and audit JSON
   are not reportable fields. TAT, SPIN and Complaint Case records are not
   joined through names, phones, or national IDs.
3. `PortalReportDefinition` and `PortalReportChart` keep a versioned,
   validated report configuration. Running a report always reads current
   canonical case data; it does not change a case, publish a register, or
   create a data snapshot.
4. `portal.reports.view` and `portal.reports.manage` are seeded as explicit
   Portal IT-only capabilities. Report definition and run/export actions write
   append-only compliance-audit evidence and respect the established technical
   Django Superuser break-glass policy.
5. The Mini App uses a vendored, pinned Chart.js 4.5.1 build for in-app bar,
   doughnut and line charts. XLSX is the only v1 export. PDF/printing and
   Drive/Sheets delivery are intentionally out of scope.
6. `inspect_reporting_relationships` is a read-only command that inventories
   Django model relations. It documents future expansion; it is not a dynamic
   query or join planner.

## Consequences

- IT has a useful controlled reporting surface without a new web service,
  external dependency at runtime, or Google side effect.
- A future data source, field, join, scheduled delivery or document output
  needs its own source-owner review and ADR/release decision.
- Report outputs are live and can change as cases change. This is intentional;
  a future immutable report snapshot needs separate storage and retention
  controls.

## Alternatives considered

- **Generic query/SQL builder:** rejected because it could disclose sensitive
  fields, create unsafe joins, and be difficult to audit.
- **Separate reporting service:** rejected for v1 because this single Django
  repository and free Render operating model do not justify another deployment.
- **Runtime CDN or hand-built canvas charts:** rejected for field-connectivity
  reliability and maintenance risk respectively.
- **PDF/`window.print()`:** rejected because Telegram Android WebView printing
  is unreliable; XLSX remains the operational export format.

## Migration and rollback

`core.0099_portal_reporting` is authorised only for merge and local/staging
validation under this ADR. It does **not** authorise a production migration or
deploy. A named release approver must separately authorise the production
application.

To undo a non-production application before report definitions are in use,
run:

```text
python manage.py migrate core 0098_portal_role_separation
```

This reverses only the report schema. Its reverse policy seed is intentionally
a no-op: policy and compliance-audit evidence are append-only. Do not blindly
reverse the migration after production use; restore prior code/policy through
the audited access-control process and preserve evidence.
