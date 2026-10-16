# ADR 0055: Source-bound Mini App design review

## Context

Portal, TAT Tracker, Complaints and Origination share some UI assets but do not
have one evidence-backed record of approved presentation and interaction choices.
A screenshot or a green browser test is not human design approval. Operational
roles, data and business decisions must remain independent.

## Decision

Add the disabled-by-default, active-Superuser-only Design Lab in the same Django
project. `ui_review` owns immutable review revisions, append-only decisions and
immutable standard releases. The first board shows current source-based variants
and unapproved foundation proposals. No design is pre-approved.

Full-shell synthetic scenes use actual templates, CSS order and JavaScript with
an isolated I/O adapter. Uncovered journeys and font substitutions are visible
coverage gaps, not invented equivalents. Specimens cannot access operational
APIs, authentication data, camera, microphone or notifications. Native diagnostics
run only on an explicit reviewer gesture in the host.

Approvals bind exact source, fixture and evidence fingerprints. A source change
makes an old approval historical, never silently current. Adopting with changes
records a request; a later concrete revision still needs approval. Browser and
native device evidence are distinguished. Saved evidence uses existing private
Drive storage; local audit captures remain ignored. Only reviewed synthetic
visual baselines may enter the existing hash-governed artifact allowlist.

Candidate foundations and Telegram/JBL theme selection are lab-scoped. No
operational Mini App loads them before a separately approved migration. The
default candidate theme is Telegram/Automatic. Preferences contain theme IDs,
not identity or form data. Human review remains necessary before a standard can
be released. Phase 6 starts only after explicit user approval.

## Consequences

- The lab's code is deployable independently of design choices and app migration.
- Three bounded records retain decisions and source/evidence provenance; QA
  remains responsible for functional test executions.
- Existing workflow permissions, business APIs, data and appearance are unchanged.
- Normal Django migrations apply. Export review/release manifests and back up
  the database before reversing with `python manage.py migrate ui_review zero`;
  reversal removes lab records only and does not delete private Drive files.
- No new framework, bot, storage provider or third-party dependency is introduced.

## Alternatives considered

- A new bot/codebase: rejected because it creates another source of UI drift.
- A text decision log only: rejected because it cannot demonstrate alternatives.
- Reusing QA Pass/Fail as design approval: rejected because the decisions have
  different meaning, authority and revision requirements.
- Immediately changing shared CSS: rejected because it would migrate apps before
  the reviewer has selected a standard.
