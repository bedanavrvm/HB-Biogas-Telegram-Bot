/s# Portal user-language review

**Scope:** Staff-facing labels, helper text, buttons, empty states, dialogs, toasts, and errors in the Portal Mini App. This review covers all routable Portal screens, including screens limited to Operations, HomeBiogas, Head of Rural, Management, and IT. It does not change workflow rules, permissions, records, or backend identifiers.

**Review rule:** Keep terms staff use to perform work (`JBL`, `HB`, `order`, `invoice`, `payment`, `branch`, `loan officer`, `case`). Replace implementation terms with the result, the next action, or a concise explanation. A support reference may remain after a plain-language explanation.

## Navigation and shared language

| Location | Current label or copy | Issue | Suggested wording |
| --- | --- | --- | --- |
| Navigation | `Deferred & Reappraisal` | Combines two different outcomes; “deferred” is internal status language. | `Cases needing follow-up` with a status chip of `Deferred` or `Reappraisal needed` on each case. |
| Navigation | `Finalized Orders` | “Finalized” does not say what staff can find there. | `Signed orders` |
| Navigation | `Import History` | Sounds like a technical log rather than a usable work area. | `Imported files` |
| Navigation | `HB Action` | Ambiguous to new staff. | `HB installation & commissioning` |
| Pipeline stage | `Fulfilment` | British technical/operations terminology, not staff task language. | `Orders` |
| Pipeline stage | `Finance` | Too broad; the stage contains invoice and payment work. | `Invoices & payments` |
| Shared filter sheet | `Choose filters to narrow this queue.` | “Queue” is repeated and does not explain the effect. | `Choose what you want to see.` |
| Shared filter sheet | `Show` | Generic label beside ordering. | `Sort cases by` |
| Shared date filters | `HB visit date` / `JBL visit date` | Clear to experienced staff but the date’s use is not stated. | `HB visit date` / `JBL visit date` — retain labels and add `From` / `To` helper copy only when no dates are selected. |
| Shared errors | `Queue unavailable` | Correct but not action-oriented. | `This list could not load` |
| Shared errors | `Reference: ERR-…` | Necessary support detail, but appears without a plain action. | `Try again. If it still fails, share reference ERR-… with IT.` |
| Shared sync notices | `publication`, `publication operation`, `synchronization operation` | Backend terminology is visible to ordinary staff. | `Sheet update`, `pending Sheet update`, or `Sheet update failed` as appropriate. |
| Shared actions | `Retry sync` | “Sync” is familiar enough, but does not identify the target. | `Retry Sheet update` |

## Home and performance

| Location | Current label or copy | Issue | Suggested wording |
| --- | --- | --- | --- |
| Dashboard header | `Your authorized scope` | Authorization language does not help ordinary staff. | `Your work area` |
| Dashboard | `Operational pipeline` | Repeats “pipeline” and is abstract. | `Your work today` |
| Dashboard | `Current pipeline` / `Open a stage to continue work` | Repeats “pipeline” and makes stages sound like a technical construct. | `Where cases are now` / `Open a stage to work on its cases` |
| Dashboard | `Deferred or flagged` | “Flagged” does not explain the needed action. | `Needs follow-up` |
| Dashboard | `Scoped to your access` | Access-control language adds no value to ordinary staff. | Remove; the list already reflects the user’s work area. |
| Dashboard attention card | `Needs attention` with generic `review` detail | Can be too vague to identify what needs doing. | Use the concrete cause: `3 cases need an invoice`, `1 Sheet update failed`, or `2 cases are overdue`. |
| Dashboard activity | `Completed work` | Clear, but the timeframe is separated and easy to miss. | `Your completed work` with `Today` and `Last 7 days` attached to their values. |
| Performance header | `Live team insight` | Corporate wording that does not identify the screen. | Remove. |
| Performance header | `Provisional business outcomes from recorded JBL visits` | Technical and discouraging; “provisional” needs a plain explanation if retained. | `See this month’s visit results. Results can update as cases progress.` |
| Performance screen | `Officer breakdown by cohort` | “Cohort” is analytical jargon. | `Staff results by role, branch, and product` |
| Performance row | `quality floor` | Scoring implementation term. | `Performance score` |
| Performance row | `final approval`, `payment-finalized`, `pending` in one line | Dense and mixes outcome states with score explanation. | Use short metric labels in a compact details view: `Approved`, `Paid`, `Still in progress`. |
| Performance eligibility | `Minimum 20 completed visits to rank` | “Rank” may sound punitive without context. | `A result appears after 20 completed visits this month.` |

## Visits, credit, approval, and orders

| Location | Current label or copy | Issue | Suggested wording |
| --- | --- | --- | --- |
| JBL queue | `JBL Visit Queue` | “Queue” is useful but can be shortened in the title. | `JBL visits to complete` |
| JBL queue | `Farmers visited by HB, not yet visited by JBL` | Accurate but reads as a system condition. | `Customers HomeBiogas has visited and JBL still needs to visit.` |
| My visits | `My Submitted Visits` | “Submitted” is unnecessary; staff need the current state. | `My JBL visits` |
| Credit queue | `Credit Analysis Queue` | The role task is clearer than queue terminology. | `Credit analyses to complete` |
| Credit queue | `JBL visited - awaiting credit decision` | Hyphenated system phrasing. | `JBL visit complete. Credit decision needed.` |
| Order approval | `Make final case decisions before order preparation.` | “Final case decisions” is abstract. | `Approve or decline cases before an order is prepared.` |
| Approval delegation | `Review controls` / `Temporary approval cover` | Internal governance language is exposed before the action. | `Temporary approval cover` / `Choose who can cover approval while you are away.` |
| Order preparation | `Requisition Queue` | “Requisition” is an internal document term; staff call this an order. | `Orders to prepare` |
| Order preparation | `Final decision approved - assign order number` | Passive, redundant, and omits the next result. | `Approved cases ready to add to an order.` |
| Order preparation | `Official order number` / `Assigned on preview` | “Official” is necessary only at finality; “preview” can confuse first-time users. | `Order number` / `Assigned when you create the order file` |
| Order preparation | `Clear selection` | Clear, retain. | No change. |
| Order history | `Requisition Batches` | Repeats a technical word and “batch” is not explained. | `Order files` |
| Order history | `Generated order batches and archives` | “Archives” is vague. | `Orders you created, including signed copies.` |
| Signed order upload | `complete signed and stamped copy of this exact document version` | Legally useful but too dense for a checkbox. | `I confirm this is the signed and stamped copy of this order.` Keep the exact-version validation in the server response, not the checkbox copy. |

## Invoice and payment work

| Location | Current label or copy | Issue | Suggested wording |
| --- | --- | --- | --- |
| Invoice upload | `Invoice pool` | “Pool” is internal working-state terminology. | `Invoice uploads` |
| Invoice upload | `Each file remains in the pool for reconciliation.` | “Reconciliation” is finance jargon. | `Each uploaded invoice stays here until it is matched or reviewed.` |
| Invoice review | `identity, duplicate, and match signals visible together` | “Signals” is technical and hides the action. | `Check the customer, possible duplicate, and match result in one place.` |
| Invoice filter | `All records on this page` | “Records” is database terminology. | `All invoices on this page` |
| Invoice filter | `Possible duplicates` | Clear, retain. | No change. |
| Invoice filter | `Payment blocked` | Does not say what blocks payment. | `Needs correction before payment` |
| Invoice upload result | `parse failure` | Technical parser language should never be primary staff copy. | `We could not read this invoice` |
| Invoice detail | `Change applicant match` | Can sound like changing the customer rather than correcting the invoice link. | `Correct customer match` |
| Payment landing | `Payment batches start from received invoice deliveries` | Correct concept, but “batches” and “deliveries” together are dense. | `Create a payment from a received set of invoices.` |
| Payment landing | `Prepare payment from a reconciled HB delivery. Held invoices remain in that delivery but are not payable.` | Two technical terms and a negative explanation. | `Choose a received invoice set. Only matched invoices can be added to payment.` |
| Payment tab | `Ready to generate` | Generate what is unclear. | `Ready for payment file` |
| Payment tab | `Other batch` | Sounds like an error but does not explain it. | `Already in another payment` |
| Payment confirmation | `Submit payment batch for review?` | “Batch” is acceptable but outcome should be explicit. | `Send this payment for approval?` |
| Payment activity | `Batch activity` | Generic. | `Payment history` |
| Payment document states | `workbook`, `generated`, `superseded` | Document jargon visible to non-IT users. | `Payment file`, `ready to download`, `replaced by a newer file`. |

## HomeBiogas installation and commissioning

| Location | Current label or copy | Issue | Suggested wording |
| --- | --- | --- |
| HB workspace title | `HB Action` | Ambiguous. | `HB installation & commissioning` |
| HB workspace subtitle | `Installation and commissioning after an accepted signed order` | “Accepted signed order” is system language. | `Work on installation and commissioning after a signed order is confirmed.` |
| Installation action | `Mark as installed` | Clear, retain. | No change. |
| Installation action | `Report installation delay` | Clear, retain. | No change. |
| Delay note | `Pending installation comment` | Status term placed before the staff purpose. | `What is delaying installation?` |
| Installation checkbox | `Installation report submitted` | Clear, retain. | No change. |
| Commissioning note | `Pending commissioning comment` | Same issue as installation. | `What is delaying commissioning?` |
| Commissioning note | `Additional remarks` / `Shown in Master Data as CS Remarks.` | “CS Remarks” exposes a Sheet column name. | `Additional notes` / remove the Master Data column explanation. |
| Commissioning readiness | `Standard readiness date` | Policy implementation language. | `Commissioning can start on` |
| HB documents | `Signed order` and `Invoice` | Clear, retain. | No change. |
| HB history | `Activity history` | Clear, retain. | No change. |

## FarmUp, SysUp, imports, and data quality

| Location | Current label or copy | Issue | Suggested wording |
| --- | --- | --- |
| FarmUp landing | `FarmUp Worklists` | Product/source name is needed, but “worklists” can be clarified. | `FarmUp monthly uploads` |
| FarmUp editor | `Updated CSV` | File-type language before the actual task. | `Upload an updated FarmUp file` |
| FarmUp editor | `mapping`, `Apply mapping`, `target field` | Necessary concept, but technical labels can be clearer. | `Match columns`, `Save column matches`, `Portal field`. |
| FarmUp editor | `Django commits first` | Implementation detail. | `Selected rows are saved to the Portal first.` |
| FarmUp editor | `Held and unresolved rows remain` | “Unresolved” does not tell staff why. | `Rows you do not select, or rows still needing review, stay in this upload.` |
| FarmUp result | `created`, `updated`, `held`, `publication queued` | Dense system result. | `X new, Y updated, Z still awaiting review. Master Data Sheet update is queued.` |
| FarmUp repair | `Repair Sheet` | Vague and can imply deleting/rebuilding the sheet. | `Retry Master Data Sheet update` |
| FarmUp repair | `publication operation(s)` | Backend term. | `Sheet update(s)` |
| SysUp import | `reconciliation`, `commit`, `review state` | Finance/database terminology makes a simple review flow harder. | `Compare with existing customers`, `Save selected rows`, `Review result`. |
| SysUp import | `global product mapping` | Internal catalogue concept should not block staff understanding. | `Product needs Operations review` |
| Import history | `staging`, `archive operation`, `source fingerprint` | Internal process terms should not appear in routine UI. | `Uploaded file`, `file saved`, `matching file`. |
| Data-quality warning | `canonical customer`, `source provenance` | Backend data-governance terms. | `Customer record used by the Portal`, `where this value came from`. |

## Case detail, timeline, reports, settings, and technical feedback

| Location | Current label or copy | Issue | Suggested wording |
| --- | --- | --- |
| Case detail | `Customer case` | Generic and repetitive when a reference is already present. | `Case` or omit the label. |
| Case detail | `Identifiers not recorded` | Correct but passive. | `Customer ID or phone number is missing.` |
| Case detail | `TAT target unavailable` / `Target unavailable` | Technical configuration failure is shown as a case fact. | `No time target has been set for this step.` |
| Case detail | `Correction reason` | Clear only to IT/Operations; need to say when it is used. | `Why are you correcting this record?` |
| Case timeline | Repeated field-level events such as `JBL Media Uploaded` followed by individual file events | Repetitive; the timeline reads like a system log. | Group same-time uploads under `JBL visit completed` with an expandable `3 files attached` list. |
| Case timeline | `Authority: …`, `related records`, internal event families | Audit internals visible in ordinary history. | Hide from ordinary users; retain in an IT/Operations-only audit details drawer. |
| Case timeline | `Customer Field Synchronized` repeated for each imported field | Repetition obscures meaningful work. | One grouped event: `Customer details updated from FarmUp` with expandable changed fields. |
| Reports | `Curated catalogue` | Product-management wording, not a staff task. | `Available reports` |
| Reports | `Report definition`, `run`, `source`, `dimension` | Builder terminology should remain hidden because custom report building is intentionally unavailable. | Show only report title, purpose, filters, and `Open report` / `Download Excel`. |
| Settings | `Portal default`, `Open work queue first` | “Portal default” is system language. | `Start screen` / `Open this work list when the Portal starts` |
| Settings | `Configuration health`, `degraded`, `maintenance` | Suitable for IT only, but needs staff-facing status words. | IT: `System checks`; non-IT: hide entirely. Use `Needs setup` or `Needs retry`, never `degraded`. |
| Settings | `TAT targets`, `Optional minutes` | Settings need plain description. | `Time target for each step` / `Leave blank if this step has no target.` |
| Settings | `Delegation`, `approval gate`, `expires at` | Governance terms are required but can be clearer. | `Temporary approval cover`, `Approval step`, `Cover ends on`. |
| All errors | `revision conflict`, `stale revision`, `idempotency`, `validation`, `canonical` | Internal failure concepts must not be exposed as the primary message. | Explain the recovery: `This case changed while you were working. Reload it, check the latest details, then try again.` |

## Repetition and removal candidates

These items are not replacements for a single term; they should be removed or consolidated when the corresponding screen is updated.

| Location | Redundant copy | Recommended treatment |
| --- | --- | --- |
| Dashboard | Both `Operational pipeline` and `Current pipeline` | Keep one section title: `Where cases are now`. |
| Invoice pages | Header explains invoice review, then cards repeat the same match/review descriptions | Keep the instruction in the header; reserve cards for invoice-specific facts and action state. |
| Payment pages | `Payment batch`, `Batch activity`, repeated batch-state labels | Use `Payment` in titles and `Payment history` in detail; show the state once in the header. |
| FarmUp editor | Repeated Sheet publication notices after upload, commit, and repair | Keep one persistent status line with `Saved`, `Updating Sheet`, or `Sheet update needs retry`. |
| Case timeline | Separate umbrella and leaf events for the same uploaded media | Group under the parent action and make file names expandable. |
| Settings | Capability and scope explanations beside routine preferences | Hide policy/permission mechanics outside IT/Operations controls. |

## Wording that should remain precise

The following should not be simplified away because they distinguish governed business outcomes or evidence:

- `Approved`, `Declined`, `Deferred`, `Reappraisal needed`, `Installed`, and `Commissioned` as case-status values.
- `Signed order`, `Signed payment file`, `Invoice`, `Order number`, `Payment number`, and `HomeBiogas`.
- `DD-MM-YYYY` date guidance and customer-facing identifiers such as the short case reference.
- Plain-language legal confirmations that a signed/stamped scan is the complete copy of the document being submitted.

## Implementation order after approval

1. Replace shared navigation, filter, sync, and error copy first so every Portal screen becomes clearer consistently.
2. Update the dashboard, queues, invoice/payment workspaces, and HB Action screens next.
3. Group timeline events and move audit-only information behind authorized detail disclosure.
4. Apply the IT/Operations-only settings and report terminology changes without weakening role-based visibility or audit evidence.
