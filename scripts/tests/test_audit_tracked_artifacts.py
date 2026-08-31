import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from scripts import audit_tracked_artifacts
from scripts.audit_tracked_artifacts import (
    CLASSIFICATION_PATH_PREFIXES,
    controlled_artifact,
    load_allowlist,
    secret_categories,
)


class TrackedArtifactAuditTests(TestCase):
    def test_controlled_artifact_extensions_are_case_insensitive(self):
        self.assertTrue(controlled_artifact("exports/customer-data.XLSX"))
        self.assertTrue(controlled_artifact("screenshots/review.JpG"))
        self.assertTrue(controlled_artifact("~$working-copy.xlsx"))
        self.assertFalse(controlled_artifact("core/services/parser.py"))

    def test_secret_scanner_returns_categories_without_secret_values(self):
        content = b'prefix -----BEGIN ' + b'PRIVATE KEY----- suffix'
        self.assertEqual(secret_categories(content), ["private_key"])

    def test_service_account_structure_is_detected(self):
        content = b'{"type": "service_' + b'account", "private_' + b'key": "redacted"}'
        self.assertIn("google_service_account", secret_categories(content))

    def test_placeholders_do_not_trigger_high_confidence_patterns(self):
        content = b'TELEGRAM_BOT_TOKEN=your-token API_KEY=example'
        self.assertEqual(secret_categories(content), [])

    def test_sanitized_fixture_classification_has_one_bounded_directory(self):
        self.assertEqual(
            CLASSIFICATION_PATH_PREFIXES["sanitized_test_fixture"],
            "core/test_fixtures/sanitized/",
        )

    def test_allowlist_rejects_fixture_classification_outside_fixture_directory(self):
        payload = {
            "version": 1,
            "artifacts": {
                "exports/customer-data.csv": {
                    "sha256": "0" * 64,
                    "classification": "sanitized_test_fixture",
                    "purpose": "invalid path test",
                }
            },
        }
        with TemporaryDirectory() as directory:
            path = Path(directory) / "allowlist.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with patch.object(audit_tracked_artifacts, "ALLOWLIST_PATH", path):
                with self.assertRaisesRegex(ValueError, "outside core/test_fixtures/sanitized"):
                    load_allowlist()
