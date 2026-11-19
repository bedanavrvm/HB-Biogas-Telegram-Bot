# Corrections, cleared fields and Sheet refresh

Updated 17/11/2026.

In Complaints, open the pencil beside Complaint Details. County and Constituency
use the existing location catalogue; changing county clears an incompatible
constituency. Village / Landmark stays free text. Optional fields can be cleared;
required identity/complaint fields retain their validation. Historical locations
outside the current catalogue remain visible until explicitly corrected. A
failed catalogue lookup retains the draft and offers Retry.

Saving records the previous and replacement values in Django before publication.
The complaint history displays removals as `Village / Landmark: Previous Value →
Not set`. Reported/resolved dates display and accept `dd/mm/yyyy HH:mm`, with a
calendar button and Nairobi time. Google date cells display `dd/mm/yyyy`.

Complaint publication now includes all editable biodata, locations, description
and dates, as well as status/comments. Explicit blanks clear owned cells;
omitted fields in a correction request leave the saved value unchanged. Stable
Complaint IDs, unrelated columns and formulas are not editable through this path.
Portal retains its existing Master Data/Eco-conserve/internal-order projection
semantics. Both writers check affected cells after publication, including blanks,
before reporting success. Readback mismatch leaves the publication retryable.

For an old Sheet row that still differs from the correctly saved case:

1. Open Complaint Details, or Portal / Complete Case History.
2. Select **Re-sync to Sheet**. The action requires that workflow's existing
   publication retry permission and current case scope.
3. Check publication status. This queues the latest saved snapshot without
   another edit, workflow transition or duplicate correction-history entry.

An active job is reused; its lease/backoff is preserved. A completed job can be
followed by a new audited refresh. Repeated requests with the same request key
are idempotent. Publication workers/pumps must still be running and the group's
Sheet projection enabled. Deleted records cannot be restored by stale jobs.

The Complaints client-facing biodata notice says Master Data; the exact source
case reference remains in internal attribution. No production repair or bulk
re-sync is run automatically by this change, and no new permission is granted.
