# Reviewed v5: Eco-conserve header correction

The user confirmed that the two registers share a structure and asked for value
inspection when Eco-conserve contained two Invoice Amount headers. The original
workbook is retained. The import-ready copy changes exactly one header cell;
it makes no financial or personal-data corrections.

Source: Master Data Live - Original vs Cleaned v5.xlsx.
Output: Master Data Live - Original vs Cleaned v5 - Import Ready.xlsx.

In Eco-conserve Compare, AN1 and AO1 both said AJ | Invoice Amount | Cleaned.
Across all 156 populated rows, AN contains zero. AO contains the actual invoice
amounts; AP contains discounts and AQ contains payment references. This aligns
the meaningful fields with Master Data's schema. AN1 is therefore renamed
**LEGACY | Duplicate Invoice Amount (AN) | Cleaned**, retaining every zero as
historical evidence. AO remains the operational Invoice Amount. AP/AQ remain
unchanged. The importer still rejects ambiguous duplicate operational headers;
it does not guess between competing amounts on future uploads.

The ZIP-level repair changes only xl/worksheets/sheet3.xml and only cell AN1.
Every data value and every other archive entry is unchanged. The local audit is
test-results/eco-header-repair.json. Source SHA256:
6372926a0432958f3448262ec0d128d74f14f91c4ffe402ba882b47af1d7b82b.
Output SHA256: e00a212895871a8cbfb07de64c39ac9bedc12ce7cbf9395a26aef5e297c2caf8.

Playwright uploaded and staged this copy separately for both sources: 156
Eco-conserve rows (17 warning rows), and 4,077 Master Data rows (208 warning
rows), with no blocked rows. Warnings remain visible for malformed contacts,
unusual references and conflicting dates/workflow facts. Zero reviewed customer
rows were committed into canonical cases. This staging is not a production
import or final verification of those historical facts.
