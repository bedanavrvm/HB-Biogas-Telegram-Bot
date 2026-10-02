"""Local disposable parser process. Input/output never leaves this machine."""
import json
import os
import sys


def main():
    # Linux production workers enforce address-space and CPU ceilings as well
    # as the parent's cross-platform wall-clock timeout. Windows relies on the
    # parent's kill-on-timeout and render allocation preflight.
    if os.name == 'posix':
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    if sys.argv[1:] == ['preview']:
        from core.services.secure_media_preview import _pdf_preview_html, PDF_PREVIEW_MAX_SOURCE_BYTES
        options = json.loads(sys.stdin.buffer.readline(8192))
        content = sys.stdin.buffer.read(PDF_PREVIEW_MAX_SOURCE_BYTES + 1)
        sys.stdout.buffer.write(_pdf_preview_html(content, **options))
        return
    # A child imports Django only after setup, never inherits live DB connections.
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from core.services.invoice_parser import _parse_invoice_pdf_bytes
    content = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
    if len(content) > 8 * 1024 * 1024:
        raise ValueError('Invoice file exceeds the parser byte budget.')
    invoices, pages = _parse_invoice_pdf_bytes(content)
    sys.stdout.write(json.dumps({'invoices': invoices, 'pages': pages}, default=str))


if __name__ == '__main__':
    main()
