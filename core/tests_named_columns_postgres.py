"""Actual PostgreSQL locking checks; never substitute SQLite lock semantics."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from types import SimpleNamespace
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import TransactionTestCase
from django.utils import timezone

from core.models import ComplianceAuditChainState, Product, ProductVersion, ProductTatConfiguration, TatTrackerCase, TatConfigurationEvent
from core.services.tat_bm_stage_rollout import prepare, publish
from core.services.tat_configuration import resolve_tat_configuration
from core.services.tat_tracker import update_case
from core.services.workflow_transitions import WorkflowRevisionConflict


@skipUnless(connection.vendor == 'postgresql', 'Requires the task-owned local PostgreSQL database.')
class BMConcurrentWritesTests(TransactionTestCase):
    def setUp(self):
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        self.actor = get_user_model().objects.create_superuser('concurrent-stage-root', password='test-only')
        self.source = ProductVersion.objects.filter(product__code='business', status='published').first()
        if self.source is None:
            from copy import deepcopy
            from core.services.product_catalog import publish_product_version
            from core.services.tat_configuration import GLOBAL_TAT_STAGES
            product = Product.objects.create(code='business', name='Synthetic Business', category='loan')
            self.source = ProductVersion.objects.create(product=product, version=1, min_amount=Decimal('10000'))
            ProductTatConfiguration.objects.create(product_version=self.source, sheet_name='TAT Register',
                case_prefix='SYNTHETIC', remarks_col=0, status_col=0, tat_start_col=0,
                stage_columns={'created': 0}, stages=[deepcopy(row) for row in GLOBAL_TAT_STAGES
                                                if row['key'] != 'bm_analysis_approval'])
            self.source = publish_product_version(version=self.source, actor=self.actor)

    def run_concurrently(self, operation):
        barrier = Barrier(2)

        def run():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return operation()
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(run) for _ in range(2)]
            return [future.result(timeout=30) for future in futures]

    def test_concurrent_preparation_creates_one_successor(self):
        results = self.run_concurrently(lambda: str(prepare(self.source.pk, actor=self.actor).pk))
        self.assertEqual(results[0], results[1])
        self.assertEqual(TatConfigurationEvent.objects.filter(action='bm_analysis_stage_prepared').count(), 1)
        self.assertEqual(self.source.product.versions.filter(status='draft').count(), 1)

    def test_concurrent_decisions_have_one_winner_and_no_double_approval(self):
        draft = prepare(self.source.pk, actor=self.actor)
        publish(draft, actor=self.actor)
        stamp = timezone.now().isoformat()
        case = TatTrackerCase.objects.create(
            group_id='synthetic-concurrency', case_id='SYNTHETIC-BM-CONCURRENT', product_key='business',
            amount=Decimal('25000'), branch='Training', current_stage='bm_analysis_approval',
            configuration_binding_status=TatTrackerCase.CONFIG_VERSIONED,
            tat_configuration_snapshot=resolve_tat_configuration(draft, requested_amount=Decimal('25000')),
            stage_values={'created': stamp, 'mpesa_to_admin': stamp},
        )
        group = SimpleNamespace(group_id=case.group_id, sheet_id='', workflow={'type': 'tat_tracker'})

        def decide():
            try:
                update_case(group, {'roles': ['BM'], 'name': 'Synthetic BM'}, case.case_id,
                            [{'field': 'bm_analysis_approval', 'value': 'Approved'}],
                            expected_revision=case.workflow_revision)
                return 'saved'
            except WorkflowRevisionConflict:
                return 'conflict'

        self.assertCountEqual(self.run_concurrently(decide), ['saved', 'conflict'])
        case.refresh_from_db()
        self.assertEqual(case.current_stage, 'mpesa_verified')
        self.assertEqual(case.events.filter(stage_key='bm_analysis_approval').count(), 1)
