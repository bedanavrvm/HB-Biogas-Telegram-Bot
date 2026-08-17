# IMAB Customer API Field Checklist

## Purpose

Use this checklist to confirm which customer-level fields are available in existing IMAB reports before agreeing the first API contract.

For each field, record:

- whether it is available;
- the exact IMAB report and column name;
- its format or allowed values; and
- any clarification needed from the IMAB team.

Version 1 is limited to customer-level data. Loan accounts, repayment schedules, balances, arrears, and transactions are reserved for a future integration phase.

## Existing Customers Without Loans report

These fields are already consumed by the current controlled System Export workflow.

| Current report field | Current use in the Portal | Confirmed in report | Exact IMAB column name | Notes |
|---|---|---:|---|---|
| Customer ID | Stable IMAB customer number and identity matching | Yes | Customer ID | Confirm whether this value is permanent and never reused. |
| Name | IMAB display/legal name used in payment documents | Yes | Name | Confirm whether this is the legal name and whether separate name components exist. |
| Mobile No | Exact customer matching and primary phone history | Yes | Mobile No | Confirm country-code format and whether the number is verified. |
| ID NO | Exact identity matching and data-quality review | Yes | ID NO | Confirm supported ID types and whether leading zeros are preserved. |
| Branch | System branch and payment-document branch | Yes | Branch | Request a stable branch code in addition to the label. |
| Loan Officer | IMAB-assigned loan officer | Yes | Loan Officer | Request a stable officer ID or code in addition to the name. |
| Product Name | Product shown in payment documents | Yes | Product Name | Request a stable product code in addition to the label. Loan-level product history is deferred. |
| LGF Balance | Currently imported as the JBL-side deposit value | Yes | LGF Balance | Must be clarified: a current balance is not necessarily the total amount paid. |

## Additional customer fields to check

Complete the last four columns while reviewing IMAB reports.

| Priority | Proposed API key | Business meaning | Expected type / format | Available in IMAB? | IMAB report name | Exact IMAB column name | Findings / notes |
|---|---|---|---|---:|---|---|---|
| Required | `id_type` | Type of identity document associated with `ID NO` | Controlled value, such as `national_id`, `passport`, `alien_id`, or `business_registration` |  |  |  |  |
| Required | `secondary_mobile_no` | Alternative customer phone number | E.164 preferred, for example `+2547...` |  |  |  |  |
| Required | `customer_status` | Current IMAB customer state | Documented enumeration such as active, inactive, blocked, or closed |  |  |  |  |
| Required | `customer_type` | Legal/customer classification | Documented enumeration such as individual, business, or group |  |  |  |  |
| Required | `branch_code` | Stable branch identifier that survives branch relabeling | String/code |  |  |  |  |
| Required | `loan_officer_id` | Stable IMAB identifier for the assigned loan officer | String/code |  |  |  |  |
| Required | `product_code` | Stable code corresponding to Product Name | String/code |  |  |  |  |
| Required | `created_at` | Date and time the customer was created in IMAB | ISO 8601 timestamp with timezone |  |  |  |  |
| Required | `updated_at` | Date and time of the latest material IMAB customer update | ISO 8601 timestamp with timezone |  |  |  |  |
| Required | `record_version` | Version used to detect changed or stale records | Increasing integer, opaque version, or ETag |  |  |  |  |
| Required | `is_deleted` | Indicates that an IMAB customer was removed or retired | Boolean |  |  |  | Prefer this when IMAB uses soft deletion. |
| Required | `deactivated_at` | When an inactive/deleted customer ceased being active | ISO 8601 timestamp with timezone or null |  |  |  | May be used instead of, or alongside, `is_deleted`. |
| Useful | `legal_name` | Official customer name when `Name` is only a display name | String |  |  |  | Do not request if `Name` is already the authoritative legal name. |
| Useful | `first_name` | Structured first/given name | String |  |  |  | Optional if IMAB only stores a reliable full legal name. |
| Useful | `middle_name` | Structured middle name | String or null |  |  |  |  |
| Useful | `last_name` | Structured surname/family name | String |  |  |  |  |
| Useful | `email_address` | Customer email for future controlled communication | Valid email string or null |  |  |  | Request only if reliably maintained. |
| Useful | `mobile_verified_at` | When the primary phone was verified | ISO 8601 timestamp with timezone or null |  |  |  | Prefer a timestamp over a free-text Yes/No flag. |
| Useful | `kyc_status` | Summary of IMAB KYC completion/review state | Documented enumeration |  |  |  | Request status only, not copies of KYC documents. |
| Useful | `kyc_last_reviewed_at` | Last completed KYC review | ISO 8601 timestamp with timezone or null |  |  |  |  |
| Useful | `kyc_expiry_at` | Date on which the current KYC review expires | ISO 8601 date/timestamp or null |  |  |  |  |

## LGF fields requiring clarification

The existing report exposes only `LGF Balance`. The Portal currently uses that value as the JBL-side deposit in payment documents. This assumption should not be carried into the API unless IMAB confirms that the balance always equals the total deposit received for the relevant customer.

| Priority | Proposed API key | Question for IMAB | Expected type / format | Available? | IMAB report / column | IMAB explanation |
|---|---|---|---|---:|---|---|
| Required | `lgf_account_id` | Is there a stable customer-level LGF account identifier? | String/code |  |  |  |
| Required | `lgf_currency` | Which currency applies to all LGF amounts? | ISO 4217 code, normally `KES` |  |  |  |
| Required | `lgf_current_balance` | What amount is currently held in the LGF account? | Decimal string with two decimal places |  |  |  |
| Required | `lgf_total_amount_received` | What cumulative LGF amount has JBL actually received from this customer? | Decimal string with two decimal places |  |  |  |
| Useful | `lgf_last_credit_amount` | What was the most recent LGF credit amount? | Decimal string with two decimal places or null |  |  |  |
| Useful | `lgf_last_credit_at` | When was the latest LGF credit posted? | ISO 8601 timestamp with timezone or null |  |  |  |

### LGF decision to record

- [ ] IMAB confirms `LGF Balance` means current account balance only.
- [ ] IMAB confirms `LGF Balance` means total amount deposited/received.
- [ ] IMAB can provide both current balance and cumulative amount received.
- [ ] IMAB can identify which customer-level LGF account the figures belong to.
- [ ] The value can be used in payment documents without a loan-account identifier.

Record the agreed definition:

> _Add the IMAB team's confirmed LGF definition here._

## API capability checklist

These are API contract requirements rather than customer fields.

| Capability | Available? | IMAB endpoint / parameter | Findings / notes |
|---|---:|---|---|
| Lookup by Customer ID |  |  |  |
| Lookup by ID number and ID type |  |  |  |
| Cursor-based pagination |  |  |  |
| Filter records updated after a supplied timestamp |  |  | Prefer an `updated_since` or equivalent parameter. |
| Response-level `generated_at` or `as_of` timestamp |  |  |  |
| Per-record `updated_at` value |  |  |  |
| Per-record version or ETag |  |  |  |
| Explicit nulls for unavailable values |  |  | Avoid ambiguous empty strings and omitted keys. |
| Documented status/code enumerations |  |  | Include customer, ID-type, branch, officer, and product codes. |
| Stable identifiers when labels change |  |  |  |
| Soft-deletion/inactivation indicator |  |  |  |
| Documented rate limits |  |  | Include response headers if available. |
| Retry guidance for `429` and transient `5xx` responses |  |  |  |
| Test/sandbox environment |  |  | Must contain synthetic data only. |

## Fields not requested in version 1

Do not request these until a defined Portal workflow needs them:

- identity-document images or scans;
- customer photographs or signatures;
- passwords, PINs, authentication secrets, or security answers;
- internal IMAB comments or unrestricted staff notes;
- credit-scoring inputs, model outputs, or bureau reports;
- precise home/business addresses when the existing Portal location data is sufficient;
- loan accounts, approved/disbursed amounts, repayment schedules, balances, arrears, or transactions.

## Source-of-truth boundary

### IMAB-owned customer data

- IMAB customer number and customer-record status;
- IMAB legal/display name;
- IMAB identity and phone values, subject to controlled reconciliation;
- stable branch, officer, and product assignments;
- clearly defined customer-level LGF values; and
- IMAB creation, modification, version, and deactivation metadata.

### Django-owned operational data

- Portal visits and field evidence;
- workflow states, decisions, approvals, and conditions;
- operational comments and audit events;
- order, invoice, requisition, and payment workflow state; and
- staff roles, branch access, and maker-checker controls.

IMAB updates must be reconciled and audit-logged. They must not silently overwrite Django-owned workflow or operational data.

## Future loan API phase

The customer API must expose a stable Customer ID that can later link to separate loan-account endpoints. The future phase may cover:

- loan application and account identifiers;
- approval and disbursement dates and amounts;
- product version and commercial terms;
- installment frequency and amount;
- first, next, and final repayment dates;
- outstanding principal, interest, fees, and total balance;
- arrears, days past due, PAR classification, and account status; and
- repayment schedules and immutable transaction identifiers.

None of these loan-level fields are required for the customer API v1 decision.

## IMAB review sign-off

| Item | Value |
|---|---|
| IMAB contact |  |
| Reports reviewed |  |
| Review date |  |
| Customer API fields confirmed |  |
| Fields unavailable |  |
| Fields requiring clarification |  |
| Agreed next action |  |

