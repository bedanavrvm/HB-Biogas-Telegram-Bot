# Telegram Mini App diagnostics

This subsystem combines Sentry Browser errors/traces with a first-party,
privacy-safe lifecycle trail. It can distinguish an intentional close, an
ordinary background/resume cycle, a client error, and a later-confirmed
visible-session gap. `abrupt_unknown_confirmed` is evidence of an unexplained
termination, not proof that Android/iOS killed the WebView.

## Deployment

1. Apply Django migrations.
2. Create a separate Sentry Browser project and set `SENTRY_BROWSER_DSN` in the
   deployment environment. Leave it blank to run first-party diagnostics only.
3. Keep `SENTRY_BROWSER_TRACES_SAMPLE_RATE=0.05` initially. Browser errors use
   100% sampling; Session Replay is not included or enabled.
4. Run `python manage.py prune_miniapp_diagnostics` first to preview retention,
   then schedule `python manage.py prune_miniapp_diagnostics --apply` daily.

The client uses the pinned local Sentry Browser 10.55.0 tracing bundle, so a
Mini App launch does not depend on a runtime Sentry CDN request.

## Data and privacy contract

- Raw sessions and events are retained for 14 days by default.
- Anonymous daily counts are retained for 180 days by default.
- No Telegram ID, customer field, request/response body, query string, URL
  identifier, input/click breadcrumb, attachment, or Replay payload is accepted.
- The actor is the canonical Django user resolved from verified Telegram
  `initData`; an active workflow `AccessGrant` (or the documented Superuser
  technical override) is still required.
- `X-Request-ID` is the existing business request UUID. It is not replaced by a
  diagnostics-only correlation identifier.
- Signal-token retries and client event UUIDs are idempotent.

## Classification and alerts

Visible heartbeat gaps first become `stale_unconfirmed` when a later authorized
launch is seen. A durable recovery marker may then classify the prior session as
`abrupt_unknown_confirmed`; a prior hidden state becomes
`backgrounded_not_resumed` instead. Intentional close and other terminal states
are never overwritten by recovery retries.

In production, a structured warning is emitted only when one
workflow/platform/release segment has a full seven-day baseline and its rolling
one-hour window has at least 20 sessions, at least five confirmed abrupt
sessions, a rate above twice baseline, and an increase above five percentage
points. The warning is rate-limited to once per segment per hour.

## Release validation

Before enabling alert routing, exercise Android and iOS Telegram clients through
background/foreground, phone lock, app switching, intentional close, offline
launch, and process termination. Confirm that WebView `localStorage` survives
relaunch on the supported Telegram/device versions. Observe production in the
read-only Django Admin diagnostics views for at least two weeks before changing
the initial segmented thresholds.
