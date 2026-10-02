"""Bounded, self-contained media previews for Telegram Mini Apps."""
from __future__ import annotations

import base64
import math
import time
import json
import subprocess
import sys
from pathlib import Path
from html import escape as html_escape
from io import BytesIO


PDF_PREVIEW_MAX_SOURCE_BYTES = 16 * 1024 * 1024
PDF_PREVIEW_MAX_PAGES = 8
PDF_PREVIEW_MAX_RENDERED_BYTES = 10 * 1024 * 1024
PDF_PREVIEW_SCALE = 1.25
PDF_PREVIEW_MAX_PAGE_PIXELS = 12_000_000
PDF_PREVIEW_MAX_TOTAL_PIXELS = 40_000_000
PDF_PREVIEW_MAX_SECONDS = 15


def pdf_preview_html(
    content: bytes, filename: str, *, password: str | None = None,
    show_filename: bool = True, show_single_page_caption: bool = True,
    start_page: int = 1,
    page_limit: int = PDF_PREVIEW_MAX_PAGES,
) -> bytes:
    """Keep native PDF rendering out of the web worker with a hard deadline."""
    if not content or len(content) > PDF_PREVIEW_MAX_SOURCE_BYTES:
        raise ValueError('This PDF is too large for an in-app preview.')
    options = json.dumps({'filename': filename, 'password': password,
                          'show_filename': show_filename, 'show_single_page_caption': show_single_page_caption,
                          'start_page': start_page, 'page_limit': page_limit})
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'scripts.invoice_pdf_worker', 'preview'],
            cwd=Path(__file__).resolve().parents[2],
            input=options.encode() + b'\n' + content, capture_output=True,
            timeout=PDF_PREVIEW_MAX_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError('This PDF took too long to preview. Download it instead.') from exc
    if result.returncode:
        raise ValueError('This PDF could not be previewed safely. Download it instead.')
    if len(result.stdout) > PDF_PREVIEW_MAX_RENDERED_BYTES * 2:
        raise ValueError('This PDF is too detailed for an in-app preview.')
    return result.stdout


def _pdf_preview_html(
    content: bytes,
    filename: str,
    *,
    password: str | None = None,
    show_filename: bool = True,
    show_single_page_caption: bool = True,
    start_page: int = 1,
    page_limit: int = PDF_PREVIEW_MAX_PAGES,
) -> bytes:
    """Render bounded PDF pages into a self-contained WebView-safe document."""
    if not content or len(content) > PDF_PREVIEW_MAX_SOURCE_BYTES:
        raise ValueError('This PDF is too large for an in-app preview.')

    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(content, password=password or None)
    rendered_bytes = 0
    total_pixels = 0
    started = time.monotonic()
    page_images: list[str] = []
    try:
        total_pages = len(document)
        if not total_pages:
            raise ValueError('This PDF has no pages to preview.')
        first_page = max(0, min(int(start_page) - 1, total_pages - 1))
        page_count = min(total_pages - first_page, max(1, min(int(page_limit), PDF_PREVIEW_MAX_PAGES)))
        for page_index in range(first_page, first_page + page_count):
            if time.monotonic() - started > PDF_PREVIEW_MAX_SECONDS:
                raise ValueError('This PDF is too detailed for an in-app preview. Download it instead.')
            page = document[page_index]
            bitmap = image = None
            try:
                width, height = page.get_size()
                if not all(math.isfinite(value) and value > 0 for value in (width, height)):
                    raise ValueError('This PDF has invalid page dimensions.')
                pixels = math.ceil(width * PDF_PREVIEW_SCALE) * math.ceil(height * PDF_PREVIEW_SCALE)
                total_pixels += pixels
                if pixels > PDF_PREVIEW_MAX_PAGE_PIXELS or total_pixels > PDF_PREVIEW_MAX_TOTAL_PIXELS:
                    raise ValueError('This PDF is too detailed for an in-app preview. Download it instead.')
                bitmap = page.render(scale=PDF_PREVIEW_SCALE)
                image = bitmap.to_pil().convert('RGB')
                with BytesIO() as output:
                    image.save(output, format='JPEG', quality=82, optimize=True)
                    encoded = output.getvalue()
            finally:
                if image is not None:
                    image.close()
                if bitmap is not None:
                    bitmap.close()
                page.close()
            rendered_bytes += len(encoded)
            if rendered_bytes > PDF_PREVIEW_MAX_RENDERED_BYTES:
                raise ValueError('This PDF is too detailed for an in-app preview.')
            page_images.append(base64.b64encode(encoded).decode('ascii'))
    finally:
        document.close()

    continuation = (
        f'<p class="notice">Showing pages {first_page + 1}–{first_page + page_count} of {total_pages}.</p>'
        if total_pages > page_count else ''
    )
    image_markup = ''.join(
        f'<figure>{f"<figcaption>Page {index}</figcaption>" if total_pages > 1 or show_single_page_caption else ""}'
        f'<img src="data:image/jpeg;base64,{encoded}" alt="{html_escape(filename)} - page {index}"></figure>'
        for index, encoded in enumerate(page_images, start=first_page + 1)
    )
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; padding: 12px; background: #f2f4f7; color: #1d2939; font: 14px system-ui, sans-serif; }}
  header {{ position: sticky; top: 0; z-index: 1; padding: 8px 4px 10px; background: #f2f4f7; font-weight: 700; }}
  figure {{ margin: 0 auto 14px; max-width: 980px; background: #fff; box-shadow: 0 1px 3px rgba(16,24,40,.16); }}
  figcaption {{ padding: 7px 10px; color: #667085; font-size: 12px; }}
  img {{ display: block; width: 100%; height: auto; }}
  .notice {{ max-width: 980px; margin: 0 auto 12px; padding: 8px 10px; border-radius: 6px; background: #fff4e5; color: #7a4d00; }}
</style></head><body>{f"<header>{html_escape(filename)}</header>" if show_filename else ""}{continuation}{image_markup}</body></html>'''.encode('utf-8')
