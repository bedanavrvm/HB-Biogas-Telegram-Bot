# Operational Documentation

This directory contains the current, short-form documents that govern the
running platform. Historical root-level summaries are context only; code,
migrations, tests, settings, and these operational documents take precedence.

| Document | Purpose |
|---|---|
| [Glossary](glossary.md) | Shared roles, capabilities, workflow language, and UI status semantics. |
| [Loan Origination Admin Guide](origination-admin-guide.md) | Superuser setup of products, fields, main/supporting PDFs, access, publication, testing, and troubleshooting. |
| [Loan Origination Developer Guide](origination-developer-guide.md) | Origination architecture, models, APIs, security, versioning, local development, verification, and safe extension rules. |
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
