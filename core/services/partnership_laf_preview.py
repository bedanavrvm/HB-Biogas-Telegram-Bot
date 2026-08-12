"""In-process populated preview renderer for the approved Partnership LAF."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any

from django.conf import settings
from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


APPROVED_TEMPLATE_SHA256 = '5e7d264c0cf3e4264e9ab768fd89a4fd1dab131eedd733cce439ce11c6e345f1'


class PartnershipLafPreviewError(RuntimeError):
    pass


def _asset_paths() -> tuple[Path, Path]:
    source = Path(getattr(
        settings, 'ORIGINATION_LAF_TEMPLATE_PATH',
        settings.BASE_DIR / 'e-signatures' / 'JBL' / 'Jawabu Partnership LAF.pdf',
    ))
    config = Path(getattr(
        settings, 'ORIGINATION_LAF_CONFIG_PATH',
        settings.BASE_DIR / 'e-signatures' / 'JBL' / 'partnership_laf_template_config.json',
    ))
    return source, config


@lru_cache(maxsize=1)
def _approved_assets() -> tuple[bytes, dict[str, Any]]:
    source_path, config_path = _asset_paths()
    if not source_path.is_file() or not config_path.is_file():
        raise PartnershipLafPreviewError('The approved Partnership LAF template assets are unavailable.')
    source = source_path.read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    if digest != APPROVED_TEMPLATE_SHA256:
        raise PartnershipLafPreviewError('The Partnership LAF template failed integrity verification.')
    try:
        config = json.loads(config_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise PartnershipLafPreviewError('The Partnership LAF placement configuration is invalid.') from exc
    if config.get('document_type') != 'partnership_loan_application' or int(config.get('version') or 0) != 1:
        raise PartnershipLafPreviewError('The Partnership LAF placement configuration is not approved.')
    return source, config


def _display_value(value: Any) -> str:
    if value is None or value == '':
        return ''
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    return str(value).strip()


def _overlay_page(width: float, height: float, fields: list[tuple[dict, str]]) -> bytes:
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=(width, height), pageCompression=1)
    pdf.setFillColorRGB(0.04, 0.04, 0.04)
    for spec, raw_value in fields:
        box = spec.get('box') or {}
        value = _display_value(raw_value)
        if spec.get('render_as') == 'checkbox':
            expected = spec.get('checked_when')
            checked = value == _display_value(expected) if expected is not None else value.casefold() in {'yes', 'true', '1', 'x'}
            value = 'X' if checked else ''
        if not value:
            continue
        x, y = float(box.get('x', 0)), float(box.get('y', 0))
        width_available = max(float(box.get('width', 0)), 1)
        height_available = max(float(box.get('height', 0)), 1)
        font_name = str(spec.get('font') or 'Helvetica')
        font_size = float(spec.get('font_size') or 8)
        min_size = float(spec.get('min_font_size') or 5)
        while font_size > min_size and stringWidth(value, font_name, font_size) > width_available:
            font_size -= 0.25
        if stringWidth(value, font_name, font_size) > width_available:
            while value and stringWidth(f'{value}...', font_name, font_size) > width_available:
                value = value[:-1]
            value = f'{value}...' if value else ''
        if not value:
            continue
        text_width = stringWidth(value, font_name, font_size)
        align = spec.get('align', 'left')
        draw_x = x + (width_available - text_width) / 2 if align == 'center' else x + width_available - text_width if align == 'right' else x
        vertical = spec.get('vertical_align', 'bottom')
        draw_y = y + max((height_available - font_size) / 2, 0) if vertical in {'middle', 'center'} else y
        pdf.setFont(font_name, font_size)
        pdf.drawString(draw_x, draw_y, value)
    pdf.save()
    return output.getvalue()


def render_partnership_laf(context: dict[str, Any]) -> bytes:
    source, config = _approved_assets()
    reader = PdfReader(BytesIO(source))
    fields_by_page: dict[int, list[tuple[dict, str]]] = {}
    manifest = (config.get('field_overlay_manifest') or {}).get('fields') or {}
    for spec in manifest.values():
        if not isinstance(spec, dict):
            continue
        page_number = int(spec.get('page_number') or 1)
        fields_by_page.setdefault(page_number, []).append((spec, context.get(spec.get('context_key'))))

    writer = PdfWriter()
    for index, page in enumerate(reader.pages, start=1):
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        overlay = _overlay_page(width, height, fields_by_page.get(index, []))
        overlay_page = PdfReader(BytesIO(overlay)).pages[0]
        page.merge_page(overlay_page, over=True)
        writer.add_page(page)
    output = BytesIO()
    writer.write(output)
    result = output.getvalue()
    if not result.startswith(b'%PDF'):
        raise PartnershipLafPreviewError('The populated Partnership LAF could not be generated.')
    return result
