# Complaints user-guide screenshots

This folder documents the screenshot names referenced by
`COMPLAINT_CASES_MINI_APP_GUIDE.md`. It does not authorize committing images.

Use the numbered filenames in the guide's Screenshot checklist in the final
manual publication package. Keep images outside Git by default. Capture the
Mini App at an ordinary mobile size and use synthetic training records only.

Before adding an image:

- remove or replace real names, phone numbers, national IDs, locations,
  complaint descriptions, file names, and Telegram identities;
- avoid browser addresses, tokens, notifications, or unrelated chats;
- keep the complete control being explained visible;
- do not crop away a warning or status that changes the meaning of the screen;
- verify labels match the current production release; and
- use PNG for clear UI text.

## Local Playwright capture set

The automated capture set is generated locally from an isolated SQLite database
containing only records explicitly labelled as training examples. The mobile
viewport is 390 by 844 pixels. It supplies screenshots 1--14 under the exact
filenames in the guide checklist.

Screenshots 9 and 10 use Chromium's fake camera and a browser-intercepted
synthetic saved-evidence response. Neither can contact Google Drive. The
reproducible fixture, capture runners, manifests, and troubleshooting examples
are kept in the ignored `test-results/complaints-guide-screenshots/` folder.

The following examples still require a deliberate manual capture from a
synthetic Sheet:

- `15-google-register.png`
- `16-synchronized-row.png`
- `17-resolved-reopened-sheet.png`

Do not use a copy of the production register for these images. Build examples
with synthetic data or fully redact every customer value.

If a fully synthetic screenshot must be committed, follow
`docs/repository-data-artifact-policy.md`: review the file and metadata, record
its path and SHA-256 in the tracked-artifact allowlist, and force-add it only
after that review. Never commit a redacted live screenshot; metadata or missed
details can still disclose operational information.
