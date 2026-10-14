# Consistent signature images and optional identity copies

Accepted - 14 October 2026.

## Context

Device handwriting fonts disagree with the signed PDF. Mandatory guarantor copies
also obstruct testing, while long navigation and recovery panels obscure the work.

## Decision

New typed captures use one local, hash-pinned renderer and one of four vendored
regular handwriting fonts. An authenticated preview returns the exact image hash;
confirmation regenerates and verifies it, retaining its bytes and rendering profile
in existing signature metadata. Full names shrink, never abbreviate or wrap. Only
the existing verified date accompanies the mark. Historical captures and signed
bytes retain their original rendering path.

Borrower and two guarantor identity copies are optional under a captured collection
policy. Editable drafts adopt that policy on a recorded save; submitted applications
do not change. Choosing camera capture requires both sides and creates one private
PDF per person using Portal's validated image collation. Saved identity fields,
not display labels or client-supplied identity, determine the subject. Upload events
retain the subject binding; changed identity makes the old copy informationally
stale, not a submission blocker.

Ordinary unsigned downloads no longer receive a red page overlay (amending ADR
0048). Their copy kind remains explicit in the UI and filename. TEST watermarks,
authorization, revisions, consent, OTP and approval rules remain unchanged.

## Consequences

No new models, migrations, providers or permissions. Shared document publication
never rewrites captured applications. Font licences and hashes accompany assets.
Roll back UI independently; retain the renderer/assets while any version-2 capture
exists. Removing the new renderer would make those captures unreadable.

## Alternatives considered

Browser fonts cannot guarantee matching printed marks. Replacing historical
captures would alter evidence. Making unrelated evidence or signer obligations
optional would expand the approved scope.
