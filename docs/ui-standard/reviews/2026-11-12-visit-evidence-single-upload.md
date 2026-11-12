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
