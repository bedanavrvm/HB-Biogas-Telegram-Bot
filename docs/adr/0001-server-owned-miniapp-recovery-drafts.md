# ADR 0001: Server-owned Mini App recovery drafts

Status: Accepted — 29-July-2026

## Context

Portal, FCA, FarmUp/System Export, and SPIN forms can be interrupted by a weak
mobile connection, an incoming Telegram message, or a WebView restart. Browser
`localStorage` is not an acceptable store for sensitive customer form data: it
is tied to one device/browser profile, is hard to audit, and may leave copies
after a staff account's access changes.

The Portal must retain its workflow-specific screens and navigation. The TAT
Mini App provides the visual reference for compact hierarchy and immediate
feedback; it is not a replacement information architecture for the Portal.

## Decision

Use one `MiniAppDraft` model and `core.services.miniapp_drafts` for
short-lived, field-only recovery data. Each draft is scoped to the canonical
Django user, workflow, and batch/group context; it uses a revision number to
reject stale writes and expires after seven days.

The generic draft API requires verified Telegram `initData` plus the same
scoped authorization used by the underlying form (a signed review token for
FCA/FarmUp or SPIN role capability). It never accepts multipart uploads or
attachment payload fields. Files remain on the device until the explicit
workflow submission.

Shared UX behaviour is centralized in `core/static/miniapp/utils.js` and
`base.css`: touch-friendly controls, theme-aware status semantics, skeleton
loading cards, haptic confirmation where Telegram supports it, and harmless
session-only UI context restoration. Portal keeps its screens; the shared
primitives bring its feedback and resilience in line with TAT.

## Consequences

- Sensitive drafts are no longer stored in browser `localStorage` for the
  covered forms.
- A second device cannot silently overwrite a newer saved draft.
- Offline edits remain visible in the current screen but are not claimed as
  durably saved until the server confirms them.
- Attachments must be selected again after a form recovery, by design.
- The change adds a schema migration: `core.0072_miniapp_drafts`.

## Alternatives considered

1. Continue with `localStorage` — rejected because it is not centrally
   controlled, cannot be associated reliably with staff access, and can retain
   customer data after account changes.
2. Build a separate SPA/offline-sync client — rejected because the repository
   deliberately uses Django-rendered Mini Apps without a frontend build
   service; it adds substantial operational and security complexity.
3. Store uploaded files as drafts — rejected because this would create
   uncommitted customer-document copies and muddle Drive/audit ownership.

## Release and rollback

No production migration or Render deployment is authorized by this ADR alone.
Before production release, obtain explicit approval, confirm a current
PostgreSQL backup, and manually test the covered forms inside Telegram.

To undo the schema change after an approved deployment, first confirm no
recovery drafts need retaining, then run:

```powershell
python manage.py migrate core 0071_accesscontrolpolicystate_and_more
```

This removes the non-canonical draft table only; it does not alter staff,
access-grant, payment, or workflow records.
