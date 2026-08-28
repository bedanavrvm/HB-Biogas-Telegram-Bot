# Guided Origination product setup

## Purpose

The guided workspace is the default Superuser path for creating and maintaining an Origination product. It coordinates the existing global `Product`, immutable `ProductVersion`, `OriginationProductDefinition`, document packet, and PDF calibration records. It does not create a second setup-state database.

Open **Django Admin → Origination product definitions → Guided product setup**.

## User workflow

1. **Product and availability** — enter the stable product identity and choose every branch where officers can start it. The stable code cannot change later.
2. **Commercial terms** — enter the KES amount range, tenor policy, interest policy, fees, Origination requirements, and custom attributes.
3. **Publish terms** — review and explicitly publish the commercial-terms version. This is publication checkpoint 1. Published terms are immutable.
4. **Form and signers** — use the visual form builder to arrange canonical fields and define required signing roles.
5. **Document packet** — select a published reusable primary LAF or upload a product-owned LAF. Supporting documents remain available from the same step.
6. **PDF alignment** — open each document in the full-screen calibration builder. For a product-owned LAF, use **Save & return**; the product is not published from the calibration screen. The return target is signed, internal, and expires after 24 hours.
7. **Review and publish** — resolve every incomplete or stale item and publish the exact form and packet. This is publication checkpoint 2.

The dashboard resumes the first stale step before the first incomplete step. `blocked` means a preceding required step is not valid. `stale` means the step was previously confirmed but one of its governed inputs or dependencies has changed.

## Maintenance and version safety

- Published `ProductVersion` and `OriginationProductDefinition` rows are never edited.
- **Create editable successor** reuses an existing draft when present, otherwise creates the next terms and form versions and inherits the prior packet/calibration through the established cloning services.
- Existing applications continue to use their captured product, schema, template, and packet snapshots.
- Advanced model pages remain available for exceptional Origination configuration. Changes to governed product/form/document inputs are reflected immediately by the workspace hashes and can make dependent steps stale. TAT and unrelated workflow settings remain outside Origination readiness by design.

## Concurrency and idempotency

Every workspace write includes:

- a per-request retry key;
- canonical SHA-256 state tokens for all steps; and
- a database lock over the definition and terms version.

If another tab or Superuser changed relevant state, the write returns HTTP 409 and identifies the changed steps. The submitted values are retained on the conflict page for copying, but are never silently applied over newer data.

Successful step confirmations are append-only `setup_step_completed` events on the existing product-version or Origination product event streams. Replaying the same request key does not create duplicate setup evidence.

## Authorization and security

- Every workspace route independently requires an active Django Superuser.
- Navigation visibility is not treated as authorization.
- Calibration return tokens contain only a definition ID and allowlisted step key, are Django-signed, expire after 24 hours, and are checked against the selected document family.
- Invalid or expired return tokens fall back to the setup dashboard with a visible warning; external return URLs are never accepted.

## Developer notes

- `core/services/origination_setup.py` owns snapshots, hashes, readiness, resume selection, signed returns, and setup completion events.
- `core/origination_setup_forms.py` owns bounded multi-model forms.
- `core/origination_setup_admin.py` owns the Superuser routes and transaction boundaries.
- The authoritative final publication still runs the existing product-catalog and Origination-template publication services. The workspace readiness projection is guidance; it does not replace final server-side validation.
- No schema migration is required because durable draft state and audit evidence use existing governed models.

## Verification

Run the focused checks with the repository virtual environment:

```powershell
$env:DEBUG='true'
$env:DJANGO_SECRET_KEY='local-test-secret-long-enough'
.\.venv\Scripts\python.exe manage.py test core.tests_origination_setup
.\.venv\Scripts\python.exe manage.py check
```

Before production use, complete a Superuser smoke test with a non-customer sample PDF: create a draft, publish terms, build fields/signers, upload or select a LAF, save calibration, return to the wizard, publish the product, and confirm it appears in the Origination Mini App for an assigned test branch.
