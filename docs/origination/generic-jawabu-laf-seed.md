# Generic Jawabu LAF seed reference

This document is the field-by-field reference for the reusable two-page Jawabu
loan application form seeded by
`core/services/generic_jawabu_laf_seed.py`. The Python seed contract remains the
authoritative source if documentation drifts.

## Template identity and ownership

| Item | Configuration |
|---|---|
| Source PDF | `LAFS/Jawabu LAF (2).pdf` (supplied locally and excluded from Git) |
| Seed command | `seed_generic_jawabu_laf` |
| Document type | `jawabu_generic_laf` |
| Display name | Generic Jawabu LAF |
| Template role | Reusable global primary-template family |
| Product attachment | Never automatic; an administrator explicitly assigns the published reusable template to each compatible draft product definition |
| Publication | Never automatic; calibrate and publish the reusable template before assigning it |
| PDF placement ownership | Human-owned in the Django Admin alignment builder; the seed does not create or publish coordinates |
| Deliberate exclusions | Freehand sketches and Commissioner for Oaths content are not captured as ordinary form fields |

The two printed Net Income values are intentionally independent, manually
entered canonical fields. The seed does not infer or calculate either one from
income and expenses.

## Running the seed

Dry-run:

```powershell
.\.venv\Scripts\python.exe manage.py seed_generic_jawabu_laf --actor <active-superuser>
```

Apply after reviewing the PDF digest and counts:

```powershell
.\.venv\Scripts\python.exe manage.py seed_generic_jawabu_laf --actor <active-superuser> --apply
```

Use `--pdf` only when intentionally selecting another local copy of the reviewed
form. `--apply` requires the restricted Drive media folder. Re-running against
the same PDF reuses the template and updates its editable semantic contract. It
does not attach or overwrite any product. Incompatible canonical types or
repeatable structures stop the operation rather than altering historical data.

## Form sections

| Section key | Admin/Mini App title | Purpose |
|---|---|---|
| `applicant_details` | Applicant Details | Applicant identity, household, and contact details |
| `enterprise_details` | Enterprise Details | Business location and manually declared monthly finances |
| `loan_details` | Loan Details | Requested facility, commercial terms, quote and existing borrowing in one ordered flow |
| `security_details` | Security Details | Assets pledged for the facility |
| `guarantor_details` | Guarantor Details | Required first guarantor and optional second guarantor |
`commercial_terms` remains a compatibility token for older snapshots, but new
and upgraded schemas merge those fields into `loan_details` and set
`commercial_section_key` to that section. The officer enters the amount before
the repayment tenor; the ProductVersion quote follows in the same step.

## Governed Commercial Terms contract

The seed appends Commercial Terms contract v2. The officer enters only amount
and tenor. Every other commercial value is calculated from the immutable
ProductVersion, shown read-only in the Mini App, and remains available for PDF
mapping through a system-derived canonical field.

| Canonical key | Type | Required | Validation / PDF use |
|---|---|---|---|
| `loan_amount` | `money` | Yes | Product min/max envelope; normal `text` placement |
| `repayment_tenor` | `number` | Yes | Positive whole number; ProductVersion min/max |
| `repayment_tenor_unit` | `choice` | Derived | Policy `week` or `month` |
| `contract_currency` | `choice` | Derived | Policy currency; `kes`/`KES` remains mappable |
| `contract_interest_rate_percent` | `number` | Derived | Published policy rate |
| `contract_interest_method` | `choice` | Derived | Policy `flat` or `reducing` |
| `contract_interest_rate_period` | `choice` | Derived | Policy `monthly` or `annual` |
| `contract_repayment_frequency` | `choice` | Derived | Policy `weekly`, `fortnightly`, or `monthly` |
| `installment_count` | `number` | Derived | Decimal quote schedule |
| `installment_amount` | `money` | Derived | Regular installment; `text` placement |
| `final_installment_amount` | `money` | Derived | Rounded final schedule amount |
| `financed_principal_amount` | `money` | Derived | Loan amount plus mandatory financed fees |
| `total_interest_amount` | `money` | Derived | Calculated policy interest |
| `total_repayment_amount` | `money` | Derived | Financed principal plus interest |
| `financed_fee_total` | `money` | Derived | Mandatory financed fees |
| `upfront_fee_total` | `money` | Derived | Mandatory upfront fees |
| `loan_fees` | `repeating_group` | Derived | Mandatory policy fee rows; optional fees are excluded |

Each derived `loan_fees` row contains policy-owned `fee_key`, `fee_label`,
`collection_mode`, and calculated `amount`. Amount/tenor range exceptions are
revision-bound; pricing or fee changes require a new ProductVersion.

## Canonical field mapping

For the PDF, `text` is the ordinary overlay for scalar values. Printed choice
boxes require separate `checkbox` placements with a canonical `checked_when`
code. Repeatable structures use `repeating_table` and must have their columns
calibrated in printed order. System fields do not appear in the Mini App form,
but may be mapped onto the PDF when the application/product workflow supplies
their values.

Date controls retain canonical ISO `YYYY-MM-DD` values in Django and snapshots,
while the Mini App native-picker control and PDF output display `dd-mm-yy` for
Kenya. The phone still owns the native calendar UI itself.

| PDF/form meaning | Canonical key | Section | Type / control | Required | Source / governance | Validation or choices | Recommended PDF render |
|---|---|---|---|---|---|---|---|
| Number of weeks | `number_of_weeks` | Applicant Details | `text` | Yes | User input; internal | Manual text exactly as declared | `text` |
| First name | `applicant_first_name` | Applicant Details | `text` | Yes | User input; PII | None | `text` |
| Middle name | `applicant_middle_name` | Applicant Details | `text` | No | User input; PII | None | `text` |
| Surname | `applicant_surname` | Applicant Details | `text` | Yes | User input; PII | None | `text` |
| National ID | `applicant_id_number` | Applicant Details | `national_id` | Yes | User input; PII; reporting filter | Shared Kenyan national-ID validation | `text` |
| Date of birth | `applicant_dob` | Applicant Details | `date` | Yes | User input; PII | ISO date | `text` |
| Email | `applicant_email` | Applicant Details | `text` | No | User input; PII | None | `text` |
| Marital status | `applicant_marital_status` | Applicant Details | `choice` | Yes | User input; PII; reporting dimension | `single`, `married`, `divorced`, `widowed` | One `checkbox` placement per printed option using the matching code |
| Number of children | `applicant_number_of_children` | Applicant Details | `number` | No | User input; internal | Minimum 0 | `text` |
| Other dependants | `applicant_number_of_other_dependants` | Applicant Details | `number` | No | User input; internal | Minimum 0 | `text` |
| Mobile phone | `applicant_phone` | Applicant Details | `phone` | Yes | User input; PII; reporting filter | Shared Kenyan-phone normalization | `text` |
| Alternative phone | `applicant_other_phone` | Applicant Details | `phone` | No | User input; PII | Shared Kenyan-phone normalization | `text` |
| Postal address | `applicant_postal_address` | Applicant Details | `text` | No | User input; PII | None | `text` |
| Postal code | `applicant_postal_code` | Applicant Details | `text` | No | User input; PII | None | `text` |
| Town | `applicant_town` | Applicant Details | `text` | No | User input; PII | None | `text` |
| Spouse/next-of-kin name | `applicant_next_of_kin` | Applicant Details | `text` | Yes | User input; PII | None | `text` |
| Spouse/next-of-kin ID | `applicant_next_of_kin_id` | Applicant Details | `national_id` | No | User input; PII | Shared Kenyan national-ID validation | `text` |
| Spouse/next-of-kin phone | `applicant_next_of_kin_phone` | Applicant Details | `phone` | Yes | User input; PII | Shared Kenyan-phone normalization | `text` |
| Present residence address | `applicant_residence_address` | Applicant Details | `text`, full width | Yes | User input; PII | None | `text` |
| Residence tenure | `applicant_housing_tenure` | Applicant Details | `choice` | Yes | User input; PII; reporting dimension | `rented`, `owned`, `mortgage` | One `checkbox` placement per printed option using the matching code |
| Employer/business address | `employer_business_address` | Applicant Details | `text`, full width | Yes | User input; PII | None | `text` |
| Type of business | `business_type` | Enterprise Details | `text` | Yes | User input; internal | None | `text` |
| Business location | `business_location` | Enterprise Details | `text` | Yes | User input; PII | None | `text` |
| Monthly income | `monthly_income` | Enterprise Details | `money` | Yes | User input; financial; reporting metric | Decimal money | `text` |
| Monthly business expenses | `monthly_expenses` | Enterprise Details | `money` | Yes | User input; financial; reporting metric | Decimal money | `text` |
| First/enterprise net income | `enterprise_net_income` | Enterprise Details | `money` | Yes | **Manual user input**; financial; reporting metric | Decimal money; not formula-derived | `text` |
| Monthly household expenses | `monthly_household_expenses` | Enterprise Details | `money` | Yes | User input; financial; reporting metric | Decimal money | `text` |
| Second/household net income | `household_net_income` | Enterprise Details | `money` | Yes | **Manual user input**; financial; reporting metric | Decimal money; not formula-derived | `text` |
| Amount applied for | `loan_amount` | Commercial Terms | `money` | Yes | Officer-entered; financial; reporting metric | Product policy envelope | `text` |
| Own contribution | `own_contribution` | Loan Details | `money` | Yes | User input; financial | Decimal money | `text` |
| Project cost | `project_cost` | Loan Details | `money` | Yes | User input; financial | Decimal money | `text` |
| Loan purpose | `loan_purpose` | Loan Details | `text`, full width | Yes | User input; internal | None | `text` |
| Repayment period | `repayment_period` | Legacy PDF compatibility | `text` | No new input | Rendered from `repayment_tenor` plus `repayment_tenor_unit`; retained for old snapshots/mappings | Legacy `text` placement only |
| Daily/weekly repayment amount | `daily_weekly_repayment_amount` | Legacy PDF compatibility | `money` | No new input | Rendered from `installment_amount`; retained for old snapshots/mappings | Legacy `text` placement only |
| Loans at other institutions | `external_loans` | Loan Details | `repeating_group`, full width | No | User input; financial | 0–3 rows; structure below | `repeating_table` |
| Security pledged | `pledged_assets` | Security Details | `repeating_group`, full width | Yes | User input; financial | 1–4 rows; structure below | `repeating_table` |
| Guarantor 1 name | `guarantor_1_name` | Guarantor Details | `text` | Yes | User input; PII | None | `text` |
| Guarantor 1 ID | `guarantor_1_id_number` | Guarantor Details | `national_id` | Yes | User input; PII | Shared Kenyan national-ID validation | `text` |
| Guarantor 1 phone | `guarantor_1_phone` | Guarantor Details | `phone` | Yes | User input; PII | Shared Kenyan-phone normalization | `text` |
| Guarantor 1 relationship | `guarantor_1_relationship` | Guarantor Details | `text` | Yes | User input; PII | None | `text` |
| Guarantor 1 residence | `guarantor_1_residence_location` | Guarantor Details | `text` | Yes | User input; PII | None | `text` |
| Guarantor 1 business location | `guarantor_1_business_location` | Guarantor Details | `text` | No | User input; PII | None | `text` |
| Guarantor 1 employer | `guarantor_1_employer` | Guarantor Details | `text` | No | User input; PII | None | `text` |
| Guarantor 1 years known | `guarantor_1_years_known` | Guarantor Details | `text` | Yes | User input; internal | Manual text as printed | `text` |
| Guarantor 2 name | `guarantor_2_name` | Guarantor Details | `text` | No | User input; PII | Presence triggers second-ID evidence requirement | `text` |
| Guarantor 2 ID | `guarantor_2_id_number` | Guarantor Details | `national_id` | No | User input; PII | Shared Kenyan national-ID validation | `text` |
| Guarantor 2 phone | `guarantor_2_phone` | Guarantor Details | `phone` | No | User input; PII | Shared Kenyan-phone normalization | `text` |
| Guarantor 2 relationship | `guarantor_2_relationship` | Guarantor Details | `text` | No | User input; PII | None | `text` |
| Guarantor 2 residence | `guarantor_2_residence_location` | Guarantor Details | `text` | No | User input; PII | None | `text` |
| Guarantor 2 business location | `guarantor_2_business_location` | Guarantor Details | `text` | No | User input; PII | None | `text` |
| Guarantor 2 employer | `guarantor_2_employer` | Guarantor Details | `text` | No | User input; PII | None | `text` |
| Guarantor 2 years known | `guarantor_2_years_known` | Guarantor Details | `number` | No | User input; internal | Minimum 0 | `text` |
| Product code | `product_code` | Loan Details | `text` (not an input) | No | System-derived; internal | Resolved from selected global product | `text` where printed |
| Product name | `product_name` | Loan Details | `text` (not an input) | No | System-derived; internal | Resolved from selected global product | `text` where printed |
| Loan product boxes | `loan_product` | Loan Details | `choice` (not an input) | No | System-derived; internal | `jawabu_express`, `jawabu_advantage`, `jawabu_landlord`, `jawabu_almasi`, `other` | One `checkbox` per printed product using the matching code |
| Other loan product | `loan_product_other` | Loan Details | `text` (not an input) | No | System-derived; internal | Used when canonical product choice is `other` | `text` |
| Contractual borrower full name | `borrower_full_name` | Loan Details | `text` (not an input) | No | System-derived; PII | Supplied by the application/signing context | `text` |
| Deponent full name | `deponent_full_name` | Loan Details | `text` (not an input) | No | System-derived; PII | Supplied by the signing context | `text` |
| Acknowledgement recipient | `acknowledgement_recipient_name` | Loan Details | `text` (not an input) | No | System-derived; PII | Supplied by the signing context | `text` |
| Approved amount | `approval_amount` | Loan Details | `money` (not an input) | No | System-derived; financial | Decimal money from approved terms/application | `text` |
| Amount advanced | `amount_advanced` | Loan Details | `money` (not an input) | No | System-derived; financial | Decimal money | `text` |
| Acknowledgement amount | `acknowledgement_amount` | Loan Details | `money` (not an input) | No | System-derived; financial | Decimal money | `text` |
| Installment amount | `installment_amount` | Commercial Terms | `money` | No input | System-derived from ProductVersion; financial | Decimal quote schedule | `text` |
| Interest rate | `interest_rate` | Legacy PDF compatibility | `text` (not a new input) | No | Rendered from `contract_interest_rate_percent`; frozen old schemas remain supported | `text` |
| Repayment frequency | `repayment_frequency` | Legacy PDF compatibility | `text` (not a new input) | No | Rendered from `contract_repayment_frequency`; frozen old schemas remain supported | `text` |
| Penalty rate | `penalty_rate` | Loan Details | `text` (not an input) | No | System-derived; financial | Product/application display value | `text` |
| BRO 1 name | `bro_1_name` | Loan Details | `text` (not an input) | No | System-derived; internal | Responsible staff context | `text` |
| BRO 2 name | `bro_2_name` | Loan Details | `text` (not an input) | No | System-derived; internal | Responsible staff context | `text` |
| Branch Manager name | `branch_manager_name` | Loan Details | `text` (not an input) | No | System-derived; internal | Responsible staff context | `text` |

### Repeatable table structures

`external_loans` permits zero to three manually entered rows:

| Column key | Label | Type | Required per row | Validation |
|---|---|---|---|---|
| `institution_name` | Institution | `text` | Yes | Maximum 180 characters |
| `amount_advanced` | Amount advanced | `money` | Yes | Minimum 0 |
| `date_advanced` | Date advanced | `date` | Yes | ISO date |
| `repayment_period` | Repayment period | `text` | Yes | Maximum 80 characters |
| `outstanding_amount` | Outstanding amount | `money` | Yes | Minimum 0 |

`pledged_assets` requires one to four manually entered rows:

| Column key | Label | Type | Required per row | Validation |
|---|---|---|---|---|
| `description` | Description | `text` | Yes | Maximum 240 characters |
| `year_of_purchase` | Year of purchase | `number` | Yes | 1900–2200 |
| `serial_number` | Serial number | `text` | No | Maximum 120 characters |
| `current_value` | Current value | `money` | Yes | Minimum 0 |

The alignment builder creates one `repeating_table` placement per printed table.
The product builder exposes minimum/maximum row counts and stores 1-4 Mini App
columns in `repeatable_layout.column_widths`, requiring positive percentages
totalling 100. The PDF builder independently
stores the row count and each canonical table column's `width_ratio`/`x_ratio`,
also totalling 100, so form layout and printed alignment can be tuned safely.
Configure its columns in the same order as the corresponding structure above;
do not map each possible row as unrelated scalar fields.

## Signers and slots

| Role | Required | Identity mapping | Slots |
|---|---|---|---|
| Borrower (`borrower`) | Yes | Name `applicant_first_name`; phone `applicant_phone`; ID `applicant_id_number` | One holistic verified `signature` capture is reused at `declaration_signature`, `loan_agreement_signature`, `affidavit_signature`, and `acknowledgement_signature`. The same completion fills `declaration_date_signed`, `loan_agreement_date_signed`, and `acknowledgement_date_signed` (`date_signed`). The packet cannot become fully signed until every required placement is complete. |
| Guarantor 1 (`guarantor_1`) | Yes | Name `guarantor_1_name`; phone `guarantor_1_phone`; ID `guarantor_1_id_number` | `guarantor_1_signature` (`signature`, required) |
| Guarantor 2 (`guarantor_2`) | Conditional | Name `guarantor_2_name`; phone `guarantor_2_phone`; ID `guarantor_2_id_number` | It remains in the single Guarantor Details section but is rendered in its own labelled card. Any entered Guarantor 2 value makes the core identity, evidence, and `guarantor_2_signature` completion mandatory. |
| Business Relationship Officer 1 (`bro_1`) | Yes | Authorized staff context | `bro_1_approval_signature` (`signature`, required); `bro_1_approval_date_signed` (`date_signed`, required) |
| Business Relationship Officer 2 (`bro_2`) | No | Authorized staff context | `bro_2_approval_signature` (`signature`, optional); `bro_2_approval_date_signed` (`date_signed`, optional) |
| Branch Manager (`branch_manager`) | Yes | Authorized staff context | `branch_manager_approval_signature` (`signature`, required); `branch_manager_approval_date_signed` (`date_signed`, required) |

The seed defines no stamp slot and does not treat the Commissioner for Oaths area
as a self-service signature. A governed stamp or commissioner workflow must be
designed explicitly before adding such a slot.

## Evidence requirements

| Requirement key | Label | Required | Enforcement | Validation |
|---|---|---|---|---|
| `guarantor_1_id_copy` | Guarantor 1 ID Copy | Yes | Before review | Clear document upload |
| `guarantor_2_id_copy` | Guarantor 2 ID Copy | Conditional | Before review | Required when `guarantor_2_name` is truthy |

These are application evidence requirements, not supporting document templates
and not PDF placements.
The Mini App **Take photo** action opens a live rear-camera stream through
`getUserMedia`; **Choose file** remains the separate document/photo picker.

## Calibration, publication, and product assignment

1. Open the reusable Generic Jawabu LAF template in Django Admin.
2. Open the alignment builder and place all printable required fields. **Snap
   to lines** is enabled by default; hold Alt during a gesture to bypass it.
3. Create one checkbox placement for every printed Marital Status, Residence
   Tenure, and Loan Product option, selecting the matching canonical code.
4. Configure `external_loans` and `pledged_assets` as repeating tables.
5. Place the required borrower, guarantor, BRO, and Branch Manager signer slots
   on every corresponding PDF line.
6. Save and inspect the filled sample on every page. Verify both Net Income
   values display the two independently entered values.
7. Publish the reusable template as a Superuser.
8. Open each compatible **draft** Origination Product Definition, select the
   published Generic Jawabu LAF as its primary template, and verify its product
   schema remains compatible.
9. Publish each product definition separately. Products already published are
   immutable and require an editable successor version.
10. Create a synthetic application for every assigned product and verify form
    validation, evidence, PDF preview, checkbox ticks, signer dispatch, and the
    latest signed packet before production use.
