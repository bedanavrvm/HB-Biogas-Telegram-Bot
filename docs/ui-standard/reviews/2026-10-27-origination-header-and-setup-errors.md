# Origination header removal and actionable setup errors

27 October 2026. Bounded corrections requested by the user. These reuse the
existing Origination header icon actions, confirmation sheet, Admin task links
and autosave feedback. No candidate tokens, approved baselines or Phase 6 gates
change.

## Result and scope

- One labelled red trash icon sits immediately before Manage documents in the
  application header. The repeated form-footer removal button is removed.
  The existing 44px target, keyboard focus, confirmation and lifecycle
  permissions remain. Signed applications still use invalidation and require a
  reason. A lighter red keeps the icon visible on the existing dark surface.
- Shared-value contract errors identify the exact document name/version, field
  label/key, reason and comparison document. Structured error keys remain
  unchanged. Product setup retains these details in both initial rendering and
  autosave; unpublished-document reminders no longer replace field errors.
- Every selected Main LAF is checked, so one incompatible document combination
  cannot hide the errors in a later selected combination. Validation rules and
  application/publication authority remain unchanged.

## Evidence

The original warning was reproduced by
`ChosenDocumentMeaningTests.test_setup_warning_names_document_version_field_and_conflict`:
the complete readiness result was only `Review the highlighted document fields.`
The header regression also failed against the original source because the
removal button was outside `.editor-document-actions`.

Results: all 64 form browser scenarios passed, with all five new header cases
passing again after the final dark-theme correction. Across scoped Django runs,
154 checks passed; three PostgreSQL-only concurrency cases were skipped on
SQLite. The new native Admin fixture initially lacked Django `is_staff`, so its
first browser run reached Admin login; the fixture was corrected and all three
native Admin/Mini App journeys then passed together. JavaScript syntax,
`git diff --check` and the UI source ratchet passed. PostgreSQL was not rerun for
this presentation/message change.

Focused source-bound coverage:

- `origination.tests_value_contracts`: contract diagnostics, all error keys,
  fields and document comparisons, plus existing value/ownership rules.
- `core.tests_origination_setup` and `core.tests_origination_document_catalogue`:
  setup/selection/publication behaviour.
- `origination.tests_workflow_improvements`: existing allowed/denied removal,
  invalidation, retry and audit paths.
- `core.tests_origination_improvements_browser`: real Django Admin sessions and
  native Mini App shell against synthetic local storage, including the exact
  detailed warning before and after autosave and real unsigned deletion.
- `core/tests_browser/origination_application_forms.spec.js`: actual ordered
  Django shell assets with synthetic API I/O. Header placement at 320px/390px/
  1280px, light/dark, multiple sections, reason requirement and denied action.

Synthetic screenshots are in ignored `test-results/playwright/` for each header
variant and `test-results/origination-improvements-live/` for native Admin and
Mini App journeys. The detailed warning screenshot is
`setup-fields-remaining-task-390.png`. These are implementation evidence, not
human design approval or real Telegram device/screen-reader validation.

## Deployment and limits

Deploy code and collect static assets; the Mini App script/style cache versions
are changed. No migration, reseed, reset, new dependency or provider action is
needed. This change does not resolve an actual incompatible field automatically:
the Admin must review the named field meanings in the named Document editors.
No production data, Sheets/Drive or real Telegram devices were used.
