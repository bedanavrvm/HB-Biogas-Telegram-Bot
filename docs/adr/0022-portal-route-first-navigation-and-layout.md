# ADR 0022: Portal Route-First Navigation and Grouped Layout

**Status:** Accepted for merge and local/staging validation. Production release
requires the normal named release approval; no schema migration is involved.

## Context

The Portal accumulated a flat list of sixteen capability-gated destinations,
an all-screens-in-one-fragment template, and historical client-side page
toggling alongside the newer htmx route shell. This made mobile navigation
crowded and allowed a restored local screen to disagree with an explicit URL.
It also made it too easy for a future feature to add a third navigation path.

Telegram Android, browser history, and the Portal already use Django templates,
htmx, vanilla JavaScript, and Alpine.js. The settled frontend decision remains
Alpine.js for local interactivity; this does not justify a React/Vue migration.

## Decision

1. A Portal route is the top-level navigation authority:
   `/portal/s/<screen>/` for a screen and `/portal/cases/<case-id>/` for a
   case-history drill-down. An explicit URL always wins over retained local UI
   state. Landing preferences may redirect only a cold `/portal/` opening.
2. Existing htmx navigation and `miniapp-nav.js` own browser history and the
   Telegram BackButton. Dynamic Portal controls use one `navigateTo()` helper
   instead of calling `switchPage()` or `history.pushState()` directly.
3. The sidebar is grouped as Overview, My work, Finance & documents, Cases,
   IT tools, and Account. Grouping is display-only and never changes the
   capability that guards a screen.
4. The mobile bottom bar exposes at most four permitted destinations selected
   from the user's scoped Portal role. The sidebar remains the complete
   capability-filtered navigation surface.
5. Portal CSS gains semantic success/warning/danger aliases, a named stacking
   scale, shared labelled-value tile primitives, and complete reduced-motion
   coverage. Branded document print styles remain intentionally fixed to paper
   colours and are outside runtime theme replacement.
6. A cold Portal load renders one persistent shell: offline feedback, shared
   filters, workflow overlays, toast, and the selected screen root. Route
   navigation replaces only `#portal-screen` with its single authorized page.
   Screen-local handlers must be delegated or explicitly re-initializable;
   persistent overlays retain their existing one-time bindings.

## Consequences

- Staff get a compact role-aware bottom bar and a readable grouped sidebar
  without losing any authorized screen or deep-link behaviour.
- Dynamic page changes no longer leave the browser URL at the old screen.
- A route change no longer ships or toggles every Portal page. This reduces
  DOM size, avoids duplicate element IDs, and makes each screen's lifecycle
  explicit without changing a workflow API or data record.
- Navigation grouping and bottom-bar order are presentation rules. They do not
  grant access and must remain covered by server-side capability checks.

## Alternatives considered

- **React/Vue migration:** rejected. The established Django/htmx/Alpine stack
  already supports the required UI; a framework replacement would add release
  risk without fixing competing navigation ownership.
- **Keep all twelve-plus destinations in the bottom bar:** rejected because it
  produces illegible labels and unreliable touch targets on field devices.
- **Retain all screens inside a hidden sibling container:** rejected because
  it leaves mobile memory/DOM pressure, duplicate IDs, and stale handler risk
  in place even when the route-first navigation is working.

## Migration and rollback

No schema migration is included.

To undo, redeploy the prior application commit. This changes only Portal
presentation and client navigation; it does not delete or rewrite customer,
workflow, document, audit, Drive, or Sheets data.
