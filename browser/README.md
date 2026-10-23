# JBL standalone browser client

The ADR 0073 operations candidate is a **separate native build**, not the local
demo: `npm run build -- --complaints-operations` (optionally `--development`).
Its company-authenticated Complaint actions, safe soft navigation and reporting
are exercised only by the isolated Django transport runner. Production stays
off/unmounted. Setup, evidence, rollback and remaining parity/release gates:
[`browser-channel-parity.md`](../docs/runbooks/browser-channel-parity.md).

The 22 October UI correction is in this **native operations** entry, not the
older 8767 simulator. From the repository root run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_complaints_local_review.ps1
```

Wait for readiness, then open **http://127.0.0.1:8769/_review/** and use only the
synthetic sign-in shown there. Leave that terminal running. If an older review
host is already running, stop it with Ctrl+C and restart the same command:
each process pins its startup assets. Agent builds do not update that process.
The fresh review seed now includes varied branches, types, dates and statuses.
It does not use or change operational data. See DESIGN.md for the UI brief,
intentional differences and current review boundaries.

This workspace uses **React 18 and actual Atlassian Design System components**.
The current entry is a local, deterministic access-flow demo: fixed read-only
values, no API, credentials, mail, staff/customer records or workflow grants.
It does not activate the dormant Django browser authentication boundary.

Use Node **22.23.3** (`.nvmrc`); tested with npm **11.19.0**. Keep the root
Telegram package manifest/lock separate. From the repository root, in a shell
using that runtime:

```powershell
npm --prefix browser ci
npm --prefix browser run check:dependencies
node browser/scripts/check-context.cjs
npm --prefix browser run typecheck
npm --prefix browser run lint
npm --prefix browser run build
.venv/Scripts/python.exe scripts/serve_ads_browser_preview.py
```

Open **http://127.0.0.1:8766/** on this computer. Ctrl+C stops the server. Open
**http://127.0.0.1:8766/review.html** for the separate design harness with labelled
ADS Page/Theme/Response selects. The staff presentation has no scenario controls.
Review selections do not represent backend
authority. All credential fields stay read-only and recovery labels are invalid.
Refresh/Reset demo restarts in-memory state. Business tools remain disconnected.
The earlier custom wireframe on port 8765 is historical, not this ADS build.
Keep the server session running; restart the documented command if the local
terminal/session ends. No background service or public deployment is installed.

`.npmrc` enforces exact strict-peer/engine installation and disables lifecycle
scripts. Parcel/Compiled is configured explicitly; automatic dependency install
is disabled in the build. The build records its exact dependency lock, modules,
packages, output hashes and readable third-party notices. Only manifest-listed
flat HTML/JS/CSS/notices can be served. No source maps, node_modules, repository
files, queries or API are exposed. Local CSP blocks connections, form submits,
remote assets and fonts. Runtime-inserted theme styles are allowed only for this
data-free loopback demo. The static Parcel import map gets an exact CSP hash
and may name only reviewed local modules. Production nonce/CSP/static integration
is separate. The dedicated browser-client CI job installs/checks/builds this
workspace and captures synthetic browser evidence; it has no deployment step.

See [dependency decision](DEPENDENCIES.md), `dependency-review.json` and ADR 0066
for exact versions, the scoped context compatibility exception, fixed development
selector parser, licence sources, asset exclusions and maintenance boundary.
The dependency checker rejects additional original-peer mismatches or another
React renderer. The build rejects unreviewed packages/licences and excluded
font/image/native/brand-glyph modules. No Atlassian branding or fonts are copied.

Run the actual source/build browser checks after starting the default server:

```powershell
node scripts/test_ads_browser_preview.js
.venv/Scripts/python.exe -m unittest scripts.tests.test_ads_browser_preview
```

For the separate development StrictMode check, build with
`node browser/scripts/build.cjs --development`, start
`python scripts/serve_ads_browser_preview.py --development --port 8767`, then run
`node scripts/test_ads_browser_preview.js --development`. Development outputs and
captures are separate ignored directories; the normal preview stays on 8766.

Screenshots and the source-bound report go to ignored
`test-results/ads-browser-preview/`. These are synthetic evidence, not human
approval, WCAG certification or real-device/native-auth acceptance. Component
mapping and source hashes are in `docs/ui-standard/component-index.md` and
`registry.json`. All browser pages use ADS Box/Grid/Inline/Stack layouts,
Heading/Text typography, Anchor/LinkButton navigation and existing form/status
components. Styling uses typed `@atlaskit/css` cssMap/xcss and `token()` calls;
responsive queries use the supported ADS breakpoint. Content widths are app
geometry, not visual tokens. No first-party stylesheet, global/font override,
native selector or component skin remains. ADS's typography token system-font
fallbacks are used without shipping proprietary fonts.

Read `DESIGN.md` and the current official Atlassian guidance before changing UI.
Access tasks use one bounded column with title/description, persistent section
feedback, fields and action in reading order. The workspace uses actual ADS
Root/TopNav/Main/SideNav and side-nav-items, with a 1296px content grid including
margins. Default surfaces, borders and neutral groups replace the raised-page
frame and nested sunken boxes. There is one screen-level fixed-value notice.
Technical checks and viewport fit do not establish design quality or full ADS
conformance; screenshots remain candidates for human review.

Desktop checks cover staff/review compositions at 1280x720, 1366x768 and 1440x900
in both themes, plus every form's error/retry states on the shared review
renderer. Mobile/enlarged text keeps natural scrolling and readable typography.
The Navigation System supplies its own main scroll region and skip navigation;
the test asserts current laptop content fits both body and main regions.

Both ADS plugins' **complete recommended rule sets** run as errors, including
advisory guidance. Do not reintroduce native layout classes or disable the
styling rules. The single line-scoped read-only input exception protects this
synthetic demo from real credential entry. Build manifests bind first-party
source hashes; browser checks reject stale builds, verify first-painted field
colors and typography against loaded ADS tokens in both themes, and check flat
surfaces, bounded tasks, feedback order and viewport fit. They do not certify
an Atlassian product or replace human review.

No production bundle/static integration, backend URL, configuration secret,
database migration or business permission is added. M1 remains open for actual
auth/CSRF, proof delivery/interrupted setup/recovery, shared cache/privacy,
PostgreSQL, support/backup owners, staging and both-channel acceptance.
Rollback stops the local server and reverts this workspace/tooling/docs; retain
the backend's existing staff, credentials, sessions, audit and workflow data.

## Closed native authentication and onboarding (P1c.5/P1c.6)

ADR 0067 adds a **separate dormant build**, not another mode of the synthetic
preview. `node browser/scripts/build.cjs --authentication` builds editable ADS
password/MFA/recovery-login fields against fixed same-origin
`/api/staff/auth/v1/` paths. Add `--development` for the separate StrictMode build.
Neither is mounted by Django or served by the loopback demo. Production browser
authentication stays off and E006 blocking. No operational login URL is supplied.

Routine sign-in has two short steps, uses standard autofill, retains the username
after mistakes and resumes the server-owned stage on refresh. Recovery is on the
code screen. CSRF refresh/rotation and session checks happen in the background;
uncertain requests prompt a safe session read rather than resending credentials.
Secrets are cleared from forms and never stored or logged. Workflow tools
and real staff/provider delivery remain separate increments.
ADR 0068 adds the local guided existing-account invitation, first-password,
QR/manual-key enrollment and one-time recovery handoff. The invitation uses a
fragment erased before requests and is consumed only by explicit Continue.
Verified setup and fresh enrollment drafts resume from their bound server
session. One create-password action invokes native setup/login/recheck without
retaining the password between screens. Saving codes enters fresh sign-in;
setup never grants identity assurance or workflow access. No operational
invitation URL, mail dispatch or proof export is supplied by this local build.

Run real React -> Django middleware/database sessions -> native allauth tests
with the existing root Playwright tooling and Python environment. From a shell
using the pinned Node runtime, set synthetic values for `DEBUG=True`,
`DJANGO_SECRET_KEY` and empty Google/Sentry credential variables, then:

```powershell
node browser/scripts/build.cjs --authentication
node browser/scripts/build.cjs --authentication --development
$env:RUN_STAFF_BROWSER_E2E='1'
python manage.py test staff_auth --settings=staff_auth.transport_test_settings --keepdb --noinput
```

The opt-in settings refuse a non-test runner and always use the full checked-in
schema in `test-results/staff-browser-transport.sqlite3`. This never opens the
workspace/production database. `--keepdb` permits local repeat checks; it does
not preserve operational data. Tests create their own synthetic users, native
factors and explicit admission, with no workflow grants. Ordinary staff_auth
discovery skips the two browser runs unless explicitly opted in. CI builds and
executes both in the isolated browser-client job; configured CI is not evidence
of a completed remote run.

Only test URLconf `staff_auth.transport_test_urls` hosts this entry and the
native handlers, with test-only guards and verified source/build/asset hashes.
Its two context probes test identity success and existing Complaints denial;
they expose no cases and are not P2 endpoints. Requests stay on ephemeral
loopback, Python outbound connections are rejected, and email uses locmem.
Proof travels to the browser runner through stdin only. Reports contain source
hashes, request paths/methods, bounds and synthetic captures with QR/key/codes masked under
`test-results/staff-browser-transport/{production,development}/`.

This remains local SQLite/headless evidence. PostgreSQL races, real devices,
assistive review, operational shared cache, production static/CSP/session origin,
actual delivery/recovery support and M0/M1 remain acceptance gates. No
dependency, schema, policy matrix, Telegram, merge or deployment change applies.

## Closed Complaints integration

### Latest native workspace: one-command local review

Responsive correction checks use the existing Playwright CLI against a dedicated
loopback review host. They never persist credentials or browser session state:

```powershell
$env:COMPLAINTS_REVIEW_ORIGIN='http://127.0.0.1:8769'
node node_modules/playwright/cli.js test core/tests_browser/complaints_responsive.spec.js --workers=1
```

To check the development artifact, set
`COMPLAINTS_REVIEW_BUILD=dist-complaints-operations-development` after building it.
This test context loads hash-checked build assets itself; other tabs keep their
startup-pinned UI. Native requests still use the isolated host's real cookie,
CSRF, MFA and owning Complaint authorization. Restart an older host if its API
predates the current source. Captures are synthetic review evidence under
`test-results/playwright/`, not approved screenshot baselines.

The opted-in `staff_auth.tests_complaints_operations_transport` suite also runs
this CLI spec against fresh native sessions in both build modes. It supplies
synthetic credentials only to child-process memory, so CI does not need the human
review host or consume its recovery codes. Those captures are retained separately
under `test-results/complaints-responsive/<build>/`.

From the repository root, keep this foreground PowerShell terminal open:

```powershell
.\scripts\start_complaints_local_review.ps1
```

If Node 22 is not found automatically, pass `-NodePath 'C:\path\to\node.exe'`.
This uses the existing dependencies; it does not download/install a runtime or
change production settings. It builds the latest operations entry, creates a
fresh **dedicated synthetic SQLite test database**, applies the checked-in test
schema, then prints `Local synthetic review ready`. Initial preparation takes
longer than an ordinary server start. Open http://127.0.0.1:8769/_review/ on the
same computer. That loopback-only page supplies the synthetic username/password
and an unused recovery code. Follow the ordinary password/MFA sign-in, choosing
**Use a recovery code**. Refresh the instructions for another unused code.
No actual staff account is needed. Enter sample values/files only.

The latest queue, reports, settings and activity use the real native adapter
and owning Complaint authorization against test fixtures. Server connections
outside loopback are blocked; email uses locmem. No actual Sheets, Drive, SMS or
Telegram delivery occurs. This is not the older no-account simulator below.
Changes last until restart/stop (Ctrl+C); the server also stops after 12 hours.
Each start has its own database under `test-results/complaints-local-review/`,
so stopping a previous test process cannot leave duplicate fixture users on
restart or interfere with the automated tests' database. Files are ignored local
test artifacts, not production backups; no automatic operational cleanup runs.
Build assets are verified and pinned at startup. Further agent edits/builds
cannot change the version currently being reviewed; restart to see new changes.

If the browser reports connection refused, first check the terminal is still
running and has printed the readiness message. A stopped/failed process is not
an installed service. Rerun the command; do not enable production browser flags
or use `runserver` against deployment settings as a substitute.

For the persistent, no-account synthetic review demo, open
http://127.0.0.1:8767/ on this computer. Restart it from the repository root:

```powershell
$browserNode = (Resolve-Path test-results/node-v22.23.3/node.exe).Path
& $browserNode browser/scripts/build.cjs --complaints-demo
.venv/Scripts/python.exe scripts/serve_complaints_demo.py
```

Use the pinned Node runtime described below. The server stays available until
stopped (Ctrl+C for a foreground run); it is not an installed Windows service.
It opens straight into synthetic cases, with working search/status/paging/
detail/history and Exit/Open demo actions. No password or MFA setup is needed.
Use **Demo role** to follow a realistic local handoff:

1. **Complaint Officer:** New complaint, fill customer details (or Fill sample
   customer), Continue, select the workspace/branch/category and record details.
   Choose image/PDF files or Use sample image, then Record complaint.
2. **HB Resolver:** the same case stays selected. Take action, Add resolution
   comment to save feedback while leaving it open; Upload evidence to add files;
   Resolve complaint to close it with a resolution note.
3. **Complaint Manager:** Reopen complaint with a reason. Search CMP-3 to complete
   the historical Needs details record. Managers can also create/upload.
4. **IT Support:** explicit scoped technical override. **Portal HB** demonstrates
   that another workflow's role grants no Complaint access.

View image previews or explicitly download a PDF from the case evidence.
Uploads are limited to ten files per action, 10 MB each/30 MB total, with a
60 MB sandbox budget. Extension/signature checks match supported file types;
duplicate content is reused per case. Choose files opens the native file chooser.
Creation Back retains complaint text and selected files. Every saved action
records the synthetic actor and Nairobi timestamp in history. Roles use current
built-in policy, not deployment-specific overrides or real staff permissions.

Entered values, action history and uploaded bytes stay in process memory, shared
across demo tabs/roles and retained on refresh. **Reset demo** or server restart
clears them and restores ten seed cases. This is a local review simulator.
Its isolated, integrity-checked SQLite fixture is under
`test-results/complaints-local-demo/fixture-v2.sqlite3` (the old v1 seed is retained).
No Django initialization,
`.env`, operational database, auth route, account/grant or external provider is
used. Only `/demo-api/complaints/v1/` simulator routes are exposed; API calls omit
cookies. POSTs require the same local Origin and demo header. The immutable seed
stays read-only. The 8766 fixed access preview remains separate. ADR 0072 governs
role journeys; ADR 0071 governs the original availability. This
review demo; it is not a live staff pilot or native-auth acceptance.

For development-mode review, build with `--complaints-demo --development` and
run the server with `--development --port 8768`. Tests:

```powershell
python -m unittest scripts.tests.test_complaints_demo scripts.tests.test_complaints_demo_sandbox
node scripts/test_complaints_demo.js
node scripts/test_complaints_demo.js --development
```

The browser checks expect those two loopback servers to be running. Reports
and synthetic captures are under `test-results/complaints-local-demo/` by mode.

ADR 0070 / P2a adds a separate dormant workspace, alongside remaining M1 work:

```powershell
node browser/scripts/build.cjs --complaints
node browser/scripts/build.cjs --complaints --development
$env:RUN_STAFF_BROWSER_E2E='1'
python manage.py test core.tests_browser_complaints staff_auth.tests_complaints_transport --settings=staff_auth.transport_test_settings --keepdb --noinput
```

Use the pinned Node 22.23.3 runtime for builds and set
`STAFF_BROWSER_TEST_NODE` to that executable when it is not your shell's Node.
The test-only `staff_auth.complaints_transport_test_urls` verifies the exact
Complaints build/source/assets and native login before accessing synthetic
cases. It is separate from both the fixed preview and pure-auth harness.
Reports/captures live in `test-results/complaints-browser-transport/` by mode.
No customer data, credential screenshots, external publication or real staff
admission. These settings always select the isolated full-schema SQLite test DB.

This connects current Complaint permissions and list/search/paging/detail/
history. The allowlisted candidate omits phone/National ID, Telegram/source
identifiers, raw messages, evidence/location URLs and history notes/diffs.
Names/descriptions still need privacy acceptance before operational use.
Production remains off/unmounted; M1 and named-reader acceptance still apply.
