# Workflow-owned recovery controls

## Context

Warnings currently route staff to Settings without a repair, and Portal's bell
discards actions that Home already provides. Shared integration records must
not become a cross-Mini-App task inbox.

## Decision

Each Mini App exposes a paged, current-access-filtered App status projection.
A shared presentation component executes only actions supplied by that owning
app. Existing retry services remain authoritative: recovery never resubmits a
business decision, payment, complaint, signature or original application.

The user approved scoped TAT IT retries for Sheet publications, including
remarks. A deployment-provisioned `tat.publication.retry` capability applies
only to Sheet work; signature and notification dispatch authority is unchanged.
Retry confirmation supplies a recorded reason without a new free-text note.
Current complete grant tuples, source revision, data mode and leases still apply.

## Consequences

No persistent error model, universal operation executor or bulk retry is added.
Queued work is reported as waiting, not synchronized. Configuration errors and
uncertain deliveries lead to review rather than blind retries. Existing failure
evidence survives successful recovery.

## Alternatives considered

A global retry queue would mix authority and business effects. Settings-only
controls retain the original dead end for staff acting from a warning.

## Rollback

Roll back application code and run `python manage.py migrate core
0204_tat_bm_analysis_capability` to reverse the new policy provisioning. Its
reverse removes only the untouched migration-owned default and increments the
policy version; later administrator policy edits and audit evidence survive.
Production deployment/migration requires separate approval.
