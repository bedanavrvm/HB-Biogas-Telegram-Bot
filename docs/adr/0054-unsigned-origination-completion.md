# Document-owned unsigned completion

Accepted - 15 October 2026.

The user explicitly chose completion without e-signing for signature-free Main
LAFs. New catalogue applications capture this policy and finish as `completed`
when no selected document requires signatures. Completion is not loan approval;
`approved` continues to mean the existing signed approval outcome. Historical
applications and signed bytes retain their original policy.

The selected documents own signer obligations. Product mirrors may supply
identity mappings for those roles, but cannot reintroduce omitted document
signers. Required signatures on a selected supporting document retain the
signing flow. Changing document selection before submission recomputes this
decision against captured document contracts, not current product settings.

Completion reuses officer ownership, revision, full preview, typed required-field,
commercial-term and evidence validation, then locks the application. It records
completion without creating signing packages, approvals, sessions or provider
requests. Copies remain unsigned and available combined or individually.

Migration 0008 adds the status choice only; there is no backfill. Rollback must
account for newly completed applications rather than relabelling them approved.

The alternatives were draft/download-only, which the user rejected, and treating
zero signatures as automatic loan approval, which would misrepresent consent.
