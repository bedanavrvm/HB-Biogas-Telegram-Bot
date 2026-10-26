"""The synthetic preview must expose only its three assets and no write surface."""
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import threading
import unittest

from scripts.serve_browser_access_preview import FILES, PreviewHandler


class BrowserAccessPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), PreviewHandler)
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join(timeout=5)

    def request(self, path='/', method='GET', headers=None, body=None):
        connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_only_fixed_preview_assets_are_served(self):
        for path in FILES:
            with self.subTest(path=path):
                status, headers, raw = self.request(path)
                self.assertEqual(status, 200)
                self.assertEqual(int(headers['Content-Length']), len(raw))
                self.assertNotIn('Set-Cookie', headers)

    def test_repository_paths_encoded_traversal_queries_and_api_are_unavailable(self):
        for path in ('/AGENTS.md', '/.env', '/../.env', '/%2e%2e/.env',
                     '/preview.js?proof=synthetic', '/api/', '/v1/auth/login/', '/%2findex.html'):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)

    def test_rebinding_and_foreign_hosts_are_rejected(self):
        for host in ('untrusted.invalid', 'untrusted.invalid:8765', '127.0.0.1.evil.invalid',
                     'localhost', 'localhost:1', '127.0.0.1:1'):
            with self.subTest(host=host):
                self.assertEqual(self.request(headers={'Host': host})[0], 403)
        self.assertEqual(self.request(headers={'Host': f'localhost:{self.server.server_port}'})[0], 200)

    def test_post_does_not_consume_or_echo_demo_credentials(self):
        status, headers, raw = self.request('/v1/setup/password/', 'POST', body=b'synthetic-only')
        self.assertEqual(status, 405)
        self.assertEqual(headers['Allow'], 'GET, HEAD')
        self.assertEqual(raw, b'')
        self.assertNotIn('Set-Cookie', headers)

    def test_head_has_headers_without_a_body(self):
        status, headers, raw = self.request(method='HEAD')
        self.assertEqual(status, 200)
        self.assertGreater(int(headers['Content-Length']), 0)
        self.assertEqual(raw, b'')

    def test_csp_blocks_network_forms_remote_assets_and_framing(self):
        for path in ('/', '/missing'):
            with self.subTest(path=path):
                _, headers, _ = self.request(path)
                for directive in ("connect-src 'none'", "form-action 'none'", "img-src 'none'",
                                  "font-src 'none'", "frame-ancestors 'none'"):
                    self.assertIn(directive, headers['Content-Security-Policy'])
                self.assertEqual(headers['Cache-Control'], 'no-store')
                self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
                self.assertNotIn('Access-Control-Allow-Origin', headers)


if __name__ == '__main__':
    unittest.main()
