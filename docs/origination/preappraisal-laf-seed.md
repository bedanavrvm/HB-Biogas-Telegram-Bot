# Pre-appraisal: supporting-document reference

The [reviewed input rules](main-laf-canonical-map.md#reviewed-input-rules)
apply when preparing new drafts: email format, whole-number counts and asset
years, and birth-date limits. Existing application snapshots stay unchanged.

Reviewed blank source: `SUPPORT LAF- PRE-APPRAISAL FORM.pdf`, 1 pages, 291667 bytes.
SHA-256: `e8652cabd9bde1e5bb995d48c38c04460164fd928f51e8630ac1e742082c117e`.
Catalogue identity: `jawabu_preappraisal`; document key: `preappraisal`.

## Draft preparation

Use the existing isolated environment and an active Superuser actor:

```powershell
.\.venv\Scripts\python.exe manage.py seed_origination_support_lafs --laf-root .\LAFS --laf preappraisal --actor admin
```

This is read-only by default. `--apply` is a deliberate database/Drive write,
creates an unpublished shared-value draft and never adds product eligibility.
Alignment is human-owned. Existing products, applications, files and signatures
are not migrated. A field reference is not a certified placement coordinate.

## Canonical fields

| Key | Type | Subject / scope | Source reference |
|---|---|---|---|
| `borrower_full_name` | `text` | applicant / application | p1: Applicant name |
| `applicant_id_number` | `national_id` | applicant / application | p1: Applicant National ID |
| `applicant_phone` | `phone` | applicant / application | p1: Applicant Mobile Phone |
| `applicant_postal_address` | `text` | applicant / application | p1: Applicant Postal Address |
| `applicant_other_phone` | `phone` | applicant / application | p1: Applicant Alternative Phone |
| `applicant_email` | `text` | applicant / application | p1: Applicant Email |
| `applicant_residence_address` | `text` | applicant / application | p1: Present Residence Address |
| `business_type` | `text` | business / application | p1: Type of Business |
| `business_location` | `text` | business / application | p1: Business Location |
| `loan_purpose` | `text` | application / application | p1: Loan Purpose |
| `loan_amount` | `money` | loan / application | p1: Amount Applied For |
| `business_started_on` | `date` | business / application | p1: Business started on |
| `business_years_at_current_location` | `number` | business / application | p1: Years at this location |
| `business_has_branches` | `boolean` | business / application | p1: Other business branches |
| `business_managed_full_time` | `boolean` | business / application | p1: Managed full time |
| `business_employee_count` | `number` | business / application | p1: Employees |
| `business_good_day_sales` | `money` | business / application | p1: Good-day sales |
| `business_low_day_sales` | `money` | business / application | p1: Low-day sales |
| `business_seasonal` | `boolean` | business / application | p1: Seasonal business |
| `business_peak_periods` | `text` | business / application | p1: Busy periods |
| `business_low_periods` | `text` | business / application | p1: Low periods |
| `business_customer_stock_estimate` | `money` | business / application | p1: Applicant stock estimate |
| `business_officer_stock_estimate` | `money` | business / document | p1: Officer stock estimate |
| `business_stock_financing_history` | `textarea` | business / application | p1: How stock was financed |
| `business_challenges` | `textarea` | business / application | p1: Business challenges |
| `business_monthly_rent` | `money` | business / application | p1: Business rent |
| `preappraisal_assessment_notes` | `textarea` | application / document | p1: Officer assessment |
| `preappraisal_second_visit_recommended` | `boolean` | application / document | p1: Second visit recommended |
| `preappraisal_recommended_amount` | `money` | loan / document | p1: Officer recommended amount |
| `preappraisal_affordable_payment` | `money` | loan / application | p1: Affordable payment |
| `preappraisal_affordable_frequency` | `text` | loan / application | p1: Affordability frequency |
| `external_loans` | `repeating_group` | application / application | p1: Loans in Other Financial Institutions |

## Signers and unresolved decisions

Required roles: `borrower`, `officer`.
Unsupported native roles remain publication repair tasks; they are not mapped
to an unrelated approved role. Signature dates come from exact document signing
records, never a preview clock. Identity fields needed for OTP may be additional
signing inputs, not printed blanks.

- Printed Type and Box require owner clarification before placement.
- Supervisor/committee decisions are not officer-entered approval values.
- Photos, ID copies, statement and map pin remain evidence, not scalar text.

## Value sources and signer bindings

| Key | Source / binding | Unit / reporting period |
|---|---|---|
| `borrower_full_name` | calculated / `system.borrower_full_name` | Not applicable |
| `applicant_id_number` | entered | Not applicable |
| `applicant_phone` | entered | Not applicable |
| `applicant_postal_address` | entered | Not applicable |
| `applicant_other_phone` | entered | Not applicable |
| `applicant_email` | entered | Not applicable |
| `applicant_residence_address` | entered | Not applicable |
| `business_type` | entered | Not applicable |
| `business_location` | entered | Not applicable |
| `loan_purpose` | entered | Not applicable |
| `loan_amount` | entered | contract currency |
| `business_started_on` | entered | Not applicable |
| `business_years_at_current_location` | entered | Not applicable |
| `business_has_branches` | entered | Not applicable |
| `business_managed_full_time` | entered | Not applicable |
| `business_employee_count` | entered | Not applicable |
| `business_good_day_sales` | entered | contract currency |
| `business_low_day_sales` | entered | contract currency |
| `business_seasonal` | entered | Not applicable |
| `business_peak_periods` | entered | Not applicable |
| `business_low_periods` | entered | Not applicable |
| `business_customer_stock_estimate` | entered | contract currency |
| `business_officer_stock_estimate` | entered | contract currency |
| `business_stock_financing_history` | entered | Not applicable |
| `business_challenges` | entered | Not applicable |
| `business_monthly_rent` | entered | contract currency |
| `preappraisal_assessment_notes` | entered | Not applicable |
| `preappraisal_second_visit_recommended` | entered | Not applicable |
| `preappraisal_recommended_amount` | entered | contract currency |
| `preappraisal_affordable_payment` | entered | contract currency |
| `preappraisal_affordable_frequency` | entered | Not applicable |
| `external_loans` | entered | Not applicable |
| Child columns | `institution_name` (`text`), `amount_advanced` (`money`), `date_advanced` (`date`), `repayment_period` (`text`), `outstanding_amount` (`money`) | Maximum 3; minimum 0 |

- `borrower`: `borrower_signature` (`signature`), `borrower_date_signed` (`date_signed`). Identity: `name` to `borrower_full_name`, `phone` to `applicant_phone`, `national_id` to `applicant_id_number`.
- `officer`: `officer_signature` (`signature`), `officer_date_signed` (`date_signed`). Identity: existing authorized staff assignment.

## Compatibility and validation

Shared keys reuse the same subject, type, source, units and repeat structure.
Local fields belong to this document instance. Required choices and row limits
are validated by the existing form service; generated values cannot be posted.
No legal attestation, approval, receipt or transfer event is invented by rendering.
The source hash and dedicated reference are checked by supporting-seed tests.
