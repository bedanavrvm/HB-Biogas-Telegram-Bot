# P0 discovery: Complaints pilot and release baseline

Date: 19 October 2026. Branch observed: `Platform-Interdependence`. HEAD observed: `9612b1ab4a76f0445574996c333171a07fdd99ce`.

Status update: **D1–D3 answered; operational M0 remains open.** The user selected self-managed Django/allauth MFA, browser convenience with possible exit later, and existing Django Complaints grants; confirmed deployed release/migrations unknown; and approved browser MFA first while preserving Telegram. P1a is now a dormant local foundation, not operational admission. Current execution/checklist: codebase-analysis-docs/assets/STAFF_BROWSER_MFA_FOUNDATION.md. Historical P0 evidence below remains explicitly discovery-only.

The three planning Markdown files were already modified when P0 began and were preserved. P0 itself changed no runtime code/schema/dependency/grant/customer record. The later P1a scope is recorded separately; no commit, merge, deployment or real integration operation has been performed.

## 1. Decisions and current evidence

| Item | Current evidence | Required next input/action |
|---|---|---|
| D1: company authentication/MFA | User explicitly selected existing Django users + allauth TOTP/recovery | Name provisioning/recovery/support owners; no credentials in chat/Git |
| D2: business driver | User selected browser convenience, possible exit later | Prove useful Complaints journeys; do not claim continuity/exit readiness |
| D3: Complaint audience | User selected existing Django roles/group scope | Choose exact pilot accounts without adding authority |
| Deployed state | User confirmed unknown; local branch/HEAD only | Inspect actual release/migrations and known incidents before deployment/activation |
| D4/D10: session assurance and origin | Undecided | Approved company-login/session/revocation/CSRF design before P1 |
| D5: first bounded write | Resolution comment proposed, not selected | Complaint owner accepts business need and side effects |
| D11: privacy | Source exposes personal/contact/location/evidence fields; actual flows/contracts not reviewed | Named privacy owner and qualified review where required by driver |
| D12: maintenance | Primary/backup capacity unknown | Name operators and rehearse recovery/containment before production admission |

The user answered D1–D3 and confirmed the unknown deployment baseline. The self-managed choice is explicit, not inferred from branch creation or Google service accounts. Only a dormant local P1a integration proceeds; P2/browser admission remains closed pending accepted authentication, support and release evidence.

**Findings:** local source is available, operational prerequisites are not. **Open questions:** entries above. **Next steps:** finish M0 only after the answers and required baseline evidence exist; do not report P0 or production ready.

## 2. Focused existing endpoint manifest

The project mounts `core/api/urls.py` under `/api/` in `config/urls.py`. The browser `/complaints/` entry is a shell, not an independent login. All surfaces below are **existing Telegram routes**, not newly enabled browser endpoints.

| Method and path | Existing entry/service | Authority and behavior | Proposed pilot treatment |
|---|---|---|---|
| GET `/complaints/` | `core/api/complaint_case_views.py::complaint_cases_app` | Shell rendering; protected data actions authorize separately | Reuse only reviewed UI; no credential bypass |
| POST `/api/complaints/bootstrap/` | `complaint_cases_bootstrap`; `core/services/complaint_cases.py::bootstrap_data` | `_context`, `complaint.queue.view`; counts, actor, preferences, catalogue/location and policy projections | Minimal allowlisted company-browser bootstrap later; do not copy entire data response automatically |
| POST `/api/complaints/cases/` | `complaint_cases_list`; `list_cases_page` | Current actor/group policy; search/status/branch/category and paging; serialized results | P2 candidate query; preserve existing group-wide queue policy |
| POST `/api/complaints/cases/fragment/` | `complaint_cases_list_fragment`; `list_cases_page` | Same query, existing HTML fragment and paging | Frontend dependency; avoid duplicate business logic |
| POST `/api/complaints/cases/<case-id>/` | `complaint_cases_detail`; `case_detail` | Queue access and group lookup; raw-message source field removed when source-view capability is absent | P2 candidate with stricter explicit field projection; preserve current policy |
| POST `/api/complaints/cases/<case-id>/comments/` | `complaint_cases_comment`; `comment_case` | Current `complaint.case.comment`, case lookup, expected revision, actor-bound payload hash and retry key; locked writes, audit, optional Sheet publication | P3 candidate only, via a new CSRF-protected company-session endpoint |
| POST `/api/complaints/cases/<case-id>/sync-retry/` | Existing retry endpoint | Authorized integration recovery with external effects | Exclude until repair contract and owner are reviewed; never call on page refresh |
| POST `/api/complaints/cases/create/` and `finish-created/` | Existing intake/publication endpoints | Creation plus evidence and publication workflow | Excluded from first read/comment pilot; required later if continuity includes new intake |
| Evidence, voice, exports, reports, resolve/reopen/update | Existing owning routes in `core/api/urls.py` | Additional capabilities, protected content, transitions and/or external effects | Explicitly deferred, not implicitly browser-enabled |

### Authentication, request identity and authorization

- `core/api/complaint_case_views.py::_context` gets signed data from `X-Telegram-Init-Data` or the request payload, validates it through `core/services/telegram_identity.py`, resolves the canonical user and selected enabled Complaint group, then builds `staff_actor_for_user`.
- Auth-disabled mode is local/test-only and requires a logged-in active user. It is not a production browser-login mechanism.
- The listed POST views are CSRF-exempt for the existing signed credential and use `miniapp_write_response`. Even query-shaped POST requests pass through existing transport request-identity handling; do not assume a future GET adapter has identical write-key requirements.
- `_capability_error` calls current workflow policy and records capability usage. “Read” does not mean no operational telemetry write.
- A new browser boundary must require approved company-session assurance, framework CSRF on unsafe methods and a real current access context. It calls shared services, never the decorated exempt Telegram HTTP view. No production `access=None` or login-created grants.

### Preserve the actual Complaint scope exception

`core/services/complaint_cases.py::_case_queryset` deliberately shares cases across branches **within the same configured group**. Branch filters in list requests are presentation filters, not a replacement authorization boundary. The existing source test `core/tests_complaint_cases.py::ComplaintCaseServiceTests.test_branch_scoped_grant_still_sees_the_shared_group_queue` captures that behavior; it was inspected, not executed here.

Do not impose a universal “other branch must be hidden” rule on the new read adapter. Current per-action scope rules still apply where supplied by the owning policy; creation, source/evidence access and other actions must be reviewed individually. Any change to this policy needs separate authority, not an accidental change during channel adaptation.

### Read-side effects and field minimization

`serialize_case` calls `ensure_case_control`, which may initialize a control row and allocate/ensure its reference; initialization can resolve catalogue/location/customer links and SLA defaults. Existing history/detail reads therefore cannot be labelled database-write-free. Record the intended compatibility behavior before extracting a query.

`serialize_case` includes name, primary/secondary phone, national ID, location labels, description and source metadata. `case_detail` adds raw message, resolution/history, evidence and location. The current HTTP detail handler strips raw message when `complaint.case.source.view` is unavailable, but its complete payload is not an automatically approved browser disclosure contract.

Proposed P2 projection for review: reference/record locator, status/category/branch, selected timestamps, current revision and approved history facts. Explicitly decide whether names, descriptions or comment text are necessary; exclude national ID, phone, GPS, raw chat, evidence URLs and export payloads by default until approved. This is a **proposal**, not a newly implemented restriction on existing Telegram users.

### Comment command boundary

In inspected `comment_case` source:

1. Resolve the case in its group and require current comment capability. Built-in policy defines HB_STAFF comment authority; current configured policy, scoped IT and active-Superuser rules remain authoritative.
2. Require `client_request_id`, bounded nonempty `comment_text` and valid expected revision. Payload digest includes the actor identity.
3. Under transaction/row locks, recognize an exact replay, reject a conflicting key or stale revision, and reject a new comment on a closed case.
4. Append CaseUpdate, advance ComplaintCaseControl revision, retain unchanged complaint status and record native/compliance actor evidence.
5. Optional voice processing has its own validation/evidence boundary; exclude it from the first browser write unless separately reviewed.
6. If projection is enabled, attempt Sheet publication after canonical commit, then save success/failure status. Local save and failed projection must be presented distinctly; do not resubmit the business comment to repair Google.

No real comment or Google call was made. Source tests to execute in an isolated implementation baseline include append-only/timing preservation, failed-publication local save, API replay/authorization and the PostgreSQL comment-versus-resolution race in `core/tests_complaint_cases.py`.

**Findings:** a reusable source command exists, but the adapter, field contract, initialization effects and live behavior remain unverified. **Open questions:** approved projection, actual group/policy, concurrency and recovery baseline. **Next steps:** confirm prerequisites, then run the bounded functional baseline before any browser implementation.

## 3. Checks actually run in this P0 turn

Interpreter: existing `.venv/Scripts/python.exe`. No dependency installation, database migration or application test run occurred.

| Check | Observed result | What it does not prove |
|---|---|---|
| `scripts/check_architecture_boundaries.py` | Passed; zero legacy API mutation baseline entries | Runtime workflow correctness |
| `scripts/check_miniapp_write_inventory.py` | Passed; 202 reviewed routes | That every route works or accepts company sessions |
| `scripts/check_ui_standard.py` | Passed; legacy ratchet active, candidate UI isolated | Real browser/Telegram behavior or UI approval |
| `scripts/check_migration_graph.py`, default invocation | Stopped at the missing/unsafe default secret-key guard before graph validation | A migration-graph or production defect |
| Same graph check, explicit isolated process settings | Passed; 275 migration nodes, 16 leaves | Production migration application, PostgreSQL locks or schema readiness |

The graph retry used process-local synthetic DEBUG/secret configuration, SQLite `:memory:` and disabled monitoring/provider credential settings. It did not change `.env`, committed settings or operational data. A graph check reads migration metadata; it does not apply migrations. The first failed invocation is retained rather than concealed.

Not run: application test suites, actual company login, PostgreSQL concurrency, full CI, live staging/Telegram-device journeys, production readiness/grant audits, provider calls or privacy/restore drills. These remain future gates, not silently passed items.

**Findings:** narrow source/governance checks pass in the stated local context. **Open questions:** functional and operational baseline. **Next steps:** use an isolated approved test environment when the prerequisite decisions and baseline confirmation are supplied.

## 4. Current merge/deployment checklist

No merge/deployment has been attempted. Use `codebase-analysis-docs/assets/PLATFORM_INDEPENDENCE_RELEASE_CHECKLIST.md` for each handoff; retain completed private operational records outside Git.

- [x] Branch/HEAD and pre-existing planning edits recorded.
- [x] Current work is Markdown only; no runtime endpoints, UI assets, business rules or grants changed.
- [x] No new dependency, environment setting or migration to install/apply.
- [x] Existing source scope and hidden read/publication effects documented.
- [x] Narrow checks recorded with their limitations and initial configuration failure.
- [x] User answered D1–D3 and confirmed deployed baseline unknown; actual release inspection remains required before deployment.
- [ ] Confirm privacy/support owners and applicable first-pilot projection.
- [ ] Obtain any later merge/deployment authorization; a separate branch is not authorization.
- [ ] If this Markdown change is merged, confirm the target branch's automatic-deploy behavior before merging. A merge may trigger a deployment even without runtime source changes.
- [ ] If deployed, follow the existing release record and verify existing authorized Telegram launch/list/detail behavior; no browser login is expected from this change.

Rollback of these P0 files is documentation-only. There is no browser feature to disable, new schema to reverse or customer data to restore. Do not run migration reversal or integration-replay commands for this change.

## STATE BLOCK — P0 evidence / P1a handoff

- INDEX_VERSION: platform-independence-p0-1.
- FILE_MAP_SUMMARY: `core/api/complaint_case_views.py`, `core/services/complaint_cases.py`, `core/services/miniapp_requests.py`, `core/services/workflow_capabilities.py`, `core/services/workflow_access.py`, `core/api/urls.py`, Complaint tests, release template and read-only check scripts.
- OPEN_QUESTIONS: deployed commit/migrations/incidents, session/origin acceptance, first-write approval, privacy/support ownership and operational baseline. D1–D3 answered; actual pilot accounts still to name.
- KNOWN_RISKS: Telegram session fallback/CSRF, group-shared reads mistaken for branch isolation, read-time initialization, overbroad detail payloads, post-commit publication and single-maintainer support.
- GLOSSARY_DELTA: no new persistent domain, role or runtime capability.
- NEXT_READ_QUEUE: P1a evidence and P1b operational provisioning/recovery; then isolated Complaint projection/access tests. No browser admission until M1.
- PHASE_STATUS: discovery evidence retained; operational M0/M1 remain open. Dormant local P1a implemented separately, later apps not started.
