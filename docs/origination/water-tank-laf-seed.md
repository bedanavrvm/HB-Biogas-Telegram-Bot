# Water Tank Main LAF seed

Source: `Jawabu LAF-Water Tank.pdf`, two pages, SHA-256
`0ed3bb9de5f0635b99f62356e23bed704913424c5b4c44c80cc79ff37283bae8`.
Run `seed_origination_main_lafs --laf water_tank`. Eligibility is exactly
`water_tank`; document type is `water_tank_laf`; apply fails if that governed product is unavailable.

## Sections and fields

Sections are `applicant_details`, `water_tank_details`, `supplier_details`,
`loan_details`, `security_details`, `guarantor_details`, and governed
`commercial_terms`.

Applicant fields are `applicant_first_name` (`text`, required),
`applicant_middle_name` (`text`), `applicant_surname` (`text`, required),
`applicant_id_number` (`national_id`, required), `applicant_dob` (`date`),
`applicant_email` (`text`), `applicant_marital_status` (`choice`: `single`,
`married`, `divorced`, `widowed`), `applicant_phone` (`phone`, required),
`applicant_other_phone` (`phone`), `applicant_postal_address` (`text`),
`applicant_postal_code` (`text`), `applicant_town` (`text`),
`applicant_residence_address` (`text`, required), `applicant_housing_tenure`
(`choice`: `rented`, `owned`, `mortgage`), and `employer_business_address`
(`text`).

Product fields are `water_tank_capacity_litres` (`number`, required, minimum
`1`), `water_tank_source` (`text`, required), and `water_tank_brand` (`text`,
required). Both printed size boxes map to `water_tank_capacity_litres`.

Supplier fields are `supplier_name` (`text`, required),
`supplier_payment_details` (`textarea`, required), `supplier_contact_name`
(`text`, required), `supplier_contact_phone` (`phone`, required but not
printed), and `supplier_code` (`text`). `loan_purpose` is required full-width `text`.
`pledged_assets` is a required `repeating_group`/`repeating_table` using
`description` (`text`), `year_of_purchase` (`number`), `serial_number`
(`text`), and `current_value` (`money`).

Guarantor fields are `guarantor_1_name`, `guarantor_1_id_number`,
`guarantor_1_phone`, `guarantor_1_relationship`,
`guarantor_1_residence_location`, `guarantor_1_business_location`,
`guarantor_1_employer`, and `guarantor_1_years_known`; types are respectively
`text`, `national_id`, `phone`, `text`, `text`, `text`, `text`, and `text`.

## Signers and evidence

Signer roles are `borrower`, `guarantor_1`, `supplier_representative`, `bro_1`,
optional `bro_2`, and `branch_manager`. Every role has a `signature` and
`date_signed` slot: `borrower_signature`, `borrower_date_signed`,
`guarantor_1_signature`, `guarantor_1_date_signed`,
`supplier_representative_signature`, `supplier_representative_date_signed`,
`bro_1_signature`, `bro_1_date_signed`, `bro_2_signature`,
`bro_2_date_signed`, `branch_manager_signature`, and
`branch_manager_date_signed`. Supplier also has
`supplier_representative_stamp` (`stamp`).
`residence_sketch` and `delivery_location_sketch` are optional document
evidence, not text inputs.

Coordinates, duplicate-field placement, checkbox conditions, typography,
overflow, supplier stamp appearance, previews, and publication remain
human-owned in the alignment builder.
