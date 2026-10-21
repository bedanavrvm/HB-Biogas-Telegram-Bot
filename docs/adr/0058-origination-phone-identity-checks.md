# ADR 0058: Advisory Origination phone registration checks

## Context

The approved IT pilot checks either saved Applicant phone against the Applicant's
National ID using Safaricom Mobile Number Validation. Calls may be billable.
Origination application revisions, signing evidence and workflow authority must
remain unchanged. Exact results must be reusable across Origination applications
for thirty days without exposing the original application.

## Decision

Own the implementation and three new tables in `origination`: pseudonymous
subject locks, immutable terminal attempt evidence, and Nairobi-day dispatch
allowances. Existing application events provide actor-attributed, request-keyed
receipts. No raw identifiers or provider bodies enter the new tables. Subject
HMACs use a separate deployment secret and environment/account context.

Only a complete scoped Origination IT grant or active Superuser may use the
pilot. A checked-in capability migration increments the access-policy version.
The feature is disabled by default. Confirmation authorizes one operator action;
it is not customer consent. A fresh conclusive result is reused for thirty days;
only a new explicit confirmation may start another paid attempt. Production
dispatch reservations are capped at fifty per Nairobi calendar day, independently
of account/credential rotation. There are no background paid retries.

Network calls occur outside database transactions. Subject locks, operation
claims, a one-in-flight constraint and finalization fencing prevent concurrent
duplicate dispatches. Expired leases and lost responses are uncertain, not
mismatches. Read-only status polling never resumes signing dispatch. Phone-check
events do not adopt form-projection policy or change application timestamps.

## Consequences

Safaricom onboarding, approved identifier disclosure, credentials and separate
authorization for real calls are deployment responsibilities. Shared evidence
survives application/product deletion; expiry ends reuse, not audit retention.
No automatic purge is added. Provider failures leave the application usable.
The inline UI is a source-bound candidate using existing styles; this decision
does not approve Design Lab foundations or Phase 6 migration.

Operational rollback: disable `ORIGINATION_PHONE_ID_CHECK_ENABLED`. Keep evidence.
Destructive schema reversal, only after backup/export and explicit approval:
`python manage.py migrate origination 0009_signer_sms_provider`, followed by
`python manage.py migrate core 0206_advanta_integration`. These reverse
Origination 0010/0011 and core 0207. Never reverse unrelated later migrations or
run these commands against production by default. Capability policy evidence is
retained but ignored by older code; reversal increments the access-policy version.

## Alternatives considered

- Store flags on applications: rejected because checks are independent evidence,
  and workflow revisions/signed snapshots must not change.
- Reuse only within one application: rejected by the approved cost/reuse policy.
- Rely on client disabling or process-local locks: rejected across workers.
- Automatically retry timeouts: rejected because billing outcome is uncertain.
- Add identity OTP or approval gating: outside the approved advisory pilot.

## Implementation reference

See `codebase-analysis-docs/assets/PHONE_ID_CHECKS.md` for configuration, API,
retention, review evidence and verification results.

## 21 October 2026: explicit recheck and safe diagnostics

The operator needs to investigate unexpected results and deliberately request a
new check, rather than be trapped by thirty-day result reuse. A confirmed
`fresh_check: true` bypasses conclusive-result reuse for that action only. It
does not bypass an in-flight check, current IT scope, saved-value binding,
request-key replay protection, the operator throttle or the fifty-per-day
allowance. Ordinary requests retain thirty-day reuse. The flag is part of the
request fingerprint without changing fingerprints of historical ordinary
requests. Every fresh attempt and its receipt are new records; old outcomes
remain immutable. There are still no automatic paid retries.

The existing Integration Operation retains a bounded, allowlisted diagnostic
view of the exchange and the adapter emits the same safe structure to logs.
Phone/National ID and credentials are never logged or copied into diagnostics;
untrusted free-text/unknown response fields are excluded. Environment, API path,
request reference, safe response codes/status/reference and interpretation
remain visible. OAuth payloads are excluded. Existing exact response parsing is
unchanged; diagnostics do not claim the public provider contract was verified.

The compact recheck icon uses the existing Origination icon-button pattern and
one explicit cost warning. Sandbox results are labelled as test results. This
is a narrow UI candidate, not permission to migrate foundations or other apps.
No new schema, dependency, role or automatic dispatch is introduced.

Alternatives rejected: deleting cached evidence, making every request skip
reuse, allowing overlapping paid calls, or logging unrestricted payloads. A
code rollback restores ordinary reuse and leaves all recorded evidence intact.
