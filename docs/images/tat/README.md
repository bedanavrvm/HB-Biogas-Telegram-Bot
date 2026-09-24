# TAT user-guide screenshots

This folder documents the screenshot names referenced by
`TAT_TRACKER_MINI_APP_GUIDE.md`. The folder does not authorize committing the
image files.

Screenshots 1–19 can be regenerated offline with
`node scripts/capture_tat_guide.js`. The script renders the checked-in Mini App
with invented training cases and intercepted responses; it does not contact
Telegram, Google, or production Django. Review the output before publication.

Use the numbered filenames in the guide's screenshot checklist in the final
manual publication package. Keep screenshots outside Git by default. Capture
the Mini App at an ordinary small-phone size and use synthetic training records
only.

Before adding an image:

- replace real names, phone numbers, national IDs, amounts, branches, remarks,
  document names, and Telegram identities with synthetic values;
- do not show browser addresses, signed launch data, tokens, notifications, or
  unrelated chats;
- keep the complete control, warning, or status being explained visible;
- do not crop away context that changes the meaning of the screen;
- verify labels against the current production release; and
- use PNG for readable UI text.

The Google Sheet images to add manually are:

- `20-tat-register-overview.png`
- `21-tat-synchronized-case-row.png`
- `22-case-index.png` (only if the secondary tab is enabled)
- `23-audit-log.png` (only if the secondary tab is enabled)

Never use a production register screenshot. Build synthetic examples instead.
Blurring, cropping, or visually redacting a live Sheet is not sufficient for a
repository artifact because metadata or overlooked cells can still disclose
operational information.

If a fully synthetic screenshot must be committed, follow
`docs/repository-data-artifact-policy.md`: review the file and metadata, record
its path and SHA-256 in the tracked-artifact allowlist, and force-add it only
after approval.
