from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import (
    GroupSheetConfiguration,
    TatTrackerCase,
    TatTrackerEvent,
    TatUpdateSideEffectDispatch,
)
from core.services.tat_update_dispatch import (
    MAX_ATTEMPTS,
    process_dispatches,
    reserve_update_dispatches,
)
from core.services.tat_tracker import update_case
from core.services.workflow_timeline import tat_case_timeline


@override_settings(TAT_TRACKER_SIGNATURES_ENABLED=False)
class TatUpdateDispatchTest(TestCase):
    def setUp(self):
        self.config = GroupSheetConfiguration.objects.create(
            group_id='-100-dispatch', display_name='Dispatch test', sheet_id='sheet',
            sheet_name='TRACKER-Business', tat_sheet_projection_enabled=True,
            workflow={
                'type': 'tat_tracker', 'products': ['business'],
                'branches': ['Nakuru'], 'tat_notification_mode': 'shadow',
            },
        )
        self.case = TatTrackerCase.objects.create(
            group_id=self.config.group_id, sheet_id='sheet', sheet_name='TRACKER-Business',
            case_id='JBL-BS-2026-900001', product_key='business',
            product_label='Business', client_name='TEST CLIENT', branch='Nakuru',
            workflow_revision=2,
        )

    def test_reservation_is_unique_and_sheet_processing_is_deferred(self):
        first = reserve_update_dispatches(self.config, self.case, request_id='request-1')
        second = reserve_update_dispatches(self.config, self.case, request_id='request-1')

        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)
        dispatch = TatUpdateSideEffectDispatch.objects.get(
            effect_type=TatUpdateSideEffectDispatch.EFFECT_SHEET,
        )
        self.assertEqual(dispatch.effect_type, TatUpdateSideEffectDispatch.EFFECT_SHEET)
        with patch('core.services.tat_tracker.sync_case_to_sheet', return_value=True) as sync:
            self.assertEqual(process_dispatches(limit=1, dispatch_ids=[str(dispatch.pk)]), 1)
        sync.assert_called_once()
        dispatch.refresh_from_db()
        self.assertEqual(dispatch.status, TatUpdateSideEffectDispatch.STATUS_SUCCEEDED)

    def test_stage_update_commits_without_calling_external_sheet(self):
        self.case.stage_values = {'created': timezone.now().isoformat()}
        self.case.current_stage = 'mpesa_to_admin'
        self.case.save(update_fields=['stage_values', 'current_stage', 'updated_at'])
        user = {
            'name': 'BRO User', 'telegram_id': '111', 'roles': ['BRO'],
            'capabilities': ['tat.home.view', 'tat.stage.mpesa_to_admin.update'],
        }

        with patch('core.services.tat_tracker.sync_case_to_sheet') as sheet_sync:
            detail = update_case(
                self.config, user, self.case.case_id,
                [{'field': 'mpesa_to_admin', 'value': 'STAMP'}],
                expected_revision=self.case.workflow_revision,
                request_id='fast-stamp-request',
            )

        sheet_sync.assert_not_called()
        self.case.refresh_from_db()
        self.assertEqual(self.case.workflow_revision, 3)
        self.assertTrue(self.case.stage_values.get('mpesa_to_admin'))
        self.assertEqual(detail['summary']['workflow_revision'], 3)
        self.assertTrue(self.case.update_dispatches.exists())

    def test_failed_retry_reuses_dispatch_and_becomes_visible_for_attention(self):
        reserve_update_dispatches(self.config, self.case, request_id='request-2')
        dispatch_id = str(TatUpdateSideEffectDispatch.objects.get(
            effect_type=TatUpdateSideEffectDispatch.EFFECT_SHEET,
        ).pk)
        with patch('core.services.tat_tracker.sync_case_to_sheet', side_effect=RuntimeError('provider detail')):
            for _attempt in range(MAX_ATTEMPTS):
                TatUpdateSideEffectDispatch.objects.filter(pk=dispatch_id).update(next_retry_at=timezone.now())
                process_dispatches(limit=1, dispatch_ids=[dispatch_id])

        dispatch = TatUpdateSideEffectDispatch.objects.get(pk=dispatch_id)
        self.assertEqual(TatUpdateSideEffectDispatch.objects.filter(
            effect_type=TatUpdateSideEffectDispatch.EFFECT_SHEET,
        ).count(), 1)
        self.assertEqual(dispatch.total_attempts, MAX_ATTEMPTS)
        self.assertEqual(dispatch.status, TatUpdateSideEffectDispatch.STATUS_NEEDS_ATTENTION)
        self.assertNotIn('provider detail', dispatch.last_error_message)

    def test_older_revision_is_superseded_without_external_processing(self):
        reserve_update_dispatches(self.config, self.case, request_id='request-stale')
        dispatch = TatUpdateSideEffectDispatch.objects.get(
            effect_type=TatUpdateSideEffectDispatch.EFFECT_SHEET,
        )
        self.case.workflow_revision += 1
        self.case.save(update_fields=['workflow_revision', 'updated_at'])

        with patch('core.services.tat_tracker.sync_case_to_sheet') as sheet_sync:
            self.assertEqual(process_dispatches(limit=1, dispatch_ids=[str(dispatch.pk)]), 1)

        sheet_sync.assert_not_called()
        dispatch.refresh_from_db()
        self.assertEqual(dispatch.status, TatUpdateSideEffectDispatch.STATUS_SUPERSEDED)

    def test_staff_timeline_hides_only_duplicate_transition_receipts(self):
        TatTrackerEvent.objects.create(
            case=self.case, group_id=self.case.group_id, actor_name='Officer One',
            stage_key='ca_analysis_sent', stage_label='Credit analysis sent',
            new_value='2026-09-02T12:00:00+03:00', source='mini_app',
        )
        TatTrackerEvent.objects.create(
            case=self.case, group_id=self.case.group_id, actor_name='Officer One',
            stage_key='workflow_transition', stage_label='Workflow transition',
            source='workflow_transition', transition_code='tat.stage.advance',
        )
        TatTrackerEvent.objects.create(
            case=self.case, group_id=self.case.group_id, actor_name='Administrator',
            stage_key='case_details', stage_label='Corrected Branch',
            source='admin_correction', new_value='Nakuru',
        )

        entries = tat_case_timeline(self.case)['entries']
        self.assertEqual(len(entries), 2)
        self.assertEqual({entry['actor'] for entry in entries}, {'Officer One', 'Administrator'})

    def test_template_moves_mode_to_settings_and_restores_collapsed_activity(self):
        template = Path('core/templates/tat_tracker/app.html').read_text(encoding='utf-8')
        script = Path('core/static/miniapp/tat_tracker.js').read_text(encoding='utf-8')

        self.assertNotIn('id="workflowModeBanner"', template)
        self.assertIn('id="tatSettingsDataMode"', template)
        self.assertIn('<details class="activity-panel">', template)
        self.assertIn('id="eventList"', template)
        self.assertIn("keepalive: true", script)
        self.assertNotIn('await loadTaskInbox();', script)
