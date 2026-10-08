# Vehicle security agreement: supporting-document reference

Reviewed blank source: `SUPPORT LAF- Logbook CHATTEL MORTGAGE.pdf`, 5 pages, 707552 bytes.
SHA-256: `f72923199e9ce5060c8872ab82955cafcd4410eec22beba8192e8bdc12109d95`.
Catalogue identity: `jawabu_chattel_security`; document key: `chattel_security`.

## Draft preparation

Use the existing isolated environment and an active Superuser actor:

```powershell
.\.venv\Scripts\python.exe manage.py seed_origination_support_lafs --laf-root .\LAFS --laf chattel_security --actor admin
```

This is read-only by default. `--apply` is a deliberate database/Drive write,
creates an unpublished shared-value draft and never adds product eligibility.
Alignment is human-owned. Existing products, applications, files and signatures
are not migrated. A field reference is not a certified placement coordinate.

## Canonical fields

| Key | Type | Subject / scope | Source reference |
|---|---|---|---|
| `grantor_name` | `text` | grantor / application | p1: Grantor name |
| `grantor_national_id` | `national_id` | grantor / application | p1: Grantor ID |
| `grantor_postal_address` | `text` | grantor / application | p1: Grantor postal address |
| `borrower_full_name` | `text` | applicant / application | p1: Borrower name |
| `applicant_postal_address` | `text` | applicant / application | p1: Applicant Postal Address |
| `security_secured_principal` | `money` | loan / document | p1: Secured principal |
| `vehicle_description` | `text` | vehicle / application | p3: Vehicle description |
| `vehicle_type` | `text` | vehicle / application | p3: Vehicle type |
| `vehicle_registration_number` | `text` | vehicle / application | p3: Vehicle registration |
| `vehicle_year_manufactured` | `number` | vehicle / application | p3: Year of manufacture |
| `vehicle_engine_number` | `text` | vehicle / application | p3: Engine number |
| `vehicle_make` | `text` | vehicle / application | p3: Vehicle make |
| `vehicle_model` | `text` | vehicle / application | p4: Vehicle model |
| `vehicle_chassis_number` | `text` | vehicle / application | p4: Chassis number |
| `vehicle_colour` | `text` | vehicle / application | p4: Vehicle colour |
| `vehicle_registered_owner_name` | `text` | vehicle / application | p4: Registered owner |
| `pledged_assets` | `repeating_group` | application / application | p4: Security Pledged |
| `grantor_spouse_name` | `text` | grantor_spouse / application | p4: Grantor spouse |
| `security_identified_by` | `text` | document / document | p4: Identified by |
| `advocate_name` | `text` | document / document | p5: Advocate name |
| `advocate_postal_address` | `text` | document / document | p5: Advocate postal address |
| `affidavit_sworn_at` | `text` | document / document | p5: Sworn at |
| `grantor_residence_address` | `text` | grantor / application | p5: Beneficial owner residence |
| `grantor_nationality` | `text` | grantor / application | p5: Beneficial owner nationality |

## Signers and unresolved decisions

Required roles: `grantor`, `grantor_spouse`, `advocate`, `commissioner_for_oaths`.
Unsupported native roles remain publication repair tasks; they are not mapped
to an unrelated approved role. Signature dates come from exact document signing
records, never a preview clock. Identity fields needed for OTP may be additional
signing inputs, not printed blanks.

- Grantor, spouse and advocate are distinct parties, not aliases for applicant or witness.
- Execution, certification and affidavit dates belong to their exact signing/attestation events.

## Value sources and signer bindings

| Key | Source / binding | Unit / reporting period |
|---|---|---|
| `grantor_name` | entered | Not applicable |
| `grantor_national_id` | entered | Not applicable |
| `grantor_postal_address` | entered | Not applicable |
| `borrower_full_name` | calculated / `system.borrower_full_name` | Not applicable |
| `applicant_postal_address` | entered | Not applicable |
| `security_secured_principal` | entered | contract currency |
| `vehicle_description` | entered | Not applicable |
| `vehicle_type` | entered | Not applicable |
| `vehicle_registration_number` | entered | Not applicable |
| `vehicle_year_manufactured` | entered | Not applicable |
| `vehicle_engine_number` | entered | Not applicable |
| `vehicle_make` | entered | Not applicable |
| `vehicle_model` | entered | Not applicable |
| `vehicle_chassis_number` | entered | Not applicable |
| `vehicle_colour` | entered | Not applicable |
| `vehicle_registered_owner_name` | entered | Not applicable |
| `pledged_assets` | entered | Not applicable |
| Child columns | `description` (`text`), `year_of_purchase` (`number`), `serial_number` (`text`), `current_value` (`money`) | Maximum 4; minimum 1 |
| `grantor_spouse_name` | entered | Not applicable |
| `security_identified_by` | entered | Not applicable |
| `advocate_name` | entered | Not applicable |
| `advocate_postal_address` | entered | Not applicable |
| `affidavit_sworn_at` | entered | Not applicable |
| `grantor_residence_address` | entered | Not applicable |
| `grantor_nationality` | entered | Not applicable |


## Compatibility and validation

Shared keys reuse the same subject, type, source, units and repeat structure.
Local fields belong to this document instance. Required choices and row limits
are validated by the existing form service; generated values cannot be posted.
No legal attestation, approval, receipt or transfer event is invented by rendering.
The source hash and dedicated reference are checked by supporting-seed tests.
