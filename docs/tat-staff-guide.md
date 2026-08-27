# TAT Mini App Staff Guide

The TAT Mini App tracks one loan case through its governed stages. Django is
the source of truth; the Google Sheet is an operational copy. Open the app from
the approved Telegram bot so Telegram can verify your identity.

## Your queues

- **Assigned to me** contains tasks where you are the named primary or active
  backup recipient.
- **Available to my role** contains cases your current role and scope permit
  you to action, even when another staff member received the first alert.
- **All cases** appears only when your permission includes the broader view.

Queue filters never expand your access. The count and Next/Previous controls
apply to the selected queue and filters. If a refresh fails, the app retains
the last confirmed queue instead of presenting an unverified empty list.

## Create, find, and update a case

1. Select **Create case**, then choose the product and branch before entering
   the client details. Monetary amounts are whole KES.
2. Review the confirmation and submit once. A retry after a slow connection is
   safe and must not create a duplicate case.
3. Use **Find** for case ID, client name, ID number, phone, branch, or BRO.
4. Open the case and complete only the stage actions offered to your role.
5. Review the confirmation before saving. The server validates the current
   stage, permission, prerequisites, workflow mode, and revision.

If the app reports that the case or workflow changed, keep your entered note,
refresh the case, review the newer values, and submit again only if still
appropriate. Never create a second case to bypass a conflict.

## Pilot, Production, and connectivity

- A visible **Pilot** banner means the case is test data in the current Pilot
  cycle. Do not treat it as an operational production case.
- Production cases remain operational when the current test cycle changes.
- A local save succeeds before Sheet publication. If the Sheet is unavailable,
  do not recreate the case; report the synchronization warning to IT.
- Switching apps or briefly losing connectivity should not invalidate the
  confirmed server state. Reopen the Mini App and refresh.

## Alerts and links

In **Settings**, select **Connect private alerts** to let the bot send personal
task links. A link may show expired or superseded when the case has moved to a
new revision; the app redirects an authorized user to the current task when
safe. Group alerts remain privacy-safe and must not contain customer details.

Contact the JBL administrator when your role, branch, product, or private-alert
status is wrong. Contact IT for repeated loading, Telegram, Sheet-sync, or stale
link failures. Include the case reference and time, not customer PII in chat.
