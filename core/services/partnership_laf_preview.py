"""In-process populated preview renderer for the approved Partnership LAF."""

from __future__ import annotations

from io import BytesIO
from typing import Any

from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas


class PartnershipLafPreviewError(RuntimeError):
    pass


def _approved_assets(*, version: int = 1, expected_sha256: str = '') -> tuple[bytes, dict[str, Any]]:
    try:
        from core.services.origination_templates import OriginationTemplateError, load_active_template
        return load_active_template(
            'partnership_loan_application', version=version, expected_sha256=expected_sha256,
        )
    except OriginationTemplateError as exc:
        raise PartnershipLafPreviewError(str(exc)) from exc


def _display_value(value: Any) -> str:
    if value is None or value == '':
        return ''
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    return str(value).strip()


def _overlay_page(width: float, height: float, fields: list[tuple[dict, str]], defaults: dict) -> bytes:
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=(width, height), pageCompression=1)
    pdf.setFillColorRGB(0.04, 0.04, 0.04)
    for spec, raw_value in fields:
        box = spec.get('allowed_area') or spec.get('box') or {}
        unit_scale = 72 / 25.4 if spec.get('units', 'pt') == 'mm' else 1
        value = _display_value(raw_value)
        if spec.get('render_as') == 'checkbox':
            expected = spec.get('checked_when')
            normalized = value.casefold().replace('_', ' ').replace('-', ' ')
            if isinstance(expected, list):
                checked = normalized in {_display_value(item).casefold().replace('_', ' ').replace('-', ' ') for item in expected}
            else:
                checked = normalized == _display_value(expected).casefold().replace('_', ' ').replace('-', ' ') if expected is not None else normalized in {'yes', 'true', '1', 'x'}
            if checked:
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


def render_template(source: bytes, config: dict[str, Any], context: dict[str, Any]) -> bytes:
    reader = PdfReader(BytesIO(source))
    fields_by_page: dict[int, list[tuple[dict, str]]] = {}
    overlay_manifest = config.get('field_overlay_manifest') or {}
    manifest = overlay_manifest.get('fields') or {}
    defaults = overlay_manifest.get('defaults') or {}
    for spec in manifest.values():
        if not isinstance(spec, dict):
            continue
        page_number = int(spec.get('page_number') or 1)
        fields_by_page.setdefault(page_number, []).append((spec, context.get(spec.get('context_key'))))

    writer = PdfWriter()
    for index, page in enumerate(reader.pages, start=1):
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        overlay = _overlay_page(width, height, fields_by_page.get(index, []), defaults)
        overlay_page = PdfReader(BytesIO(overlay)).pages[0]
        page.merge_page(overlay_page, over=True)
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
    source, config = _approved_assets(version=version, expected_sha256=expected_sha256)
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
