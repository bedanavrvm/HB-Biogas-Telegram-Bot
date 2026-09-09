# Telegram Notification Policy

Telegram provides quick awareness and navigation. The relevant Mini App holds
the fields, validation detail, and action controls. Django and immutable audit
events hold the complete operational evidence.

## Message types

- **Informational:** one short statement describing what happened.
- **Action required:** say what is waiting, provide a staff-facing reference
  when useful, state the next step, and provide the relevant Mini App button.
- **Success:** confirm the completed action and its workflow outcome. Do not
  repeat submitted fields.
- **Error:** explain what the user should check using human field labels. Keep
  raw validators, exception text, and implementation details inside the Mini
  App or Admin audit boundary.

## Allowed content

Use only the minimum needed identity, context, action, and navigation. Prefer a
customer name, staff-facing reference, workflow stage, and branch when they are
needed to distinguish the task.

Do not include internal database identifiers, raw backend validation text,
file counts, changed-field dumps, request metadata, or unnecessary customer
PII such as National ID and phone number. A technical identifier may remain in
an Admin-only alert only when it is the sole route to the audited record.

Before adding a line, ask: if it is removed, can the recipient still understand
what happened and know what to do? If yes, remove it from Telegram.
