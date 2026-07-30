# JBL Workflow Platform Glossary

Last reviewed: 30-July-2026

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
| Physical document sign-off | An authorised Portal role's attested upload of a scan of a paper-signed and stamped generated workbook. It is not an e-signature or handwriting-verification service. |
| Approval gate | A distinct credit, final-review, or payment-review decision record. It is not inferred solely from the current text shown on a farmer card. |
| Conditional approval | A forward decision that remains ineffective until every separately recorded condition is cleared by an authorised staff member. |
| Approval invalidation | An append-only change of an approval record when a material controlled field changes after the decision. The case requires re-review rather than silently retaining the old decision. |
| Approval delegation | A Portal-Admin-authorised, non-self-granted temporary authority limited to one approval gate, optional branch/product scope, and at most 14 days. |
| Controlled visit evidence | The only Portal forward-visit media categories: LAF and JBL visit photo. New records bind directly to a case and carry a case-reference storage key, content hash, capture context, and retrieval audit. |
| Compliance audit event | Immutable, hash-chained cross-workflow evidence used for investigation. It supplements rather than replaces the detailed event history of Portal, Complaint Cases, TAT, SPIN, and access control. |
| Compliance checkpoint | A daily record of the compliance-audit chain position and hash. Mailbox delivery is disabled unless an authorised operator explicitly enables and runs it. |

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
| `portal.*` | Jawabu Portal | `portal.dashboard.view`, `portal.jbl_visit.write`, `portal.payment.review`, `portal.documents.regenerate`, `portal.documents.sign` |
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
| Signed scan approved | A retained generated workbook has a separately stored PDF/JPG/PNG scan of its physically signed and stamped copy, confirmed by the configured authorised role. |
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
| Sheet register contract | An Admin-managed, publication-only description of a configured Sheet tab: expected headers, row key, and backend/formula/derived/immutable ownership. It is never an inbound import permission. |
| Sheet sync audit | A deliberate read-only comparison of a register contract to the live Sheet. It records header fingerprints and privacy-preserving discrepancies, not raw customer values. |
| Verified TAT duplicate repair | A confirmed, destructive cleanup that re-reads the live Sheet by immutable Case ID after deletion, then re-publishes the canonical survivor. It must not be confused with a dry-run duplicate report. |

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
