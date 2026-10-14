# Named Sheet columns and BM analysis approval

## Context

Staff can insert or move Google Sheet columns. Numeric field positions and
first/last-match header lookups can then read, overwrite or delete unrelated
data. TAT also needs a distinct BM decision immediately after M-PESA submission;
the draft credit-assessment workflow is not its implementation prerequisite.

## Decision

All live Google Sheet fields resolve through unique named headers. Normalize
Unicode, case and whitespace, retain explicit workflow aliases, and reject
duplicate or ambiguous names before reads or mutations. Required missing names
fail safely; numerical positions are transport coordinates derived from current
validated headers, never fallback authority. Column order is presentation only.
Use one shared resolver and validate header freshness before writes. Preserve
human/formula/unknown cells and keep canonical commits independent of providers.

New TAT configurations include `bm_analysis_approval` (BM, Approved/Declined)
between M-PESA submission and Admin verification, with an automatic timestamp.
Approval advances; decline terminates. No new signing/evidence gate is introduced.
Targets are explicitly configured; missing targets are not scored. Existing case
snapshots and final standings retain their original paths. Publish audited
successors rather than rewriting published products or operational records.

## Consequences

Missing, duplicate or ambiguous legacy headers require explicit operator repair.
Read-only audits disclose names and coordinates, never customer cells. Apps Script
deployment and three new TAT headers are operator tasks. Historic numeric layout
metadata remains evidence but is not runtime addressing authority. Google Sheets
has no atomic schema compare-and-write: stop manual structural editing during
maintenance and minimize the check/write interval. This change makes no external
writes or automatic production configuration publication.

## Alternatives considered

Updating fixed offsets or keeping positional fallbacks leaves old and new rows
unsafe after another edit. A separate BM credit-assessment workflow adds unrelated
gates. Globally rewriting existing case paths would change history and rankings.

## Rollback

No schema reversal is required for the shared resolver. Restore code only after
pausing publication; never restore positional writes against moved columns.
Retire/revise future TAT configuration through the existing publication services;
do not remove the BM stage from cases that already captured it.
