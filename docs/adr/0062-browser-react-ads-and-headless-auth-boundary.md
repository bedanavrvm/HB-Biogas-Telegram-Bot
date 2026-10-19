# ADR 0062: separate React browser client and constrained JSON authentication

## Context

The user explicitly selected React and Atlassian Design System (ADS) for new
standalone browser pages. This supersedes the earlier no-SPA direction for that
new channel only. Telegram is the current operational UI and remains unchanged.
P1a and P1b.1 are committed on the working branch; production release/migration
state remains unknown. Browser admission is disabled.

The user chose exact package/licence review before installing ADS packages or
assets. The general ADS licence describes Atlassian-integrated uses, while some
published packages declare open-source licences. Neither package metadata alone
nor choosing React establishes permission for a complete standalone ADS stack.

## Decision

Keep a logically separate browser React frontend, sharing Django's canonical
staff, authorization, business services and data. Prefer a same-origin deployment
with server-side session cookies and CSRF-protected JSON APIs; a second frontend
does not require a second backend service or client-stored bearer tokens.
Do not import Telegram SDK/utilities/themes into React or restyle Telegram.

Record ADS as the chosen design direction, subject to an exact direct/transitive
package, asset, font/icon and notice review before installation. Do not invent
permission or silently substitute another design system. Proposed build-tool and
version choices need their dependency/compatibility decision before installation.
Official current setup favors Parcel/Compiled; its Vite integration is explicitly
experimental. Avoid treating an unreviewed Vite scaffold as the default.

Implement P1b.2a as the next backend slice: an allowlisted JSON password/MFA/state/
logout boundary over the installed allauth headless browser views, plus a
request-local encrypted pending-enrollment session adapter. Keep production URLs
unmounted and activation checks blocking. Add the headless Django app from the
already-pinned allauth distribution; no new dependency, model or migration.

The boundary accepts only same-origin cookie/CSRF browser requests, never Telegram
or app-token fallback. Admission, current active identity, verified primary email,
bounded channel context and MFA assurance remain independent requirements.
Normalize responses instead of exposing the generic allauth account surface,
partial user/contact records, methods or session tokens. A password-only session
is an enrollment-only state, never authenticated business authority. Successful
company login is audited before this boundary reports success.

Protect only the vendor pending-TOTP session entry during wrapped requests using
dedicated-key encryption with expiry and user/admission/revision binding. Do not
change the global Django session backend or patch installed vendor source. This
storage adapter is not authorization to expose enrollment endpoints.

## Consequences

React dependency upgrades, ADS linting/tokens/components, accessibility and
interaction evidence, browser build/licence/size checks, and asset-cache rollback
become a distinct maintenance budget. Existing Node Mini App tests and Django
release paths remain unchanged until an explicitly reviewed browser build is
added. Existing Telegram Design Lab migration restrictions remain in force;
choosing ADS for new browser pages is not approving a Telegram redesign.

No React/ADS packages or assets, production auth URL, generic signup/reset/email
management route, grant, real message or production change is added here. Shared
cache/replay protection, provisioning, enrollment/recovery UI, offboarding
integration, mail/support, licence clearance and M1 staging acceptance remain
activation gates. Normal rollback keeps browser admission off; no schema reversal
is required for this slice.

## Alternatives considered

- Reuse Telegram templates/SDK in React: rejected by the user's separate-browser
  direction and channel independence requirements.
- Rebuild business workflows in React or add another backend/database: unnecessary
  and creates conflicting authority.
- Mount allauth's complete account/app-token API: rejected; broader account,
  recovery and token surfaces are not the approved pilot scope.
- Automatically install the complete ADS ecosystem: rejected pending the user's
  chosen package/licence review.

## Primary references

- https://atlassian.design/license/
- https://atlassian.design/get-started/develop/atlassians
- https://atlassian.design/foundations/tokens/use-tokens-in-code
- https://docs.allauth.org/en/latest/headless/installation.html
