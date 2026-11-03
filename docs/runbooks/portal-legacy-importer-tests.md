# Legacy importer regression suite

Run from the repository root with the installed Python dependencies. Python 3.12
and the repository's Node version are the supported CI configuration. The tests
generate synthetic XLSX files; no operational workbook is needed or committed.

## Commands (PowerShell)

For the API/database suite and the navigation regression:

```powershell
.\.venv\Scripts\Activate.ps1
$env:DEBUG = "True"
$env:DATABASE_URL = "sqlite:///local-tests.sqlite3"
python manage.py test portal_legacy.tests core.tests_portal_navigation --settings=config.settings --noinput --verbosity 2
```

SQLite verifies validation and transaction rollback, but does not establish
PostgreSQL row locking. To run on PostgreSQL, first create a disposable local
database and use a local role with permission to create Django's test database.
Set TEST_DATABASE_URL with those credentials. The checked-in profile rejects
remote hosts and database names without "test".

```powershell
$env:TEST_DATABASE_URL = "postgresql://LOCAL_TEST_USER:LOCAL_TEST_PASSWORD@127.0.0.1:5432/jbl_test"
python manage.py test portal_legacy.tests portal_legacy.tests_browser.LegacyConcurrentTests core.tests_portal_navigation --settings=config.settings_test_postgres --noinput --verbosity 2
```

The actual Django/Playwright workflow is opt-in so a backend-only installation
does not require Node/Chromium. It starts its own loopback Django server, uses
real signed Telegram authentication and drives the checked-in UI. No separate
review server, private settings or retained rehearsal database is required.

```powershell
npm.cmd ci
npx.cmd playwright install chromium
$env:RUN_PORTAL_LEGACY_E2E = "1"
python manage.py test portal_legacy core.tests_portal_navigation core.tests_portal_imports core.tests_portal_full_reset --settings=config.settings_test_postgres --noinput --verbosity 2
```

Run the command through manage.py as shown: this also selects Django's explicit
test runtime. Calling the management API from a stdin script without setting
sys.argv leaves the repository's test-runtime flag off and can invalidate
authentication-disabled fixtures in unrelated old suites.

CI includes portal_legacy in the PostgreSQL regression job and enables the
Playwright workflow after installing Node and Chromium. The ordinary Django job
also discovers the API suite; browser and PostgreSQL-only checks clearly skip
when their prerequisites are absent.

## Boundaries and coverage

The checked-in importer suite has 52 API/database methods, one PostgreSQL
independent-worker method and one real Django/Playwright method. The separate
navigation module includes the regression for the reported dictionary identity.

- portal_legacy/tests.py drives signed HTTP requests through authentication,
  authorization, chunk storage, XLSX decoding, staging, row approval, governed
  test cleanup, canonical commit, snapshot, replacement and readback. Assertions
  inspect responses and persisted cases, provenance, audit events, number claims
  and independent sheet cells. Expected amounts/dates/formulas are literal
  worked examples, rather than results calculated by the production importer.
- test_support.py supplies synthetic workbook builders and the used Google SDK
  boundary. Real importer, authorization, database, deletion and financial
  reservation code remain active. Only provider IO and the API test clock are
  substituted. The provider applies wire-level clear/copy/metadata operations
  and can lose its acknowledgement after atomic application.
- tests_browser.py checks two independent HTTP workers against PostgreSQL while
  one provider call is deliberately held. The second worker must receive a
  conflict while the first retains the lease. This check is skipped on SQLite.
- The Playwright workflow uses the real shell and AG Grid, uploads 61 rows,
  reviews table/cards, retains approval across register switches/reload,
  paginates to the second page, commits in bounded requests, projects Eco and
  reads its target. It asserts that the Master sentinel survives. Screenshots
  at 320/390/1280 and observations are saved under
  test-results/legacy-importer-automated-browser/.

Negative cases cover unsigned/unauthorized/revoked access, workflow and owner
isolation, branch-role scope composition, source retargeting, conflicting chunks,
incomplete/checksum-invalid workbooks, duplicate mappings/rows, missing source
identity, excessive columns/XML, shared formulas across cache reconstruction,
stale revisions, active/expired leases, unapproved records, invalid money,
unresolved identity collisions, deletion policy/token/fingerprint changes,
concurrent cutover holds, empty sources and attempts to restart completed work.

Projection checks cover both register directions, exact counterpart preservation,
all-row/case coverage, foreign live Case IDs, destination aliasing, manual-edit
confirmation, cell capacity, changed snapshots, retained backups, corrupt readback,
held publication and lost replacement acknowledgement without a duplicate write.
Legacy phone originals, unknown stages, dates, zero/unknown deposits and consumed
financial references remain distinguishable from fabricated workflow evidence.

## Bugs retained as regressions

The navigation suite reproduced the original eight errors before the fix. The
Legacy menu's real-user check now follows capability filtering and rejects a
dictionary identity for legacy access without breaking unrelated presentation
fixtures. Permanent staff authority is unchanged.

New importer checks exposed discarded-file replay returning an unusable discarded
session, empty workbooks starting a hold with no viable replacement, and leaked
decode-cache handles on oversized XML rejection. The fixes respectively reopen
only the uncommitted discarded session, reject empty cleanup before any hold, and
close the cache database on both success and parsing failure.

A full fresh PostgreSQL run also caught a branch-limited IT grant combining
with a whole-owner Operations grant at the import boundary. The importer now
passes the requested resource scope to its IT capability check, so the same IT
grant must satisfy branch, product and owner; the wider Operations grant cannot
supply its missing scope. Other workflows' grant semantics are unchanged.

The suite does not establish live Google behavior, physical Telegram-device
acceptance, production instance memory headroom or a full 50,000-case canonical
commit/replacement. It does not delete/import production data or deploy code.

## Local verification, 3 November 2026

The final combined PostgreSQL command ran **112 tests, all passing** in 96.743
seconds: importer API/worker/browser coverage plus navigation, FarmUp/SysUp and
Portal reset regressions. Actual Playwright screenshots/observations are in
test-results/legacy-importer-automated-browser/; the complete local log is
test-results/legacy-final-regressions-postgres.log. Django checks, migration
drift, database governance, write-route inventory, UI-source ratchet, Python/JS
syntax and git diff whitespace checks passed.

This local environment used Python 3.14.6 / Django 5.1.6. CI is configured for
the repository's pinned Python 3.12 dependencies; that remote CI run was not
performed here. The 112-test result is a scoped local result, not the whole
repository suite or production acceptance.
