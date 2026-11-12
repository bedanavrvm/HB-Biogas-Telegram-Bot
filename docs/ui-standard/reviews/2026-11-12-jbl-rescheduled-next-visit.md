# JBL rescheduling and visible visit evidence

User-approved scope: rescheduled outcomes require a next visit date; due visits
must remain actionable. The follow-up requests remove the outcome-only helper
sentence and keep optional evidence open at all times.

## Source-bound change

The visit form reuses its current two-column field grid, native date picker,
inline validation, compact section labels, upload rows and sticky Save action.
Optional evidence is a permanently visible labelled section. Its heading sits
outside the upload card, separated from Comment; there is no disclosure control.
Required evidence/location still follows the forwarding outcome and existing
permissions. The intake-only new-lead deposit hold retains its existing controls.

Rescheduled requires Next visit date, today or later in Nairobi, on both client
and server. The date is separate from a completed physical visit and from the
existing deferral/reappraisal deadline. Saved field drafts restore the date.
The case remains in the JBL queue. Future appointments do not create premature
action reminders; today's and overdue appointments appear once in the existing
notification bell and Home actions, within the viewer's authorized scope.
Replacing the outcome, withdrawing or resetting for reappraisal clears the active
schedule while preserving history. Legacy records receive no invented dates.
Migration 0215 adds the nullable planned date with a database purpose comment.

## Observed local evidence

Playwright ran the real Django Portal shell, signed synthetic Telegram identity,
authorization, draft endpoints and case saves against isolated PostgreSQL.
Remote hosts were blocked and Google transports disabled. Host theme variables
were supplied for the dark check, as Telegram normally supplies them.

Artifacts in `test-results/reschedule-review/` (ignored, synthetic data only):

- `desktop-evidence-open.png`: 1280 x 1000, light.
- `mobile-evidence-open.png`: 390 x 844, light, deposit-held existing case.
- `mobile-dark-evidence-open.png`: 390 x 844, dark, existing LAF case.
- `results.json`: interaction assertions and database readback.

All three screenshots were visually inspected. Each has an 11px gap after the
comment card and a media heading above the upload card, with no horizontal page
overflow. The checks verify visible evidence for Rescheduled and Rejected by JBL,
no collapse affordance, hidden verbose helper, required/minimum-date feedback,
retained date across outcome switches, durable desktop draft recovery, and a real
successful save. Database readback retains the planned date without inventing a
physical visit date or officer. Real dashboard responses include the due case
and exclude the future appointment from action reminders. No page errors occurred.

All 107 tests passed across `core.tests_jbl_outcome_requirements`,
`core.tests_portal_dashboard`, `hb_operations.tests_deposits` and
`core.tests_visit_repayment` on a freshly migrated local PostgreSQL test database.
They cover invalid dates before uploads, Nairobi midnight, replay after the
appointment date, stale revisions, audit/clearing, permission scope and deposit
rules. The 11 focused Playwright camera/repayment regressions also passed after
replacing obsolete disclosure clicks with direct evidence-visibility assertions;
the existing repayment check now verifies the required rescheduling field and
absence of a collapse control. Ruff, JavaScript syntax, UI source ratchet and
migration drift checks passed.

This is local implementation evidence. Production deployment, physical Telegram
camera behavior and real Google uploads were not checked. No Phase 6 migration,
new workflow permission or standalone browser activation is implied.
