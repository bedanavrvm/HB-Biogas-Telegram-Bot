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

## Local Playwright capture set

The first automated capture set was generated locally from an isolated SQLite
database containing only records explicitly labelled as training examples. The
mobile viewport was 390 by 844 pixels. It supplies screenshots 1–8 and 11–14
under the exact filenames in the guide checklist. The reproducible fixture,
capture runner, manifest, and additional troubleshooting examples are kept in
the ignored `test-results/complaints-guide-screenshots/` folder.

The following examples still require a deliberate manual capture:

- `09-camera-selected-files.png` — capture the camera surface on a physical
  phone; the local bundle includes only the selected-file viewer.
- `10-secure-evidence.png` — capture a synthetic item after it has been saved
  through the configured protected evidence store.
- `15-google-register.png`, `16-synchronized-row.png`, and
  `17-resolved-reopened-sheet.png` — capture only from a synthetic Sheet.

Do not use a copy of the production register for these images. Build the
examples with synthetic data or fully redact every customer value.

If a fully synthetic screenshot must be committed, follow
`docs/repository-data-artifact-policy.md`: review the file and metadata, record
its path and SHA-256 in the tracked-artifact allowlist, and force-add it only
after that review. Never commit a redacted live screenshot; metadata or missed
details can still disclose operational information.
