# Analysis state and continuation ledger

## STATE BLOCK — Phase 1 complete

- INDEX_VERSION: `1`, source commit `f9b1e8a97cf98b1e6c79927bd0ee7ce46c2ddcc2`; hashes are SHA-256 of exact file bytes.
- FILE_MAP_SUMMARY: first 50 ranked rows in `codebase-analysis-docs/assets/FILE_INDEX.md` (explicit source paths, classifications, line counts, hashes, import counts). Total indexed: 1,455; Python parsed without syntax errors. Metadata is indexed more broadly than code is read.
- OPEN_QUESTIONS: deployed migration state and provider configuration cannot be established from Git; verify actual enablement of newer credit-assessment and reporting features; distinguish runtime model ownership from compatibility imports.
- KNOWN_RISKS: sensitive operational artifacts exist in the repository; do not reproduce their contents. `core` includes very large, highly coupled modules. Root-level historical documentation can contradict implementation. Static route/model counts include declarations, not necessarily distinct deployed endpoints/tables.
- GLOSSARY_DELTA: bounded domain; canonical workflow state; publication reservation; workflow-scoped AccessGrant; frozen application/signing snapshot; physical finance sign-off.
- NEXT_READ_QUEUE: identity/access and retry boundary; webhook dispatch; integration-operation leases/publication; feature services and boundary tests; financial finality; versioned TAT/Origination; generated catalog and migrations.

## Phase 1 findings

The application is a staff operations platform for JBL/Jawabu Biashara Limited and HomeBiogas financing. Telegram provides ingestion, identity, launch links and alerts; Django owns operational workflow state. Google Sheets and Drive supply operational registers and protected artifacts. Field officers, analysts, branch managers, Operations Administrators, Head of Rural, HB staff, scoped IT staff and technical Superusers have distinct authority.

The runtime is a Django modular monolith using Python 3.12 and Django 5.2.17 as pinned in `requirements.txt` and `pyproject.toml`. `config/urls.py` mounts canonical APIs under `/api/`, browser entry points at root, explicit legacy aliases, Django Admin, health checks and a gated design lab. `config/settings.py` installs 11 local applications: core, origination, requisitions, payments, credit_assessments, hb_operations, qa_tracker, tat_recognition, portal_recognition, report_delivery and ui_review.

Feature families: complaints intake/resolution and evidence; customer/farmer intake and FCA; Portal visit/credit/final approval; requisitions/invoices/payment batches; post-order HB installation/commissioning; SPIN credit requests; product/version/location governance; TAT stages, responsibilities, SLA, notifications and recognition; Origination documents/forms/signing/approval; staff/access lifecycle; reports/email; audit, reliability, release and internal QA/design tooling.

Build (`build.sh`), schema release (`release.sh`) and serving (`start.sh`) are explicitly separated. The app serves Django templates and local JavaScript/CSS without a frontend build server. Frontend tooling provides syntax checks, Node contracts and Playwright tests. PostgreSQL-specific behavior is covered by a separate CI job; SQLite is used by the ordinary CI job. These statements describe checked-in configuration, not observed production.

### Decisions/Findings

Follow current implementations and tests. Use legacy Origination imports only as compatibility evidence; implementation ownership is under `origination`. Keep all outputs in the requested analysis folder.

### Open Questions

Production state is outside this source-only investigation. Remaining source questions are tracked above and resolved in later state blocks.

### Next Steps

Complete the architecture pass before feature-by-feature interpretation; retain a separate mechanical source inventory and human interpretation.

## STATE BLOCK — Phase 2 complete

- INDEX_VERSION: `1`; phase 1 source index and first 50 ranked files remain unchanged.
- FILE_MAP_SUMMARY: `codebase-analysis-docs/assets/FILE_INDEX.md`, first 50 rows; backbone additionally inspected: `core/services/telegram_identity.py`, `workflow_access.py`, `workflow_capabilities.py`, `miniapp_requests.py`, `workflow_transitions.py`, `external_resilience.py`, `portal_publication.py`, `workflow_data_mode.py`, `compliance_audit.py`, `sheet_columns.py`, `storage.py`; `origination/auth.py`; browser/API/legacy routing.
- OPEN_QUESTIONS: feature-specific finality, enablement and correction behavior; exact compatibility edges; live provider/deployment state remains unavailable.
- KNOWN_RISKS: request-key binding is not itself business deduplication; local/test authentication bypass must not be treated as production authority; a resource must match one complete grant tuple; stale publication operations are superseded; old Pilot cycles are read-only; legacy parser deduplication does not include group in its hash input.
- GLOSSARY_DELTA: complete grant tuple; optimistic workflow revision; fenced execution lease; terminal/dead-letter operation; named Sheet column; production-plus-active-pilot visibility.
- NEXT_READ_QUEUE: complaints creation/mutation; Portal pipeline and imports; order/payment sign-off; TAT version binding and credit assessment; Origination snapshots/signing; auxiliary reporting/QA; tests and migrations.

Architecture sources are stored in `codebase-analysis-docs/assets/architecture.mmd`, `write-publication.mmd` and `business-flow.mmd`. The business-flow diagram shows conceptual interaction; SPIN does not automatically create a TAT case, and Origination does not inherit Portal authorization. Feature analysis must preserve these distinctions.

## STATE BLOCK — Phase 3 complete

- INDEX_VERSION: `1`; source commit and hashes unchanged.
- FILE_MAP_SUMMARY: first 50 files in `codebase-analysis-docs/assets/FILE_INDEX.md`; expanded to finance/domain services, TAT configuration/transitions/tasks, Origination creation/submission/signing/documents/SMS, credit assessment/mailbox, reports, lifecycle, QA and Design Lab. Module/model/route/test inventories retain exact symbols and source locations.
- OPEN_QUESTIONS: live flags and provider state remain unverified; no source ambiguity blocks documentation. Future implementation must choose the captured Origination policy, not assume a universal sequence.
- KNOWN_RISKS: complaint Telegram/batch intake is retired; Order Approval is code-fixed archived; SPIN cutover and credit-assessment gates are independent; old direct grant override raises while direct Superuser lifecycle remains supported; Portal conditional approval is retired, unlike historical Origination conditional packet policy.
- GLOSSARY_DELTA: order UUID versus reusable display number; payment-facts review digest; signed invoice-name agreement; document-owned unsigned completion; source-pinned signing provider; captured versus live catalogue configuration.
- NEXT_READ_QUEUE: confirm nuanced compatibility/deletion/timing contracts and validation findings; assemble schema/API reference and final knowledge document.

## STATE BLOCK — Phase 4 complete

- INDEX_VERSION: `1`; source baseline unchanged.
- FILE_MAP_SUMMARY: top 50 in FILE_INDEX plus `sheet_sync.py`, `tat_comments.py`, `invoice_processing_limits.py`, `payments/invoice_agreements.py`, `access_control.py`, `staff_lifecycle.py`, `workflow_recognition.py`, `report_delivery/dispatch.py` and governance checks.
- OPEN_QUESTIONS: production performance, scheduler coverage and provider correctness cannot be concluded from source/local checks.
- KNOWN_RISKS: shared helpers can accept permissive local access context; legacy dedupe omits group; remarks intentionally avoid workflow revisions/timestamps; hash-bound finance/signing artifacts cannot follow mutable source. Architecture check reports one existing OrderWorkspaceEvent write in Portal view. Source catalogue check is stale in usage/writer metadata. Local venv lacks cryptography; ordinary Django URL checks cannot load.
- GLOSSARY_DELTA: best-effort wake-up versus durable scheduler; accepted SMS versus verified signature; activity period versus current snapshot; source/scan hashes are different artifacts.
- NEXT_READ_QUEUE: finalize documented APIs, relationship diagrams, safe test commands and confidence/assumption tables.

## STATE BLOCK — Phase 5 complete

- INDEX_VERSION: `1`; static inventories now include MODULE_REFERENCE, TEST_REFERENCE and DATABASE_DOMAINS alongside raw source/model/route/settings/import inventories.
- FILE_MAP_SUMMARY: first 50 ranked FILE_INDEX entries are the stable file map; domain ER sources are core-relationships.mmd, origination-relationships.mmd and tat-relationships.mmd under the analysis assets directory.
- OPEN_QUESTIONS: no live API traffic, financial records, customer database contents, external files or signed payloads were used as examples.
- KNOWN_RISKS: static model declarations include abstract classes; routes are local declarations, not expanded method contracts. Runtime loaded catalogue has 209 entries; migration graph has 271 migrations including framework migrations. Current catalogue drift affects usage/writer metadata for seven model entries, not demonstrated schema drift.
- GLOSSARY_DELTA: complete grant tuple; value-contract subject; authoritative record versus projection; route mount versus local pattern.
- NEXT_READ_QUEUE: finish master assembly; validate source anchors, repository-relative references, generated inventory coverage and final dirty-worktree scope.

## STATE BLOCK — Phase 6 complete

- INDEX_VERSION: `1`, source commit `f9b1e8a97cf98b1e6c79927bd0ee7ce46c2ddcc2`; source hashes verified unchanged.
- FILE_MAP_SUMMARY: explicit top 50 below, with detailed ranks/counts/hashes in `codebase-analysis-docs/assets/FILE_INDEX.md`. Coverage: 1,455 tracked source files; 5,178 top-level symbols; 215 model declarations; 392 route declarations; 176 direct setting lookups. Runtime model-only catalogue: 209 application-table entries.
- OPEN_QUESTIONS: production deployed revision/applied migrations, runtime feature flags, staff grants, real provider behavior, scheduler coverage, data volumes and backups were deliberately not inspected. No unresolved source question blocks the documentation handoff.
- KNOWN_RISKS: existing direct view write in Portal order finalization; canonical catalogue usage/writer metadata drift in seven model entries; incomplete local Python environment missing cryptography; no Django workflow/browser/PostgreSQL or live-provider validation claimed. Retired/gated compatibility paths are explicitly marked in the master.
- GLOSSARY_DELTA: consolidated operational glossary in master section 13; semantics remain workflow-qualified and canonical catalogue/code-owned.
- NEXT_READ_QUEUE: none for this documentation task. For implementation, read the owning master feature section, verify its current source hash and follow the test map. Re-run `python codebase-analysis-docs/assets/validate_analysis.py` after editing this bundle.
- DELIVERABLE: `codebase-analysis-docs/CODEBASE_KNOWLEDGE.md`; 15 feature-family breakdowns, architecture/data-flow/relationship diagrams, API examples, change recipes, source/test/schema indexes, gotchas, assumptions and verification limits.
- VALIDATION: AST inventory, dependency parity, Node suite, 143-file JS syntax, 271-migration graph, 11 governance unit tests and analysis-path/hash checks completed. 249 explicit source anchors checked. Only `codebase-analysis-docs/` is intended new tracked scope; application code and migrations are unchanged.

### FILE_MAP_SUMMARY — Top 50 ranked source paths

1. `core/services/miniapp_settings.py`
2. `core/models.py`
3. `hb_operations/models.py`
4. `origination/models.py`
5. `payments/models.py`
6. `requisitions/models.py`
7. `tat_recognition/models.py`
8. `portal_recognition/models.py`
9. `report_delivery/models.py`
10. `core/api/browser_urls.py`
11. `core/api/legacy_urls.py`
12. `core/api/portal_views.py`
13. `core/api/urls.py`
14. `core/api/views.py`
15. `core/services/access_control.py`
16. `core/services/access_grant_governance.py`
17. `core/services/access_policies.py`
18. `core/services/activity_changes.py`
19. `core/services/branches.py`
20. `core/services/case_updates.py`
21. `core/services/commands.py`
22. `core/services/complaint_cases.py`
23. `core/services/complaint_register.py`
24. `core/services/complaint_timing.py`
25. `core/services/compliance_audit.py`
26. `core/services/document_signoffs.py`
27. `core/services/document_sync.py`
28. `core/services/durable_jobs.py`
29. `core/services/external_resilience.py`
30. `core/services/fca.py`
31. `core/services/group_config.py`
32. `core/services/group_reset.py`
33. `core/services/identifiers.py`
34. `core/services/invoice_cleanup.py`
35. `core/services/invoice_identity.py`
36. `core/services/invoice_name_change_letters.py`
37. `core/services/invoice_parser.py`
38. `core/services/jawabu.py`
39. `core/services/jawabu_approvals.py`
40. `core/services/jawabu_case360.py`
41. `core/services/jawabu_case_reference.py`
42. `core/services/jawabu_master.py`
43. `core/services/jawabu_pipeline.py`
44. `core/services/jawabu_validation.py`
45. `core/services/live_sheet_records.py`
46. `core/services/location_catalog.py`
47. `core/services/locations.py`
48. `core/services/miniapp_deletion_sheets.py`
49. `core/services/miniapp_messages.py`
50. `core/services/miniapp_recovery.py`

### Decisions/Findings

The master is assembled and source-backed. Retained historical code, current public boundaries and deployment-dependent gates are distinguished. All documentation/supplemental tooling remains inside the requested output directory.

### Open Questions

Live environment questions are explicitly outside the evidence gathered, not silently assumed resolved. The baseline application validation findings are documented without changing its behavior.

### Next Steps

Use the master and inventories for the next bounded engineering task. Refresh exact source evidence when Git or file hashes change; do not reactivate retired helpers or change signed snapshots based on old prose.
