from pathlib import Path
import importlib.util
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    'check_database_governance', ROOT / 'scripts' / 'check_database_governance.py',
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DatabaseGovernanceTests(unittest.TestCase):
    def test_current_post_adoption_models_are_documented(self):
        self.assertEqual(MODULE.errors(), [])

    def test_rules_require_complete_metadata(self):
        self.assertIn('retention', MODULE.REQUIRED_METADATA)
        self.assertIn('purpose', MODULE.REQUIRED_METADATA)
        self.assertIn('domain', MODULE.REQUIRED_METADATA)

    def test_new_models_are_forbidden_in_legacy_core(self):
        self.assertIn('origination', MODULE.BOUNDED_DOMAIN_APPS)
        self.assertIn('complaints', MODULE.BOUNDED_DOMAIN_APPS)


if __name__ == '__main__':
    unittest.main()
