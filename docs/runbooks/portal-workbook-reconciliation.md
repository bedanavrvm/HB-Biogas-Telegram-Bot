# Reviewed workbook reconciliation

Use Portal > Legacy import > **Update Existing Cases** for a later workbook version.
Select its Portal owner and either Master Data or Eco-conserve. Each register has
its own saved session. This mode never deletes a case, clears a Sheet or creates
a register-wide maintenance hold.

## Review and apply

1. Upload the XLSX, accept the mapping, then let the bounded comparison finish.
   Reopening the same file/register resumes its existing session.
2. Review the changed-only table. Open Row to select individual fields or choose
   **Keep current position** / an explicit current position. The source facts
   remain retained even when a different position is chosen.
3. For Rescheduled, enter an exact next visit date as **dd/mm/yyyy**. A past date
   or a vague phrase such as "next week" cannot silently become a future reminder.
4. Select reviewed changes and apply. Saved revisions queue through the native
   Sheet publisher; the page separately counts applied, synced and awaiting sync.
   Reopen/resume if interrupted. A stale case must be compared again.

Select All excludes rows held by invalid values or conflicts. An authorized IT
reviewer can select an independently safe comment/field while leaving an unrelated
financial difference unchecked. A blocked position cannot be forced by checking it.
Identity conflicts and duplicate source matches require an exact reviewed match;
a shared National ID is not enough to choose between units.

## Rules for this reconciliation profile

- The first Decision/Action is the reported outcome; a second is guidance.
  Jawabu Final Position is ignored. HB Action and November comments guide review
  and append notes; they never establish completed installation or commissioning.
- Newly reported Approved enters **Credit Analysis**, with no invented approval
  actor, approval time, signed order or officer visit credit.
- A current request for family discussion/more time overrides a contradictory
  Approved guide. Unknown hold start/expiry dates stay unknown.
- Explicit cash/other-financier/withdrawal outcomes retain their reported meaning.
  Installation instructions and existing source order references require their
  owning workflows; the importer never allocates a replacement order number.
- Blank source cells preserve existing values. Missing rows never delete cases.
  Equivalent phone, money, dates and retained reviewed cleanup avoid needless review.
- Notes append without replacing the original history. The audit retains source
  hash, worksheet/row, selected facts, before/after values, actor and review time.
- Historical cases remain historical. FarmUp cases remain FarmUp; this update does
  not attach an initial LegacyRow to an app-created case. New current intakes use
  validated FarmUp/office intake instead of bypassing missing biodata as history.
- A repeated accepted source fact does not undo a later app change. Reconciliation
  checks the case revision under lock. Native closure needs its owning resume
  action; expired deferrals need reappraisal. Existing order membership, invoices,
  payments, final decisions and HB progress block inappropriate stage replacement.
- Externally reported date-only timing is labelled as an external spreadsheet
  estimate and excluded from measured SLA targets. Missing endpoints stay unknown.
  A later genuine app milestone can resume native timing. Case-origin filters
  remain independent of the source of an individual amendment.

Existing update sessions retain their original policy. New update sessions capture
the reconciliation profile; deployment does not reinterpret an in-flight old upload.

## Release and recovery

No schema or permission-matrix change is required. Keep the private source,
reviewed selection, fresh backup and rehearsal receipts outside Git. Obtain the
separate production deployment approval required by AGENTS.md. After deployment,
recompare against current production and apply only the approved selection in
bounded chunks. Review any changed revisions or newly conflicting records first.

Google delivery remains separate from the database commit: inspect native
publication receipts before claiming sync, and use the existing retry/resume
controls if delayed. Do not recreate cases or reimport the whole initial register.

Before deployment, code rollback is a checkout/redeploy of the prior release.
After accepted updates, retain audit history and use a reviewed corrective
amendment for the exact affected fields; rolling back code does not undo data.
A database restore is a separate incident decision because it would discard
later work. Do not rewrite approval evidence, delete source events or clear a Sheet.
