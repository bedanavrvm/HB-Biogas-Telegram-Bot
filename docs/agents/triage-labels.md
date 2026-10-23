# Triage labels

The five canonical roles map directly to the labels in this repository's
GitHub issue tracker.

| Canonical role | GitHub label | Meaning |
| --- | --- | --- |
| `needs-triage` | `needs-triage` | Maintainer needs to evaluate the issue. |
| `needs-info` | `needs-info` | Waiting for information from the reporter. |
| `ready-for-agent` | `ready-for-agent` | Fully specified and ready for agent implementation. |
| `ready-for-human` | `ready-for-human` | Requires human implementation. |
| `wontfix` | `wontfix` | Will not be actioned. |

Use these strings whenever a skill refers to one of the canonical roles.
Labels describe issue readiness; they do not grant application permissions,
authorize external side effects, or bypass review and deployment gates.

Before creating a label, check the existing labels in the
[configured tracker](issue-tracker.md). Create missing names only; preserve
existing labels, colours, and descriptions. Change this mapping explicitly if
the repository later adopts another vocabulary.
