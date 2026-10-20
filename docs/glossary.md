# JBL Workflow Platform Glossary

Last reviewed: 20-October-2026

This is the shared vocabulary for the Portal, Complaint Cases, TAT, and SPIN
Mini Apps.  The code catalogues remain authoritative: role validation lives in
`core.services.access_policies`, capability definitions in
`core.services.workflow_capabilities`, and workflow transitions in their
respective service modules.

## Canonical staff access

**Browser MFA assurance:** A server-owned, expiring record that the existing
Django user completed company password and allauth TOTP/recovery authentication.
It is not a workflow grant or an alternative to owning-action authorization.
P1a is dormant and mounts no production company-login or business routes;
Telegram signed-launch access remains unchanged. See
`codebase-analysis-docs/assets/STAFF_BROWSER_MFA_FOUNDATION.md` and ADR 0060.

**Browser admission:** Explicit opt-in and current browser-only revocation
generation for an existing Django staff identity. The active technical Superuser
manages it through the audited lifecycle service; it supplies no workflow grant.
Browser suspension/revocation preserves Telegram and shared Django sessions.
P1b.1 adds backend controls, not usable login. See
`codebase-analysis-docs/assets/STAFF_BROWSER_LIFECYCLE.md` and ADR 0061.

**Company browser boundary:** The separate cookie/CSRF JSON authentication
adapter in `staff_auth/browser_api.py`. Its server-owned channel context and
durable login-audit receipt augment MFA assurance. Future browser business APIs
must use `require_company_browser_user` plus owning-workflow authorization;
neither password-only enrollment state nor a generic Django cookie qualifies.
P1b.2a has no production routes and remains disabled. See
`codebase-analysis-docs/assets/STAFF_BROWSER_JSON_AUTH.md` and ADR 0062.

**Pending enrollment secret:** allauth's temporary TOTP seed, wrapped per browser
request as expiring dedicated-key ciphertext bound to user/admission/revision.
Storage protection is not permission to enroll; no production enrollment API is exposed.

**Browser TOTP use claim:** An expiring shared database record reserving one
native-validated TOTP in the closed company-browser adapter. Its factor-seed
HMAC covers the native-normalized code and factor identity; the table retains
no plaintext code, seed or employee identifier. A claim prevents reuse across
independent native worker caches; it is not MFA assurance or workflow authority.
Live claims must not be evicted. Preview-first expiry cleanup and migration
rollback rules are in ADR 0064 and
`codebase-analysis-docs/assets/STAFF_BROWSER_REPLAY_GUARD.md`. Native shared
rate-limit caching remains an operational prerequisite.

**Closed browser enrollment:** Dormant P1b.2b.1 native TOTP setup for an existing,
explicitly admitted password-only company-browser session, including fresh
password recheck, encrypted pending/permanent seeds, exact factor receipts and
transactional audit. Three relative handlers are test-only mounted, not production
endpoints. Setup never grants browser MFA assurance or business authority;
explicit logout plus a new password/MFA login follows. See ADR 0063 and
`codebase-analysis-docs/assets/STAFF_BROWSER_ENROLLMENT.md`.

**Recovery-code handoff:** One-time native unused-code disclosure during current
closed enrollment. The native viewed marker and nonsecret compliance audit commit
together; retries never re-show/regenerate codes. Lost response means uncertain
delivery and a separate verified support decision, not authorization to retry
disclosure. A working TOTP authenticator remains usable for normal login.

**React browser client:** New standalone presentation layer selected by the user
with Atlassian Design System. Package/transitive/asset licence review precedes
installation. Django still owns identity, grants, workflows and records. Existing
Telegram pages and their separate Design Lab migration hold remain unchanged.
See `codebase-analysis-docs/assets/BROWSER_REACT_ADS_DECISION.md`.

**Browser dependency review snapshot:** D13a's proposed exact manifest, npm
review-only lock and integrity-checked archive/licence/asset metadata. It is
evidence for a human dependency/licence/build decision, not an installed frontend,
production lockfile, legal clearance or new authority. Offline snapshot binding
and synthetic safety tests do not approve installation.

**HB deposit hold:** The Portal's pre-visit HB financial gate: an unrecorded,
zero or below-KES-5,000 cumulative total keeps the case visible but disabled in
the JBL queue. HB staff use HB Actions → Deposits to record/correct totals;
Operations Administrators view only, within Portal scope. Decreases require a
reason and the editor locks after the current cycle's first recorded JBL visit.
FarmUp discrepancies cannot overwrite an HB-owned total. This is not an M-PESA
verification or an individual-receipt ledger. See
`codebase-analysis-docs/assets/HB_DEPOSITS.md` and ADR 0059.

**Origination phone registration check:** An optional, scoped-IT-only confirmed
Daraja check of a saved Applicant phone against the Applicant National ID. Exact
results are reusable across Origination applications for thirty days, without
revealing another application's details. It proves neither handset possession
nor signature/approval authority. The production pilot permits fifty dispatch
reservations per Nairobi day and never automatically retries a paid call.

**Origination Manage documents:** The assigned officer's draft-only Main LAF and
supporting-document chooser. Supporting selection preserves recoverable answers
and captured versions; changing the Main LAF starts a confirmed blank replacement
and cancels the source. Submitted applications use existing withdrawal rules.

**Origination signing-link SMS provider:** The SMS provider retained by one
external signing link for its invitations, verification codes and withdrawal
notices. A new deployment default applies only to newly created links. Delivery
confirmation is not signature verification or application approval.

**Design Lab:** The active-Superuser-only synthetic UI review workspace. A review
revision freezes source/evidence; decisions are append-only. An approved UI
standard release is not deployment or authorisation to migrate an operational
Mini App. Workflow roles remain independent.

**Approved report recipient:** An email destination explicitly permitted to receive
reports for one Mini App, group and its approved branch/product scope. This
approval does not grant Mini App access or transfer to another workflow.

**Scheduled Mini App report:** A recurring report owned by Portal, TAT or
Complaints, sent to that app's approved recipients for a completed Nairobi period.

**Scheduled Portal report:** A recurring Pipeline, Outcomes or Finance report for
one completed Nairobi calendar period, with current-snapshot data clearly
distinguished from period activity.

**Complaint resolution comment:** HB feedback saved while a complaint remains
open. Comments retain their actor and timestamp separately from resolution
details. Queue badges count all comments, not unread comments; saving feedback
does not resolve the case or restart its SLA.


| Term | Meaning |
|---|---|
| `User` | Django's canonical staff account. Telegram-only staff normally have an unusable password; separately approved Admin or future company-browser provisioning may establish a password without creating a second staff identity or business grants. |
| `UserProfile` | One-to-one Telegram identity record: immutable bound `telegram_id`, mutable `telegram_username`, phone, and Telegram metadata. |
| `AccessGrant` | A user-specific workflow/role/scope assignment. It may restrict branch, product, or group configuration. It does not itself invent a capability. |
| Capability | A stable code-controlled permission such as `portal.jbl_visit.write`. Policies decide which roles receive existing capabilities. |
| Effective access | The intersection of an active user's scoped grants/emergency grants and the approved role-capability policy. |
| Emergency access | A separately audited, reason-required grant that expires automatically. It is not a substitute for a permanent AccessGrant. |
| Physical document sign-off | An authorised Portal role's attested upload of a scan of a paper-signed and stamped generated workbook. It is not an e-signature or handwriting-verification service. |
| Approval gate | A distinct credit, final-review, or payment-review decision record. It is not inferred solely from the current text shown on a farmer card. |
| Conditional approval | Retired Portal decision type. New Credit and Head of Rural decisions must be Approved, Deferred, Rejected, or the existing supported exception path; a cached client submitting a conditional decision is rejected. Historical audit structures remain readable. |
| Approval invalidation | An append-only change of an approval record when a material controlled field changes after the decision. The case requires re-review rather than silently retaining the old decision. |
| Approval delegation | A Portal-Admin-authorised, non-self-granted temporary authority limited to one approval gate, optional branch/product scope, and at most 14 days. |
| Controlled visit evidence | The only Portal forward-visit media categories: LAF and JBL visit photo. New records bind directly to a case and carry a case-reference storage key, content hash, capture context, and retrieval audit. |
| Compliance audit event | Immutable, hash-chained cross-workflow evidence used for investigation. It supplements rather than replaces the detailed event history of Portal, Complaint Cases, TAT, SPIN, and access control. |
| Compliance checkpoint | A daily record of the compliance-audit chain position and hash. Mailbox delivery is disabled unless an authorised operator explicitly enables and runs it. |
| Mini App retry key | A client-generated request identity sent in `Idempotency-Key`/`X-Request-ID` and the payload. It makes a mobile retry traceable; legacy clients are marked until strict mode is approved. |
| Integration operation | A redacted local record of a Sheets, Drive, or Telegram side effect, its bounded attempts, outcome, and retry/dead-letter state. It is not an automatic background job. |
| Integration circuit | A persisted dependency safety state. It opens after repeated transient failures and blocks further calls during a short cooldown before one recovery probe. |
| Portal import staging | Capability-scoped FarmUp/SysUp review retaining the uploaded source in `JawabuFarmerUploadBatch`. Authorized Operations/IT staff commit explicitly selected matches with source fingerprints and case/upload revisions; corrected values and Keep Portal/Use SysUp choices are audited. |
| Unsigned order workspace | A UUID-identified generated order, not yet locked by an accepted signed scan. Explicit additions require the same group, partner and request date; each generated workbook version is retained. |
| Released finance number | An allocator slot released by confirmed unsigned cancellation. Its next owner has a different UUID; the counter never rewinds and old evidence remains. Ambiguous number-only links are rejected. |
| Archived invoice delivery | A hidden payment-preparation workspace. Archive/restore retains its invoice rows and PDFs; it does not ignore or delete invoices. |
| Import archive | The restricted Drive retention copy of a staged FarmUp/SysUp source. It is retried through a durable integration operation and its Drive URL is never exposed in the Mini App API. |
| Portal import working-list archive | An IT-recorded action that removes a staged import from the active Imports list while retaining its raw source, parser review data, Drive archive state, and immutable audit evidence. It is distinct from the Drive import archive. |
| Mini App preference | A user-owned, validated setting for one Mini App (landing screen, saved filters, compact cards, and non-critical alert intent). It never grants workflow access. Preferences apply only to catalogue-listed informational/digest alerts, never to security/access, assignment, approval/rejection, or SLA-overdue-breach alerts. |
| Business Admin | A scoped operational role (`BUSINESS_ADMIN`) used for high-impact workflow authority. It is distinct from Django `is_staff` and `is_superuser`; neither technical flag grants Mini App access. |
| IT | A scoped Mini App support role (`IT`) available in Portal, Complaint Cases, TAT, and SPIN. It is not inferred from Django `is_staff` or `is_superuser`; every workflow still requires its own explicit `AccessGrant` and approved capabilities. |
| Portal maintenance mode | An IT-only temporary Portal read-only state. It blocks newly admitted Portal writes with a safe message while reads and requests already inside a view can finish. It is not a general outage flag or a bypass of normal access control. |
| JBL to Schedule Visit | A FarmUp-created operational handoff after an HBG visit is available and before a JBL officer records a real visit outcome. It is a queue status, not an officer-selectable completed-visit result. |
| Current Pipeline State | A Django-derived Master Data summary of the case's present operational state. It complements, but never overwrites, historical JBL visit, Credit, and Head of Rural columns. |
| Access Control Checker | An active Django Admin staff user appointed by a technical Superuser to independently approve or reject Mini App access-policy requests. This is not a Mini App role or capability. |
| Staff lifecycle plan | A durable, revision-checked ordinary-staff change. An active Django Superuser applies it directly by default, or explicitly sends it to the Staff approvals queue for an independent checker decision. |
| Bootstrap override | The audited, reason-required exception allowing a sole active Django Superuser to approve their own access-policy request only while no independent checker or different Superuser exists. It ends as soon as an independent reviewer exists. |
| Django Superuser Access Grant override | The audited, immediate technical-admin path for an active Django `is_superuser` to create, edit, activate, deactivate, or delete a staff `AccessGrant`. It never grants that Superuser Mini App access by itself and does not extend to capability-matrix or document-signoff policy changes. |
| TAT configuration proposal | A reasoned, snapshot-based maker-checker request for TAT targets, future holidays, or escalation rules. IT proposes; a different authorised TAT Business Admin reviews it. |
| TAT responsibility roster | A scoped primary-and-ranked-backup routing policy for private TAT tasks. The canonical stage selects the role, while `AccessGrant` independently determines who may act; assigning responsibility never grants access. |
| Stage target snapshot | The TAT target captured when a case enters a stage. It protects an in-flight SLA calculation from later target changes. |
| Portal report definition | An IT-owned, versioned configuration that can select only fields and chart operations from the server-owned Portal catalogue. It runs against live canonical Django case data and never permits arbitrary SQL, ORM paths, cross-workflow identity matching, Drive/Sheets output, or report-source snapshots. |

## Workflow keys and role codes

| Workflow key | Mini App | Canonical role codes |
|---|---|---|
| `jawabu_portal` | JBL/Jawabu Pipeline Portal | `JBL_OFFICER`, `CREDIT_ANALYST`, `HB_STAFF`, `IT`, `BUSINESS_ADMIN` |
| `complaint_cases` | Complaint Case Mini App | `OFFICER`, `MANAGER`, `IT` |
| `tat_tracker` | TAT Tracker | `BRO`, `BUSINESS_ADMIN`, `CA`, `BM`, `SECRETARY`, `CHAIR`, `LOAN_APPROVER`, `FINANCE`, `IT`, `MANAGEMENT` |
| `spin_credit_analysis` | SPIN / Credit Analysis | `CREDIT_ANALYST`, `IT`, `BUSINESS_ADMIN` |

Role codes are workflow-scoped. `BUSINESS_ADMIN` is a business authority,
never a blanket Django-superuser permission, and must be explicitly granted
for each workflow/scope. Historical evidence may display legacy `ADMIN` where
that was the original recorded code.

## Capability naming

Capabilities follow `<miniapp>.<module>.<action>`. Add a definition only in
`core.services.workflow_capabilities`; do not hard-code a new string in a view
or template.

| Prefix | Scope | Examples |
|---|---|---|
| `portal.*` | Jawabu Portal | `portal.dashboard.view`, `portal.jbl_visit.write`, `portal.payment.review`, `portal.documents.regenerate`, `portal.documents.sign`, `portal.imports.view`, `portal.workspace.manage`, `portal.reports.view`, `portal.reports.manage` |
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
| Exact invoice duplicate | Another invoice with the same identity, invoice details and financial values. Shared IDs, phone numbers or invoice numbers alone indicate similar details, not a duplicate. |
| Invoice-name agreement | Private, immutable signed/agreed copy of the exact sent correction letter. It clears the unchanged correction's identity hold, not financial checks or payment approval; the corrected invoice remains an outstanding follow-up. |
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
| TAT remark | An append-only staff note with actor, applicable TAT roles and saved time. It may be added to a finished case but never advances stages, changes timing or contributes a scored action. |
| Timeline annotation | An append-only authorised correction, artifact link, or redaction record. It never edits or deletes the source event. |
| Customer identity resolution | Matching a Jawabu case to a canonical customer using one exact national ID, customer number, or current/historical phone. Name similarity only produces a review candidate. |
| Origination Applicant | Person or entity applying for a loan. Applicant is the standard operational label before execution. |
| Origination signing acknowledgement | The short agreement confirmed by a signer for the exact application documents and required approval. Historical signing requests retain their original agreement. |
| Origination application copy | A downloadable document bundle: clearly unsigned before approval, or the exact signed application after approval. Downloading never grants approval. |
| Origination typed mark | A versioned server-rendered handwriting image bound to the confirmed name, style and preview hash. It is appearance, not independent proof of identity; the verified signing action supplies that evidence. |
| Origination identity copy | An optional complete ID PDF bound to a saved borrower or guarantor identity under the captured collection policy. A later identity change flags the earlier copy without deleting evidence. |
| Origination Customer | The canonical global customer identity optionally matched to an Origination Applicant; it is not a generic form-role synonym. |
| Origination Borrower | Contractual obligor or signer named in legal documents. The role may refer to the same person as the Applicant but has a distinct legal meaning. |
| Origination Party | Collective term for the Applicant, guarantors, spouse, and other document participants. |
| Origination value contract | Versioned meaning of a canonical field: its subject, ownership, units, reporting period and allowlisted value source. Legacy applications retain their original meanings. |
| Origination shared value | One application-owned value reused by selected documents; distinct document-instance inputs never overwrite it. |
| Origination person-role binding | Explicit confirmation that a spouse, next of kin or referee occupies a document-defined guarantor slot. It is not automatic identity matching or signing authority. |
| Origination LAF bootstrap | One-time, opt-in release preparation of reviewed blank PDFs as unassigned document drafts. A durable fingerprint survives deletion; explicit force is required to recreate completed seeds. |
| Permanent selected-product deletion | Testing-gated physical deletion of explicitly selected global products and their Origination history, not catalogue tombstone removal. Other workflow references block; shared catalogue, identity, compliance and external evidence survive. |
| Data-quality issue | An active warning about a canonical Jawabu value or controlled reference value. It is resolved through an append-only staff resolution record. |
| Field provenance | The append-only source, timestamp, actor, and before/after values for a cross-system customer field update. |
| Sheet register contract | An Admin-managed, publication-only description of a configured Sheet tab: expected headers, row key, and backend/formula/derived/immutable ownership. It is never an inbound import permission. |
| Sheet sync audit | A deliberate read-only comparison of a register contract to the live Sheet. It records header fingerprints and privacy-preserving discrepancies, not raw customer values. |
| Verified TAT duplicate repair | A confirmed, destructive cleanup that re-reads the live Sheet by immutable Case ID after deletion, then re-publishes the canonical survivor. It must not be confused with a dry-run duplicate report. |

Use `Pending` for work not yet decided. Do not substitute an ambiguous visual
label such as “in review” for a server-side state.

## UI status semantics

**Origination signing plan**: The required people and document-signing obligations
for one loan application. Under the configurable policy, all required signers
complete approval, regardless of signing order.

**Signing participant**: One identified person responsible for one or more
document signature placements. A role identifies their capacity; repeated
placements do not create additional people.

| Semantic status | Meaning | Shared treatment |
|---|---|---|
| Informational | Neutral contextual state | Brand/info color |
| Success | Completed or valid action | Green |
| Warning | Needs attention but is not blocked | Amber |
| Error/blocked | Failed, denied, or cannot proceed | Red |

These meanings are shared by `base.css` across Mini Apps. A badge or icon must
not reverse these meanings in an individual app.
