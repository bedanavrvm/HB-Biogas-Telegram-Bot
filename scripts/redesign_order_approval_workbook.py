"""Convert the old order approval workbook into one flat worksheet.

The original workbook uses multiple tabs, merged headers, and section rows.
This script reads that workbook and creates a single `Orders` worksheet with
one header row, bot-compatible BRO columns, source traceability, and cleaner
back-office/product columns.
"""
from __future__ import annotations

import argparse
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape


DEFAULT_INPUT = "ORDER APPROVAL APRIL 2026.xlsx"
DEFAULT_OUTPUT = "ORDER APPROVAL REDESIGNED.xlsx"
OUTPUT_SHEET_NAME = "Orders"

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}

HEADERS = [
    "ORDER RECORD ID",
    "SOURCE TAB",
    "SOURCE ROW",
    "SOURCE NOTE",
    "SECTION",
    "CURRENT STATUS",
    "DATE VISITED",
    "CUSTOMER NAME",
    "CONTACTS / PRIMARY",
    "CONTACTS / SECONDARY",
    "ID NUMBER",
    "COUNTY",
    "SUB-COUNTY",
    "LOCATION AND NEAREST LANDMARK",
    "VISITED BY",
    "HB STAFF",
    "DEPOSIT / HB",
    "DEPOSIT / JBL",
    "COMMENT",
    "IS CUSTOMER CREATED ON IMAB?",
    "CUSTOMER NO",
    "CREDIT ANALYSIS",
    "Media URLs",
    "BACK OFFICE DATE",
    "VERIFIED BY",
    "BACK OFFICE CREDIT ANALYSIS",
    "DOCUMENTATION COMPLETE?",
    "PRODUCT TEAM DATE",
    "ORDER NO.",
    "CALLED/VERIFIED BY",
    "PRODUCT TEAM COMMENTS",
    "FINAL DECISION",
]

SOURCE_COLUMNS = {
    "CURRENT STATUS": 1,
    "DATE VISITED": 2,
    "CUSTOMER NAME": 3,
    "CONTACTS / PRIMARY": 4,
    "CONTACTS / SECONDARY": 5,
    "ID NUMBER": 6,
    "COUNTY": 7,
    "LOCATION AND NEAREST LANDMARK": 8,
    "VISITED BY": 9,
    "HB STAFF": 10,
    "DEPOSIT / HB": 11,
    "DEPOSIT / JBL": 12,
    "COMMENT": 13,
    "IS CUSTOMER CREATED ON IMAB?": 14,
    "CUSTOMER NO": 15,
    "CREDIT ANALYSIS": 16,
    "BACK OFFICE DATE": 17,
    "VERIFIED BY": 18,
    "BACK OFFICE CREDIT ANALYSIS": 19,
    "DOCUMENTATION COMPLETE?": 20,
    "PRODUCT TEAM DATE": 21,
    "ORDER NO.": 22,
    "CALLED/VERIFIED BY": 23,
    "PRODUCT TEAM COMMENTS": 24,
}

DECISION_COLUMNS = {
    "DEFERRED": 25,
    "DECLINED": 26,
    "APPROVED": 27,
}

DATE_HEADERS = {
    "DATE VISITED",
    "BACK OFFICE DATE",
    "PRODUCT TEAM DATE",
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Redesign the order approval workbook as one flat sheet.",
    )
    parser.add_argument(
        "-i",
        "--input",
        default=DEFAULT_INPUT,
        help=f"Source workbook path. Default: {DEFAULT_INPUT}",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Output workbook path. Default: {DEFAULT_OUTPUT}",
    )
    args = parser.parse_args()

    source = Path(args.input)
    if not source.exists():
        raise SystemExit(f"Input workbook not found: {source}")

    records = extract_records(source)
    output = Path(args.output)
    write_workbook(output, records)

    print(f"Read {len(records)} order row(s) from {source}")
    print(f"Created {output.resolve()}")
    print("Configure the bot group with sheet_name/search tab: Orders")


def extract_records(path: Path) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    with zipfile.ZipFile(path) as archive:
        shared_strings = read_shared_strings(archive)
        for sheet_name, sheet_path in workbook_sheets(archive):
            rows = worksheet_rows(archive, sheet_path, shared_strings)
            section = ""
            for row_number in sorted(rows):
                cells = rows[row_number]
                if is_section_row(cells):
                    section = cells.get(2, "").strip()
                    continue
                if not is_order_row(cells):
                    continue

                record = {
                    "ORDER RECORD ID": "",
                    "SOURCE TAB": sheet_name,
                    "SOURCE ROW": str(row_number),
                    "SOURCE NOTE": "",
                    "SECTION": section,
                    "SUB-COUNTY": "",
                    "Media URLs": "",
                }
                if has_extra_legacy_value_after_id(cells):
                    record["SOURCE NOTE"] = (
                        "Legacy extra value after ID NUMBER: "
                        f"{normalize_value(cells.get(7, ''))}"
                    )
                    apply_shifted_legacy_row(record, cells)
                    records.append(record)
                    continue

                for header, column_index in SOURCE_COLUMNS.items():
                    record[header] = normalize_value(
                        cells.get(column_index, ""),
                        is_date=header in DATE_HEADERS,
                    )
                record["FINAL DECISION"] = final_decision(cells)
                records.append(record)
    return records


def read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []

    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(text.text or "" for text in item.findall(".//m:t", NS))
        for item in root.findall("m:si", NS)
    ]


def workbook_sheets(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    relationship_targets = {
        relationship.attrib["Id"]: relationship.attrib["Target"]
        for relationship in relationships.findall("rel:Relationship", NS)
    }

    sheets = []
    for sheet in workbook.find("m:sheets", NS):
        relationship_id = sheet.attrib[
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        ]
        target = relationship_targets[relationship_id]
        if not target.startswith("xl/"):
            target = "xl/" + target
        sheets.append((sheet.attrib["name"], target))
    return sheets


def worksheet_rows(
    archive: zipfile.ZipFile,
    sheet_path: str,
    shared_strings: list[str],
) -> dict[int, dict[int, str]]:
    root = ET.fromstring(archive.read(sheet_path))
    rows: dict[int, dict[int, str]] = {}
    for row in root.findall(".//m:row", NS):
        row_number = int(row.attrib["r"])
        values: dict[int, str] = {}
        for cell in row.findall("m:c", NS):
            reference = cell.attrib.get("r", "")
            column_index = column_reference_to_index(reference)
            value = cell_value(cell, shared_strings).strip()
            if value:
                values[column_index] = value
        if values:
            rows[row_number] = values
    return rows


def cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "s":
        value = cell.find("m:v", NS)
        if value is None or value.text is None:
            return ""
        return shared_strings[int(value.text)]
    if cell_type == "inlineStr":
        return "".join(text.text or "" for text in cell.findall(".//m:t", NS))

    value = cell.find("m:v", NS)
    return value.text if value is not None and value.text is not None else ""


def is_section_row(cells: dict[int, str]) -> bool:
    if set(cells) != {2}:
        return False
    value = cells[2].strip()
    return bool(value) and not looks_like_date(value)


def is_order_row(cells: dict[int, str]) -> bool:
    return bool(cells.get(3, "").strip() and cells.get(6, "").strip())


def final_decision(cells: dict[int, str]) -> str:
    for decision, column_index in DECISION_COLUMNS.items():
        if cells.get(column_index, "").strip():
            return decision
    return ""


def has_extra_legacy_value_after_id(cells: dict[int, str]) -> bool:
    """Detect old rows where an unlabelled value was inserted after ID NUMBER."""
    return (
        is_numeric(cells.get(7, ""))
        and bool(cells.get(8, "").strip())
        and bool(cells.get(9, "").strip())
    )


def apply_shifted_legacy_row(record: dict[str, str], cells: dict[int, str]) -> None:
    for header in [
        "CURRENT STATUS",
        "DATE VISITED",
        "CUSTOMER NAME",
        "CONTACTS / PRIMARY",
        "CONTACTS / SECONDARY",
        "ID NUMBER",
    ]:
        record[header] = normalize_value(
            cells.get(SOURCE_COLUMNS[header], ""),
            is_date=header in DATE_HEADERS,
        )

    shifted_columns = {
        "COUNTY": 8,
        "LOCATION AND NEAREST LANDMARK": 9,
        "VISITED BY": 10,
        "HB STAFF": 11,
        "DEPOSIT / HB": 12,
        "DEPOSIT / JBL": 13,
        "COMMENT": 14,
        "IS CUSTOMER CREATED ON IMAB?": 15,
        "CUSTOMER NO": 16,
    }
    for header, column_index in shifted_columns.items():
        record[header] = normalize_value(cells.get(column_index, ""))

    record["CREDIT ANALYSIS"] = ""
    for header in [
        "BACK OFFICE DATE",
        "VERIFIED BY",
        "BACK OFFICE CREDIT ANALYSIS",
        "DOCUMENTATION COMPLETE?",
        "PRODUCT TEAM DATE",
        "ORDER NO.",
        "CALLED/VERIFIED BY",
        "PRODUCT TEAM COMMENTS",
    ]:
        record[header] = normalize_value(
            cells.get(SOURCE_COLUMNS[header], ""),
            is_date=header in DATE_HEADERS,
        )
    record["FINAL DECISION"] = final_decision(cells)


def is_numeric(value: str) -> bool:
    try:
        float(str(value or "").strip())
    except ValueError:
        return False
    return True


def normalize_value(value: str, is_date: bool = False) -> str:
    value = str(value or "").strip().replace("_x000D_", " ")
    value = " ".join(value.split())
    if is_date:
        return normalize_date(value)
    return value


def normalize_date(value: str) -> str:
    if not value:
        return ""
    for date_format in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d-%b-%Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(value, date_format).strftime("%d-%b-%Y")
        except ValueError:
            continue
    try:
        serial = float(value)
    except ValueError:
        return value
    if serial < 30000 or serial > 70000:
        return value

    # Excel's 1900 date system is represented by the 1899-12-30 epoch.
    converted = datetime(1899, 12, 30) + timedelta(days=serial)
    return converted.strftime("%d-%b-%Y")


def looks_like_date(value: str) -> bool:
    value = str(value or "").strip()
    return "/" in value or "-" in value


def column_reference_to_index(reference: str) -> int:
    letters = "".join(char for char in reference if char.isalpha())
    column_index = 0
    for letter in letters:
        column_index = column_index * 26 + ord(letter.upper()) - 64
    return column_index


def write_workbook(path: Path, records: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml())
        archive.writestr("_rels/.rels", root_relationships_xml())
        archive.writestr("docProps/app.xml", app_properties_xml())
        archive.writestr("docProps/core.xml", core_properties_xml())
        archive.writestr("xl/workbook.xml", workbook_xml())
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_relationships_xml())
        archive.writestr("xl/styles.xml", styles_xml())
        archive.writestr("xl/worksheets/sheet1.xml", worksheet_xml(records))


def content_types_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
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


def app_properties_xml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Python</Application>
  <DocSecurity>0</DocSecurity>
  <ScaleCrop>false</ScaleCrop>
  <HeadingPairs>
    <vt:vector size="2" baseType="variant">
      <vt:variant><vt:lpstr>Worksheets</vt:lpstr></vt:variant>
      <vt:variant><vt:i4>1</vt:i4></vt:variant>
    </vt:vector>
  </HeadingPairs>
  <TitlesOfParts>
    <vt:vector size="1" baseType="lpstr"><vt:lpstr>{xml_escape(OUTPUT_SHEET_NAME)}</vt:lpstr></vt:vector>
  </TitlesOfParts>
</Properties>
"""


def core_properties_xml() -> str:
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>Order Approval Redesigned</dc:title>
  <dc:creator>HB Biogas Telegram Bot</dc:creator>
  <cp:lastModifiedBy>HB Biogas Telegram Bot</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:modified>
</cp:coreProperties>
"""


def workbook_xml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="{xml_escape(OUTPUT_SHEET_NAME)}" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>
"""


def workbook_relationships_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
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


def worksheet_xml(records: list[dict[str, str]]) -> str:
    rows = [row_xml(1, HEADERS, style_index=1)]
    for row_number, record in enumerate(records, start=2):
        rows.append(row_xml(row_number, [record.get(header, "") for header in HEADERS]))

    last_cell = f"{column_letter(len(HEADERS))}{max(len(records) + 1, 1)}"
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="A1:{last_cell}"/>
  <sheetViews>
    <sheetView workbookViewId="0">
      <pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>
    </sheetView>
  </sheetViews>
  <sheetFormatPr defaultRowHeight="15"/>
  <cols>
    <col min="1" max="4" width="16" customWidth="1"/>
    <col min="5" max="5" width="14" customWidth="1"/>
    <col min="6" max="6" width="28" customWidth="1"/>
    <col min="7" max="10" width="18" customWidth="1"/>
    <col min="11" max="11" width="34" customWidth="1"/>
    <col min="12" max="29" width="18" customWidth="1"/>
  </cols>
  <sheetData>
    {"".join(rows)}
  </sheetData>
  {data_validations_xml(HEADERS, first_data_row=2)}
  <autoFilter ref="A1:{column_letter(len(HEADERS))}1"/>
</worksheet>
"""


def data_validations_xml(headers: list[str], first_data_row: int, last_data_row: int = 5000) -> str:
    validations = []
    validations.extend(dropdown_validation(headers, "IS CUSTOMER CREATED ON IMAB?", ["Yes", "No", "Pending"], first_data_row, last_data_row))
    validations.extend(dropdown_validation(headers, "CREDIT ANALYSIS", ["Approved", "Pending", "Rejected"], first_data_row, last_data_row))
    validations.extend(dropdown_validation(headers, "BACK OFFICE CREDIT ANALYSIS", ["Approved", "Pending", "Rejected"], first_data_row, last_data_row))
    validations.extend(dropdown_validation(headers, "DOCUMENTATION COMPLETE?", ["Yes", "No", "Pending"], first_data_row, last_data_row))
    validations.extend(dropdown_validation(headers, "FINAL DECISION", ["Approved", "Rejected", "Deferred", "Cash", "Under Review"], first_data_row, last_data_row))
    validations.extend(custom_phone_validation(headers, "CONTACTS / PRIMARY", first_data_row, last_data_row))
    validations.extend(custom_phone_validation(headers, "CONTACTS / SECONDARY", first_data_row, last_data_row))
    validations.extend(decimal_validation(headers, "DEPOSIT / HB", first_data_row, last_data_row))
    validations.extend(decimal_validation(headers, "DEPOSIT / JBL", first_data_row, last_data_row))
    validations.extend(integer_validation(headers, "CUSTOMER NO", first_data_row, last_data_row))
    for header in DATE_HEADERS:
        validations.extend(date_validation(headers, header, first_data_row, last_data_row))
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
