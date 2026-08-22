from types import SimpleNamespace
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse

from core.models import (
    GroupSheetConfiguration,
    MediaAttachment,
    SpinCreditRequest,
    TatTrackerCase,
    WorkflowDataModeEvent,
    WorkflowDataModeState,
    WorkflowPilotPurgeRun,
)
from core.services.tat_tracker import next_case_id, product_by_key
from core.services.workflow_data_mode import (
    WORKFLOW_SPIN,
    WORKFLOW_TAT,
    WorkflowModeChanged,
    assert_record_writable,
    change_mode,
    mode_snapshot,
    operational_spin_requests,
    operational_tat_cases,
    rotate_pilot_cycle,
)
from core.services.workflow_pilot_purge import (
    acknowledge_sheet_readiness,
    preview_purge,
    process_purge,
    start_purge,
)


class FakeWorksheet:
    def __init__(self, rows):
        self.rows = [list(row) for row in rows]
        self.deleted_rows = []

    def get_all_values(self, value_render_option=None):
        return [list(row) for row in self.rows]

    def delete_rows(self, row_number):
        self.deleted_rows.append(row_number)
        del self.rows[row_number - 1]


class WorkflowDataModeTests(TestCase):
    def setUp(self):
        self.superuser = get_user_model().objects.create_superuser(
            username='pilot-admin', email='pilot@example.invalid', password='test-password',
        )

    def spin(self, source_hash, **overrides):
        values = {
            'group_id': '-100pilot',
            'source_message_hash': source_hash,
            'request_type': 'spin',
        }
        values.update(overrides)
        return SpinCreditRequest.objects.create(**values)

    def tat(self, case_id, **overrides):
        values = {
            'group_id': '-100tatpilot',
            'case_id': case_id,
            'product_key': 'business',
            'product_label': 'Business',
            'client_name': 'SYNTHETIC APPLICANT',
        }
        values.update(overrides)
        return TatTrackerCase.objects.create(**values)

    def test_direct_creates_snapshot_current_pilot_cycle(self):
        spin = self.spin('a' * 64)
        tat = self.tat('JBL-BS-2026-001')
        state = WorkflowDataModeState.objects.get(pk=1)

        self.assertEqual(spin.data_mode, 'pilot')
        self.assertEqual(spin.pilot_cycle_id, state.spin_pilot_cycle_id)
        self.assertEqual(spin.data_scope_key, f'pilot:{state.spin_pilot_cycle_id}')
        self.assertEqual(tat.pilot_cycle_id, state.tat_pilot_cycle_id)

    def test_rotation_closes_prior_cycle_and_active_cycle_is_never_previewed(self):
        closed = self.spin('b' * 64)
        rotate_pilot_cycle(
            WORKFLOW_SPIN, actor=self.superuser, reason='Close first synthetic cycle.',
            request_id='rotate-one',
        )
        active = self.spin('c' * 64)

        self.assertNotIn(closed, list(operational_spin_requests()))
        self.assertIn(active, list(operational_spin_requests()))
        preview_ids = {item['record_id'] for item in preview_purge(WORKFLOW_SPIN)['manifest']['records']}
        self.assertIn(str(closed.pk), preview_ids)
        self.assertNotIn(str(active.pk), preview_ids)

    def test_switching_to_production_does_not_make_unrotated_pilot_cycle_purgeable(self):
        protected = self.spin('9' * 64)
        change_mode(
            WORKFLOW_SPIN, 'production', actor=self.superuser,
            reason='Move new creation into production.', request_id='protect-last-pilot',
        )

        preview_ids = {
            item['record_id'] for item in preview_purge(WORKFLOW_SPIN)['manifest']['records']
        }
        self.assertNotIn(str(protected.pk), preview_ids)

    def test_mode_change_is_snapshot_based_idempotent_and_audited(self):
        pilot = self.spin('d' * 64)
        _, first, replayed = change_mode(
            WORKFLOW_SPIN, 'production', actor=self.superuser,
            reason='Begin controlled production.', request_id='mode-production',
        )
        _, replay, replayed_again = change_mode(
            WORKFLOW_SPIN, 'production', actor=self.superuser,
            reason='Begin controlled production.', request_id='mode-production',
        )
        production = self.spin('e' * 64)

        self.assertFalse(replayed)
        self.assertTrue(replayed_again)
        self.assertEqual(first.pk, replay.pk)
        self.assertEqual(WorkflowDataModeEvent.objects.filter(action='mode_changed').count(), 1)
        self.assertEqual(production.data_mode, 'production')
        self.assertNotIn(pilot, list(operational_spin_requests()))
        self.assertIn(production, list(operational_spin_requests()))

    def test_closed_pilot_write_returns_stable_mode_changed_error(self):
        record = self.tat('JBL-BS-2026-002')
        old_version = mode_snapshot(WORKFLOW_TAT).mode_version
        rotate_pilot_cycle(
            WORKFLOW_TAT, actor=self.superuser, reason='Close cycle.', request_id='tat-rotate',
        )
        with self.assertRaises(WorkflowModeChanged) as raised:
            assert_record_writable(record, expected_mode_version=old_version)
        self.assertEqual(raised.exception.code, 'WORKFLOW_MODE_CHANGED')
        detail = operational_tat_cases(TatTrackerCase.objects.filter(pk=record.pk))
        self.assertFalse(detail.exists())

    def test_local_purge_deletes_closed_rows_only_and_leaves_media(self):
        closed = self.spin('f' * 64)
        media = MediaAttachment.objects.create(group_id='-100pilot', telegram_file_id='synthetic-file')
        rotate_pilot_cycle(
            WORKFLOW_SPIN, actor=self.superuser, reason='Close disposable cycle.',
            request_id='rotate-disposable',
        )
        active = self.spin('1' * 64)
        production = self.spin(
            '2' * 64, data_mode='production', pilot_cycle_id=None, data_scope_key='production',
        )
        preview = preview_purge(WORKFLOW_SPIN)
        run, replayed = start_purge(
            WORKFLOW_SPIN, preview['manifest_hash'], actor=self.superuser,
            reason='Remove synthetic closed-cycle rows.', request_id='purge-local',
        )
        completed = process_purge(run.pk)

        self.assertFalse(replayed)
        self.assertEqual(completed.status, 'completed')
        self.assertFalse(SpinCreditRequest.objects.filter(pk=closed.pk).exists())
        self.assertTrue(SpinCreditRequest.objects.filter(pk=active.pk).exists())
        self.assertTrue(SpinCreditRequest.objects.filter(pk=production.pk).exists())
        self.assertTrue(MediaAttachment.objects.filter(pk=media.pk).exists())
        self.assertIsNone(WorkflowDataModeState.objects.get(pk=1).active_spin_purge_id)

    def test_sheet_purge_requires_fingerprint_ack_then_repairs_surviving_pointer(self):
        config = GroupSheetConfiguration.objects.create(
            group_id='-100sheetpilot', display_name='Synthetic SPIN', enabled=True,
            sheet_id='synthetic-sheet', sheet_name='SPIN Register',
            workflow={'type': 'spin_credit_analysis', 'batch_sheet_name': 'SPIN Register'},
        )
        closed = self.spin(
            '3' * 64, group_id=config.group_id, sheet_id=config.sheet_id,
            sheet_name=config.sheet_name, row_number=2,
            public_sequence_year=2026, public_sequence_number=1,
        )
        rotate_pilot_cycle(
            WORKFLOW_SPIN, actor=self.superuser, reason='Close Sheet-backed cycle.',
            request_id='rotate-sheet',
        )
        survivor = self.spin(
            '4' * 64, group_id=config.group_id, sheet_id=config.sheet_id,
            sheet_name=config.sheet_name, row_number=3,
            public_sequence_year=2026, public_sequence_number=2,
            data_mode='production', pilot_cycle_id=None, data_scope_key='production',
        )
        sheet = FakeWorksheet([
            ['Request ID', 'Status'],
            ['SPIN-2026-0001', 'Pilot'],
            ['SPIN-2026-0002', 'Production'],
        ])
        preview = preview_purge(WORKFLOW_SPIN)
        with patch('core.services.workflow_pilot_purge._worksheet', return_value=sheet):
            with self.assertRaises(ValidationError):
                start_purge(
                    WORKFLOW_SPIN, preview['manifest_hash'], actor=self.superuser,
                    reason='Verified Sheet purge.', request_id='sheet-purge-blocked',
                )
            acknowledge_sheet_readiness(
                WORKFLOW_SPIN, config.sheet_id, config.sheet_name,
                actor=self.superuser, note='Checked formulas and all fixed ranges.',
            )
            run, _ = start_purge(
                WORKFLOW_SPIN, preview['manifest_hash'], actor=self.superuser,
                reason='Verified Sheet purge.', request_id='sheet-purge-ready',
            )
            completed = process_purge(run.pk)

        self.assertEqual(completed.status, 'completed')
        self.assertEqual(sheet.deleted_rows, [2])
        self.assertFalse(SpinCreditRequest.objects.filter(pk=closed.pk).exists())
        survivor.refresh_from_db()
        self.assertEqual(survivor.row_number, 2)

    def test_concurrent_purge_for_same_workflow_is_blocked(self):
        self.spin('5' * 64)
        rotate_pilot_cycle(
            WORKFLOW_SPIN, actor=self.superuser, reason='Close a purgeable cycle.',
            request_id='rotate-lock',
        )
        preview = preview_purge(WORKFLOW_SPIN)
        first, _ = start_purge(
            WORKFLOW_SPIN, preview['manifest_hash'], actor=self.superuser,
            reason='First purge owns the lock.', request_id='purge-lock-one',
        )
        with self.assertRaises(ValidationError):
            start_purge(
                WORKFLOW_SPIN, preview['manifest_hash'], actor=self.superuser,
                reason='Second purge must not interleave.', request_id='purge-lock-two',
            )
        self.assertEqual(WorkflowPilotPurgeRun.objects.get(pk=first.pk).status, 'pending')

    def test_tat_sequence_does_not_reuse_deleted_case_number(self):
        group = SimpleNamespace(group_id='-100sequence')
        product = product_by_key('business')
        first = next_case_id(group, product)
        second = next_case_id(group, product)
        self.assertNotEqual(first, second)
        self.assertEqual(int(second.rsplit('-', 1)[-1]), int(first.rsplit('-', 1)[-1]) + 1)

    def test_admin_switchboard_is_superuser_only(self):
        state = WorkflowDataModeState.objects.get(pk=1)
        staff = get_user_model().objects.create_user(
            username='ordinary-admin', password='test-password', is_staff=True,
        )
        change_url = reverse('admin:core_workflowdatamodestate_change', args=[state.pk])
        self.client.force_login(staff)
        self.assertEqual(self.client.get(change_url).status_code, 403)
        self.client.force_login(self.superuser)
        response = self.client.get(change_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Pilot cleanup')

    def test_admin_mode_change_is_form_error_while_purge_lock_is_active(self):
        state = WorkflowDataModeState.objects.get(pk=1)
        state.active_spin_purge_id = uuid.uuid4()
        state.save(update_fields=['active_spin_purge_id', 'updated_at'])
        self.client.force_login(self.superuser)

        response = self.client.post(
            reverse('admin:core_workflowdatamodestate_change', args=[state.pk]),
            {'spin_mode': 'production', 'tat_mode': 'pilot', 'reason': 'Unsafe race attempt.'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Finish the active pilot purge')
        state.refresh_from_db()
        self.assertEqual(state.spin_mode, 'pilot')

    def test_admin_switches_only_selected_workflow_and_records_reason(self):
        state = WorkflowDataModeState.objects.get(pk=1)
        self.client.force_login(self.superuser)

        response = self.client.post(
            reverse('admin:core_workflowdatamodestate_change', args=[state.pk]),
            {
                'spin_mode': 'production',
                'tat_mode': 'pilot',
                'reason': 'Controlled SPIN production release.',
                '_save': 'Save',
            },
        )

        self.assertEqual(response.status_code, 302)
        state.refresh_from_db()
        self.assertEqual(state.spin_mode, 'production')
        self.assertEqual(state.tat_mode, 'pilot')
        event = WorkflowDataModeEvent.objects.get(workflow='spin', action='mode_changed')
        self.assertEqual(event.reason, 'Controlled SPIN production release.')
