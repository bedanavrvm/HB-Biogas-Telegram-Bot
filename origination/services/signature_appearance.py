"""Bounded, deterministic typed marks; no browser fonts or external rendering."""
import base64
import hashlib
import json
import unicodedata
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTS = {
    'caveat': 'Caveat', 'dancing_script': 'Dancing Script',
    'yellowtail': 'Yellowtail', 'nothing_you_could_do': 'Nothing You Could Do',
}
ASSETS = Path(__file__).resolve().parents[1] / 'assets' / 'signature_fonts'
RENDERER_VERSION = 'typed-mark-2'


def _error(message):
    from origination.services.loan_origination import OriginationError
    return OriginationError(message)


@lru_cache(maxsize=4)
def _font_bytes(font: str) -> bytes:
    if font not in FONTS:
        raise _error('Choose one of the signature styles.')
    manifest = json.loads((ASSETS / 'manifest.json').read_text(encoding='utf-8'))
    content = (ASSETS / f'{font}.ttf').read_bytes()
    if hashlib.sha256(content).hexdigest() != manifest['fonts'][font]['sha256']:
        raise _error('Signature styles are unavailable. Please contact IT.')
    return content


def render_mark(name: str, font: str = 'caveat') -> tuple[bytes, dict]:
    if not isinstance(name, str) or any(unicodedata.category(c).startswith('C') for c in name):
        raise _error('Enter your full name without special control characters.')
    name = ' '.join(name.split())
    if not 2 <= len(name) <= 120:
        raise _error('Enter your full name using 2 to 120 characters.')
    content = _font_bytes(font)
    image = Image.new('RGBA', (750, 209), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    size = 133  # 32pt at 300dpi; retain every letter even for long names.
    while True:
        face = ImageFont.truetype(BytesIO(content), size=size)
        if hasattr(face, 'get_variation_axes'):
            try:
                face.set_variation_by_axes([400])
            except OSError:
                pass  # Static regular fonts have no variation axis.
        box = draw.textbbox((0, 0), name, font=face, stroke_width=1)
        width, height = box[2] - box[0], box[3] - box[1]
        if width <= 718 and height <= 185:
            break
        size -= 1
        if size < 4:
            raise _error('This name cannot fit. Please use the drawn signature option.')
    draw.text(((750 - width) / 2 - box[0], (209 - height) / 2 - box[1]), name,
              font=face, fill='#1F2A6B', stroke_width=1, stroke_fill='#1F2A6B')
    output = BytesIO()
    image.save(output, format='PNG', dpi=(300, 300), compress_level=9)
    return output.getvalue(), {
        'method': 'typed', 'name': name, 'font': font, 'appearance_version': 2,
        'renderer': RENDERER_VERSION, 'font_sha256': hashlib.sha256(content).hexdigest(),
        'colour': '#1F2A6B', 'frame_pt': [180, 50],
    }


def preview_capture(name: str, font: str = 'caveat') -> dict:
    content, _profile = render_mark(name, font)
    return {'image_url': 'data:image/png;base64,' + base64.b64encode(content).decode('ascii'),
            'sha256': hashlib.sha256(content).hexdigest()}


def freeze_capture(value: dict) -> dict:
    content, profile = render_mark(value.get('name'), value.get('font') or 'caveat')
    digest = hashlib.sha256(content).hexdigest()
    if value.get('preview_sha256') != digest:
        raise _error('Your signature changed. Check the preview before saving again.')
    return {**profile, 'image_png': base64.b64encode(content).decode('ascii'), 'image_sha256': digest}
