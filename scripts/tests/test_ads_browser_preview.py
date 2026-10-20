"""The built ADS demo exposes hashed static assets, never the workspace or APIs."""
import hashlib
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest

from scripts.serve_ads_browser_preview import ADSPreviewHandler, importmap_hashes, load_build


class ADSBrowserPreviewTests(unittest.TestCase):
    def test_review_entry_is_subject_to_the_same_inline_script_boundary(self):
        routes = {'/index.html': (b'<!doctype html>', 'text/html'),
                  '/review.html': (b'<script>alert(1)</script>', 'text/html')}
        with self.assertRaises(ValueError):
            importmap_hashes(routes)

    def test_importmaps_are_hashed_and_cannot_load_foreign_modules_or_inline_code(self):
        body = b'{"imports":{"theme":"/theme.js"}}'
        routes = {'/index.html': (b'<script type=importmap>' + body + b'</script>', 'text/html'),
                  '/theme.js': (b'/* synthetic */', 'text/javascript')}
        self.assertEqual(len(importmap_hashes(routes)), 1)
        for html in (b'<script>alert(1)</script>',
                     b'<script type=importmap>{"imports":{"theme":"https://foreign.invalid/theme.js"}}</script>',
                     b'<script src=/theme.js>alert(1)</script>'):
            with self.subTest(html=html), self.assertRaises(ValueError):
                importmap_hashes({**routes, '/index.html': (html, 'text/html')})

    def fixture(self, directory):
        files = []
        for name, raw in {'index.html': b'<!doctype html><title>Synthetic fixture</title>',
                          'app.abc.js': b'/* synthetic fixture */',
                          'THIRD_PARTY_NOTICES.txt': b'Synthetic notice fixture'}.items():
            (directory / name).write_bytes(raw)
            files.append({'name': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
        manifest = {'schemaVersion': 1, 'demoOnly': True, 'files': files}
        (directory / 'build-manifest.json').write_text(json.dumps(manifest))
        return manifest

    def test_changed_output_is_rejected_before_serving(self):
        with TemporaryDirectory() as location:
            directory = Path(location)
            self.fixture(directory)
            (directory / 'app.abc.js').write_bytes(b'changed fixture')
            with self.assertRaises(ValueError):
                load_build(directory)

    def test_paths_maps_and_duplicates_in_manifest_are_rejected(self):
        for name in ('../outside.js', 'folder/app.js', '/app.js', 'app.js.map', 'build-manifest.json', 'font.woff2'):
            with self.subTest(name=name), TemporaryDirectory() as location:
                directory = Path(location)
                manifest = self.fixture(directory)
                manifest['files'][0]['name'] = name
                (directory / 'build-manifest.json').write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):
                    load_build(directory)
        with TemporaryDirectory() as location:
            directory = Path(location)
            manifest = self.fixture(directory)
            manifest['files'].append(manifest['files'][0])
            (directory / 'build-manifest.json').write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                load_build(directory)

    def test_missing_notice_or_nondemo_build_is_rejected(self):
        for change in ('notices', 'demo'):
            with self.subTest(change=change), TemporaryDirectory() as location:
                directory = Path(location)
                manifest = self.fixture(directory)
                if change == 'demo':
                    manifest['demoOnly'] = False
                else:
                    manifest['files'] = [r for r in manifest['files'] if r['name'] != 'THIRD_PARTY_NOTICES.txt']
                (directory / 'build-manifest.json').write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):
                    load_build(directory)

    def test_only_manifest_assets_are_readable_without_cookie_or_write_surface(self):
        with TemporaryDirectory() as location:
            directory = Path(location)
            self.fixture(directory)
            with ThreadingHTTPServer(('127.0.0.1', 0), ADSPreviewHandler) as server:
                server.preview_assets = load_build(directory)
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                def request(path='/', method='GET', headers=None):
                    connection = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                    connection.request(method, path, headers=headers or {})
                    response = connection.getresponse()
                    result = response.status, dict(response.getheaders()), response.read()
                    connection.close()
                    return result
                try:
                    for path in ('/', '/app.abc.js', '/THIRD_PARTY_NOTICES.txt'):
                        status, headers, raw = request(path)
                        self.assertEqual(status, 200)
                        self.assertTrue(raw)
                        self.assertNotIn('Set-Cookie', headers)
                        self.assertEqual(headers['Cache-Control'], 'no-store')
                        self.assertIn("connect-src 'none'", headers['Content-Security-Policy'])
                        self.assertIn("script-src 'self'", headers['Content-Security-Policy'])
                        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
                    for path in ('/package.json', '/build-manifest.json', '/node_modules/react/index.js',
                                 '/.env', '/v1/auth/login/', '/app.abc.js?proof=synthetic'):
                        self.assertEqual(request(path)[0], 404)
                    self.assertEqual(request(headers={'Host': 'foreign.invalid'})[0], 403)
                    self.assertEqual(request(method='POST')[0], 405)
                    self.assertEqual(request(method='HEAD')[2], b'')
                finally:
                    server.shutdown()
                    worker.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
