# Vehicle transfer: supporting-document reference

Reviewed blank source: `SUPPORT LAF- Logbook TRANSFER FORM.pdf`, 2 pages, 110836 bytes.
SHA-256: `6ac34912b4220bbc17f134509af90dbff6cd1bdeaac0220356001295328779cd`.
Catalogue identity: `jawabu_vehicle_transfer`; document key: `vehicle_transfer`.

## Draft preparation

Use the existing isolated environment and an active Superuser actor:

```powershell
.\.venv\Scripts\python.exe manage.py seed_origination_support_lafs --laf-root .\LAFS --laf vehicle_transfer --actor admin
```

This is read-only by default. `--apply` is a deliberate database/Drive write,
creates an unpublished shared-value draft and never adds product eligibility.
Alignment is human-owned. Existing products, applications, files and signatures
are not migrated. A field reference is not a certified placement coordinate.

## Canonical fields

| Key | Type | Subject / scope | Source reference |
|---|---|---|---|
| `vehicle_registration_number` | `text` | vehicle / application | p1: Vehicle registration |
| `vehicle_make` | `text` | vehicle / application | p1: Vehicle make |
| `vehicle_body_type` | `text` | vehicle / application | p1: Vehicle body type |
| `vehicle_chassis_number` | `text` | vehicle / application | p1: Chassis number |
| `vehicle_engine_number` | `text` | vehicle / application | p1: Engine number |
| `vehicle_insurance_provider` | `text` | vehicle / application | p1: Third-party insurer |
| `seller_name` | `text` | seller / application | p1: Seller name |
| `seller_national_id` | `national_id` | seller / application | p1: Seller ID |
| `seller_postal_address` | `text` | seller / application | p1: Seller postal address |
| `seller_kra_pin` | `text` | seller / application | p1: Seller KRA PIN |
| `proposed_owner_name` | `text` | proposed_owner / application | p1: Proposed Owner name |
| `proposed_owner_national_id` | `national_id` | proposed_owner / application | p1: Proposed Owner ID |
| `proposed_owner_postal_address` | `text` | proposed_owner / application | p1: Proposed Owner postal address |
| `proposed_owner_kra_pin` | `text` | proposed_owner / application | p1: Proposed Owner KRA PIN |
| `proposed_owner_phone` | `phone` | proposed_owner / application | p1: New owner phone |
| `proposed_owner_occupation` | `text` | proposed_owner / application | p1: New owner occupation |
| `proposed_owner_employer` | `text` | proposed_owner / application | p1: New owner employer |
| `vehicle_transfer_fee` | `money` | document / document | p1: Transfer fee |

## Signers and unresolved decisions

Required roles: `seller`, `proposed_owner`.
Unsupported native roles remain publication repair tasks; they are not mapped
to an unrelated approved role. Signature dates come from exact document signing
records, never a preview clock. Identity fields needed for OTP may be additional
signing inputs, not printed blanks.

- Company/institution applicants are outside this rollout.
- Printed official-use boxes and the malformed location label remain unmapped.
- Proposed owner is not the registered owner until authoritative transfer evidence exists.

## Value sources and signer bindings

| Key | Source / binding | Unit / reporting period |
|---|---|---|
| `vehicle_registration_number` | entered | Not applicable |
| `vehicle_make` | entered | Not applicable |
| `vehicle_body_type` | entered | Not applicable |
| `vehicle_chassis_number` | entered | Not applicable |
| `vehicle_engine_number` | entered | Not applicable |
| `vehicle_insurance_provider` | entered | Not applicable |
| `seller_name` | entered | Not applicable |
| `seller_national_id` | entered | Not applicable |
| `seller_postal_address` | entered | Not applicable |
| `seller_kra_pin` | entered | Not applicable |
| `proposed_owner_name` | entered | Not applicable |
| `proposed_owner_national_id` | entered | Not applicable |
| `proposed_owner_postal_address` | entered | Not applicable |
| `proposed_owner_kra_pin` | entered | Not applicable |
| `proposed_owner_phone` | entered | Not applicable |
| `proposed_owner_occupation` | entered | Not applicable |
| `proposed_owner_employer` | entered | Not applicable |
| `vehicle_transfer_fee` | entered | contract currency |


## Compatibility and validation

Shared keys reuse the same subject, type, source, units and repeat structure.
Local fields belong to this document instance. Required choices and row limits
are validated by the existing form service; generated values cannot be posted.
No legal attestation, approval, receipt or transfer event is invented by rendering.
The source hash and dedicated reference are checked by supporting-seed tests.
