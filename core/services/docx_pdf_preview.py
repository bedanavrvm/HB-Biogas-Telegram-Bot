"""Bounded local PDF renditions of generated DOCX letters.

This is intentionally a small WordprocessingML renderer for the governed
invoice-name-change template, not a general Office conversion service. The
final populated DOCX is the input, so the preview cannot substitute different
wording or customer values.
"""
from __future__ import annotations

import base64
import html
import io
import mimetypes
import posixpath
import re
import zipfile
from xml.etree import ElementTree as ET

from pypdf import PdfReader
from weasyprint import HTML


W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
A_NS = 'http://schemas.openxmlformats.org/drawingml/2006/main'
PKG_REL_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'
W = f'{{{W_NS}}}'
R = f'{{{R_NS}}}'
A = f'{{{A_NS}}}'

MAX_DOCX_BYTES = 16 * 1024 * 1024
MAX_EXPANDED_BYTES = 50 * 1024 * 1024
MAX_PDF_BYTES = 16 * 1024 * 1024


class DocxPreviewError(ValueError):
    pass


def _safe_archive(data: bytes) -> zipfile.ZipFile:
    if not data or len(data) > MAX_DOCX_BYTES:
        raise DocxPreviewError('The generated letter is too large to preview.')
    try:
        archive = zipfile.ZipFile(io.BytesIO(data), 'r')
    except zipfile.BadZipFile as exc:
        raise DocxPreviewError('The generated letter is not a valid DOCX file.') from exc
    infos = archive.infolist()
    if len(infos) > 500 or sum(info.file_size for info in infos) > MAX_EXPANDED_BYTES:
        archive.close()
        raise DocxPreviewError('The generated letter expands beyond the preview safety limit.')
    if 'word/document.xml' not in archive.namelist():
        archive.close()
        raise DocxPreviewError('The generated letter has no Word document body.')
    return archive


def _relationships(archive: zipfile.ZipFile, part_name: str) -> dict[str, str]:
    directory, filename = posixpath.split(part_name)
    rel_name = posixpath.join(directory, '_rels', f'{filename}.rels')
    if rel_name not in archive.namelist():
        return {}
    try:
        root = ET.fromstring(archive.read(rel_name))
    except ET.ParseError as exc:
        raise DocxPreviewError('The generated letter contains invalid relationships.') from exc
    relationships: dict[str, str] = {}
    for relation in root.findall(f'{{{PKG_REL_NS}}}Relationship'):
        if str(relation.attrib.get('TargetMode') or '').lower() == 'external':
            continue
        relation_id = str(relation.attrib.get('Id') or '')
        target = str(relation.attrib.get('Target') or '')
        if not relation_id or not target:
            continue
        resolved = posixpath.normpath(posixpath.join(directory, target))
        if resolved.startswith('../') or resolved.startswith('/'):
            continue
        relationships[relation_id] = resolved
    return relationships


def _property_value(element: ET.Element | None, name: str) -> str:
    if element is None:
        return ''
    child = element.find(f'{W}{name}')
    return str(child.attrib.get(f'{W}val') or child.attrib.get('val') or '') if child is not None else ''


def _image_html(archive: zipfile.ZipFile, relationships: dict[str, str], run: ET.Element) -> str:
    images: list[str] = []
    for blip in run.iter(f'{A}blip'):
        target = relationships.get(str(blip.attrib.get(f'{R}embed') or ''))
        if not target or target not in archive.namelist():
            continue
        content = archive.read(target)
        mime_type = mimetypes.guess_type(target)[0] or 'application/octet-stream'
        if not mime_type.startswith('image/'):
            continue
        encoded = base64.b64encode(content).decode('ascii')
        images.append(
            f'<img class="docx-image" src="data:{mime_type};base64,{encoded}" alt="Letter image">'
        )
    return ''.join(images)


def _run_html(archive: zipfile.ZipFile, relationships: dict[str, str], run: ET.Element) -> str:
    properties = run.find(f'{W}rPr')
    if properties is not None and (
        properties.find(f'{W}vanish') is not None
        or properties.find(f'{W}webHidden') is not None
    ):
        return ''
    styles: list[str] = []
    if properties is not None:
        if properties.find(f'{W}b') is not None:
            styles.append('font-weight:700')
        if properties.find(f'{W}i') is not None:
            styles.append('font-style:italic')
        if properties.find(f'{W}u') is not None:
            styles.append('text-decoration:underline')
        size = _property_value(properties, 'sz')
        if size.isdigit():
            styles.append(f'font-size:{max(7, min(30, int(size) / 2))}pt')
    parts: list[str] = []
    for node in run.iter():
        # ``instrText`` is Word field source code (for example a LINK to the
        # spreadsheet used to build the template), never letter content.
        if node.tag == f'{W}t':
            parts.append(html.escape(node.text or ''))
        elif node.tag == f'{W}tab':
            parts.append('&emsp;')
        elif node.tag in {f'{W}br', f'{W}cr'}:
            parts.append('<br>')
    parts.append(_image_html(archive, relationships, run))
    content = ''.join(parts)
    if not content:
        return ''
    style = f' style="{";".join(styles)}"' if styles else ''
    return f'<span{style}>{content}</span>'


def _paragraph_html(archive: zipfile.ZipFile, relationships: dict[str, str], paragraph: ET.Element) -> str:
    properties = paragraph.find(f'{W}pPr')
    alignment = _property_value(properties, 'jc')
    css_alignment = {'center': 'center', 'right': 'right', 'both': 'justify'}.get(alignment, 'left')
    deleted_runs = {
        id(run)
        for deleted in paragraph.iter(f'{W}del')
        for run in deleted.iter(f'{W}r')
    }
    field_stack: list[bool] = []
    rendered_runs: list[str] = []
    for run in paragraph.iter(f'{W}r'):
        if id(run) in deleted_runs:
            continue
        markers = [
            str(node.attrib.get(f'{W}fldCharType') or node.attrib.get(f'{W}type') or '')
            for node in run.iter(f'{W}fldChar')
        ]
        for marker in markers:
            if marker == 'begin':
                field_stack.append(False)
            elif marker == 'separate' and field_stack:
                field_stack[-1] = True
        # Outside a field all text is visible. Inside a field only its cached
        # result, after ``separate``, is visible. This keeps the actual value
        # while suppressing LINK/MERGEFORMAT instructions and local paths.
        if not field_stack or all(field_stack):
            rendered_runs.append(_run_html(archive, relationships, run))
        for marker in markers:
            if marker == 'end' and field_stack:
                field_stack.pop()
    runs = ''.join(rendered_runs)
    return f'<p style="text-align:{css_alignment}">{runs or "&nbsp;"}</p>'


def _cell_html(archive: zipfile.ZipFile, relationships: dict[str, str], cell: ET.Element) -> str:
    properties = cell.find(f'{W}tcPr')
    grid_span = _property_value(properties, 'gridSpan')
    colspan = f' colspan="{int(grid_span)}"' if grid_span.isdigit() and int(grid_span) > 1 else ''
    shading = _property_value(properties, 'shd')
    style = ''
    if shading and re.fullmatch(r'[0-9A-Fa-f]{6}', shading):
        style = f' style="background:#{shading}"'
    content = ''.join(
        _paragraph_html(archive, relationships, child)
        if child.tag == f'{W}p' else _table_html(archive, relationships, child)
        for child in list(cell) if child.tag in {f'{W}p', f'{W}tbl'}
    )
    return f'<td{colspan}{style}>{content}</td>'


def _table_html(archive: zipfile.ZipFile, relationships: dict[str, str], table: ET.Element) -> str:
    rows = []
    for row in table.findall(f'{W}tr'):
        cells = ''.join(_cell_html(archive, relationships, cell) for cell in row.findall(f'{W}tc'))
        rows.append(f'<tr>{cells}</tr>')
    return '<table>' + ''.join(rows) + '</table>'


def _part_html(archive: zipfile.ZipFile, part_name: str) -> str:
    if part_name not in archive.namelist():
        return ''
    try:
        root = ET.fromstring(archive.read(part_name))
    except ET.ParseError as exc:
        raise DocxPreviewError('The generated letter contains invalid document XML.') from exc
    relationships = _relationships(archive, part_name)
    container = root.find(f'{W}body') or root
    rendered: list[str] = []
    for child in list(container):
        if child.tag == f'{W}p':
            rendered.append(_paragraph_html(archive, relationships, child))
        elif child.tag == f'{W}tbl':
            rendered.append(_table_html(archive, relationships, child))
    return ''.join(rendered)


def _header_footer_parts(archive: zipfile.ZipFile) -> tuple[list[str], list[str]]:
    relationships = _relationships(archive, 'word/document.xml')
    root = ET.fromstring(archive.read('word/document.xml'))
    header_ids = [str(node.attrib.get(f'{R}id') or '') for node in root.iter(f'{W}headerReference')]
    footer_ids = [str(node.attrib.get(f'{R}id') or '') for node in root.iter(f'{W}footerReference')]
    return (
        [relationships[item] for item in header_ids if item in relationships],
        [relationships[item] for item in footer_ids if item in relationships],
    )


def _normalise_text(value: str) -> str:
    # PDF text extraction may insert whitespace at table-cell line wraps (even
    # inside an ID or phone number). Compare canonical characters instead.
    return re.sub(r'[^\w]+', '', str(value or ''), flags=re.UNICODE).casefold()


def render_docx_pdf(data: bytes, *, expected_values: list[str] | None = None) -> bytes:
    """Render the populated governed DOCX into a self-contained PDF."""
    archive = _safe_archive(data)
    try:
        headers, footers = _header_footer_parts(archive)
        header_html = ''.join(_part_html(archive, part) for part in headers)
        body_html = _part_html(archive, 'word/document.xml')
        footer_html = ''.join(_part_html(archive, part) for part in footers)
    finally:
        archive.close()
    if not _normalise_text(re.sub(r'<[^>]+>', ' ', body_html)):
        raise DocxPreviewError('The generated letter has no previewable content.')
    document = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><style>
      @page {{ size: A4; margin: 16mm 17mm 18mm; }}
      * {{ box-sizing: border-box; }}
      body {{ margin: 0; color: #111827; font-family: Arial, Helvetica, sans-serif; font-size: 10pt; line-height: 1.35; }}
      header {{ margin-bottom: 7mm; }} footer {{ margin-top: 7mm; }}
      p {{ margin: 0 0 7pt; min-height: 1em; }}
      table {{ width: 100%; margin: 6pt 0 10pt; border-collapse: collapse; table-layout: auto; }}
      td, th {{ padding: 5pt 4pt; border: .6pt solid #9ca3af; vertical-align: top; overflow-wrap: anywhere; }}
      td p, th p {{ margin: 0; }}
      .docx-image {{ display: inline-block; max-width: 100%; max-height: 30mm; object-fit: contain; }}
    </style></head><body><header>{header_html}</header><main>{body_html}</main><footer>{footer_html}</footer></body></html>'''
    try:
        pdf = HTML(string=document).write_pdf()
    except Exception as exc:
        raise DocxPreviewError('The generated letter could not be rendered for preview.') from exc
    if not pdf.startswith(b'%PDF') or len(pdf) > MAX_PDF_BYTES:
        raise DocxPreviewError('The generated letter preview is invalid or too large.')
    if expected_values:
        extracted = _normalise_text(' '.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(pdf)).pages))
        missing = [value for value in expected_values if _normalise_text(value) not in extracted]
        if missing:
            raise DocxPreviewError('The generated preview did not retain every governed letter value.')
    extracted_text = ' '.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(pdf)).pages)
    leaked_field_code = re.search(
        r'(?i)(MERGEFORMAT|LINK\s+(?:Excel|Word)|[A-Z]:\\[^\n]+\.(?:xlsx?|docx?))',
        extracted_text,
    )
    if leaked_field_code:
        raise DocxPreviewError('The generated preview contains hidden template instructions. Repair the letter template and try again.')
    return pdf
