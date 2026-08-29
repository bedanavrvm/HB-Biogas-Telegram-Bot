# Staff access and Telegram onboarding

## Source of truth

`AccessGrant` is the permanent Mini App authorization source of truth. Telegram group membership, launcher messages, and activation records do not grant workflow access.

Each permanent grant is one exact tuple:

`workflow + role + branch + product + Telegram group configuration`

A blank branch, product, or group is a deliberate wildcard for all current and future compatible values. It is not the same as selecting every value that exists today.

## Guided scope editor

The Staff lifecycle workspace groups the editor by workflow and role. Within one card, selected branches, products, and Telegram groups expand to the Cartesian product of exact grants. Use another card when combinations must not cross.

The review screen lists every exact tuple and shows added, retained, and removed counts. More than 12 resolved grants receives a prominent warning. One scope card may create at most 50 grants and one lifecycle plan at most 100.

An active Django Superuser may apply a change directly. Independent checker review is optional and is used only when the Superuser deliberately selects that path. Non-Superusers cannot use direct apply.

## Telegram onboarding completion

Activation proves the Telegram identity. It does not independently prove authorization.

Before welcome messages, launchers, or invitations are delivered, onboarding calls the same `workflow_access_decision()` service used by the first protected Mini App endpoint for the selected Telegram group and launcher capability. Onboarding may be marked complete only when every applicable launcher passes that runtime-equivalent decision.

Readiness failures use stable reasons:

- `telegram_identity_unbound`
- `workflow_grant_missing`
- `group_scope_mismatch`
- `capability_policy_denied`

The Admin effective-access page shows the exact grant tuples, Telegram identity status, configured launcher capability, group ID, matching grant evidence, and readiness result.

## Runtime denial diagnostics

TAT protected endpoints distinguish an unbound identity, a missing workflow grant, a Telegram-group scope mismatch, and a denied capability. Client responses remain safe and supportable; server logs retain the stable reason code and request correlation ID.

## Read-only production audit

Run:

```powershell
.\.venv\Scripts\python.exe manage.py audit_staff_launcher_readiness
```

Use `--json` for machine-readable evidence. The command is diagnostic-only: it does not create, broaden, retire, or repair any grant. Repair failures through the Staff lifecycle workspace so the exact diff remains reviewed and audit-logged.

## Verification checklist

1. Open the user in Django Admin and select **View effective access**.
2. Confirm the Telegram identity is bound to the intended user.
3. Confirm the selected group and launcher show **Ready**.
4. Confirm the exact grant table contains either that group configuration or the explicit all-compatible-groups wildcard.
5. Open the Mini App from the same Telegram group and confirm its bootstrap endpoint succeeds.
6. If it fails, use the stable denial code and request ID; do not broaden the user to all scopes merely to clear the error.
