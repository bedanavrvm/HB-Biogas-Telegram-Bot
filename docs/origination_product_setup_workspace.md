# Guided Origination product setup

## Purpose

The guided workspace is the default Superuser path for creating and maintaining an Origination product. It coordinates the existing global `Product`, immutable `ProductVersion`, `OriginationProductDefinition`, document packet, and PDF calibration records. It does not create a second setup-state database.

Open **Django Admin → Origination product definitions → Guided product setup**.

## User workflow

1. **Product** — enter its name and branches. The internal stable code is generated automatically. Additional descriptive settings are optional.
2. **Terms** — enter lending limits, tenor, interest and repayment. Fees and additional requirements are collapsed until needed; technical quote keys are derived.
3. **Documents** — choose existing Main LAFs and supporting documents, or upload a blank PDF. A new PDF may start with the reviewed Jawabu field preset or the visual field builder. Define applicant fields and signing locations once on the document, then save and return. Draft products are connected automatically; no catalogue trip is required.
4. **Preview & enable** — inspect branches, terms, signers, the applicant form and synthetic filled-PDF samples. Enable publishes the selected prepared documents, financial terms and product profile atomically; failure rolls canonical changes back.

The dashboard resumes the first incomplete section, then any section marked **Review changes**. Sections remain navigable and valid saves do not require earlier confirmations. Review changes are advisory; genuinely invalid financial, form, signer or consent configuration still blocks final publication with an actionable error.

The independent Document Catalogue remains the application-selection authority. Guided enablement requires a compatible Main LAF; it cannot report success while officers are unable to start applications. Dashboard readiness never downloads PDFs or contacts Drive. Full geometry/source checks run during explicit publication.

**Save draft** keeps typed valid values and stays on the current section. Missing required terms retain their existing draft values; invalid typed values still show errors. Setup can be reopened without requiring earlier confirmation clicks. Choose the final approval policy in Documents; its existing governed consent and signer checks remain mandatory at enablement.

Published products have a **Documents** action for document-only repairs without cloning unchanged financial terms. A reused published document that needs another product in its allowlist creates/reopens a draft successor, retaining fields, PDF bytes, alignment and prior allowed products. Final review names other affected products before activation. Existing applications remain pinned to their captured versions. Selecting documents prepares additions/replacements; it does not silently withdraw previously published choices.

Older drafts with already-published financial terms can finish using those terms. To change them, use **Create editable successor**. Old Publish terms links redirect to final review and do not publish early.

## Published product overview

Select a product name or **View product** under **Published products** to open its read-only family overview. It shows current branch/workflow availability plus every form and terms version, fees, requirements, custom attributes, form fields, signer roles, owned or reusable LAFs, supporting documents, version policies, calibration status, hashes, and publication history.

Availability is current product-level configuration. Terms, forms, signer rules, and document packets are shown separately for each exact version. Use **Create editable successor** to change a published version.

## Bulk availability

Open **Manage availability** from a Product record or the published-product overview. Select several branches and workflows and apply them once; the internal `portal` channel is derived automatically and is not an Admin choice. Repeating the same request is safe. To remove coverage, select the existing assignments and use **Deactivate selected**. Assignments are deactivated rather than deleted and the operation is recorded in the compliance audit ledger.

**Select all current** stores each currently active branch explicitly. A branch created later is not automatically authorized.

## Maintenance and version safety

- Published `ProductVersion` and `OriginationProductDefinition` rows are never edited.
- **Create editable successor** reuses an existing draft when present, otherwise creates the next terms and form versions and inherits the prior packet/calibration through the established cloning services.
- Existing applications continue to use their captured product, schema, template, and packet snapshots.
- Published legacy Main LAFs retain the fields and signers of their original product definition, even when that product is retired. The catalogue validates this original contract against the selected product; it never borrows a newer product's fields to make an incompatible PDF appear ready.
- In the document catalogue, select one document and choose **Create / open editable version**, or open the document's version button. A legacy published PDF can create an independent catalogue successor with its existing PDF, alignment, original form, signers and eligible products. Repeated requests reopen the draft; publishing it does not rewrite existing application snapshots.
- Publishing a linked successor with the same start date replaces its exact predecessor: the earlier terms are retired, not deleted, and their dates, history and application references are preserved. Unrelated overlapping versions remain blocked. Document versions can reuse the same global product through their eligibility assignments.
- Advanced model pages remain available. Meaningful configuration changes show a review reminder; publication status and actor/time metadata do not invalidate financial confirmation. Historical confirmation events are retained and do not become publication gates.

## Concurrency and idempotency

Every workspace write includes:

- a per-request retry key;
- canonical SHA-256 state tokens, checked for the section being edited and its dependencies; and
- a database lock over the definition and terms version.

Relevant concurrent changes return HTTP 409 with the changed sections and submitted values. Unrelated section changes do not prevent saving. Final enablement checks identity, financial terms, compatibility profile, selected document versions, eligibility and alignment revisions together. Readiness uses separate content fingerprints rather than the write-conflict tokens. Existing document-selection events retain draft intent; published catalogue eligibility remains the source of truth.

Successful step confirmations are append-only `setup_step_completed` events on the existing product-version or Origination product event streams. Replaying the same request key does not create duplicate setup evidence.

## Authorization and security

- Every workspace route independently requires an active Django Superuser.
- Navigation visibility is not treated as authorization.
- Calibration return tokens contain only a definition ID and allowlisted step key, are Django-signed, expire after 24 hours, and are checked against the selected document family.
- Invalid or expired return tokens fall back to the setup dashboard with a visible warning; external return URLs are never accepted.

## Developer notes

- `origination/services/origination_setup.py` owns snapshots, hashes, readiness, resume selection, signed returns, and setup completion events.
- `origination/services/origination_setup_documents.py` coordinates catalogue-backed preparation and activation without legacy packet assignments or another setup-state model.
- `core/origination_setup_forms.py` owns bounded multi-model forms.
- `core/origination_setup_admin.py` owns the Superuser routes and transaction boundaries.
- The authoritative final publication still runs the existing product-catalog and Origination-template publication services. The workspace readiness projection is guidance; it does not replace final server-side validation.
- Migration `0140_repair_origination_availability_channel` changes active legacy Loan Origination `telegram` availability rows to the operational `portal` channel. It merges safely when an equivalent portal row already exists.

## Verification

Run the focused checks with the repository virtual environment:

```powershell
$env:DEBUG='true'
$env:DJANGO_SECRET_KEY='local-test-secret-long-enough'
.\.venv\Scripts\python.exe manage.py test core.tests_origination_setup
.\.venv\Scripts\python.exe manage.py check
```

Before production use, create a synthetic draft, save financial terms, save fields/signers, revisit and change the draft terms, then publish once. Confirm that a compatible document from the independent catalogue makes the product available for the assigned test branch. Application approval and signing safeguards remain unchanged.
