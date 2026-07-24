"""Render a generated workbook print area to a portable PDF without browser printing."""

from __future__ import annotations

import base64
import io
from html import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Table, TableStyle


def _color(value: str, fallback=colors.white):
    try:
        return colors.HexColor(value) if value else fallback
    except ValueError:
        return fallback


def _image_flowable(image: dict, max_width: float, max_height: float):
    data_url = str(image.get('data_url') or '')
    if ',' not in data_url:
        return None
    try:
        raw = base64.b64decode(data_url.split(',', 1)[1])
        reader = ImageReader(io.BytesIO(raw))
        width = min(float(image.get('width') or max_width), max_width)
        height = min(float(image.get('height') or max_height), max_height)
        return Image(reader, width=max(1, width), height=max(1, height))
    except Exception:
        return None


def workbook_preview_to_pdf(preview: dict) -> bytes:
    """Create a landscape PDF from the active sheet serialized by workbook_preview."""
    sheets = preview.get('sheets') or []
    if not sheets:
        raise ValueError('The generated workbook has no printable sheet.')
    sheet = sheets[0]
    columns = sheet.get('columns') or []
    rows = [row for row in (sheet.get('rows') or []) if not row.get('hidden')]
    if not columns or not rows:
        raise ValueError('The workbook print area is empty.')

    page_size = landscape(A4)
    margin = 18
    available_width = page_size[0] - (margin * 2)
    raw_widths = [0 if col.get('hidden') else max(18, float(col.get('width') or 13) * 7) for col in columns]
    width_scale = min(1, available_width / max(1, sum(raw_widths)))
    col_widths = [max(1, width * width_scale) for width in raw_widths]
    row_heights = [max(10, float(row.get('height') or 18) * min(1, width_scale + .2)) for row in rows]
    image_map = {(int(item['row']), int(item['column'])): item for item in (sheet.get('images') or [])}
    normal = ParagraphStyle('WorkbookCell', fontName='Helvetica', fontSize=6.5, leading=7.5, textColor=colors.black)

    matrix = [['' for _ in columns] for _ in rows]
    commands = [('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('LEFTPADDING', (0, 0), (-1, -1), 3),
                ('RIGHTPADDING', (0, 0), (-1, -1), 3), ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2)]
    for row_index, row in enumerate(rows):
        for cell in row.get('cells') or []:
            column_index = int(cell.get('column') or 1) - 1
            if not 0 <= column_index < len(columns):
                continue
            style = cell.get('style') or {}
            text_style = ParagraphStyle(
                f'Cell-{row_index}-{column_index}', parent=normal,
                fontName='Helvetica-Bold' if style.get('bold') else 'Helvetica',
                fontSize=max(5, min(11, float(style.get('font_size') or 11) * .62)),
                leading=max(6, min(13, float(style.get('font_size') or 11) * .72)),
                textColor=_color(style.get('color'), colors.black),
                alignment={'center': 1, 'right': 2}.get(style.get('horizontal'), 0),
            )
            contents = []
            image = image_map.get((int(row.get('number') or row_index + 1), column_index + 1))
            if image:
                rendered_image = _image_flowable(image, col_widths[column_index] * max(1, int(cell.get('col_span') or 1)), row_heights[row_index] * max(1, int(cell.get('row_span') or 1)))
                if rendered_image:
                    contents.append(rendered_image)
            value = str(cell.get('value') or '')
            if value:
                contents.append(Paragraph(escape(value).replace('\n', '<br/>'), text_style))
            matrix[row_index][column_index] = contents if len(contents) > 1 else (contents[0] if contents else '')
            commands.append(('BACKGROUND', (column_index, row_index), (column_index, row_index), _color(style.get('background'))))
            for side, command in (('border_top', 'LINEABOVE'), ('border_right', 'LINEAFTER'), ('border_bottom', 'LINEBELOW'), ('border_left', 'LINEBEFORE')):
                if style.get(side):
                    commands.append((command, (column_index, row_index), (column_index, row_index), 1.2 if style.get(side) in {'medium', 'thick'} else .5, colors.black))
            col_span = max(1, int(cell.get('col_span') or 1))
            row_span = max(1, int(cell.get('row_span') or 1))
            if col_span > 1 or row_span > 1:
                commands.append(('SPAN', (column_index, row_index), (column_index + col_span - 1, row_index + row_span - 1)))

    output = io.BytesIO()
    document = SimpleDocTemplate(
        output, pagesize=page_size, leftMargin=margin, rightMargin=margin,
        topMargin=margin, bottomMargin=margin, title=str(sheet.get('name') or 'Payment Sheet'),
    )
    table = Table(matrix, colWidths=col_widths, rowHeights=row_heights, repeatRows=0)
    table.setStyle(TableStyle(commands))
    document.build([table])
    return output.getvalue()
