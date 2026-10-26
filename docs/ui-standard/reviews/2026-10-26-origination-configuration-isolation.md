# Origination configuration: functional UI correction

Authorized by the user's accepted plan and implementation request on 26 October 2026.
This reuses the existing Django Admin editor, selects, fieldsets, autosave feedback,
Mini App form projection and confirmation controls. It does not adopt lab tokens,
change approved visual baselines, activate browser business access or authorize Phase 6.

The document editor can select identity values from the application/Main LAF without
adding duplicate document inputs. Removing signing placements refreshes the signer
list and schema revision immediately, so a subsequent edit does not restore removed
requirements or fail with an obsolete revision. Static documents do not require an
unused field. Removing an optional printed signing date does not recreate it later;
the signing action retains its audited timestamp independently.

Origination requirements use the existing repeatable Admin rows. Published shared
financial terms stay read-only while an Origination successor edits its own checklist.
The explicit financial-edit action names its shared scope. The read-only detail view
shows the Origination configuration captured on that version. Shared catalogue controls
are grouped separately, and blocked reset previews explain which other app uses a product.

Visible application Loan details reuse the existing form-field renderer. Amount and
tenor remain once per application even when their PDF placements are removed; the
accepted policy exception is recorded in ADR 0075.

Real Chromium journeys use the Django Admin shell with a synthetic local session,
synthetic PDFs and mocked Drive. They cover upload, signer editing, placement,
preview, publication, attachment, shared updates, withdrawal, removal, later save and
reload. Source-bound captures are retained locally under:

- `test-results/origination-configuration-browser/`: shared identity and deletion, 390/1280px.
- `test-results/origination-authoring/`: custom PDF and product publication, 320/390/430/1280px.
- `test-results/origination-maintenance-live/`: shared edit/withdrawal, light/dark.
- `test-results/origination-attachment-live/`: attachment and reload, light/dark.

Reproduce using `scripts/test_origination_configuration.py --postgres
core.tests_origination_maintenance_browser`. PostgreSQL is a separate synthetic
loopback instance on port 55439. The helper ignores `.env`, blocks remote connections
and retains machine-readable test summaries. Migration 0014 is tested locally only.

Checked source hashes are recorded in the UI registry as functional exceptions,
without replacing baseline hashes. Screenshots are synthetic behavior evidence;
physical Telegram/device and screen-reader acceptance are not claimed.
