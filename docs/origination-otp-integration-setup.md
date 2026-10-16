# Origination OTP Integration: Setup and Testing Guide

## Purpose

This guide explains how to configure and test verified OTP signing for the Loan
Origination Mini App. It covers:

- optional Advanta and Africa's Talking Sandbox/production setup;
- how the main LAF and supporting loan forms must be configured;
- which phone number receives each OTP;
- self-service and assisted signing;
- signatures and production stamps;
- the expected signing and archival results; and
- troubleshooting and production-readiness checks.

This guide is for Django Superusers, Origination administrators, Operations,
and developers. Complete the Sandbox procedure with synthetic data before
enabling production SMS.

## SMS provider selection and Advanta

Africa's Talking remains the default. Select Advanta for **new signing links**
only with these deployment environment values:

```dotenv
ORIGINATION_ESIGN_ENABLED=True
ORIGINATION_SMS_PROVIDER=advanta
ORIGINATION_ADVANTA_PARTNER_ID=<account-partner-id>
ORIGINATION_ADVANTA_API_KEY=<server-only-api-key>
ORIGINATION_ADVANTA_SENDER_ID=<approved-transactional-sender>
```

Store the values in the approved deployment secret store, never in Django
Admin or source control. Advanta must approve/assign the sender and enable the
transactional route for the account. Confirm account data-handling terms and
any outbound IP allowlist with the provider before production. No Advanta
sandbox, throughput guarantee or TTL control is assumed from the public docs.
Local tests mock all provider calls; live handset tests need explicit approval.

Each new external signing link captures its SMS provider. Invitations, OTPs,
resends and withdrawal notices all use that provider. Existing links are
classified as Africa's Talking by migration. Changing the selector requires a
normal deployment/restart and does not rewrite links or resend messages.
Keep original-provider credentials while its links remain active. Replaying a
create request returns the same link/provider; deliberately replacing a link
creates a new session using the current selector.

The configured account can rotate its API key. Delivery lookup stops if the
account identity changes: do not query an old message ID in a different account.
Review the original account manually and preserve its evidence. There is one
configured account per provider, not a multi-account routing system.

### Submission and delivery

Advanta sends JSON by HTTPS POST to
`https://quicksms.advantasms.com/api/services/sendotp`. Required fields are
`apikey`, `partnerID`, `mobile`, `message`, and `shortcode`. One request contains
one recipient; HTTP 200 is not acceptance without a valid successful recipient
result and matching number/message ID. The route supports OTP and other
transactional messages, not promotional traffic.

Delivery is fetched by authenticated POST to `/api/services/getdlr`, using
`apikey`, `partnerID` and the returned `messageID`. No new public Advanta
callback is exposed because the published callback contract does not specify
authentication. Existing Africa's Talking callbacks remain provider-scoped;
ambiguous message IDs are ignored rather than modifying multiple records.

The existing redacted Integration operations register retains provider,
submission/delivery state, message ID and safe error category. It never retains
OTP plaintext, message bodies, signing tokens, API credentials or raw responses.
Signer sessions in Origination Admin show their pinned provider read-only.

Authenticated staff signatures do not require SMS credentials. The signing
projection's existing `enabled`/`signing_available` flags describe the master
signing gate; the additive `delivery_available` flag describes new-link SMS
configuration. External link creation/sending still checks its relevant
provider server-side. These flags grant no role or signing authority.

- Accepted/queued/SentToNetwork is not proof of handset delivery.
- DeliveredToTerminal confirms handset delivery only, never signing/approval.
- Explicit rejection and uncertain submission are different failures.
- No automatic submission retry or cross-provider failover occurs. An unknown
  result may still arrive. A correct code remains usable until expiry, regardless
  of the delivery report. Explicit resend invalidates the previous code and
  remains subject to existing cooldown, phone, session and verification limits.
- Unknown invitation delivery is resolved by reviewing evidence and explicitly
  replacing the link if needed, not retrying the original send operation.
- Old withdrawal operations keep their historical attempts, but their automatic
  budget is reduced to one. Schema reversal intentionally does not restore an
  unsafe larger retry budget.

Official API references:
[send OTP/transactional messages](https://developers.advantasms.com/sms-api/send-otp.html),
[delivery lookup](https://developers.advantasms.com/sms-api/delivery.html),
[delivery statuses](https://developers.advantasms.com/sms-api/delivery-status.html),
[response codes](https://developers.advantasms.com/sms-api/codes.html).

### Scheduled delivery runner

Provision this command in the hosting scheduler **once per minute**:

```text
python manage.py process_origination_deliveries --apply
```

Without `--apply`, it only reports due work. Apply handles at most five due
lookups/notifications in a 50-second external-call budget. Expiring database
leases prevent overlapping runs from duplicating lookups or SMS submissions.
Receipt work never reopens the send operation. The existing approved-document
storage and Telegram work retains its own retry rules.

Advanta lookup times are 1, 3, 10, 30, 120, 480 and 1500 minutes after submission;
late runners resume the schedule without busy-looping. Definitive delivery or
failure stops polling; no report after the final check stays unconfirmed. This
does not extend the ten-minute OTP or invalidate an already verified signature.

Verify the `origination_deliveries` Durable job runner heartbeat is fresh with
all browser pages closed. The readiness command below reports stale runner,
missing original-provider credentials and account-change warnings without
making external calls. A warning does not block saving/editing/downloading an
application or verifying a valid code.

```text
python manage.py check_origination_signing_readiness --json
```

The release's pre-migration check reads Django's migration register first. If
`core.0206_advanta_integration` or `origination.0009_signer_sms_provider` is still
pending, it defers only the delivery queries that need that schema. Normal
configuration checks still run. After migration, `release.sh` rechecks signing
and delivery readiness before bootstrap or recording a completed release.

Outside that pre-migration phase, unapplied SMS migrations are a readiness error
that names the exact missing migrations and directs the operator to the normal
release process. A connection, permission or query failure instead reports
`origination-esign-delivery-database`; it never guesses that migrations are
missing. Database exception text, connection strings and credentials are not
printed. If migrations are recorded as applied but the queries fail, verify
database connectivity, permissions and actual schema consistency before retrying.

Local verification on 16 October 2026: 64 focused PostgreSQL checks passed for
the migration/register diagnostics, release sequencing, Advanta transport and
delivery handling. Tests include simulated connection/query failures, an actual
pending migration-register entry, redaction and post-migration release failure.
An exploratory 81-test run also hit the unchanged older consent-policy
expectation in `core.tests_production`; its service and test match HEAD.
No new migration, production deployment or real provider call was made.
Evidence: `test-results/origination-readiness-schema-final.log` and
`test-results/origination-readiness-schema-postgres.log`.

### Troubleshooting and safe rollout

| Safe diagnostic | Administrator action |
|---|---|
| configuration_required / invalid_credentials | Check the selected or link-pinned provider credentials in deployment settings; restart after repair. |
| invalid_sender | Confirm the exact approved sender and transactional-route permission with Advanta. |
| invalid_recipient | Have the owning officer check the signer's saved Kenyan mobile number; never substitute the officer's number. |
| network_not_allowed | Confirm the recipient network and account route with Advanta. |
| account_unavailable | Check the account's ability to send with the provider. |
| send_unconfirmed | Review provider evidence. A code may still arrive; do not blindly repeat the send. |
| account_changed | Restore/check the original account for old-message evidence; do not query it in the replacement account. |
| lookup_unavailable / report_unavailable | Keep delivery unconfirmed; check provider availability. This is not failed signing. |
| stale/never-run heartbeat | Provision/repair the once-per-minute runner, then check the existing records. |
| origination-esign-delivery-schema | Finish `release.sh` through its migration step, then rerun the signing readiness check. Only genuinely pending SMS migrations are listed. |
| origination-esign-delivery-database | Check the deployment's database connection/permissions; if migrations are recorded as applied, check actual schema consistency. Retry after repair rather than reapplying migrations blindly. |

Deploy first with `africas_talking` selected. Apply the checked-in migrations
through the normal release process; no staff role/shell repair is required.
Then configure Advanta in a controlled environment and explicitly authorize
handset checks for the borrower and two guarantors, invitation, OTP, resend,
withdrawal, network variation and delayed/failed delivery. Do not claim live
readiness based on mocked tests or screenshots.

Normal rollback sets `ORIGINATION_SMS_PROVIDER=africas_talking` and restarts.
Existing Advanta links still use Advanta; retain credentials until expiry or
authorized replacement. Preserve additive schema and historical evidence.
Before schema reversal, stop/expire active Advanta links and export evidence:

```text
python manage.py migrate origination 0008_unsigned_application_completion
python manage.py migrate core 0205_tat_publication_retry_capability
```

Older code must not serve active Advanta links. Production deployment and
migration remain separately authorized actions.

### SMS feedback verification

The approved implementation changes only SMS feedback wording in the existing
signing shell: requesting/sending is not labelled confirmed delivery. Saved
signature capture and code entry survive uncertain sends. No layout, tokens,
typography, permissions or new signing steps are introduced. The UI source
ratchet records this copy-only exception, not a foundation approval or Phase 6
migration. Synthetic light/dark 360px failure screenshots are produced by
`origination_signing_completion.spec.js` under ignored `test-results/playwright`.
Real Telegram/SMS behaviour still requires the authorized handset checks above.

Local verification on 16 October 2026 used synthetic fixtures and mocked
provider calls. The PostgreSQL acceptance selection passed 131 tests, including
provider concurrency, signing-plan/unsigned-completion behaviour and migration
upgrade/reversal. A refreshed provider-only run passed 27 tests and the signing
browser selection passed 31 tests, including light/dark uncertain-SMS recovery.
A fresh PostgreSQL selection of 72 access/notices/evidence/Portal/SMS tests also
passed; it distinguishes missing reference fixtures in reused test databases
from application regressions.
Source-ratchet, migration-graph, model/migration-drift, database-catalogue and
changed-module lint checks passed. These are implementation evidence, not live
SMS delivery evidence. Broader pre-existing failures are recorded in
`KNOWN_GAPS.md`; no production deployment or provider test was performed.

## What the integration does

### Signing feedback and exit

External signers review the documents, draw or type their signature and choose
**Save & send code**. Capture alone is not completion: **Finish signing** verifies
the SMS code and applies the signature. SMS failure retains the saved capture;
**Resend code** resumes verification under the existing cooldown and attempt limits.

Only server-confirmed completion shows **Signature saved**, its application
reference and Nairobi signing time. The short outcome distinguishes remaining
signatures/stamps, final approval and an approved application. It does not wait
for Drive archival. There is no separate acknowledgement action.

The acknowledgement closes the external signing context after ten seconds where
Telegram/browser closure is supported. **Close now** exits sooner; **Stay here**
cancels the timer. Ordinary tabs which cannot be closed show **You can close this
tab**. Staff signing returns to the application instead of closing the Mini App.
Assisted signing closes only the borrower's signing context, not the officer app.
Errors preserve input and never start the countdown. Retried uncertain saves
reuse their request key; a server-state check recovers a committed signature.

The simulator stays separately labelled TEST. Real staff signing never uses
synthetic-name prompts. Signer identity, consent, configured approval policies,
required stamps and independent approval restrictions are unchanged.

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

Africa's Talking uses the pinned Python SDK. Advanta uses the existing requests
dependency. The original signing schema is `core.0123_origination_verified_signing`;
provider selection adds `core.0206_advanta_integration` and
`origination.0009_signer_sms_provider` through the normal migration chain.

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
RELEASE_ENVIRONMENT=staging
APP_BASE_URL=https://<public-staging-host>
```

Important rules:

- `APP_BASE_URL` must be the public HTTPS origin without a trailing path, for
  example `https://example.onrender.com`.
- `ORIGINATION_SIGNING_BASE_URL` is optional. When set, it must be an approved
  HTTPS origin routing to this Django service and its host must be included in
  `ALLOWED_HOSTS`. Leave it blank to use `APP_BASE_URL`.
- Sandbox requires `AFRICASTALKING_USERNAME=sandbox`.
- Production requires `AFRICASTALKING_SMS_ENVIRONMENT=production`, a live
  non-sandbox username/API key, a funded account and an approved Sender ID
  (or an explicitly provider-approved shared sender).
- Logging/release labels describe the deployment, not the SMS account. Keep
  `SENTRY_ENVIRONMENT` and `RELEASE_ENVIRONMENT` as staging/testing when using
  live SMS for a controlled test; they do not enable or disable OTP delivery.
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
a test service. Final verified signing now schedules restricted-Drive archival
automatically after the local signing transaction commits. Point staging at an
approved staging/restricted Drive folder before completing every required slot.
Never archive synthetic test output into a production customer-document folder.

### 4. Configure the delivery-report callback

In the Africa's Talking SMS application, set the delivery-report callback to:

```text
https://<public-host>/api/origination/webhooks/africastalking/delivery/
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
5. Complete the main LAF and every selected supporting-document form.
6. Preview the full packet once and verify page order and content. This single
   preview satisfies the current revision's primary/supporting preview gate.
7. Submit the application for review.
8. Open the **Prepare** queue as authorized Operations staff and select
   **Prepare review packet**.
9. Open the **Review** queue as an authorized independent checker, select
   **Preview frozen packet**, inspect it, and approve that exact hash-bound PDF.
10. Open the approved application in **Signing** as Operations and select
    **Start signing**.
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
27. Confirm automatic restricted-Drive archival reaches `uploaded`. If the
    automatic attempt reports `failed`, use **Retry archival** after correcting
    the Drive configuration or transient outage.

Complete the signing test only when the deployment is configured with an
approved staging Drive folder. The signed packet remains locally complete when
Drive is unavailable, but its archival status will require attention.

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
| Verified signing is disabled | Confirm the enable flag, provider environment, matching username/API key and redeployment. Logging environment labels are independent. |
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

### SMS acceptance and delivery feedback

An SMS submission needs an explicit accepted result and a message ID. The
documented immediate codes 100, 101 and 102 mean processed, sent and queued;
none proves delivery to the phone. A rejected response is recorded as failed.
A missing/malformed response or network timeout remains unconfirmed, because
the message might still arrive. Raw SMS contents and provider bodies are not
copied into the integration error record.

Only a later `Success` or `Delivered` delivery report confirms handset receipt.
`Sent`, `Submitted` and `Buffered` remain accepted/awaiting delivery. Delayed
intermediate/unknown reports cannot overwrite a final delivered/failed result.
These callbacks never verify an OTP, add a signature or approve an application.
Historical delivery rows are not bulk-reclassified by this change; existing
signatures and signed documents are untouched.

Repeating the same request does not send another SMS and never changes an
unconfirmed/rejected send into success. For codes, wait for the existing
cooldown before requesting a fresh code; contact the JBL officer if the problem
continues. For failed invitations, correct the provider issue first, then use
the existing Reset / reissue action. Do not automatically retry a timed-out
send: it may already have been accepted and charged.

Provider references: [SMS response and delivery codes](https://help.africastalking.com/en/articles/16150386-messaging-error-codes),
[delivery stages](https://help.africastalking.com/en/articles/742491-why-did-my-messages-fail).

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
      `AFRICASTALKING_SMS_ENVIRONMENT=production` and the matching live
      application username/API key. Set logging/release labels to production
      only when the deployment itself is production.
- [ ] A separately approved, small real-SMS smoke test is scheduled using
      controlled Safaricom and Airtel numbers.
- [ ] `ORIGINATION_ESIGN_ENABLED` remains easy to disable if the smoke test
      exposes a carrier/provider problem.

After the controlled live smoke test, monitor delivery reports, session
lockouts, provider failures, duplicate-phone overrides, and Drive archival
failures before expanding production use.
