# Signed invoice-name agreement permits payment

Accepted by the user on 6 October 2026: a signed/agreed version of the governed
name-change letter clears the identity hold; the corrected invoice remains an
outstanding follow-up, not a payment blocker. Merely recording that a letter was
sent does not clear the hold. Order eligibility, financial readiness, current
Head of Rural review and payment finality remain independent requirements.

Retain immutable accepted scan bytes in the bounded payments domain, tied to
the sent artifact and exact case/household identity facts. Changed identity,
revoked relationship or superseded correction cannot reuse old consent. No
legacy request is automatically cleared, and no applicant identity is rewritten.
Invoice delivery is source provenance, not a restriction on later batch members.

Rollback: stop accepting agreements, restore the preceding application version,
and run `python manage.py migrate payments 0006_bind_payment_numbers` only after
exporting accepted agreements: reversal removes their local evidence table.
No production migration or payment execution is authorized by this code change.
