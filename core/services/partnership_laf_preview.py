"""In-process populated preview renderer for the approved Partnership LAF."""

from __future__ import annotations

from io import BytesIO
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas


class PartnershipLafPreviewError(RuntimeError):
    pass


def _approved_assets(
    *, document_type: str = 'partnership_loan_application', version: int = 1,
    expected_sha256: str = '',
) -> tuple[bytes, dict[str, Any]]:
    try:
        from core.services.origination_templates import OriginationTemplateError, load_active_template
        return load_active_template(
            document_type, version=version, expected_sha256=expected_sha256,
        )
    except OriginationTemplateError as exc:
        raise PartnershipLafPreviewError(str(exc)) from exc


def _display_value(value: Any) -> str:
    if value is None or value == '':
        return ''
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    return str(value).strip()


def _formatted_value(value: Any, spec: dict[str, Any]) -> str:
    text = _display_value(value)
    if not text:
        return ''
    value_format = str(spec.get('value_format') or '')
    if value_format == 'money':
        try:
            return f'{Decimal(text):,.2f}'
        except (InvalidOperation, ValueError):
            return text
    if value_format in {'date_dmy', 'date_long'}:
        try:
            parsed = date.fromisoformat(text)
            return parsed.strftime('%d/%m/%Y' if value_format == 'date_dmy' else '%d %b %Y')
        except ValueError:
            return text
    return text


def _draw_cell(pdf, value: Any, box: dict[str, float], spec: dict[str, Any], defaults: dict) -> None:
    text = _formatted_value(value, spec)
    if not text:
        return
    font_name = str(spec.get('font') or defaults.get('font') or 'Helvetica')
    font_size = float(spec.get('font_size') or defaults.get('font_size') or 8)
    min_size = float(spec.get('min_font_size') or defaults.get('min_font_size') or 5)
    width_available = max(float(box['width']), 1)
    while font_size > min_size and pdfmetrics.stringWidth(text, font_name, font_size) > width_available:
        font_size -= .25
    while text and pdfmetrics.stringWidth(text, font_name, font_size) > width_available:
        text = text[:-1]
    if not text:
        return
    text_width = pdfmetrics.stringWidth(text, font_name, font_size)
    align = spec.get('align', defaults.get('align', 'left'))
    draw_x = box['x'] + (width_available - text_width) / 2 if align == 'center' else box['x'] + width_available - text_width if align == 'right' else box['x']
    try:
        ascent, descent = pdfmetrics.getAscentDescent(font_name, font_size)
    except KeyError:
        font_name = 'Helvetica'
        ascent, descent = pdfmetrics.getAscentDescent(font_name, font_size)
    draw_y = box['y'] + max((box['height'] - (ascent - descent)) / 2, 0) - descent
    pdf.setFont(font_name, font_size)
    pdf.drawString(draw_x, draw_y, text)


def _normalized_checkbox_value(value: Any) -> str:
    return _display_value(value).casefold().replace('_', ' ').replace('-', ' ')


def _checkbox_is_checked(actual: Any, expected: Any, *, display_value: Any = None) -> bool:
    actual_values = {_normalized_checkbox_value(actual), _normalized_checkbox_value(display_value)} - {''}
    if isinstance(expected, list):
        expected_values = {_normalized_checkbox_value(item) for item in expected}
        return bool(actual_values & expected_values)
    if expected is not None and expected != '':
        return _normalized_checkbox_value(expected) in actual_values
    return bool(actual_values & {'yes', 'true', '1', 'x'})


def _overlay_page(width: float, height: float, fields: list[tuple[dict, Any, Any]], defaults: dict) -> bytes:
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=(width, height), pageCompression=1)
    pdf.setFillColorRGB(0.04, 0.04, 0.04)
    for spec, raw_value, condition_value in fields:
        box = spec.get('allowed_area') or spec.get('box') or {}
        unit_scale = 72 / 25.4 if spec.get('units', 'pt') == 'mm' else 1
        if spec.get('render_as') == 'repeating_table':
            rows = max(int(spec.get('rows') or 1), 1)
            items = raw_value if isinstance(raw_value, list) else []
            x = float(box.get('x', 0)) * unit_scale
            y = float(box.get('y', 0)) * unit_scale
            table_width = float(box.get('width', 0)) * unit_scale
            table_height = float(box.get('height', 0)) * unit_scale
            row_height = table_height / rows
            columns = [item for item in (spec.get('columns') or []) if isinstance(item, dict)]
            for row_index, item in enumerate(items[:rows]):
                if not isinstance(item, dict):
                    continue
                cursor = 0.0
                for column_index, column in enumerate(columns):
                    width_ratio = float(column.get('width_ratio') or (1 / max(len(columns), 1)))
                    x_ratio = float(column.get('x_ratio')) if column.get('x_ratio') is not None else cursor
                    cursor = x_ratio + width_ratio
                    cell = {
                        'x': x + table_width * x_ratio + 3,
                        'y': y + table_height - ((row_index + 1) * row_height),
                        'width': max(table_width * width_ratio - 6, 1),
                        'height': row_height,
                    }
                    _draw_cell(pdf, item.get(str(column.get('key') or '')), cell, column, defaults)
            continue
        value = _formatted_value(raw_value, spec)
        if spec.get('render_as') == 'checkbox':
            if _checkbox_is_checked(condition_value, spec.get('checked_when'), display_value=raw_value):
                x, y = float(box.get('x', 0)) * unit_scale, float(box.get('y', 0)) * unit_scale
                box_width, box_height = float(box.get('width', 0)) * unit_scale, float(box.get('height', 0)) * unit_scale
                size = max(min(box_width, box_height), 1)
                pdf.setLineWidth(max(size * .12, 1.1))
                pdf.line(x + size * .18, y + size * .48, x + size * .42, y + size * .24)
                pdf.line(x + size * .42, y + size * .24, x + size * .84, y + size * .76)
            continue
        if not value:
            continue
        x, y = float(box.get('x', 0)) * unit_scale, float(box.get('y', 0)) * unit_scale
        width_available = max(float(box.get('width', 0)) * unit_scale, 1)
        height_available = max(float(box.get('height', 0)) * unit_scale, 1)
        padding = spec.get('padding', defaults.get('padding', 0))
        padding_x = float(padding.get('x', 0) if isinstance(padding, dict) else padding or 0) * unit_scale
        padding_y = float(padding.get('y', 0) if isinstance(padding, dict) else padding or 0) * unit_scale
        x, y = x + padding_x, y + padding_y
        width_available, height_available = max(width_available - 2 * padding_x, 1), max(height_available - 2 * padding_y, 1)
        font_name = str(spec.get('font') or defaults.get('font') or 'Helvetica')
        font_size = float(spec.get('font_size') or defaults.get('font_size') or 8)
        min_size = float(spec.get('min_font_size') or defaults.get('min_font_size') or 5)
        text_case = spec.get('text_case', defaults.get('text_case', 'none'))
        value = value.upper() if text_case == 'uppercase' else value.lower() if text_case == 'lowercase' else value.title() if text_case == 'titlecase' else value
        fit = spec.get('fit', defaults.get('fit', 'shrink'))
        while fit == 'shrink' and font_size > min_size and pdfmetrics.stringWidth(value, font_name, font_size) > width_available:
            font_size -= 0.25
        if fit != 'overflow' and pdfmetrics.stringWidth(value, font_name, font_size) > width_available:
            while value and pdfmetrics.stringWidth(f'{value}...', font_name, font_size) > width_available:
                value = value[:-1]
            value = f'{value}...' if value else ''
        if not value:
            continue
        text_width = pdfmetrics.stringWidth(value, font_name, font_size)
        align = spec.get('align', defaults.get('align', 'left'))
        draw_x = x + (width_available - text_width) / 2 if align == 'center' else x + width_available - text_width if align == 'right' else x
        vertical = spec.get('vertical_align', defaults.get('vertical_align', 'bottom'))
        try:
            ascent, descent = pdfmetrics.getAscentDescent(font_name, font_size)
        except KeyError:
            font_name = 'Helvetica'
            ascent, descent = pdfmetrics.getAscentDescent(font_name, font_size)
        draw_y = y + max((height_available - (ascent - descent)) / 2, 0) - descent if vertical in {'middle', 'center'} else y + height_available - ascent if vertical == 'top' else y - descent
        pdf.setFont(font_name, font_size)
        pdf.drawString(draw_x, draw_y, value)
    pdf.save()
    return output.getvalue()


def _signature_preview_page(width: float, height: float, slots: list[dict]) -> bytes:
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=(width, height), pageCompression=1)
    pdf.setStrokeColorRGB(0.48, 0.23, 0.93)
    pdf.setFillColorRGB(0.34, 0.12, 0.65)
    pdf.setDash(4, 3)
    for spec in slots:
        box = spec.get('allowed_area') or spec.get('box') or {}
        unit_scale = 72 / 25.4 if spec.get('units', 'pt') == 'mm' else 1
        try:
            x = float(box.get('x', 0)) * unit_scale
            y = float(box.get('y', 0)) * unit_scale
            box_width = float(box.get('width', 0)) * unit_scale
            box_height = float(box.get('height', 0)) * unit_scale
        except (TypeError, ValueError):
            continue
        pdf.rect(x, y, box_width, box_height, stroke=1, fill=0)
        pdf.setFont('Helvetica-Bold', 6)
        label = str(spec.get('label') or spec.get('slot_key') or 'Signature slot')
        pdf.drawString(x + 3, y + max(3, box_height - 8), label[:72])
        padding = spec.get('padding') if isinstance(spec.get('padding'), dict) else {}
        try:
            padding_x = max(0, float(padding.get('x', 0)) * unit_scale)
            padding_y = max(0, float(padding.get('y', 0)) * unit_scale)
            rotation = float(spec.get('rotation', 0))
        except (TypeError, ValueError):
            padding_x = padding_y = rotation = 0
        content_x = -box_width / 2 + padding_x
        content_y = -box_height / 2 + padding_y
        content_width = max(1, box_width - padding_x * 2)
        content_height = max(1, box_height - padding_y * 2)
        slot_type = str(spec.get('slot_type') or 'signature')
        pdf.saveState()
        pdf.translate(x + box_width / 2, y + box_height / 2)
        pdf.rotate(rotation)
        if slot_type == 'stamp':
            stretch = str(spec.get('stamp_fit') or 'contain') == 'stretch'
            stamp_width = content_width if stretch else content_width * .72
            stamp_height = content_height if stretch else content_height * .72
            align = str(spec.get('align') or 'center')
            vertical = str(spec.get('vertical_align') or 'center')
            stamp_x = content_x if align == 'left' else content_x + content_width - stamp_width if align == 'right' else content_x + (content_width - stamp_width) / 2
            stamp_y = content_y if vertical == 'bottom' else content_y + content_height - stamp_height if vertical == 'top' else content_y + (content_height - stamp_height) / 2
            pdf.setStrokeColorRGB(.72, .12, .12)
            pdf.rect(stamp_x, stamp_y, stamp_width, stamp_height, stroke=1, fill=0)
            pdf.setFillColorRGB(.72, .12, .12)
            pdf.setFont('Helvetica-Bold', min(10, max(5, stamp_height * .3)))
            pdf.drawCentredString(stamp_x + stamp_width / 2, stamp_y + stamp_height * .4, 'STAMP PREVIEW')
        else:
            ink = {
                'black': (0.09, 0.14, 0.12),
                'blue': (0.04, 0.24, 0.58),
                'purple': (0.34, 0.12, 0.65),
            }.get(str(spec.get('ink_color') or 'black'), (0.09, 0.14, 0.12))
            pdf.setFillColorRGB(*ink)
            font_name = str(spec.get('typed_font') or 'Helvetica-BoldOblique')
            value = 'Signed date' if slot_type == 'date_signed' else 'Sample signature'
            try:
                font_size = float(spec.get('font_size') or 15)
                text_width = max(1, pdf.stringWidth(value, font_name, font_size))
            except (TypeError, ValueError, KeyError):
                font_name, font_size = 'Helvetica-BoldOblique', 15
                text_width = max(1, pdf.stringWidth(value, font_name, font_size))
            horizontal_scale = min(1, max(.1, content_width / text_width))
            vertical = str(spec.get('vertical_align') or 'center')
            text_y = content_y if vertical == 'bottom' else content_y + max(0, content_height - font_size) if vertical == 'top' else content_y + max(0, (content_height - font_size) / 2)
            align = str(spec.get('align') or 'center')
            anchor_x = content_x if align == 'left' else content_x + content_width if align == 'right' else content_x + content_width / 2
            pdf.translate(anchor_x, text_y)
            pdf.scale(horizontal_scale, 1)
            pdf.setFont(font_name, font_size)
            if align == 'left':
                pdf.drawString(0, 0, value)
            elif align == 'right':
                pdf.drawRightString(0, 0, value)
            else:
                pdf.drawCentredString(0, 0, value)
        pdf.restoreState()
    pdf.save()
    return output.getvalue()


def render_template(source: bytes, config: dict[str, Any], context: dict[str, Any]) -> bytes:
    reader = PdfReader(BytesIO(source))
    fields_by_page: dict[int, list[tuple[dict, Any, Any]]] = {}
    overlay_manifest = config.get('field_overlay_manifest') or {}
    manifest = overlay_manifest.get('fields') or {}
    defaults = overlay_manifest.get('defaults') or {}
    canonical_values = context.get('_canonical_values') if isinstance(context.get('_canonical_values'), dict) else {}
    for spec in manifest.values():
        if not isinstance(spec, dict):
            continue
        page_number = int(spec.get('page_number') or 1)
        context_key = str(spec.get('context_key') or '')
        display_value = context.get(context_key)
        condition_value = canonical_values.get(context_key, display_value)
        fields_by_page.setdefault(page_number, []).append((spec, display_value, condition_value))
    signature_slots_by_page: dict[int, list[dict]] = {}
    if context.get('_show_signature_slots'):
        signature_manifest = (config.get('signature_overlay_manifest') or {}).get('slots') or {}
        for spec in signature_manifest.values():
            if not isinstance(spec, dict):
                continue
            page_number = int(spec.get('page_number') or 1)
            signature_slots_by_page.setdefault(page_number, []).append(spec)

    writer = PdfWriter()
    for index, page in enumerate(reader.pages, start=1):
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        overlay = _overlay_page(width, height, fields_by_page.get(index, []), defaults)
        overlay_page = PdfReader(BytesIO(overlay)).pages[0]
        page.merge_page(overlay_page, over=True)
        if signature_slots_by_page.get(index):
            signature_overlay = _signature_preview_page(
                width, height, signature_slots_by_page[index],
            )
            page.merge_page(PdfReader(BytesIO(signature_overlay)).pages[0], over=True)
        writer.add_page(page)
    output = BytesIO()
    writer.write(output)
    result = output.getvalue()
    if not result.startswith(b'%PDF'):
        raise PartnershipLafPreviewError('The populated Partnership LAF could not be generated.')
    return result


def render_partnership_laf(
    context: dict[str, Any], *, version: int = 1, expected_sha256: str = '',
    configuration: dict[str, Any] | None = None,
) -> bytes:
    return render_origination_document(
        context,
        document_type='partnership_loan_application',
        version=version,
        expected_sha256=expected_sha256,
        configuration=configuration,
    )


def render_origination_document(
    context: dict[str, Any], *, document_type: str, version: int = 1,
    expected_sha256: str = '', configuration: dict[str, Any] | None = None,
) -> bytes:
    """Render any published origination product PDF using its calibrated overlays."""
    source, config = _approved_assets(
        document_type=document_type, version=version, expected_sha256=expected_sha256,
    )
    return render_template(source, configuration or config, context)


def render_pdf_page(pdf_data: bytes, *, page_number: int, scale: float = 1.5) -> tuple[bytes, int]:
    """Render one populated page for Telegram WebViews that cannot paint PDF blobs."""
    try:
        import pypdfium2 as pdfium

        document = pdfium.PdfDocument(pdf_data)
        total_pages = len(document)
        try:
            if page_number < 1 or page_number > total_pages:
                raise PartnershipLafPreviewError('The requested preview page does not exist.')
            page = document[page_number - 1]
            bitmap = page.render(scale=max(0.75, min(float(scale), 2.5)))
            image = bitmap.to_pil().convert('RGB')
            output = BytesIO()
            image.save(output, format='JPEG', quality=86, optimize=True)
            return output.getvalue(), total_pages
        finally:
            document.close()
    except PartnershipLafPreviewError:
        raise
    except Exception as exc:
        raise PartnershipLafPreviewError('The populated preview page could not be rendered.') from exc
