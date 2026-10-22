# Automatic document updates until the first confirmed signature

Accepted - 22 October 2026. Supersedes the new-applications-only update boundary
in ADRs 0047 and 0057, not their field projection or Main LAF replacement rules.

Unsigned applications automatically adopt newly published versions of their
selected document families when the assigned officer opens/resumes them; the
server checks again before submission or preparation for signing. There is no
refresh button, confirmation step, publication fan-out or provider call. Reads
remain read-only: the client invokes the scoped, authenticated POST boundary.

The first confirmed signature on any document locks the entire application's
document versions. Confirmation means a saved signature action or verified
signer/session/completed signed bundle, including retained or invalidated past
signature evidence. A typed/drawn preview or unverified OTP attempt is not a
signature. Test-confirmed signatures obey the same editing boundary. Closed
cancelled, declined and expired applications are not resurrected; completion
without signatures does not itself lock document updates.

## Preserved and invalidated

Update the same document families only, never switch Main LAF family or product.
Retain application identity, product version, commercial terms/quote, uploads,
compatible canonical answers and document-local answers. Changed types, subjects,
sources, ownership or repeating-column meanings must not reinterpret old input;
the superseded schema/answers remain in the existing private application history.
New/changed inputs become visible through normal placed-field projection and
normal submission validation, rather than blocking adoption. Keep the captured
completion/approval policy and reconcile document-owned signing obligations and
compatible staff assignments without granting authority.

One atomic application revision replaces the selected snapshots, cancels unsigned
signing packages and bearer links, invalidates OTP challenges, clears current
review/preview/completion markers, and returns the application to editing.
Historical package bytes/reviews remain unchanged. Revision-bound download links
become stale. Existing review notices are superseded; reviewers receive a local
in-app notice, not an SMS/email. Re-submission requires the updated preview and
current rules. An update found on submission returns the updated form rather than
silently submitting a document the officer has not seen.

## Failure and concurrency

Only active assigned officers with the existing Origination capability/scope may
invoke adoption. Application-row locking serializes adoption with signature
confirmation; immutable signature evidence wins once committed. A deterministic
revision/plan request key prevents duplicate adoption; stale writes are rejected.
Missing, ambiguous, ineligible or incompatible successors preserve saved work and
produce an actionable warning. They do not silently downgrade documents or sign
an outdated bundle. Existing legacy records without a governed catalogue are not
inferred into it.

Opening/resuming checks respect dirty forms, recovery drafts, dialogs and previews.
Cross-device changes still use normal revision conflicts, not silent overwrites.
This is lazy adoption, not a background sweep of dormant applications. Switching
to a different Main LAF still uses the explicit blank-replacement flow in ADR 0057.
