# HB pre-visit deposits

## Context

FarmUp can legitimately deliver an intake with no HB deposit or less than KES
5,000. JBL must not visit until the cumulative recorded HB deposit reaches that
amount. Existing HomeBiogasAction records require an accepted signed order and
cannot represent this earlier work.

## Decision

Add a separate Deposits workstream to the existing HB Actions shell. Django's
JawabuFarmerMaster deposit is authoritative; HB records cumulative totals using
Decimal, revision checks, request keys, field provenance and pipeline/compliance
events. Keep operational legacy receipt aliases consistent without rewriting
uploaded source evidence. HB can correct decreases with a reason. The editor
locks once the current visit cycle has a recorded JBL visit. Later invoice and
payment processing retain their own authority.

Blank/underpaid deposits are a financial hold, not an invalid intake. Show held
cases in the JBL queue without allowing visit activation. Enforce the gate
before evidence publication and again under the final transition lock. Already
successful retries remain successful. Office intake may be saved on hold without
recording a visit or retaining visit uploads. A subsequent FarmUp import cannot
overwrite an HB-owned total; retain its differing observation in Activity.

Portal HB staff edit, Operations Administrators view, scoped IT has its existing
technical override, and active Django Superusers retain break-glass access.
Other Mini App grants confer no authority. Deploy these approved defaults in a
checked-in capability migration and advance the access-policy version.

## Consequences

No new persistent model, payment provider, receipt ledger, Sheet column, TAT
stage or recognition milestone is introduced. Deposit edits reserve the existing
durable publication operation. Legacy deposit-only review flags require an
explicit dry-run-first audited reconciliation, never mutation on a GET.
Production deployment/data reconciliation require separate authorization.

## Alternatives considered

Filtering underpaid cases out hides operational backlog. Client-only disabling
allows direct submission bypasses. Creating installation records early violates
signed-order finality. Letting imports overwrite staff corrections loses money
history. An individual payment ledger exceeds this cumulative-total workflow.
