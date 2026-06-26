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
OPTIONS_SHEET_NAME = "Dropdown Options"
TITLE = "ORDER APPROVAL FORM - BUSINESS RELATIONSHIP OFFICER"
PRE_FORMATTED_ROWS = 200

HEADERS = [
    "ORDER RECORD ID",
    "ORDER NO",
    "REQUISITION DATE",
    "DATE VISITED",
    "CUSTOMER NAME",
    "BRANCH",
    "ID NUMBER",
    "CONTACTS / PRIMARY",
    "CONTACTS / SECONDARY",
    "COUNTY",
    "SUB-COUNTY",
    "LOCATION AND NEAREST LANDMARK",
    "VISITED BY",
    "HB STAFF",
    "DEPOSIT / HB",
    "DEPOSIT / JBL",
    "BRO COMMENT",
    "IS CUSTOMER CREATED ON IMAB?",
    "CUSTOMER NO",
    "CREDIT ANALYSIS",
    "DECISION COMMENT",
    "FINAL DECISION",
    "Media URLs",
]

SAMPLE_ROW = [
    "JBL-1",
    "ORD-001",
    "08-May-2026",
    "09-May-2026",
    "PATRICK MWANGI MAINA",
    "MURANGA",
    "113650221",
    "254740614990",
    "",
    "MURANGA",
    "KIHARU",
    "GITURI NEAR KAGANDA CENTRE",
    "JOHN & KIBINGE",
    "THOMAS",
    "5000",
    "0",
    "Approved",
    "CREATED",
    "15118",
    "Pending",
    "Reviewed by credit team",
    "Deferred",
    "",
]

OPTIONS_HEADERS = ["Branch", "County", "Sub-County", "Visited By", "HB Staff"]
OPTIONS_SAMPLE_ROWS = [
    ["MURANGA", "MURANGA", "KIHARU", "JOHN", "THOMAS"],
    ["EMBU", "EMBU", "", "KIBINGE", ""],
]

STYLE_DEFAULT = 0
STYLE_TITLE = 1
STYLE_TITLE_FILL = 2
STYLE_HEADER_SYSTEM = 3
STYLE_HEADER_VISIT = 4
STYLE_HEADER_IDENTITY = 5
STYLE_HEADER_LOCATION = 6
STYLE_HEADER_STAFF = 7
STYLE_HEADER_FINANCIAL = 8
STYLE_HEADER_ASSESSMENT = 9
STYLE_HEADER_DECISION = 10
STYLE_DATA_SYSTEM = 11
STYLE_DATA_VISIT = 12
STYLE_DATA_VISIT_DATE = 13
STYLE_DATA_IDENTITY = 14
STYLE_DATA_LOCATION = 15
STYLE_DATA_STAFF = 16
STYLE_DATA_FINANCIAL = 17
STYLE_DATA_ASSESSMENT = 18
STYLE_DATA_DECISION = 19

GROUP_STYLES = {
    "system": (STYLE_HEADER_SYSTEM, STYLE_DATA_SYSTEM),
    "visit": (STYLE_HEADER_VISIT, STYLE_DATA_VISIT),
    "identity": (STYLE_HEADER_IDENTITY, STYLE_DATA_IDENTITY),
    "location": (STYLE_HEADER_LOCATION, STYLE_DATA_LOCATION),
    "staff": (STYLE_HEADER_STAFF, STYLE_DATA_STAFF),
    "financial": (STYLE_HEADER_FINANCIAL, STYLE_DATA_FINANCIAL),
    "assessment": (STYLE_HEADER_ASSESSMENT, STYLE_DATA_ASSESSMENT),
    "decision": (STYLE_HEADER_DECISION, STYLE_DATA_DECISION),
}

HEADER_GROUPS = {
    "ORDER RECORD ID": "system",
    "ORDER NO": "visit",
    "REQUISITION DATE": "visit",
    "DATE VISITED": "visit",
    "CUSTOMER NAME": "visit",
    "BRANCH": "visit",
    "ID NUMBER": "identity",
    "CONTACTS / PRIMARY": "identity",
    "CONTACTS / SECONDARY": "identity",
    "COUNTY": "location",
    "SUB-COUNTY": "location",
    "LOCATION AND NEAREST LANDMARK": "location",
    "VISITED BY": "staff",
    "HB STAFF": "staff",
    "DEPOSIT / HB": "financial",
    "DEPOSIT / JBL": "financial",
    "BRO COMMENT": "assessment",
    "IS CUSTOMER CREATED ON IMAB?": "assessment",
    "CUSTOMER NO": "assessment",
    "CREDIT ANALYSIS": "assessment",
    "DECISION COMMENT": "decision",
    "FINAL DECISION": "decision",
    "Media URLs": "system",
}

COLUMN_WIDTHS = {
    "ORDER RECORD ID": 24,
    "ORDER NO": 16,
    "REQUISITION DATE": 18,
    "DATE VISITED": 15,
    "CUSTOMER NAME": 28,
    "BRANCH": 16,
    "ID NUMBER": 18,
    "CONTACTS / PRIMARY": 18,
    "CONTACTS / SECONDARY": 18,
    "COUNTY": 18,
    "SUB-COUNTY": 20,
    "LOCATION AND NEAREST LANDMARK": 36,
    "VISITED BY": 20,
    "HB STAFF": 20,
    "DEPOSIT / HB": 14,
    "DEPOSIT / JBL": 14,
    "BRO COMMENT": 36,
    "IS CUSTOMER CREATED ON IMAB?": 24,
    "CUSTOMER NO": 16,
    "CREDIT ANALYSIS": 18,
    "DECISION COMMENT": 36,
    "FINAL DECISION": 18,
    "Media URLs": 42,
}


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
    order_sheet_names = [
        name for name in sheet_names
        if name.lower() != OPTIONS_SHEET_NAME.lower()
    ]
    if not order_sheet_names:
        raise SystemExit(f"At least one worksheet tab other than {OPTIONS_SHEET_NAME!r} is required.")
    workbook_sheets = workbook_sheet_names(sheet_names)
    options_sheet_index = len(workbook_sheets)

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml(len(workbook_sheets)))
        archive.writestr("_rels/.rels", root_relationships_xml())
        archive.writestr("docProps/app.xml", app_properties_xml(workbook_sheets))
        archive.writestr("docProps/core.xml", core_properties_xml())
        archive.writestr("xl/workbook.xml", workbook_xml(workbook_sheets))
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_relationships_xml(workbook_sheets))
        archive.writestr("xl/styles.xml", styles_xml())
        for index, sheet_name in enumerate(order_sheet_names, start=1):
            sample = SAMPLE_ROW if include_sample_row and index == 1 else None
            archive.writestr(
                f"xl/worksheets/sheet{index}.xml",
                worksheet_xml(sheet_name, sample),
            )
        archive.writestr(
            f"xl/worksheets/sheet{options_sheet_index}.xml",
            options_worksheet_xml(),
        )


def workbook_sheet_names(sheet_names: list[str]) -> list[str]:
    names = [
        name for name in sheet_names
        if name.lower() != OPTIONS_SHEET_NAME.lower()
    ]
    names.append(OPTIONS_SHEET_NAME)
    return names


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
  <numFmts count="1">
    <numFmt numFmtId="164" formatCode="dd-mmm-yyyy"/>
  </numFmts>
  <fonts count="4">
    <font><sz val="10"/><color theme="1"/><name val="Arial"/></font>
    <font><b/><sz val="13"/><color rgb="FFFFFFFF"/><name val="Arial"/></font>
    <font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Arial"/></font>
    <font><sz val="10"/><color theme="1"/><name val="Arial"/></font>
  </fonts>
  <fills count="20">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF0D47A1"/><bgColor rgb="FF0D47A1"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF37474F"/><bgColor rgb="FF37474F"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF1A7744"/><bgColor rgb="FF1A7744"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF1565C0"/><bgColor rgb="FF1565C0"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF6A1B9A"/><bgColor rgb="FF6A1B9A"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF00695C"/><bgColor rgb="FF00695C"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFE65100"/><bgColor rgb="FFE65100"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFB71C1C"/><bgColor rgb="FFB71C1C"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF4A148C"/><bgColor rgb="FF4A148C"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFECEFF1"/><bgColor rgb="FFECEFF1"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFE8F5E9"/><bgColor rgb="FFE8F5E9"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFE3F2FD"/><bgColor rgb="FFE3F2FD"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFF3E5F5"/><bgColor rgb="FFF3E5F5"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFE0F2F1"/><bgColor rgb="FFE0F2F1"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFFBE9E7"/><bgColor rgb="FFFBE9E7"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFFFEBEE"/><bgColor rgb="FFFFEBEE"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFEDE7F6"/><bgColor rgb="FFEDE7F6"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFFFFFFF"/><bgColor rgb="FFFFFFFF"/></patternFill></fill>
  </fills>
  <borders count="3">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border>
      <left style="thin"><color rgb="FFDDDDDD"/></left>
      <right style="thin"><color rgb="FFDDDDDD"/></right>
      <top style="thin"><color rgb="FFDDDDDD"/></top>
      <bottom style="thin"><color rgb="FFDDDDDD"/></bottom>
      <diagonal/>
    </border>
    <border>
      <bottom style="medium"><color rgb="FFFFFFFF"/></bottom>
      <diagonal/>
    </border>
  </borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="20">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="2" xfId="0" applyAlignment="1" applyBorder="1" applyFill="1" applyFont="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="2" xfId="0" applyBorder="1" applyFill="1" applyFont="1"/>
    <xf numFmtId="0" fontId="2" fillId="3" borderId="1" xfId="0" applyAlignment="1" applyBorder="1" applyFill="1" applyFont="1"><alignment horizontal="center" shrinkToFit="1" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="2" fillId="4" borderId="1" xfId="0" applyAlignment="1" applyBorder="1" applyFill="1" applyFont="1"><alignment horizontal="center" shrinkToFit="1" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="2" fillId="5" borderId="1" xfId="0" applyAlignment="1" applyBorder="1" applyFill="1" applyFont="1"><alignment horizontal="center" shrinkToFit="1" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="2" fillId="6" borderId="1" xfId="0" applyAlignment="1" applyBorder="1" applyFill="1" applyFont="1"><alignment horizontal="center" shrinkToFit="1" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="2" fillId="7" borderId="1" xfId="0" applyAlignment="1" applyBorder="1" applyFill="1" applyFont="1"><alignment horizontal="center" shrinkToFit="1" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="2" fillId="8" borderId="1" xfId="0" applyAlignment="1" applyBorder="1" applyFill="1" applyFont="1"><alignment horizontal="center" shrinkToFit="1" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="2" fillId="9" borderId="1" xfId="0" applyAlignment="1" applyBorder="1" applyFill="1" applyFont="1"><alignment horizontal="center" shrinkToFit="1" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="2" fillId="10" borderId="1" xfId="0" applyAlignment="1" applyBorder="1" applyFill="1" applyFont="1"><alignment horizontal="center" shrinkToFit="1" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="3" fillId="11" borderId="1" xfId="0" applyAlignment="1" applyBorder="1" applyFill="1" applyFont="1"><alignment horizontal="left" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="3" fillId="12" borderId="1" xfId="0" applyAlignment="1" applyBorder="1" applyFill="1" applyFont="1"><alignment horizontal="left" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="164" fontId="3" fillId="12" borderId="1" xfId="0" applyAlignment="1" applyBorder="1" applyFill="1" applyFont="1" applyNumberFormat="1"><alignment horizontal="left" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="3" fillId="13" borderId="1" xfId="0" applyAlignment="1" applyBorder="1" applyFill="1" applyFont="1"><alignment horizontal="left" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="3" fillId="14" borderId="1" xfId="0" applyAlignment="1" applyBorder="1" applyFill="1" applyFont="1"><alignment horizontal="left" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="3" fillId="15" borderId="1" xfId="0" applyAlignment="1" applyBorder="1" applyFill="1" applyFont="1"><alignment horizontal="left" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="3" fillId="16" borderId="1" xfId="0" applyAlignment="1" applyBorder="1" applyFill="1" applyFont="1"><alignment horizontal="left" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="3" fillId="17" borderId="1" xfId="0" applyAlignment="1" applyBorder="1" applyFill="1" applyFont="1"><alignment horizontal="left" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="3" fillId="18" borderId="1" xfId="0" applyAlignment="1" applyBorder="1" applyFill="1" applyFont="1"><alignment horizontal="left" vertical="center" wrapText="1"/></xf>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
  <dxfs count="4">
    <dxf><font><color rgb="FF1B5E20"/></font><fill><patternFill patternType="solid"><fgColor rgb="FFE8F5E9"/><bgColor rgb="FFE8F5E9"/></patternFill></fill></dxf>
    <dxf><font><color rgb="FFB71C1C"/></font><fill><patternFill patternType="solid"><fgColor rgb="FFFFEBEE"/><bgColor rgb="FFFFEBEE"/></patternFill></fill></dxf>
    <dxf><font><color rgb="FFE65100"/></font><fill><patternFill patternType="solid"><fgColor rgb="FFFFF8E1"/><bgColor rgb="FFFFF8E1"/></patternFill></fill></dxf>
    <dxf><font><color rgb="FF0D47A1"/></font><fill><patternFill patternType="solid"><fgColor rgb="FFE3F2FD"/><bgColor rgb="FFE3F2FD"/></patternFill></fill></dxf>
  </dxfs>
</styleSheet>
"""


def worksheet_xml(sheet_name: str, sample_row: list[str] | None = None) -> str:
    del sheet_name
    rows = [title_row_xml()]
    rows.append(row_xml(2, HEADERS, style_indexes=header_style_indexes(), height=34))

    first_data_row = 3
    last_data_row = first_data_row + PRE_FORMATTED_ROWS - 1
    for row_index in range(first_data_row, last_data_row + 1):
        values = sample_row if sample_row and row_index == first_data_row else [""] * len(HEADERS)
        rows.append(row_xml(row_index, values, style_indexes=data_style_indexes(), height=20))

    last_column = column_letter(len(HEADERS))

    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetPr>
    <tabColor rgb="FF0D47A1"/>
  </sheetPr>
  <sheetViews>
    <sheetView workbookViewId="0">
      <pane xSplit="3" ySplit="2" topLeftCell="D3" activePane="bottomRight" state="frozen"/>
      <selection activeCell="D3" sqref="D3" pane="bottomRight"/>
    </sheetView>
  </sheetViews>
  <sheetFormatPr defaultRowHeight="18"/>
  <cols>{columns_xml()}</cols>
  <sheetData>
    {"".join(rows)}
  </sheetData>
  <autoFilter ref="A2:{last_column}2"/>
  <mergeCells count="1"><mergeCell ref="A1:{last_column}1"/></mergeCells>
  {conditional_formatting_xml(first_data_row, last_data_row, last_column)}
  {data_validations_xml(HEADERS, first_data_row=3)}
  <pageMargins left="0.75" right="0.75" top="1" bottom="1" header="0" footer="0"/>
  <pageSetup orientation="landscape"/>
</worksheet>
"""


def options_worksheet_xml() -> str:
    rows = [
        row_xml(1, OPTIONS_HEADERS, style_indexes=[STYLE_HEADER_SYSTEM] * len(OPTIONS_HEADERS), height=24)
    ]
    for row_index, values in enumerate(OPTIONS_SAMPLE_ROWS, start=2):
        rows.append(row_xml(row_index, values, style_indexes=[STYLE_DATA_SYSTEM] * len(OPTIONS_HEADERS), height=20))

    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetPr><tabColor rgb="FF37474F"/></sheetPr>
  <sheetViews>
    <sheetView workbookViewId="0">
      <pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>
    </sheetView>
  </sheetViews>
  <sheetFormatPr defaultRowHeight="18"/>
  <cols>
    <col min="1" max="4" width="22" customWidth="1"/>
  </cols>
  <sheetData>{"".join(rows)}</sheetData>
  <autoFilter ref="A1:D1"/>
</worksheet>
"""


def conditional_formatting_xml(first_row: int, last_row: int, last_column: str) -> str:
    decision_col = column_letter(HEADERS.index("FINAL DECISION") + 1)
    sqref = f"A{first_row}:{last_column}{last_row}"
    decisions = [
        ("Approved", 0, 1),
        ("Rejected", 1, 2),
        ("Deferred", 2, 3),
        ("Under Review", 3, 4),
    ]
    rules = "".join(
        (
            f'<cfRule type="expression" dxfId="{dxf_id}" priority="{priority}">'
            f'<formula>${decision_col}{first_row}="{xml_escape(decision)}"</formula>'
            '</cfRule>'
        )
        for decision, dxf_id, priority in decisions
    )
    return f'<conditionalFormatting sqref="{sqref}">{rules}</conditionalFormatting>'


def data_validations_xml(headers: list[str], first_data_row: int, last_data_row: int = 1000) -> str:
    validations = []
    validations.extend(options_range_validation(headers, "BRANCH", 1, first_data_row, last_data_row))
    validations.extend(options_range_validation(headers, "COUNTY", 2, first_data_row, last_data_row))
    validations.extend(options_range_validation(headers, "SUB-COUNTY", 3, first_data_row, last_data_row))
    validations.extend(options_range_validation(headers, "VISITED BY", 4, first_data_row, last_data_row))
    validations.extend(options_range_validation(headers, "HB STAFF", 5, first_data_row, last_data_row))
    validations.extend(dropdown_validation(headers, "IS CUSTOMER CREATED ON IMAB?", ["Yes", "No", "Pending"], first_data_row, last_data_row))
    validations.extend(dropdown_validation(headers, "CREDIT ANALYSIS", ["Approved", "Pending", "Rejected"], first_data_row, last_data_row))
    validations.extend(dropdown_validation(headers, "FINAL DECISION", ["Approved", "Rejected", "Deferred", "Under Review"], first_data_row, last_data_row))
    validations.extend(custom_phone_validation(headers, "CONTACTS / PRIMARY", first_data_row, last_data_row))
    validations.extend(custom_phone_validation(headers, "CONTACTS / SECONDARY", first_data_row, last_data_row))
    validations.extend(decimal_validation(headers, "DEPOSIT / HB", first_data_row, last_data_row))
    validations.extend(decimal_validation(headers, "DEPOSIT / JBL", first_data_row, last_data_row))
    validations.extend(integer_validation(headers, "CUSTOMER NO", first_data_row, last_data_row))
    validations.extend(date_validation(headers, "DATE VISITED", first_data_row, last_data_row))
    for header in ["CUSTOMER NAME", "BRANCH", "COUNTY", "SUB-COUNTY", "VISITED BY", "HB STAFF"]:
        validations.extend(uppercase_validation(headers, header, first_data_row, last_data_row))
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


def options_range_validation(
    headers: list[str],
    header: str,
    options_column: int,
    first_row: int,
    last_row: int,
) -> list[str]:
    reference = validation_range(headers, header, first_row, last_row)
    if not reference:
        return []
    options_col = column_letter(options_column)
    formula = f"'{OPTIONS_SHEET_NAME}'!${options_col}$2:${options_col}$500"
    return [
        '<dataValidation type="list" allowBlank="1" showErrorMessage="0" '
        f'sqref="{reference}"><formula1>{xml_escape(formula)}</formula1></dataValidation>'
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


def uppercase_validation(headers: list[str], header: str, first_row: int, last_row: int) -> list[str]:
    reference = validation_range(headers, header, first_row, last_row)
    if not reference:
        return []
    cell = reference.split(":", 1)[0]
    formula = f'OR({cell}="",EXACT({cell},UPPER({cell})))'
    return [
        '<dataValidation type="custom" allowBlank="1" showErrorMessage="1" '
        f'errorTitle="Use uppercase" error="{xml_escape(header)} should be uppercase." sqref="{reference}">'
        f'<formula1>{xml_escape(formula)}</formula1></dataValidation>'
    ]


def validation_range(headers: list[str], header: str, first_row: int, last_row: int) -> str:
    try:
        column = headers.index(header) + 1
    except ValueError:
        return ""
    letter = column_letter(column)
    return f"{letter}{first_row}:{letter}{last_row}"


def title_row_xml() -> str:
    values = [TITLE] + [""] * (len(HEADERS) - 1)
    styles = [STYLE_TITLE] + [STYLE_TITLE_FILL] * (len(HEADERS) - 1)
    return row_xml(1, values, style_indexes=styles, height=30)


def header_style_indexes() -> list[int]:
    return [
        GROUP_STYLES[HEADER_GROUPS.get(header, "system")][0]
        for header in HEADERS
    ]


def data_style_indexes() -> list[int]:
    styles = []
    for header in HEADERS:
        if header == "DATE VISITED":
            styles.append(STYLE_DATA_VISIT_DATE)
            continue
        styles.append(GROUP_STYLES[HEADER_GROUPS.get(header, "system")][1])
    return styles


def columns_xml() -> str:
    return "".join(
        (
            f'<col min="{index}" max="{index}" '
            f'width="{COLUMN_WIDTHS.get(header, 18)}" customWidth="1"/>'
        )
        for index, header in enumerate(HEADERS, start=1)
    )


def row_xml(
    row_index: int,
    values: list[str],
    style_index: int = STYLE_DEFAULT,
    style_indexes: list[int] | None = None,
    height: int | None = None,
) -> str:
    if style_indexes is None:
        style_indexes = [style_index] * len(values)
    cells = "".join(
        cell_xml(row_index, column_index, value, style_indexes[column_index - 1])
        for column_index, value in enumerate(values, start=1)
    )
    height_attributes = (
        f' ht="{height}" customHeight="1"'
        if height is not None
        else ""
    )
    return f'<row r="{row_index}"{height_attributes}>{cells}</row>'


def cell_xml(row_index: int, column_index: int, value: str, style_index: int) -> str:
    reference = f"{column_letter(column_index)}{row_index}"
    style = f' s="{style_index}"' if style_index else ""
    if value == "":
        return f'<c r="{reference}"{style}/>'
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
