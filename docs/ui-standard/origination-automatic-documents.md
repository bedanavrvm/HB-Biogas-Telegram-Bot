# Origination automatic document updates

User-requested behaviour candidate, 22 October 2026. No new density, colours,
controls or tokens. This extends the existing application shell and toast pattern;
it is not a Phase 6 migration or approval of any visual baseline.

## Behaviour

Opening/resuming an officer-owned unsigned application checks for published
same-family document updates automatically. Compatible answers and uploads stay;
new supporting fields use the existing shared `fieldInput` renderer. Shared Main
LAF values remain grey/read-only on supporting pages. No refresh button or modal
is added. A short informational toast confirms an update. Failure leaves the form
usable and gives a warning; reopening retries. The server checks before submission
and returns the updated editing form rather than signing an unseen revision.

Confirmed signature evidence anywhere in the application suppresses automatic
adoption. Unconfirmed signature previews do not. The existing Manage documents
action remains for selection/replacement, not version refresh. ADR 0060 owns the
workflow, authorization and preservation rules.

## Evidence

`core/tests_browser/origination_application_forms.spec.js` renders the actual
Django shell/assets with synthetic operational I/O. The automatic-update tests
verify unsigned reviewed-to-draft adoption, preserved values, new supporting
fields, read-only shared values, no confirmation dialog/button, failure/reopen,
resume checks and absence of updates for signed applications. Light 360px and
dark 390px captures are in `test-results/origination-automatic-documents-verified`.
Screenshots are review evidence, not approved baselines. Actual Telegram client
behaviour and PostgreSQL row locking need their own environment verification.

Verified locally: **231 backend tests run, 226 passed, 5 PostgreSQL-only skips**
across automatic adoption, catalogue/selection, shared values/projection, unsigned
completion, signing plans, approvals and OTP signing. **33 application browser
tests passed**, followed by **5 final automatic-update checks** with explicit
runtime-error assertions and the shorter informational toast. Light/dark PNGs
were inspected. Django checks and migration drift (no new migrations), Ruff,
148 first-party JavaScript syntax checks, UI source ratchet and whitespace checks
passed. Providers were synthetic/disabled; nothing was deployed or published.

Reproduce:

```powershell
npx playwright test --config=playwright.config.js core/tests_browser/origination_application_forms.spec.js --grep "unsigned documents update|automatic update failure|resuming an unsigned|signed application does" --workers=1 --output=test-results/origination-automatic-documents-verified
.venv/Scripts/python.exe scripts/test_named_sheets.py origination.tests_document_refresh origination.tests_document_management origination.tests_value_contracts
```
