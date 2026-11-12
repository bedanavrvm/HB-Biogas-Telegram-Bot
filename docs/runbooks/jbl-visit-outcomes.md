# JBL visit outcomes and documents

Implemented 12 November 2026 under the approved visit-outcome plan.

## Recording an outcome

Choose the outcome first. For Rescheduled, Deferred / On Hold, Rejected by JBL,
Opted for Cash, or Opted for Other Partner, select whether a physical visit
actually took place. Outcome-only saves require no visit date, officer, deposit,
GPS, county, constituency, village, ID, LAF or supporting photo. The existing
outcome reason/comment rules still apply. Withdrawn continues through its stage
status action.

A physical unsuccessful visit needs its actual date, subject to the existing
HBG chronology and future-date checks. It does not require successful-visit
evidence. Outcome-only saves preserve any earlier real visit date and officer;
the separate audit event records the decision actor and time. They do not earn
visit performance points or enter My Visits as a new physical visit. Reports
retain the earlier physical visit outcome instead of labelling it with a later
phone decision. Existing historical facts are retained.

Forwarding to credit still needs a physical visit, the deposit gate, governed
county/constituency and village, Client ID, LAF, a supporting photo, and GPS or
the existing location-unavailable explanation. Phone outcomes cannot advance
to credit. Pre-visit deposit holds sort last before pagination, including when
Newest ordering is selected. Open a held card to record an outcome; the
forwarding option remains disabled. An unsuccessful physical visit at the JBL
stage does not remove the deposit hold or prevent HB from recording the payment
needed to proceed. Existing role, group and branch authorization remains.

Creating an office lead retains its required intake identity/location. A new
lead below the deposit threshold is saved as intake awaiting HB payment; open
that saved case to record a later outcome.

## Repayment terms on the LAF

Repayment day (1-31) and Period (months, 1-120) are entered by the JBL officer
below the media section. A complete selected LAF (PDF/image or both captures)
or an already stored LAF reveals the fields. A partial capture does not.
The officer reads the agreed values from the document; there is no automatic
extraction. Valid existing values are prefilled.

Both fields are required before forwarding to credit. The server checks them
before uploading evidence and saves them atomically with the visit and audit.
Negative/paused outcomes do not require them and preserve earlier saved terms.
Removing an unsaved LAF hides the inputs but keeps their draft values; selecting
it again restores entry. Draft field recovery includes both values, but uploaded
file bytes still need selecting again after closing the app.

Head of Rural reviews the terms in a compact summary. Edit repayment terms opens
an explicit correction, saved with the final review and recorded before/after in
Case History. Closing the correction omits those keys so the ordinary decision
cannot clear the terms. Existing cases missing values can still be completed
here. No case is backfilled or given invented terms. Existing Sheet, order and
payment columns continue to use the same case fields. No migration is required.

## Uploading evidence

Upload one complete file per Client ID or LAF:

- One complete, unencrypted PDF containing one or two pages.
- One clear image containing the complete document, converted locally to PDF.

For separate sides/pages, use Capture photos. The camera guides ID front/back
and LAF page 1/page 2. Tap a captured preview to review or retake that page.
The regular upload picker does not ask for separate sides or pages.

Review that both sides/pages are present and readable. The app does not infer
missing content or split/crop a combined image. File type, decoded image limits,
PDF bounds, size budgets, private access and content-hash deduplication remain.
A complete file and named page captures cannot be supplied together for the same
document. Switching outcome preserves selected files.

For a non-forwarding outcome, the outcome commits before optional evidence is
processed. An incomplete capture, invalid document or failed provider call leaves
the outcome saved and shows the pending evidence with Retry evidence only.
Correct or remove the affected selection, then retry. Successful categories are
removed from the pending selection. The same receipt prevents a second outcome;
existing content hashes prevent duplicate external uploads. Selected file bytes
last only while the form remains open. Closing the app does not undo the saved
outcome; files not yet saved need selecting again.

New case-linked uploads use searchable private Drive names, for example:
`2026-11-12 Synthetic Client LAF JBL Visit ID-12345678 JBL-42 01.pdf`.
Names are path-safe and bounded; file type/date/sequence distinguish evidence.
Original source names remain in MediaAttachment audit history. Existing files
are retained; this change does not perform a retrospective Drive rename.

## Local verification boundary

Synthetic PostgreSQL checks cover phone/physical outcomes, deposit holds,
chronology, replay, scoped denial, optional failure/retry, document validation,
report facts and no visit performance points. Naming tests exercise the actual
upload orchestration with only Google Drive transport replaced. The real Portal
shell was checked at desktop and 390px mobile widths with signed synthetic
Telegram identity and PostgreSQL readback. Production Sheets/Drive were not used.
