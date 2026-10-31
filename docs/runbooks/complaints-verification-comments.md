# Complaints: JBL verification comments

Implemented 31 October 2026. This is an append-only comment policy, not an
additional approval stage. Open, Reopened and Closed retain their meanings.
There is no Verified status or mandatory verification gate.

## Staff actions

| Complaint role | Comment | Resolve | Reopen |
| --- | --- | --- | --- |
| Officer | JBL findings on open or closed cases | No | Closed cases, with reason |
| Manager | JBL findings on open or closed cases | No | Closed cases, with reason |
| IT | JBL findings on open or closed cases | No | Closed cases, with reason |
| HB | HB feedback on open cases | Open cases, with resolution note | No |

These are built-in Complaint capabilities. Current group scope, account state
and explicit permission policy still apply. Other Mini App grants confer no
Complaint authority. People holding both JBL and HB grants explicitly choose
the comment type; HB resolution authority stays separate.
IT's normal form presents JBL actions. The existing scoped IT technical
override remains available for recovery; this change does not revoke it or
alter historical IT feedback.

Use a JBL comment to record what was checked, the finding, and any follow-up.
A satisfactory finding can remain a comment on the closed case. An
unsatisfactory finding can be recorded as a comment and followed by Reopen
with a reason. A saved comment alone does not certify verification, close or
reopen a case, restart its clock, or unlock the ordinary staff conversation.
Management must interpret the recorded findings; there is no machine-enforced
verification completion count.

## Attachments and history

Both comment forms use the existing photo/PDF picker: JPEG, PNG, WebP or PDF,
up to 10 files, 10 MB each and 30 MB total per submission. A nonblank comment
of at most 5,000 characters is required. Server signature checks validate
the files. Comment text and retained file receipts commit together in Django;
Google availability does not block the save. Existing request keys prevent a
retry from creating another comment. A changed payload needs a new request key.

The existing publisher uploads retained bytes to private Drive storage and
publishes the Sheet separately. Drive completion queues a follow-up Sheet
snapshot so attachment links replace pending labels even when Sheets completed
first. Failed publication retains the canonical comment and original bytes for
the existing scoped IT recovery process. See
[the publisher runbook](complaints-browser-publications.md).

HB and JBL comments, their files, and closure/reopen actions appear in case
History, newest first. Sheet Resolution History contains the same operational
notes and status changes, oldest first. Ordinary conversation messages retain
their separate conversation handling. JBL notes never replace Resolution
Details or the latest HB resolution.

## Register and elapsed time

The projected register and Excel export contain separate columns:

- **Resolution Comments:** HB feedback.
- **JBL Verification Comments:** JBL findings, actor, Nairobi timestamp and
  attachment references.
- **Resolution History:** chronological operational notes and transitions.
- **Resolution Details / Date Resolved:** latest HB closure.

Days Open and “Closed after X days” remain elapsed calendar days from the
original reported timestamp to the latest closure. While reopened, the endpoint
is the current time. Temporarily closed intervals count. Reopening clears only
the current resolution date; comments leave reported date, resolution date,
resolution text and SLA start unchanged.

Example: reported on day 0, closed on day 3, reopened on day 8, and finally
closed on day 8 displays **Closed after 8 days**. A verification comment on day
9 leaves it at 8 days.

## Deployment preparation

Add the exact header **JBL Verification Comments** to each enabled Complaint
register before enabling the updated publisher. Column position is immaterial:
the adapter maps named headers and rejects missing or duplicate headers. A
missing column leaves publication retryable; it must not rewrite the workbook
layout or lose the saved comment.

Normal deployment must apply migration
`0212_complaint_verification_comments`, deploy the updated client and publisher,
and rebuild the standalone Complaints operations artifact. The migration ships
the built-in JBL comment/reopen permissions and updates explicit saved Complaint
schema mappings. No staff shell command or new persistent model is required.
Existing browser release/admission flags and production approval remain governed
by their current runbooks.

Local review did not deploy this change, alter an operational database, or write
to real Sheets/Drive/Telegram. Evidence and limits:
[source-bound review](../ui-standard/reviews/2026-10-31-complaint-verification-comments.md).
