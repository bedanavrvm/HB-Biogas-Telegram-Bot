# Scheduled Portal reports

Portal Pipeline, Outcomes and Finance reports can be emailed through Resend.
This is independent of Gmail credit appraisal ingestion. Sending is **off by
default**; this change does not configure DNS, contact recipients or deploy a
scheduler.

## Operator setup

1. Apply reviewed migrations `report_delivery.0001_initial` and
   `0002_alter_approvedrecipient_authorized_by_and_more` in your approved
   release process. It creates only delivery/configuration tables.
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

   This is an explicitly scheduled email runner, not a change to Portal Sheet
   publication. Without it, queued emails remain queued. No browser timer or
   request thread performs delivery. The minute cadence controls dispatch
   latency, not five messages per schedule every minute: each occurrence is
   reserved once. More than five ready recipient deliveries drain across later
   invocations; retries obey backoff.

## Staff controls

- **Portal Settings → Email reports → Send reports now**: visible only to IT
  (or active Superusers). Confirm to queue all active schedules within your
  complete grant scopes. The app remains usable. It cannot widen recipient
  scope or send arbitrary addresses. Expect dispatch on the next runner pass.
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
  database snapshot. Its PDF and XLSX serialize those same facts. Excel has the
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

Migration reversal: disable sending and stop the runner; export configuration
and history if required; run `python manage.py migrate report_delivery zero`.
This deletes this app's records, not Portal cases or external emails. Reapply
with `python manage.py migrate report_delivery`. Domain/DNS, provider delivery,
production migrations and scheduler operation require operator verification;
local tests do not prove them.

Provider contracts: [Resend send API](https://resend.com/docs/api-reference/emails/send-email),
[idempotency](https://resend.com/docs/dashboard/emails/idempotency-keys),
[Svix manual verification](https://docs.svix.com/receiving/verifying-payloads/how-manual).
