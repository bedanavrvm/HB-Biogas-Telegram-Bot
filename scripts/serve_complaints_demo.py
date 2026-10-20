"""Loopback-only Complaints review with an isolated, synthetic SQLite fixture.

No Django initialization, environment configuration, accounts or external I/O.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import sqlite3
import sys
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.serve_ads_browser_preview import importmap_hashes, load_build  # noqa: E402
from scripts.complaints_demo_sandbox import DemoFailure, Sandbox, seed  # noqa: E402

DEMO_DIRECTORY = ROOT / 'test-results/complaints-local-demo'
PREFIX = '/demo-api/complaints/v1/'
SUMMARY_FIELDS = ('key', 'reference', 'customer_name', 'branch', 'category', 'status', 'reported_at')


def fixture():
    return seed()


def fixture_rows():
    return [('synthetic-complaints-v2', json.dumps(fixture(), sort_keys=True, separators=(',', ':')))]


def _no_links(path):
    if any(part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()) for part in (path, *path.parents)):
        raise ValueError('Demo paths must not use filesystem links.')


def read_fixture(database):
    _no_links(database)
    with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as connection:
        if connection.execute('PRAGMA user_version').fetchone()[0] != 2:
            raise ValueError('Unrecognized demo fixture store.')
        tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if tables != [('demo_fixture_v2',)]:
            raise ValueError('Unexpected demo fixture schema.')
        rows = connection.execute('SELECT record_key, payload FROM demo_fixture_v2 ORDER BY record_key').fetchall()
    if rows != fixture_rows():
        raise ValueError('Demo fixture differs from its synthetic source.')
    return json.loads(rows[0][1])


def prepare_fixture(directory=DEMO_DIRECTORY):
    directory = Path(directory).absolute()
    _no_links(directory)
    directory.mkdir(parents=True, exist_ok=True)
    database = directory / 'fixture-v2.sqlite3'
    _no_links(database)
    if not database.exists():
        # Exclusive creation avoids replacing any existing/unrecognized store.
        with database.open('xb'):
            pass
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute('CREATE TABLE demo_fixture_v2 (record_key TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            connection.executemany('INSERT INTO demo_fixture_v2 VALUES (?, ?)', fixture_rows())
            connection.execute('PRAGMA user_version=2')
    read_fixture(database)
    return database


def demo_build(development=False):
    directory = ROOT / 'browser' / ('dist-complaints-demo-development' if development else 'dist-complaints-demo')
    manifest = json.loads((directory / 'build-manifest.json').read_bytes())
    if manifest.get('localComplaintsDemo') is not True or manifest.get('closedAuthentication') is not False or manifest.get('closedComplaints') is not False:
        raise ValueError('Expected the separate synthetic Complaints demo.')
    if not manifest.get('sources'):
        raise ValueError('Demo sources must be bound to this build.')
    for row in manifest['sources']:
        source = ROOT / row['path']
        if not row['path'].startswith('browser/src/') or '..' in Path(row['path']).parts:
            raise ValueError('Unexpected demo source path.')
        if hashlib.sha256(source.read_bytes().replace(b'\r\n', b'\n')).hexdigest() != row['sha256']:
            raise ValueError('Rebuild the demo after changing its source.')
    if any(Path(name).name in {'staff-access.tsx', 'auth-transport.ts', 'auth-index.tsx'} for name in manifest.get('modules', [])):
        raise ValueError('Company authentication must not be bundled into the demo.')
    return load_build(directory, entry='complaints-demo.html')


def demo_read(database, path, query):
    try:
        return 200, Sandbox(read_fixture(database)).read('officer', path.removeprefix(PREFIX), parse_qs(query, keep_blank_values=True, max_num_fields=3))
    except DemoFailure as error:
        return error.status, {'error': error.message}
    except ValueError:
        return 400, {'error': 'invalid_request'}


class ComplaintsDemoHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Never retain paths, queries, headers or supplied bodies.

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, private')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        hashes = ' '.join(self.server.script_hashes)
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self' " + hashes + "; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src blob:; font-src 'none'; form-action 'none'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'")
        super().end_headers()

    def _respond(self, status, raw=b'', content_type='application/json; charset=utf-8', *, head=False):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        if status == 405:
            self.send_header('Allow', 'GET, HEAD')
        self.end_headers()
        if not head:
            self.wfile.write(raw)

    def _read(self, *, head=False):
        hosts = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        if self.headers.get('Host', '') not in hosts or self.headers.get('Sec-Fetch-Site', '') == 'cross-site' or (self.headers.get('Origin') and self.headers['Origin'] not in {'http://' + host for host in hosts}):
            return self._respond(403, head=head)
        if any(name in self.headers for name in ('Authorization', 'X-Telegram-Init-Data', 'X-Session-Token')):
            return self._respond(403, head=head)
        if len(self.path) > 2048:
            return self._respond(414, head=head)
        target = urlsplit(self.path)
        if target.netloc or target.scheme:
            return self._respond(404, head=head)
        if target.path.startswith(PREFIX):
            try:
                read_fixture(self.server.demo_database)
                persona = self.headers.get('X-Demo-Role', 'officer')
                route = target.path.removeprefix(PREFIX)
                evidence = re.fullmatch(r'evidence/([a-f0-9-]{36})/', route)
                if evidence and not target.query:
                    raw, mime = self.server.sandbox.attachment(persona, evidence[1])
                    self.send_response(200)
                    self.send_header('Content-Type', mime)
                    self.send_header('Content-Length', str(len(raw)))
                    self.send_header('Content-Disposition', 'attachment')
                    self.end_headers()
                    if not head:
                        self.wfile.write(raw)
                    return
                payload = self.server.sandbox.read(persona, route, parse_qs(target.query, keep_blank_values=True, max_num_fields=3))
                status = 200
            except DemoFailure as error:
                status, payload = error.status, {'error': error.message, 'fields': error.fields}
            except (ValueError, sqlite3.Error, OSError):
                status, payload = 503, {'error': 'Demo data is unavailable. Restart the local server.'}
            return self._respond(status, json.dumps(payload).encode(), head=head)
        asset = self.server.preview_assets.get(target.path) if not target.query else None
        if asset is None:
            return self._respond(404, head=head)
        return self._respond(200, asset[0], asset[1], head=head)

    def do_GET(self):
        self._read()

    def do_HEAD(self):
        self._read(head=True)

    def _reject_write(self):
        self.close_connection = True
        self._respond(405)

    def do_POST(self):
        expected = {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}
        if ('http://' + self.headers.get('Host', '')) not in expected or self.headers.get('Origin') not in expected or self.headers.get('X-Demo-Request') != '1' or any(name in self.headers for name in ('Authorization', 'X-Telegram-Init-Data', 'X-Session-Token')):
            self.close_connection = True
            return self._respond(403)
        if not self.path.startswith(PREFIX) or '?' in self.path or self.headers.get_content_type() != 'application/json':
            self.close_connection = True
            return self._respond(404)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 42 * 1024 * 1024 or self.headers.get('Transfer-Encoding'):
                self.close_connection = True
                return self._respond(413)
            read_fixture(self.server.demo_database)
            payload = json.loads(self.rfile.read(length))
            result = self.server.sandbox.mutate(self.headers.get('X-Demo-Role', ''), self.path.removeprefix(PREFIX), payload)
            return self._respond(200, json.dumps(result).encode())
        except DemoFailure as error:
            return self._respond(error.status, json.dumps({'error': error.message, 'fields': error.fields}).encode())
        except (ValueError, UnicodeError):
            return self._respond(400, b'{"error":"Review the submitted demo action."}')
        except (sqlite3.Error, OSError):
            return self._respond(503, b'{"error":"Demo data is unavailable."}')

    do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _reject_write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--development', action='store_true')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Choose a local port from 1024 to 65535.')
    try:
        assets = demo_build(args.development)
        database = prepare_fixture()
    except (OSError, ValueError, KeyError, sqlite3.Error) as error:
        raise SystemExit('Demo startup refused. Verify the dedicated build and synthetic fixture store.') from error
    with ThreadingHTTPServer(('127.0.0.1', args.port), ComplaintsDemoHandler) as server:
        server.preview_assets, server.demo_database = assets, database
        server.sandbox = Sandbox(read_fixture(database))
        server.script_hashes = importmap_hashes(assets)
        print(f'Local synthetic Complaints demo: http://127.0.0.1:{server.server_port}/ (Ctrl+C to stop)', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
