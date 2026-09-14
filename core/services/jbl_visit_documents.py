"""Bounded, local-only collation of the two JBL Visit document captures."""
import base64
import hashlib
import io
import logging
import warnings

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)
DOCUMENT_SLOTS = {
    'CLIENT_ID': ('client_id_front', 'client_id_back'),
    'LAF': ('laf_page_1', 'laf_page_2'),
}
SLOT_LABELS = {
    'client_id_front': 'Client ID front', 'client_id_back': 'Client ID back',
    'laf_page_1': 'LAF page 1', 'laf_page_2': 'LAF page 2',
}


class VisitDocumentError(ValueError):
    def __init__(self, message: str, field: str):
        super().__init__(message)
        self.field = field


def validated_image(file_obj, *, field: str) -> bytes:
    """Decode content, reject bombs/animation, strip metadata and normalize EXIF."""
    maximum = max(1, settings.MEDIA_MAX_FILE_SIZE_MB) * 1024 * 1024
    label = SLOT_LABELS.get(field, 'Supporting photo')
    if not 4096 <= int(file_obj.size or 0) <= maximum:
        raise VisitDocumentError(f'{label} must be between 4 KB and {maximum // (1024 * 1024)} MB.', field)
    extension = str(file_obj.name).lower().rsplit('.', 1)[-1]
    if extension not in {'jpg', 'jpeg', 'png', 'webp'}:
        raise VisitDocumentError(f'{label} must be a JPG, PNG or WebP photo.', field)
    try:
        file_obj.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(file_obj) as source:
                expected = {'jpg': 'JPEG', 'jpeg': 'JPEG', 'png': 'PNG', 'webp': 'WEBP'}[extension]
                if source.format != expected or getattr(source, 'n_frames', 1) != 1:
                    raise VisitDocumentError(f'{label} is not a valid single photo.', field)
                if source.width * source.height > 24_000_000 or min(source.size) < 300:
                    raise VisitDocumentError(f'{label} is too small or too large to process. Choose a clear photo.', field)
                image = ImageOps.exif_transpose(source)
                image.load()
                image.thumbnail((3000, 3000), Image.Resampling.LANCZOS)
                # Composite transparency against white instead of losing text.
                rgba = image.convert('RGBA')
                rgb = Image.new('RGB', rgba.size, 'white')
                rgb.paste(rgba, mask=rgba.getchannel('A'))
                output = io.BytesIO()
                rgb.save(output, format='JPEG', quality=92, optimize=True)
                return output.getvalue()
    except VisitDocumentError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning):
        raise VisitDocumentError(f'{label} could not be read. Retake it or choose another photo.', field) from None
    finally:
        file_obj.seek(0)


def render_document(category: str, images: list[bytes]) -> bytes:
    """Render trusted data URLs only; no filesystem/network resource fetching."""
    from weasyprint import HTML, default_url_fetcher

    def local_images_only(url, *args, **kwargs):
        if not url.startswith('data:image/jpeg;base64,'):
            raise ValueError('Only embedded document images are permitted.')
        return default_url_fetcher(url, *args, **kwargs)

    height = '120mm' if category == 'CLIENT_ID' else '265mm'
    rows = ''.join(
        f'<section><img src="data:image/jpeg;base64,{base64.b64encode(data).decode("ascii")}"></section>'
        for data in images
    )
    html = (f'<html><head><style>@page {{size:A4;margin:12mm}}'
            f'body {{margin:0}} section {{height:{height};text-align:center;break-inside:avoid}}'
            f'img {{max-width:186mm;max-height:{height}}}'
            + ('section+section {break-before:page}' if category == 'LAF' else '')
            + '</style></head><body>' + rows + '</body></html>')
    return HTML(string=html, url_fetcher=local_images_only).write_pdf()


def prepare_visit_documents(categorized_files: dict[str, list]) -> dict[str, list]:
    """Convert four named captures to two complete PDFs before any Drive write."""
    from pypdf import PdfReader, PdfWriter

    prepared = {key: list(value or []) for key, value in categorized_files.items()}
    for category, slots in DOCUMENT_SLOTS.items():
        selected = [prepared.pop(slot.upper(), []) for slot in slots]
        if not any(selected):
            continue
        for slot, files in zip(slots, selected):
            if len(files) != 1:
                raise VisitDocumentError(f'Add exactly one photo for {SLOT_LABELS[slot]}.', slot)
        if prepared.get(category):
            raise VisitDocumentError('Choose either captured pages or a completed document, not both.', slots[0])
        images = [validated_image(files[0], field=slot) for slot, files in zip(slots, selected)]
        if images[0] == images[1]:
            raise VisitDocumentError('Both captures are the same photo. Capture the other side or page.', slots[1])
        try:
            pdf = render_document(category, images)
            reader = PdfReader(io.BytesIO(pdf))
            expected_pages = 1 if category == 'CLIENT_ID' else 2
            if len(reader.pages) != expected_pages:
                raise ValueError('Unexpected generated page count')
            # Strip variable producer metadata and bind the exact ordered images.
            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
            digest = hashlib.sha256(b''.join(images)).hexdigest()
            writer.add_metadata({'/Title': 'Client ID' if category == 'CLIENT_ID' else 'LAF',
                                 '/CaptureDigest': digest})
            output = io.BytesIO()
            writer.write(output)
            result = output.getvalue()
        except Exception:
            logger.exception('JBL Visit document collation failed category=%s', category)
            raise VisitDocumentError('The document could not be prepared. Your photos are still selected; retry.', slots[0]) from None
        if len(result) > max(1, settings.MEDIA_MAX_FILE_SIZE_MB) * 1024 * 1024:
            raise VisitDocumentError('The combined document is too large. Choose smaller clear photos.', slots[0])
        prepared[category] = [SimpleUploadedFile(
            'client-id.pdf' if category == 'CLIENT_ID' else 'laf.pdf', result,
            content_type='application/pdf',
        )]
    return {key: value for key, value in prepared.items() if value}
