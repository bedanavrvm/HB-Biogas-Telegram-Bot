# Shared Document Signing

This component owns signature appearance validation, PDF ink and the in-app signing dialog.
It grants no workflow access and does not create loan applications.

Origination retains its application/package records, signer obligations, links,
OTP sessions and approvals. Its compatibility imports use the shared rendering code;
historical links and signed bytes are unchanged.
Both Mini Apps load the shared typed-signature control. Portal additionally uses
the shared in-app signing dialog with owner-authorized document page callbacks.

`portal_lafs` owns the Portal case link, draft/version records, consent evidence
and stage checks. A client/guarantor reviews and signs on the officer's device,
consents, and the authenticated officer confirms witnessing the signature.
This uses the normal authorized Portal API, without SMS or bearer links.
There is no Portal remote invitation,
shareable signing link or remote-signing control in this release.

Never replace either owning app's capability checks with a shared signing role.
Keep all signature rendering against captured document bytes and placements.
