# Origination UI, application copies and JBL Apps

## Deployment

Ship the signature-font manifest, four bundled fonts and licences together.
The exact JSON exception in `.gitignore` permits the public manifest without
allowing other credential/configuration JSON files. `build.sh` verifies all
font hashes and renders each style before collecting static files. No database
migration, access-grant change, new provider or runtime font download is needed.

After deploying and checking `/apps/` in Telegram, set the bot's Main Mini App
URL in BotFather to the deployment's `/apps/` URL. This is separate from the
private-chat menu button and pinned JBL Apps messages. The Bot API menu-button
command cannot change the Main Mini App destination. Named Mini App URLs stay
unchanged. Archived Order Approval routes still return 410 and offer JBL Apps.
No Telegram configuration or production deployment is performed by local tests.

The chooser validates fresh Telegram identity and lists only destinations
allowed by the user's current workflow-specific grants. A shared role name
grants no cross-app access. Multiple authorized groups expand within their app
card. Destination APIs independently recheck permissions.

## Application copies

The download icon opens a compact chooser: All documents, Main LAF and each
selected supporting document. All documents retains the original combined PDF;
individual choices include only that document. These are not attachment/ID-copy
exports. An individual filename adds the document name before the timestamp.

Missing required details produce a Download/Cancel confirmation. Confirmation
applies to that saved revision and does not waive malformed supplied values,
signing requirements, source integrity or authorization. The application stays
in its current state. Approved copies contain the exact signed document bytes.

Names use applicant, product, requested amount and Nairobi preparation time:
`Applicant Product KES 100000 14-10-2026 15-30-00.pdf`. Missing details fall back
to the application reference and `Amount not set`; no number is invented.
Retries of the same request retain their filename. Links expire after 15 minutes
and recheck the saved revision and current access for both GET and HEAD.

Telegram receives the same filename as the HTTP attachment. Responses declare
PDF content, correct byte length, no-store/private caching and the Telegram Web
origin header. Native confirmation means download requested, not completed.

For approved applications, individual copies use captured page boundaries from
the verified signed original, including historical notice-page offsets. If an
older application lacks safe boundaries, use All documents. Do not reconstruct
or re-sign the document to provide an individual copy.

## Signature-free applications and replacement documents

Publishing a document without signers no longer excludes it from the application
catalogue. A new application captures the exact Main LAF selected by the officer;
older versions are not substituted and existing applications are not upgraded.
The active published document must still explicitly allow the chosen product.

When no selected document requires signatures, preview the saved document
bundle and choose Complete application. The result is Completed, not Approved.
The application is locked, no signing links are created and its unsigned copies
remain downloadable. Required fields, entered-value validation, lending terms
and required evidence still apply. A selected supporting document with required
signatures retains signing instead. See ADR 0054.

An exact replacement independently published in the Document editor no longer
leaves a stale unpublished-changes notice on its product. Genuine pending
removals, unpublished replacements and unconnected replacements still require
their normal product action. No publication history or application is rewritten.

Several distinct supporting documents can be selected. Repeating one template
for two guarantors is not implemented: do not assume one guarantor form creates
two person-specific legal documents.

Deploy migration `origination.0008_unsigned_application_completion` with the
normal migration step and the versioned static assets. No seed, role-grant shell
command, environment switch or provider configuration is required.

## Real-device verification

Use a synthetic application, not customer data:

1. Download an incomplete copy, cancel once, then confirm. The native dialog
   must name the PDF; the application must remain editable and unsigned.
2. Open the PDF from Telegram Downloads on Android and Desktop/Web. Check every
   page and the device's Open with action. If opening fails, retain a redacted
   screenshot, Telegram version and whether the saved file opens outside Telegram.
3. Download an approved copy and compare its bytes with the signed source.
4. Test all four typed styles, long names, and a borrowed phone/browser session.
5. Check queue filters, signing rows, native/fallback buttons and previews in
   light/dark modes, including the smallest supported mobile viewport.

The app does not control Telegram's downloaded-file viewer or OS associations.
Local intercepted-browser tests cannot certify this client-owned behaviour.

## Local verification record - 14 October 2026

- Backend: 85 passed, one PostgreSQL-only signing concurrency check skipped on
  isolated SQLite. Covers copy confirmation/retries, filenames, access denials,
  asset failures, signing obligations, identity copies, routes and throttling.
- Browser: 185 passed across Origination, Complaints, Portal and JBL Apps;
  four final dark-mode/toolbar rechecks also passed. Screenshots at 320-1280px
  were inspected, including native/fallback actions, queue identifiers, filters,
  internal/public signing and previews. No customer data was used.
- Django checks, migration drift, Python/JavaScript syntax and whitespace pass.
  The four-style signature preflight passes. Ruff is not installed locally.
- Artifact/privacy audit: 19 unchanged HEAD allowlist hash mismatches remain in
  the logo and older Portal screenshot baselines; see `KNOWN_GAPS.md`.
- Not verified: production deployment, BotFather cutover, real Telegram download
  opening and PostgreSQL concurrency. The full repository suite was not run.

## Local verification record - 15 October 2026

- Affected backend suites: 170 passed, two PostgreSQL-only concurrency checks
  skipped on isolated SQLite. Includes document selection, signed page extraction,
  historical notice offsets/tokens, unsigned completion, normal draft save,
  required supporting signatures, authorization, setup and queue filters.
- Browser: 59 passed. Screenshots of the download chooser were inspected at
  320px light, 390px dark and desktop widths; the completed unsigned view was
  also inspected. Tests use synthetic applications and intercepted local APIs.
- Django configuration, migration drift, Python/JavaScript syntax and diff checks
  pass. Migration 0008 applies in the test database; no records are backfilled.
- Artifact/privacy audit: 17 allowlist hash mismatches remain in the existing logo
  and Portal screenshots. `git diff --quiet HEAD` confirms these files are
  unchanged by this work. No allowlist hashes were weakened or replaced.
- Production deployment, PostgreSQL concurrency and real Telegram file opening
  are unverified. No external storage, email, SMS or Telegram writes were made.
