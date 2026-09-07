from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from core.models import (
    AccessGrant,
    ComplianceAuditEvent,
    GroupSheetConfiguration,
    LiveSheetRecordChange,
    Product,
    ProductAvailability,
    ProductTatConfiguration,
    ProductVersion,
    TatActionTask,
    TatCaseSequence,
    TatPresentationSettings,
    TatResponsibilityAssignment,
    TatResponsibilityChangePlan,
    TatResponsibilityEvent,
    TatTrackerApprovalCertificate,
    TatTrackerCase,
    TatTrackerEvent,
    TatUpdateSideEffectDispatch,
    WorkflowDataModeEvent,
    WorkflowDataModeState,
    WorkflowTatDailyMetric,
)
from core.services.access_grant_governance import governed_access_grant_mutation
from core.services.tat_full_reset import (
    TAT_RESET_MODELS,
    TatFullResetError,
    preview_full_tat_reset,
    reset_all_tat_data,
)


@override_settings(
    TELEGRAM_BOT_TOKEN='',
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
)
class TatFullResetTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.root = User.objects.create_superuser(
            'tat-reset-root', 'tat-reset-root@example.test', 'password',
        )
        self.staff = User.objects.create_user('tat-reset-staff', is_staff=True)
        self.group = GroupSheetConfiguration.objects.create(
            group_id='-100-tat-full-reset',
            display_name='TAT full reset test',
            sheet_id='tat-reset-sheet',
            sheet_name='TRACKER-Business',
            workflow={'type': 'tat_tracker'},
        )
        self.other_group = GroupSheetConfiguration.objects.create(
            group_id='-100-other-workflow',
            display_name='Other workflow',
            sheet_id='other-sheet',
            sheet_name='Cases',
            workflow={'type': 'case'},
        )
        with governed_access_grant_mutation('TAT full-reset test setup'):
            self.grant = AccessGrant.objects.create(
                user=self.staff,
                workflow='tat_tracker',
                role='BRO',
                group_configuration=self.group,
            )
        self.product = Product.objects.create(
            name='TAT Reset Loan', code='tat-reset-loan', category='loan',
        )
        self.version = ProductVersion.objects.create(
            product=self.product,
            version=1,
            currency='KES',
            min_amount=Decimal('1000'),
            max_amount=Decimal('100000'),
            created_by=self.root,
        )
        self.tat_configuration = ProductTatConfiguration.objects.create(
            product_version=self.version,
            sheet_name='TRACKER-Business',
            case_prefix='TAT',
            remarks_col=10,
            status_col=11,
            tat_start_col=12,
            stage_columns={'created': 12},
            stages=[{
                'key': 'created', 'label': 'Created', 'role': 'BRO', 'column': 12,
            }],
        )
        self.case = TatTrackerCase.objects.create(
            group_id=self.group.group_id,
            sheet_id=self.group.sheet_id,
            sheet_name=self.group.sheet_name,
            case_id='TAT-RESET-001',
            product_key=self.product.code,
            product_label=self.product.name,
            product=self.product,
            product_version=self.version,
            client_name='Synthetic TAT Client',
            branch='Nakuru',
        )
        self.event = TatTrackerEvent.objects.create(
            case=self.case,
            group_id=self.group.group_id,
            stage_key='created',
            stage_label='Created',
            actor_user=self.staff,
        )
        TatTrackerApprovalCertificate.objects.create(
            case=self.case,
            event=self.event,
            staff_user=self.staff,
            signer_name='TAT Reset Staff',
            stage_key='created',
            external_reference='tat-reset-certificate',
        )
        TatUpdateSideEffectDispatch.objects.create(
            case=self.case,
            workflow_revision=self.case.workflow_revision,
            effect_type=TatUpdateSideEffectDispatch.EFFECT_SHEET,
        )
        self.assignment = TatResponsibilityAssignment.objects.create(
            group_configuration=self.group,
            branch='Nakuru',
            role='BRO',
            product_key=self.product.code,
            primary_user=self.staff,
            created_by=self.root,
        )
        TatResponsibilityEvent.objects.create(
            assignment=self.assignment,
            assignment_id_snapshot=self.assignment.pk,
            action=TatResponsibilityEvent.ACTION_CREATED,
            actor=self.root,
        )
        TatResponsibilityChangePlan.objects.create(
            assignment=self.assignment,
            proposed_snapshot={'active': False},
            expected_updated_at=self.assignment.updated_at,
            reason='Synthetic reset coverage.',
            request_id='tat-reset-change-plan',
            created_by=self.root,
        )
        TatActionTask.objects.create(
            case=self.case,
            group_configuration=self.group,
            assignment=self.assignment,
            stage_key='created',
            stage_label='Created',
            responsible_role='BRO',
            case_revision=self.case.workflow_revision,
        )
        TatCaseSequence.objects.create(
            group_id=self.group.group_id,
            product_key=self.product.code,
            year=2026,
            next_number=2,
        )
        TatPresentationSettings.objects.update_or_create(
            singleton=1,
            defaults={'updated_by': self.root},
        )
        ProductAvailability.objects.create(
            product=self.product,
            workflow='tat_tracker',
            channel='telegram',
        )
        self.other_availability = ProductAvailability.objects.create(
            product=self.product,
            workflow='jawabu_portal',
            channel='portal',
        )
        LiveSheetRecordChange.objects.create(
            group_configuration=self.group,
            group_id=self.group.group_id,
            sheet_id=self.group.sheet_id,
            sheet_tab=self.group.sheet_name,
            row_number=2,
            record_key=self.case.case_id,
            action='update',
            status='success',
        )
        self.other_sheet_change = LiveSheetRecordChange.objects.create(
            group_configuration=self.other_group,
            group_id=self.other_group.group_id,
            sheet_id=self.other_group.sheet_id,
            sheet_tab=self.other_group.sheet_name,
            row_number=2,
            record_key='CMP-KEEP',
            action='update',
            status='success',
        )
        WorkflowTatDailyMetric.objects.create(
            metric_date=date(2026, 9, 1),
            workflow='tat_tracker',
            group_id=self.group.group_id,
            stage_key='created',
        )
        self.other_metric = WorkflowTatDailyMetric.objects.create(
            metric_date=date(2026, 9, 1),
            workflow='jawabu_pipeline',
            group_id=self.other_group.group_id,
            stage_key='submitted',
        )
        self.mode_state = WorkflowDataModeState.objects.get(pk=1)
        self.spin_state = (
            self.mode_state.spin_mode,
            self.mode_state.spin_pilot_cycle_id,
            self.mode_state.spin_mode_version,
            self.mode_state.active_spin_purge_id,
        )
        self.old_tat_cycle = self.mode_state.tat_pilot_cycle_id
        self.old_tat_version = self.mode_state.tat_mode_version
        WorkflowDataModeEvent.objects.create(
            workflow='tat_tracker',
            action='cycle_rotated',
            old_mode='pilot',
            new_mode='pilot',
            reason='Synthetic TAT event.',
            actor=self.root,
        )
        self.spin_event = WorkflowDataModeEvent.objects.create(
            workflow='spin',
            action='cycle_rotated',
            old_mode='pilot',
            new_mode='pilot',
            reason='SPIN must survive.',
            actor=self.root,
        )

    def test_registry_covers_every_tat_owned_model(self):
        discovered = {
            model
            for model in apps.get_app_config('core').get_models()
            if model.__name__.startswith(('Tat', 'WorkflowTat', 'ProductTat'))
        }
        self.assertEqual(set(TAT_RESET_MODELS), discovered)

    def test_service_rejects_non_superuser(self):
        before = preview_full_tat_reset()['counts']
        with self.assertRaisesRegex(TatFullResetError, 'Superuser'):
            reset_all_tat_data(
                actor=self.staff,
                reason='Synthetic cleanup.',
                request_id='tat-reset-denied',
            )
        self.assertEqual(preview_full_tat_reset()['counts'], before)

    def test_reset_clears_tat_database_state_and_preserves_shared_records(self):
        before = preview_full_tat_reset()
        self.assertGreater(before['total'], 0)

        result = reset_all_tat_data(
            actor=self.root,
            reason='Clear complete synthetic TAT state.',
            request_id='tat-full-reset-1',
        )

        self.assertFalse(result['replayed'])
        self.assertEqual(result['after']['total'], 0)
        self.assertFalse(TatTrackerCase.objects.exists())
        self.assertFalse(TatTrackerEvent.objects.exists())
        self.assertFalse(TatTrackerApprovalCertificate.objects.exists())
        self.assertFalse(TatResponsibilityAssignment.objects.exists())
        self.assertFalse(ProductTatConfiguration.objects.exists())
        self.assertFalse(WorkflowTatDailyMetric.objects.filter(workflow='tat_tracker').exists())
        self.assertFalse(WorkflowDataModeEvent.objects.filter(workflow='tat_tracker').exists())

        self.assertTrue(get_user_model().objects.filter(pk=self.staff.pk).exists())
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())
        self.assertTrue(ProductVersion.objects.filter(pk=self.version.pk).exists())
        self.assertTrue(GroupSheetConfiguration.objects.filter(pk=self.group.pk).exists())
        self.assertTrue(AccessGrant.objects.filter(pk=self.grant.pk).exists())
        self.assertTrue(ProductAvailability.objects.filter(pk=self.other_availability.pk).exists())
        self.assertTrue(LiveSheetRecordChange.objects.filter(pk=self.other_sheet_change.pk).exists())
        self.assertTrue(WorkflowTatDailyMetric.objects.filter(pk=self.other_metric.pk).exists())
        self.assertTrue(WorkflowDataModeEvent.objects.filter(pk=self.spin_event.pk).exists())

        state = WorkflowDataModeState.objects.get(pk=1)
        self.assertEqual(
            (state.spin_mode, state.spin_pilot_cycle_id, state.spin_mode_version, state.active_spin_purge_id),
            self.spin_state,
        )
        self.assertEqual(state.tat_mode, 'pilot')
        self.assertNotEqual(state.tat_pilot_cycle_id, self.old_tat_cycle)
        self.assertEqual(state.tat_mode_version, self.old_tat_version + 1)
        reset_event = ComplianceAuditEvent.objects.get(
            deduplication_key='tat:full-reset:tat-full-reset-1',
        )
        self.assertEqual(reset_event.action, 'database_reset')
        self.assertEqual(reset_event.metadata['scope'], 'tat_database_only')

        replay = reset_all_tat_data(
            actor=self.root,
            reason='Clear complete synthetic TAT state.',
            request_id='tat-full-reset-1',
        )
        self.assertTrue(replay['replayed'])
        state.refresh_from_db()
        self.assertEqual(state.tat_mode_version, self.old_tat_version + 1)
        self.assertEqual(
            ComplianceAuditEvent.objects.filter(
                deduplication_key='tat:full-reset:tat-full-reset-1',
            ).count(),
            1,
        )

    def test_reset_rolls_back_when_a_delete_step_fails(self):
        from core.services import tat_full_reset

        before = preview_full_tat_reset()['counts']
        real_delete = tat_full_reset._delete_target
        call_count = 0

        def fail_during_reset(target, *, tat_group_ids, counts):
            nonlocal call_count
            call_count += 1
            real_delete(target, tat_group_ids=tat_group_ids, counts=counts)
            if call_count == 5:
                raise RuntimeError('Injected TAT reset failure')

        with patch.object(tat_full_reset, '_delete_target', side_effect=fail_during_reset):
            with self.assertRaisesRegex(RuntimeError, 'Injected TAT reset failure'):
                reset_all_tat_data(
                    actor=self.root,
                    reason='Rollback synthetic TAT reset.',
                    request_id='tat-reset-rollback',
                )
        self.assertEqual(preview_full_tat_reset()['counts'], before)
        self.assertFalse(ComplianceAuditEvent.objects.filter(
            deduplication_key='tat:full-reset:tat-reset-rollback',
        ).exists())

    @override_settings(TAT_FULL_RESET_ENABLED=False)
    def test_endpoint_is_disabled_by_default(self):
        self.client.force_login(self.root)
        response = self.client.get(reverse('admin:core_tat_full_reset'))
        self.assertEqual(response.status_code, 403)

    @override_settings(TAT_FULL_RESET_ENABLED=True)
    def test_endpoint_requires_superuser_reason_and_exact_phrase(self):
        url = reverse('admin:core_tat_full_reset')
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(url).status_code, 403)

        self.client.force_login(self.root)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'RESET ALL TAT DATA')
        self.assertContains(response, 'Google Sheets rows')

        response = self.client.post(url, {
            'confirmation': 'RESET TAT',
            'reason': 'Synthetic cleanup.',
            'request_id': 'wrong-tat-confirmation',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'exact confirmation phrase')
        self.assertTrue(TatTrackerCase.objects.exists())

    @override_settings(TAT_FULL_RESET_ENABLED=True)
    def test_admin_confirmation_executes_reset(self):
        self.client.force_login(self.root)
        url = reverse('admin:core_tat_full_reset')
        response = self.client.post(url, {
            'confirmation': 'RESET ALL TAT DATA',
            'reason': 'Clear TAT records through the guarded Admin control.',
            'request_id': 'tat-admin-reset-success',
        })

        self.assertRedirects(response, url)
        self.assertFalse(TatTrackerCase.objects.exists())
        self.assertTrue(ComplianceAuditEvent.objects.filter(
            deduplication_key='tat:full-reset:tat-admin-reset-success',
        ).exists())

    @override_settings(TAT_FULL_RESET_ENABLED=True)
    def test_admin_button_and_sidebar_link_are_superuser_only(self):
        self.client.force_login(self.root)
        response = self.client.get(reverse('admin:core_tattrackercase_changelist'))
        self.assertContains(response, 'Reset TAT database')
        response = self.client.get(reverse('admin:index'))
        self.assertContains(response, 'Reset all TAT data')

        from core.admin_navigation import get_admin_navigation

        request = RequestFactory().get('/admin/')
        request.user = self.staff
        navigation = get_admin_navigation(request)
        reset_item = next(
            item
            for group in navigation
            for item in group.get('items', [])
            if item.get('title') == 'Reset all TAT data'
        )
        self.assertFalse(reset_item['permission'](request))
