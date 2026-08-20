# Loan Origination Mini App: Django Admin Guide

Last verified against the repository on **20 August 2026**.

This guide is for Django Superusers and staff responsible for configuring loan
products, LAFs, supporting documents, and Mini App access. It describes the
current Admin interface. Do not use old root-level implementation notes as an
operating manual.

## What the setup creates

One usable loan product is assembled from several governed records:

```text
Global Product
    └── Product Terms and Requirements (versioned commercial terms)
            └── Origination Product Definition (versioned form contract)
                    ├── Main LAF PDF and its field/signature mapping
                    └── Supporting document assignments
                            └── Reusable supporting PDF versions and mappings
```

When an officer starts an application, Django freezes snapshots of the product
terms, form schema, requirements, document versions, mappings, and signer rules.
Changing the Admin setup therefore affects **new applications only**. Existing
applications continue using the versions they started with.

## Who may configure it

Creating, changing, publishing, purging, or resetting Origination configuration
requires an active Django Superuser. Published records are deliberately
immutable. A Superuser changes them by creating a new editable version, not by
editing the published record in place.

Mini App access is separate from Django Admin access. Officers and reviewers
need an active `AccessGrant` for the `Jawabu Portal` workflow; `is_staff` alone
does not grant Mini App access.

## Before starting

Confirm the deployment has:

- all current Django migrations applied;
- `APP_BASE_URL` set to the public HTTPS origin;
- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_BOT_USERNAME` configured;
- `ORIGINATION_MINI_APP_SHORT_NAME` matching the BotFather Mini App short name;
- valid Google service-account credentials;
- `GOOGLE_DRIVE_MEDIA_FOLDER_ID` pointing to the approved restricted media
  folder; and
- the service account allowed to create and read files in that folder.

The relevant upload limits are:

- `ORIGINATION_TEMPLATE_MAX_FILE_SIZE_MB` for LAF/supporting PDFs;
- `ORIGINATION_EVIDENCE_MAX_FILE_SIZE_MB` per evidence file;
- `ORIGINATION_EVIDENCE_MAX_FILES_PER_REQUIREMENT`; and
- `ORIGINATION_EVIDENCE_MAX_TOTAL_UPLOAD_MB` per application.

Never place real credentials, customer documents, IDs, or phone numbers in test
fixtures or repository files.

## End-to-end setup

The Configuration section of the Django Admin sidebar contains the pages used
below.

### 1. Configure locations

1. Open **Configuration → Global locations**.
2. Confirm every branch, county, and sub-county needed by the product is active
   and has the correct immutable code and hierarchy.
3. Open **Configuration → Branch service areas** and connect branches to the
   counties/sub-counties they serve.
4. Resolve any location mapping issues before publishing a product restricted to
   those locations.

Use the canonical location records. Do not type alternative branch/county names
into form schemas.

### 2. Create the Global Product

1. Open **Configuration → Global products** and select **Add Product**.
2. Enter:
   - **Name**: the staff-facing product name;
   - **Code**: a stable lowercase identity such as `asset_finance`;
   - category, description, active state, and sort order.
3. Add approved aliases only when imports or other workflows use another name.
4. Configure availability only if the product must be restricted:
   - branch;
   - workflow; or
   - channel (`Portal`, `Telegram`, `Django Admin`, `Imports`, or `API`).
5. Save.

If there are no active availability assignments, the product is globally
available. Once saved, the product code cannot be changed because access scopes
and historical records depend on it.

### 3. Define commercial terms and requirements

1. From the product, select **Add version**, or open
   **Configuration → Product terms and requirements** and add a version.
2. Complete the draft's commercial terms:
   - currency;
   - minimum/maximum amount;
   - minimum/maximum tenor and tenor unit;
   - flat or reducing-balance interest method;
   - interest rate and monthly/annual rate period;
   - repayment frequency; and
   - the canonical amount and tenor field keys used for quotes.
3. Add any fees, including calculation basis, collection mode, minimum/maximum,
   and whether each fee is mandatory.
4. Add requirements and choose when they are enforced. Document requirements
   become evidence requests in the Mini App.
5. Add typed custom attributes only for product terms that are not applicant
   form fields.
6. Add product TAT configuration if this product uses it.
7. Save the version as a draft.

Do not publish the terms yet if the Origination form and PDFs are not ready. If
you publish too early, use **Create editable next version**; published terms
cannot be edited.

### 4. Create the Origination Product Definition and main LAF

1. Open **Configuration → Origination product definitions**.
2. Select **Add Origination product definition**.
3. Choose the draft **Product definition** / product terms version. The
   Origination product key and name must match its Global Product code and name.
4. Upload the approved primary LAF PDF.
5. Use the visual form builder to:
   - add sections in the order officers should complete them;
   - select canonical fields for each section;
   - set product-specific labels, help text, width, required state, and permitted
     choice presentation; and
   - add every required signer role.
6. Save. A successfully uploaded LAF opens the alignment builder.

The primary document always uses the key `primary`, is always required, and
cannot be officer-selectable.

### 5. Create and govern canonical fields

Use **Configuration → Origination data fields**, the builder's **Create
canonical field** link, or **+ Field** in the alignment builder.

Origination uses the following controlled terminology:

- **Applicant** is the person or entity applying for the loan and is the
  standard term in form sections, field labels, queues, and review screens.
- **Customer** means the canonical global customer identity that may be matched
  to an applicant. It is not a synonym for Applicant in form configuration.
- **Borrower** is reserved for the contractual obligor, signer roles, and legal
  PDF wording.
- **Party** collectively describes the applicant, guarantors, spouse, and other
  document participants.
- **Client** is not a person label in Origination. Technical names such as
  `client_request_id` retain their established API meaning.
- **Farmer** is used only when a product specifically needs an occupation field;
  it remains valid terminology in the separate legacy Jawabu workflows.

Before creating a field, search for the same business meaning. Reuse one
canonical key for labels such as “Applicant ID”, “National ID”, or “ID Number”
when they mean the same value. Product forms may relabel that field without
creating another data identity.

Available types are short text, long text, number, money, date, phone, national
ID, choice, yes/no, governed branch/county/sub-county, and repeatable group.
Also set:

- **Source**: user input or system-derived;
- **Sensitivity**: public, internal, PII, financial, or restricted;
- masking and export policy;
- reporting use: unavailable, filter, dimension, or metric;
- aliases and help text; and
- canonical choice codes/labels where applicable.

The key and data type are immutable. Repeatable-group structure is immutable,
and existing canonical choice codes cannot be removed. Deactivate obsolete
fields/options rather than reinterpreting historical data. Conflicts appear in
**Configuration → Legacy fields needing review** and can block publication.

The catalogue also checks new keys, labels, and aliases for terminology
collisions. Open **Review terminology** from Origination data fields to compare
possible duplicates. A Superuser can consolidate a same-type duplicate into a
preferred field or confirm that it has a genuinely different meaning.
Consolidation deactivates the duplicate for new configuration and records the
preferred field, but never rewrites published schemas, application payloads, or
PDF mappings.

### 6. Align and save the main LAF

In the alignment builder:

1. Select **+ Field**, choose a field, then draw or place its box on the PDF.
2. Add and place every required signer or stamp slot.
3. For a normal data field, use **Selected** controls to set box dimensions,
   text alignment, font, minimum font size, padding, capitalization,
   checkbox/text rendering, and overflow behavior.
4. For a signature slot, use **Selected** to customize its slot label,
   horizontal/vertical alignment, padding, rotation, ink colour, typed-signature
   font and size, and drawn-signature stroke width.
5. For a stamp slot, configure its slot label, alignment, padding, rotation, and
   whether the approved PNG keeps its proportions or fills the whole box. The
   stamp image itself is selected from governed stamp assets during signing.
6. Use **Global formatting** for shared text defaults. Individual field settings
   may override them.
7. Check every page with **Fit width**, **Fit page**, zoom, and page navigation.
8. Switch from **Template** to **Filled sample** and inspect a generated sample.
9. Select **Save draft**.
10. Open **Publish readiness** and correct every mapping-related item.

If the product needs supporting documents, return to the product definition now
and add them before selecting **Publish product**. Publication validates the
whole packet, not only the main LAF.

Undo/redo is session-local. Saving does not make an incomplete mapping
publishable; server validation remains authoritative.

### 7. Add a supporting document

Return to the draft Origination Product Definition and find **Document packet**.
There are two supported paths.

#### Attach an existing reusable document

1. Choose a document from the published-document dropdown.
2. Select **Add**.
3. Its card appears in the packet.
4. Use **Advanced settings** to change its inclusion rule or order.
5. Use **Preview PDF mapping** to inspect the resolved active version.

Only global supporting templates that are active and have a published
calibration appear in the dropdown.

#### Create a new reusable document

1. Select **Create supporting document**.
2. Choose the create-new option and enter a stable document key, name, and PDF.
3. Select the canonical fields that this document needs. Add sections and signer
   roles visually; do not enter JSON.
4. Configure how the product uses it:
   - **Always required** for every application;
   - **Required when rule matches** with a product field/operator/value; or
   - **Officer selectable** for an optional document.
5. Set display order, officer-selectable state, and default-selected state.
   Default selection is valid only for optional documents.
6. Select **Upload and align fields**.
7. Place its fields and signer slots in the alignment builder, inspect the filled
   sample, and select **Publish & attach**.

The new document is stored as a reusable global template family. Its assignment
uses **Latest published compatible version** by default. New applications take
the newest compatible published version, while every application retains the
exact version it resolved at creation.

To detach a document from a draft product, select **Remove** on its packet card.
This removes only the assignment. It does not delete the reusable template or
change existing applications.

### 8. Publish safely

Before publication, confirm:

- the Global Product is active and its availability is correct;
- product terms, fees, and requirements are complete;
- there is exactly one mapped primary LAF;
- every supporting document resolves to a published compatible template;
- all required fields and signer slots are placed;
- Applicant name, National ID, and primary telephone are attached and marked required;
- filled samples render correctly on every page;
- there are no unresolved field-review issues; and
- an officer/reviewer access test has been prepared.

Use **Publish product** in the main LAF builder. The server validates and
activates the document/product contract and publishes the linked Global Product
terms version if it is still a draft. Publication is audit-logged. A successful
publish leaves a persistent message naming the product and version that is now
available for new production applications.

### 9. Grant Mini App access

Open **Users**, then either select **Add staff user** or open an existing user and
manage **Access grants**.

Use workflow `Jawabu Portal` and the narrowest required branch/product scope:

| Role | Default Origination access |
|---|---|
| `JBL_OFFICER` | View, create, and edit their own applications. |
| `OPERATIONS_ADMIN` | View/review applications and prepare signing packages. |
| `BUSINESS_ADMIN` (Head of Rural) | View and review applications. |

### Signing and stamps during testing

`Prepare signing package` freezes and hashes the reviewed packet. It is not an
OTP or e-sign dispatch. When `ORIGINATION_TEST_SIGNING_ENABLED=True` and
`SENTRY_ENVIRONMENT` is explicitly `development`, `dev`, `local`, `test`,
`testing`, or `staging`, the Signing queue exposes a simulator that places
either a drawn synthetic mark or a typed test signer name into each configured
signature slot. Open the application review, choose **Capture TEST signature**,
select **Draw** or **Type**, provide the synthetic test mark, and then use
**Preview TEST signed packet** to verify its calibrated PDF position.

Do not capture a person's real signature in this simulator. It performs no OTP,
identity, consent, or legal-signature verification. The server validates and
bounds the test input, stores it only as test-action evidence, and does not send
the raw mark back in normal application API responses.

Create test stamps from **Configuration → Origination stamp assets**. Upload a
genuine PNG, choose `Test only`, optionally restrict it to a branch, and make
the version active. Only active test stamps appear in the simulator. Test
outputs remain visibly watermarked and never make an application fully signed.
Production stamp assets cannot be applied until a verified production signing
integration supplies signature evidence.

### Correction re-checks

The checker must select at least one exact field, requirement, or supporting
document field. During correction all other controls are locked in the Mini App
and at the API. Resubmission returns to that original checker. Another scoped
checker must use **Take over re-check** and give an audited reason before they
can decide it.

The role-capability policy is authoritative and may be customized through the
governed access-control workflow. Product and branch scopes further restrict the
role. An active Django Superuser has the audited technical break-glass override.

### 10. Configure and test the Telegram launcher

Create the Mini App in BotFather using the public `/origination/` URL and set the
same short name in `ORIGINATION_MINI_APP_SHORT_NAME`. Add **Loan Origination** to
the relevant Telegram group configuration's Mini App launchers.

Preview launcher changes without contacting Telegram:

```powershell
.\.venv\Scripts\python.exe manage.py sync_telegram_launchers --dry-run
```

Limit the preview or publication to one configured group when appropriate:

```powershell
.\.venv\Scripts\python.exe manage.py sync_telegram_launchers --group-id <telegram-group-id> --dry-run
.\.venv\Scripts\python.exe manage.py sync_telegram_launchers --group-id <telegram-group-id>
```

The final command changes a real Telegram message. Run it only for an explicitly
approved group.

## Test with the synthetic demo packet

The seed command creates no application or customer data. It creates one fully
published synthetic product, a two-field main LAF, and a two-field guarantor
supporting document. The apply mode uploads synthetic PDFs to the configured
Drive folder.

Preview the operation:

```powershell
.\.venv\Scripts\python.exe manage.py seed_origination_packet_demo --actor <superuser-username>
```

Apply it:

```powershell
.\.venv\Scripts\python.exe manage.py seed_origination_packet_demo --actor <superuser-username> --apply
```

Then open the Mini App, create an **Origination packet demo** application,
complete and preview the main LAF, select/open the guarantor document, complete
its fields, and preview the packet.

The command refuses an inactive/non-Superuser actor and a conflicting partial
demo setup. Re-running it against the complete published demo is safe.

## Change an existing production product

1. Open the published Product Terms version and use **Create editable next
   version** if commercial terms change.
2. Open the published Origination Product Definition and use **Create editable
   next version** for form, LAF, signer, or packet changes.
3. Edit and test only the new drafts.
4. Publish the linked replacement contract when it is ready.

Old versions remain visible in version history and continue supporting existing
applications. Do not purge production versions to reduce list clutter.

## Testing-only deletion controls

### Purge one Origination record

An active Superuser sees **God mode purge** on supported Origination records.
The confirmation page shows related database rows. It requires the exact record
ID and a reason. It bypasses normal immutability only for Origination data.

### Reset all Origination data

This is a testing-only clean slate:

1. Set `ORIGINATION_FULL_RESET_ENABLED=True` and redeploy.
2. Sign in as an active Superuser.
3. Open **Configuration → Reset all Origination data**.
4. Review the per-model counts, enter a reason, and type
   `RESET ALL ORIGINATION DATA` exactly.
5. Run the reset.
6. Immediately set `ORIGINATION_FULL_RESET_ENABLED=False` and redeploy.

It permanently deletes all Origination applications, packet snapshots,
configuration, mappings, canonical fields, and Origination audit records. It
does **not** delete Drive files, Global Products, locations, users, permissions,
or data belonging to another Mini App. Deleted database links to retained Drive
files cannot be recovered automatically.

## Troubleshooting

| Symptom | Checks and remedy |
|---|---|
| Product/definition dropdown is empty | Create an active Global Product and a suitable draft Product Terms version. Confirm the current Superuser and that another conflicting draft/version does not already exist. |
| “Published product versions are immutable” | Open the published record and use **Create editable next version**. |
| PDF upload fails | Check PDF validity/size, Google credentials, folder ID, service-account folder permission, and the record's upload error. |
| A field is missing from the builder | Search **Origination data fields**, confirm it is active, or create one canonical field. Resolve incompatible legacy bindings in **Legacy fields needing review**. |
| Publish readiness is blocked | Place all required fields/signers, save, inspect filled sample, publish each reusable supporting template, and resolve field-review issues. |
| Supporting document dropdown is empty | The reusable template must be global, supporting-role, active, and have a published calibration. |
| Supporting document is not in the Mini App | Confirm its assignment is on the published Origination definition. Create a **new application** after the change; existing applications retain their packet snapshot. |
| “One or more supporting documents cannot be selected” | The document is required/conditional rather than selectable, is not applicable, or is absent from this application's snapshot. Refresh and verify the assignment; start a new application after configuration changes. |
| Supporting preview is unavailable | Select the optional document, complete its required fields, save the current revision, then preview it. Confirm its template still resolves. |
| Submit is blocked | Save and preview the main LAF for the current revision, complete every selected required document/evidence item, and resolve validation errors. |
| HTTP 409 / “application changed” | Another save changed the revision. Refresh before retrying; do not force stale data over the newer revision. |
| Officer sees no products/branches | Check the published active definition, effective product terms, product availability, active location catalogue, AccessGrant role, and branch/product scope. |
| Telegram shows an older UI | Relaunch the Mini App after deployment and confirm the deployed static asset version. The HTML shell is sent with no-store headers, but an old deployment still serves old assets. |
| Server reports a PostgreSQL `FOR UPDATE` outer-join error | Confirm the current Origination template service code is deployed. Lock base rows before loading nullable related objects; do not add `select_related()` nullable joins to a locking queryset. |
| Reset link is missing | It is intentionally visible only when `ORIGINATION_FULL_RESET_ENABLED=True` and the current user is an active Superuser. |

## Production acceptance checklist

- Create a new test application rather than reusing one created before the final
  publication.
- Confirm branch/product scoping with one officer and one reviewer account.
- Complete, save, and reload every field type used by the product.
- Preview the main LAF and every required/optional supporting document.
- Verify conditional documents appear only when their rule matches.
- Confirm packet order, page output, text alignment, checkbox rendering, and
  signer placement.
- Submit, return for correction, resubmit, review, upload required evidence, and
  prepare a signing package.
- Verify repeated taps do not create duplicate applications/events/packages.
- Check Django logs and Origination audit events without exposing customer data.
- Keep `ORIGINATION_FULL_RESET_ENABLED=False` in normal production operation.
