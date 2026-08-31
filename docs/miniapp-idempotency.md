# Mini App idempotency contract

Every unsafe Mini App request (`POST`, `PUT`, `PATCH`, or `DELETE`) has two
independent replay boundaries:

1. The HTTP boundary requires one canonical request key. Current clients send
   the same value in `Idempotency-Key`, `X-Request-ID`, and, when the body
   format supports it, `client_request_id`.
2. The owning workflow retains its database uniqueness, state/revision,
   content-hash, duplicate-media, and durable external-operation checks.

The transport key supplements domain constraints; it never replaces them.
The server rejects mismatched transport headers and gives header values
precedence over a stale body value. It does not invent a fallback write key.
Random response references remain correlation identifiers only.

## Route inventory and CI

`core/miniapp_write_inventory.py` is the executable review register. Every
Mini App write route records its methods, authentication guard, capability,
scope, request-key boundary, and domain replay mechanism. Explicitly public
webhooks, signer endpoints, and token-protected operator APIs are listed in the
separate non-Mini-App exclusion register.

Run:

```bash
python scripts/check_miniapp_write_inventory.py
node scripts/test_miniapp_idempotency_clients.js
```

CI fails for an uncovered or stale unsafe-method route, a blank policy field,
or a Mini App route without a statically visible request-key boundary. The
client test exercises JSON, multipart, XHR headers, stable retry keys, and
single-flight double-click protection.

## Client behavior

- Create a key when a user begins a genuinely new action.
- Keep it in the action payload or form object while the request is in flight.
- Coalesce a second click with the existing in-flight promise.
- Retain the key after a network timeout, connection failure, or 5xx response,
  because the server may already have committed the action.
- Clear it after a definitive response; a later deliberate action receives a
  new key.
- Never use `sendBeacon` for these writes because it cannot set the required
  headers.

Order Approval additionally stores a group-scoped unique request reservation,
a fingerprint of immutable form and file content, and the response snapshot.
An exact replay performs no second Sheet, media, or Telegram operation. Reuse
of the same key with changed content returns HTTP 409.

## Production enforcement and diagnostics

Production configuration must set:

```text
REQUIRE_MINIAPP_IDEMPOTENCY_KEY=True
MINIAPP_IDEMPOTENCY_OBSERVATION_DAYS=14
```

Production readiness reports an error when strict mode is disabled or the
observation window is outside 1–90 days. Missing-key attempts increment only a
daily route/method/outcome counter. The aggregate contains no request body,
path parameters, actor, Telegram identity, or customer data. Any accepted or
rejected legacy write in the configured lookback produces a readiness warning
for investigation.

Local development and tests may leave strict mode disabled explicitly. That
does not create a production bypass because `DEBUG=False` deployment checks
reject the same setting.
