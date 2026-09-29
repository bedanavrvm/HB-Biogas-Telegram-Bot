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

MCP setup is pending a reusable synthetic browser fixture. The current E2E
suite installs Telegram/API mocks inside individual tests, so an independent
MCP browser cannot reuse those mocks without first extracting them. Do not use
an MCP browser against a running Portal until that shared fixture and a
localhost-only setup are in place; otherwise authentication and integrations
would not be guaranteed to stay synthetic.

When enabled, MCP sessions and trace files are local development tools only.
Never point them at staging or production, and never process real customer data;
use only the project's synthetic or mocked fixtures. Review and clean up
generated tests like hand-written code before committing them.

