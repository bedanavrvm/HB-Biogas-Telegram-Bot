# Loan Origination Mini App: Django Admin Guide

Last verified against the repository on **26 August 2026**.

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

#### Product policy versus entered Commercial Terms

Every newly created or upgraded loan-form definition receives a **Commercial
Terms** section automatically. Officers enter only **Loan amount** and
**Repayment tenor**. The Mini App immediately shows a read-only quote calculated
from the linked Product Terms version.

Currency, tenor unit, interest rate/method/period, repayment frequency,
installments, mandatory fees, and totals are managed only in Product policy.
Optional fees are excluded from Origination unless an administrator publishes
them as mandatory. Do not create duplicate form inputs for these values merely
to place them on a PDF; their system-derived canonical fields remain available
inside the alignment builder.

For an approved one-off amount or tenor range exception, an active Superuser opens
**Configuration → Origination commercial exceptions**, selects the exact
editable application revision, and records a detailed reason plus the external
approval reference. Any subsequent edit/revision invalidates that exception.

### 4. Create the Origination Product Definition and main LAF

1. Open **Configuration → Origination product definitions**.
2. Select **Add Origination product definition**.
3. Choose the draft **Product definition** / product terms version. The
   Origination product key and name must match its Global Product code and name.
4. Choose one **Main LAF source**:
   - **Choose from reusable library** (default): select an active global primary
     LAF with a published calibration. The product references that governed
     template; do not upload the PDF again.
   - **Upload a new PDF**: use this only when the product needs a primary LAF
     that is not already in the reusable library.
   - **Configure later**: save the product-form draft without a main LAF. The
     draft cannot be published until a main LAF is attached and ready.
5. Save the draft. A reusable selection is attached to this product as its one
   primary document and pinned to the selected published version.
6. Use the visual form builder to:
   - add sections in the order officers should complete them;
   - select canonical fields for each section;
   - set product-specific labels, help text, width, required state, and permitted
     choice presentation; and
   - add every required signer role.
7. Save. A newly uploaded LAF opens the alignment builder.

The primary document always uses the key `primary`, is always required, and
cannot be officer-selectable.

A reusable main LAF may serve several products. **Already attached** means
attached to the current product, not unavailable to every other product. The
selector excludes inactive, non-global, supporting, or unpublished templates
and explains why no eligible template is available.

Reusable main LAFs are version-pinned: publishing a newer compatible revision
does not silently change an existing product draft. When a newer revision is
available, open the product's **Document packet** and select **Use vN**. That
explicit upgrade merges the compatible contract into the draft and records an
audit event. Published product definitions remain immutable; use **Create
editable next version** before changing their document packet.

To change a published reusable LAF or supporting document, open its template
record and use the prominent **Create editable version** action. This creates a
safe draft using the same approved PDF, field/signing contract, and current
alignment, then opens the visual builder. Use **Upload replacement PDF instead**
only when the actual source PDF changed. Retired versions direct administrators
back to the current published family version before a successor is created.

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

The Applicant identity contract does not require one hard-coded variable name.
In the loan-form builder, map the Borrower's **Signer name field**, **OTP phone
field**, and **National ID field** to the canonical fields used by that product.
Publication treats those explicit mappings as authoritative and uses the legacy
standard keys only as a fallback. The mapped fields are made required in the
published form contract so queues, review, and signing all resolve the same
Applicant identity.

Available types are short text, long text, number, money, date, phone, national
ID, choice, yes/no, governed branch/county/sub-county, and repeatable group.
Also set:

- **Source**: user input or system-derived;
- **Sensitivity**: public, internal, PII, financial, or restricted;
- masking and export policy;
- reporting use: unavailable, filter, dimension, or metric;
- aliases and help text; and
- canonical choice codes/labels where applicable.

The key is locked after creation. A Superuser may correct a wrongly selected
data type while the field is used only by draft loan forms and unpublished
templates; saving the correction updates those editable schemas together. Once
the field is present in a published/retired contract or an application snapshot,
its type is frozen and a correctly typed replacement field must be created (or,
during testing only, Origination test data must be reset first). Legacy numeric
ID fields remain visible in signer National ID selectors so an existing draft is
not blocked while the catalogue is being corrected.

Governance and input-contract settings are not globally locked. A Superuser may
change source, sensitivity, masking, reporting/export policy, help text, active
state, and additive choice labels/options. Those changes govern future
application snapshots; existing application snapshots keep their historical
contract. Repeatable-group structure remains immutable, and existing canonical
choice codes cannot be removed. Deactivate obsolete fields/options rather than
reinterpreting historical data. Conflicts appear in
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
| `OPERATIONS_ADMIN` | Prepare frozen review packets, review when separately permitted, and start approved signing packages. |
| `BUSINESS_ADMIN` (Head of Rural) | View and review applications. |

### Signing and stamps during testing

**Prepare review packet** freezes and hashes the complete unsigned application
before checker review. After checker approval, **Start signing** unlocks signer
dispatch without rerendering the approved packet. Neither action sends an OTP
until Operations explicitly creates a signer session. When
`ORIGINATION_TEST_SIGNING_ENABLED=True` and
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

### Configure verified OTP signing

For the complete deployment, phone-mapping, LAF-configuration, Sandbox-test,
negative-test, and production-activation procedure, use
[Origination OTP Integration: Setup and Testing Guide](origination-otp-integration-setup.md).

Verified signing is separate from the no-OTP simulator. Start in the Africa's
Talking Sandbox; it exercises the provider request/response path without
sending a real SMS. Configure these secrets in the deployment environment, not
in Django Admin or Git:

```text
ORIGINATION_ESIGN_ENABLED=True
AFRICASTALKING_SMS_ENVIRONMENT=sandbox
AFRICASTALKING_USERNAME=sandbox
AFRICASTALKING_API_KEY=<sandbox-key>
AFRICASTALKING_SENDER_ID=
ORIGINATION_SIGNING_LINK_TTL_HOURS=48
ORIGINATION_SIGNING_BASE_URL=
SENTRY_ENVIRONMENT=staging
RELEASE_ENVIRONMENT=staging
APP_BASE_URL=https://<staging-host>
```

The service fails closed unless the settings agree. Sandbox readiness is
accepted only when both `SENTRY_ENVIRONMENT` and `RELEASE_ENVIRONMENT` are
explicitly non-production and the username is `sandbox`.
Production requires `AFRICASTALKING_SMS_ENVIRONMENT=production`, a non-sandbox
username, credentials, `SENTRY_ENVIRONMENT=production`, and the explicit
enable flag.

Before publishing a product, configure every required external signer in the
main LAF builder. For each signer choose canonical fields for **Signer name**,
**OTP phone**, and, where applicable, **National ID**. These are catalogue
selections, not free-form variable names. The signing package freezes those
values and all selected documents.

The Operations and checker flow is:

1. The officer submits a complete revision after one full-packet preview.
2. Operations opens **Prepare** and chooses **Prepare review packet**. This
   freezes form values, product/quote data, evidence, selected documents,
   participants, signer identities, template configuration, manifest and PDF.
3. The checker opens **Review**, chooses **Preview frozen packet**, and then
   approves, declines, or flags exact fields with an inline instruction.
4. After approval, Operations opens **Signing** and chooses **Start signing**.
5. For an external signer choose **Send to signer's phone**. Use **In-person
   assisted signing** only when the signer is physically using the officer's
   device.
6. After all required signatures and stamps are complete, archive the packet.
   The completed application continues to show **View signed LAF** and
   **Download PDF**. Both actions retrieve the immutable, hash-verified signed
   packet from restricted Drive; users do not need direct Drive access.
   Self-service sends the opaque packet link to the mapped phone. Assisted mode
   opens the same ceremony on the officer's device and is separately audited.
7. The signer must open every packet page, draw or type their signature, accept
   the atomic packet consent, and enter the six-digit OTP. One valid OTP applies
   that capture to every signature slot assigned to that signer in the frozen
   packet.
8. Authenticated staff sign their own configured staff slots from the Mini App.
   Apply only an active `Production` stamp to a calibrated stamp slot.
9. When all required slots are complete, archive the exact frozen signed PDF to
   restricted Drive. A failed archive retains the signed bytes and hash for an
   idempotent retry; it never rerenders from mutable product data.

If a signer exhausts five verification attempts, the session locks for 30
minutes. Three OTP sends in 30 minutes also block further sends. Operations may
choose **Reset / reissue**, but must enter an audit reason. A previously approved
shared-phone exception retains its Superuser approval; a new shared-phone
exception still requires a Superuser and a reason. Africa's Talking delivery
reports are informational only and can never verify an OTP or change signing
status.

Before production launch, perform a separately approved small real-SMS smoke
test on controlled Safaricom and Airtel numbers. The Sandbox cannot prove real
carrier delivery, Sender ID acceptance, MNO throttling, or DND behavior.

### Correction re-checks

The checker must select at least one exact field, requirement, or supporting
document field and enter an instruction beside every selected item. During
`correction_required`, all other controls are locked in the Mini App and API;
the general **Edit application** action is unavailable. Resubmission returns to
the original checker. Another scoped checker must use **Take over re-check**
and give an audited reason before deciding it.

Before signing dispatch, the assigned officer can choose **Edit application**.
If Operations has already prepared a frozen packet, the officer must confirm
that it will be cancelled. If a checker already approved it, the same action
also invalidates approval, creates an in-app alert for that checker, returns the
application to Draft, and requires a new frozen packet and full review. No edit
action is available once signing has started.

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

### Prepare the reviewed Invoice Finance LAF

The complete field, validation, rendering, and signer mapping is maintained in
[Invoice Finance LAF seed reference](origination/invoice-finance-laf-seed.md).

Keep `LAFS/INVOICE FINANCE.pdf` outside Git. First create the global **Invoice
Finance** product and its commercial terms in Django Admin. Then run the safe
preview:

```powershell
.\.venv\Scripts\python.exe manage.py seed_invoice_finance_origination --actor <superuser-username>
```

If the summary is correct, apply it:

```powershell
.\.venv\Scripts\python.exe manage.py seed_invoice_finance_origination --actor <superuser-username> --apply
```

The command governs the approved canonical fields, replaces only an editable
draft (or creates a successor to a published definition), uploads the primary
PDF to restricted Drive, and leaves it unpublished. Open the resulting draft's
alignment builder to place the fields and signer slots, inspect the filled
sample, and publish. The source form's **ATTACH** checklist is deliberately not
converted into supporting-document requirements.

### Prepare the reusable Generic Jawabu LAF

The complete reusable-template contract is maintained in
[Generic Jawabu LAF seed reference](origination/generic-jawabu-laf-seed.md).
It includes every canonical field, repeatable table, manual Net Income value,
choice-checkbox mapping, signer slot, and guarantor evidence requirement.

Preview the operation:

```powershell
.\.venv\Scripts\python.exe manage.py seed_generic_jawabu_laf --actor <superuser-username>
```

Apply it only after reviewing the dry-run:

```powershell
.\.venv\Scripts\python.exe manage.py seed_generic_jawabu_laf --actor <superuser-username> --apply
```

The command uploads an unpublished reusable primary-template family. It does
not attach or overwrite a product. Calibrate and publish the template, then
explicitly select it from every compatible draft product definition and publish
those product definitions separately.

### Upgrade existing editable definitions to Commercial Terms

Published loan-form definitions and existing application snapshots are never
edited by the upgrade. Generate and review an exact signed manifest first:

```powershell
.\.venv\Scripts\python.exe manage.py upgrade_origination_commercial_contract --manifest-out .\commercial-upgrade.manifest
```

The report separately lists published products that need **Create editable next
version**. Apply only unchanged Draft targets with an active Superuser. Generate
a fresh v2 manifest; v1 manifests are deliberately rejected:

```powershell
.\.venv\Scripts\python.exe manage.py upgrade_origination_commercial_contract --apply-manifest .\commercial-upgrade.manifest --actor <superuser-username>
```

Apply is atomic and aborts on drift, missing/published targets, or a tampered
manifest. The manifest is a local operational artifact and must not be committed.

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
| Verified signing is disabled | Check all e-sign environment settings together. Sandbox and production gates intentionally fail closed when the environment, username, credentials, or enable flag disagree. |
| Signer is locked or the link expired | In the application's Verified packet signing panel choose **Reset / reissue** and enter the operational reason. Do not create an unaudited replacement. |
| OTP SMS says accepted but did not arrive | Provider acceptance is not delivery or verification. Inspect **Origination OTP challenges**, the delivery receipt/status, cooldowns, and carrier behavior; reset only when operationally justified. |
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
