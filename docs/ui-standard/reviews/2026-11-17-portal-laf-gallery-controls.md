# Portal LAF, gallery and repayment controls - 17/11/2026

The user requested an icon for Fill Biogas LAF beside upload/camera, a clearer
client-media gallery, an inline repayment pencil that expands/collapses the
correction fields, and captured LAF pages fitted to A4.

## Changes and source patterns

- `portal_lafs/static/portal_lafs/form.js` and `form.css` reuse the visit's
  40px document action buttons. The form icon has a Fill/Resume accessible name
  and tooltip; progress, availability, feature gating, saved drafts and signing
  remain under the existing LAF service. Other stages retain their LAF access.
- `portal_farmer_sheet.js` moves Case documents navigation into the preview
  header with an explicit Document counter. Page navigation, a Page counter,
  zoom, fit and rotate stay together below the image. Single-image page arrows
  disappear; page buttons never switch documents in this gallery. Swipes,
  keyboard navigation, abort/retry and return to the unsaved review remain.
- `secure_media_viewer.js` uses consistent SVG icons. Its page-only control
  option is enabled only by this client-media gallery, preserving other shared
  gallery consumers' existing next-document behaviour.
- The final-review repayment disclosure places the pencil beside the saved
  day/period. Its existing native details control toggles the fields, retains
  drafts and submits corrections only when expanded. The extra text-action row
  is removed. `portal.css` reuses existing controls and fixes inherited icon
  margins so tool groups stay together on desktop as well as phones.
- `jbl_visit_documents.render_document` explicitly fits new LAF images inside
  186 x 273mm on A4 with 12mm margins. Previously maximum sizes alone left smaller
  photos at their intrinsic size. Portrait and landscape images now scale to the
  largest fit without cropping or distortion; Client ID collation is unchanged.
  Existing retained/signed documents are not rewritten. Background inside a
  photograph remains part of the photograph; this does not invent a crop.

Asset versions are incremented in `base_shell.html`. No new dependency, migration,
permission or production feature activation is introduced. Existing source-bound
patterns are reused; candidate foundations and Phase 6 migration remain on hold.

## Evidence

Playwright used the native Django Portal shell on isolated PostgreSQL with
signed synthetic Telegram credentials and normal authorized case, draft, LAF,
media-list and media-preview APIs. Synthetic bytes replaced only the Drive
download/template boundary; external sockets were blocked. The generated LAF PDF
was rendered by the real preview processor. The initial local storage fixture
needed its constructor patched before that final journey; no provider was called.

The native journey opened/resumed the LAF from its icon, expanded/collapsed the
repayment editor, opened media from the case's Client Media list, paged within a
two-page PDF, switched to the ID image, zoomed/rotated, and returned to the same
case. Screenshots were visually inspected at 320px, 390px and 1280px, including
dark mode. No horizontal overflow or JavaScript page errors were recorded.
The final capture includes the correction for inherited auto margins that had
spread toolbar controls apart on desktop.

- [LAF action icons](portal-media-controls-2026-11-17/laf-icons-390.png)
- [Repayment pencil and expanded fields](portal-media-controls-2026-11-17/repayment-pencil-390.png)
- [Gallery at 320px](portal-media-controls-2026-11-17/gallery-320-light.png)
- [Gallery at 390px](portal-media-controls-2026-11-17/gallery-390-light.png)
- [Gallery at 1280px](portal-media-controls-2026-11-17/gallery-1280-light.png)
- [Dark gallery](portal-media-controls-2026-11-17/gallery-390-dark.png)
- [Real generated A4 page](portal-media-controls-2026-11-17/captured-laf-a4.png)

The document-size regression failed before the fix (77pt unused printable
extent) and passed afterward, checking actual PDF image bounds, aspect ratio,
margins and page counts. The full document, outcome and repayment suites passed:
63 backend tests. All 46 focused Playwright tests passed, covering the icon feature gate, form open/
resume, correction submission/draft retention, grouped controls, single-image
and multipage navigation, zoom/rotation, late-response cancellation and other
shared consumers. An older rejected-case fixture was aligned with the current
decision_context contract; no rejected-case production logic changed.

The UI source ratchet, 221-route write inventory, 180-file first-party JavaScript
syntax check, LAF script syntax, selected Ruff checks, Git whitespace check,
migration drift check and 233-table database catalogue verification passed.

No production deployment, live Drive access, physical handset or printing check
was performed. No historical PDFs, customer records or production grants changed.
