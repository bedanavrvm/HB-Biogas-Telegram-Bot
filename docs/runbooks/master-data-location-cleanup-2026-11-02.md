# Master Data v5 location and monetary cleanup

This workbook-only cleanup uses the latest manually edited `Master Data Live - Original vs Cleaned v4.xlsx`. It does not change the Portal, Complaints location catalogue, database, or provider integrations. The source workbook and its remaining historical columns are retained; v5 proposals appear beside reviewed v4 values.

## Monetary rules

- Blank, a standalone hyphen and explicit zero represent numeric zero in monetary output columns.
- Total is HB deposit plus the actual legacy JBL deposit. The deposit date is excluded.
- `Not on SF` in HB deposit is an explicit exception: retain that marker and leave Total intentionally blank, without a missing-amount or invalid-total flag.
- Other malformed monetary text or a date under an amount heading remains unresolved. Do not recover a receipt amount by subtracting from Total.
- Use decimal arithmetic. Retain the reviewed amount beside each proposed value.

## Why the old location list was insufficient

The previous reference was a 2019 national-administration census snapshot. Official sources also describe county-government units, constituencies, wards, later administrative units and historical names. A missing name in that snapshot is not proof that the customer's place is invalid.

The [2026 NYS national recruitment schedule](https://www.nys.go.ke/sites/default/files/NYS--RECRUITMENT%20OF%20NYS%20VOLUNTEER%20SERVICEMEN%20AND%20SERVICEWOMEN--new%20%281%29.pdf) contains 412 numbered county/sub-county entries. In particular, it explicitly lists Othaya with Nyeri South as an alternate label. The [Nyeri CIDP](https://www.nyeri.go.ke/wp-content/uploads/2024/01/APPROVED-CIDP.pdf) also recognises Othaya. Othaya must not be discarded as an unrecognised sub-county.

The [IEBC 2022 ward register](https://www.iebc.or.ke/docs/rov_per_caw.pdf) supplies a complete electoral hierarchy of 47 counties, 290 constituencies and 1,450 wards. These facts establish electoral parents; they do not establish that every national administrative boundary is identical.

| Source label | Treatment |
|---|---|
| Othaya / Nyeri South | Retain a supported sub-county name and Othaya constituency; record the published alternate name. |
| Manyatta | Valid county operational/electoral label. Do not invent an Embu North/West split. |
| Runyenjes | Retain the electoral/operational name; an explicitly sourced Embu East relationship can be recorded separately. |
| Mathira / Kieni / Mwea | Retain the known constituency when the supplied locality cannot identify the administrative East/West unit. |
| Bahati | Retain the county-supported sub-county name rather than blanking it because a different reference uses Nakuru North. |
| Kaharo | An independently documented Murang'a South locality; it must take precedence over fuzzy correction to Kahuro. |
| Ngobit | National administrative parent and constituency can differ; record both meanings explicitly. |

Relevant primary county sources include the [Embu overview](https://www.embu.go.ke/county-overview), [Meru CIDP](https://meru.go.ke/assets/file/0edda0ba-meru-county-integrated-development-p.pdf), [Kiambu administrative directory](https://kiambu.go.ke/administrative-units/), and [Murang'a health facility list](https://muranga.go.ke/wp-content/uploads/2024/08/Telemedicine-Pilot-Health-Facilities.pdf). County-specific research and each applied source URL are retained in the private local v5 research/audit artifacts.

## Application and review

Cleaned geographic text uses uppercase. Exact researched names and aliases take priority over spelling heuristics. Heuristics are county-qualified and recorded with their supporting reference. Unresolved broad areas and localities survive in `Location detail`; constituency and sub-county remain separate. Source wording stays available even when a parent cannot safely be assigned.

The workbook includes the national administrative schedule, the full electoral hierarchy, a sourced crosswalk and a row-level mapping audit. County-dependent dropdowns use the expanded reference; they are suggestions rather than a hard prohibition on future human corrections.

The saved-file review checks source-value preservation, row identities, untouched contacts/IDs, zero monetary blanks, the `Not on SF` exception, deposit addition, uppercase geographic output, reference membership and projection consistency. It is a direct review of the actual workbook, not a synthetic test suite or proof of a customer's real address.

No production import or app catalogue migration follows from this cleanup. Complete present-day legal boundary equivalence and customer-address verification remain outside this task.

The existing Portal workbook reader treats `Constituency` as a legacy alias for `sub_county`. V5 deliberately separates those values; a future ingestion adapter must handle the new constituency column explicitly. This task does not change that adapter or claim that v5 can be imported unchanged.
