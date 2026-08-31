# URL and configuration contract

## Canonical surfaces

All JSON, upload, mutation, provider callback, and webhook endpoints use the
`/api/` prefix. Intentional root routes are limited to:

- `/health/` for a public liveness response;
- `/staff/activate/`, `/origination/`, `/order-approval/`,
  `/jawabu-farmers/review/`, `/fca/review/`, `/spin/`, `/tat-tracker/`,
  `/complaints/`, and `/portal/...` browser/Mini App entry points;
- `/s/` and `/origination/sign/` public signer shells;
- Django Admin and the separately controlled `/ops/health/` integration.

`config/urls.py` does not include `core.api.urls` at the root. New API routes
therefore have exactly one URL unless a compatibility route is deliberately
reviewed and added.

## Compatibility inventory

| Legacy surface | Canonical surface | Behaviour | Retirement evidence |
|---|---|---|---|
| `/api/<Mini App browser route>` | root browser route | permanent GET/HEAD redirect | `core.legacy_routes` warning count |
| root activation/login POST | `/api/staff/activate/submit/`, `/api/auth/telegram/` | direct alias | `core.legacy_routes` warning count |
| root public signer APIs | `/api/origination/sign/api/...` | direct alias; bearer credentials are never redirected | `core.legacy_routes` warning count |
| root Telegram/TAT/Africa's Talking callbacks | corresponding `/api/...` callback | direct alias until provider dashboards are verified | `core.legacy_routes` warning count |

Deprecation records contain only method, request path, and canonical path. They
must never include query strings, bodies, cookies, bearer values, or headers.
Remove each explicit alias only after its production count is zero for the
agreed observation window.

## Client and launcher findings

First-party Mini App JavaScript uses `/api/` for server calls. Telegram launcher
generation uses root browser routes. Public signing HTML emits the canonical
API session URL while its long-lived root APIs remain direct compatibility
aliases. Telegram webhook retries are not subject to application throttling.

## Executable manifest checks

Run:

```bash
python scripts/check_settings_env_parity.py
python scripts/check_dependency_parity.py
```

The first check requires every literal `config(...)` key in Django settings to
have an active `.env.example` assignment. The only environment-only exceptions
are the deployment bootstrap Superuser variables. Deprecated single-sheet and
JSON routing variables remain explicitly blank and labelled as compatibility
settings.

The second check requires pip and Poetry to declare the same direct packages
and verifies runtime import coverage. Both manifests target Python 3.12. The
Order Approval submission ceiling is 30 MB in settings, the environment
template, the rendered client, and operational documentation.
