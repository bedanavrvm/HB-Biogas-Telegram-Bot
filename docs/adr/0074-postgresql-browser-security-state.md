# ADR 0074: PostgreSQL-only native browser security state

23 October 2026. Accepted by the user's explicit PostgreSQL-only instruction.

## Context

Browser activation previously required Redis/Memcached for pinned allauth's
native rate-limit histories, atomic lock acquisition and used-TOTP cache.
PostgreSQL already owns admission, sessions, durable throttles and TOTP replay
claims. The user chose to avoid an additional paid datastore. Django's stock
DatabaseCache is not an adequate substitute for these concurrency guarantees.

## Decision

Add a staff_auth-owned expiring security-state table and a narrowly routed cache
adapter for the pinned native allauth rate-limit and TOTP-used namespaces.
Use PostgreSQL conditional upserts for atomic add, owner-token lock release and
lease-checked history updates. HMAC keys precede storage; bounded JSON contains
only timestamp histories or opaque lock/use markers. Ordinary workflow cache
keys retain the existing local behaviour. No vendor monkeypatch or package is
required. Keep the existing factor-seed replay claims as defence in depth.

Browser-off configuration retains the existing cache. Browser activation must
select this adapter and PostgreSQL; missing schema/store errors fail closed.
Production browser URLs, approval gates and workflow grants remain unchanged.

## Consequences

Authentication adds small PostgreSQL reads/writes instead of a subscription.
Database outage prevents new browser authentication; this is deliberate and
does not claim infrastructure isolation from the already-shared database.
Live security rows are never culled or globally cleared. Bounded expiry-only
maintenance removes expired rows, never audit history or current replay claims.
Exercise separate worker processes and native HTTP sessions on PostgreSQL.

Rollback: disable browser access first, restore its prior code/configuration,
then `python manage.py migrate staff_auth 0003_staffbrowsersetupgrant` only
after confirming no browser worker uses the new table. This removes temporary
cache state, not accounts, grants, audit history or durable TOTP replay claims.

## Alternatives

Managed Redis is valid but adds cost; it is not commissioned. Process-local
cache, stock DatabaseCache and disabling native limits do not meet this contract.
