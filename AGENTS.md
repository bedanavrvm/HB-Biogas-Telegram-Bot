# AGENTS.md

## Purpose

This file is the operating guide for AI coding agents and human contributors working in this repository.

The repository is a Django-based operational workflow platform for JBL/Jawabu HomeBiogas. Telegram is the primary message-ingestion, user-identity, command, notification, and Mini App channel. Django stores workflow state and audit history. Google Sheets and Google Drive integrate the platform with existing staff operations.

The repository name is historical. Do not treat this as a small Telegram bot or a single complaint parser. It currently contains several business-critical workflows:

- Complaint and case ingestion from Telegram/forwarded WhatsApp content
- Complaint case management Mini App, including map pins and Drive evidence
- Jawabu farmer intake and pipeline processing
- FCA review/import workflows
- JBL site-visit processing
- Credit and final-decision processing
- Requisition and invoice generation
- Order approval, including media uploads
- SPIN credit requests and analyst completion
- TAT tracking with role- and stage-based rules
- Google Sheets and Google Drive synchronization

Changes can affect operational data, customer records, approvals, financial values, documents, and staff workflows. Work conservatively, preserve auditability, and validate changes at the narrowest affected boundary before running broad tests.

---

## Quick reference (read this first)

If you read nothing else, follow these:

1. **Never commit secrets or customer data** — tokens, service-account JSON, phone numbers, IDs, photos, spreadsheets. See [Security and privacy rules](#security-and-privacy-rules).
2. **Every write path must be idempotent.** Telegram retries webhooks; Mini Apps can double-submit. Check for existing records before creating new ones.
3. **Telegram authentication ≠ authorization.** A valid `initData` signature only proves Telegram identity — check the actor is an approved staff member for that action, branch, or group.
4. **Money is `Decimal`, never `float`.** Route all financial fields through `Decimal` and decimal DB fields.
5. **Django is the source of truth for workflow state.** Google Sheets is a synchronized view, not a second database — never let Sheets silently override backend state without a defined conflict rule.
6. **State transitions are validated server-side**, never trusted from client input.
7. **Never perform real external side effects by default** — no writes to production Sheets/Drive, no messages to real Telegram groups, no webhook changes — unless explicitly requested and authorized. See [External side effects](#external-side-effects).
8. **Don't trust root-level Markdown docs as current truth.** Code, migrations, tests, and settings win over old status write-ups (see [Instruction precedence](#instruction-precedence)).
9. **One bounded change per PR.** Don't mix architecture refactors with business-rule changes.
10. Unsure which workflow owns something? Check the [Workflow ownership guide](#workflow-ownership-guide) before guessing.

---

## Domain glossary

The workflows in this repo use organization-specific shorthand. An agent unfamiliar with JBL/HomeBiogas operations should treat this as required reading before touching business logic.

| Term | Meaning in this codebase |
|---|---|
| **JBL** | Jawabu Biashara Limited — the credit-only microfinance institution this platform serves. |
| **Jawabu** | Short form used across services/models for JBL-related farmer/customer records and pipeline. |
| **HomeBiogas** | The biogas-financing product line and associated field/order workflows. |
| **FCA** | Field Control Visit / field review workflow — data collected during in-field visits, reviewed and imported into the platform. |
| **TAT** | Turnaround Time — tracked per loan/case stage with role- and product-based rules (`tat_tracker.py`). |
| **SPIN** | Credit/CRB-report-linked request workflow handled by `spin_credit.py`, completed by credit analysts. |
| **Mini App** | A Telegram Web App (mobile-first web UI launched inside Telegram) backed by Django templates/static assets under `core/templates/*` and `core/static/miniapp/`. |
| **`initData`** | Telegram's signed payload proving a Mini App session belongs to a specific Telegram user; must be HMAC-verified server-side before trust. |
| **Portal** | The aggregated staff-facing view across pipeline/workflow data, served by `core/api/portal_views.py`. |

If new domain terms are introduced by a change, add them here rather than only in a service docstring — this table is the first place agents and new contributors look.

---

## Instruction precedence

When instructions conflict, follow this order:

1. Explicit user request
2. Security, privacy, and data-integrity requirements in this file
3. More specific `AGENTS.md` files in subdirectories, if added later
4. Existing tests and database constraints
5. Current implementation conventions
6. Historical documentation

Many root-level Markdown documents describe earlier versions of the project. They are useful context, not necessarily current truth. Prefer executable code, migrations, tests, current settings, and current URL routing over claims such as "complete," "production ready," "MVP," or old file counts.

---

## Repository map

### Main entry points

- `manage.py` — Django management entry point
- `config/settings.py` — application settings and environment variables
- `config/urls.py` — project-level URL routing
- `core/api/urls.py` — workflow and API route definitions
- `core/api/views.py` — Telegram webhook and several Mini App/API endpoints
- `core/api/portal_views.py` — Jawabu pipeline portal endpoints
- `core/models.py` — database models for all workflows
- `core/admin.py` — Django admin registrations and operations

### Business services

Business rules belong in `core/services/`, not in templates or oversized view functions.

Key modules:

- `case_updates.py` — complaint/case update processing
- `commands.py` — Telegram command handling
- `deduplication.py` — message and case deduplication
- `fca.py` — FCA parsing/import behaviour
- `group_config.py` — Telegram-group/workflow configuration
- `group_reset.py` — controlled group data resets
- `invoice_parser.py` — invoice extraction and parsing
- `jawabu.py` — Jawabu message processing
- `jawabu_master.py` — master farmer-record operations
- `jawabu_pipeline.py` — pipeline state and transition logic
- `live_sheet_records.py` — sheet-originated record-change handling
- `order_approval.py` — order-approval workflow and attachments
- `parser.py` — complaint/message parsing
- `requisition.py` — requisition generation and files
- `sheet_analyzer.py` — spreadsheet inspection
- `sheet_schema.py` — expected sheet structure and mappings
- `sheet_sync.py` — synchronization orchestration
- `sheets.py` — low-level Google Sheets gateway
- `spin_credit.py` — SPIN request parsing and workflow logic
- `storage.py` — media/file storage abstraction
- `tat_tracker.py` — TAT workflow configuration and transitions
- `telegram_command_menu.py` — Telegram command registration
- `workflow_presets.py` — workflow definitions/presets

### Frontend Mini Apps

Templates:

- `core/templates/order_approval/`
- `core/templates/jawabu_farmers/`
- `core/templates/fca_review/`
- `core/templates/spin/`
- `core/templates/tat_tracker/`
- `core/templates/portal/`
- `core/templates/complaint_cases/`

Static assets:

- `core/static/miniapp/`

The Mini Apps use Django templates and mostly vanilla JavaScript. Preserve Telegram Web App compatibility and mobile-first behaviour.

### Tests

- `core/tests.py`
- `core/tests_pipeline.py`
- `core/tests_order_approval.py`
- `core/tests_spin_credit.py`
- `core/tests_tat_tracker.py`
- `core/tests_group_reset.py`
- `core/tests_sheets_validation.py`
- `core/tests_data_quality.py`
- `core/test_data_quality_simple.py`

### Operational integrations and examples

The repository root contains Google Apps Script files, spreadsheet examples, deployment notes, and historical implementation documents. Treat real-looking spreadsheets, exports, media, and credentials as sensitive even when the repository is private.

> **Drift check:** this map reflects the repository's structure as of the last time this file was reviewed. If a listed file/module no longer exists, or a new top-level service has been added, update this section as part of your change rather than leaving it stale.

---

## Environment variables

This is a template of variables this class of system typically needs. Treat it as a checklist to reconcile against the actual `.env.example` and `config/settings.py` — do not assume a name below is exactly correct until you've confirmed it in the repo.

| Variable | Purpose | Sensitive? |
|---|---|---|
| `DJANGO_SECRET_KEY` | Django cryptographic signing key | Yes |
| `DEBUG` | Django debug mode toggle (must be `False` in production) | No |
| `ALLOWED_HOSTS` | Django allowed host list | No |
| `DATABASE_URL` | PostgreSQL connection string (production) / SQLite for local dev | Yes |
| `TELEGRAM_BOT_TOKEN` | Bot API token used for sending messages / Bot API calls | Yes |
| `TELEGRAM_WEBHOOK_SECRET` | Shared secret validated on incoming webhook requests | Yes |
| `API_AUTH_TOKEN` | Token protecting manual/admin/script-facing endpoints | Yes |
| `GOOGLE_SERVICE_ACCOUNT_JSON` / `GOOGLE_APPLICATION_CREDENTIALS` | Service-account credentials for Sheets/Drive API access | Yes |
| Sheet/Drive IDs (e.g. `*_SHEET_ID`, `*_FOLDER_ID`) | Identify target spreadsheets/folders per workflow | Treat as sensitive unless confirmed non-sensitive |
| `TAT_TRACKER_SIGNATURES_ENABLED` | Enables external TAT e-signature dispatch and stage gating | No |
| `COMPLAINT_CASES_MINI_APP_SHORT_NAME` | Telegram Mini App short name for complaint cases | No |
| `COMPLAINT_CASES_WEBAPP_REQUIRE_TELEGRAM_AUTH` | Requires verified Telegram Mini App identity for complaint case APIs | No |
| `COMPLAINT_CASE_MAX_FILES_PER_UPDATE` / `COMPLAINT_CASE_MAX_TOTAL_UPLOAD_MB` | Limits complaint evidence uploads | No |

When adding a new configuration value, add it to `.env.example` with a placeholder (never a real value) in the same change, and add it to this table.

---

## Architectural model

Use this model when reasoning about changes:

```text
Telegram groups / Telegram Mini Apps
                 |
                 v
       Django HTTP/API boundary
                 |
                 v
      Workflow application services
                 |
       +---------+----------+
       |                    |
       v                    v
 Django database       Google integrations
       |              (Sheets / Drive)
       v                    |
 Audit and state            v
                    Staff-facing registers/files
```

### Intended responsibilities

**Telegram**

- Receives forwarded messages, commands, files, and replies
- Supplies signed Mini App identity data
- Launches workflow interfaces
- Delivers confirmations, errors, and operational notifications

**Django**

- Validates requests and identities
- Applies business rules
- Stores canonical workflow state and audit history
- Enforces idempotency and data integrity
- Generates files
- Coordinates external integrations

**Google Sheets**

- Provides staff-facing registers and reporting
- May provide explicitly designated manual-entry fields
- Must not silently become an uncontrolled second database

**Google Drive**

- Stores workflow media and supporting documents when configured

### Source-of-truth rule

For every field changed or introduced, identify its owner:

- `backend-owned`
- `sheet-owned`
- `formula-owned`
- `derived`
- `immutable`

Do not implement bidirectional synchronization without defining conflict behaviour. Prefer Django as the authoritative system for workflow state and use Sheets as a synchronized operational view.

---

## Critical invariants

These invariants must be preserved unless the task explicitly redesigns them and includes migrations, tests, and documentation.

### 1. Raw input must remain auditable

Never overwrite or discard original Telegram/WhatsApp content merely because parsing succeeds. Raw input, processing status, parsed output, and errors should remain traceable.

### 2. Processing must be idempotent

Telegram may retry webhooks. Users may resubmit Mini App forms. Networks may retry requests. A repeated request must not silently create duplicate cases, payments, approvals, farmer records, requisitions, or media.

Use and preserve:

- Telegram message identifiers
- Group identifiers
- Message/content hashes
- Request IDs
- Existing unique constraints
- Explicit duplicate checks
- Transactional state transitions

Do not weaken database constraints to make a failing test pass.

### 3. Group context must not leak

Most Telegram message IDs are only meaningful with their group/chat context. Queries involving group-routed data must include the correct group or configuration scope.

Do not assume all users should see all configured groups. Portal aggregation is an existing behaviour, not a universal authorization rule.

### 4. Authentication is not authorization

A valid Telegram `initData` signature proves Telegram identity. It does not prove that the user is an approved JBL/Jawabu staff member or that they may operate every workflow, branch, group, or stage.

When adding protected behaviour, enforce both:

- cryptographic Telegram authentication (see [Telegram Mini App authentication](#telegram-mini-app-authentication)); and
- business authorization by approved identity, role, branch, group, or workflow.

### 5. Workflow transitions must be validated server-side

Never trust a client-provided status, stage, amount, role, branch, or decision without server-side validation.

For staged workflows:

- Validate the current state
- Validate the requested transition
- Validate required fields and attachments
- Validate actor permissions
- Record the actor and timestamp
- Preserve transition history

### 6. Financial and identifier values require precise handling

Do not use floating-point arithmetic for money. Use `Decimal` and database decimal fields. All monetary amounts in this system are KES unless a workflow explicitly states otherwise.

Normalize Kenyan phone numbers and IDs (e.g. `+254...` / `07...` variants) through shared helpers. Do not duplicate ad hoc normalization in views or JavaScript when a service already exists.

### 7. External synchronization failure must not corrupt local state

Google Sheets or Drive may be unavailable. Code must distinguish:

- local transaction success
- external synchronization success
- retryable external failure
- permanent validation failure

Do not mark a record fully synchronized before the external operation succeeds. Preserve retry metadata and useful error information without exposing secrets to users.

### 8. Files must be validated before processing

Apply configured size/count restrictions. Validate content type, extension, and parser expectations. Treat uploaded spreadsheets, PDFs, images, and WhatsApp exports as untrusted input.

Do not trust user filenames for storage paths. Use safe generated names and preserve original names only as metadata.

### 9. Production errors must not expose internals

Log full exceptions server-side. Return a stable, user-safe error response. Do not return stack traces, database errors, file paths, service-account details, raw Google API responses, or secrets.

### 10. Audit records must be append-oriented

Case updates, workflow events, decisions, sync attempts, and staff actions should be recorded rather than destructively rewritten. Correcting a mistake should usually create a new event/update while preserving history.

### 11. Timestamps are timezone-aware and locally meaningful

JBL operates in Kenya (`Africa/Nairobi`, UTC+3, no DST). Use `django.utils.timezone` for all datetime handling; never construct naive datetimes for TAT/stage calculations. When displaying times to staff in Mini Apps or Sheets, convert from UTC storage to `Africa/Nairobi` at the display boundary, not in the database layer.

---

## Security and privacy rules

### Never commit

- `.env`
- Telegram bot tokens
- Telegram webhook secrets
- Django secret keys
- API auth tokens
- Google service-account JSON
- private database URLs
- customer IDs, phone numbers, photos, signatures, invoices, chat exports, or production spreadsheets
- private Google Sheet or Drive identifiers unless explicitly approved and non-sensitive

Update `.env.example` with placeholders when adding configuration.

### If a secret is accidentally committed

Treat this as an incident, not a cleanup task:

1. Rotate the credential immediately at the source (Telegram BotFather for bot tokens, Google Cloud Console for service accounts, Django settings for secret key) — a `git revert` alone does not invalidate an exposed secret.
2. Do not rely on removing the file from the latest commit; it remains in Git history unless history is rewritten, which has its own risks on a shared repo and should be coordinated, not done unilaterally by an agent.
3. Report what was exposed, for how long, and what was rotated in the PR/commit description.

### Historical repository data

The repository has contained operational spreadsheets, WhatsApp exports, and customer media. Deleting a file from the working tree does not remove it from Git history.

Agents must not:

- copy production data into tests or fixtures
- quote customer data in commits or pull requests
- add generated customer files to the repository
- use real tokens in CI checks
- assume private Git hosting is sufficient data protection

Use synthetic fixtures.

### Telegram webhook

The production webhook must require `TELEGRAM_WEBHOOK_SECRET`. Preserve constant-time secret comparison. Do not add alternate unauthenticated webhook routes.

### Telegram Mini App authentication

Do not reimplement Telegram `initData` validation separately for new workflows. Reuse or extract a shared authenticator that:

1. Parses the query string
2. Removes the supplied hash
3. Constructs the canonical data-check string
4. Derives the signing key from the bot token
5. Calculates HMAC-SHA256
6. Uses constant-time comparison
7. Checks `auth_date` age
8. Returns a normalized Telegram user identity

Tests must cover invalid hash, expired data, malformed payload, missing user, and valid payload.

### Manual APIs

Endpoints intended for scripts/admin operations must require `API_AUTH_TOKEN` or stronger authorization. Do not use obscurity or an uncommon URL as protection.

### CSRF exemptions

`@csrf_exempt` is permitted only when a route has an appropriate non-cookie authentication mechanism, such as Telegram webhook secret validation or verified Telegram `initData`.

Every new exemption requires an explicit reason and tests proving unauthorized requests are rejected.

### Logging

Logs must be useful without leaking full personal data or secrets. Prefer record IDs, group IDs, workflow names, and correlation IDs. Redact tokens, authorization headers, signed Telegram payloads, credentials, and sensitive document content.

---

## External API limits and backoff

Both Telegram and Google APIs enforce rate limits that this platform can realistically hit during bulk operations (bulk Sheet reconciliation, mass notifications, large imports):

- **Telegram Bot API**: expect `429` responses with a `retry_after` value during bursts (e.g. broadcasting to many groups, rapid `setMyCommands` calls). Respect `retry_after` rather than a fixed retry interval; do not busy-loop retries.
- **Google Sheets/Drive APIs**: expect quota errors (HTTP 429/`RATE_LIMIT_EXCEEDED`, or `403` quota variants) under bulk writes. Batch reads/writes where the API supports it instead of per-row calls, and back off with jitter on retry.

When adding or modifying bulk operations, make retry/backoff behaviour explicit and covered by a test (mocking the rate-limit response), rather than relying on the caller happening to be slow.

---

## Coding conventions

### Python

- Confirm the actual pinned Python/Django versions in `requirements.txt`/`pyproject.toml` and `runtime.txt` before assuming a specific version — treat any version stated elsewhere in older docs as a starting point to verify, not a guarantee.
- Use four-space indentation
- Use `snake_case` for functions, variables, modules, and model fields
- Use `PascalCase` for classes and Django models
- Prefer type hints for new service-layer functions
- Prefer small pure helpers for parsing and normalization
- Keep HTTP concerns in views and business logic in services
- Use `transaction.atomic()` for multi-write state changes
- Use `select_for_update()` when concurrent transitions could conflict
- Use timezone-aware datetimes through `django.utils.timezone`
- Use `Decimal` for money
- Use Django settings rather than reading environment variables throughout the codebase
- Use structured, actionable error messages and dedicated exceptions where helpful
- If a linter/formatter config exists (e.g. `ruff`, `black`, `isort`, `flake8` — check for their config files at the repo root), run it before committing rather than hand-formatting to match surrounding code by eye.

### Django models and migrations

- Every model change requires a migration
- Never edit an applied migration to change production behaviour; create a new migration
- Add indexes for frequent queue/status/group lookups when justified
- Add database constraints for invariants that must survive concurrency
- Define `related_name` deliberately
- Avoid adding nullable fields without understanding existing records and backfill behaviour
- For status fields, use `TextChoices` or the established local convention
- Preserve audit timestamps and actor fields

After model changes, run:

```bash
python manage.py makemigrations --check --dry-run
python manage.py migrate
```

When a migration is intentionally needed:

```bash
python manage.py makemigrations core
python manage.py migrate
python manage.py makemigrations --check --dry-run
```

Review generated migrations before accepting them.

### Views and APIs

A view should normally:

1. Authenticate
2. Authorize
3. Parse and validate input
4. Call a service/application function
5. Map expected errors to stable responses
6. Return a response

Do not add substantial parsing, spreadsheet logic, file generation, or state-machine logic directly to `core/api/views.py` or `portal_views.py`.

Use consistent JSON response structures within each workflow. Preserve existing clients when changing response fields.

### Services

Service functions should make dependencies and side effects clear. Prefer explicit inputs over reading request globals. Separate:

- parsing
- validation
- state transition
- persistence
- external synchronization
- notification formatting

When a function performs multiple side effects, document ordering and partial-failure behaviour.

### JavaScript and templates

- Keep Mini Apps mobile-first
- Use Telegram theme variables when available
- Do not trust client-side validation as enforcement
- Escape user-controlled output
- Keep API URLs generated from Django or centralized in one client helper
- Preserve loading, retry, empty, success, and error states
- Prevent accidental duplicate submissions
- Validate with `node --check` for standalone Apps Script/JavaScript where applicable
- Include screenshots or a clear manual test record for visible changes

### Google Apps Script

Root `.gs` files are deployed separately from Django. A change may require both source-code updates and staff-side redeployment.

When changing Apps Script:

- Avoid hard-coded secrets
- Preserve expected sheet/tab/header names or provide a migration path
- Run syntax checks
- Document deployment/version steps
- Test against a copy of a spreadsheet, not production data

---

## Workflow ownership guide

Use this table to locate the likely change surface for a given workflow, and what must be preserved when touching it.

| Workflow | Key files | Preserve |
|---|---|---|
| **Complaint/case ingestion** | `core/api/views.py`, `services/parser.py`, `services/deduplication.py`, `services/case_updates.py`, `services/sheets.py`, `services/sheet_sync.py`, `core/models.py`, `core/tests.py`, `core/tests_data_quality.py` | Raw-message audit history, deduplication, group context, bot-owned vs. staff-owned sheet fields |
| **Complaint Cases Mini App** | `core/api/complaint_case_views.py`, `services/complaint_cases.py`, `templates/complaint_cases/`, `static/miniapp/complaint_cases.*`, `core/tests_complaint_cases.py` | Verified Telegram identity plus named group staff roles, group-scoped reads/writes, append-only case/evidence records, idempotent updates, and Drive failure metadata |
| **Group/workflow configuration** | `services/group_config.py`, `services/workflow_presets.py`, `services/telegram_command_menu.py`, `core/models.py`, `core/admin.py`, `core/tests_pipeline.py` | Database-managed group configuration; don't introduce environment-only config unless backward compatibility is deliberate |
| **Jawabu/FCA pipeline** | `services/jawabu.py`, `services/jawabu_master.py`, `services/jawabu_pipeline.py`, `services/fca.py`, `core/api/views.py`, `core/api/portal_views.py`, `templates/jawabu_farmers/`, `templates/fca_review/`, `templates/portal/`, `static/miniapp/portal.*`, `core/tests_pipeline.py` | Controlled state transitions, decision history, actor/timestamp metadata |
| **Requisitions and invoices** | `services/requisition.py`, `services/invoice_parser.py`, `core/api/portal_views.py`, `core/models.py`, requisition templates/workbooks, `core/tests_pipeline.py` | Money handling, order numbers, filenames, generated workbook contents, download authorization, idempotency |
| **Order approval** | `services/order_approval.py`, `core/api/views.py`, `templates/order_approval/`, `services/storage.py`, `core/models.py`, `core/tests_order_approval.py`, `order_approval_apps_script.gs` | Telegram authentication, lookup/suggestion APIs, attachment limits, duplicate submissions, media storage failures, sheet sync |
| **SPIN credit** | `services/spin_credit.py`, `core/api/views.py`, `templates/spin/`, `static/miniapp/spin_form.*`, `core/models.py`, `core/tests_spin_credit.py` | Analyst authorization, request-type requirements, phone/ID/amount normalization, attachment handling, completion audit fields |
| **TAT tracker** | `services/tat_tracker.py`, `core/api/views.py`, `templates/tat_tracker/`, `static/miniapp/tat_tracker.*`, `tat_tracker_apps_script.gs`, `core/models.py`, `core/tests_tat_tracker.py` | Role restrictions, branch/product scope, stage prerequisites, duplicate create requests, timestamp calculations, event history |
| **Google Sheets/Drive integrations** | `services/sheets.py`, `services/sheet_sync.py`, `services/sheet_schema.py`, `services/sheet_analyzer.py`, `services/live_sheet_records.py`, `services/storage.py`, `core/tests_sheets_validation.py` | Mock external APIs in tests; test retries, missing headers, formula columns, reordered columns, partial failures, duplicate rows |

---

## Adding a new workflow

The existing workflows (order approval, SPIN, TAT tracker, Jawabu/FCA) share a repeatable shape. When adding a new one, follow the same pattern rather than inventing a new structure:

1. **Model(s)** in `core/models.py` — include actor, timestamp, and status/stage fields from the start; register in `core/admin.py`.
2. **Service module** in `core/services/<workflow>.py` — parsing, validation, state-transition, and persistence logic, kept separate from Telegram/HTTP concerns.
3. **View(s)** in `core/api/views.py` (or a new file if the workflow is large) — authenticate → authorize → parse/validate → call service → map errors → respond. Register routes in `core/api/urls.py`.
4. **Mini App template + static assets** (if the workflow needs a UI) under `core/templates/<workflow>/` and `core/static/miniapp/` — mobile-first, Telegram theme variables, loading/error/empty states, duplicate-submit prevention.
5. **Tests** in a dedicated `core/tests_<workflow>.py` — cover authentication, authorization, valid/invalid transitions, idempotency, and any file/media handling per [Test requirements by change type](#test-requirements-by-change-type).
6. **Sheet/Drive integration** (if applicable) — define field ownership explicitly (`backend-owned`/`sheet-owned`/`formula-owned`/`derived`/`immutable`) before writing sync code.
7. **Documentation** — add the workflow to the [Repository map](#repository-map) and [Workflow ownership guide](#workflow-ownership-guide) tables, and add any new domain terms to the [Domain glossary](#domain-glossary).
8. **Environment variables** — add any new config to `.env.example` and the [Environment variables](#environment-variables) table.

---

## Development setup

### Create an environment

```bash
python -m venv .venv
```

Activate it:

```bash
# Linux/macOS
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Create local configuration:

```bash
cp .env.example .env
```

Use SQLite for isolated local work unless PostgreSQL-specific behaviour is under test. Never point local tests at a production database, Sheet, Drive folder, or Telegram webhook.

Apply migrations:

```bash
python manage.py migrate
```

Run the server:

```bash
python manage.py runserver
```

Health endpoint:

```text
GET /api/health/
```

Because `core.api.urls` is also included at the root, some routes may be reachable with and without `/api/`. Do not add new duplicate root routing unless compatibility requires it.

---

## Validation commands

### Fast syntax and configuration checks

```bash
python -m compileall config core
python manage.py check
python manage.py makemigrations --check --dry-run
```

### Focused tests

Run the nearest suite first:

```bash
python manage.py test core.tests_tat_tracker
python manage.py test core.tests_spin_credit
python manage.py test core.tests_order_approval
python manage.py test core.tests_pipeline
python manage.py test core.tests_sheets_validation
python manage.py test core.tests_group_reset
python manage.py test core.tests_data_quality
```

Run a class or method when iterating:

```bash
python manage.py test core.tests_tat_tracker.TatTrackerApiTests
python manage.py test core.tests_tat_tracker.TatTrackerApiTests.test_name
```

Use the actual class/method name from the test file.

### Full suite

```bash
python manage.py test
```

### Coverage

```bash
coverage erase
coverage run manage.py test
coverage report -m
```

### Apps Script syntax

```bash
cp order_approval_apps_script.gs /tmp/order_approval_apps_script.js
node --check /tmp/order_approval_apps_script.js
```

Repeat for other `.gs` files changed in the task.

### Deployment-oriented checks

```bash
python manage.py collectstatic --noinput
python manage.py check --deploy
```

`check --deploy` may report expected local-environment warnings. Do not suppress legitimate production-security warnings without justification.

---

## Test requirements by change type

### Parser or normalization change

Add tests for:

- expected format
- missing fields
- malformed fields
- whitespace/case variants
- Kenyan phone formats where relevant
- amount/date edge cases
- multiple cases in one input
- non-target messages
- duplicate inputs

### Model/state change

Add tests for:

- valid transition
- invalid transition
- concurrent/idempotent retry
- database constraints
- actor and timestamp recording
- migration compatibility with existing data

### Authentication/authorization change

Add tests for:

- missing credentials
- malformed credentials
- invalid signature/token
- expired Telegram data
- authenticated but unauthorized actor
- authorized actor
- wrong group/branch/role

### Sheet synchronization change

Add tests for:

- expected headers
- reordered headers
- missing required headers
- formula-owned columns
- append/update distinction
- external failure
- retry metadata
- duplicate prevention
- local state after sync failure

### File/media change

Add tests for:

- valid upload
- oversize file
- unsupported type
- excessive count/total size
- unsafe filename
- storage failure
- duplicate content where hashing is used
- authorization to download/access

### Mini App UI change

Verify manually on a narrow mobile viewport and, where possible, Telegram's webview. Check:

- light and dark Telegram themes
- keyboard-open layout
- loading/error/empty states
- double-tap/double-submit behaviour
- stale session/auth data
- slow network
- long names and values
- attachment selection/cancellation

---

## External side effects

Agents must not perform real external writes unless explicitly requested and properly authorized.

Do not, by default:

- register or replace a production Telegram webhook
- call `setMyCommands` against the production bot
- write to production Google Sheets
- upload to production Google Drive
- send Telegram messages to real groups/users
- run destructive synchronization
- reset group data
- generate or expose real customer documents

Use mocks, local fixtures, test groups, copied spreadsheets, and development credentials.

If a management command can mutate external systems, inspect it before running it and state the intended target.

---

## Data migration and synchronization discipline

Before changing schemas or mappings:

1. Identify existing records affected
2. Identify external sheet columns affected
3. Define source-of-truth ownership
4. Define backfill/default behaviour
5. Define rollback behaviour
6. Add migration tests or data checks
7. Update `.env.example`, admin, scripts, and documentation as needed

Never silently reinterpret an existing status value or spreadsheet column. Introduce a mapping or migration.

For destructive reset/sync behaviour, require explicit scope and make the operation repeatable and auditable.

---

## Background work and reliability

Long-running work should not be added casually to a request/response path or a process-local thread.

Examples:

- large WhatsApp imports
- bulk Sheet reconciliation
- Google Drive uploads
- invoice parsing
- requisition generation
- large spreadsheet writes

For new critical background work, prefer a durable job model/queue. At minimum, persist:

- job identity
- requested by
- requested at
- status
- progress/counts
- retry count
- last error
- completion timestamp
- idempotency key

Do not assume a Render/Gunicorn worker will remain alive after returning a response.

---

## Refactoring guidance

The current `core` app is a large modular monolith. Improve boundaries incrementally; do not perform an unrequested "big bang" rewrite.

Preferred extraction direction:

```text
telegram_gateway
staff/authorization
group_configuration
complaints
jawabu
order_approval
spin
tat_tracker
requisitions
integrations/google_sheets
integrations/google_drive
```

When refactoring:

- preserve public routes unless migration is intentional
- preserve model/table names unless a migration is necessary
- move tests with behaviour
- avoid circular imports
- keep shared integration code workflow-agnostic
- introduce compatibility wrappers when moving heavily used functions
- make one bounded change per pull request where practical

Do not mix broad architecture refactors with unrelated business-rule changes.

---

## Documentation rules

When behaviour changes, update the smallest canonical document that users or operators rely on.

Prefer documenting:

- current architecture
- current environment variables
- deployment steps
- staff workflow steps
- data ownership
- security model
- migration/rollback instructions

Do not create another "implementation complete" or duplicate summary file. Update an existing canonical document or place historical notes under an archive location.

Code comments should explain why a non-obvious rule exists, not repeat the code.

---

## Commit and pull-request expectations

### Commits

Use focused, descriptive messages, for example:

```text
Fix duplicate TAT case creation on retried requests
Require staff role for SPIN analyst completion
Preserve sheet-owned status during complaint resync
Add retry metadata for Drive upload failures
```

Do not include customer data, secrets, generated production files, or unrelated formatting changes.

### Pull requests

Include:

- workflow(s) affected
- problem and root cause
- implementation approach
- security/data-integrity implications
- migrations and backfill requirements
- environment-variable changes
- external deployment steps
- tests run and results
- screenshots for Mini App changes
- rollback notes for risky changes

Explicitly call out any change to:

- authentication/authorization
- status transitions
- spreadsheet headers or formulas
- generated workbook format
- money calculations
- data deletion/reset behaviour
- webhook configuration

---

## Definition of done

A change is complete only when all relevant items are true:

- Behaviour is implemented in the correct layer
- Authentication and authorization are enforced
- Idempotency and concurrency were considered
- Data ownership and sync behaviour are clear
- Errors are safe for users and useful in logs
- Tests cover success, failure, and retry paths
- Model changes have reviewed migrations
- Focused tests pass
- Full tests pass, or unrelated failures are documented with evidence
- No secret or customer data was added
- `.env.example` reflects new settings
- User/operator documentation is updated
- External deployment steps are documented
- Visible UI changes were manually checked

---

## Agent response format

At the end of a coding task, report:

1. What changed
2. Why it changed
3. Files changed
4. Tests/checks run and their results
5. Migrations/configuration/deployment actions required
6. Remaining risks or unresolved issues

Be explicit when a test or external integration could not be executed. Never claim a production integration works based only on mocked tests.

---

## Quick decision checklist

Before editing, ask internally:

- Which workflow owns this behaviour?
- Is the code path a webhook, Mini App, manual API, management command, or background job?
- What authenticates the caller?
- What authorizes the action?
- What prevents duplicate execution?
- Which database records and external rows/files change?
- Who owns each affected field?
- What happens if Google or Telegram fails halfway?
- What audit record proves what happened?
- Which focused test file should change?

If these questions do not have clear answers, inspect more code before modifying behaviour.
