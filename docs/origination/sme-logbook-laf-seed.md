# SME-LOGBOOK Main LAF seed

Source: `SME-LOGBOOK LAF.pdf`, four pages, SHA-256
`4e4a95c814e1ac64058e39510658f86f3bbad770b5ab5961a0f782167a697416`.
Run `seed_origination_main_lafs --laf sme_logbook`. Eligibility is strictly
`logbook`; document type is `sme_logbook_laf`; the seed does not infer eligibility for `business`.

## Sections

`applicant_details`, `business_details`, `employment_details`, `loan_details`,
`business_appraisal`, `household_budget`, `security_details`,
`referee_details`, `guarantor_details`, `referral_details`, and governed
`commercial_terms`.

## Applicant, business, and employment

The shared applicant contract uses `applicant_first_name` (`text`, required),
`applicant_middle_name` (`text`), `applicant_surname` (`text`, required),
`applicant_id_number` (`national_id`, required), `applicant_dob` (`date`),
`applicant_email` (`text`), `applicant_marital_status` (`choice`: `single`,
`married`, `divorced`, `widowed`), `applicant_phone` (`phone`, required),
`applicant_other_phone` (`phone`), `applicant_postal_address` (`text`),
`applicant_postal_code` (`text`), `applicant_town` (`text`),
`applicant_residence_address` (`text`, required), `applicant_housing_tenure`
(`choice`: `rented`, `owned`, `mortgage`), and `employer_business_address`
(`text`).

Business fields are `business_name` (`text`, required), `business_type`
(`text`, required), `business_license_number` (`text`), `business_location`
(`text`, required), `business_location_block` (`text`),
`business_premises_tenure` (`choice`, required: `owned`, `rented`),
`business_monthly_rent` (`money`), `business_years_at_current_location`
(`number`), `business_previous_location` (`text`), `business_employee_count`
(`number`), `business_full_time_employee_count` (`number`), and
`business_casual_employee_count` (`number`). All numeric counts have minimum
`0`; location history remains optional.

Employment fields are `employer_name` (`text`), `employment_start_date`
(`date`), `employment_position` (`text`), `employment_type` (`choice`:
`permanent`, `contract`), `employment_contract_end_date` (`date`),
`gross_monthly_salary` (`money`), and `net_monthly_salary` (`money`).

## Facility and appraisals

Required facility inputs are `comfortable_monthly_repayment_amount` (`money`),
`loan_purpose` (`text`, full width), `project_cost` (`money`), and `own_contribution`
(`money`). `external_loans` is an optional `repeating_group` rendered as a
`repeating_table` with `institution_name` (`text`), `amount_advanced`
(`money`), `date_advanced` (`date`), `repayment_period` (`text`), and
`outstanding_amount` (`money`).

Business appraisal inputs are `business_sales_amount` (`money`, required),
`business_other_income_lines` (`repeating_group`) with child `source` (`text`)
and `amount` (`money`), `business_purchases_amount` (`money`, required),
`business_rent_expense`, `business_payroll_expense`,
`business_utilities_expense`, and `business_other_expense` (all optional
`money`). `business_total_income`, `business_total_expenses`, and
`business_net_surplus` are system-derived `money` fields.

Household inputs are `household_spouse_net_salary`,
`household_pension_income`, `household_other_income`, `household_rent_expense`,
`household_school_fees_expense`, `household_transport_expense`,
`household_utilities_expense`, `household_food_expense`,
`household_other_loan_repayment`, `household_medical_expense`, and
`household_entertainment_expense` (optional `money`).
`household_total_income`, `household_total_expenses`, and
`household_net_surplus` are system-derived `money` fields. Officers never type
the printed totals or surplus/deficit values.

## Collateral, referee, guarantors, and referral

`manufactured_collateral_assets` is a required `repeating_group` and
`repeating_table` with `description` (`text`), `year_of_manufacture` (`number`),
`serial_number` (`text`), and `current_value` (`money`). It is intentionally
distinct from `pledged_assets.year_of_purchase`.

Referee inputs are `referee_name` (`text`, required), `referee_address`
(`text`), `referee_email` (`text`), `referee_phone` (`phone`, required), and
`referee_relationship` (`text`, required).

The two guarantors reuse `guarantor_1_name`, `guarantor_1_id_number`,
`guarantor_1_phone`, `guarantor_1_relationship`,
`guarantor_1_residence_location`, `guarantor_1_business_location`,
`guarantor_1_employer`, `guarantor_1_years_known`, and matching
`guarantor_2_name`, `guarantor_2_id_number`, `guarantor_2_phone`,
`guarantor_2_relationship`, `guarantor_2_residence_location`,
`guarantor_2_business_location`, `guarantor_2_employer`,
`guarantor_2_years_known`. Types remain the reviewed shared `text`,
`national_id`, `phone`, and `number` contracts; signer identity fields are
required even where the PDF expects the ID only as an attachment.

Referral inputs are `referral_source` (`choice`: `jawabu_staff`,
`advertisement`, `social_media`, `marketing_contact`, `friend_family`,
`print_media`, `agent`), `referral_agent_name` (`text`), and
`referral_agent_id_number` (`national_id`).

## Signers, evidence, and calibration

Signer roles are `borrower`, `guarantor_1`, `guarantor_2`, `bro_1`, `bro_2`,
`branch_manager`, and `management_approver`. Each has a reviewed `signature`
and `date_signed` slot: `borrower_signature`, `borrower_date_signed`,
`guarantor_1_signature`, `guarantor_1_date_signed`, `guarantor_2_signature`,
`guarantor_2_date_signed`, `bro_1_signature`, `bro_1_date_signed`,
`bro_2_signature`, `bro_2_date_signed`, `branch_manager_signature`,
`branch_manager_date_signed`, `management_approver_signature`, and
`management_approver_date_signed`.

Evidence requirements are `mpesa_statement_12_months`,
`bank_statement_6_months`, conditional `payslips_2_months`,
`guarantor_1_id_copy`, and `guarantor_2_id_copy`, all of type `document` and
enforced at `review`.

The fixed printed `No. 3096` is not data. The alignment must white-out that
value and place system `reference_number`; it must remain visible in preview
before activation is allowed. Coordinates, whiteout geometry, typography,
overflow, signer placement, and publication remain human-owned.
