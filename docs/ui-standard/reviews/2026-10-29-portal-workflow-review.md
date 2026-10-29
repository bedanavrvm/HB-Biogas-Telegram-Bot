# Portal workflow recovery and bulk documents

29 October 2026. User-requested synthetic workflow review with realistic negative
outcomes and orders above 50 leads. This repairs the existing Telegram Portal;
it introduces no replacement shell, CSS system or lab tokens.

The [full review](../../portal-miniapp-workflow-review-2026-10-29.md) records
backend causes, manual browser actions, bulk workbook inspection, failures,
recovery and remaining limits. Open the
[local evidence gallery](../../../test-results/portal-workflow-review/index.html).

## Existing patterns and intentional changes

- History uses existing cards, badges, details, secure media and file controls.
  Completed and Awaiting signed scan now reflect retained payment state. Only
  pending review is labelled Review payment; retained documents use Preview
  workbook. Superseded loads cannot replace the active tab/filter.
- Signed-scan controls carry a nonvisual source version/checksum. A changed
  workbook is explained, the chosen file retained, and current version required.
  Drive failure uses the existing retained-file retry flow.
- Existing FarmUp confirmation, progress, feedback and selection serve a
  confirmed bulk selection in 50-row saves. Interrupted work retains completed
  rows and remaining selections. No automatic warning acknowledgement is added.
- Expected errors reuse inline feedback/toasts with reviewed messages. Unknown
  errors remain generic. Workbook fixes affect print geometry, not Portal CSS.
- `base_shell.html` cache versions bind the revised scripts. No shared visual
  tokens, other Mini App styling or operational template layout is changed.

## Manual evidence

Playwright used real Django/PostgreSQL workflow and local provider transports.
No tests, assertions, lint or type checks were run.

| Interaction | Evidence in the gallery |
|---|---|
| Active History tab survives delayed response | `history-delayed-response-overwritten-390.png` before; `history-delayed-response-retained-390.png` after; `history-response-race.js.result.json` |
| Completed 61-case payment and preview | `payment-history-completed-61-final-390.png`, `payment-history-retained-61-preview-390.png` |
| Stale workbook refuses chosen scan | `signed-order-stale-source-rejected-after-390.png` |
| Provider failure retains scan with guidance | `signed-order-retained-guidance-after-390.png`, `signed-60-order-drive-outage-retained-390.png` |
| 500 rows selected and saved through real UI | `farmup-500-selected-native-ui-390.png`, `farmup-500-native-ui-complete-390.png` |
| 50 saved / 50 retained, then successful retry | `farmup-interrupted-50-saved-50-retained-390.png`, `farmup-interrupted-resumed-complete-390.png` |
| Specific duplicate and invoice feedback | `credit-duplicate-number-blocked-after-390.png`, `invoice-unrecognized-clear-guidance-final-390.png` |
| Full workflow and responsive reports | Office lead through commissioned history; reports at 320/390/1280; dark History at 390 |

The gallery retains pre-repair/intermediate failures and actual Excel-exported
pages for the final 252-case order and 61-case payment. Captures establish the
shown states, not human design approval, real-device accessibility or provider
delivery. Source hashes for changed UI files are in `registry.json` changes and
the local manifest. Legacy/approved hashes, pending review status and Phase 6
migration hold remain unchanged.
