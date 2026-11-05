# Complaints correction without a manual reason

The user explicitly removed the correction-reason step on 5 November 2026.
Telegram and standalone browser retain their current compact IT correction
forms, with the reason field removed. Save directly submits the edited fields.
The shared service accepts an omitted/blank reason and automatically labels the
audit action. Older clients may still supply a bounded note. Existing actor,
time, before/after values, request-key replay, revision, scope, value validation
and Sheet queue behavior remain in the owning service. Reopening a complaint
still requires its separate reopening reason.

This supersedes the required-reason interaction in the 4 November historical
reporting/correction review. No restyling, baseline replacement, new tokens,
Phase 6 migration or workflow grant change is included.

Local verification uses actual Django signed-Telegram and company
password/MFA/CSRF routes against disposable PostgreSQL, driven by Playwright.
The journey saves an unassigned historical category through Telegram, then a
location detail through the staff browser; neither request contains a manual
reason. Readback checks category linkage, both audit events, retained original
status/resolution/clocks and persistence after reload. It also exercises exact
replay, stale revisions, invalid category rejection and non-IT denial.
Desktop/mobile and browser light/dark captures are in
`test-results/complaint-note-free-browser/`, alongside browser and DB results
and source hashes. This is local synthetic evidence; no live Google write,
deployment or physical-device acceptance is claimed.
