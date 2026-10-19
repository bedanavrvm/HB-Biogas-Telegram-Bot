# Platform-independence phase, merge and deployment checklist

Use a change-specific copy at **every phase handoff and every proposed/completed merge or deployment**. Do not report unchecked items as passed. “Not applicable” requires a reason. Branch creation, implementation approval and passing CI do not authorize a merge, production deployment, migration, access-policy change or real external side effect.

Use the existing `docs/production-release-record.md` and `PRODUCTION_RUNBOOK.md` for actual production governance. Keep completed private records, user/cohort identities, credentials and production screenshots outside Git. Link this checklist rather than creating competing release records.

## 1. Identify the change

- [ ] Phase/app/milestone and primary business driver.
- [ ] Actual branch, exact proposed/deployed commit, target branch/environment and previous known-good release.
- [ ] Plain-language additions/changes and **what is deliberately unchanged**.
- [ ] Files/services/UI assets affected; identify every shared Telegram consumer.
- [ ] Evidence level: source inspected, checks/tests executed, staging verified, production verified or unknown.
- [ ] D1/identity and other relevant gates resolved; named release, workflow and backup/support owners.
- [ ] Explicit merge/deployment authority recorded; inspect automatic deployment hooks before merging.

## 2. Before merge

- [ ] Diff is bounded; pre-existing/unrelated edits and customer data/secrets are not included accidentally.
- [ ] Required structural/dependency/access decisions reviewed; no automatic cross-workflow authority.
- [ ] Changed browser paths remain separate from CSRF-exempt Telegram endpoints; no production `access=None` fallback.
- [ ] Actual owning workflow scope is preserved. In Complaints, do not replace the current group-shared read policy with blanket branch isolation.
- [ ] Focused tests, affected Telegram/browser regressions, static/governance checks and applicable full-CI results recorded; include failures/skips/not-run reasons.
- [ ] Shared assets tested in both channels, including stale cached Telegram clients where affected.
- [ ] UI source ratchet/review respected; no candidate theme migration or baseline update without approval.
- [ ] Configuration variables/defaults, dependency changes, schema migrations and catalogue metadata explicitly listed—or state **none**.
- [ ] Unresolved issues have owners; no focused green run is presented as a green full suite.

## 3. Before deployment or activation

- [ ] Confirm actual deployed state and migration plan, not just local HEAD.
- [ ] Existing production-release/readiness process followed; backup/restore reference and exact migration compatibility/reversal/forward-fix recorded if applicable.
- [ ] New browser channel/cohort/surface/write admission stays closed during deployment unless that exact activation is approved.
- [ ] Current Telegram auth, bot/webhook, launcher, notification and staff-binding defaults remain as reviewed.
- [ ] IdP/cookie/CSRF/session-assurance/revocation settings validated if changed; never list secret values.
- [ ] Current operator can contain the affected surface; backup can execute the procedure; actual rehearsal observations recorded.
- [ ] Worker overlap, long uploads, queues/leases and static-asset compatibility reviewed if affected.
- [ ] Runtime deployment and user/cohort activation treated as separate decisions.

## 4. Things to look out for after merge/deployment

- [ ] Existing authorized Telegram launch, list/detail and relevant write still work; no surprise company-login requirement.
- [ ] Wrong-group/workflow/role and revoked/inactive access is rejected according to existing policy.
- [ ] Browser session/CSRF failures do not cause a silent credential fallback or login loop.
- [ ] Correct actor, revision and audit appear for real approved changes; no duplicate comments, approvals, deposits or publication reservations.
- [ ] An uncertain/timed-out save is reconciled before retrying through another channel.
- [ ] Sheet/Drive publication, pending work and task routing show the expected distinction from canonical save success.
- [ ] No unintended Telegram/email/SMS/Daraja call, double-send, changed escalation or evidence disclosure.
- [ ] Shared UI, downloads, dirty-form protection and old cached WebViews behave as reviewed.
- [ ] Staff-reported errors/delays, safe logs and actual scripted journeys reviewed by a named human; no fabricated percentage thresholds for tiny cohorts.
- [ ] Support owner checks the next agreed business review point and records go/hold/contain/rollback.

## 5. Rollback and closure

- [ ] Browser-only fault: close only the affected browser surface/new admissions where possible; preserve Telegram access and committed state.
- [ ] Shared-code fault: use compatible known-good application or reviewed forward fix; a browser flag alone may not repair Telegram.
- [ ] Preserve audit, signatures, finance claims and valid pending work; no automatic business reversal or duplicate external dispatch.
- [ ] Database restore is disaster recovery with explicit authority, not routine feature rollback.
- [ ] Record actual rollback/containment actions and results, unresolved gates and next owner.

## P0 discovery-only handoff

Expected additions: source endpoint/side-effect manifest, prerequisite register, local check results and this reporting template. Runtime/API/UI/configuration/dependency/schema additions: **none**. Browser access: **not implemented**. Required next input: IdP/MFA, primary driver, first Complaint audience and deployed baseline. No migration, webhook change, staff activation, provider call or deployment is required to review these files.

## P1a dormant foundation handoff

The later user decisions and actual P1a additions supersede the P0-only status,
not its historical evidence. Use the completed scope, verification, activation
blockers and specific monitoring/rollback checklist in
`codebase-analysis-docs/assets/STAFF_BROWSER_MFA_FOUNDATION.md` for this phase.
Dependency and 12 vendor migrations are deployment considerations; browser
admission stays off. No merge/deployment has been performed or authorized.
