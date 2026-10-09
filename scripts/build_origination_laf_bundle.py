"""Build private blank PDF assets, stripping author/XMP metadata.

Read-only unless --apply. Source bytes must match the reviewed seed registry.
Only the fixed origination/assets/lafs directory is ever written. No customer
PDFs, arbitrary inputs, external upload or publication are supported.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from pypdf import PdfReader, PdfWriter
from origination.services.origination_main_laf_seeds import DEFINITIONS as MAIN, source_path
from origination.services.origination_support_laf_seeds import DEFINITIONS as SUPPORT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    options = parser.parse_args()
    target = ROOT / 'origination' / 'assets' / 'lafs'
    if options.apply:
        target.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for definition in (*[d for d in MAIN if d.key != 'water_tank'], *SUPPORT):
        source = source_path(definition, ROOT / 'LAFS')
        data = source.read_bytes()
        reader = PdfReader(source)
        assert hashlib.sha256(data).hexdigest() == definition.sha256
        assert len(data) == definition.byte_size and len(reader.pages) == definition.page_count
        assert not any(field.get('/V') for field in (reader.get_fields() or {}).values()), 'Filled PDF is not a blank asset.'
        writer = PdfWriter(clone_from=reader)
        if writer._info is not None:
            writer._info.get_object().clear()
        writer._root_object.pop('/Metadata', None)
        # Cloning retains orphan XMP objects even after the root reference is
        # removed. Strip every metadata stream, including page-level metadata,
        # without changing content streams, resources, or printed form fields.
        for obj in writer._objects:
            if isinstance(obj, dict):
                obj.pop('/Metadata', None)
                if obj.get('/Type') == '/Metadata' and hasattr(obj, 'set_data'):
                    obj.set_data(b'')
        import io
        output = io.BytesIO()
        writer.write(output)
        clean = output.getvalue()
        sanitized = PdfReader(io.BytesIO(clean))
        assert not sanitized.metadata
        assert b'<dc:creator' not in clean and b'<pdf:Author' not in clean
        assert len(sanitized.pages) == len(reader.pages)
        assert all(a.get_contents().get_data() == b.get_contents().get_data()
                   for a, b in zip(reader.pages, sanitized.pages)), 'Form pages changed.'
        if options.apply:
            (target / definition.filename).write_bytes(clean)
        manifest[definition.key] = {'filename': definition.filename, 'source_sha256': definition.sha256,
                                    'sha256': hashlib.sha256(clean).hexdigest(), 'byte_size': len(clean),
                                    'page_count': definition.page_count}
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
