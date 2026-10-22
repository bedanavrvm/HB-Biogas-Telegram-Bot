# Origination application sections - scoped UI candidate

Header, supporting-value presentation and incomplete bundle preview were
superseded on 22 October by [the corrective candidate](origination-ui-corrections.md).
The behaviour/evidence below records the earlier implementation, not approval
of the superseded source-navigation design.

User-requested implementation, 21 October 2026. This is not approval of a
shared design standard, new tokens, visual baselines or Phase 6 migration.

## Behaviour

Main LAF inputs retain their logical sections. Each selected, applicable
supporting document has one page with grouped inputs and an individual Preview
action, including documents that need no additional answers. The separate
supporting-document index step is removed; Manage documents stays in the header.

The applicant name identifies the application header. Saved phones use the
existing `MiniAppUtils.phoneLink` dialler pattern and National ID has a clipboard
action with truthful success/failure feedback. Contacts and scoped IT registration
checks appear once in that header, not as disabled input copies in every section.
No access grants, masking rules or provider-dispatch policies change.

Application schema fields have additive, response-only `input_owner` metadata:
`{kind: main, section_key: ...}` or `{kind: document, document_key: ...}`.
Main LAF fields win ownership; otherwise the first selected applicable document
in captured order owns a shared input. The full canonical schema remains available
to validation and saving. Other documents show a read-only summary and source
navigation. Document-local fields and legacy contracts are not merged.

Document edits use the existing revision/request-key save endpoint and the same
save serialisation and encrypted draft recovery as Main LAF edits. Navigation,
preview and document management await saves. Recovery includes document identity
and local answers, including the exit snapshot; restoring opens the correct page.

Clear Guarantor 2 removes its link and clears its active captured fields in one
save. Guarantor 1 and the source spouse/next-of-kin/referee remain unchanged.
Success follows server acknowledgement; failed and overlapping saves are tested.

An explicitly confirmed incomplete supporting preview sends
`allow_incomplete: true`. The server returns `X-Preview-Complete: false` without
marking the document previewed/completed. Submission/signing requirements stay
intact. Individual final previews use `document_key` on the existing signed-bundle
endpoint and extract only manifest-bound pages from hash-verified retained bytes.
Missing historical boundaries fail closed; signed source bytes never change.

## Evidence

Source-faithful synthetic tests: `core/tests_browser/origination_application_forms.spec.js`,
`origination_phone_identity.spec.js`, `origination_queues.spec.js` and
`origination_signing_plans.spec.js`. No real identities, provider calls, production
records or document versions are used. The linked-guarantor persistence test
failed before the fix; incomplete-preview readiness also failed before its fix.

Reproduce from the repository root:

```powershell
npx playwright test core/tests_browser/origination_application_forms.spec.js core/tests_browser/origination_phone_identity.spec.js core/tests_browser/origination_queues.spec.js core/tests_browser/origination_signing_plans.spec.js --workers=2 --output=test-results/origination-final
```

The ignored output includes phone-sized light/dark screenshots:

- `origination_application_fo-af32c-ut-reference-clutter-light-/application-header-light.png`
- `origination_application_fo-af32c-ut-reference-clutter-light-/supporting-document-light.png`
- `origination_application_fo-22d6c-out-reference-clutter-dark-/application-header-dark.png`
- `origination_application_fo-22d6c-out-reference-clutter-dark-/supporting-document-dark.png`
- `origination_application_fo-3bc26-eeps-typed-values-for-retry/document-save-failed.png`

These captures are review evidence, not approved baselines. Existing font sizing
and typography declarations are retained. Browser fallback fonts cannot verify
the production font. Real Telegram dialler/clipboard permissions, native keyboard
and staff-device font rendering remain human checks. No general cross-app UI
migration, publication, document upgrade or production deployment is performed.

Final verification: 124 related browser tests passed; 166 focused backend tests
ran with 163 passes and three PostgreSQL-only skips. Ruff, JavaScript syntax,
UI source ratchet and whitespace checks passed. Four older source-string tests
in `core.tests_loan_origination_frontend` reproduce the same failures against
HEAD; see `KNOWN_GAPS.md`. The operational changes do not claim a clean full suite.
