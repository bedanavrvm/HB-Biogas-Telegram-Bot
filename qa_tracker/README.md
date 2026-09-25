# QA tracker

This bounded app owns the internal, cross-workflow manual QA registry and release results. It is not an operational customer workflow and is not a replacement for CI.

Seeded app choices: Portal, TAT Tracker, Complaints, SPIN, Origination, FCA Review, Farmers Review, and Order Approval. Each has its own human-observable checklist. Create a separate release cycle for each app being tested; creating a cycle freezes that app's then-active test IDs. Older review Mini Apps are included because their browser routes still exist; mark a case Blocked when its required upload or authorized test context is unavailable.

New-cycle forms prefill the release from `APP_RELEASE`, the commit from Render's `RENDER_GIT_COMMIT` (or a SHA-shaped `APP_RELEASE`), and a supported `RELEASE_ENVIRONMENT`. These are editable suggestions captured at creation, not a fresh lookup each time the checklist is viewed. If no trustworthy value exists, the field stays blank for the tester.

- `TestCase` is a permanent-ID registry. Retire a case with `active=False`; never reuse its ID. Substantive behavior changes should receive a new ID.
- `TestCycle` freezes the active test IDs when a release checklist is created. Its app, environment, group, branch, product, and build metadata are immutable afterward.
- `TestRun` is create-only. The latest execution per case in a cycle is its current result; all earlier executions remain available in run history.
- `TestEvidence` stores only the private Drive reference, generated filename, MIME, size, and digest of a screenshot. No public Drive URL is served. Screenshots and generated PDFs require the same scoped admin authorization as the cycle.

Retention: QA registry, cycles, and executions remain until a separately approved retention policy exists. Screenshots follow the organization's restricted Drive retention policy. The report PDF is generated on demand and is not stored. Django is the source of truth for result state; Drive holds binary evidence only.

Access: active Superusers, or active Django staff with an active, matching IT AccessGrant for the workflow and exact group/branch/product scope. IT grants are evaluated as complete tuples, not combined across grants. A direct URL cannot bypass that scope. No new Google credentials or folders are needed beyond the existing private media root.
