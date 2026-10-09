# Logbook offer: supporting-document reference

The [reviewed input rules](main-laf-canonical-map.md#reviewed-input-rules)
apply when preparing new drafts: email format, whole-number counts and asset
years, and birth-date limits. Existing application snapshots stay unchanged.

Reviewed blank source: `SUPPORT LAF- Logbook Offer Letter .pdf`, 4 pages, 622272 bytes.
SHA-256: `a95635785bfd8b253c6b4196c399626d1dff82a20c0b6bba48d46bd72b8a82bf`.
Catalogue identity: `jawabu_logbook_offer`; document key: `logbook_offer`.

## Draft preparation

Use the existing isolated environment and an active Superuser actor:

```powershell
.\.venv\Scripts\python.exe manage.py seed_origination_support_lafs --laf-root .\LAFS --laf logbook_offer --actor admin
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
| `reference_number` | `text` | application / application | p1: Offer reference |
| `application_date` | `date` | application / application | p2: Application date |
| `financed_principal_amount` | `money` | application / application | p2: Contract principal; p2: Contract principal; p2: Contract principal |
| `installment_amount` | `money` | application / application | p2: Installment amount |
| `installment_count` | `number` | application / application | p2: Installment count |
| `contract_interest_rate_percent` | `number` | application / application | p2: Contract interest rate |
| `vehicle_registration_number` | `text` | vehicle / application | p2: Vehicle registration |
| `offer_penalty_rate_percent` | `number` | loan / document | p2: Offer penalty rate |
| `offer_processing_fee_rate_percent` | `number` | loan / document | p2: Offer processing fee rate |
| `offer_risk_fund_rate_percent` | `number` | loan / document | p2: Offer risk fund rate |

## Signers and unresolved decisions

Required roles: `borrower`, `witness`, `branch_manager`, `management_approver`.
Unsupported native roles remain publication repair tasks; they are not mapped
to an unrelated approved role. Signature dates come from exact document signing
records, never a preview clock. Identity fields needed for OTP may be additional
signing inputs, not printed blanks.

- Printed working-capital purpose and fixed penalty clause require compliance review.
- Fee/penalty blanks are not inferred from total fees or interest.
- Approval sequence and authorized-signatory authority must be explicitly confirmed.

## Value sources and signer bindings

| Key | Source / binding | Unit / reporting period |
|---|---|---|
| `borrower_full_name` | calculated / `system.borrower_full_name` | Not applicable |
| `applicant_id_number` | entered | Not applicable |
| `applicant_phone` | entered | Not applicable |
| `applicant_postal_address` | entered | Not applicable |
| `reference_number` | calculated / `system.reference_number` | Not applicable |
| `application_date` | calculated / `system.application_date` | Not applicable |
| `financed_principal_amount` | calculated / `quote.financed_principal_amount` | contract currency |
| `installment_amount` | calculated / `quote.installment_amount` | contract currency |
| `installment_count` | calculated / `quote.installment_count` | Not applicable |
| `contract_interest_rate_percent` | calculated / `quote.contract_interest_rate_percent` | Not applicable |
| `vehicle_registration_number` | entered | Not applicable |
| `offer_penalty_rate_percent` | entered | Not applicable |
| `offer_processing_fee_rate_percent` | entered | Not applicable |
| `offer_risk_fund_rate_percent` | entered | Not applicable |


## Compatibility and validation

Shared keys reuse the same subject, type, source, units and repeat structure.
Local fields belong to this document instance. Required choices and row limits
are validated by the existing form service; generated values cannot be posted.
No legal attestation, approval, receipt or transfer event is invented by rendering.
The source hash and dedicated reference are checked by supporting-seed tests.
