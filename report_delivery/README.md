# Mini App email reports

## Branded overview and filtered exports

New emails contain the management overview and one Excel attachment, not a PDF.
Project-owned templates provide JBL branding, key figures, readable dates and
report scope. A bare `REPORT_EMAIL_FROM` address gets the display name JBL BOT;
you can explicitly set `REPORT_EMAIL_FROM=JBL BOT <it@your-verified-domain>`.
Explicitly configured display names are preserved. Existing frozen submissions
retain their original bytes and attachments on retry.

The shared email layout uses Jawabu navy/green branding, compact coloured
headline figures, readable duration/percentage values and paired breakdowns.
Segoe UI/Helvetica Neue/Arial fallbacks use 16px body/table text, 14px supporting
labels, 18px section headings, a 26px title and 30px headline figures. Long
amounts get wider cards rather than reduced font sizes. On phones, ordinary
headline figures form two columns, financial figures use full width, and
breakdown tables stack.
The existing project logo is embedded as a local base64 inline attachment using
[Resend Content-ID](https://resend.com/changelog/embed-images-using-cid); no
remote image URL, tracking pixel or new hosting is needed. If the packaged logo
is unavailable, text branding remains and the report can still be sent.
The first three non-empty captured chart definitions are considered for offline
PNG graphs using the existing Pillow dependency. Up to eight categories and
four series fit the mobile renderer; longer/unreadable labels, unsupported
chart types and failed rendering fall back to HTML breakdowns. No captured
values are truncated or changed: breakdowns list every category, including
missing values, and remain visible when images are blocked. PNGs use the same
inline Content-ID mechanism as the logo. No interactive tabs, remote assets,
public links, browser process or additional dependency is required.
The Excel remains the only report file; logo/graphs are additional inline images.
The existing serialized 10-MiB ceiling includes all inline image bytes.
The attachment notice is not a fake download button or a public report link.
New formatting affects only emails, never captured metrics or workbook cells.
Actual Gmail/Outlook rendering and client-controlled dark-mode inversion still
require inbox verification; local browser previews are not that certification.

In Portal Reports, TAT Reports or Complaints Data Overview, tap the envelope
beside Excel export, enter one address and Send. The current applied filters,
including search/chart selections, are captured when the dialog opens. The
email uses the same native workbook exporter as Download Excel. It never
creates a recurring schedule or permanently approves that destination.
Existing export permission is required; schedule management remains IT-only.
Each reservation records its requester and destination; customer values and
email addresses are not included in diagnostic logs. Access is checked again
before disclosure; changed grants block the captured report rather than
silently broadening or narrowing it. Suppression also applies to one-off sends.

Close/Cancel/Escape/Telegram Back return to the existing report, without waiting
for delivery. Queued and Sending are not proof of delivery: Accepted means
Resend accepted it, while Delivered requires its signed webhook. Immediate
dispatch is best-effort and database-leased; a process restart or occupied
worker slots retains the queued work. Status checks and the existing processor
can resume it; this does not introduce an unattended retry scheduler.

Apply `python manage.py migrate report_delivery` through `0004_reportdelivery_one_off`.
Rollback command: `python manage.py migrate report_delivery 0003_remove_approvedrecipient_report_recipient_scope_unique_and_more`.
Disable sending first. Reversal is guarded if one-off evidence exists: retain
the additive schema when rolling back application code, or restore a verified
pre-release backup. No rollback automatically deletes disclosure evidence.
Production migrations or test emails require explicit operator approval.

Send now starts immediately after commit without a shell command. Delivery
progress appears in Settings; the web request does not wait for generation or
submission. The recurring scheduler remains a separate operator setup below.

## Mini App Settings: Portal, TAT and Complaints

Each app now owns its email report schedules and recipient approvals. Portal
offers Pipeline, Outcomes and Finance; TAT offers completed-period TAT outcomes;
Complaints offers complaints reported in the selected period with their current
resolution status. No cross-workflow customer joins are made.

IT opens **Settings → Email reports → Manage reports** in Portal/TAT. In
Complaints, the header **gear icon** opens the Settings panel. Add a report,
choose its cadence and Nairobi sending time, enter recipient addresses
(one per line), choose Active, and Save. Confirming approves those addresses
for that app and retained group/selected branch/product scope. The group is
kept internally, not exposed as a dropdown. Branches use configured scoped
choices, not free text. Blank scope fields mean the
whole selected group; narrower IT grants cannot approve broader scope.

The pencil edits a schedule; the send icon queues that schedule immediately.
The existing Portal Send reports now control queues all active Portal schedules
only. Closing Complaints Settings returns to the same screen and retains
unsaved fields. Credentials remain in deployment environment settings, never
in the Mini App. Suppressed addresses require explicit Admin review.

TAT reports use the existing Period Performance cohort and operational data-mode
rules. Complaints reports use reported dates; their resolution values are current,
not reconstructed historical status. Both Excel attachments are capped at 2,000
rows for scheduled reports, with full-scope counts stated in the email. One-off
sends retain the native download's limits (Portal 2,000; TAT 10,000; Complaints
uses its existing register export). One shared runner handles all apps.

Apply `0003_remove_approvedrecipient_report_recipient_scope_unique_and_more`:
existing schedules/approvals retain Portal ownership. Pause the runner and export
or remove TAT/Complaints configurations before reversing with
`python manage.py migrate report_delivery 0002_alter_approvedrecipient_authorized_by_and_more`.
Removing workflow ownership while retaining cross-app schedules is unsafe.

Portal Pipeline, Outcomes and Finance reports can be emailed through Resend.
This is independent of Gmail credit appraisal ingestion. Sending is **off by
default**; this change does not configure DNS, contact recipients or deploy a
scheduler.

## Operator setup

1. Apply reviewed `report_delivery` migrations through `0004` in your approved
   release process. These changes affect only delivery/configuration tables.
2. In Resend, verify an organization-owned sending domain using the DNS records
   it supplies. Configure SPF/DKIM and the organization's DMARC policy. Disable
   open/click tracking for this reporting domain.
3. Store `RESEND_API_KEY`, `REPORT_EMAIL_FROM` and `RESEND_WEBHOOK_SECRET` in
   Render's environment secret store. `REPORT_EMAIL_REPLY_TO` is optional.
   The sender must use the verified domain. Restrict the API key to sending.
4. Add a Resend webhook at `/api/report-delivery/resend/webhook/` for sent,
   delivered, delivery-delayed, bounced, complained and failed events. The raw
   body is verified using Svix HMAC and a five-minute timestamp tolerance.
5. In Django Admin → Scheduled reports → Approved recipients, explicitly
   approve each address and its group/branch/product disclosure scope. A blank
   branch/product permits the whole group. An email account is not a Portal
   access grant. Scope approval is required even for Workspace addresses.
6. Add a Report schedule, select its preset, group and narrowing filters, and
   assign approved recipients. Preview the PDF; queue a test to one assigned
   address. Enable the schedule only after checking its scope and output.
7. Set `REPORT_EMAIL_DELIVERY_ENABLED=True` and schedule this command **every
   minute**, using the deployment's approved scheduler:

   ```text
   python manage.py process_report_deliveries --apply --limit 5 --max-seconds 50
   ```

   This runner is for unattended recurring schedules, not Portal Sheet
   publication. **Send now does not require it:** after the reservation commits,
   a bounded background thread claims the requested reports and submits them.
   The HTTP request never waits for workbook generation or Resend. Settings checks
   display acceptance or a safe failure reason. Reopening Settings wakes pending
   work after an interrupted process; durable leases and provider keys prevent
   duplicate submission. Two workers per process, at most 50 claims per wake,
   protect the web service. Worker restarts can interrupt progress; this is not
   an always-on job service. The minute cadence controls unattended dispatch
   latency, not five messages per schedule every minute: each occurrence is
   reserved once. More than five ready recipient deliveries drain across later
   invocations; retries obey backoff.

## Staff controls

- **Portal Settings → Email reports → Send reports now**: visible only to IT
  (or active Superusers). Confirm to queue all active schedules within your
  complete grant scopes. The app remains usable. It cannot widen recipient
  scope or send arbitrary addresses. It starts immediate background processing
  and checks delivery status automatically. Provider acceptance is not proof
  of inbox delivery; verified webhooks establish Delivered status.
- **Admin schedule → Preview / Send / Pause**: preview makes no provider call;
  Send now queues all assigned recipients; Queue test queues only the selected
  approved recipient. Tests use real approved addresses when delivery is enabled.
- **Report deliveries**: shows queued/accepted/delivered/retry/failure states,
  safe issue codes, attempts and next retry. “Accepted” is provider acceptance;
  “Delivered” is delivery evidence, not read evidence.
- **Review retry**: reuses the exact payload and key for unaccepted, still-safe
  deliveries. A changed scope/configuration requires a fresh reviewed report.
- A bounced/complained-about email is suppressed across every approval for that
  address. IT must investigate and explicitly clear suppression after review.

## Period and data rules

- Default time is 08:00 Nairobi. Daily reports cover yesterday; Monday's weekly
  report covers the previous Monday–Sunday; day-one monthly reports cover the
  previous month; quarter reports run January/April/July/October day one and
  cover the previous quarter. Calendar boundaries include leap days.
- Pipeline is the **current backlog at generation**, not historical pipeline
  reconstruction. Outcomes uses activity in the completed period. Finance uses
  the period's matching cases with **current recorded financial values**, not
  historical cash flow. These bases are stated in attachments and email.
- Each recipient delivery captures summary, charts and case rows from one
  database snapshot. Its email overview and XLSX serialize those same facts. Scheduled Excel has the
  Portal's existing 2,000-row limit; summaries/charts cover all matching cases.
  Both row count and limit are shown. Narrow the scope when all rows are needed.
- Empty reports are sent unless Skip empty is selected. A failed report build
  never becomes an empty report. Email content exceeding the conservative
  10-MiB serialized payload ceiling fails instead of silently dropping files.
- After downtime, only the latest due occurrence is reserved. Older skipped
  occurrences are counted on the schedule; delayed generation is labelled.

## Reliability, privacy and recovery

- Every delivery is one recipient only. Complete current IT grant tuples and
  recipient approval are rechecked before capture and just before submission.
  Revocation, recipient edits, schedule revision changes and pauses block stale
  work. Admin permission defaults cannot bypass these checks.
- Workers claim a five-minute compare-and-swap database lease; provider calls
  use fixed HTTPS endpoints, 5-second connect and 20-second read timeouts and a
  per-delivery idempotency key. Network/provider temporary failures retry with
  bounded exponential backoff, at most six automatic attempts.
- Deleting an approving account clears its live approval reference and blocks
  pending sends; it does not prevent the existing staff hard-deletion workflow.
- Resend retains idempotency keys for 24 hours. At 23h55 after the first attempt,
  unresolved work becomes **Uncertain** and automatic retry stops. Inspect
  Resend's provider history before deciding whether a new manual send is safe.
  Never mark it failed and send again merely because the client lost a response.
- Signed webhook receipts are deduplicated, retain no recipient/body data, and
  reconcile even if the webhook arrives before the API response is persisted.
  Delivered/suppression evidence takes precedence over delayed/sent evidence.
- Report rows and exact base64 email payloads are erased after 30 days; delivery
  metadata and webhook receipts after 180 days. Each runner does bounded cleanup.
  When sending is disabled, continue retention with:

  ```text
  python manage.py purge_report_deliveries --apply
  ```

- Logs/error metadata contain safe categories, not provider response bodies,
  email addresses, IDs or customer report rows. PDFs fetch no URLs or files.
  Retained payloads are sensitive database data: apply existing backup/access
  controls. An email already delivered cannot be recalled by DB cleanup.

## Validation and rollout

Run `python manage.py test report_delivery core.tests_portal_report_insights
core.tests_portal_reporting` using the local PostgreSQL test profile for
production parity. All provider calls in tests are mocked and all cases are
synthetic. Run the Portal email Settings Playwright checks for mobile layout
and single-flight confirmation behavior.

Filtered send and presentation checks:

```text
python manage.py test report_delivery --noinput
npx playwright test core/tests_browser/report_email_export.spec.js core/tests_browser/portal_reporting.spec.js core/tests_browser/complaint_reporting.spec.js
```

These use synthetic data and mocked delivery. Browser email previews verify
layout, not Gmail/Outlook rendering or actual inbox delivery.

Full app removal (not a routine rollback): disable sending and stop the runner; export configuration
and history if required; run `python manage.py migrate report_delivery zero`.
The one-off evidence guard described above must be respected. This deletes this app's records, not Portal cases or external emails. Reapply
with `python manage.py migrate report_delivery`. Domain/DNS, provider delivery,
production migrations and scheduler operation require operator verification;
local tests do not prove them.

Provider contracts: [Resend send API](https://resend.com/docs/api-reference/emails/send-email),
[idempotency](https://resend.com/docs/dashboard/emails/idempotency-keys),
[Svix manual verification](https://docs.svix.com/receiving/verifying-payloads/how-manual).
