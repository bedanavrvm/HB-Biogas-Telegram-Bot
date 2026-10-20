"""Local fixture review must never expose operational authentication or data."""
from contextlib import closing
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from scripts.serve_complaints_demo import ComplaintsDemoHandler, PREFIX, demo_read, prepare_fixture, read_fixture
from scripts import serve_complaints_demo
from scripts.serve_ads_browser_preview import load_build


class ComplaintsDemoTests(unittest.TestCase):
    def test_only_fresh_separate_demo_builds_are_accepted(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            directory = root / 'browser/dist-complaints-demo'
            directory.mkdir(parents=True)
            source = root / 'browser/src/complaints-demo.html'
            source.parent.mkdir()
            source.write_bytes(b'Synthetic source')
            files = []
            for name, raw in {'complaints-demo.html': b'<title>Synthetic demo</title>', 'demo.js': b'/* fixture */', 'THIRD_PARTY_NOTICES.txt': b'Synthetic notices'}.items():
                (directory / name).write_bytes(raw)
                files.append({'name': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
            manifest = {'schemaVersion': 1, 'demoOnly': True, 'localComplaintsDemo': True,
                        'closedAuthentication': False, 'closedComplaints': False, 'modules': [],
                        'files': files, 'sources': [{'path': 'browser/src/complaints-demo.html', 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}]}
            path = directory / 'build-manifest.json'
            path.write_text(json.dumps(manifest), encoding='utf-8')
            with patch.object(serve_complaints_demo, 'ROOT', root):
                self.assertIn('/', serve_complaints_demo.demo_build())
                with self.assertRaises(ValueError):
                    load_build(directory)
                source.write_bytes(b'Changed source')
                with self.assertRaises(ValueError):
                    serve_complaints_demo.demo_build()
                source.write_bytes(b'Synthetic source')
                manifest['closedAuthentication'] = True
                path.write_text(json.dumps(manifest), encoding='utf-8')
                with self.assertRaises(ValueError):
                    serve_complaints_demo.demo_build()

    def test_fixture_restart_is_idempotent_and_unchanged(self):
        with TemporaryDirectory() as folder:
            database = prepare_fixture(Path(folder))
            before = database.read_bytes()
            self.assertEqual(prepare_fixture(Path(folder)), database)
            self.assertEqual(database.read_bytes(), before)
            data = read_fixture(database)
            self.assertEqual(len(data['cases']), 10)
            self.assertTrue(all(case['customer_name'].startswith('Sample Farmer ') for case in data['cases']))

    def test_unrecognized_database_is_not_replaced(self):
        with TemporaryDirectory() as folder:
            database = Path(folder) / 'fixture-v2.sqlite3'
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute('CREATE TABLE unrelated (value TEXT)')
            before = database.read_bytes()
            with self.assertRaises(ValueError):
                prepare_fixture(Path(folder))
            self.assertEqual(database.read_bytes(), before)

    def test_changed_fixture_is_not_served(self):
        with TemporaryDirectory() as folder:
            database = prepare_fixture(Path(folder))
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute("UPDATE demo_fixture_v2 SET payload='unexpected contents'")
            with self.assertRaises(ValueError):
                read_fixture(database)

    def test_queue_search_status_paging_and_detail(self):
        with TemporaryDirectory() as folder:
            database = prepare_fixture(Path(folder))
            path = PREFIX + 'groups/1/cases/'
            status, data = demo_read(database, path, '')
            self.assertEqual(status, 200)
            self.assertEqual(data['pagination'], {'page': 1, 'pages': 2, 'total': 7, 'page_size': 4})
            self.assertEqual(len(demo_read(database, path, 'page=2')[1]['items']), 3)
            self.assertEqual(demo_read(database, path, 'status=resolved')[1]['pagination']['total'], 2)
            self.assertEqual(demo_read(database, path, 'status=all')[1]['pagination']['total'], 9)
            self.assertEqual(demo_read(database, path, 'q=Lanet')[1]['items'][0]['reference'], 'CMP-3')
            self.assertEqual(demo_read(database, path, 'q=CMP-1')[1]['items'][0]['reference'], 'CMP-1')
            self.assertEqual(demo_read(database, path, 'q=nomatch')[1]['items'], [])
            status, detail = demo_read(database, path + data['items'][0]['key'] + '/', '')
            self.assertEqual(status, 200)
            self.assertIn('history', detail['case'])
            self.assertEqual(detail['case']['customer_phone'], '0700000001')
            self.assertEqual(demo_read(database, PREFIX + 'groups/3/cases/', '')[0], 403)

    def test_invalid_query_and_excessive_paging_are_rejected(self):
        with TemporaryDirectory() as folder:
            database = prepare_fixture(Path(folder))
            for query in ('page=0', 'page=nan', 'page=9999999', 'page=1&page=2', 'status=wrong', 'unknown=1', 'q=' + 'a' * 151, 'q=a&status=all&page=1&extra=2'):
                with self.subTest(query=query):
                    self.assertEqual(demo_read(database, PREFIX + 'groups/1/cases/', query)[0], 400)

    def test_http_boundary_only_exposes_demo_reads_and_verified_assets(self):
        with TemporaryDirectory() as folder:
            database = prepare_fixture(Path(folder))
            with ThreadingHTTPServer(('127.0.0.1', 0), ComplaintsDemoHandler) as server:
                server.demo_database, server.script_hashes = database, []
                server.sandbox = serve_complaints_demo.Sandbox(read_fixture(database))
                server.preview_assets = {'/': (b'Synthetic demo', 'text/html')}
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                def request(path='/', method='GET', headers=None, body=None):
                    connection = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                    connection.request(method, path, body=body, headers=headers or {})
                    response = connection.getresponse()
                    result = response.status, dict(response.getheaders()), response.read()
                    connection.close()
                    return result

                try:
                    for path in ('/', PREFIX + 'groups/', PREFIX + 'groups/1/cases/'):
                        status, headers, raw = request(path)
                        self.assertEqual(status, 200)
                        self.assertTrue(raw)
                        self.assertNotIn('Set-Cookie', headers)
                        self.assertEqual(headers['Cache-Control'], 'no-store, private')
                        self.assertIn("connect-src 'self'", headers['Content-Security-Policy'])
                        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
                    for path in ('/.env', '/fixture-v2.sqlite3', '/build-manifest.json', '/api/staff/auth/v1/session/', '/api/staff/complaints/v1/groups/', '/?proof=invalid'):
                        self.assertEqual(request(path)[0], 404)
                    self.assertEqual(request(method='HEAD')[2], b'')
                    self.assertEqual(request(PREFIX + 'groups/', method='POST')[0], 403)
                    origin = f'http://127.0.0.1:{server.server_port}'
                    headers = {'Origin': origin, 'Content-Type': 'application/json', 'X-Demo-Request': '1', 'X-Demo-Role': 'officer'}
                    context = server.sandbox.context('officer')
                    payload = json.dumps({'epoch': context['epoch'], 'request_key': 'http-demo-reset-1'})
                    self.assertEqual(request(PREFIX + 'reset/', method='POST', headers=headers, body=payload)[0], 200)
                    self.assertEqual(request(PREFIX + 'reset/', method='POST', headers={**headers, 'Origin': 'https://foreign.invalid'}, body=payload)[0], 403)
                    self.assertEqual(request('/api/staff/auth/v1/login/', method='POST', headers=headers, body=payload)[0], 404)
                    for method in ('PUT', 'PATCH', 'DELETE', 'OPTIONS'):
                        self.assertEqual(request(PREFIX + 'groups/', method=method)[0], 405)
                    for headers in ({'Host': 'foreign.invalid'}, {'Origin': 'https://foreign.invalid'}, {'Sec-Fetch-Site': 'cross-site'}, {'Authorization': 'invalid'}, {'X-Telegram-Init-Data': 'invalid'}, {'X-Session-Token': 'invalid'}):
                        self.assertEqual(request(headers=headers)[0], 403)
                    # An existing cookie conveys no authority and is never used.
                    self.assertEqual(request(PREFIX + 'groups/', headers={'Cookie': 'sessionid=synthetic'})[0], 200)
                    with closing(sqlite3.connect(database)) as connection, connection:
                        connection.execute("UPDATE demo_fixture_v2 SET payload='unexpected contents'")
                    status, _, raw = request(PREFIX + 'groups/')
                    self.assertEqual(status, 503)
                    self.assertNotIn(b'unexpected contents', raw)
                finally:
                    server.shutdown()
                    thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
