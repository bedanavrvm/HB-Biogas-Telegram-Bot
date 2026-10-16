"""Portable source identity; only equivalent CRLF/LF text endings are ignored."""
import hashlib


TEXT_SUFFIXES = frozenset({'.py', '.html', '.js', '.css', '.json', '.svg', '.txt'})


def source_digest(path):
    content = path.read_bytes()
    if path.suffix in TEXT_SUFFIXES:
        content = content.replace(b'\r\n', b'\n')
    return hashlib.sha256(content).hexdigest()
