# Main LAF canonical map and seed operation

The reviewed source set is the six PDFs under the operator-supplied `LAFS/MAIN`
directory. PDFs are not committed. `seed_origination_main_lafs` verifies the
exact filename, SHA-256, byte size and page count before it reads catalogue
state. It is a dry run unless `--apply` is supplied.

```powershell
python manage.py seed_origination_main_lafs --laf-root "C:\path\to\LAFS" --laf all --actor admin
python manage.py seed_origination_main_lafs --laf-root "C:\path\to\LAFS" --laf all --actor admin --apply
```

`--laf` accepts `invoice_finance`, `generic`, `lipa_mdogo_mdogo`,
`micro_asset`, `water_tank`, and `sme_logbook`. Apply creates independent Main
LAF catalogue entries in Ready for review state. It does not publish alignment,
activate a template, change product terms, or alter historical applications.

## Reviewed source and eligibility matrix

| Seed | Source | Pages | Eligible global product |
|---|---|---:|---|
| `invoice_finance` | `INVOICE FINANCE.pdf` | 1 | `invoice_finance` |
| `generic` | `JBL LAF Generic.pdf` | 2 | none; unavailable until explicitly assigned |
| `lipa_mdogo_mdogo` | `Jawabu LAF-Lipa Mdogo Mdogo NEW (2).pdf` | 2 | `biogas` |
| `micro_asset` | `Jawabu LAF-Micro Asset Loan.pdf` | 2 | `micro_asset` |
| `water_tank` | `Jawabu LAF-Water Tank.pdf` | 2 | `water_tank` |
| `sme_logbook` | `SME-LOGBOOK LAF.pdf` | 4 | `logbook` |

The seed fails if an eligible product is missing, inactive, or has neither a
published nor draft `ProductVersion`. It never creates a product or silently
widens an allowlist.

## Reuse rules

- Applicant, contact, household, business, facility, guarantor, external-loan,
  commercial-term, and approval identities reuse active canonical keys.
- `external_loans` and `pledged_assets` retain their immutable reviewed child
  structures. SME uses `manufactured_collateral_assets` because its printed
  column is `year_of_manufacture`, not `year_of_purchase`.
- Commercial contract v2 exposes only `loan_amount` and `repayment_tenor` as
  officer input. Rates, frequency, installments, interest, fees and totals are
  system-derived.
- Approval decisions, staff identities, signatures, dates and stamps belong to
  controlled workflow or signer actions. They are not approval text entered by
  the originating officer.
- Photos, IDs, statements, invoices, pins and sketches are evidence
  requirements. Freehand sketch boxes are not canonical text fields.

## Publication boundary

The Admin alignment builder remains human-owned. An administrator must place
fields and signer/stamp slots, choose checkbox conditions, inspect overflow and
typography, preview realistic values, publish an alignment revision, and only
then activate the catalogue version. The SME template must white-out the fixed
`No. 3096` and overlay `reference_number` before activation.

Each LAF has a dedicated reference containing its complete field, signer,
evidence, validation, and render contract. `LafSeedDocumentationContractTests`
detects drift between those references and the Python registry.
