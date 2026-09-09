# Micro Asset Main LAF seed

Source: `Jawabu LAF-Micro Asset Loan.pdf`, two pages, SHA-256
`da128ee33a9052531976f2cb15756dd161dc44f747daa111527184a58bc756eb`.
Run `seed_origination_main_lafs --laf micro_asset`. Eligibility is exactly
`micro_asset`; document type is `micro_asset_laf`; the independent `primary`/`required` template remains
unpublished until visually calibrated.

## Sections and fields

Sections are `applicant_details`, `supplier_details`, `loan_details`,
`security_details`, `guarantor_details`, and governed `commercial_terms`.

Required applicant inputs are `applicant_first_name` (`text`),
`applicant_surname` (`text`), `applicant_id_number` (`national_id`),
`applicant_phone` (`phone`), and `applicant_residence_address` (`text`). Shared
optional inputs are `applicant_middle_name` (`text`), `applicant_dob` (`date`),
`applicant_email` (`text`), `applicant_marital_status` (`choice`: `single`,
`married`, `divorced`, `widowed`), `applicant_other_phone` (`phone`),
`applicant_postal_address` (`text`), `applicant_postal_code` (`text`),
`applicant_town` (`text`), `applicant_housing_tenure` (`choice`: `rented`,
`owned`, `mortgage`), and `employer_business_address` (`text`).

Supplier/asset inputs are `supplier_name` (`text`, required),
`supplier_payment_details` (`textarea`, required), `supplier_contact_name`
(`text`, required), `supplier_contact_phone` (`phone`, required but not
printed), `supplier_code` (`text`), `asset_item_purchased` (`text`, required),
`asset_purchase_price` (`money`, required, minimum `0`), and `asset_use_type`
(`choice`, required: `home`, `commercial`). `loan_purpose` is required `text`
and uses a full-width control.

`pledged_assets` is a required `repeating_group` rendered as a
`repeating_table` with `description` (`text`), `year_of_purchase` (`number`),
`serial_number` (`text`), and `current_value` (`money`). Guarantor keys are the
shared `guarantor_1_name`, `guarantor_1_id_number`, `guarantor_1_phone`,
`guarantor_1_relationship`, `guarantor_1_residence_location`,
`guarantor_1_business_location`, `guarantor_1_employer`,
`guarantor_1_years_known`, and equivalent `guarantor_2_name`,
`guarantor_2_id_number`, `guarantor_2_phone`, `guarantor_2_relationship`,
`guarantor_2_residence_location`, `guarantor_2_business_location`,
`guarantor_2_employer`, `guarantor_2_years_known`. The first guarantor identity
is required; the second is optional.

## Signers, evidence, and calibration

Signer roles are `borrower`, `guarantor_1`, optional `guarantor_2`,
`supplier_representative`, `bro_1`, optional `bro_2`, and `branch_manager`.
Reviewed slots are `borrower_signature`, `borrower_date_signed`,
`guarantor_1_signature`, `guarantor_1_date_signed`, `guarantor_2_signature`,
`guarantor_2_date_signed`, `supplier_representative_signature`,
`supplier_representative_date_signed`, `supplier_representative_stamp`,
`bro_1_signature`, `bro_1_date_signed`, `bro_2_signature`,
`bro_2_date_signed`, `branch_manager_signature`, and
`branch_manager_date_signed`. Slot types are `signature`, `date_signed`, and
supplier `stamp`.
The supplier OTP identity comes from `supplier_contact_name` and
`supplier_contact_phone`.

`residence_sketch` is optional document evidence. The printed “tank delivery”
sketch label is a source-template defect and intentionally has no canonical
field. It must be acknowledged during preview review. Coordinates, typography,
checkbox conditions, stamp appearance, and publication remain human-owned.
