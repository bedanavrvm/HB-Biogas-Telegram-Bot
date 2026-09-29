# CI and Frontend Quality Gates

The continuous-integration workflow validates backend and first-party frontend
code without contacting production Telegram, Google, Africa's Talking, or
e-signature services. Browser scenarios intercept API traffic and use synthetic
identities and files.

## Immediate gates

CI runs these checks before the full Django suite:

- `npm run check:js` parses every first-party JavaScript file with Node. Vendored
  libraries are excluded and remain governed by their pinned dependency.
- `npm run test:node` executes the diagnostics and request-id/idempotency unit
  suites.
- `npm run test:browser` executes the Chromium Mini App contract tests for
  bootstrap, denied authentication, double-submit prevention, mobile navigation,
  multipart retry, and Origination test signing.
- Playwright retains screenshots and video for failed tests; traces are retained
  on local failures and captured on the first retry in CI. GitHub Actions uploads
  browser failure evidence only when the job fails, retaining it for 14 days.
- `ruff check config core scripts` applies only the correctness rules configured
  in `pyproject.toml`; it does not format the repository.
- The settings/environment, runtime dependency, write-route inventory, artifact
  privacy, migration graph, migration-drift, and Apps Script checks run directly
  from their governed scripts.
- `scripts/check_dependency_vulnerabilities.py` runs `pip-audit` against the
  installed runtime. Any exception must name one advisory and package, explain
  the control, and expire. `PYSEC-2026-3412` for WeasyPrint is temporarily
  accepted through 2026-09-30 because no fixed release is available; document
  inputs remain governed and server-generated.

The Python dependency manifests and Node lockfile are installation inputs. A
dependency change must update both `requirements.txt` and `pyproject.toml`, run
the parity check, and regenerate `package-lock.json` when JavaScript tooling
changes.

## Coverage policy

Coverage is collected with branch measurement. Tests and migrations are omitted
from the report so the baseline describes application code. CI publishes
`coverage.json` and `coverage-subsystems.json`; the latter records line and
branch coverage for API, services, management commands, models, admin, and the
remaining core code.

The initial gate deliberately avoids subsystem quotas. It enforces two reviewed
conditions:

1. Total application coverage may not fall below
   `scripts/coverage_baseline.json`.
2. Branches introduced on changed `core/services/` lines must be exercised.

Update the baseline only after a complete, repeatable suite and review the
resulting subsystem deltas. A lower baseline is a policy change, not routine
test maintenance.

## Local commands

```bash
npm ci
npx playwright install chromium
npm run check:js
npm run test:node
npm run test:browser

# Open the newest failure trace, or pass a specific trace .zip path after --
npm run test:e2e:trace:show
# npm run test:e2e:trace:show -- test-results/playwright/path/to/trace.zip

# Force full tracing for every test; append a Playwright file/pattern as needed
npm run test:e2e:trace -- core/tests_browser/miniapp_flows.spec.js --grep "payment"

ruff check config core scripts
python scripts/check_settings_env_parity.py
python scripts/check_dependency_parity.py
python scripts/check_miniapp_write_inventory.py
python scripts/check_repository_artifacts.py
python scripts/check_dependency_vulnerabilities.py
python scripts/check_migration_graph.py
python manage.py makemigrations --check --dry-run

coverage erase
coverage run --branch --source=core manage.py test
coverage json -o coverage.json
python scripts/check_coverage_quality.py
coverage report
```

For a pull request, pass the fetched target branch to reproduce changed-service
enforcement, for example `--base-ref origin/main`.

## Trace Viewer

After a local browser-test failure, run `npm run test:e2e:trace:show` to open the
most recently modified trace archive. Pass a specific `.zip` path after `--` to
open that trace instead. To deliberately capture every step, use
`npm run test:e2e:trace -- <Playwright file or pattern>` and append normal
Playwright filters such as `--grep` as needed.

## Playwright MCP authoring tool

Install the pinned MCP server with `npm ci`, then start an isolated local Django
server using a fresh SQLite database. In PowerShell:

```powershell
New-Item -ItemType Directory -Force test-results | Out-Null
$env:DATABASE_URL = 'sqlite:///test-results/mcp-synthetic.sqlite3'
$env:DEBUG = 'True'
$env:DJANGO_SECRET_KEY = 'local-only-synthetic-browser-session'
$env:TELEGRAM_BOT_TOKEN = 'not-a-real-telegram-token'
$env:TELEGRAM_WEBHOOK_SECRET = 'local-only-synthetic-webhook-secret'
$env:GOOGLE_SERVICE_ACCOUNT_FILE = ''
$env:GOOGLE_DRIVE_MEDIA_FOLDER_ID = ''
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

The project MCP entry is in `.codex/config.toml`; reload the trusted project in
Codex after changing it. It starts isolated Chromium and loads the shared
`core/tests_browser/fixtures/local_mcp_fixtures.js` init script. The same file
is exercised by `local_mcp_fixture.spec.js`. It gives the app a synthetic
Telegram identity, serves synthetic Portal API reads, rejects API writes, and
blocks external fetches and external links. Use `http://127.0.0.1:8000/portal/`
in the MCP browser. Only the local shell HTML is served by Django; operational
data and integrations remain mocked. Do not seed real records into this
database.

For conversational authoring, describe a flow, drive it through MCP against
that local fixture, and ask for a Playwright test using the existing suite's
locators and conventions. Review and clean up generated code, and run the
relevant test before committing it. The fixture is read-only by design; test
write behavior in the existing isolated Playwright tests.

MCP sessions and trace files are local development tools only. Never point them
at staging or production, and never process real customer data; use only the
project's synthetic or mocked fixtures. The origin allowlist is an extra guard,
not authorization to use a non-local target.

