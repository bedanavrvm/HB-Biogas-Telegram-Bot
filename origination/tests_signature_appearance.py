from io import BytesIO
from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import subprocess

from django.test import SimpleTestCase
from PIL import Image
from pypdf import PdfReader

from origination.services.signature_appearance import FONTS, preview_capture, freeze_capture
from origination.services.origination_signing import _slot_overlay
from origination.services.loan_origination import OriginationError


class SignatureAppearanceTests(SimpleTestCase):
    def test_manifest_is_not_excluded_from_deployments(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(['git', 'check-ignore', '--no-index', '-q',
            'origination/assets/signature_fonts/manifest.json'], cwd=root, capture_output=True)
        self.assertEqual(result.returncode, 1, 'The signature manifest must ship with the fonts.')

    def test_missing_or_invalid_bundle_has_a_clear_error(self):
        from origination.services import signature_appearance as appearance
        with TemporaryDirectory() as directory, patch.object(appearance, 'ASSETS', Path(directory)):
            appearance._font_bytes.cache_clear()
            with self.assertRaisesRegex(appearance.SignatureAssetsUnavailable, 'Signature styles are unavailable'):
                appearance.preview_capture('Synthetic Signer')
        appearance._font_bytes.cache_clear()

    def test_each_font_renders_full_long_names_without_clipping(self):
        for font in FONTS:
            for name in ["Wanjiku Mwangi-Kamau", "Njeri O'Kamau", 'W M K N', 'Wanjiku ' * 14]:
                preview = preview_capture(name, font)
                capture = freeze_capture({
                    'name': name, 'font': font, 'appearance_version': 2,
                    'preview_sha256': preview['sha256'],
                })
                import base64
                png = base64.b64decode(capture['image_png'])
                image = Image.open(BytesIO(png))
                self.assertEqual(image.size, (750, 209))
                bounds = image.getbbox()
                self.assertGreater(bounds[0], 0)
                self.assertLess(bounds[2], image.width)
                self.assertEqual(capture['name'], ' '.join(name.split()))
                action = SimpleNamespace(action_type='signature', stamp_asset_id=None,
                                         metadata={'signature_capture': capture})
                page = PdfReader(BytesIO(_slot_overlay(600, 800, [({
                    'allowed_area': {'x': 40, 'y': 60, 'width': 180, 'height': 50},
                }, action)], test_mode=False))).pages[0]
                self.assertEqual(len(page.images), 1)
                self.assertEqual(page.images[0].image.convert('RGBA').tobytes(), image.tobytes())

    def test_historical_typed_capture_retains_text_renderer(self):
        action = SimpleNamespace(action_type='signature',stamp_asset_id=None,
                                 metadata={'signature_capture':{'method':'typed','name':'Legacy Synthetic'}})
        page = PdfReader(BytesIO(_slot_overlay(600,800,[({'allowed_area':{
            'x':40,'y':60,'width':180,'height':50}},action)],test_mode=False))).pages[0]
        self.assertEqual(len(page.images),0)
        self.assertIn('Legacy Synthetic',page.extract_text())

    def test_changed_preview_is_rejected(self):
        with self.assertRaises(OriginationError):
            freeze_capture({'name': 'Synthetic Signer', 'font': 'caveat',
                            'appearance_version': 2, 'preview_sha256': 'wrong'})

    def test_untrusted_font_and_control_characters_rejected(self):
        for name, font in [('Synthetic', '../font'), ('Name\x00', 'caveat')]:
            with self.assertRaises(OriginationError):
                preview_capture(name, font)
