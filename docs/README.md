# Operational Documentation

This directory contains the current, short-form documents that govern the
running platform. Historical root-level summaries are context only; code,
migrations, tests, settings, and these operational documents take precedence.

| Document | Purpose |
|---|---|
| [Glossary](glossary.md) | Shared roles, capabilities, workflow language, and UI status semantics. |
| [Loan Origination Admin Guide](origination-admin-guide.md) | Superuser setup of products, fields, main/supporting PDFs, access, publication, testing, and troubleshooting. |
| [Loan Origination Developer Guide](origination-developer-guide.md) | Origination architecture, models, APIs, security, versioning, local development, verification, and safe extension rules. |
| [SPIN and TAT Pilot Modes](spin-tat-pilot-modes.md) | Superuser mode switches, protected Pilot cycles, Mini App behavior, verified Sheet cleanup, recovery, and developer scoping rules. |
| [TAT Staff Guide](tat-staff-guide.md) | Day-one queue, case, conflict, connectivity, and alert instructions for TAT users. |
| [TAT Access and Responsibilities](tat-access-and-responsibilities.md) | Canonical administrator guide for AccessGrant authorization and separate responsibility routing. |
| [Staff Lifecycle Workspace](staff-lifecycle-workspace.md) | Guided onboarding, access, transfer, leave, return, offboarding, checker bootstrap, and Telegram activation manual. |
| [TAT Private Tasks](tat-private-tasks.md) | Private inbox, deep-link, delivery, retry, backup, and privacy behavior. |
| [TAT Developer Guide](tat-developer-guide.md) | Current service boundaries, authority model, write contracts, and safe extension rules. |
| [TAT Production Runbook](tat-production-runbook.md) | TAT scheduler, readiness, staging acceptance, monitoring, recovery, and rollback. |
| [TAT Logic](../TAT_TRACKER_TAT_LOGIC.md) | Canonical stage calculation, target, status, and display rules. |
| [ADR 0001](adr/0001-server-owned-miniapp-recovery-drafts.md) | Decision and release safety record for server-owned Mini App recovery drafts. |
| [ADR 0007](adr/0007-sheet-register-governance-and-verified-tat-repair.md) | Publication-only Sheet contracts, drift evidence, and verified TAT duplicate-row repair. |
| [../CHANGELOG.md](../CHANGELOG.md) | Dated visible/operational changes. |
| [../KNOWN_GAPS.md](../KNOWN_GAPS.md) | Diagnosed limitations, workarounds, and release verification still required. |
| [../PRODUCTION_RUNBOOK.md](../PRODUCTION_RUNBOOK.md) | Release, rollback, recovery, credentials, backups, and emergency access. |
| [production-release-record.md](production-release-record.md) | Private evidence template for a controlled production deployment. |

## ADR convention

Use `NNNN-short-title.md`. Write the ADR before implementing a structural or
costly-to-reverse decision. Include Context, Decision, Consequences, and
Alternatives considered. If an ADR introduces a migration, dependency, or
external side effect, include the required approval gate and rollback plan.
