# JBL standalone browser client

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
