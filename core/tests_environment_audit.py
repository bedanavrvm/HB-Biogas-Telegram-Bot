from pathlib import Path
import re
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from core.services.environment_audit import audit_environment, clean_environment


class EnvironmentAuditTests(SimpleTestCase):
    def test_audit_reports_names_and_never_values(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text(
                'DJANGO_SECRET_KEY=never-print-this\n'
                'SECURE_SSL_REDIRECT=True\n'
                'ORDER_APPROVAL_WEBAPP_ENABLED=False\n',
                encoding='utf-8',
            )

            report = audit_environment(path)

        self.assertEqual(report['summary']['retained'], 1)
        self.assertEqual(report['summary']['redundant_default'], 1)
        self.assertEqual(report['summary']['deprecated'], 1)
        self.assertNotIn('never-print-this', str(report))

    def test_cleaner_preserves_non_default_values_and_creates_backup(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text(
                'SECURE_SSL_REDIRECT=False\n'
                'MEDIA_MAX_FILE_SIZE_MB=20\n'
                'SENTRY_BROWSER_TRACES_SAMPLE_RAT=0.5\n',
                encoding='utf-8',
            )

            report = clean_environment(path)
            cleaned = path.read_text(encoding='utf-8')

            self.assertIn('SECURE_SSL_REDIRECT=False', cleaned)
            self.assertNotIn('MEDIA_MAX_FILE_SIZE_MB', cleaned)
            self.assertNotIn('SENTRY_BROWSER_TRACES_SAMPLE_RAT', cleaned)
            self.assertTrue(Path(report['backup']).exists())

    def test_environment_templates_are_split_and_have_no_deprecated_names(self):
        root = Path(__file__).resolve().parent.parent
        minimal = (root / '.env.example').read_text(encoding='utf-8')
        optional = (root / '.env.optional.example').read_text(encoding='utf-8')

        self.assertLess(sum('=' in line for line in minimal.splitlines()), 40)
        self.assertIn('COMPLAINT_CASE_MAX_TOTAL_UPLOAD_MB=30', optional)
        self.assertNotIn('ORDER_APPROVAL_MAX_TOTAL_UPLOAD_MB=', minimal + optional)
        self.assertNotIn('ORDER_APPROVAL_WEBAPP_ENABLED=', minimal + optional)
        self.assertNotIn('SENTRY_BROWSER_TRACES_SAMPLE_RAT=', minimal + optional)

    def test_every_documented_environment_name_is_consumed_by_code(self):
        root = Path(__file__).resolve().parent.parent
        templates = '\n'.join(
            (root / name).read_text(encoding='utf-8')
            for name in ('.env.example', '.env.optional.example')
        )
        documented = {
            match.group(1) for match in re.finditer(
                r'^\s*([A-Z][A-Z0-9_]*)\s*=', templates, re.MULTILINE,
            )
        }
        source = '\n'.join(
            path.read_text(encoding='utf-8', errors='ignore')
            for directory in ('config', 'core')
            for path in (root / directory).rglob('*.py')
            if 'migrations' not in path.parts and not path.name.startswith('tests')
        )
        unsupported = {
            key for key in documented
            if not re.search(rf"['\"]{re.escape(key)}['\"]", source)
        }

        self.assertEqual(unsupported, set())
