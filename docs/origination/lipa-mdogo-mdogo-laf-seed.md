# Lipa Mdogo Mdogo Biogas Main LAF seed

Source: `Jawabu LAF-Lipa Mdogo Mdogo NEW (2).pdf`, two pages, reviewed SHA-256
`5e5ca308bd9e5f3d44f15af1a200e28bd3cf0b688312a24390835dcfd26f9b13`.
Run `seed_origination_main_lafs --laf lipa_mdogo_mdogo`; eligibility is exactly
global product `biogas`. Document type is `lipa_mdogo_mdogo_laf`. The template is created as `primary`, `required`, and
Ready for review; no coordinates are created or published.

## Sections

`applicant_details`, `biogas_details`, `affordability`, `borrowing_details`,
`security_details`, `guarantor_details`, and the governed `commercial_terms`
section.

## Required officer fields

- `applicant_first_name` (`text`), `applicant_surname` (`text`),
  `applicant_id_number` (`national_id`), `applicant_phone` (`phone`),
  `applicant_residence_address` (`text`), `next_of_kin_name` (`text`), and
  `next_of_kin_phone` (`phone`).
- `livestock_cow_count` (`number`, minimum `0`), `land_ownership_type`
  (`choice`: `own`, `family`, `leased`), `applicant_sub_county`
  (`sub_county`), and `applicant_county` (`county`).
- `biogas_system_size` (`text`), `biogas_source` (`text`), and `biogas_brand`
  (`text`).
- `financing_plan` (`text`), `deposit_capacity_amount` (`money`, minimum
  `5000`), `comfortable_monthly_repayment_amount` (`money`), `monthly_income`
  (`money`), and `monthly_expenses` (`money`).
- `crb_loans_current` (`boolean`), `active_external_loan` (`boolean`), and
  `pledged_assets` (`repeating_group`).
- `guarantor_1_name` (`text`), `guarantor_1_id_number` (`national_id`),
  `guarantor_1_phone` (`phone`), `guarantor_1_relationship` (`text`),
  `guarantor_1_residence_location` (`text`), and `guarantor_1_years_known`
  (`text`).

## Optional officer fields

`applicant_middle_name` (`text`), `applicant_dob` (`date`), `applicant_email`
(`text`), `applicant_marital_status` (`choice`: `single`, `married`,
`divorced`, `widowed`), `applicant_other_phone` (`phone`),
`applicant_postal_address` (`text`), `applicant_postal_code` (`text`),
`applicant_town` (`text`), `applicant_housing_tenure` (`choice`: `rented`,
`owned`, `mortgage`), `employer_business_address` (`text`), `spouse_name`
(`text`), `spouse_phone` (`phone`), `applicant_sublocation` (`text`),
`applicant_residence_years` (`number`), `income_source_employment` (`boolean`),
`income_source_business` (`boolean`), `income_source_farming` (`boolean`),
`income_source_other` (`text`), `homebiogas_deposit_amount` (`money`),
`jbl_deposit_amount` (`money`), `preferred_repayment_date` (`date`), and
`external_loans` (`repeating_group`). Optional guarantor detail keys are
`guarantor_1_business_location` (`text`) and `guarantor_1_employer` (`text`).

`external_loans` uses `institution_name` (`text`), `amount_advanced` (`money`),
`date_advanced` (`date`), `repayment_period` (`text`), and
`outstanding_amount` (`money`). `pledged_assets` uses `description` (`text`),
`year_of_purchase` (`number`), `serial_number` (`text`), and `current_value`
(`money`). Both tables render through `repeating_table` placement.

## Signers and evidence

Signer roles are `borrower`, `guarantor_1`, `bro_1`, `credit_analyst`, and
`branch_manager`. Their reviewed slots are `borrower_signature`,
`borrower_date_signed`, `guarantor_1_signature`, `guarantor_1_date_signed`,
`bro_1_signature`, `bro_1_date_signed`, `credit_analyst_signature`,
`credit_analyst_date_signed`, `branch_manager_signature`, and
`branch_manager_date_signed`; slot types are `signature` and `date_signed`.

Required document evidence is `customer_photo`, `livestock_photo`,
`mpesa_statement`, `applicant_id_copy`, and `residence_location_pin`.
HomeBiogas and Jawabu recommendation narratives remain controlled workflow
outcomes; they are not editable application fields in this seed.

Checkboxes use explicit conditions such as `checked_when=own` and do not rely
on printed marks. Typography, coordinates, overflow, evidence presentation,
and all final legal review remain human-owned in the alignment builder.
