"""Reviewed request/parser budgets; independent of invoice identity rules."""

MAX_DELIVERY_FILES = 20
MAX_DELIVERY_BYTES = 32 * 1024 * 1024
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_PDF_PAGES = 200
MAX_PARSE_SECONDS = 20


def validate_invoice_delivery(files):
    if len(files) > MAX_DELIVERY_FILES:
        raise ValueError(f'Upload at most {MAX_DELIVERY_FILES} invoice PDFs at a time. Split this delivery into smaller uploads.')
    if sum(int(getattr(file, 'size', 0) or 0) for file in files) > MAX_DELIVERY_BYTES:
        raise ValueError('This invoice delivery exceeds 32 MB. Split it into smaller uploads.')
