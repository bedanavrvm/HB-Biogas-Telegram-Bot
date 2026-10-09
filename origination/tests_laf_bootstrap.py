from datetime import timedelta
from io import StringIO
from unittest.mock import patch
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection, close_old_connections
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from core.models import ComplianceAuditChainState, ComplianceAuditEvent, IntegrationOperation, Product
from origination.models import OriginationDocumentProductEligibility, OriginationDocumentTemplate
from origination.services import origination_laf_bootstrap as bootstrap


@override_settings(ORIGINATION_LAF_BOOTSTRAP_ENABLED=True, ORIGINATION_LAF_BOOTSTRAP_ACTOR='laf-bootstrap-root')
class LafBootstrapTests(TestCase):
    def setUp(self):
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        self.actor = get_user_model().objects.create_superuser('laf-bootstrap-root', 'root@example.test', 'password')
        self.upload = self.enterContext(patch('origination.services.origination_templates._upload_template_bytes',
                                             side_effect=lambda template, **kw: (f'synthetic-{template.pk}', 'https://drive.example.test/blank')))

    def test_dry_run_is_read_only_and_all_eleven_assets_are_valid(self):
        result = bootstrap.bootstrap_lafs()
        self.assertEqual(result['documents'], 11)
        self.assertNotIn('water_tank', [item.key for item in bootstrap.bundled_definitions()])
        self.assertFalse(OriginationDocumentTemplate.objects.exists())
        self.assertFalse(IntegrationOperation.objects.exists())
        self.upload.assert_not_called()

    def test_first_apply_seeds_once_without_products_assignment_or_publication(self):
        product_ids = set(Product.objects.values_list('pk', flat=True))
        self.assertEqual(bootstrap.bootstrap_lafs_from_environment()['status'], 'completed')
        self.assertEqual(OriginationDocumentTemplate.objects.count(), 11)
        self.assertEqual(set(Product.objects.values_list('pk', flat=True)), product_ids)
        self.assertFalse(OriginationDocumentProductEligibility.objects.exists())
        self.assertFalse(OriginationDocumentTemplate.objects.exclude(status='ready').exists())
        self.assertTrue(all(t.form_schema.get('value_contract_version') == 2
                            for t in OriginationDocumentTemplate.objects.all()))
        self.assertEqual(bootstrap.bootstrap_lafs_from_environment()['status'], 'already_completed')
        self.assertEqual(self.upload.call_count, 11)

    def test_completed_fingerprint_survives_deleted_draft_and_force_recreates_it(self):
        bootstrap.bootstrap_lafs(apply=True)
        template = OriginationDocumentTemplate.objects.first()
        from origination.services.origination_god_mode import _purge_template
        from collections import Counter
        _purge_template(template.pk, Counter())
        self.assertEqual(bootstrap.bootstrap_lafs(apply=True)['status'], 'already_completed')
        self.assertEqual(OriginationDocumentTemplate.objects.count(), 10)
        self.assertEqual(bootstrap.bootstrap_lafs(apply=True, force=True)['status'], 'completed')
        self.assertEqual(OriginationDocumentTemplate.objects.count(), 11)

    def test_interrupted_apply_retains_drafts_and_resumes_without_duplicate_uploads(self):
        real = bootstrap.apply_seed
        count = 0
        def interrupted(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 3:
                raise ValueError('synthetic interruption')
            return real(*args, **kwargs)
        with patch.object(bootstrap, 'apply_seed', side_effect=interrupted):
            with self.assertRaises(bootstrap.LafBootstrapError):
                bootstrap.bootstrap_lafs(apply=True)
        self.assertEqual(OriginationDocumentTemplate.objects.count(), 2)
        self.assertFalse(ComplianceAuditEvent.objects.filter(action='laf.bootstrap_completed').exists())
        bootstrap.bootstrap_lafs(apply=True)
        self.assertEqual(OriginationDocumentTemplate.objects.count(), 11)
        self.assertEqual(self.upload.call_count, 11)

    def test_preflight_failure_does_not_start_partial_seed(self):
        with patch.object(bootstrap, 'preflight_seed', side_effect=ValueError('synthetic invalid source')):
            with self.assertRaises(ValueError):
                bootstrap.bootstrap_lafs(apply=True)
        self.assertFalse(IntegrationOperation.objects.exists())
        self.upload.assert_not_called()

    def test_live_lease_prevents_second_attempt_and_expired_lease_recovers(self):
        key = f'origination:laf-bootstrap:{bootstrap.bootstrap_fingerprint()}'
        operation = IntegrationOperation.objects.create(integration='google_drive', operation_type='origination_laf_bootstrap',
                                                        deduplication_key=key, status='running', last_attempt_at=timezone.now())
        self.assertEqual(bootstrap.bootstrap_lafs(apply=True)['status'], 'running')
        self.upload.assert_not_called()
        IntegrationOperation.objects.filter(pk=operation.pk).update(last_attempt_at=timezone.now() - timedelta(hours=1))
        self.assertEqual(bootstrap.bootstrap_lafs(apply=True)['status'], 'completed')

    @override_settings(ORIGINATION_LAF_BOOTSTRAP_ENABLED=False)
    def test_disabled_has_no_reads_or_uploads(self):
        with self.assertNumQueries(0):
            self.assertEqual(bootstrap.bootstrap_lafs_from_environment()['status'], 'disabled')

    def test_actor_must_be_existing_active_superuser(self):
        for username in ('', 'missing-user'):
            with override_settings(ORIGINATION_LAF_BOOTSTRAP_ACTOR=username):
                with self.assertRaises(bootstrap.LafBootstrapError):
                    bootstrap.bootstrap_lafs(apply=True)
        self.upload.assert_not_called()

    def test_command_defaults_to_dry_run(self):
        output = StringIO()
        call_command('bootstrap_origination_lafs', stdout=output)
        self.assertIn('dry_run', output.getvalue())
        self.upload.assert_not_called()

    def test_missing_optional_assets_are_safe_when_disabled_and_actionable_when_enabled(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        with TemporaryDirectory() as folder, patch.object(bootstrap, 'ASSET_ROOT', Path(folder)):
            with override_settings(ORIGINATION_LAF_BOOTSTRAP_ENABLED=False):
                self.assertEqual(bootstrap.bootstrap_lafs_from_environment()['status'], 'disabled')
            with self.assertRaisesMessage(bootstrap.LafBootstrapError, 'bundle is missing or invalid'):
                bootstrap.bootstrap_lafs_from_environment()
        self.upload.assert_not_called()


class BlankBundleContractTests(SimpleTestCase):
    def test_bundle_bytes_are_hash_pinned_blank_and_metadata_free(self):
        import hashlib
        from pypdf import PdfReader
        from scripts.audit_tracked_artifacts import load_allowlist
        allowlist = load_allowlist()
        for definition in bootstrap.bundled_definitions():
            with self.subTest(document=definition.key):
                path = bootstrap.ASSET_ROOT / definition.filename
                data = path.read_bytes()
                digest = hashlib.sha256(data).hexdigest()
                self.assertEqual(digest, definition.sha256)
                self.assertEqual(len(data), definition.byte_size)
                self.assertEqual(allowlist['origination/assets/lafs/' + definition.filename]['sha256'], digest)
                reader = PdfReader(path)
                self.assertEqual(len(reader.pages), definition.page_count)
                self.assertFalse(reader.metadata)
                self.assertNotIn(b'<dc:creator', data)
                self.assertNotIn(b'<pdf:Author', data)
                self.assertFalse(any(field.get('/V') for field in (reader.get_fields() or {}).values()))


@skipUnless(connection.vendor == 'postgresql', 'Requires real PostgreSQL row locks.')
@override_settings(ORIGINATION_LAF_BOOTSTRAP_ACTOR='concurrent-laf-root')
class ConcurrentLafBootstrapTests(TransactionTestCase):
    def test_two_first_requests_share_one_lease_and_upload_each_document_once(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        get_user_model().objects.create_superuser('concurrent-laf-root', password='synthetic')
        started, release = Event(), Event()
        apply = bootstrap.apply_seed
        def slow_first(definition, **kwargs):
            if definition.key == bootstrap.SOURCE_DEFINITIONS[0].key:
                started.set()
                if not release.wait(20):
                    raise RuntimeError('Synthetic test coordinator timed out.')
            return apply(definition, **kwargs)
        def run():
            close_old_connections()
            try:
                return bootstrap.bootstrap_lafs(apply=True)
            finally:
                close_old_connections()
        with patch.object(bootstrap, 'apply_seed', side_effect=slow_first), patch(
            'origination.services.origination_templates._upload_template_bytes',
            side_effect=lambda template, **kw: (f'synthetic-{template.pk}', 'https://drive.example.test/blank'),
        ) as upload, ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(run)
            try:
                self.assertTrue(started.wait(20))
                self.assertEqual(pool.submit(run).result(timeout=20)['status'], 'running')
            finally:
                release.set()
            self.assertEqual(first.result(timeout=30)['status'], 'completed')
        self.assertEqual(upload.call_count, 11)
        self.assertEqual(OriginationDocumentTemplate.objects.count(), 11)
        self.assertEqual(ComplianceAuditEvent.objects.filter(action='laf.bootstrap_completed').count(), 1)

