# Phone registration pilot verification

Date: 19 October 2026. Worktree implementation, not a production release.
No real provider requests, staff messages, production migration or deployment.

## Results

| Check | Evidence/result |
|---|---|
| New backend feature tests | 20 passed; 2 PostgreSQL-only concurrency tests skipped on SQLite |
| Adapter after final deadline hardening | 4 tests passed independently |
| Final real-shell feature browser suite | 9 passed, including light/dark, cancellation, denial, mismatch, loading, double click, failure, terminal application and stale browser revision |
| Existing queue/signing browser regressions | 72 passed; the combined run had 79 passes before the final two feature scenarios were added |
| Node client suites | `npm run test:node` passed |
| JavaScript syntax | `npm run check:js` passed, 145 first-party files |
| Django configuration | `manage.py check` passed |
| Migration state | `makemigrations --check --dry-run --skip-checks` passed; no changes detected |
| Migration graph | 274 migrations, 16 leaves; passed |
| Database governance | Passed; three new models are bounded-domain, commented, classified and indexed with reasons |
| Canonical database catalogue | Regenerated and verified: 212 application-table entries |
| UI source ratchet | Passed; legacy baselines unchanged, candidate foundations isolated, Phase 6 remains on hold |
| Whitespace | `git diff --check` passed |
| Python syntax | `compileall` passed for affected code |
| Ruff | Unavailable in the local virtual environment; no lint success claimed |

The new backend tests cover field bindings, leading-zero IDs, both Kenyan number
families, strict provider response parsing, authorization/denial, same-key replay,
cross-application and cross-slot reuse, month expiry, unchanged application rows,
no form-policy adoption, global allowance/reset, uncertain outcomes, circuit
opening, stale leases, late-result fencing, offboarding and the partial unique
constraint. HTTP mocks assert no redirects or resubmission, bounded bodies and
per-byte composed-deadline checks. The actor never supplies arbitrary identifiers
through the verification API.

PostgreSQL tests require the guarded `config.settings_test_postgres` profile and
a local `TEST_DATABASE_URL`. Neither a configured URL nor local port 5432 listener
was available. The two skipped scenarios are same-pair concurrent applications
sharing one dispatch, and different subjects racing for the final daily slot.
SQLite success does not establish row-lock correctness. Run those tests before
production activation; do not weaken or remove their PostgreSQL guards.

## Broader regressions and baseline attribution

A normal isolated in-memory Django run exercised 105 tests across the feature,
identity copies, approval signatures, capability policy and Telegram
authentication. It was **not a clean suite**: fifteen failing assertions included
one manifest test using the old single-module ownership assumption. That guard
now checks the actual Origination/Portal/Complaints owning module; its complete
manifest assertion passes independently. The test still requires a real callable
and real capability for every listed endpoint; no assertion was removed.

The other fourteen assertions belong to two existing test methods:

- `PortalAccessHardeningTests.test_multi_role_policy_change_is_one_atomic_request`
  expects an older capability set; retained `portal.origination.signing.staff`
  appears in the actual set.
- `CanonicalTelegramAuthenticationTests.test_every_authentication_flag_and_age_has_a_deployment_check`
  contains thirteen old numeric error-code expectations that differ from the
  current deployment checks.

A separate 24-test run removed only the introduced capability definition from
the runtime catalogue for these two baseline methods, restoring HEAD-shaped
catalogue behaviour in memory. It produced the same fourteen baseline assertion
failures, zero errors, two PostgreSQL skips and twenty passing feature tests.
This was not a pristine historical database checkout; it isolates the new
catalogue entry, while the affected legacy policy/check implementations remain
unchanged. No production policy was edited or reset.

An earlier custom file-backed test harness mixed connection/test-name settings
and caused missing-table errors after a class closed its connection. That harness
result was discarded. The normal in-memory runner above reproduced no such
errors; do not attribute that harness failure to application code.

Read-only HEAD-source comparisons additionally established:

- Settings/environment parity: 119 findings both before and after the feature.
- Unsafe-method inventory: 34 findings both before and after; the new route is
  explicitly inventoried and request-key protected.
- Architecture checking still flags the existing
  `core/api/portal_views.py::portal_requisition_finalize` direct
  `OrderWorkspaceEvent.objects.create`. No new view ORM mutation was added.

No broad baseline, error numbering, legacy capability cleanup or unrelated
permission semantics was changed to make verification green.

## UI source-bound candidate

Source digests use `lf-text-v1`, normalizing CRLF to LF. These are candidate
evidence, **not a human approval or permission for Phase 6**.

| Source | SHA-256 |
|---|---|
| `origination/static/miniapp/phone_identity_checks.js` | `1f97585a65cb25229ce162225f69fe5968413809dc331b052b4ae89542063fd7` |
| `origination/static/miniapp/loan_origination.js` | `43aedb798cefa206ca68175ab162ac14b221edde439615f74949f9d3ae13d3fd` |
| `origination/static/miniapp/origination_compact.css` | `6258a199ec1bec066f90dbb91b6fc8a3d1c4b1410fba842ec172e32854dc1751` |
| `origination/templates/loan_origination/app.html` | `579309de48238a14d558cb13f85f1a44f5aaf9d3e5c251f9257e4d6d944a6a25` |

Final temporary synthetic screenshots, generated by
`core/tests_browser/origination_phone_identity.spec.js`, are recorded below.
They are ignored CI/review artifacts, not committed visual baselines. Paths are
relative to the repository root. Light, dark and loading images were inspected;
real Telegram popup, deployed font and handset review remain outstanding.

| Artifact | SHA-256 |
|---|---|
| `test-results/playwright/origination_phone_identity-f31f2--actions-fit-a-phone-light-/phone-check-light.png` | `dcc5564123ebc34afb21a714d279d90b3646eac5f8705a4f206f94f4dac849d5` |
| `test-results/playwright/origination_phone_identity-51185-e-actions-fit-a-phone-dark-/phone-check-dark.png` | `f5c8ce2d52ae6cb8a1e407cff436239e5634c6eb2c76aea5809d5b6da3e65110` |
| `test-results/playwright/origination_phone_identity-f31f2--actions-fit-a-phone-light-/phone-check-reused.png` | `cd8b928677a20f455c596e2018e0b4c2f9fe3b85b79d3c1199afffb17dca352e` |
| `test-results/playwright/origination_phone_identity-51185-e-actions-fit-a-phone-dark-/phone-check-reused.png` | `6b280d8ea4ca63c1c515c427a9f4dc57e8d395f19fa313696f5c3d53a589e48a` |
| `test-results/playwright/origination_phone_identity-c1b8f-edback-not-an-approval-gate/phone-check-mismatch.png` | `a2f7cdca5e11725962212c8be306d6d986672ea2d21d7db84b1ddd1e62cc2438` |
| `test-results/playwright/origination_phone_identity-1b37d-ce-and-polling-is-read-only/phone-check-loading.png` | `f86752d6a95022a3f167a0aaf3fe3a266988de85bb5a6d2208cb8b99920a1ab3` |
| `test-results/playwright/origination_phone_identity-02021-lures-leave-the-form-usable/phone-check-unavailable.png` | `89ac6ee522cb5375d1c375ec22559c0f498d5c3389fad8766a646ce0e6a2cf6f` |

## STATE BLOCK

```text
INDEX_VERSION: phone-registration-pilot-v1 / 2026-10-19
FILE_MAP_SUMMARY:
  origination/services/phone_identity.py — authority, receipts, reuse, quota/fencing
  origination/services/daraja_phone_identity.py — bounded server-only provider adapter
  origination/models.py — independent subject, attempt and daily allowance tables
  origination/views.py + origination/urls.py — dedicated authenticated GET/POST
  origination/services/loan_origination.py — projection and non-adopting audit option
  origination/static/miniapp/phone_identity_checks.js — confirmed inline action/polling
  origination/static/miniapp/loan_origination.js — field and read-only integration
  origination/tests_phone_identity.py — synthetic backend and guarded PG tests
  core/tests_browser/origination_phone_identity.spec.js — real-shell UI candidate
  core/migrations/0207_alter_integrationoperation_integration.py — provider identity
  origination/migrations/0010_originationphoneidentitydailyusage_and_more.py — evidence
  origination/migrations/0011_phone_identity_pilot_capability.py — built-in IT policy
OPEN_QUESTIONS:
  Operator commercial terms: taxes, failure billing, volume-tier application.
  Separate authorization and results for real sandbox/production calls.
KNOWN_RISKS:
  PostgreSQL concurrency and real Telegram/deployed-font review remain unverified.
  Existing governance and legacy assertion failures remain outside this feature.
GLOSSARY_DELTA: Origination phone registration check; advisory evidence, not possession.
NEXT_READ_QUEUE:
  codebase-analysis-docs/assets/PHONE_ID_CHECKS.md — deployment/config/rollback gates
  origination/tests_phone_identity.py::PhoneIdentityConcurrencyTests — PG activation gate
```

**Decisions/Findings:** implementation is disabled by default and tested with
synthetic provider data only. **Open Questions:** external commercial/activation
facts remain operator-owned. **Next Steps:** obtain PostgreSQL and human/native UI
evidence, review migrations/configuration, then separately authorize any real call.
