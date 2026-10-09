# Main LAF canonical map and seed operation

The original reviewed source set is the six PDFs under the operator-supplied `LAFS/MAIN`
directory. PDFs are not committed. `seed_origination_main_lafs` verifies the
exact filename, SHA-256, byte size and page count before it reads catalogue
state. It is a dry run unless `--apply` is supplied.

The renamed root-level Generic, Invoice Finance, SME/Logbook, Micro Asset and
Biogas sources are also accepted through exact reviewed filename aliases; the
hash, size and page checks are unchanged. The root-level Biogas filename does
not change its existing operational catalogue role. Water Tank remains an
additional existing seed, not one of the current eleven source PDFs.

For new shared-value drafts, add `--shared-values`. This never converts an
existing published document or application. See [value contracts](value-contracts.md)
for migration, repair and rollout boundaries. The six new supporting sources
use `seed_origination_support_lafs`, with dedicated references in this directory.
They are unassigned, unpublished drafts; visual occurrence/placement review is
still required before legal use.

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

## Reviewed input rules

The register now contains six Main LAFs and six supporting documents (the
original eleven plus Water Tank). Each occurrence, subject, source page and
requiredness remains in its dedicated LAF reference above; the following rules
supplement those mappings, rather than creating a second naming dictionary.

| Meaning / examples | Mini App control and validation | PDF value |
|---|---|---|
| Applicant / referee email | Email keyboard; optional blank allowed; valid email and at most 254 characters | Entered address |
| Children, dependants, cows and employee counts | Numeric keyboard; non-negative whole numbers | Whole number, including zero |
| Asset purchase / manufacture year | Whole number; retain the reviewed 1900–2200 limits where configured | Year, not a date |
| Years resident / years known / operating duration | Decimal number, not a forced integer | Entered duration |
| Applicant birth date | Date picker, today or earlier; existing supported age-range guard remains | Day/month/year |
| Application / agreement / repayment dates | Separate date fields; configured bounds only, no universal past-date rule | Day/month/year; signed dates remain signer events |
| Nationality | `applicant_nationality_country` / `grantor_nationality_country`: active country dropdown | Country label, not ISO code |
| National IDs, phones, account, chassis and registration numbers | Identity text or phone controls; preserve leading zeroes and existing Kenyan ID/phone checks | Stored identifier |
| Money, fees, rates and totals | Decimal server arithmetic, bounded amounts/rates; entered KES amounts retain the existing whole-KES rule | Governed money formatting; zero and negative calculated surplus remain visible |
| Repeating people, obligations and assets | Each child receives its scalar format/limits; bounded rows and independent row IDs | Child labels / values in calibrated rows |
| County / sub-county | Existing active location catalogue; `parent_field` binds the correct county when there are several | Human-readable location name |
| Yes / No | Choice control; false is a value, not missing | Yes / No, not True / False |
| Calculated amounts / later workflow outcomes | Read-only; no new editable approval/disbursement facts | Generated only when the existing source provides them |

Countries are an offline reviewed ISO 3166 reference from
[RIPE NCC](https://www.ripe.net/community/internet-governance/internet-technical-community/the-rir-system/list-of-country-codes-and-rirs/),
in `origination/reference_data/countries.json`. All 249 entries are seeded;
only Kenya (`ke`) starts active. Re-seeding preserves Admin activation choices.
New document drafts capture the currently active codes and labels. Existing
published documents retain their captured choices until explicitly updated.

The original `applicant_nationality` and `grantor_nationality` text keys remain
valid for historical documents; they are not changed in place. Adopt the new
choice fields in an editable document version and review its placements before
publishing. Ambiguous paper labels, optional signatures and legal terms remain
human-owned decisions. No new lending eligibility or age policy is inferred.

Input rules are stored in the published schema: `format`, `integer`,
`decimal_places`, `min`, `max`, `min_length`, `max_length`, `pattern`,
`min_date`, `max_date`, `no_future`, and `parent_field`. The same rules drive
the main and supporting forms and the server, including repeating cells.
Clearing a rule in the editor removes it. Incomplete drafts are allowed, but
supplied invalid values cannot be committed. Errors are inline; input remains.
For shared fields, requiredness is OR and limits intersect across selected
documents in newly reviewed `input_rules_version: 1` schemas. Legacy applications
keep their previous shared-rule resolution. Incompatible bounds/formats stop
publication or packet selection. Reviewed repeat-cell rules supplement new
document schemas without modifying the canonical row definition.
