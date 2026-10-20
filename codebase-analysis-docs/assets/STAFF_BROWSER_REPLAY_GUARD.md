# Shared browser TOTP one-use guard — P1b.2b.2

20 October 2026. Starts at `bb232703` on Platform-Interdependence. This is a
closed backend increment, not operational browser admission. Browser remains
disabled, E006 blocking and production auth/business routes unmounted. Actual
deployed release/migrations are unknown. No commit, merge, deployment, real
staff action or external provider write is performed by this increment.

## 1. Scope and implementation

The existing local virtual environment lacked the already-pinned
`django-allauth[mfa]==65.20.0`. Restoring that package and its declared extras
repairs local startup; no Python/frontend manifest or pin was changed. This is
not a new dependency decision or frontend installation.

Pinned native TOTP validation uses the default Django cache's `add()`. That
cache is process-local here, and is also used by Origination template caching,
Daraja tokens and diagnostic suppression. This increment leaves it unchanged.
The official allauth shared-cache/rate-limit requirements remain applicable:
https://docs.allauth.org/en/latest/common/rate_limits.html .

`staff_auth/replay.py` subclasses the pinned native headless MFA input/view.
Native validation runs first; a successful TOTP then reserves shared use before
the native form saves authentication or the browser login receipt is completed.
Only the constrained browser handler selects this subclass. No vendor code or
global cache object is patched in runtime code. The unmounted headed fixtures
remain historical native-library evidence, not an alternate certified surface.

The key is HMAC-SHA256, purpose-separated and keyed by the factor's decrypted
seed, covering the native factor ID and native-normalized code. Native strips
ASCII punctuation and whitespace during comparison; matching representations
must reserve the same key. Pin/upgrade review must retain that relationship.
The new table stores only the digest and expiry: no plaintext code, factor seed,
employee identity, network address, serialized general cache values or new FK.
Encryption-key/Django-secret rotation does not change the logical claim key.

The unique primary key admits one insert. Expired renewal uses a conditional
update on the old expiry; PostgreSQL must recheck that condition after a
competing updater releases the row. A claim lives conservatively for
`MFA_TOTP_PERIOD * (2 * MFA_TOTP_TOLERANCE + 1)` seconds after acceptance.
Unexpired claims are not general cache entries and must not be evicted.

## 2. Request and failure behavior

The existing relative `POST v1/mfa/` contract is retained. A duplicate native
TOTP attempt returns the ordinary `mfa_required` 400 and grants no assurance.
The first admitted session's existing authenticated lost-response retry still
returns success without creating a second claim or login audit. A fresh native
code can be used for a new login. Native recovery-code locking/consumption stays
unchanged and creates no TOTP claim.

Replay-store failure returns `authentication_unavailable` 503 with no secret or
backend diagnostics. Current browser authentication context is discarded and,
because Django skips automatic session saves on 5xx, cleanup is saved explicitly
when that session store remains available. An unavailable session store cannot
guarantee persisted cleanup; no successful authentication response or new
assurance is issued. Native factor-key failure also fails closed.

Later audit failure can leave the valid code consumed without a usable login.
Use a fresh code. Never remove a live claim or reset factors to make that same
code succeed. A claim is replay state, not evidence of successful login; the
existing native/password/MFA/active-admission/audit/workflow guards remain.

## 3. Schema, retention and rollback

- Additive migration: `staff_auth.0002_stafftotpreplaystate`, no backfill.
- Table: `staff_auth_totp_replay_state`, model `StaffTOTPReplayState`.
- PK: 64-character keyed digest. The expiry index exists only to find bounded
  expired-only cleanup batches; catalogue metadata and PostgreSQL comments are
  checked in.
- Cleanup: `python manage.py purge_staff_totp_replays` previews at most 1,000
  expired claims. `--batch-size` allows 1–10,000. `--apply` rechecks expiry during
  deletion, preserving any selected claim that was concurrently renewed.
- No cleanup job is registered or executed against operational data. Name its
  operator/schedule before production admission; expired claims may be safely
  renewed in place until then. Cleanup never changes native factors/admissions,
  users, grants, audit or business state.

Normal application rollback leaves the browser off and retains the additive
table. Exact destructive reversal **before operational use** is:

```text
python manage.py migrate staff_auth 0001_initial
```

This removes only the new replay table. It requires actual release authority,
backup/compatibility review and all browser authentication workers closed.
Preserve `staff_auth.0001_initial` and native credentials. Do not reverse the
table while any worker can authenticate, clear live rows or restore the database
to undo this feature. If security state is lost, all earlier native code windows
must end before fresh password/MFA admission. No production action is authorized.

## 4. Verification and limits

The restored pre-change baseline passed **140 tests: 136 passed and four
PostgreSQL-only skips**, using the configured native password hasher. The first
new focused run passed **14 tests: 12 passed and two PostgreSQL-only skips**.
The final combined run passed **156 tests: 150 passed and six PostgreSQL-only
skips**, including all **14 new SQLite tests** and two new replay-race skips.
The other four skips are the existing lifecycle/enrollment races. The suite is:

```text
python manage.py test staff_auth core.tests_telegram_authentication core.tests_user_identity core.tests_user_hard_delete --noinput --verbosity 0
```

Execution used an ignored local harness with process-local synthetic settings,
in-memory SQLite, denied external sockets and a test-only MD5 password hasher
for the expanded rerun. No committed password-hasher setting changed. The
separate 140-test baseline above used the configured native hasher; the fast
rerun does not certify production KDF performance. Logs remain ignored under
`test-results/staff-browser-p1b-baseline.txt`, `staff-browser-replay-focused.txt`,
`staff-browser-replay-final.txt` and `staff-browser-replay-governance.txt`.
No deployment/customer credentials or operational data were used.

The new tests cover independent native cache instances, native-normalized code
variants, wrong-code denial, fresh-code acceptance, outage and login-audit
failure, unchanged recovery-code consumption, key rotation, expiry and cleanup.
Two real-PostgreSQL-only tests cover first-use and expired-renewal races.

Other executed passes: all **44 governance/tool tests**; Django system check;
no migration drift; migration graph (**289 migrations, 19 leaves**); model
governance; regenerated/verified database catalogue (**214 application tables**);
architecture boundaries; **202-route** Mini App write inventory; UI source
ratchet; Python compilation; dependency parity (**28 direct packages**) and
`pip check`; offline D13 review-snapshot binding; changed/untracked-file secret
pattern and whitespace checks; isolated SQLite migration forward/reversal
retaining the existing admission fixture and `auth_user`.

Wider checks are still not all green: **119** existing environment-template
omissions; **17** existing allowlisted-artifact hash mismatches; dependency audit
held by the `PYSEC-2026-3412` exception expired on 2026-09-30. No allowlist,
exception, security default or test baseline was relaxed. Ruff/PostgreSQL tools
are unavailable locally. Full application CI, production, actual workers,
real-device/staging, mail or frontend/legal readiness is not established.

Independent in-memory cache instances are a synthetic boundary test, not an
actual deployed multi-worker or PostgreSQL result. The broader native shared
rate-limit/cache topology, controlled provisioning/password/verified address,
notifications, helpdesk/recovery, staff offboarding acceptance, real Telegram/
browser/device journeys, support handover, D13 frontend acceptance and M1 remain
open. No production mount, general allauth URL, real enrollment, grant change,
global cache setting or Telegram frontend change occurs.

The formatted-code fixture also established that pinned native local-cache
`CacheKeyWarning` can include its raw code-bearing key. The test captures that
expected warning without printing synthetic codes; no runtime warning filter is
installed. Native cache key/log privacy is part of the remaining shared-cache/M1
work and must be resolved before operational routes are mounted. HMAC storage
in this new table does not sanitize the native local cache or general logging.

## 5. Change-specific handoff checklist

- [x] Bounded shared browser TOTP guard, additive security table, metadata,
  preview-first cleanup, ADR 0064 and tests supplied.
- [x] No frontend dependency/configuration variable/production route, business
  capability or Telegram asset/authentication change. Existing missing local
  dependency restored from its committed pin.
- [x] Record executed focused/native/Telegram/user lifecycle and governance
  results, explicit skips/failures and isolated migration reversal evidence.
- [ ] Before merge, review native normalization, expiry, conditional update,
  outage/audit behavior and all source compatibility evidence. Confirm actual
  branch auto-deploy behavior before seeking any merge/release authority.
- [ ] Before operational admission, execute PostgreSQL races, review allauth
  worker/cache topology and remaining P1b/P1c/M0/M1/support/privacy gates. This
  guard does not supply a shared native rate-limit cache.
- [ ] Before deployment, inspect actual deployed commit/migrations, backup,
  old-app/new-schema overlap and approved rollout/rollback. Keep browser off,
  E006 blocking and auth/business URLs unmounted.
- [ ] After any authorized shared-auth deploy, verify existing Telegram and
  Admin login/read/write journeys. No browser MFA traffic is expected while
  unmounted. Investigate unexpected exposure, duplicate admitted code, backend
  outage, missing audit, plaintext credentials or cleanup of a live claim.
- [ ] Normal rollback preserves accepted login audit/admission/factors and live
  replay claims. Use a compatible application or reviewed forward correction;
  the off flag cannot repair a shared-runtime regression.

### STATE BLOCK

- INDEX_VERSION: staff-browser-replay-1 / P1b.2b.2 / 20 October 2026.
- FILE_MAP_SUMMARY: staff_auth/replay.py, browser_api.py, models.py, catalogue.py,
  admin.py, migration 0002, purge_staff_totp_replays, tests_replay.py; ADR 0064;
  plan/release checklist/catalogue and governance documentation.
- OPEN_QUESTIONS: provisioning, verified recovery/support, native shared rate
  cache, notifications, PostgreSQL, deployed baseline, cleanup/support owners,
  D13 and M1. No operational admission authorized.
- KNOWN_RISKS: native upgrade/normalization drift, claims lost by unsafe cleanup
  or rollback, unexecuted concurrency, authentication failure after code use,
  premature mounts and existing wider CI findings.
- NEXT_READ_QUEUE: remaining bounded P1b prerequisite; resolve exact frontend
  graph; P1c; M1 before Complaints. Preserve later M3 review.
- VERIFICATION: final 156 tests (150 passed, six PostgreSQL-only skips), all 44
  governance/tool tests, isolated SQLite additive/reversal rehearsal and relevant
  static/catalogue checks passed. Existing 119 environment/17 artifact/expired
  dependency-audit gates remain. No full CI, PostgreSQL, actual worker/device,
  staging, frontend or production claim.
