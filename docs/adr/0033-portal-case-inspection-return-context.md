# ADR 0033: Queue-specific case inspection and return context

## Context

Portal operational queues perform different jobs. Visit, credit and decision
cards must open their action forms; Order Preparation card clicks inspect a
case while checkboxes select the batch. Full document navigation loses local
selections, search and unfinished forms. Restoring customer search or forms
through URLs or a durable navigation cache would expose unnecessary data.

## Decision

Keep full GET navigation for top-level screens. For a case-history inspection
only, fetch the authorized Django history fragment with a bounded timeout,
validate its root, and retain one originating screen and open form in memory.
The canonical case URL and browser Back/Forward still describe the detour.
Visible and Telegram Back use that same browser entry. Reload/cold links use
the existing server-rendered history route with an allowlisted return screen.
No customer search, form values, files or history HTML enter navigation storage.
Only selected case IDs, captured revisions and the preparation date may be
recovered from sessionStorage for 30 minutes, keyed by a SHA-256 digest of the
signed Telegram launch and invalidated by access-policy version changes.
Retained case IDs/revisions are not authorization: APIs recheck scope, state
and revision. Rendering never silently advances a selected case's revision.

Deferred review displays canonical deferral information and only offers the
existing stage action when the actor has its capability and reappraisal is
not required. No new transition or permission is introduced.

## Consequences

Order selection, target date, filters, search, scroll and open form fields
survive an in-session inspection. The detour has failure feedback and leaves
the original screen intact on timeout or denial. Lost/reloaded sessions do
not promise recovery of in-memory context. Top-level navigation is unchanged.
No migrations, external writes, new dependency or capability changes.

## Alternatives considered

- Reintroduce HTMX navigation for every screen: rejected; it reopens a recent
  Telegram WebView reliability fix outside this bounded change.
- Persist all UI context in sessionStorage/history state: rejected; customer
  search, customer records and local attachments do not belong in that cache.
- Route every operational card through history: rejected; it adds a detour to
  the user's actual task and breaks batch selection semantics.

## Rollback

Redeploy the preceding application commit. No database reversal is required.
