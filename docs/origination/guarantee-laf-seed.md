# Guarantee and undertaking: supporting-document reference

Reviewed blank source: `SUPPORT LAF- GUARANTOR FORM.pdf`, 1 pages, 622484 bytes.
SHA-256: `463ae42ecc15e866f7c7edbd9052362817ed5b0e01bdf584fe8691c2c67c5901`.
Catalogue identity: `jawabu_guarantee`; document key: `guarantee`.

## Draft preparation

Use the existing isolated environment and an active Superuser actor:

```powershell
.\.venv\Scripts\python.exe manage.py seed_origination_support_lafs --laf-root .\LAFS --laf guarantee --actor admin
```

This is read-only by default. `--apply` is a deliberate database/Drive write,
creates an unpublished shared-value draft and never adds product eligibility.
Alignment is human-owned. Existing products, applications, files and signatures
are not migrated. A field reference is not a certified placement coordinate.

## Canonical fields

| Key | Type | Subject / scope | Source reference |
|---|---|---|---|
| `guarantor_1_name` | `text` | guarantor_1 / application | p1: Guarantor 1 Name |
| `guarantor_1_id_number` | `national_id` | guarantor_1 / application | p1: Guarantor 1 National ID |
| `guarantor_1_phone` | `phone` | guarantor_1 / application | p1: Guarantor 1 Phone |
| `guarantor_1_postal_address` | `text` | guarantor_1 / application | p1: Guarantor postal address |
| `guarantor_1_town` | `text` | guarantor_1 / application | p1: Guarantor town |
| `guarantor_1_email` | `text` | guarantor_1 / application | p1: Guarantor email |
| `borrower_full_name` | `text` | applicant / application | p1: Borrower name; p1: Borrower name; p1: Borrower name |
| `applicant_id_number` | `national_id` | applicant / application | p1: Applicant National ID |
| `guaranteed_amount` | `money` | loan / document | p1: Loan amount advanced / sum guaranteed |
| `guarantee_referenced_agreement_date` | `date` | document / document | p1: Referenced agreement date |
| `witness_name` | `text` | document / document | p1: Witness name |
| `witness_phone` | `phone` | document / document | p1: Witness phone |
| `witness_national_id` | `national_id` | document / document | p1: Witness ID |

## Signers and unresolved decisions

Required roles: `guarantor_1`, `witness`.
Unsupported native roles remain publication repair tasks; they are not mapped
to an unrelated approved role. Signature dates come from exact document signing
records, never a preview clock. Identity fields needed for OTP may be additional
signing inputs, not printed blanks.

- The guaranteed obligation is not the requested or disbursed amount.
- Witness identity is signing evidence; witness phone/ID are not printed blanks.

## Value sources and signer bindings

| Key | Source / binding | Unit / reporting period |
|---|---|---|
| `guarantor_1_name` | entered | Not applicable |
| `guarantor_1_id_number` | entered | Not applicable |
| `guarantor_1_phone` | entered | Not applicable |
| `guarantor_1_postal_address` | entered | Not applicable |
| `guarantor_1_town` | entered | Not applicable |
| `guarantor_1_email` | entered | Not applicable |
| `borrower_full_name` | calculated / `system.borrower_full_name` | Not applicable |
| `applicant_id_number` | entered | Not applicable |
| `guaranteed_amount` | entered | contract currency |
| `guarantee_referenced_agreement_date` | entered | Not applicable |
| `witness_name` | entered | Not applicable |
| `witness_phone` | entered | Not applicable |
| `witness_national_id` | entered | Not applicable |

- `guarantor_1`: `guarantor_1_signature` (`signature`), `guarantor_1_date_signed` (`date_signed`). Identity: `name` to `guarantor_1_name`, `phone` to `guarantor_1_phone`, `national_id` to `guarantor_1_id_number`.
- `witness`: `witness_signature` (`signature`), `witness_date_signed` (`date_signed`). Identity: `name` to `witness_name`, `phone` to `witness_phone`, `national_id` to `witness_national_id`.

## Compatibility and validation

Shared keys reuse the same subject, type, source, units and repeat structure.
Local fields belong to this document instance. Required choices and row limits
are validated by the existing form service; generated values cannot be posted.
No legal attestation, approval, receipt or transfer event is invented by rendering.
The source hash and dedicated reference are checked by supporting-seed tests.
