# Application signing plans

## Context

Origination currently identifies signers by role and has several captured approval
policies. Role identity cannot distinguish two borrowers or two staff members with
the same role. Exposing preparation and approval implementation steps also makes
the officer journey unnecessarily long.

## Decision

An explicitly published new product version may select `all_required` completion.
Active Superusers configure document-compatible defaults and application overrides
in Django Admin. Individuals have stable participant IDs; roles authorize actions
but are not participant identities. All required participants may sign in parallel.
The final required signature/stamp approves the exact package transactionally.
Submission prepares the local package; the officer deliberately dispatches links.

Submitted plans and consent are frozen. Withdrawal cancels sessions/signatures and
retains evidence; a successor draft plan is editable. Existing applications and
legacy signer links are never backfilled or reinterpreted. Product owns defaults;
Document editor owns PDF capacity and placements. No grant changes or cron jobs.

## Consequences

New consent must explicitly cover `all_required`; empty legacy approval roles are
not sufficient. Participant identity participates in session and action binding.
Approval does not depend on a particular role signing last. Template-required
signers/placements cannot be removed by an application override. Configuration
does not grant staff access. Existing background archival remains independent.

## Alternatives considered

Keeping BM-last does not meet the selected policy. Numeric signature thresholds
without named participants confuse repeat placements with distinct signers.
A general-purpose workflow builder adds sequencing and quorum complexity that is
not required. Existing policies continue through their original implementation.

## Release and rollback

Do not activate a real product or consent policy automatically. Review migration
0007 before applying it; all old rows default to `legacy` and remain unchanged.
Schema reversal: `python manage.py migrate origination 0006_originationdatafield_value_contract`.
Reverse only before new-policy records exist, or after a verified backup and
explicit operator decision: schema rollback cannot preserve new signing evidence.
