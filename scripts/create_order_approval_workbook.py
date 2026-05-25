"""Create an Order Approval Excel workbook template.

The generated workbook uses row 1 as a visual title and row 2 as the
bot-compatible header row. It uses only Python's standard library so it can run
on Render or a local machine without extra packages.
"""
from __future__ import annotations

import argparse
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape


DEFAULT_OUTPUT = "order_approval_template.xlsx"
DEFAULT_TABS = ["Orders"]
TITLE = "ORDER APPROVAL FORM - BUSINESS RELATIONSHIP OFFICER"

HEADERS = [
    "DATE VISITED",
    "CUSTOMER NAME",
    "BRANCH",
    "ID NUMBER",
    "CONTACTS / PRIMARY",
    "CONTACTS / SECONDARY",
    "COUNTY",
    "LOCATION AND NEAREST LANDMARK",
    "VISITED BY",
    "HB STAFF",
    "DEPOSIT / HB",
    "DEPOSIT / JBL",
    "COMMENT",
    "IS CUSTOMER CREATED ON IMAB?",
    "CUSTOMER NO",
    "CREDIT ANALYSIS",
    "FINAL DECISION",
    "Media URLs",
    "SOURCE TAB",
    "SOURCE ROW",
]

SAMPLE_ROW = [
    "09-May-2026",
    "PATRICK MWANGI MAINA",
    "MURANGA",
    "113650221",
    "0740614990",
    "",
    "MURANGA",
    "GITURI NEAR KAGANDA CENTRE",
    "JOHN & KIBINGE",
    "THOMAS",
    "5000",
    "0",
    "Approved",
    "CREATED",
    "15118",
    "Pending",
    "Under Review",
    "",
    "",
    "",
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create an Excel workbook template for order approval.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Output .xlsx path. Default: {DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "--tabs",
        default=",".join(DEFAULT_TABS),
        help=(
            "Comma-separated worksheet tab names. "
            "Default: Orders"
        ),
    )
    parser.add_argument(
        "--sample-row",
        action="store_true",
        help="Include one sample data row in the first worksheet.",
    )
    args = parser.parse_args()

    tabs = [tab.strip() for tab in args.tabs.split(",") if tab.strip()]
    if not tabs:
        raise SystemExit("At least one worksheet tab is required.")

    validate_sheet_names(tabs)
    output = Path(args.output)
    create_workbook(output, tabs, include_sample_row=args.sample_row)
    print(f"Created {output.resolve()}")


def validate_sheet_names(sheet_names: list[str]) -> None:
    seen = set()
    for name in sheet_names:
        if len(name) > 31:
            raise SystemExit(f"Worksheet name is too long: {name!r}")
        if any(char in name for char in r'[]:*?/\\'):
            raise SystemExit(f"Worksheet name contains invalid Excel chars: {name!r}")
        normalized = name.lower()
        if normalized in seen:
            raise SystemExit(f"Duplicate worksheet name: {name!r}")
        seen.add(normalized)


def create_workbook(
    output: Path,
    sheet_names: list[str],
    include_sample_row: bool = False,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml(len(sheet_names)))
        archive.writestr("_rels/.rels", root_relationships_xml())
        archive.writestr("docProps/app.xml", app_properties_xml(sheet_names))
        archive.writestr("docProps/core.xml", core_properties_xml())
        archive.writestr("xl/workbook.xml", workbook_xml(sheet_names))
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_relationships_xml(sheet_names))
        archive.writestr("xl/styles.xml", styles_xml())
        for index, sheet_name in enumerate(sheet_names, start=1):
            sample = SAMPLE_ROW if include_sample_row and index == 1 else None
            archive.writestr(
                f"xl/worksheets/sheet{index}.xml",
                worksheet_xml(sheet_name, sample),
            )


def content_types_xml(sheet_count: int) -> str:
    sheet_overrides = "\n".join(
        (
            f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.'
            'spreadsheetml.worksheet+xml"/>'
        )
        for index in range(1, sheet_count + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  {sheet_overrides}
</Types>
"""


def root_relationships_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
"""


def app_properties_xml(sheet_names: list[str]) -> str:
    titles = "".join(
        f"<vt:lpstr>{xml_escape(name)}</vt:lpstr>" for name in sheet_names
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Python</Application>
  <DocSecurity>0</DocSecurity>
  <ScaleCrop>false</ScaleCrop>
  <HeadingPairs>
    <vt:vector size="2" baseType="variant">
      <vt:variant><vt:lpstr>Worksheets</vt:lpstr></vt:variant>
      <vt:variant><vt:i4>{len(sheet_names)}</vt:i4></vt:variant>
    </vt:vector>
  </HeadingPairs>
  <TitlesOfParts>
    <vt:vector size="{len(sheet_names)}" baseType="lpstr">{titles}</vt:vector>
  </TitlesOfParts>
</Properties>
"""


def core_properties_xml() -> str:
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>Order Approval Template</dc:title>
  <dc:creator>HB Biogas Telegram Bot</dc:creator>
  <cp:lastModifiedBy>HB Biogas Telegram Bot</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:modified>
</cp:coreProperties>
"""


def workbook_xml(sheet_names: list[str]) -> str:
    sheets = "\n".join(
        (
            f'<sheet name="{xml_escape(name)}" sheetId="{index}" '
            f'r:id="rId{index}"/>'
        )
        for index, name in enumerate(sheet_names, start=1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    {sheets}
  </sheets>
</workbook>
"""


def workbook_relationships_xml(sheet_names: list[str]) -> str:
    sheet_rels = "\n".join(
        (
            f'<Relationship Id="rId{index}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{index}.xml"/>'
        )
        for index in range(1, len(sheet_names) + 1)
    )
    style_rel_id = len(sheet_names) + 1
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  {sheet_rels}
  <Relationship Id="rId{style_rel_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>
"""


def styles_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2">
    <font><sz val="11"/><name val="Calibri"/></font>
    <font><b/><sz val="11"/><name val="Calibri"/></font>
  </fonts>
  <fills count="2">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
  </fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="2">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>
"""


def worksheet_xml(sheet_name: str, sample_row: list[str] | None = None) -> str:
    del sheet_name
    rows = [row_xml(1, [TITLE] + [""] * (len(HEADERS) - 1), style_index=1)]
    rows.append(row_xml(2, HEADERS, style_index=1))
    if sample_row:
        rows.append(row_xml(3, sample_row, style_index=0))

    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetViews>
    <sheetView workbookViewId="0">
      <pane ySplit="2" topLeftCell="A3" activePane="bottomLeft" state="frozen"/>
    </sheetView>
  </sheetViews>
  <sheetFormatPr defaultRowHeight="15"/>
  <cols>
    <col min="1" max="1" width="14" customWidth="1"/>
    <col min="2" max="2" width="28" customWidth="1"/>
    <col min="3" max="7" width="18" customWidth="1"/>
    <col min="8" max="8" width="34" customWidth="1"/>
    <col min="9" max="20" width="18" customWidth="1"/>
  </cols>
  <sheetData>
    {"".join(rows)}
  </sheetData>
  {data_validations_xml(HEADERS, first_data_row=3)}
</worksheet>
"""


def data_validations_xml(headers: list[str], first_data_row: int, last_data_row: int = 1000) -> str:
    validations = []
    validations.extend(dropdown_validation(headers, "IS CUSTOMER CREATED ON IMAB?", ["Yes", "No", "Pending"], first_data_row, last_data_row))
    validations.extend(dropdown_validation(headers, "CREDIT ANALYSIS", ["Pass", "Fail", "Pending", "N/A"], first_data_row, last_data_row))
    validations.extend(dropdown_validation(headers, "FINAL DECISION", ["Approved", "Rejected", "Hold", "Under Review"], first_data_row, last_data_row))
    validations.extend(custom_phone_validation(headers, "CONTACTS / PRIMARY", first_data_row, last_data_row))
    validations.extend(custom_phone_validation(headers, "CONTACTS / SECONDARY", first_data_row, last_data_row))
    validations.extend(decimal_validation(headers, "DEPOSIT / HB", first_data_row, last_data_row))
    validations.extend(decimal_validation(headers, "DEPOSIT / JBL", first_data_row, last_data_row))
    validations.extend(integer_validation(headers, "CUSTOMER NO", first_data_row, last_data_row))
    validations.extend(date_validation(headers, "DATE VISITED", first_data_row, last_data_row))
    if not validations:
        return ""
    return f'<dataValidations count="{len(validations)}">{"".join(validations)}</dataValidations>'


def dropdown_validation(headers: list[str], header: str, values: list[str], first_row: int, last_row: int) -> list[str]:
    reference = validation_range(headers, header, first_row, last_row)
    if not reference:
        return []
    formula = '"' + ",".join(values) + '"'
    return [
        '<dataValidation type="list" allowBlank="1" showErrorMessage="1" '
        f'errorTitle="Invalid value" error="Choose one of: {xml_escape(", ".join(values))}." sqref="{reference}">'
        f'<formula1>{xml_escape(formula)}</formula1></dataValidation>'
    ]


def custom_phone_validation(headers: list[str], header: str, first_row: int, last_row: int) -> list[str]:
    reference = validation_range(headers, header, first_row, last_row)
    if not reference:
        return []
    cell = reference.split(":", 1)[0]
    formula = f'OR({cell}="",AND(ISNUMBER(--{cell}),LEN({cell})=12,LEFT({cell},3)="254"))'
    return [
        '<dataValidation type="custom" allowBlank="1" showErrorMessage="1" '
        'errorTitle="Invalid phone" error="Use 254XXXXXXXXX format, for example 254740614990." '
        f'sqref="{reference}"><formula1>{xml_escape(formula)}</formula1></dataValidation>'
    ]


def decimal_validation(headers: list[str], header: str, first_row: int, last_row: int) -> list[str]:
    reference = validation_range(headers, header, first_row, last_row)
    if not reference:
        return []
    return [
        '<dataValidation type="decimal" operator="greaterThanOrEqual" allowBlank="1" showErrorMessage="1" '
        f'errorTitle="Invalid amount" error="{xml_escape(header)} must be zero or greater." sqref="{reference}">'
        '<formula1>0</formula1></dataValidation>'
    ]


def integer_validation(headers: list[str], header: str, first_row: int, last_row: int) -> list[str]:
    reference = validation_range(headers, header, first_row, last_row)
    if not reference:
        return []
    return [
        '<dataValidation type="whole" operator="greaterThanOrEqual" allowBlank="1" showErrorMessage="1" '
        f'errorTitle="Invalid number" error="{xml_escape(header)} must contain digits only." sqref="{reference}">'
        '<formula1>0</formula1></dataValidation>'
    ]


def date_validation(headers: list[str], header: str, first_row: int, last_row: int) -> list[str]:
    reference = validation_range(headers, header, first_row, last_row)
    if not reference:
        return []
    return [
        '<dataValidation type="date" operator="between" allowBlank="1" showErrorMessage="1" '
        f'errorTitle="Invalid date" error="{xml_escape(header)} must be a valid date." sqref="{reference}">'
        '<formula1>1/1/2020</formula1><formula2>12/31/2099</formula2></dataValidation>'
    ]


def validation_range(headers: list[str], header: str, first_row: int, last_row: int) -> str:
    try:
        column = headers.index(header) + 1
    except ValueError:
        return ""
    letter = column_letter(column)
    return f"{letter}{first_row}:{letter}{last_row}"


def row_xml(row_index: int, values: list[str], style_index: int = 0) -> str:
    cells = "".join(
        cell_xml(row_index, column_index, value, style_index)
        for column_index, value in enumerate(values, start=1)
    )
    return f'<row r="{row_index}">{cells}</row>'


def cell_xml(row_index: int, column_index: int, value: str, style_index: int) -> str:
    reference = f"{column_letter(column_index)}{row_index}"
    style = f' s="{style_index}"' if style_index else ""
    return (
        f'<c r="{reference}" t="inlineStr"{style}>'
        f"<is><t>{xml_escape(value)}</t></is>"
        "</c>"
    )


def column_letter(column_index: int) -> str:
    letters = ""
    while column_index:
        column_index, remainder = divmod(column_index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def xml_escape(value: str) -> str:
    return escape(str(value or ""), {'"': "&quot;"})


if __name__ == "__main__":
    main()
