# Telegram Mini App Authentication

`core.services.telegram_identity.validate_telegram_init_data` is the only
implementation of Telegram `initData` verification. It requires a valid HMAC,
`hash`, bounded positive `auth_date` age, no future timestamp, a JSON object in
`user`, and a Telegram user ID. `core.services.telegram_auth` is a temporary
compatibility adapter that delegates to it and preserves the older
`(valid, error, payload)` response shape.

Authentication only establishes Telegram identity. Each workflow must resolve
the canonical active Django user and independently authorize that user through
the applicable `AccessGrant`, group, branch, role, and capability rules.

Unsigned Mini App requests are accepted only when the workflow auth flag is
explicitly disabled and Django is running in `DEBUG` or its test runner. Local
Complaint Cases requests in that mode additionally require an authenticated,
active Django test user; anonymous fallback identities are not supported.

For production, all five `*_WEBAPP_REQUIRE_TELEGRAM_AUTH` flags must be true and
all shared/workflow authentication ages must be between 1 and 86400 seconds.
Both Django deployment checks and `check_production_readiness --strict` enforce
the static contract. The release readiness command also checks conditional
approval's active, approved, integrity-valid consent policy against the
database. `release.sh` runs this command before migrations or application
startup work.
