# Portal reset and diagnostic connection recovery

`portal_read_only_maintenance` means the operator maintenance gate is active.
It is independent of a legacy upload's cutover hold. GET requests can succeed
while writes and the publication pump return 503. Diagnostic telemetry errors
do not explain or release that maintenance state.

After deploying the checked-in fixes, retry the reviewed reset only if the
selected owner's Portal data is still intended to be removed. Reset requires
an active Superuser, exact group confirmation and a verified backup reference.
It includes that owner's saved legacy import progress. Retained media audits
with missing farmer/attachment links are preserved with their snapshots; genuine
cross-owner live links still block before Sheet deletion. Do not manually delete
audit evidence merely to pass the ownership guard.

If keeping the existing import, resolve the reason maintenance was enabled before
returning to writes. Authorized IT uses **Settings → System readiness →
Maintenance mode → Live → Save maintenance mode**. Completing a retried reset
does not automatically remove a maintenance mode that was already enabled when
that retry began. IT can save this setting even while a legacy cutover hold is
active. The setting shows the actual maintenance mode independently of overall
readiness; a missing document template can still make readiness Down.
Confirm the selected maintenance mode before importing again.
Then select the original register and saved upload. Earlier unsynced commits
enter FIFO sync; reupload is unnecessary unless that import was explicitly reset.

Diagnostic database reconnects are deliberately limited to the two idempotent
telemetry routes. A second failure returns 503 with an empty acknowledgement and
five-second retry guidance. The browser retains the unacknowledged events and
honors the delay. This does not authorize a generic POST retry for approvals,
financial values, documents or provider writes.

The observed public legacy importer JS and CSS matched the latest checkout even
when an existing client used older URL query versions. Confirm response bytes or
content hashes before diagnosing an incomplete deployment from `?v=` alone.
The shared diagnostics URL advances to v6 for its backoff behavior change.

Local verification and screenshots are recorded in
`../ui-standard/reviews/2026-11-03-diagnostics-db-and-media-reset-recovery.md`.
