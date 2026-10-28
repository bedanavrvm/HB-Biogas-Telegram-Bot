# Complaints browser background publication

The browser commits the complaint/action, validated original file bytes and
publication jobs in one Django transaction. A confirmed save lets staff leave
the page. Google Drive and enabled Google Sheets projections then run through
the existing integration ledger. Telegram retains its current behavior.

## Deployment requirement

Apply the checked-in `complaint_publications` migrations through the normal
release process. Configure an independent scheduled worker **every minute**:

```sh
python manage.py drain_complaint_publications --apply --limit 10 --max-seconds 50
```

Without `--apply`, the command only counts due work: it makes no provider calls
and deletes no staged bytes. The worker uses the deployment's existing database,
Google credentials, Drive folder rules and Sheet projection configuration. No
new browser credential or storage service is needed. Concurrent workers claim
and fence jobs through PostgreSQL; a live transfer renews its lease. Restarted
transfers query their retained resumable session and reconcile remote acceptance
with a stable operation marker before creating a new object.

This schedule has **not** been commissioned by this change. Keep the existing
default-off browser release flags and follow the staff browser production
runbook before release. Building assets alone does not start a publisher.

## Progress and recovery

Each file has one percentage: measured browser receipt contributes 0–49%, the
validated durable Django receipt is 50%, acknowledged Drive bytes contribute
50–99%, and a verified result committed to canonical evidence is 100%.
The saved-record panel polls while visible/online and offers explicit refresh.
It distinguishes a queued file, scheduled retry, unavailable publisher and
failure needing Complaints IT. Successful files remain usable independently.

Transient provider failures use eight attempts, exponential delay from one
minute up to one hour, jitter and any longer provider `Retry-After`. A rate-limit
403 is transient; authorization errors are permanent. Disabled groups or Sheet
projections pause work without consuming the retry budget. Existing integration
circuit protection and short external-call budgets still apply.
Where a legacy Sheet adapter returns only `False`, the worker treats that as
temporary unavailability and uses its bounded retry schedule; provider-specific
headers cannot be recovered from a boolean result.

An active Superuser or staff with the **Complaint Cases IT** role may review
Workspace tools → Publication needs attention or Django Admin → Complaint
publication files → Needs attention. Other workflow IT grants supply no access.
Restore publisher health or correct provider configuration first, then use
**Retry failed publication**. This creates an audited successor job; failure
history, canonical records and evidence identities survive. Do not clear live
leases, delete retained payloads or ask staff to re-enter a saved complaint.
No outbound alerts or notification centre is introduced.

## Retention and rollback

Successful temporary bytes become eligible for bounded cleanup **24 hours after
verified publication**. Private resumable URLs are removed with those bytes.
Unpublished committed originals have no automatic expiry: retain them until IT
resolves the publication. Uncommitted staging attempts expire after 24 hours.
Receipts follow the owning complaint's governed retention/deletion closure.
Raw file bytes and resumable URLs are excluded from the browser JSON, logging
and Admin fields.

Monitor the `complaint_browser_publications` runner heartbeat, due backlog,
dead-letter jobs and retained payload storage. A heartbeat older than 15 minutes
produces an in-app diagnostic. Run cleanup through the scheduled command; each
pass is bounded to 100 abandoned attempts and 100 successful payloads.

Roll back application code without dropping these tables. Reversing the initial
migration refuses a populated upload ledger to preserve originals and receipts.
Removing that guard or deleting the ledger requires a separate reviewed data
retention decision. Consider Telegram adoption only in a future authorized task.

Design decisions and local verification:
[design record](../../browser/STITCH-DESIGN-DECISIONS.md),
[source-bound review](../ui-standard/reviews/2026-10-28-complaints-stitch-components.md).
