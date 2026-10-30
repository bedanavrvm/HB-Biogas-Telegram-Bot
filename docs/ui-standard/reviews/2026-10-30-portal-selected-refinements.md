# Portal: selected refinements and retained direction

30 October 2026. The user reviewed all thirteen proposed areas and prefers the
existing Portal UI. The broader A/B options are not selected. The user explicitly
prioritizes useful information exposed in the viewport over additional spacing
and larger type. The original comparison pack remains a historical review.

## Selected scope

- Bottom navigation only: retain the existing Home/Pipeline/Cases/More hub
  destinations and server-side capability filtering. Show the bar on mobile
  pages without Telegram's sticky main button. Hide it while the existing
  native-primary-action binding owns the bottom edge; restore it when that
  action closes. Desktop retains the existing sidebar.
- Performance activity card only: adopt the shared bordered Points/Cases/Visits
  row and neutral surface. Keep the current compact heading, score-details
  interaction, filters, standings and scoring data. The three numeric values
  use 18px type; no page-wide type or spacing increase.

This is explicit selection of these two elements, not approval of a whole A/B
screen, a candidate theme, an ADS migration or a new UI standard.

## Direction for subsequent Portal work

1. Start from the existing operational UI and the user's art direction.
2. Preserve its information density and visible facts. Use spacing to separate
   related content, without expanding every element or reducing visible rows.
3. Avoid new tabs, accordions or steps that hide information already visible.
4. Judge a proposal at the same viewport, content and workflow state. A page
   that looks cleaner after removing information is not an improvement.
5. Keep readable labels, focus states and usable touch targets. Density should
   come from composition, not cropped fields or overlapping controls.

## Implementation boundary

`base_shell.html` mounts the existing bottom navigation endpoint, using its
`surface=bottom` projection. `portal.css` reuses the existing bottom-tab styles,
with a 49px bar plus the device safe area and a 44px link target. The native
binding's existing `.miniapp-native-action` class controls visibility, so there
is no duplicated main-button state machine. The bar occupies a shell grid row;
it does not cover scrolling content.

`portal/portal.html` labels the existing personal summary Your activity.
Only that card's effective CSS changes. The owning Performance service,
attribution, milestones, personal totals, scoped slice, rank movement and final
snapshots remain unchanged. No backend feature, grant, provider action or
deployment flag is introduced.

The Score details walkthrough exposed an existing generic dialog-focus bug:
unlisted overlay IDs supplied an empty selector. Both initial focus and Escape
now fall back to the existing `.sheet-close-button`, preserving dialog-specific
handlers. This small recovery correction changes no dialog appearance.

## Browser evidence

Direct Playwright observations and screenshots are retained under
`test-results/portal-selected-refinements-2026-10-30/`. Its `review.cjs` uses the
real Django templates, Portal scripts and isolated synthetic PostgreSQL review
host. Telegram controls are a local bridge; external providers are blocked.
No test runner, assertions, lint or type checks are used.

The final run records twelve observations and no page errors. The external
Google font request is intentionally blocked; these images use the system font
fallback, as did the source comparison.

| Observed behaviour | Evidence |
|---|---|
| Compact activity card, all totals visible; height about 118px | [390px light](../../../test-results/portal-selected-refinements-2026-10-30/performance-390-light.png) |
| All three cells remain visible without horizontal page overflow | [320px](../../../test-results/portal-selected-refinements-2026-10-30/performance-320-light.png) |
| Actual dark Telegram theme colours | [390px dark](../../../test-results/portal-selected-refinements-2026-10-30/performance-390-dark.png) |
| Desktop retains its sidebar and hides bottom tabs | [1280px](../../../test-results/portal-selected-refinements-2026-10-30/performance-1280-light.png) |
| Officer totals remain 20 points, nine cases, nine visits | [Officer activity](../../../test-results/portal-selected-refinements-2026-10-30/officer-activity-nonzero.png) |
| Score details focuses Close; Escape returns focus to its opener | [Score details](../../../test-results/portal-selected-refinements-2026-10-30/performance-score-details.png), `observations.json` |
| Branch view keeps the activity card and original standings | [Branches](../../../test-results/portal-selected-refinements-2026-10-30/performance-branches.png) |
| Loaded Home shows the authorized hubs | [Home](../../../test-results/portal-selected-refinements-2026-10-30/home-390-light.png) |
| Native Log JBL Visit owns the action; bottom tabs are hidden | [Open visit](../../../test-results/portal-selected-refinements-2026-10-30/visit-native-action-no-navbar.png) |
| Closing the visit restores the 49px bar and active Pipeline hub | [Restored navigation](../../../test-results/portal-selected-refinements-2026-10-30/queue-navbar-restored.png) |

The bar ends at the viewport bottom. When shown, content ends immediately above
it; when hidden, content regains the full height. IT Pipeline opens FarmUp;
Officer Pipeline opens Visit Queue, using the existing server-provided hub URLs.

[Raw observations](../../../test-results/portal-selected-refinements-2026-10-30/observations.json)
and [source/image manifest](../../../test-results/portal-selected-refinements-2026-10-30/source-manifest.json)
are retained with the capture driver. With the existing isolated review host
running, repeat the direct walkthrough using:

```powershell
node test-results/portal-selected-refinements-2026-10-30/review.cjs
```

Physical Telegram, device safe-area behaviour, screen readers, the downloaded
font and real providers were not checked. No test suites, lint, type checks,
approved-baseline updates, workflow migrations or deployment were run.

## Changed source binding

| Source | SHA-256 (LF text) |
|---|---|
| `core/templates/base_shell.html` | `73e832b36ee195a2818214e2f96d79d2d1f7c6442977f47c5e43bfdfef9fa086` |
| `core/templates/portal/portal.html` | `3518fab4243a2821c79c2d7b12470065a2e8429332106992a7af7dfebc316e4d` |
| `core/static/miniapp/portal.css` | `29ac5919de6db5154939181a32cba1120d254953048b9c9d699e70e27762f660` |
| `core/static/miniapp/portal_dialogs.js` | `ce041985634d6f5a5631305723fe4893ce08683a9d1971720f6bf2a592aaeef2` |
