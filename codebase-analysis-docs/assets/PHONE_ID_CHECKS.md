# Optional Applicant phone registration check

Implementation date: 19 October 2026. Workflow: `loan_origination` only.
Architecture decision: `docs/adr/0058-origination-phone-identity-checks.md`.
This reference supplements the earlier repository snapshot in
`codebase-analysis-docs/CODEBASE_KNOWLEDGE.md`.

## Behaviour and authority

`origination/services/phone_identity.py` owns the advisory IT pilot. Its
`allowed()` resolves one complete current Origination IT group/branch/product
grant and full application access. Active Superusers retain the existing
break-glass override. `is_staff`, Portal/TAT grants, officer ownership and
Telegram authentication alone do not authorize checks. The new capability is
`origination.identity.phone.verify`; migration 0011 seeds IT and increments the
policy version so active sessions refresh. A policy edit cannot bypass the
service's explicit pilot role restriction.

The Mini App offers a small action next to valid Applicant primary and alternate
phones, including in read-only saved applications. A dirty editable draft must
first pass the existing save path. Only its assigned officer may edit; verification
does not grant IT new field-editing authority. The popup confirms masked saved
identifiers, possible cost and advisory meaning. It is an operator confirmation,
not an assertion of customer consent. Cancel creates no verification request.

Matches and mismatches are reusable for thirty rolling days across Origination
applications, for the exact normalized phone/National-ID pair in the same
provider context. Each application creates its own confirmed receipt before
presenting shared evidence. No source application identity is exposed. Both
phones use the Applicant's own ID; a household-owned alternative can legitimately
not match. Neither result authenticates a handset, validates a statement, merges
customers, authorizes signing or approves a loan.

There are no checks on typing, validation, autosave, page loading or expiry.
There are no provider callbacks, automatic paid retries, SMS, Telegram alerts,
Google writes, new approval rules or signing-document changes.

## Source map and safety boundaries

- `origination/services/daraja_phone_identity.py`: bounded HTTP, OAuth token
  caching, explicit Boolean/code parsing, safe outcome allowlist; no paid retry.
- `origination/services/phone_identity.py`: saved subject resolution, exact-tuple
  pilot authorization, request receipts, admission locks, quota and finalization.
- `origination/models.py`: independent subject/check/daily-usage records.
- `origination/views.py::portal_origination_phone_identity_checks` and
  `origination/urls.py`: authenticated GET/POST transport.
- `origination/static/miniapp/phone_identity_checks.js`: inline presentation,
  one confirmation and read-only polling. `loan_origination.js` supplies current
  application, existing save/API helpers and read-only contact rendering.
- `origination/services/loan_origination.py::_record_event`: the new optional
  `adopt_form_projection=False` prevents check events adopting form policy.

Do not use the ordinary application-detail GET for polling: it calls
`resume_application_work()`. The dedicated check GET never resumes that work.
Do not select the primary phone from the general `person_fields()` mapping:
multiple applicant phones can collapse into a single entry. Explicit captured
Applicant identity mapping wins; the alternate is canonical
`applicant_other_phone`, not a label-based match.

The check itself never saves the application. Its status, revision, `updated_at`,
values, identity/document snapshots, requirements, package hashes and signatures
remain unchanged. An ordinary user-requested draft save before checking retains
its existing, separately audited semantics.

## Persistent evidence and concurrency

| Table | Purpose and retention |
|---|---|
| `origination_phone_identity_subject_state` | Unique pseudonymous provider-context/pair lock; retained with linked audit evidence |
| `origination_phone_identity_check_record` | One provider attempt; immutable terminal outcome, safe codes/references and timestamps; retained with Origination/compliance audit evidence |
| `origination_phone_identity_daily_usage` | Environment/Nairobi-date dispatch counter, independent of credential changes; retained operational evidence |

No raw phone/ID copies or provider response bodies enter these tables or
operation metadata. Pair digests use a dedicated HMAC secret, not a guessable
unkeyed identity hash. Provider context separates environment, account, shortcode
and digest protocol/key. Browser binding tokens additionally bind application,
target and revision. Application receipt IDs are local events, not global check
IDs or access tokens.

Admission briefly locks the application and subject. A fresh match/mismatch is
reused without extending expiry; a pending attempt is joined. Otherwise one
operation is reserved. Network calls occur after transaction release. The
adapter's pre-dispatch callback rechecks saved values, configuration and current
actor access, then atomically increments daily usage and marks dispatch. Operation
tokens and the one-in-flight constraint fence completion. After 120 seconds a
lease is uncertain; only a newly confirmed action may reserve a successor. Old
request-key replays never issue another call, and late results cannot replace
terminal/successor evidence.

Shared evidence deliberately has no application FK: deleting the first application
cannot delete another application's evidence. These models are excluded from
selected Mini App testing deletion. Thirty-day expiry stops reuse; it does not
purge evidence. No automatic purge is introduced.

## Configuration and provider prerequisites

Store credentials and the digest secret in the deployment secret store; never
commit real values. The settings are declared in `config/settings.py` and
`.env.example`:

| Setting | Default / meaning |
|---|---|
| `ORIGINATION_PHONE_ID_CHECK_ENABLED` | `False`; explicit deployment switch |
| `ORIGINATION_PHONE_ID_CHECK_DAILY_LIMIT` | `50`; only positive values up to 50 are accepted in this pilot |
| `DARAJA_ENVIRONMENT` | `sandbox`; only sandbox/production are allowlisted |
| `DARAJA_CONSUMER_KEY` | Empty; approved Daraja application's key |
| `DARAJA_CONSUMER_SECRET` | Empty; server-only OAuth secret |
| `DARAJA_SHORTCODE` | Empty; subscribed organization's numeric shortcode |
| `DARAJA_PHONE_ID_HMAC_KEY` | Empty; separate stable random secret of at least 32 characters |

Use sandbox only in a dedicated synthetic-data deployment. Production activation
requires approved Safaricom subscription/commercial onboarding, authorization
for identifier disclosure, production credentials and an explicitly approved
real-call check. There is no automatic environment fallback. Secret/account
changes invalidate token/cache context, but do not reset production daily usage.

The adapter uses server-side OAuth and
`https://api.safaricom.co.ke/v1/KYC-validation/validateID` (the corresponding
sandbox host in tests). National ID is the only supported document type in this
release. It accepts consistent `4000`/true and `4001`/false pairs; string
`"false"` is explicitly false. Inconsistent, malformed, unsupported or error
responses are unavailable/uncertain, never an inferred mismatch.
[Official Mobile Number Validation reference](https://developer.safaricom.co.ke/apis/MobileNumberValidation).

### Pricing and limits

The published first volume band is interpreted as **KES 4.50 per billable call**,
not KES 4.50 for an entire range. For example, 50 billable calls are approximately
KES 225; checking primary and alternate separately can require two calls. The
commercial agreement must confirm taxes, failed-call billing and volume-tier
application. The code does not hardcode a tariff or claim to be a billing ledger.

The production cap is fifty dispatch reservations per Africa/Nairobi calendar
date. Cache reuse, polling and identical request replays consume no allowance.
OAuth failure before dispatch consumes none. A reserved dispatch is not refunded
for lost/error responses. Sandbox has a separate counter. An additional privacy-
safe per-operator ten-new-actions/minute throttle limits abuse. Zero, negative,
over-pilot-limit or incomplete configuration fails closed, never unlimited.

## API and failure handling

GET/POST:
`/api/origination/api/applications/<application_id>/phone-id-checks/`.
Use the current signed Telegram identity and existing idempotency headers.

This endpoint is CSRF-exempt because every staff request is authenticated by
verified Telegram `initData`, not by a browser session cookie. The Origination
authentication wrapper and the scoped-IT/Superuser service authorization still
run for every request. A cookie-only login, missing/invalid/expired Telegram
signature, another Mini App's IT role or an out-of-scope grant cannot authorize
a check. Do not disable CSRF middleware globally or add cookie authentication
as a fallback. The 21 October fix corrects the missing endpoint exemption that
caused `CSRF token missing` before these checks could execute; it requires only
normal code deployment, not a new migration or configuration change.

GET returns `phone_id_checks` with server-resolved targets, eligibility, application
revision, opaque saved-value token and this application's receipt-linked status.
It does not expose shared results before this application confirms their use.

Example POST, containing no phone or ID values:

```json
{
  "target": "primary",
  "revision": 12,
  "subject_token": "<from current GET>",
  "confirmed": true,
  "confirmation_version": 1,
  "client_request_id": "<stable unique key>"
}
```

Results contain application-local `receipt_id`, target, status, freshness,
`applies_to_current_values`, `reused`, original completion time and reuse expiry.
States are `not_checked`, `checking`, `matched`, `not_matched`, `unavailable`, or
`unknown`; freshness distinguishes current, changed and expired evidence.

GET and receipts now identify the environment. Sandbox feedback is explicitly
labelled `Sandbox test`; a test mismatch is not presented without that context.
This label does not assert which pairs Safaricom's sandbox supports.

### Check again and diagnostics (21 October 2026)

After a result, the refresh icon beside it means **Check again**, not merely
reload the saved status. It opens one confirmation with the saved phone/ID
suffixes and warns that a charge may apply. Cancellation sends no check. While
a check is running the icon is disabled. It remains available in read-only
applications to authorized Origination IT/Superusers; it never grants editing
or approval authority.

The confirmed POST adds `"fresh_check": true` and uses a new stable request key.
Only a Boolean is accepted. This bypasses thirty-day conclusive-result reuse
for this action only; default/false requests retain normal reuse. An in-flight
attempt is joined before either reuse or new dispatch, including when an older
conclusive result exists. Same-key retries return the same receipt without a
second call. Adding the flag to a previous ordinary request key is a conflict,
not permission to reinterpret it. Historical ordinary fingerprints stay valid.
All existing scope, confirmation, value/revision, throttle and daily-allowance
checks remain. Prior outcomes/receipts are never deleted or rewritten.

New calls emit structured INFO messages beginning:

```text
Origination Daraja phone check request:
Origination Daraja phone check response:
```

In Render logs, search for that prefix or the safe `requestRefID`. The diagnostic
includes environment, provider URL, request structure, identifier lengths, HTTP
status, allowlisted response code/status/reference fields and interpretation.
Known response envelopes retain their structure with free text/other values
omitted or redacted. Phone/ID values and all credentials are excluded; OAuth
payloads are never logged. This is a safe diagnostic view, not an unrestricted
raw request/response archive, and it cannot recover earlier discarded bodies.

The same final diagnostic is retained as `provider_exchange` in the existing
Integration Operation metadata. In Django Admin, open **Integration operations**,
filter integration `daraja` and type `origination_phone_identity`, and inspect
the matching operation's metadata. `source_id` is the attempt UUID sent as
`requestRefID`; an application-local `receipt_id` is a different identifier.
Neither HTTP 200 nor operation success alone establishes a positive match.
Old operations have no diagnostic backfill. GET/reuse does not make a provider
call or manufacture a new exchange log. Provider response parsing is unchanged;
logging is not proof that the external contract or a live result is correct.

- `200`: conclusive evidence or reuse; `202`: existing execution pending.
- `400`: invalid input/confirmation; `403`: current pilot authority denied.
- `409`: revision/identity/request-key conflict.
- `429`: daily/operator allowance, with `Retry-After` when applicable.
- `503`: disabled/configuration/provider/circuit unavailability or uncertainty.

The UI polls only the dedicated GET every two seconds, at most two minutes.
Transport loss never automatically replays a POST. A new explicit confirmation
after uncertainty may incur another charge. Unrelated application edits do not
invalidate the pair evidence, but a stale browser must refresh before confirming.

For unavailable service, hand off to IT/Superuser to inspect configuration,
the `daraja` circuit and `origination_phone_identity` operations. Do not reset an
operation's attempts to resend it. Fix readiness, then use a fresh explicit
application confirmation. A daily cap is cleared only by the next Nairobi day,
not manual counter deletion. Other operational and signing work remains usable.

## Deployment and rollback

1. Review migrations core 0207, Origination 0010 and 0011; back up before any
   authorized production migration. No customer backfill is required.
2. Apply checked-in migrations and collect static assets using the normal
   explicitly authorized deployment process. Leave the feature flag false.
3. Run PostgreSQL parity/concurrency tests against a guarded local test database.
4. Review the source-bound UI candidate and real Telegram/native-font behaviour.
5. Validate an explicitly authorized synthetic sandbox setup. No implementation
   or CI test is permission for real provider calls.
6. After commercial/privacy approval, configure production and enable the flag
   for the scoped IT pilot. Retain 30-day reuse and the 50/day cap.

Operational rollback: set `ORIGINATION_PHONE_ID_CHECK_ENABLED=False` and apply
that environment change to every running worker. This hides new actions and
stops new dispatches without deleting evidence; already-dispatched work may
complete. Authorized IT
can still read retained receipts. Do not clear counters or rewrite signing data.

Destructive schema reversal, only after explicit approval and evidence export:

```text
python manage.py migrate origination 0009_signer_sms_provider
python manage.py migrate core 0206_advanta_integration
```

These reverse Origination 0010/0011 and core 0207. First check that no unrelated
later migrations would also be reversed. Capability policy history is retained
and its version bumped; older code ignores the new capability.

## UI candidate and evidence

This is a narrow, user-requested inline-action candidate, **not human design
approval**. Existing field/button/Telegram popup patterns are reused. The only
new style is a scoped 44px minimum target, matching existing controls. No lab
tokens, foundation migration, visual-baseline refresh or Phase 6 activation is
included. The source ratchet's `changes` references this record; legacy hashes
remain untouched. Design Lab source discovery follows the template's new script.

The 21 October user-requested extension reuses the existing Origination refresh
glyph and icon-button pattern beside the result, with a 44px target and wrapping
status text. It adds no global design tokens or unrelated UI changes. The real
shell browser suite covers fresh/reused outcomes, explicit fresh flag and new
request key, cancellation, double click, loading, failure, stale revision,
non-IT denial and read-only applications. Eleven Chromium checks passed in the
initial UI run. Light/dark screenshots were inspected at 360px under:

```text
test-results/playwright/origination_phone_identity-257d7-quests-a-fresh-check-light-/phone-check-again-light.png
test-results/playwright/origination_phone_identity-cc913-equests-a-fresh-check-dark-/phone-check-again-dark.png
```

These are temporary synthetic candidate evidence, not approved baselines or
proof of deployed fonts/native Telegram behaviour. The HTML bumps only the
changed phone-check script and compact stylesheet cache versions. Deploy and
collect static assets normally; no new migration, setting or dependency is
needed for this extension. Do not enable production provider calls implicitly.

`core/tests_browser/origination_phone_identity.spec.js` renders the real
Origination shell, styles, field renderer and action controller with synthetic
API data. It captures 360px light/dark, reused, mismatch, loading and unavailable
states under `test-results/playwright/`. Those ignored captures are temporary
review evidence, not approved or committed baselines. Remote/deployed fonts and
real Telegram native popups are not proven by browser captures.

Reproduce with `npx playwright test
core/tests_browser/origination_phone_identity.spec.js --workers=1`. Source hashes
and the final verification record are in `PHONE_ID_CHECK_VERIFICATION.md` in this
directory. Human/native review remains a production activation prerequisite.

## Verification state

Initial narrow run: twelve backend tests passed and the PostgreSQL concurrency
test skipped on SQLite; six initial real-shell browser tests passed. Expanded
verification is recorded separately rather than claiming live-provider success.

Pre-existing governance findings were reproduced by reading HEAD source in
memory: settings/environment parity has 119 findings, and the shared unsafe-route
inventory has 34. Both counts are unchanged; the new settings/route are covered.
Architecture checking also reports the existing direct requisition event write
in `core/api/portal_views.py::portal_requisition_finalize`.

No Safaricom verification, Google/Drive write, staff message, production migration,
webhook change or deployment occurred during implementation.
