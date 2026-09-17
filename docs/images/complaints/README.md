# Complaints user-guide screenshots

This folder documents the screenshot names referenced by
`COMPLAINT_CASES_MINI_APP_GUIDE.md`. It does not authorize committing the image
files.

Use the numbered filenames in the guide's Screenshot checklist in the final
manual publication package. Keep the image files outside Git by default.
Capture the Mini App at an ordinary mobile size and use synthetic training
records only.

Before adding an image:

- remove or replace real names, phone numbers, national IDs, locations,
  complaint descriptions, file names, and Telegram identities;
- avoid showing browser addresses, tokens, notifications, or unrelated chats;
- keep the complete control being explained visible;
- do not crop away a warning or status that changes the meaning of the screen;
- verify that labels match the current production release; and
- use PNG for clear UI text.

The Sheet images to add manually are:

- `15-google-register.png`
- `16-synchronized-row.png`
- `17-resolved-reopened-sheet.png`

Do not use a copy of the production register for these images. Build the
examples with synthetic data or fully redact every customer value.

If a fully synthetic screenshot must be committed, follow
`docs/repository-data-artifact-policy.md`: review the file and metadata, record
its path and SHA-256 in the tracked-artifact allowlist, and force-add it only
after that review. Never commit a redacted live screenshot; metadata or missed
details can still disclose operational information.
