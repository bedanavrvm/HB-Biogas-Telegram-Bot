# Invoice Finance LAF seed reference

This document is the field-by-field reference for the reviewed Invoice Finance
application form seeded by
`core/services/invoice_finance_origination_seed.py`. The Python seed contract is
authoritative if this document and the code ever disagree.

## Template identity and ownership

| Item | Configuration |
|---|---|
| Source PDF | `LAFS/INVOICE FINANCE.pdf` (supplied locally and excluded from Git) |
| Seed command | `seed_invoice_finance_origination` |
| Default global product code | `invoice_finance` |
| Template role | Product-specific primary LAF |
| Product attachment | The seed creates or replaces the editable Invoice Finance Origination Product Definition and attaches its primary template |
| Publication | Never automatic; the product definition remains a draft until an administrator calibrates and publishes it |
| PDF placement ownership | Human-owned in the Django Admin alignment builder; the seed does not create or publish coordinates |
| Supporting documents | The PDF's printed `ATTACH` checklist is deliberately ignored and creates no supporting-document assignment |

The seed requires an existing global Invoice Finance `Product` and either a
published or draft commercial `ProductVersion`. Shared canonical fields marked
**Existing shared field** below must already exist with the documented type.

## Running the seed

Run the dry-run first:

```powershell
.\.venv\Scripts\python.exe manage.py seed_invoice_finance_origination --actor <active-superuser>
```

After reviewing its proposed product/version and PDF digest, apply it:

```powershell
.\.venv\Scripts\python.exe manage.py seed_invoice_finance_origination --actor <active-superuser> --apply
```

Use `--product-code` or `--pdf` only when intentionally targeting a different
global product record or local source file. `--apply` requires the restricted
Drive media folder. Re-running the seed is idempotent for the same PDF and draft
contract: it updates mutable catalogue governance, reuses the uploaded template
where possible, and records audit events. Frozen type conflicts stop the seed
instead of silently reinterpreting existing applications.

## Form sections

| Section key | Admin/Mini App title | Purpose |
|---|---|---|
| `applicant_details` | Applicant Details | Applicant identity and contact details |
| `business_details` | Business Details | Business identity and operating details |
| `banking_details` | Banking Details | Account to receive the approved facility |
| `invoice_details` | Invoice Details | Surrendered invoice and requested advance |
| `signer_details` | Signer Details | Representatives and internal approvers |
| `acknowledgement` | Acknowledgement | Applicant receipt acknowledgement |
| `commercial_terms` | Commercial Terms | Exact officer-entered facility terms validated against ProductVersion policy |

## Governed Commercial Terms contract

The Invoice Finance seed appends the same shared Commercial Terms contract used
by other new Origination products. The LAF records what the officer entered;
the ProductVersion quote is retained separately as the validation expectation.

| Canonical key | Type | Required | Validation / rendering |
|---|---|---|---|
| `loan_amount` | `money` | Yes | Product min/max envelope; `text` overlay where printed |
| `repayment_tenor` | `number` | Yes | Positive whole number within policy unless explicitly excepted |
| `repayment_tenor_unit` | `choice` | Yes | `week` or `month` |
| `contract_currency` | `choice` | Yes | Stored code `kes`, displayed as `KES` |
| `contract_interest_rate_percent` | `number` | Yes | Compared to policy at six-decimal precision |
| `contract_interest_method` | `choice` | Yes | `flat` or `reducing` |
| `contract_interest_rate_period` | `choice` | Yes | `monthly` or `annual` |
| `contract_repayment_frequency` | `choice` | Yes | `weekly`, `fortnightly`, or `monthly` |
| `installment_count` | `number` | Yes | Positive whole number |
| `installment_amount` | `money` | Yes | Officer-entered regular installment |
| `final_installment_amount` | `money` | Yes | Schedule reconciliation |
| `financed_principal_amount` | `money` | Yes | Loan amount plus financed fees |
| `total_interest_amount` | `money` | Yes | Officer-entered total interest |
| `total_repayment_amount` | `money` | Yes | Financed principal plus interest |
| `financed_fee_total` | `money` | Yes | Sum of financed fee rows |
| `upfront_fee_total` | `money` | Yes | Sum of upfront fee rows |
| `loan_fees` | `repeating_group` | When policy has fees | Locked policy identity/collection mode; officer enters amount |

Each `loan_fees` row stores `fee_key`, `fee_label`, `collection_mode`, and
`amount`; only the amount is editable.

Money comparisons use an inclusive KES 0.01 tolerance. Internal arithmetic,
missing values, and invalid types are never exception-eligible. A Superuser
exception is bound to one exact revision and requires a reason and approval
reference.

## Canonical field mapping

`text` in the PDF-render column means a normal text overlay even when the Mini
App data type is money, date, phone, or national ID. Choice boxes require one
placement per printed option using `checkbox` plus its canonical
`checked_when` code. “Not placed” means the value supports workflow/signing but
must not be printed on this LAF.

| PDF/form meaning | Canonical key | Section | Type / Mini App control | Required | Ownership and governance | Validation or choices | Recommended PDF render |
|---|---|---|---|---|---|---|---|
| Applicant full names | `applicant_full_name` | Applicant Details | `text` | Yes | User input; PII, partial masking; aliases: Full Names, Applicant Name, Borrower Name | None | `text` |
| Application date | `application_date` | Applicant Details | `date` (not an input) | Yes | System-derived, internal; **Existing shared field** | ISO date | `text` |
| Applicant ID / National ID | `applicant_id_number` | Applicant Details | `national_id` | Yes | User input; PII, partial masking; **Existing shared field** | Shared Kenyan national-ID validation | `text` |
| Nationality | `applicant_nationality` | Applicant Details | `text` | Yes | User input; PII, partial masking | None | `text` |
| Gender: Male / Female | `applicant_gender` | Applicant Details | `choice` | Yes | User input; PII, reporting dimension | `male` = Male; `female` = Female | Two `checkbox` placements with `checked_when=male` and `checked_when=female` |
| Postal address | `applicant_postal_address` | Applicant Details | `text` | No | User input; PII, partial masking; **Existing shared field** | None | `text` |
| Email | `applicant_email` | Applicant Details | `text` | No | User input; PII, partial masking; **Existing shared field** | None | `text` |
| Applicant telephone | `applicant_phone` | Applicant Details | `phone` | Yes | User input; PII, partial masking; **Existing shared field** | Shared Kenyan-phone normalization | `text` |
| Residence location | `applicant_residence_address` | Applicant Details | `text` | Yes | User input; PII, partial masking; **Existing shared field** | None | `text` |
| Housing: Rented / Owned | `applicant_housing_tenure` | Applicant Details | `choice` | Yes | User input; PII, reporting dimension | `rented` = Rented; `owned` = Owned | Two `checkbox` placements using the matching canonical code |
| Office/business location | `business_location` | Business Details | `text` | Yes | User input; internal, unmasked; alias: Office Location | None | `text` |
| Office/business telephone | `business_phone` | Business Details | `phone` | No | User input; PII, partial masking; alias: Office Telephone | Shared Kenyan-phone normalization | `text` |
| Business name | `business_name` | Business Details | `text` | Yes | User input; internal, unmasked; reporting dimension | None | `text` |
| Registration number | `business_registration_number` | Business Details | `text` | No | User input; restricted, partial masking | None | `text` |
| Business PIN | `business_tax_pin` | Business Details | `text` | Yes | User input; restricted, partial masking; aliases: Business PIN, PIN | None | `text` |
| Bank name | `disbursement_bank_name` | Banking Details | `text` | Yes | User input; restricted, partial masking | None | `text` |
| Bank branch | `disbursement_bank_branch` | Banking Details | `text` | Yes | User input; restricted, partial masking | None | `text` |
| Account name | `disbursement_bank_account_name` | Banking Details | `text` | Yes | User input; restricted, partial masking | None | `text` |
| Account number | `disbursement_bank_account_number` | Banking Details | `text` | Yes | User input; restricted, partial masking | None | `text` |
| Surrendered invoice face value | `invoice_face_value` | Invoice Details | `money` | Yes | User input; financial, partial masking; reporting metric | Decimal money | `text` |
| Invoice due/payable date | `invoice_due_date` | Invoice Details | `date` | Yes | User input; financial, partial masking; reporting filter | ISO date | `text` |
| Loan amount requested | `loan_amount` | Commercial Terms | `money` | Yes | Officer-entered; financial, partial masking; reporting metric; **Existing shared field** | Product policy envelope | `text` |
| Advance percentage | `invoice_advance_rate_percent` | Invoice Details | `number` | Yes | User input; financial, partial masking; reporting metric | Minimum 0; maximum 100 | `text` |
| Approved facility amount | `approval_amount` | Invoice Details | `money` | Yes | User input; financial, partial masking; reporting metric; **Existing shared field** | Decimal money | `text` |
| Invoice payer representative name | `invoice_payer_representative_name` | Signer Details | `text` | Yes | User input; PII, partial masking | None | `text` where the representative name is printed |
| Invoice payer representative OTP phone | `invoice_payer_representative_phone` | Signer Details | `phone` | Yes | User input; PII, partial masking; signing-delivery field | Valid mapped Kenyan mobile phone | **Not placed** |
| Business Relationship Officer name | `bro_1_name` | Signer Details | `text` (not an input) | Yes | System-derived, internal, unmasked; **Existing shared field** | Resolved from the responsible officer | `text` |
| Management approver name | `management_approver_name` | Signer Details | `text` | Yes | User input; internal, unmasked | None | `text` |
| Amount acknowledged as received | `acknowledgement_amount` | Acknowledgement | `money` | Yes | User input; financial, partial masking; reporting metric; **Existing shared field** | Decimal money | `text` |

The seed does not calculate the advance percentage, approved amount, or
acknowledgement amount from other fields. Commercial values are also entered by
the officer; the independent policy quote is used for readiness and audit, not
as a silent replacement.

## Signers and slots

Signer slots are separate from canonical data-field boxes. Add each slot from
the Signer Slots list in the alignment builder and place it on every matching
signature/date line.

| Role | Required | Identity mapping | Slot key | Slot type | Required |
|---|---|---|---|---|---|
| Borrower (`borrower`) | Yes | Name `applicant_full_name`; phone `applicant_phone`; ID `applicant_id_number` | `declaration_signature` | `signature` | Yes |
| Borrower (`borrower`) | Yes | Same packet signer | `declaration_date_signed` | `date_signed` | Yes |
| Borrower (`borrower`) | Yes | Same packet signer | `acknowledgement_signature` | `signature` | Yes |
| Borrower (`borrower`) | Yes | Same packet signer | `acknowledgement_date_signed` | `date_signed` | Yes |
| Invoice Payer Representative (`invoice_payer_representative`) | Yes | Name `invoice_payer_representative_name`; phone `invoice_payer_representative_phone` | `invoice_payer_approval_signature` | `signature` | Yes |
| Invoice Payer Representative (`invoice_payer_representative`) | Yes | Same packet signer | `invoice_payer_approval_date_signed` | `date_signed` | Yes |
| Business Relationship Officer (`bro_1`) | Yes | Name `bro_1_name`; internal staff authorization applies | `bro_approval_signature` | `signature` | Yes |
| Business Relationship Officer (`bro_1`) | Yes | Same staff signer | `bro_approval_date_signed` | `date_signed` | Yes |
| Management Approver (`management_approver`) | Yes | Name `management_approver_name`; staff authorization applies | `management_approval_signature` | `signature` | Yes |
| Management Approver (`management_approver`) | Yes | Same staff signer | `management_approval_date_signed` | `date_signed` | Yes |

This seed defines no stamp slot. Add one only after the legal/business owner has
confirmed the exact stamp role and the application supports that governed role;
do not substitute an ordinary field box for a signature or stamp.

## Calibration and publication checklist

1. Open the resulting draft Origination Product Definition and its primary LAF
   alignment builder.
2. Place every required printable field. Do not place the OTP-only phone field.
3. For Gender and Housing Tenure, draw a separate checkbox box over each printed
   choice and select the documented `checked_when` code.
4. Place every required signature and signing-date slot.
5. Save the draft, select representative filled-sample values, and verify text,
   money, dates, and check marks land inside the intended PDF boxes.
6. Confirm publish readiness reports no missing canonical identity field or
   signer slot.
7. Publish the product definition as a Superuser. Existing applications keep
   their frozen earlier schema/template snapshots.
8. Create a synthetic application, preview the complete packet, and verify each
   remote signer receives only their own link and OTP before production use.
