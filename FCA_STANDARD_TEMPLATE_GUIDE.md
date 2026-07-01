# FCA Simple Staff Template Guide

Workbook: `FCA_Simple_Staff_Template.xlsx`

This workbook is intentionally simple. It has no Apps Script, no hidden setup, and only two sheets.

## Sheet 1: FCA Visits

Use this for approval/appraisal visits.

Columns:

- `FCA VISIT DATE`
- `CUSTOMER NAME`
- `PHONE`
- `COUNTY / HUB`
- `LOCATION / LANDMARK`
- `STAFF`
- `DEPOSIT`
- `APPROVAL BASIS`
- `COMMENT`
- `DECISION`

Decision options:

- `Approved`
- `Rejected`
- `Deferred`
- `Cash`
- `Under Review`

Use `Cash` when the customer chooses cash instead of the financed approval path.

## Sheet 2: FCA Collections

Use this for arrears/follow-up/collection visits.

Columns:

- `FCA VISIT DATE`
- `CUSTOMER NAME`
- `PHONE`
- `COUNTY / HUB`
- `LOCATION / LANDMARK`
- `OFFICER`
- `ARREARS`
- `AMOUNT PAID`
- `COMMENT`
- `OUTCOME`
- `NEXT COMMITMENT DATE`

Outcome options:

- `Paid`
- `Part Paid`
- `PTP`
- `Demand Issued`
- `Disconnected`
- `Reconnect After Payment`
- `Not Available`
- `Not Visited`
- `Decommission Recommended`
- `Under Review`

## Staff Rules

- Fill one customer/action per row.
- Do not merge cells inside the table.
- Do not add county or collection section rows inside the table; use filters instead.
- Use dates like `25-May-2026`.
- Use phone numbers like `254712345678` where possible.
- Keep comments short but clear.
