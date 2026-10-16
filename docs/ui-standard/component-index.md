# Component index and migration hold

The executable inventory is `ui_review.catalog.PATTERNS`; the lab projects it
without a second editable component dictionary. It groups 31 patterns into
Foundations, Navigation, Queues, Forms, Actions, States, Evidence, Reports and
Details. The source manifest shows exact paths and hashes for each alternative.

Existing reusable implementations include MiniAppUtils (feedback, form/draft,
theme, main-action and request behaviour), MiniAppComponents (search, filters,
pagination and action primitives), SecureMediaViewer, report controls and the
Portal confirmation dialog. Audit actual callers before extracting/reusing one.

Candidate foundations are isolated in the lab's tokens/theme files. A user may
preview Telegram or JBL plus Automatic/Light/Dark and three density choices.
No app consumes these files. An approved standard will identify the winner,
allowed variants and governed consumer modules after human review.

## Migration package required after approval

For each selected pattern, record the exact approved revision and decision,
existing consumers, target shared implementation, intentional variants, covered
states, before/after screenshots, affected workflow tests and rollback. Pilot
one pattern in one app before extending it to others. Remove old CSS only after
its final consumer has moved. Role grants and workflow semantics remain local.

**STOP:** this is preparation, not permission to start Phase 6. The user's
explicit migration approval must be obtained after reviewing that package.
