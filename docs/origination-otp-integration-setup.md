# Origination OTP Integration: Setup and Testing Guide

## Purpose

This guide explains how to configure and test verified OTP signing for the Loan
Origination Mini App. It covers:

- Africa's Talking Sandbox and production setup;
- how the main LAF and supporting loan forms must be configured;
- which phone number receives each OTP;
- self-service and assisted signing;
- signatures and production stamps;
- the expected signing and archival results; and
- troubleshooting and production-readiness checks.

This guide is for Django Superusers, Origination administrators, Operations,
and developers. Complete the Sandbox procedure with synthetic data before
enabling production SMS.

## What the integration does

For each external signer, the system:

1. freezes the reviewed application, main LAF, supporting documents, signer
   identities, field values, PDF mappings, and signature/stamp slots into one
   immutable signing package;
2. creates a revocable signing link for one signer role;
3. requires that signer to view every page in the packet;
4. captures a drawn or typed signature and versioned consent;
5. sends a six-digit OTP to that signer's mapped mobile phone;
6. applies the verified signature to every signature slot assigned to that
   signer across the whole packet; and
7. produces one hashed final PDF for restricted-Drive archival after all
   required signatures and stamps are complete.

One OTP verifies one signer across the complete packet. It does not verify a
different guarantor, witness, commissioner, or staff signer.

Africa's Talking delivery status is evidence about SMS delivery only. A
delivery callback can never verify an OTP, create a signature, or advance an
application.

## Sandbox and production are different

| Environment | Where messages appear | Which number to use |
|---|---|---|
| Africa's Talking Sandbox | The Africa's Talking web simulator/inbox. A real handset will not receive the SMS. | A Kenyan-format simulated mobile number registered in the simulator session. |
| Africa's Talking production | The actual Safaricom, Airtel, or other supported Kenyan mobile handset. | The real signer's own mapped mobile number. |

Do not use real customer names, national IDs, signatures, applications, or
phone numbers in Sandbox. Use clearly synthetic records.

Official references:

- [Africa's Talking Sandbox setup](https://help.africastalking.com/en/articles/1170660-how-do-i-get-started-on-the-africa-s-talking-sandbox)
- [Sandbox versus live environments](https://help.africastalking.com/en/articles/2189460-what-are-the-sandbox-and-the-live-environments)
- [SMS status and delivery-report meanings](https://help.africastalking.com/en/articles/16150386-messaging-error-codes)

## Part 1: Prepare the deployment

### 1. Install and migrate

Deploy the current requirements and migration:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py check
```

The integration uses the pinned `africastalking` Python SDK and migration
`core.0123_origination_verified_signing`.

Running the migration does not send SMS, upload documents, or modify existing
application payloads.

### 2. Create the Africa's Talking Sandbox application

1. Sign in to the Africa's Talking account.
2. Open the Sandbox application. The Sandbox dashboard is distinct from the
   live application.
3. Copy the Sandbox API key.
4. Open the Africa's Talking simulator.
5. Register a simulated Kenyan mobile number in the simulator. Use separate
   simulator sessions/numbers when testing more than one external signer.
6. Keep the simulator session open while sending the invitation and OTP.

The Sandbox username used by the SDK must be exactly `sandbox`.

### 3. Configure staging environment variables

Set these in Render or the approved staging environment. Do not put real keys
in `.env.example`, source control, Django Admin, screenshots, or documentation.

```text
ORIGINATION_ESIGN_ENABLED=True
AFRICASTALKING_SMS_ENVIRONMENT=sandbox
AFRICASTALKING_USERNAME=sandbox
AFRICASTALKING_API_KEY=<sandbox-api-key>
AFRICASTALKING_SENDER_ID=
ORIGINATION_SIGNING_LINK_TTL_HOURS=48
ORIGINATION_SIGNING_BASE_URL=
SENTRY_ENVIRONMENT=staging
APP_BASE_URL=https://<public-staging-host>
```

Important rules:

- `APP_BASE_URL` must be the public HTTPS origin without a trailing path, for
  example `https://example.onrender.com`.
- `ORIGINATION_SIGNING_BASE_URL` is optional. When set, it must be an approved
  HTTPS origin routing to this Django service and its host must be included in
  `ALLOWED_HOSTS`. Leave it blank to use `APP_BASE_URL`.
- Sandbox works only when `SENTRY_ENVIRONMENT` is one of `development`, `dev`,
  `local`, `test`, `testing`, or `staging`.
- Sandbox requires `AFRICASTALKING_USERNAME=sandbox`.
- Production requires `AFRICASTALKING_SMS_ENVIRONMENT=production`, a live
  non-sandbox username/API key, and `SENTRY_ENVIRONMENT=production`.
- Any mismatch fails closed and the Mini App reports that verified signing is
  disabled or not configured.
- New invitations use compact `/s/#<token>` URLs. The secret remains in the
  browser fragment so it is not sent to Django, Render access logs, or referrer
  headers. Existing `/origination/sign/#<token>` links remain valid. The
  Africa's Talking Sandbox report may display the URL as plain text; validate
  actual hyperlink behavior on controlled Android and iOS SMS clients before
  production launch.
- `ORIGINATION_TEST_SIGNING_ENABLED` controls the separate watermarked no-OTP
  simulator. When verified signing is correctly enabled, a newly prepared
  package is a verified package rather than a test package.

Redeploy the application after changing environment variables.

Africa's Talking Sandbox isolates SMS only. It does not turn Google Drive into
a test service. Point staging at an approved staging/restricted Drive folder,
or stop the acceptance test before **Archive signed packet**. Never archive
synthetic test output into a production customer-document folder.

### 4. Configure the delivery-report callback

In the Africa's Talking SMS application, set the delivery-report callback to:

```text
https://<public-host>/origination/webhooks/africastalking/delivery/
```

The URL must be publicly reachable over HTTPS. The endpoint accepts provider
delivery status and returns HTTP 200 for a valid callback. It does not authorize
or complete signing.

Immediate provider status such as `Accepted`, `Processed`, `Sent`, or `Queued`
does not mean the handset received the SMS. In production, only a later
`Success` or `Delivered` report confirms handset delivery.

## Part 2: Configure canonical signer fields

### Which phone number is used?

The OTP number is not taken from:

- the Telegram account;
- the officer who created the application;
- the reviewer;
- the branch settings;
- a global default; or
- the first phone-looking field on the form.

It comes from the canonical data field explicitly selected as **OTP phone** for
that signer role in the loan-form builder.

Examples:

| Signer role | Correct OTP phone mapping |
|---|---|
| Borrower | Applicant's own primary mobile phone canonical field. |
| Guarantor 1 | Guarantor 1's own mobile phone canonical field. |
| Guarantor 2 | Guarantor 2's own mobile phone canonical field. |
| Witness | Witness's own mobile phone canonical field, if the witness signs through OTP. |
| Commissioner for Oaths | Commissioner's configured mobile phone if treated as an external OTP signer. |
| BRO, Loan Officer, Officer, Branch Manager | No OTP session; these are authenticated staff-signing roles. |

Do not map every signer to the applicant's phone merely because that number is
already collected. Each external signer should control the phone used to verify
their own signature.

If two external signers genuinely share one phone, the system blocks dispatch
until a Django Superuser records a shared-phone override reason. This exception
is audited. It must not become the normal configuration.

### Accepted Kenyan phone formats

The canonical phone field must contain a Kenyan mobile number beginning with
mobile prefix `07` or `01`. The system accepts and normalizes:

| Input form | Normalized internal form |
|---|---|
| `07XXXXXXXX` | `2547XXXXXXXX` |
| `01XXXXXXXX` | `2541XXXXXXXX` |
| `7XXXXXXXX` | `2547XXXXXXXX` |
| `1XXXXXXXX` | `2541XXXXXXXX` |
| `+2547XXXXXXXX` | `2547XXXXXXXX` |
| `+2541XXXXXXXX` | `2541XXXXXXXX` |

Spaces, brackets, and hyphens are removed before validation. The outgoing SMS
uses the `+254...` form.

The following are rejected:

- Kenyan landlines such as `020...`;
- incomplete or overlong numbers;
- non-Kenyan country codes;
- numbers whose Kenyan mobile prefix is not `01` or `07`; and
- blank or non-numeric values.

In Sandbox, enter the simulated number registered in the Africa's Talking
simulator, using one of the accepted formats. Do not expect the OTP on a real
phone.

### Create or confirm canonical fields

In Django Admin:

1. Open **Configuration → Origination data fields**.
2. Search before creating a new field.
3. Confirm there is an active canonical name field for each signer type.
4. Confirm there is an active `Phone`-type canonical field for each external
   signer whose phone is collected separately.
5. Confirm National ID fields where the signer identity requires one.
6. Avoid duplicate fields that mean the same thing. Use aliases/labels for
   presentation differences.

Recommended semantic pattern:

| Meaning | Example canonical intent |
|---|---|
| Applicant name | `applicant_full_name` |
| Applicant phone | `applicant_phone` or the existing canonical applicant-primary-phone field |
| Applicant national ID | `applicant_national_id` or the existing canonical applicant-ID field |
| Guarantor 1 name | A canonical Guarantor 1 name field |
| Guarantor 1 phone | A canonical Guarantor 1 phone field with type `Phone` |
| Guarantor 1 national ID | A canonical Guarantor 1 ID field |

Use **Applicant** in data-entry UI. Use **Borrower** only for the contractual
signer role. Do not create separate Applicant, Client, Customer, and Borrower
fields when they represent the same person and value.

## Part 3: Prepare the main LAF and supporting forms

### PDF requirements

Each document template should be:

- a final, approved PDF rather than an editable draft;
- readable at phone width when previewed page-by-page;
- correctly oriented, with no unexpected crop or rotation;
- provided with enough blank space for mapped text, signatures, dates, and
  stamps;
- free of pre-filled real customer data;
- assigned a stable document key and clear name; and
- calibrated and published before the product is published.

The packet must contain exactly one primary LAF. Supporting documents are added
through the document packet and retain their own fields, pages, signature slots,
and stamp slots.

### Configure the form schema

From **Configuration → Origination product definitions**:

1. Open the editable draft version of the product.
2. Add the canonical fields required to complete the main LAF.
3. Organize fields into clear sections. Section keys are generated from section
   titles and should not be manually coded.
4. Add required/optional supporting documents to the **Document packet**.
5. Open the main LAF builder and each supporting-document builder.
6. Place every canonical field on the correct PDF page.
7. Preview populated sample output and confirm values do not overlap labels,
   lines, boxes, or page edges.

Do not type JSON in Admin to define ordinary form fields or signers. Use the
visual product builder and calibration builder.

### Configure each signer

In the product builder's signer section:

1. Choose the approved signer role.
2. Mark the signer required only when their signature is mandatory.
3. Choose **Signer name field** from the canonical catalogue.
4. For every external OTP signer, choose **OTP phone field**.
5. Choose **National ID field** where it is part of signer identification.
6. Add each signature or stamp slot with a stable key and understandable label.
7. Save before opening the PDF alignment builder.

When verified signing is enabled, publication rejects a required external
signature signer that has no canonical name and OTP-phone mappings.

### Align signature and stamp slots

For every slot:

1. Open the visual PDF alignment builder.
2. Draw or select the correct rectangle on the correct page.
3. Confirm the slot belongs to the correct signer role.
4. Set the signature appearance options such as alignment, padding, rotation,
   ink colour, typed font/size, or drawn-stroke width.
5. For stamps, configure the stamp slot and image-fit behavior. The actual
   governed stamp image is selected during signing.
6. Preview with synthetic data.
7. Save and publish the template calibration.

If the same signer role appears on the main LAF and supporting documents, the
system merges those signature slots into that signer's packet responsibility.
One successful OTP then completes all of that role's signature slots.

### Configure production stamps

In **Configuration → Origination stamp assets**:

1. Add a genuine transparent PNG, maximum 2 MB and 2000 × 2000 pixels.
2. Select environment `Production` for a production stamp.
3. Optionally restrict the stamp to a branch.
4. Make the correct version active.
5. Create a new version to replace an existing image; stamp bytes are
   immutable.

Only active production stamps matching the application branch appear during
verified signing. Test-only stamps cannot be applied to production packages.

### Publish in the correct order

1. Publish the calibration for the main LAF.
2. Publish each reusable supporting-document calibration.
3. Confirm every document assignment resolves to its intended latest compatible
   published template.
4. Run the product readiness checks.
5. Publish the Origination product version.
6. Create a new application for testing. Applications created before the
   publication retain their old schema and document snapshots.

## Part 4: End-to-end Sandbox test

### Test data preparation

Use:

- a clearly synthetic applicant name;
- a clearly synthetic national ID;
- the Kenyan-format number registered in the Africa's Talking simulator;
- synthetic guarantor/witness records and separate simulated numbers where
  those signers are present; and
- PDFs containing no customer data.

Do not reuse a production application.

### Test procedure

1. Open the Loan Origination Mini App as a scoped field officer.
2. Start a new application for the test product.
3. Complete every required field, including the exact canonical field mapped as
   each external signer's OTP phone.
4. Select any optional supporting documents needed for the test.
5. Complete and preview the main LAF and every selected supporting document.
6. Preview the full packet and verify page order and content.
7. Submit the application for review.
8. Open it as an authorized independent reviewer and approve it.
9. Open the reviewed application as authorized Operations staff.
10. Select **Prepare signing package**.
11. Confirm the panel says **Verified packet signing**, not **Non-production
    simulator**.
12. For the borrower or other external signer, choose **Send to signer's
    phone**. This remote self-service flow works from any location.
13. In the Africa's Talking simulator inbox, confirm the invitation contains the
    correct JBL packet reference and signing link.
14. Open the link. Confirm the address bar removes the secret fragment after
    loading.
15. Navigate through every page. Consent must remain disabled until every page
    has been opened.
16. Select **Draw** or **Type** and enter a synthetic signature.
17. Accept the packet consent. For assisted signing, also accept the explicit
    assisted-device statement.
18. Select **Send verification code**.
19. Confirm the OTP appears in the simulator inbox for the same simulated number
    mapped to that signer.
20. Enter the six-digit code within 10 minutes.
21. Confirm the signer becomes `verified` and all signature slots belonging to
    that role show complete.
22. Repeat with separate sessions/numbers for each remaining external signer.
23. Capture required authenticated staff signatures.
24. Apply every required active production stamp to its correct slot.
25. Confirm the application becomes `fully_signed` only after every required
    slot is complete.
26. Preview/inspect the completed packet.
27. Select **Archive signed packet** and confirm restricted-Drive archival.

Perform step 27 only when the deployment is configured with an approved staging
Drive folder. Otherwise confirm that the package reached `fully_signed`, then
stop without invoking archival.

### Assisted-signing test

For one synthetic signer, choose **Assisted signing** instead of sending the
link for self-service.

Confirm that:

- the ceremony opens on the officer's device;
- it clearly says the signer is using an assisted JBL device;
- the OTP still goes to the signer's mapped phone/simulator number, not the
  officer's number;
- the signer personally controls the signature, consent, and OTP entry; and
- the signer session records `assisted` mode and the assisting staff actor.

## Part 5: What to check after the test

### Mini App checks

- The correct signer name, role, and masked phone suffix are displayed.
- The full packet includes the main LAF and every selected supporting document.
- Page navigation works at 320 px mobile width without horizontal page-level
  overflow.
- Consent is unavailable until every page is reviewed.
- Draw and Type both work.
- Repeated taps do not create duplicate sessions, OTPs, signature actions, or
  archives.
- One signer's OTP does not complete another signer's slots.
- The queue/application shows `partially_signed` until all required slots are
  complete, then `fully_signed`.

### Django Admin checks

Use the Origination items in the Admin sidebar:

- **Origination signer sessions**: correct package, signer role, masked phone,
  access mode, status, and verification time.
- **Origination OTP delivery**: one challenge for the send request, expected
  delivery status, remaining attempts, expiry, and verification time.
- **Origination signing actions**: one immutable verified action per configured
  signature/stamp slot.
- **Origination signing packages**: correct package status, signed-document
  hash, archival status, and Drive reference after upload.
- **Integration operations** under technical records: Africa's Talking
  invitation/OTP operations and Google Drive upload operations completed or
  show a safe retry state.
- **Origination application events**: session creation, external verification,
  staff signing, stamping, and archive events have the expected actors/request
  IDs without raw OTPs, full phone numbers, tokens, or signatures.

The raw OTP and raw signing-link token must not appear in Django Admin or logs.
The signing link token is carried in a URL fragment and then an Authorization
header, not an HTTP path.

### PDF checks

Download or inspect the controlled test output and confirm:

- every signature is on the intended document, page, and rectangle;
- one signature is replicated only to slots belonging to the same signer role;
- typed signatures use the configured font/alignment;
- drawn signatures are legible and contained inside the slot;
- stamps use the correct active asset and branch scope;
- no overlay covers legal text;
- supporting documents are present and ordered correctly;
- the unsigned and final signed hashes are populated; and
- a Drive retry uses the retained signed bytes rather than changing the PDF.

### Negative tests

Run these with synthetic data:

| Test | Expected result |
|---|---|
| Omit an external signer's phone mapping | Product publication or signer dispatch is blocked with a clear message. |
| Enter an invalid/non-Kenyan/landline number | Dispatch is blocked. |
| Map borrower and guarantor to the same number | Dispatch is blocked until a Superuser gives an audited override reason. |
| Request OTP before signature/consent | Request is blocked. |
| Skip one packet page | Consent/signature save is blocked. |
| Enter a wrong OTP once | Attempts fall from 5 to 4; no signature action is created. |
| Replay the same failed verification request | The attempt is not deducted twice. |
| Enter five wrong OTPs | Session locks for 30 minutes. |
| Request another OTP inside 60 seconds | Resend is blocked. |
| Attempt more than three sends in 30 minutes | Further sends are blocked. |
| Enter an OTP after 10 minutes | Code is rejected as expired. |
| Change the signature after requesting an OTP | Previous OTP is invalidated; a new one is required. |
| Post a fake delivery callback | Delivery evidence may be ignored/updated, but signing never advances. |
| Reuse one idempotency key with different content | Request is rejected. |
| Open an expired/replaced signing link | Link is rejected; Operations must reset/reissue with a reason. |
| Apply a test stamp to a verified package | Action is rejected. |
| Apply a branch stamp to another branch | Action is rejected. |
| Make Drive unavailable after full signing | Signing remains complete; archive is marked failed and can be retried without re-signing. |

## Limits and recovery behavior

| Control | Current behavior |
|---|---|
| OTP lifetime | 10 minutes |
| Resend cooldown | 60 seconds |
| Sends per signer session | Maximum 3 in 30 minutes |
| Sends per phone | Maximum 5 per hour and 10 per day |
| OTP attempts | 5 |
| Lock after attempt exhaustion | 30 minutes |
| Signing-link lifetime | Default 48 hours; configured value is bounded to 1-168 hours |
| Public request throttle | Per opaque token and hashed source IP |

Operations can use **Reset / reissue** for an expired or locked session and must
enter a reason. A verified session cannot be reset because its signing actions
are immutable.

## Common problems

| Problem | Check |
|---|---|
| Verified signing is disabled | Confirm the enable flag, provider environment, username, API key, `SENTRY_ENVIRONMENT`, and redeployment. All must agree. |
| Sandbox SMS does not arrive on a real phone | This is expected. Check the registered number's Africa's Talking simulator inbox. |
| Nothing appears in the simulator | Confirm the simulator session is logged in, the same number is registered, and that exact number is in the signer's mapped canonical field. |
| `InvalidPhoneNumber` | Confirm a complete Kenyan `01...`, `07...`, or `+2541...`/`+2547...` mobile number. |
| `InvalidSenderId` | Leave Sandbox sender ID blank, or confirm the production Sender ID is approved and mapped to the live account. |
| `InsufficientBalance` | Sandbox/live account or product balance is insufficient. Production SMS is chargeable. |
| Invitation failed after session creation | Use the application's **Reset / reissue** action after checking the provider; give an audit reason. |
| Signer link says invalid/replaced | A newer active session exists, or the link expired. Reset/reissue through Operations. |
| Supporting signature is missing | Confirm the supporting document is selected, its signer role/slot is configured and calibrated, its template is published, and the application was created after publication. |
| Stamp is not listed | Confirm it is active, marked `Production`, and either global or assigned to the application's branch. |
| Provider says Sent but signer received nothing | Sent/Accepted is not Delivered. Inspect the later delivery report and carrier behavior. |
| Archive failed | Verify Drive credentials/folder access, then retry archival. Do not ask signers to sign again. |

## Production activation checklist

Do not switch to production until all Sandbox checks pass.

- [ ] Migration `core.0123_origination_verified_signing` is applied.
- [ ] Product and all supporting templates are published and previewed.
- [ ] Every required external signer has canonical name and own OTP-phone
      mappings.
- [ ] Signature and stamp positions were checked on every packet page.
- [ ] Self-service and assisted Sandbox tests passed.
- [ ] Wrong-code, expiry, resend, lockout, shared-phone, and retry tests passed.
- [ ] No raw OTP, token, signature, or full phone appears in application logs.
- [ ] Delivery callback returns HTTP 200 and cannot advance signing.
- [ ] Restricted-Drive archive and retry were verified.
- [ ] Access was tested using actual scoped officer/reviewer/Operations roles,
      not only a Superuser.
- [ ] Africa's Talking live username, API key, balance, and approved Sender ID
      are ready.
- [ ] Production environment variables are configured with
      `AFRICASTALKING_SMS_ENVIRONMENT=production` and
      `SENTRY_ENVIRONMENT=production`.
- [ ] A separately approved, small real-SMS smoke test is scheduled using
      controlled Safaricom and Airtel numbers.
- [ ] `ORIGINATION_ESIGN_ENABLED` remains easy to disable if the smoke test
      exposes a carrier/provider problem.

After the controlled live smoke test, monitor delivery reports, session
lockouts, provider failures, duplicate-phone overrides, and Drive archival
failures before expanding production use.
