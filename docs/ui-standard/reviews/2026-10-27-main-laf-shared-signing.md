# Main LAF borrower reuse and template versions

Authorized by the user's implementation request and the additional request to show
the template version in the Origination document-template list.

The existing Django Admin signer editor now uses its existing labelled select and
help-text pattern to choose a Main LAF borrower for a supporting document. The
default uses the application borrower; named Main LAF participants are offered from
the document's eligible products. Each supporting PDF keeps its own placements.
No duplicate local borrower fields are generated. Several Main LAF borrowers need
an explicit unambiguous binding before packet creation. Distinct asset owners and
guarantors retain independent identities. The Admin list includes the ordinary
sortable Version column after Name.

The application-creation correction removes the hard-coded Applicant-plus-JBL
minimum. Document obligations, independent staff authorization, OTP, full-packet
review, consent, revision checks and signature geometry remain server controlled.
New snapshots retain the binding policy and the original PDF placement keys;
existing signed packages retain their frozen participants and bytes. See ADR 0075.

This is a functional correction using the current Admin shell and controls. No lab
tokens, approved baseline hashes, browser business routes or Phase 6 gates change.

Validation on 27 October 2026, using synthetic data and loopback-only network:

| Check | Result |
| --- | --- |
| Final focused PostgreSQL service/API/concurrency run | 120 passed; no skips |
| Final focused SQLite service/API run | 120 tests, no failures; 3 PostgreSQL-only skips |
| Chromium Admin journey | Passed, including named borrower selection/reload and Version column; 390/1280px captures manually inspected |
| Static checks | No migrations detected; JavaScript syntax, UI source ratchet and whitespace checks passed |
| Additional e-sign/safe-workflow/signing-presentation run | 54 tests: 53 passed, 1 pre-existing assertion mismatch |
| Baseline verification of the mismatch | Reproduced alone at unchanged commit `76ccbc14` in an isolated checkout |
| Synthetic complete signing flow | Draft, shared values, full preview, frozen packet, one borrower link/session, OTP, two document signatures, independent officer signature, Approved, rendered marks on both PDFs |
| Retry and history checks | API/link/OTP retries do not duplicate records; unsigned bytes retain the original hash; historical participant keys stay unchanged; signed document updates remain locked |

The pre-existing failure is
`OriginationSafeWorkflowTests.test_invalid_draft_patch_identifies_field_without_logging_submitted_value`:
it expects `Enter a valid amount.` while the current number validator returns
`Enter a valid number.`. The same failure occurs on the base commit; this change
does not modify that validator or test. The endpoint continues to reject invalid
values. The separate passing checks cover authorization and OTP/provider failures.

The Chromium journey loads the actual Admin shell with a local synthetic session
and mocked private PDF storage. It chooses a named Main LAF borrower, waits for
autosave, removes the officer placement, edits again, reloads, checks that no
duplicate borrower inputs appeared, and opens the template list's Version column.
Captures are local synthetic evidence:

- `test-results/origination-configuration-browser/document-contract-390.png`
- `test-results/origination-configuration-browser/document-contract-1280.png`
- `test-results/origination-configuration-browser/document-template-versions.png`

Reproduce the focused run using `scripts/test_origination_configuration.py --postgres`
with labels `origination.tests_main_laf_signer_reuse.MainLafSignerReuseTests`,
`origination.tests_signing_plans`, `origination.tests_configuration_isolation`,
`origination.tests_document_refresh`, `origination.tests_application_presentation`,
`core.tests_origination_document_catalogue` and
`core.tests_origination_maintenance_browser.OriginationMaintenanceBrowserTests.test_document_removal_and_shared_identity_are_persistent`.
The helper ignores `.env` and uses the isolated PostgreSQL instance on port 55439.
Run logs are retained locally as `test-results/main-laf-reuse-*.log`.

Deploy the application code and collect static assets; no new migration, setting,
reseed or data reset is needed. Previously required migration 0014 still applies.
Unsigned existing applications retain their captured policy; failed creation
requests can be retried after deployment. New policy metadata is additive to the
existing snapshots. Rollback after new marked packages have been created needs
care: restore this signing reader before rendering those packages, because older
code does not understand their qualified action keys. No external data is changed.

Production deployment, real Telegram devices, screen readers and live SMS/Drive
delivery were not exercised. Physical-device and operational acceptance remain
separate from these synthetic browser and PostgreSQL checks.
