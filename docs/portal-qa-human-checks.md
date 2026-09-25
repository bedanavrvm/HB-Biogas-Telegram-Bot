# Portal QA: human verification

Record results in **Admin → QA release checklists**. Create one checklist for the deployed app, release, environment, and group; include the build commit when known. Open **Run checklist**, choose Pass, Fail, or Blocked, and optionally add a privacy-safe observation, bug reference, and screenshot. The report and comparisons are generated from those records; do not edit a spreadsheet.

Use consenting test records. Never put real customer names, IDs, phones, tokens, or documents in notes or screenshots. A missing prerequisite is **Blocked**, not Pass. Each test ID is permanent; retire a test instead of reusing its ID.

These cards are deliberately focused on behavior a person must see or judge. The [extended inventory](portal-manual-test-checklist.md) remains a reference for automated coverage audits. `NAV-06` and `NAV-07` remain manual with an **automation gap** flag until their CI coverage is confirmed.

## Launch and navigation

### NAV-01 · Launch and identity

- Do: Open Portal from the approved Telegram launcher on a phone.
- Expect: The correct staff identity and landing screen load with clear progress. No unexpected external browser opens.

### NAV-03 · Back and preview chain

- Do: Open a case from a filtered list, preview evidence, then use Close and Back.
- Expect: Each step returns to its immediate origin without losing useful list context.

### NAV-04 · Notification focus

- Do: Open the bell on a narrow phone and follow a case notification; allow the page to refresh.
- Expect: The bell remains compact and the exact target case stays visibly focused.

### NAV-05 · Feedback language

- Do: Observe a success, warning, validation failure, and server failure.
- Expect: One plain-language message appears for each event, with a useful recovery action and no duplicate alert.

### NAV-08 · List density

- Do: Inspect empty, one-item, and many-item lists; search and clear a query.
- Expect: Counts, filters, row hierarchy, and pagination remain coherent and readable.

### NAV-09 · Dates

- Do: Compare timestamps across cards, case detail, history, and export.
- Expect: Kenyan local display and day-month-year input presentation agree.

### NAV-10 · In-app documents

- Do: Open and close an image and document preview.
- Expect: The file is readable, controls work on a phone, and Close returns to the exact prior screen.

## Intake and data review

### FARM-03 · FarmUp table

- Do: Search, filter, switch table/card view, and open a row with long values on a phone.
- Expect: Text and frozen columns do not overlap; enough rows fit without losing readability.

### SYS-01 · SysUp mapping

- Do: Stage a valid SysUp file and review its mappings and matched rows.
- Expect: Source identity, applicant, and loan-officer values are visually distinct and understandable.

## HomeBiogas action

### HB-01 · Workstreams

- Do: Open a case released by an accepted signed order.
- Expect: Installation and commissioning are separate, obvious workstreams; search uses the available width.

### HB-03 · Installation form

- Do: Choose Mark as installed and inspect the form before saving.
- Expect: Only actual installation fields appear; planning and commissioning inputs remain hidden.

### HB-05 · Commissioning wait period

- Do: Inspect readiness on an installed case.
- Expect: The 21-day date and relative day count agree and make sense at the current Nairobi date.

## Payment

### PAY-02 · Candidate card

- Do: Open and close an invoice-matched candidate on a phone.
- Expect: Collapsed identity is useful; expanded case details and actions align without wasted space.

### PAY-08 · Large batch list

- Do: Inspect a completed batch and a list of many batches.
- Expect: Completed cards remain compact, filters are clear, and Back restores the correct list.

## Resilience

### NAV-06 · Offline state · automation gap

- Do: Disconnect and reconnect while viewing a populated list.
- Expect: Existing data remains readable; the app clearly identifies offline and restored states.

### NAV-07 · Interrupted form · automation gap

- Do: Background the app with an unfinished form, then return and refresh.
- Expect: Unsaved input is not silently lost or overwritten by polling.

## Run matrix

Use at least one narrow Android Telegram device and a desktop browser. Repeat visual checks at 320×568, 360×800, and 430×932 where practical, in supported light and dark themes. Mark inaccessible test conditions **Blocked**, record the reason, and never manufacture production actions just to complete a checklist.
