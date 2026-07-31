# ADR 0015: Server-rendered Portal PDF preview

Status: Accepted for code merge and staging validation - 31-July-2026

## Context

Portal staff need to view signed LAF PDFs without leaving the Telegram Mini
App. Android Telegram WebView renders protected PDF blob iframes as blank, and
its embedded Google document viewer path is blocked with
`ERR_BLOCKED_BY_RESPONSE`. Opening Drive or Chrome loses the Mini App case
context and can trigger an Android activity chooser.

## Decision

Use `pypdfium2==5.12.1` to rasterize an already-authorized PDF into bounded,
server-generated page images. The existing protected Portal media endpoint
returns a self-contained HTML preview with those images, which the existing
in-app overlay displays. Rendering is limited to the stored PDF, happens only
after Portal authorization, and does not expose a Drive URL or file ID.

The maximum rendered page count, resolution, and output size are enforced in
the Portal view. A rendering failure returns a stable in-app error and does
not change workflow state or the stored evidence.

## Consequences

- The Portal remains open on Android while staff inspect signed PDFs.
- PDF previews use more server CPU and response bandwidth than direct images;
  bounded rendering prevents a malformed or unexpectedly large PDF from
  consuming unbounded resources.
- Each successful preview retains the existing sensitive-media access audit.
- No schema migration or external write is required.

## Alternatives considered

- Browser blob PDF iframe: rejected because Android Telegram WebView displays
  a blank panel.
- Embedded Google document viewer: rejected after device verification showed
  `ERR_BLOCKED_BY_RESPONSE` in the WebView.
- `pypdf`: already installed, but it extracts/manipulates PDFs and cannot
  rasterize page images.
- PyMuPDF: locally present but dual-licensed AGPL/commercial; rejected to
  avoid an unsuitable licence dependency.
- External browser/Drive: rejected because it leaves the Mini App and loses
  case context.

## Rollback

To undo, remove the preview renderer code and run dependency installation from
the prior manifests. No database migration exists and no customer evidence is
modified. Do not remove existing Drive files or audit events.
