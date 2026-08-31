"""Fail when tracked files contain unreviewed artifacts or likely secrets.

The scanner deliberately reports only a path and finding category. It never
prints matching bytes, because a CI log must not become a second disclosure.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = ROOT / "scripts" / "tracked_artifact_allowlist.json"

CONTROLLED_ARTIFACT_SUFFIXES = {
    ".7z", ".bmp", ".csv", ".der", ".docx", ".gif", ".jpeg", ".jpg",
    ".key", ".p12", ".pdf", ".pem", ".pfx", ".png", ".rar", ".tif",
    ".tiff", ".tsv", ".webp", ".xls", ".xlsm", ".xlsx", ".zip",
}
OFFICE_LOCK_PREFIX = "~$"
MAX_TEXT_SCAN_BYTES = 5 * 1024 * 1024
CLASSIFICATION_PATH_PREFIXES = {
    "public_brand_asset": "core/static/",
    "sanitized_test_fixture": "core/test_fixtures/sanitized/",
}

# High-confidence credential shapes only. Customer-data controls are enforced
# by rejecting data/media artifacts unless their exact bytes are reviewed.
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    (
        "private_key",
        re.compile(rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    ),
    (
        "telegram_bot_token",
        re.compile(rb"(?<![A-Za-z0-9_])[0-9]{8,12}:[A-Za-z0-9_-]{30,}(?![A-Za-z0-9_-])"),
    ),
    ("aws_access_key", re.compile(rb"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])")),
    ("github_token", re.compile(rb"(?<![A-Za-z0-9_])gh[pousr]_[A-Za-z0-9]{30,}")),
    ("slack_token", re.compile(rb"(?<![A-Za-z0-9])xox[baprs]-[A-Za-z0-9-]{20,}")),
    ("google_api_key", re.compile(rb"(?<![A-Za-z0-9])AIza[A-Za-z0-9_-]{30,}")),
)


def tracked_paths() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return sorted(
        value.decode("utf-8", errors="surrogateescape")
        for value in result.stdout.split(b"\0")
        if value
    )


def load_allowlist() -> dict[str, dict[str, str]]:
    try:
        payload = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("The tracked-artifact allowlist is missing or invalid.") from exc
    if payload.get("version") != 1 or not isinstance(payload.get("artifacts"), dict):
        raise ValueError("The tracked-artifact allowlist must use version 1 and an artifacts object.")
    entries: dict[str, dict[str, str]] = {}
    for raw_path, metadata in payload["artifacts"].items():
        path = PurePosixPath(str(raw_path))
        if path.is_absolute() or ".." in path.parts or str(path) != str(raw_path):
            raise ValueError("Allowlisted artifact paths must be normalized repository-relative paths.")
        if not isinstance(metadata, dict):
            raise ValueError(f"Allowlist metadata is invalid for {path}.")
        digest = str(metadata.get("sha256") or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"Allowlist SHA-256 is invalid for {path}.")
        if not str(metadata.get("classification") or "").strip():
            raise ValueError(f"Allowlist classification is missing for {path}.")
        classification = str(metadata["classification"]).strip()
        expected_prefix = CLASSIFICATION_PATH_PREFIXES.get(classification)
        if expected_prefix is None:
            raise ValueError(f"Allowlist classification is not recognized for {path}.")
        if not str(path).startswith(expected_prefix):
            raise ValueError(
                f"Allowlisted {classification} artifact is outside {expected_prefix}: {path}."
            )
        if not str(metadata.get("purpose") or "").strip():
            raise ValueError(f"Allowlist purpose is missing for {path}.")
        entries[str(path)] = metadata
    return entries


def controlled_artifact(path: str) -> bool:
    candidate = PurePosixPath(path)
    return (
        candidate.name.startswith(OFFICE_LOCK_PREFIX)
        or candidate.suffix.casefold() in CONTROLLED_ARTIFACT_SUFFIXES
    )


def secret_categories(content: bytes) -> list[str]:
    categories = [name for name, pattern in SECRET_PATTERNS if pattern.search(content)]
    compact = re.sub(rb"\s+", b"", content.lower())
    service_account_marker = b'"type":' + b'"service_account"'
    private_key_marker = b'"private_' + b'key"'
    if service_account_marker in compact and private_key_marker in compact:
        categories.append("google_service_account")
    return categories


def scan() -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    try:
        allowlist = load_allowlist()
        paths = tracked_paths()
    except (ValueError, subprocess.CalledProcessError) as exc:
        return [(str(ALLOWLIST_PATH.relative_to(ROOT)), str(exc))]

    tracked = set(paths)
    for path in sorted(set(allowlist) - tracked):
        findings.append((path, "allowlisted artifact is not tracked"))

    for relative_path in paths:
        absolute_path = ROOT / relative_path
        if not absolute_path.is_file():
            continue
        if controlled_artifact(relative_path):
            metadata = allowlist.get(relative_path)
            if metadata is None:
                findings.append((relative_path, "unreviewed controlled artifact"))
            else:
                digest = hashlib.sha256(absolute_path.read_bytes()).hexdigest()
                if digest != str(metadata["sha256"]).lower():
                    findings.append((relative_path, "allowlisted artifact hash mismatch"))

        try:
            if absolute_path.stat().st_size <= MAX_TEXT_SCAN_BYTES:
                content = absolute_path.read_bytes()
                if b"\0" not in content:
                    for category in secret_categories(content):
                        findings.append((relative_path, f"possible {category}"))
        except OSError:
            findings.append((relative_path, "could not read tracked file"))

    return sorted(set(findings))


def main() -> int:
    findings = scan()
    if findings:
        print("Tracked artifact/privacy audit failed. No matching content is printed:")
        for path, category in findings:
            print(f"  {path}: {category}")
        print(
            "Remove sensitive/generated files. Review genuinely public or synthetic "
            "artifacts and pin their SHA-256 in scripts/tracked_artifact_allowlist.json."
        )
        return 1
    reviewed_count = len(load_allowlist())
    print(
        "Tracked artifact/privacy audit passed "
        f"({reviewed_count} reviewed artifact(s); no high-confidence secret patterns)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
