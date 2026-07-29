# JBL Workflow Platform Glossary

Last reviewed: 29-July-2026

This is the shared vocabulary for the Portal, Complaint Cases, TAT, and SPIN
Mini Apps.  The code catalogues remain authoritative: role validation lives in
`core.services.access_policies`, capability definitions in
`core.services.workflow_capabilities`, and workflow transitions in their
respective service modules.

## Canonical staff access

| Term | Meaning |
|---|---|
| `User` | Django's canonical staff account. It is active for Telegram-only staff, with an unusable password unless Django Admin login is explicitly granted. |
| `UserProfile` | One-to-one Telegram identity record: immutable bound `telegram_id`, mutable `telegram_username`, phone, and Telegram metadata. |
| `AccessGrant` | A user-specific workflow/role/scope assignment. It may restrict branch, product, or group configuration. It does not itself invent a capability. |
| Capability | A stable code-controlled permission such as `portal.jbl_visit.write`. Policies decide which roles receive existing capabilities. |
| Effective access | The intersection of an active user's scoped grants/emergency grants and the approved role-capability policy. |
| Emergency access | A separately audited, reason-required grant that expires automatically. It is not a substitute for a permanent AccessGrant. |

## Workflow keys and role codes

| Workflow key | Mini App | Canonical role codes |
|---|---|---|
| `jawabu_portal` | JBL/Jawabu Pipeline Portal | `JBL_OFFICER`, `CREDIT_ANALYST`, `HB_STAFF`, `ADMIN` |
| `complaint_cases` | Complaint Case Mini App | `OFFICER`, `MANAGER` |
| `tat_tracker` | TAT Tracker | `BRO`, `ADMIN`, `CA`, `BM`, `SECRETARY`, `CHAIR`, `LOAN_APPROVER`, `FINANCE`, `IT`, `MANAGEMENT` |
| `spin_credit_analysis` | SPIN / Credit Analysis | `CREDIT_ANALYST`, `ADMIN` |

Role codes are workflow-scoped. For example, `ADMIN` in the Portal is not a
blanket Django-superuser permission and must not be assumed to grant access to
another workflow.

## Capability naming

Capabilities follow `<miniapp>.<module>.<action>`. Add a definition only in
`core.services.workflow_capabilities`; do not hard-code a new string in a view
or template.

| Prefix | Scope | Examples |
|---|---|---|
| `portal.*` | Jawabu Portal | `portal.dashboard.view`, `portal.jbl_visit.write`, `portal.payment.review`, `portal.documents.regenerate` |
| `complaint.*` | Complaint Cases | `complaint.queue.view`, `complaint.case.create`, `complaint.case.update`, `complaint.case.manage` |
| `tat.*` | TAT Tracker | `tat.home.view`, `tat.case.create`, `tat.case.correct`, `tat.stage.<stage>.update` |
| `spin.*` | SPIN / Credit | `spin.request.view`, `spin.request.create`, `spin.request.review`, `spin.request.complete` |

`view` controls an entry point; a related write capability must declare its
required view capability. Dependencies are resolved server-side before a policy
request can be approved.

## Workflow-stage language

| Term | Meaning |
|---|---|
| Application | Initial client/case intake. |
| HBG visit | HomeBiogas field assessment. |
| JBL visit | JBL follow-up visit; it cannot be dated before a recorded HBG visit. |
| Credit | Credit analysis and decision stage. |
| Final review | Head of Rural decision before order/requisition or a separate payment review. |
| Requisition/order | Approved cases grouped under an order number and requisition date. |
| Invoice | Supplier/customer invoice parsing, review, matching, and confirmation. |
| Payment review/final | Per-case Head of Rural payment call-up review followed by a generated payment schedule. |
| Deferred | A paused case. A deferred application must be reappraised after the configured maximum deferral period. |
| Workflow revision | Monotonic case version returned to a Mini App. A write must include the version it read; a newer stored version causes a refresh-and-review conflict instead of a lost update. |
| Workflow transition | A validated movement between responsible workflow states. It records source, target, actor, authority, reason where required, and before/after revisions. |
| Workflow correction | A restricted, append-only correction of completed-stage or base-case data. It is not a normal stage transition. |
| SLA escalation | A pending operational alert created after a configured stage target is exceeded. It never automatically approves, rejects, or moves a case. |
| Official SLA time | Mon–Fri, 08:00–17:00 Africa/Nairobi, excluding active Admin-managed `BusinessCalendarHoliday` dates. It is the measure used for SLA status and escalation. |
| Wall-clock time | Actual elapsed time between two timestamps. It remains visible as supporting context and does not replace official SLA time. |
| Responsible actor | The explicitly recorded staff member responsible for a stage when the source workflow has that information. Blank attribution means a metric remains role/branch-level and must not be read as an individual performance score. |
| Unified timeline | A read-only case-history projection joining immutable events, field provenance, decisions, documents, and append-only annotations in chronological order. |
| Timeline annotation | An append-only authorised correction, artifact link, or redaction record. It never edits or deletes the source event. |
| Customer identity resolution | Matching a Jawabu case to a canonical customer using one exact national ID, customer number, or current/historical phone. Name similarity only produces a review candidate. |
| Data-quality issue | An active warning about a canonical Jawabu value or controlled reference value. It is resolved through an append-only staff resolution record. |
| Field provenance | The append-only source, timestamp, actor, and before/after values for a cross-system customer field update. |

Use `Pending` for work not yet decided. Do not substitute an ambiguous visual
label such as “in review” for a server-side state.

## UI status semantics

| Semantic status | Meaning | Shared treatment |
|---|---|---|
| Informational | Neutral contextual state | Brand/info color |
| Success | Completed or valid action | Green |
| Warning | Needs attention but is not blocked | Amber |
| Error/blocked | Failed, denied, or cannot proceed | Red |

These meanings are shared by `base.css` across Mini Apps. A badge or icon must
not reverse these meanings in an individual app.
