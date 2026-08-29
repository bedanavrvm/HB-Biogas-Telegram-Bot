# ADR 0030: Telegram staff onboarding handoff

## Context

Direct Superuser onboarding activated the Django account and AccessGrants but
left Telegram activation, group membership, launchers, and the welcome message
as unrelated manual tasks. Telegram bots cannot silently add a person to a
group, and a workflow-wide AccessGrant does not prove that the person should
join every compatible operational group.

## Decision

- The Superuser explicitly selects intended Telegram groups during onboarding.
- Selected groups are fingerprinted with the lifecycle request and validated
  against the final AccessGrants before the account is created.
- A single-use activation pack binds signed Telegram identity to the enrolled
  username. Activation then starts durable, retry-safe delivery.
- Each selected group keeps one shared pinned JBL Apps launcher. The bot creates
  a one-member, 24-hour invitation; the person must accept it.
- The user receives one private welcome containing only launchers compatible
  with current authorization plus the selected group invitations.
- A governed join is recorded quietly. The existing public welcome remains a
  fallback for unknown or manually added members.
- External failure never rolls back identity, account, or grants. Admin exposes
  status and an explicit retry that advances the delivery revision.
- Usable invite URLs are temporary. Permanent evidence retains only a digest,
  expiry, operation reference, status, and audit event.

## Consequences

Authorization and Telegram membership remain separate and explainable. Staff
receive a complete handoff without per-user pinned messages, while Superusers
can see and recover partial delivery. The bot must have invite and pin rights in
selected groups.

## Rollback

Disable post-activation delivery while retaining the onboarding and invitation
records for audit. Existing accounts, AccessGrants, identity bindings, and
shared launchers remain valid; group invitations can be revoked in Telegram.

## Operator guide

See [Telegram Staff Activation Mini App Setup](../telegram-staff-activation-setup.md)
for the BotFather registration, Render configuration, end-to-end onboarding
flow, production prerequisites, verification checklist, and recovery guidance.
