# Home visit: supporting-document reference

Reviewed blank source: `SUPPORT LAF- HOME VISIT FORM.pdf`, 1 pages, 408129 bytes.
SHA-256: `767b5bfc09f3789aa6b53b7817be0f489fedc95835e7b2a161efea9d00f4cd0c`.
Catalogue identity: `jawabu_home_visit`; document key: `home_visit`.

## Draft preparation

Use the existing isolated environment and an active Superuser actor:

```powershell
.\.venv\Scripts\python.exe manage.py seed_origination_support_lafs --laf-root .\LAFS --laf home_visit --actor admin
```

This is read-only by default. `--apply` is a deliberate database/Drive write,
creates an unpublished shared-value draft and never adds product eligibility.
Alignment is human-owned. Existing products, applications, files and signatures
are not migrated. A field reference is not a certified placement coordinate.

## Canonical fields

| Key | Type | Subject / scope | Source reference |
|---|---|---|---|
| `asset_owner_name` | `text` | asset_owner / application | p1: Assets belong to / I confirm owner |
| `asset_owner_national_id` | `national_id` | asset_owner / application | p1: Asset owner ID |
| `application_date` | `date` | application / application | p1: Loan application date; p1: Loan application date |
| `secured_assets_total` | `money` | application / application | p1: Estimated value total |
| `secured_assets` | `repeating_group` | application / application | Visual row capacity review required |
| `loan_officer_name` | `text` | application / application | p1: BRO name |
| `home_visit_completed_date` | `date` | application / application | p1: Visit date |

## Signers and unresolved decisions

Required roles: `asset_owner`, `officer`.
Unsupported native roles remain publication repair tasks; they are not mapped
to an unrelated approved role. Signature dates come from exact document signing
records, never a preview clock. Identity fields needed for OTP may be additional
signing inputs, not printed blanks.

- Owner confirmation needs its own signer; never assume the owner is the borrower.
- A preview date is not evidence that a visit occurred. Table capacity must be visually confirmed.

## Value sources and signer bindings

| Key | Source / binding | Unit / reporting period |
|---|---|---|
| `asset_owner_name` | entered | Not applicable |
| `asset_owner_national_id` | entered | Not applicable |
| `application_date` | calculated / `system.application_date` | Not applicable |
| `secured_assets_total` | calculated / `total.secured_assets_total` | Not applicable |
| `secured_assets` | Reviewed entered value | Not applicable |
| Child columns | `description` (`text`, up to 240 characters), `estimated_value` (`money`, nonnegative) | Maximum 11; minimum 1 |

The shared asset structure matches the existing canonical field; it is not
retyped or resized by seeding. The paper's actual visible row capacity must
still be configured and checked during placement before publication.
| `loan_officer_name` | calculated / `system.loan_officer_name` | Not applicable |
| `home_visit_completed_date` | workflow / `workflow.visit_date` | Not applicable |

- `officer`: `officer_signature` (`signature`), `officer_date_signed` (`date_signed`). Identity: existing authorized staff assignment.

## Compatibility and validation

Shared keys reuse the same subject, type, source, units and repeat structure.
Local fields belong to this document instance. Required choices and row limits
are validated by the existing form service; generated values cannot be posted.
No legal attestation, approval, receipt or transfer event is invented by rendering.
The source hash and dedicated reference are checked by supporting-seed tests.
