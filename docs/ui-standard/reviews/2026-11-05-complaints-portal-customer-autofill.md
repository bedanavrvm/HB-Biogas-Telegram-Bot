# Complaints Portal customer suggestions

The user approved an all-Portal biodata directory for authorized Complaints
creators, without requiring a Portal role. Selecting a result replaces biodata;
the complaint's description, category, evidence and map pin are retained.

## Interaction and data decisions

- Both Telegram and native browser creation use the same bounded Django lookup.
  National ID matches precede primary-phone matches, then name matches. Exact
  matches precede prefixes/contains within each tier. Queries begin after three
  ID/name characters or four phone digits, debounce at 300 ms and return at most
  ten distinct Portal cases. Secondary/spouse phones are not identity matches.
- Each choice shows the readable JBL reference, name, ID, primary phone, branch,
  location and matching reason. Conflicting entered identifiers are labelled.
  Multiple units/locations stay individually selectable; nothing is auto-selected
  or merged by name.
- Selection reads the current Portal record and fills name, ID, primary/secondary
  phones, branch, county, constituency and village together. Location dropdowns
  retain their dependency rules. Unsupported historical labels remain visible
  beside the affected field, and invalid legacy phone/ID values require review.
- All-branch lookup does not expand complaint creation scope. An unauthorized
  source branch stays in the source note; the creator must choose an authorized
  complaint branch. Existing server validation remains authoritative.
- Copied values remain editable. Identity edits clear the selection marker;
  Clear Portal selection retains entered values and provides manual recovery if
  a source disappears. Empty source fields clear previous customer values.
- Drafts retain copied fields and the source reference. Source selection is
  validated server-side and stored in the existing complaint creation event.
  Portal identities, financial values, documents and workflow states are not changed.
- Requests use POST bodies, not query strings, for identifiers and names. Existing
  Telegram authentication and native cookie/MFA/CSRF remain independent.

## Design and evidence

Reuses TAT's compact matching-panel idea within the current Complaints shell:
small text, bounded scrolling, full-width selectable rows, source context and
inline review guidance. Existing Stitch direction remains authoritative. No new
dependency, approved baseline, candidate token or Phase 6 migration is introduced.

Playwright exercises actual Django routes with isolated PostgreSQL records and
native password/MFA/CSRF plus signed Telegram. Screenshots cover both channels,
mobile/dark views, no match, historical issues, selection, filled forms, lookup
failure and successful save. The journey checks draft reload, field replacement,
preserved complaint text/files, Escape dismissal and retry. Two complaints retain
their source attribution and are written to a synthetic Sheet using the existing
publisher. Browser business responses are not mocked; the failure scenario aborts
one client request to exercise manual recovery.

Local artifacts:

- `test-results/complaint-customer-lookup/index.html`
- `test-results/complaint-customer-lookup/results.json`
- `test-results/complaint-customer-lookup/projected-complaints.xlsx`
- `test-results/customer-lookup-final.log`

TypeScript, ESLint and the native production build are checked separately. The
broader 81-check service/draft run passed 76 and had five failures. All five also
fail using the original HEAD Complaints service, without changing the checkout:
`test-results/customer-lookup-baseline.log`. They concern existing comment
publication/history expectations and Officer reopen policy, not this lookup.

No live customer search, production import, deployment, Google delivery or
physical-device acceptance occurred. Google transport is a synthetic boundary.
