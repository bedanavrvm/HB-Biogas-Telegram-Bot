"""Serve the hashed React/ADS demo build on loopback without Django or APIs."""
from __future__ import annotations

import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re


BUILD_ROOT = Path(__file__).resolve().parents[1] / 'browser/dist'
TYPES = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.txt': 'text/plain'}


def importmap_hashes(routes):
    hashes = []
    for route, (html, _) in routes.items():
        if not route.endswith('.html'):
            continue
        for match in re.finditer(rb'<script\b([^>]*)>(.*?)</script>', html, re.I | re.S):
            attributes, body = match.groups()
            if re.search(rb'\bsrc\s*=', attributes):
                if body.strip():
                    raise ValueError('External scripts may not contain inline code.')
                continue
            if not body.strip():
                continue
            if not re.search(rb'\btype\s*=\s*(?:"importmap"|\'importmap\'|importmap)(?:\s|$)', attributes, re.I):
                raise ValueError('Only a hashed static import map may be inline.')
            data = json.loads(body)
            if set(data) != {'imports'} or not isinstance(data['imports'], dict):
                raise ValueError('Unexpected import map structure.')
            for value in data['imports'].values():
                if not isinstance(value, str) or value not in routes:
                    raise ValueError('Import maps may resolve only to reviewed local assets.')
            hashes.append("'sha256-" + base64.b64encode(hashlib.sha256(body).digest()).decode('ascii') + "'")
    return sorted(set(hashes))


def load_build(directory=BUILD_ROOT):
    directory = directory.resolve()
    manifest = json.loads((directory / 'build-manifest.json').read_bytes())
    if manifest.get('schemaVersion') != 1 or manifest.get('demoOnly') is not True:
        raise ValueError('Expected the reviewed demo build manifest.')
    routes = {}
    for entry in manifest['files']:
        name = entry['name']
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*\.(?:html|js|css|txt)', name):
            raise ValueError('Unexpected preview asset path.')
        source = directory / name
        if source.is_symlink() or source.resolve().parent != directory:
            raise ValueError('Preview assets must stay inside the build directory.')
        raw = source.read_bytes()
        if len(raw) != entry['bytes'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise ValueError('Preview asset differs from its build manifest; rebuild first.')
        if '/' + name in routes:
            raise ValueError('Duplicate preview asset.')
        routes['/' + name] = raw, TYPES[source.suffix] + '; charset=utf-8'
    if '/index.html' not in routes or '/THIRD_PARTY_NOTICES.txt' not in routes:
        raise ValueError('The preview needs an entry page and readable third-party notices.')
    routes['/'] = routes['/index.html']
    importmap_hashes(routes)
    return routes


class ADSPreviewHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Never retain supplied paths, query strings, headers or bodies.

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        # ADS theme styles are inserted at runtime. Inline styles are allowed
        # only in this data-free local demo; a production nonce policy is separate.
        script_hashes = ' '.join(getattr(self.server, 'script_hashes', []))
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self' " + script_hashes + "; "
                         "style-src 'self' 'unsafe-inline'; connect-src 'none'; img-src 'none'; "
                         "font-src 'none'; form-action 'none'; base-uri 'none'; object-src 'none'; "
                         "frame-ancestors 'none'")
        super().end_headers()

    def _read(self, head=False):
        allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        if self.headers.get('Host', '') not in allowed:
            self.send_error(403)
            return
        asset = self.server.preview_assets.get(self.path)
        if asset is None:
            self.send_error(404)
            return
        raw, content_type = asset
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        if not head:
            self.wfile.write(raw)

    def do_GET(self):
        self._read()

    def do_HEAD(self):
        self._read(head=True)

    def do_POST(self):
        self.close_connection = True
        self.send_response(405)
        self.send_header('Allow', 'GET, HEAD')
        self.send_header('Content-Length', '0')
        self.end_headers()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--development', action='store_true', help='Serve the separately built StrictMode development demo.')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Choose a local port from 1024 to 65535.')
    try:
        assets = load_build(BUILD_ROOT.parent / 'dist-development' if args.development else BUILD_ROOT)
    except (OSError, ValueError, KeyError) as exc:
        raise SystemExit('Build the React/ADS workspace before starting the preview.') from exc
    with ThreadingHTTPServer(('127.0.0.1', args.port), ADSPreviewHandler) as server:
        server.preview_assets = assets
        server.script_hashes = importmap_hashes(assets)
        print(f'React + Atlassian demo: http://127.0.0.1:{server.server_port}/ (Ctrl+C to stop)', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
