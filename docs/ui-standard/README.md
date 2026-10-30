# Mini App Design Lab

Standalone browser styling now follows `browser/AGENTS.md`: the user's
28 October 2026 instruction makes supplied code/CSS and screenshots authoritative
for this and future requests, superseding the historical ADS adoption rule below.
Verify real interactive states in Playwright. Telegram migration and release
approval boundaries still apply.

P2a.2 / ADR 0072 extends that separate demo with synthetic role-based creation,
uploads, feedback/resolution and reopen/completion. ADS forms/Selects and
side-by-side customer/evidence layout are source-bound candidates; the hidden
native file chooser is an intentional exception documented in browser/DESIGN.md.
Decision section 15 records current evidence. No approved baseline changes,
native P2a write activation, real access or Telegram migration.

P2a.1 / ADR 0071 makes a separate synthetic Complaints demo available at
http://127.0.0.1:8767/. It reuses the ADS workspace with an explicit demo context,
fixture-only reader and no account setup. Decision section 14 records source/
browser evidence. Native staff access and Telegram migration remain gated.

P2a / ADR 0070 now connects a separate closed React/ADS Complaints workspace to
native company authentication and owning Complaint read services in isolated
synthetic tests. Decision section 13 and the component index record the new
candidate. The fixed preview and Telegram migration hold remain separate;
operational M1/privacy/named-reader/human acceptance are still required.

## Current stage

Portal direction, confirmed by the user on 30 October 2026: preserve the current
compact layouts and maximize useful information visible without scrolling.
Do not enlarge typography, add spacing or hide existing facts behind extra
sections by default. The before/A/B review approved only bottom navigation on
pages without Telegram's sticky primary action and the Performance activity
card. This does not accept either complete redesign. The bounded changes and
browser evidence are in
[the selection record](reviews/2026-10-30-portal-selected-refinements.md).

The Design Lab covers Portal, TAT Tracker, Complaints and Origination. All
patterns start unreviewed. The lab does not change their live UI, workflow
permissions or business rules. Candidate tokens/themes are not an approved
standard. **Phase 6 migration requires separate explicit user approval.**

The user's 19 October 2026 React/Atlassian Design System decision concerns **new
standalone browser pages only** (ADR 0062). It is not permission to migrate or
restyle the Telegram Mini Apps. Exact package/transitive/asset review now supports
the bounded local `browser/` React/ADS build (ADR 0066), with explicit dependency
exceptions, notices and exclusions. It is a synthetic demo, not operational
authentication or acceptance of every ADS asset. The current source/component
inventory is in component-index.md. See
`codebase-analysis-docs/assets/BROWSER_REACT_ADS_DECISION.md`.

The user's subsequent **full design adoption for the browser frontend** request
governs the current P1c.4 correction (decision section 10). It uses documented
single-column forms, persistent SectionMessage feedback, flat surfaces, the
fixed-wide workspace grid and actual Navigation System components. ADS typed
tokens and full recommended lint sets remain blocking. Always consult relevant
current official docs as required by `browser/AGENTS.md`; `browser/DESIGN.md`
maps the decisions. Imports, lint, viewport fit and screenshots do not certify
full design conformance. This browser authorization does not select/migrate
Telegram lab candidates or replace human evidence review.

The **actual React/ADS preview** is served at http://127.0.0.1:8766/ using
`python scripts/serve_ads_browser_preview.py` after the build documented in
`browser/README.md`. Credentials stay fixed demo values; business tools are
disconnected. Design selectors live separately at
http://127.0.0.1:8766/review.html. This local candidate does not approve a
standard or open M1.

P1c.5 additionally builds a separate dormant native sign-in client under ADR
0067, exercised only by opt-in isolated React-to-Django tests. It follows the
same official patterns with editable fields/autofill/inline feedback and short
password/code steps. Source candidates are in the component index/registry.
It is not served by the fixed-value preview, mounted in production, completed
onboarding or M1 acceptance. Current evidence and limits: decision section 11.

P1c.6 extends that dormant client with guided initial-password, local credential
QR/manual-key setup and one-time recovery handoff (ADR 0068, decision section 12).
Sensitive images/codes are masked in synthetic captures. Actual delivery/support,
human/device review and operational acceptance remain open; no lab approval or
Telegram migration follows from this client work.

A historical local, first-party access wireframe makes the proposed browser states
reviewable without installing dependencies or connecting authentication. Run
`python scripts/serve_browser_access_preview.py` and open
http://127.0.0.1:8765/ on the same computer. It uses fixed demo values and no ADS
assets, cookies, API or persistent storage. Its candidate inventory is in the
component index and source ratchet. This is not the React client, a standard
release, human design approval or permission to migrate Telegram. Exact scope,
verification and rollback are in the decision document's section 6.

See [implementation status](implementation-status.md) for delivered tooling,
known audit gaps, test results and remaining review gates. This is not a claim
that all original audit journeys or real-device checks are complete.

The code-owned inventory contains 31 patterns, screen/journey lists, original
template/style/script pointers and source hashes. Current queue specimens run
actual app renderers, including Portal's real server-rendered farmer fragment.
I/O is synthetic. More specialised journeys that are not yet modelled report
coverage gaps rather than displaying a claimed equivalent. An absent pattern
(for example Origination reports) is not a design alternative.

Original app page redirects are adapted to a no-navigation recorder. Their
script ordering and defer/async attributes remain intact. This is part of the
synthetic I/O boundary, not a change to operational application source.

## Open the lab

1. Apply normal checked-in migrations during an authorised deployment.
2. Set `UI_DESIGN_LAB_ENABLED=True` in the deployment environment.
3. Open `/ui-lab/` using an active Django Superuser session, or the linked
   Superuser's Telegram identity. When enabled, the lab also appears in that
   Superuser's JBL Apps list and Admin technical navigation.
4. Ordinary staff and workflow IT grants cannot read or submit lab reviews.

Anonymous bootstrap contains no catalogue, sources or evidence. Browser-session
writes require CSRF; Telegram requests use the existing verified identity
backend. Invalid supplied Telegram authentication never falls back to a cookie.
Setting the flag false hides the entry and denies the APIs without deleting
review history. No bot configuration or workflow-role shell command is needed.

## Review a pattern

1. Start with Foundations. Switch density and Telegram/JBL, Automatic/Light/Dark.
   These choices preview proposals; they do not approve them or affect live apps.
2. Select a pattern and an app. Use previous/next or Compare all. Keep “This
   device” width on a phone for 1:1 comparison; larger selected widths deliberately
   scroll inside the preview. Check long, empty, loading and failure states.
3. Expand source/behaviour details. Verify the expected element actually opened.
   Role profiles are fixtures, not a current access-policy audit.
4. Capture synthetic-only evidence. Identify alternative, state, theme and
   browser versus real Telegram. Confirm the actual font before marking it
   verified. Remote-font fallback screenshots cannot prove production typography.
5. Save evidence. It creates an immutable successor revision in private storage.
   Keep the selected file if storage fails; no approval is recorded.
6. Record your choice and short reason. “Adopt with changes” requests work and
   is **not** final approval. Approving requires evidence for that alternative,
   verified font and explicit layout/state/behaviour confirmation.
7. Review native behaviour separately with Device checks. Only those explicit
   buttons invoke real Telegram controls. The temporary button/close settings
   are restored; the lab never closes itself or opens camera/microphone.

Earlier revisions and decisions remain in history. Source changes prevent
new decisions on stale revisions. Start a new comparison rather than rewriting
old approval. Review notes are retained in memory while switching patterns;
they are not customer drafts or cross-device saved notes.

Once foundations are approved and each pattern is approved or explicitly
deferred, Prepare reviewed standard creates an immutable release. Export its
manifest for repository review. It does not merge code, update screenshots,
enable themes for staff or start migration.

## Reproduce the read-only audit

Use an isolated local/CI environment, never an operational database or browser
session. The export command reads source files and renders templates without
calling operational views or integrations:

```powershell
.venv\Scripts\python.exe manage.py export_ui_audit
node scripts/capture_ui_audit.js test-results/ui-audit
```

The command accepts output only under a subdirectory of ignored `test-results`.
It exports a commit/dirty-worktree marker, exact source hashes, 224 source scene
documents, screen/pattern inventory and declared CSS values. The capture tool
records screenshots, DOM/computed measurements, element coverage, overflow,
target sizes, runtime errors and Telegram stub calls, then builds an image index.

Defaults: queue/filter/form scenes, seven states, 360×740 and 390×844, both
themes. Narrow a run or extend it using task-specific environment values:

```powershell
$env:UI_AUDIT_SCENES='queue,filters,form,reports,recognition,detail,settings,preview'
$env:UI_AUDIT_STATES='one,long'
$env:UI_AUDIT_WIDTHS='320,360,390,430,768,1280'
node scripts/capture_ui_audit.js test-results/ui-audit
```

Remote fonts/network services are blocked in automated capture. Their fallback
status is explicit. Timings and identities are synthetic; browser time is fixed.
Inspect `capture-report.json`, not just the image index, for failed or missing
coverage. A saved PNG is not proof that its intended component was visible.
The tool does not produce human approvals or update visual baselines.
Capture/runtime failures return a nonzero exit code; absent specialised
components remain visible coverage gaps rather than silently passing as tested.

## Guardrails and future changes

`registry.json` freezes existing first-party UI source hashes as the legacy
ratchet. `python scripts/check_ui_standard.py` rejects unexplained source drift
and loading candidate tokens in operational templates. A changed source needs
a matching hash, reason and review reference in `changes`; a genuinely
nonvisual change can use an explicitly reviewed nonvisual exception.
New HTML, CSS and JavaScript in the registered UI directories must also have a
review reference; creating a new file cannot bypass the source ratchet.
Source hashes use `lf-text-v1`: CRLF is normalised to LF for text files, so an
unchanged Windows checkout and Linux deployment agree. Binary assets keep
their exact-byte hashes. This does not ignore any text/content changes.

After a standard release, also run:

```powershell
.venv\Scripts\python.exe scripts/check_ui_standard.py --manifest path-to-reviewed-export.json
```

The checker verifies the release digest, decision references and exact approved
source hashes. Token checks apply only to explicitly governed modules, with
narrow property/value/reason exceptions. Existing code is not retrospectively
forced onto unapproved tokens. Repository review is still required: a JSON
manifest or green CI result alone is not proof of authorised human approval.

For every UI task, find its catalogue entry before editing. Reuse the approved
module when one exists, or submit a concrete candidate. Include source-faithful
light/dark mobile screenshots and failure/retry evidence; update usage notes and
tests. Preserve each app's own permissions and business decisions.

## Storage, retention and rollout

Three `ui_review` tables retain revisions, decisions and standard releases.
They contain no operational records. Review histories are retained until a
separately approved retention policy. Private Drive retains screenshot pixels;
saved manifests keep their digest and metadata. Access is rechecked on retrieval,
and downloaded bytes must match their stored digest. Missing evidence is shown
as unavailable, not silently replaced by current screenshots.

Only privacy-reviewed synthetic baselines may enter the existing governed
fixture directory and exact-hash artifact allowlist. CI success/failure captures
are temporary review evidence, not canonical approved baselines.

Before reversing schema, export standard manifests and back up review history.
The exact reversal is `python manage.py migrate ui_review zero`; this removes
lab database records only and leaves Drive files and operational data unchanged.
Disabling the flag is the normal rollback when history must survive.

## Remaining human gates

- Review/choose the foundations and patterns; none is pre-approved.
- Complete missing specialised journey fixtures and real-device checks before
  approving those behaviours.
- Verify fonts, 200% text enlargement, keyboard/safe-area behaviour and actual
  Telegram download/haptic results on staff devices.
- Automated review-notification delivery is not enabled. Share the protected lab
  link manually for now; no messages are sent by this implementation.
- Prepare the consumer-specific migration package after the standard is selected,
  then obtain explicit Phase 6 approval. No operational migration is authorised.
