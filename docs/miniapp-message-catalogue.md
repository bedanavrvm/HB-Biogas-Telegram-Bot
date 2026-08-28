# Mini App message catalogue

## Purpose

`core.services.miniapp_messages` is the deployment-controlled source for
operational Mini App error copy.  A browser receives a stable code, a reviewed
plain-language message, and a correlation reference.  Internal exception text,
stack traces, request payloads, OTPs, signing tokens, signatures, and customer
data must never be returned or logged by this boundary.

Messages should state what happened and what the person can do next.  Do not
use Python exception names, HTTP terminology, internal workflow statuses, or
implementation roles such as `Superuser` in public copy.  New or changed copy
requires review by the product/operations owner responsible for the affected
workflow.  Because the catalogue is version controlled, urgent corrections use
the normal reviewed hotfix and deployment process; production Admin edits are
intentionally unsupported.

An endpoint may retain its existing explicit `message` for an expected 4xx
business or validation result; that text is therefore part of the reviewed
user-facing contract.  Uncoded exception text placed only in a legacy `error`
field is not trusted and is replaced with a catalogue fallback.  All 5xx text
is replaced regardless of its original response body.

## Response contract

Updated clients send `X-MiniApp-Message-Contract: 2`.  Error responses contain
`ok`, `success`, `code`, `message`, and `request_id`.  Only explicitly
allowlisted display details may be included.  Cached clients without the header
also receive `error` as a mirror of the safe `message`; the server logs
`legacy_error_mirror=true` whenever it emits that compatibility field.

Remove the server-side `error` mirror only after production has recorded zero
legacy-mirror emissions for 30 consecutive days, covering at least one normal
release cycle.  The frontend may keep a local `data.error = data.message` alias
until individual screens have migrated, because that alias does not cross the
network boundary.

Public unauthenticated flows use coarse retry guidance such as "about a minute"
or "try again later".  Exact throttle counters remain private.  Correlation IDs
are safe to display, but logs must join them only to allowlisted workflow and
record identifiers rather than raw applicant or signer details.

## Consent wording is separate

Origination consent, conditional-finality, and completion wording is not part
of this operational catalogue.  It remains in immutable
`OriginationConsentPolicyVersion` records and the exact policy snapshot inside
the frozen signed packet.  Consent text follows the same principles of stable
versioning and auditability, but every change requires the separate compliance
or legal approval and publication process.  Do not move consent wording into
the operational catalogue to make it easier to edit.

## Adding a message

1. Add a unique snake-case code and plain-language default to
   `MESSAGE_CATALOG`.
2. Pass only allowlisted, non-identifying formatting details.
3. Add client-specific handling only when the screen needs behaviour beyond
   displaying the message; keep `CLIENT_HANDLED_CODES` and
   `MiniAppUtils.handledMessageCodes` aligned.
4. Test the user response, legacy compatibility response, correlation log, and
   PII/technical-detail exclusion.
5. Obtain product/operations copy review, plus compliance review if the change
   affects legal consent rather than an operational message.
