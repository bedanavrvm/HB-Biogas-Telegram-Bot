# Complaints browser verification: 27 October 2026

Implementation is complete locally; **production acceptance is not complete**.
No deployment, live staff admission, real provider send or production database
operation was performed. The first account selected by the user is `bedan`.

## Executed checks

- Final combined run: **283 PostgreSQL tests, 282 passed, one existing catalogue
  hygiene failure**. No skipped tests. This includes native authentication,
  initial setup, mailbox-only verification preserving an existing Superuser
  password, MFA enrollment/recovery, revocation, CSRF/denied paths, audit/replay,
  five-process native cache/rate limits, same-code worker exclusion, Complaint
  reads/actions/reports, Telegram adapters and the shared email transport.
- A final focused run of all 15 production/onboarding checks also passes after
  preventing invitations while the Complaint browser is paused and masking
  one-time codes in diagnostic captures.
- Real React client against production `config.urls`, native PostgreSQL sessions
  and production CSP: complete Complaint creation, note, lost-response retry,
  draft/logout recovery, older-history retry/paging, reporting/filter/export,
  preferences and Back/Forward/reload. **87 synthetic workflow captures**, light/
  dark at 320, 360, 390, 768, 1280, 1366, 1440 and 1920 widths as applicable.
- Mailbox-only invitation → existing password → local authenticator enrollment →
  private recovery-code handoff → fresh password/recovery sign-in → Complaints.
  Eight additional proof-free captures cover mailbox verification and authenticated
  work in both themes at 390/1366. The notices link returns the retained licence
  document. Body/dialog typography checks use the existing ADS fallback stack.
  Desktop light and mobile dark mailbox screens were visually inspected.
- A rejected enrollment attempt previously rolled back PostgreSQL native cooldown
  history. Rejection responses now commit that bounded history while denying
  enrollment; native password/code abuse checks pass without weakening factor/audit
  transaction rollback or workflow authorization.
- A disposable loopback PostgreSQL clone verified 0005's historical default,
  row-preserving reverse/reapply, purpose column comment and refusal to reverse
  when mailbox-verification meaning would be lost. The clone was removed.
- Node 22 typecheck, ADS lint, dependency/archive/notice guards and native production
  build pass. Python Ruff, compilation, shell syntax, migration drift/graph,
  architecture boundaries, workspace navigation/recovery checks, UI source ratchet
  and the 206-route write inventory pass. Generated catalogue matches 215 tables;
  it also incorporates already-existing catalogue drift without changing those models.

Local logs: `test-results/browser-production-final-regression.log`,
`browser-production-build.log`, `browser-production-migration-roundtrip.json`,
`browser-production-artifact-audit.log`. Browser captures are under
`test-results/browser-production-native/` and
`test-results/complaints-browser-operations/dist-production/`. Earlier failure
captures/logs are retained diagnostic history; final passing journeys and source/
artifact hashes determine current evidence. None is a human-approved UI baseline.

## Unresolved release gates

1. Existing `core.tests_database_catalog.DatabaseCatalogueTests.
   test_duplicate_explicit_single_column_indexes_are_absent` fails because
   `RequisitionBatch.order_number` has `db_index=True` and the explicit
   `core_requis_order_n_097497_idx`. This model/index is unchanged by the browser
   release. Removing a redundant index needs its own reviewed migration/rollback;
   this change does not silently modify Portal/Requisition schema.
2. The repository-wide tracked artifact audit reports **17 existing allowlist hash
   mismatches and 2,416 unreviewed controlled artifacts**. No high-confidence secret
   pattern finding was reported. All controlled binary artifacts are unchanged in
   this diff; the checked-in logo example matches HEAD byte-for-byte. These are
   not certification that the files are safe. Review provenance/privacy before
   accepting, removing or updating an allowlist entry. No baseline or allowlist
   was regenerated to make the audit pass.
3. Render integration was found but is not installed/connected in this session.
   Deployment branch/service and enabled environment have not been inspected.
4. Real mailbox receipt, supervised `bedan` MFA/recovery, ongoing support ownership,
   deployed worker/cache/cookie/CSP checks, physical devices and assistive technology
   still require operational commissioning. Mock acceptance is not real delivery.

Keep browser flags off until the release gates and explicit production approval
are satisfied. Follow [the production runbook](staff-browser-production.md) for
the configuration, existing-staff handoff, monitoring and guarded rollback.
