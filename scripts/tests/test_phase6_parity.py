from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.check_settings_env_parity import env_keys, settings_keys
from scripts.check_dependency_parity import normalize, requirement_contracts, requirement_packages


class SettingsEnvironmentParserTests(unittest.TestCase):
    def test_extracts_only_active_environment_assignments(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / '.env.example'
            path.write_text('# COMMENTED=value\nACTIVE=value\nEMPTY=\n', encoding='utf-8')
            self.assertEqual(env_keys(path), {'ACTIVE', 'EMPTY'})

    def test_extracts_literal_decouple_keys(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.py'
            path.write_text("A = config('ALPHA')\nB = config('BETA', default='')\n", encoding='utf-8')
            self.assertEqual(settings_keys(path), {'ALPHA', 'BETA'})


class DependencyParserTests(unittest.TestCase):
    def test_normalizes_distribution_names_and_extras(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'requirements.txt'
            path.write_text('Django==5.1.6\npsycopg[binary]>=3.1 # adapter\n', encoding='utf-8')
            self.assertEqual(requirement_packages(path), {'django', 'psycopg'})
            self.assertEqual(requirement_contracts(path)['psycopg'], ('>=3.1', ('binary',)))
        self.assertEqual(normalize('google_auth.httplib2'), 'google-auth-httplib2')


if __name__ == '__main__':
    unittest.main()
