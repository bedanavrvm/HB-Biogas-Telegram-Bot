"""Bounded, self-contained media previews for Telegram Mini Apps."""
from __future__ import annotations

import base64
from html import escape as html_escape
from io import BytesIO


PDF_PREVIEW_MAX_SOURCE_BYTES = 16 * 1024 * 1024
PDF_PREVIEW_MAX_PAGES = 8
PDF_PREVIEW_MAX_RENDERED_BYTES = 10 * 1024 * 1024
PDF_PREVIEW_SCALE = 1.25


def pdf_preview_html(content: bytes, filename: str) -> bytes:
    """Render bounded PDF pages into a self-contained WebView-safe document."""
    if not content or len(content) > PDF_PREVIEW_MAX_SOURCE_BYTES:
        raise ValueError('This PDF is too large for an in-app preview.')

    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(content)
    total_pages = len(document)
    if not total_pages:
        raise ValueError('This PDF has no pages to preview.')
    page_count = min(total_pages, PDF_PREVIEW_MAX_PAGES)
    rendered_bytes = 0
    page_images: list[str] = []
    try:
        for page_index in range(page_count):
            page = document[page_index]
            bitmap = page.render(scale=PDF_PREVIEW_SCALE)
            image = bitmap.to_pil().convert('RGB')
            output = BytesIO()
            image.save(output, format='JPEG', quality=82, optimize=True)
            encoded = output.getvalue()
            rendered_bytes += len(encoded)
            if rendered_bytes > PDF_PREVIEW_MAX_RENDERED_BYTES:
                raise ValueError('This PDF is too detailed for an in-app preview.')
            page_images.append(base64.b64encode(encoded).decode('ascii'))
    finally:
        document.close()

    continuation = (
        f'<p class="notice">Showing the first {page_count} of {total_pages} pages.</p>'
        if total_pages > page_count else ''
    )
    image_markup = ''.join(
        f'<figure><figcaption>Page {index}</figcaption>'
        f'<img src="data:image/jpeg;base64,{encoded}" alt="{html_escape(filename)} - page {index}"></figure>'
        for index, encoded in enumerate(page_images, start=1)
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
</style></head><body><header>{html_escape(filename)}</header>{continuation}{image_markup}</body></html>'''.encode('utf-8')
