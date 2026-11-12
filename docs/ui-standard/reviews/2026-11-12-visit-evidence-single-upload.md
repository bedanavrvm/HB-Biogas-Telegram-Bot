# Visit evidence: one uploaded document, guided camera pages

User direction: upload one complete file; reserve front/back and specific-page
capture for the camera. The existing Portal disclosure, file picker, camera,
selection preview and error controls are retained.

Client ID and LAF each offer Upload document and Capture photos. Upload accepts
one complete PDF or combined image; empty front/back upload boxes and repeated
instructions are removed. Camera captures retain labelled page previews and
page-specific review/retake controls. Starting with the LAF now completes its
second page before moving to missing ID captures. One captured LAF page still
does not qualify as a complete LAF for repayment entry.

Optional evidence has a padded disclosure header and one readable instruction.
The initial empty state says No document selected; uploaded files show their
filename and preview/removal controls without a misleading capture count.
Replacing a document with an invalid multiple-file selection preserves the
previous selection. Supporting-photo uploads remain multiple-file.

## Local evidence

The actual base shell, production CSS cascade and Portal module ran in Chromium
with synthetic case/API replies, blocked remote hosts and a simulated camera.
No Django endpoint, operational database or real provider was exercised here.

Artifacts in `test-results/optional-evidence-review/` include closed, empty and
selected states at 390px and 1280px (light), plus 320px (dark). These were visually
inspected; the helper also checks horizontal overflow and retention of selected
files when changing outcome. The collapsed disclosure measures 44px high.

Eleven focused Playwright checks passed across `portal_camera.spec.js` and the
camera/repayment checks in `portal_role_remediation.spec.js`. They cover existing
cases and new leads, camera permission feedback, guided captures, LAF-first page
order, page retakes, upload/removal and repayment readiness/draft retention.
The single-file test additionally verifies rejection of a programmatically
supplied multiple-file selection without losing the selected document.

The older `miniapp_flows.spec.js` camera test fails before capture because its
fixture uses Visited instead of the forwarding outcome Visited, Awaiting Credit
Analysis, yet expects required village/location fields. That broader fixture is
not claimed green. Backend file validation and named camera-parts transport are
unchanged. Physical Telegram camera, production uploads and deployment were not
checked. No Phase 6 migration, permissions or browser activation is implied.

## Live Portal visual comparison and correction

The user requested comparison with the existing components using Playwright.
The follow-up used the running Django application at loopback port 8785, an
isolated local PostgreSQL database and signed synthetic Telegram identity.
Real Portal HTML, assets, authorization, farmer reads and draft endpoints ran;
external hosts were blocked and Google transports were stubbed. No production
records or real providers were used.

Before editing, Playwright opened the live JBL visit form and final-review form,
including its repayment editor. Screenshots and computed styles showed the
visit's 13px field values, 11px secondary labels, grouped white surfaces and
compact outlined actions. Media instead had oversized grey text buttons with
unequal widths, muted upload versus blue camera actions, bright blue empty-state
text and a different supporting-photo layout.

All three media categories now use the same compact row: 13px semibold title,
11px muted selection status, existing divider/surface colors and two equal
40px outlined icon actions. Upload always precedes camera. The buttons share
the existing media focus/hover treatment and accessible names; the disclosure
uses the existing blue inset keyboard focus style. Budget text is readable at
10px. File selection uses real buttons with native Enter/Space activation;
the old custom label-key handler was removed. Single-document uploads and
guided camera pages remain intact.

Artifacts in `test-results/optional-media-real-review/`:

- `before-visit-390.png`, `before-media-390.png`: live pre-correction visit.
- `reference-final-390.png`, `reference-final-edit-390.png`,
  `reference-final-1280.png`: existing live form references.
- `empty-*`, `collapsed-*`, `selected-*`, `preview-*`, `required-*`: final
  states at 320px and 390px light, 390px dark and 1280px light.
- `interaction-results.json`: assertions and computed 40px button geometry.

The real-page Playwright pass checks Enter/Space file-chooser activation, a long
filename, PDF preview/close, removal, no page-capture slots for a combined file,
LAF-dependent repayment entry, required versus optional outcomes, equal button
geometry and horizontal overflow. No page JavaScript errors occurred. Final
screenshots were visually inspected at the listed sizes/themes. The focused
camera/browser regressions separately retain their synthetic camera coverage;
physical Telegram camera and deployment remain unverified.

The live preview-content assertion then exposed HTTP 428: the shared selected-PDF
renderer sent identity without the required request key. It now also uses the
existing `MiniAppUtils.idempotencyHeaders` helper. A failing-then-passing browser
test covers matching request keys plus retained Telegram identity; all 17 shared
media/gesture checks passed. The live-page pass was repeated with an explicit
HTTP 200 assertion and decoded rendered-page assertion before taking preview
screenshots. This supersedes merely checking that the dialog opened. No backend
validation or access policy was relaxed. The separate 11 camera/repayment checks
also passed.
