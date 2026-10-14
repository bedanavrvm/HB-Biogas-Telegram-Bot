# TAT remarks and Telegram Web delivery

## Context

Remarks currently replace a shared text field through the stage-update path.
That path changes the workflow revision and update time, routes tasks, and
reserves signing/notification work. A remark is not a stage transition. Some
historical completed cases use their update time as their terminal clock.
Telegram Web also embeds Mini Apps, while the global frame policy forbids it.

## Decision

Authorize remarks against current TAT case-view access, including finished
cases. Deleted, unresolved and closed-Pilot cases stay read-only. Each remark
has a required request key, immutable native/compliance event, saved actor,
applicable TAT roles and server time. Preserve legacy text without inventing
attribution. Append new comments with an actor/time footer and a separator.
Update only the remarks projection: never workflow revision, update time,
completion, stage facts, tasks or signatures.

Reserve event-keyed IntegrationOperations for named-column Sheet publication.
The existing TAT processor drains them. Canonical saves do not call Google.
Publication reads current notes under the case lock; ordinary stage publishers
use the same lock for the remarks cell, preventing stale note overwrites.

Only explicitly reviewed Mini App HTML controllers may be embedded by self or
https://web.telegram.org, using CSP frame-ancestors. Admin, unrelated HTML and
API responses keep the global frame protection. Embedding never authenticates
or authorizes a user. Native workbook responses expose a named attachment and
Telegram Web's explicit CORS origin on GET and HEAD; current scope is rechecked.

## Consequences

Comment retries cannot create duplicate notes or reopen a case. Provider/schema
failure leaves the comment saved and a durable retry/repair record. Staff see
remarks in Activity, not a second history. Historical audit and timing stay intact.
The event role column grows from 80 to 255 characters; no data backfill is needed.
Rollback: first ensure no saved actor_role exceeds 80 characters, then run
`python manage.py migrate core 0202_jawabufarmermaster_requisition_batch_and_more`.
Restore the previous release only after reviewing appended remarks compatibility.
No production migration or provider mutation is part of this implementation.

## Alternatives considered

Warnings around the existing stage-update path cannot protect timing or retries.
A new comment model/worker would duplicate the existing event and queue domains.
Globally removing X-Frame-Options would unnecessarily expose Admin and other pages.
