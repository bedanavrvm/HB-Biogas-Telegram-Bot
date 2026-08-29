# Telegram Staff Activation Mini App Setup

## Purpose

Telegram staff onboarding needs a dedicated Mini App launch point so Telegram
supplies signed `initData` when a new staff member proves their identity. The
activation page combines that signed Telegram identity with the username
enrolled by the Superuser and the single-use activation code shown in Django
Admin.

This is a BotFather registration under the existing JBL Telegram bot. It is
**not** a new bot, Render service, Django application, or frontend codebase.
The existing Django service already owns the activation page and submit API.

## Why a separate Mini App registration is required

The activation endpoint must know which Telegram account opened it. A normal
HTTPS link, including one opened in Telegram's ordinary in-app browser, does
not reliably provide Telegram Mini App `initData`. Without signed `initData`,
the server cannot securely bind the newly created Django user to a Telegram
user and correctly rejects activation.

A BotFather Mini App deep link launches the page in Telegram's Mini App
context. Telegram then provides the signed identity payload that the backend
validates before accepting the activation code.

Keeping activation separate from Portal, Origination, and other operational
Mini Apps also gives the unaffiliated new user only the smallest surface needed
to activate. Workflow buttons are sent only after identity binding and are
filtered by the user's effective `AccessGrant` authorization.

## Architecture

```text
Superuser creates and authorizes staff in Django Admin
                         |
                         v
     One-time activation link and eight-digit code
                         |
                         v
https://t.me/<bot_username>/<activation_short_name>
                         |
                         v
 Telegram opens /api/staff/activate/ as a Mini App
                         |
                         v
Server verifies signed initData + enrolled username + code
                         |
                         v
Identity is bound and the authorized onboarding handoff runs
```

The relevant existing routes are:

- `GET /api/staff/activate/` — renders the activation page.
- `POST /api/staff/activate/submit/` — validates Telegram `initData` and the
  single-use activation code, binds identity, and starts the onboarding
  handoff.

## BotFather configuration

Register one Mini App on the existing production bot with these values:

| Setting | Value |
|---|---|
| Display name | `JBL Staff Activation` |
| Short name | `staff-activation` |
| Mini App URL | `https://jbl-biogas-telegram-bot.onrender.com/api/staff/activate/` |

The short name must match the deployment setting exactly. If a different
short name is chosen in BotFather, use that same value in Render instead of
`staff-activation`.

The resulting launch URL has this shape:

```text
https://t.me/<TELEGRAM_BOT_USERNAME>/<STAFF_ACTIVATION_MINI_APP_SHORT_NAME>
```

Do not substitute the direct Render URL in the activation pack. The direct URL
is useful for checking that the page renders, but it cannot complete secure
Telegram identity activation because it lacks signed Mini App context.

## Render configuration

Set the following environment values on the existing Django web service:

```text
TELEGRAM_BOT_USERNAME=<existing bot username without @>
STAFF_ACTIVATION_MINI_APP_SHORT_NAME=staff-activation
APP_BASE_URL=https://jbl-biogas-telegram-bot.onrender.com
```

`TELEGRAM_BOT_TOKEN` must already belong to the same bot used for the BotFather
Mini App registration. Never put its value in source control or this document.

After changing Render environment values, deploy/restart the existing service
through the normal controlled deployment process. No second service is
required.

## End-to-end onboarding flow

1. An active Superuser opens **Django Admin > Configuration > Users > Staff
   lifecycle workspace** and chooses onboarding.
2. The Superuser selects Telegram as the login channel, records the intended
   Telegram username, assigns the required access, and explicitly selects the
   groups the employee should join.
3. The Superuser reviews and applies the plan directly. Checker review is
   optional only when the Superuser deliberately chooses independent review.
4. Django displays an activation pack containing the BotFather Mini App link
   and an eight-digit code. The code is shown once, expires after 15 minutes,
   is single-use, and is blocked after five failed attempts.
5. The Superuser gives both items privately to the intended employee.
6. The employee opens the link inside Telegram and enters the code.
7. The server verifies all three identity factors:
   - Telegram's signed `initData`;
   - the Telegram username enrolled during onboarding; and
   - the current single-use activation code.
8. On success, the immutable Telegram ID is bound to the Django user.
9. The system refreshes each selected group's shared pinned launcher, creates
   one-member invitations that expire after 24 hours, and sends a private
   welcome containing only Mini Apps the employee is authorized to use.
10. The employee accepts each group invitation. Telegram bots cannot silently
    add a person to a group, so invitation acceptance remains a user action.

The shared Mini App launcher is pinned in each configured group. It is not
pinned separately in the employee's private chat. The private welcome provides
the employee's authorized buttons and group invitations.

## Welcome and group-membership behaviour

The private welcome must reflect current authorization rather than a hardcoded
list of applications. An `AccessGrant` controls whether the staff member may
use a workflow; accepting a Telegram invitation controls whether they are a
member of that operational group. These are intentionally separate controls.

A failure to send the welcome, refresh a launcher, or create an invitation
does not roll back the already applied Django account and access changes. The
lifecycle plan shows **Attention required**, and an active Superuser can use
**Retry Telegram delivery**. Retrying resumes the durable handoff and must not
create a second user or duplicate successful delivery work.

## Production prerequisites

- The bot is an administrator in every selectable Telegram group.
- The bot has permission to create invite links and pin messages.
- Each selected group has an enabled `GroupSheetConfiguration` compatible with
  the user's final access.
- `TELEGRAM_BOT_USERNAME` identifies the same bot configured in BotFather.
- `STAFF_ACTIVATION_MINI_APP_SHORT_NAME` exactly matches BotFather.
- The Mini App URL uses HTTPS and points to `/api/staff/activate/` on the live
  Django service.
- Production keeps `ACCESS_GRANT_GOVERNANCE_ENFORCED=True`.

## Safe verification checklist

Use a synthetic staff account and a controlled Telegram test group.

1. Open the direct HTTPS activation page in a normal browser. Confirm it
   renders, but activation reports that it must be opened inside Telegram.
2. Apply one synthetic Telegram onboarding plan as a Superuser.
3. Confirm the activation pack link starts with `https://t.me/` and contains
   the configured bot username and activation short name.
4. Open the link using the intended Telegram account and submit the code once.
5. Confirm a second submission cannot reuse the code.
6. Confirm the user's immutable Telegram ID is bound and the private welcome
   contains only authorized Mini App buttons.
7. Confirm each selected group receives or retains one shared pinned launcher
   and the employee receives an expiring invitation.
8. Confirm the employee is not silently added to a group before accepting its
   invitation.
9. Exercise **Retry Telegram delivery** after a controlled delivery failure and
   confirm it does not duplicate the user, identity binding, or completed work.
10. Confirm usable invitation URLs disappear from durable records after the
    welcome succeeds; only their digest, expiry, status, and audit evidence
    remain.

Do not use real customer data, production staff accounts, or uncontrolled
Telegram groups for this verification.

## Troubleshooting

### "Open this activation page inside Telegram and try again"

The page did not receive valid Telegram Mini App `initData`. Confirm the person
used the `https://t.me/<bot>/<short-name>` link and that the BotFather Mini App
URL points to the activation endpoint. Opening the direct Render URL is not
sufficient.

### Activation pack uses the direct HTTPS URL

One or both of `TELEGRAM_BOT_USERNAME` and
`STAFF_ACTIVATION_MINI_APP_SHORT_NAME` is blank or incorrect. The service falls
back to a direct URL when it cannot construct the Telegram Mini App deep link.

### Username or activation code did not match

Confirm the employee is using the Telegram account whose username was enrolled
by the Superuser. If the code expired, was consumed, or reached the failed
attempt limit, use **Generate replacement activation pack**. Never manually
edit the numeric Telegram ID.

### Welcome or group invitations were not delivered

Check the lifecycle plan's Telegram onboarding status and error code. Verify
the bot's group permissions, then use **Retry Telegram delivery**. Do not
recreate the Django user.

### Wrong Telegram account was bound

Use the governed Telegram identity-reset process described in the staff
lifecycle workspace. The numeric Telegram ID is immutable under ordinary model
editing and must not be corrected with a direct database update.

## Related documentation

- [Staff Lifecycle Workspace](staff-lifecycle-workspace.md)
- [ADR 0030: Telegram staff onboarding handoff](adr/0030-telegram-staff-onboarding-handoff.md)

