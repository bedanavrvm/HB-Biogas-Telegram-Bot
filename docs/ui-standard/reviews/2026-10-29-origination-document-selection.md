# Origination supporting-document selection

29 October 2026. User-reported supporting documents become unselectable after
choosing a Main LAF. This is a correction to existing selection and feedback,
using the current Mini App shell, option cards and task sheet.

## Cause and correction

The catalogue compared complete document schemas, while the editable form and
packet used the placement-driven projection. A conflicting or unfinished field
that had no placement could therefore disable an otherwise compatible supporting
PDF. Manage documents, selection saves and unsigned-update planning repeated the
full-schema check. The picker also discarded the server's precise error and
displayed only “Choose a compatible Main LAF”.

Selection now compares the same active document fields as the form. Application
Loan details remain active under ADR 0075 even without PDF placements. The
existing projection helper supplies these inputs to both the form and selection,
so they cannot be bypassed by hiding a PDF field. New selections, current draft
choices, selection writes and unsigned document-update planning use that policy.

Actual differences in subject, type, ownership, source, units, period, choices or
repeating rows remain errors. A disabled option now includes the document and
field comparison returned by the server. A selected incompatible document stays
removable. No canonical field is renamed, merged or assigned a guessed meaning.
No product or document configuration is edited by this change.

## Browser evidence

Evidence is local and synthetic in
`test-results/origination-document-selection/index.html`. The review uses the real
Django shell, static assets, session, catalogue, application creation, selection
and update endpoints against a new disposable SQLite database. External network
calls are blocked. No test runner or assertions are used.

The before capture reproduces one unused `archived_amount` field with different
subjects in the Main LAF and supporting form: neither PDF places it, but the
supporting checkbox is disabled. The after capture selects that same document.
A second supporting form places `applicant_name` for an asset owner while the
Main LAF places it for the applicant. That real conflict stays disabled and now
explains the exact field and comparison.

The browser review created a draft (HTTP 201), removed and re-added the supporting
form through Manage documents, and reopened it with both compatible choices
retained. Its active phone field saved and survived reopening; the retired amount
had no active input. A synthetic published successor was then adopted through
the real update endpoint: the phone survived, the new Inspection notes field
appeared and saved, and the supporting choice remained selected at version 2.
An additional placed `loan_amount` with guarantor meaning remained disabled
against the application's mandatory Loan details, despite no amount placement on
the Main LAF.

Manage documents captures cover light/dark 320px, 390px and 1280px. The gallery
records the captured states; it is implementation evidence, not human design
approval.

## Boundaries

This diagnosis establishes a reproducible selection defect, not the contents of
the user's deployed catalogue. The affected production document names were not
provided during the initial reproduction. A genuine active field-meaning
conflict still requires an explicit correction in the Document editor.

No migration, reseed, reset, new dependency, browser activation, provider write,
signed-packet rewrite or Phase 6 migration is part of this correction. Historical
version-1 form reconstruction remains unchanged. No tests, lint or type checks
were run at the user's request. SQLite review does not establish PostgreSQL
concurrency, live Telegram behavior, real-device accessibility or deployment.
