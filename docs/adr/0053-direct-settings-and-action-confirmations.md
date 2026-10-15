# Direct IT settings and routine action confirmations

## Context

Routine Portal actions ask staff to type audit notes that repeat the action.
TAT IT already has scoped save/review authority but the Mini App still asks for
a proposal and another review. A catalogue mapping warning also appears in the
payment picker even though the saved SysUp product label is usable there.

## Decision

- Routine actions use a named confirmation, retaining server-side actor, time,
  revision, before/after facts and request-key replay protection. Actual data,
  identity evidence, decision comments and uploads remain forms.
- Withdrawing a sent invoice-name request still requires explicit confirmation
  that HB was notified. This attestation replaces a mandatory communication
  reference; it never pretends to send a notification or clears identity holds.
- Authorized TAT IT saves targets/calendar/escalation immediately, through the
  existing validated change and audit records. Historical proposals remain;
  legacy review APIs and non-IT review authority are retained. No access-grant,
  loan approval, payment approval or signing policy is changed.
- Request-key replays are bound to the same setting, group and normalized data.
  Current group configuration is locked for direct saves. Historical case
  targets, permission scopes and completed finance documents remain immutable.
- A saved payment product label does not need a global catalogue binding. Omit
  that internal mapping warning from payment readiness. Explicit requirements
  of an already selected product version still apply.

## Consequences

Existing schemas suffice. Confirmation cancellation is a no-op. Normal code
deployment publishes the behavior; no production data repair, provider call,
permission migration or new dependency is part of this change.

## Alternatives considered

Removing all input forms would lose identity and financial decision evidence.
Removing all approvals would change business and access policy outside this
request. Auto-creating global products from arbitrary labels would invent
catalogue authority and conflate independent workflows.
