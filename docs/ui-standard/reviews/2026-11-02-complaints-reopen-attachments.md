# Complaint reopening attachments

User-directed follow-up, 2 November 2026. Both native Telegram and standalone
browser forms reuse the existing comment/resolution attachment picker for
Reopen. Reopen is hidden on Open and Reopened cases; it remains available to
authorized JBL staff on closed cases. No spacing, colour, permission or status
policy changed.

Reopening saves its reason and evidence through the same durable upload
receipts as comments. History associates files with the reopening action.
Files retain the current signature, size and count validation, private preview,
background publication and retry handling. A retry of an already committed
attachment submission returns the saved case without adding another event or
file. The original reported date and SLA anchor remain unchanged.

## Manual evidence

Artifacts: `test-results/complaint-reopen-attachments-2026-11-02/`.
`index.html` links the screenshots and observations; `source-manifest.json`
records the source and screenshot hashes. No test suite or assertions were used.

- `01-open-jbl-comment.png`, `02-hb-comment-attachment.png`: both comment
  forms still accept evidence; the open JBL form has no Reopen tab.
- `03-browser-reopen-photo.png`: closed-case reopening with an attached photo.
- `04-browser-reopen-hidden-after-save.png`: successful reopening removes the
  Reopen action and tab.
- `05-native-invalid-file-retained.png`: a disguised PNG is rejected and the
  reason/file remain available for correction.
- `06-native-reopen-pdf.png`, `07-native-reopened-history.png`: native
  reopening accepts a PDF and records its evidence in history; Reopen disappears.
- `walkthrough.json`, `native-replay.json`: observed HTTP outcomes,
  same-form/file replay results, unchanged replay revisions and tab visibility.
- `database-publication.json`: evidence foreign keys, retained-byte hashes,
  unchanged original anchors and local publisher observations.
- `08-native-reopening-preview.png`, `09-dark-open-comment.png`: the new
  history file opens through the private preview, and dark mode also hides
  Reopen on an open case. The generated PDF fixture contains a blank page.

The isolated native actor shim uses an explicit review header. This is local
identity injection, not authentication/MFA or signed-launch verification.
The raw browser multipart capture omitted fields when replayed and correctly
received a 403 for missing group identity. `native-replay.json` reconstructs
the original form fields and file bytes: that replay succeeds without another
revision, and changed file bytes on the same key are rejected.
Google providers were substituted locally; no production data, flags or
external services were changed. Native camera hardware was not exercised.

The earlier [verification-comment review](2026-10-31-complaint-verification-comments.md)
retains the other design decisions. The [operator guide](../../runbooks/complaints-verification-comments.md)
describes the shared history and elapsed-time policy.
