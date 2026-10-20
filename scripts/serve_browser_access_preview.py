"""Serve only the synthetic access wireframe on IPv4 loopback; no Django or I/O APIs."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / 'codebase-analysis-docs/assets/browser-access-preview'
FILES = {'/': ('index.html', 'text/html; charset=utf-8'),
         '/index.html': ('index.html', 'text/html; charset=utf-8'),
         '/preview.css': ('preview.css', 'text/css; charset=utf-8'),
         '/preview.js': ('preview.js', 'text/javascript; charset=utf-8')}


class PreviewHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Do not print paths, query strings, headers or supplied bodies.
        pass

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; "
                         "connect-src 'none'; img-src 'none'; font-src 'none'; form-action 'none'; "
                         "base-uri 'none'; object-src 'none'; frame-ancestors 'none'")
        super().end_headers()

    def _read(self, head=False):
        allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        if self.headers.get('Host', '') not in allowed:
            self.send_error(403)
            return
        entry = FILES.get(self.path)
        if entry is None:
            self.send_error(404)
            return
        raw = (SOURCE / entry[0]).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', entry[1])
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
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Choose a local port from 1024 to 65535.')
    with ThreadingHTTPServer(('127.0.0.1', args.port), PreviewHandler) as server:
        print(f'Synthetic access preview: http://127.0.0.1:{server.server_port}/ (Ctrl+C to stop)', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
