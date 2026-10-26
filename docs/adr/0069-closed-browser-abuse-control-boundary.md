# ADR 0069: closed browser abuse-control boundary

23 October amendment: ADR 0074 supersedes the Redis/Memcached-only backend
requirement below with the explicitly approved PostgreSQL native-state adapter.
All other authentication, privacy, failure and activation boundaries remain.

## Context

The user authorized continuing the platform-independence plan after the guided
onboarding client. Native shared-cache operation is still an M1 gate. Inspection
found that the browser's outer database limiter trusted arbitrary X-Forwarded-For
values, native throttling was normalized into credential errors, and native TOTP
cache keys could expose submitted codes in backend keys or warnings.

## Decision

Deliver P1b.2b.4 as one dormant abuse-control hardening slice. Resolve network
identity through the pinned allauth proxy/IP policy (including its IPv6 prefix),
then HMAC it before using the existing database throttle. Default proxy trust is
zero; deployment must separately prove its topology. Apply the same policy to
anonymous setup bootstrap. Do not change Telegram/public endpoint IP behavior.

Use Django's supported KEY_FUNCTION hook on the existing default local cache.
HMAC native allauth keys, including prefix/version, before backend validation;
preserve Django's exact key function for every other cache namespace. This is
privacy protection, not a shared cache or a replacement TOTP verifier. No vendor
module patch, new service, dependency, model, migration or environment knob.

Block attempted activation unless the default cache selects a reviewed Django
Redis/Memcached backend with the privacy key function. This static check does
not connect to a service or certify shared topology, capacity, non-eviction,
consistency, atomic add, credentials, or worker operation. Those demonstrations
remain mandatory before M1. E006 and the production route closure remain.

Preserve native throttle denials as JSON 429, without exposing native messages.
Contain failures at the native authentication invocation boundary, return a
fixed unavailable response, and discard only this request's browser context.
Never fall back to another credential/cache/identity or automatically replay
credentials. Keep an ordinary Admin/other-channel cookie intact. Existing
transactional enrollment/audit/one-time recovery policies remain authoritative.

An outer database-limiter failure occurs before native credentials are acted
on. Return unavailable and preserve the existing session/progress for a later
explicit retry, while blocking that request. Do not erase a verified invitation
or enrollment draft merely because its limiter is unavailable. Native-operation
failures still discard incomplete login context as described above.

## Consequences

The local default cache stays process-local, so activation additionally fails
the cache prerequisite. No operational admission is enabled and the user flow
gets no extra steps. Existing non-allauth cache keys/values and Telegram limits
remain unchanged. New native-key digests invalidate old native cache entries;
before operational use there are none to preserve. Future secret/key-function
rotation or backend changes require a drained rollout or a full live-window
hold, not mixed workers or premature clearing of abuse/replay state.

Rollback this code/config slice with browser access off. No schema reversal;
preserve credentials, admissions, shared TOTP claims, sessions and audit. Any
future operational rollout must retain live security cache state through its
longest TTL. Do not claim PostgreSQL, shared-worker or M1 acceptance locally.

## Alternatives considered

- Install a new cache service/client now: requires a separately approved
  dependency/topology and operational evidence; no silent installation.
- Use Django DatabaseCache or FileBasedCache as an assumed atomic replacement:
  does not establish the required concurrency/failure semantics.
- Suppress cache warnings or relax limits: hides secrets or weakens protection.
- Replace allauth rate limiting or change every workflow's IP trust: unnecessary
  scope and a risk to existing Telegram operation.

References (consulted 20 October 2026):
https://docs.allauth.org/en/latest/common/rate_limits.html ;
https://docs.djangoproject.com/en/5.2/topics/cache/#cache-key-transformation .
Implementation reviewed against installed allauth 65.20.0 and Django 5.2.17.

Existing frontend feedback was checked against current ADS guidance:
https://atlassian.design/components/form/usage ;
https://atlassian.design/components/section-message/usage . The existing
`staff-access.tsx` Form/MessageWrapper/SectionMessage composition retains
persistent authentication/connectivity feedback in the form sequence. This
slice changes server error classification, not components/tokens/layout, and
adds no new field, confirmation or design-conformance claim.

Verification also makes synthetic admission/authentication/revocation instants
explicit. Adjacent datetime/time readings can straddle different Windows clock
ticks (observed locally at roughly 16 ms). Test fixtures no longer infer strict
event ordering from immediate wall-clock calls. Runtime expiry checks remain
strict; a native same-tick revocation test proves admission-generation denial.
