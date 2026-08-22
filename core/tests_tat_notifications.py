import hashlib
import hmac
import json
import time
from datetime import timedelta
from urllib.parse import urlencode
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import (
    AccessGrant,
    GroupSheetConfiguration,
    TatActionTask,
    TatActionTaskRecipient,
    TatEscalationRule,
    TatGroupExceptionStatus,
    TatPrivateAlertConnection,
    TatResponsibilityAssignment,
    TatResponsibilityBackup,
    TatTrackerCase,
    UserProfile,
)
from core.services.tat_notifications import (
    connect_private_alerts,
    dispatch_task,
    inbox_payload,
    issue_locator,
    refresh_group_exception,
    resolve_locator,
    synchronize_case_task,
)
from core.services.group_config import GroupRegistry


@override_settings(
    TELEGRAM_BOT_TOKEN='test-token', TELEGRAM_BOT_USERNAME='testbot',
    TAT_TRACKER_MINI_APP_SHORT_NAME='tattracker',
)
class TatPrivateTaskTests(TestCase):
    def setUp(self):
        self.group = GroupSheetConfiguration.objects.create(
            group_id='-100-private-tat', display_name='Private TAT',
            sheet_id='sheet-test', sheet_name='TRACKER-Business',
            workflow={
                'type': 'tat_tracker', 'tat_notification_mode': 'hybrid',
                'branches': ['Nakuru'], 'products': ['business'],
                'tat_targets_minutes': {
                    'business': {'total': 1000, 'stages': {'mpesa_to_admin': 100}},
                },
            },
        )
        self.primary = self._user('primary', '101')
        self.backup = self._user('backup', '102')
        self._grant(self.primary, 'BRO')
        self._grant(self.backup, 'BRO')
        TatEscalationRule.objects.create(
            group_configuration=self.group, branch='Nakuru', threshold_percent=100,
            routing_role=TatEscalationRule.ROUTE_RESPONSIBLE,
        )
        self.assignment = TatResponsibilityAssignment.objects.create(
            group_configuration=self.group, branch='Nakuru', role='BRO',
            primary_user=self.primary,
        )
        TatResponsibilityBackup.objects.create(
            assignment=self.assignment, user=self.backup, rank=1, threshold_percent=100,
        )
        self.case = self._case('JBL-BS-2026-PRIVATE-1')

    def _user(self, username, telegram_id):
        user = get_user_model().objects.create_user(username=username, password='test-password')
        UserProfile.objects.create(user=user, telegram_id=telegram_id)
        return user

    def _grant(self, user, role, *, branch='', product=''):
        return AccessGrant.objects.create(
            user=user, workflow='tat_tracker', role=role, branch=branch,
            product=product, group_configuration=self.group,
        )

    def _case(self, case_id, *, branch='Nakuru'):
        started = timezone.now()
        return TatTrackerCase.objects.create(
            group_id=self.group.group_id, case_id=case_id, product_key='business',
            product_label='Business', client_name='SYNTHETIC APPLICANT',
            national_id='12345678', primary_phone='254700000001', branch=branch,
            bro_name='Synthetic BRO', amount='25000', status='Active',
            current_stage='mpesa_to_admin', stage_values={'created': started.isoformat()},
            stage_target_snapshots={'mpesa_to_admin': {
                'target_minutes': '100', 'started_at': started.isoformat(),
            }},
        )

    def _signed_init_data(self, telegram_id='101', username='primary'):
        pairs = {
            'auth_date': str(int(time.time())),
            'user': json.dumps({'id': int(telegram_id), 'username': username}),
        }
        check = '\n'.join(f'{key}={value}' for key, value in sorted(pairs.items()))
        secret = hmac.new(b'WebAppData', b'test-token', hashlib.sha256).digest()
        pairs['hash'] = hmac.new(secret, check.encode('utf-8'), hashlib.sha256).hexdigest()
        return urlencode(pairs)

    def test_assignment_routes_primary_and_ranked_backup_without_granting_access(self):
        task = synchronize_case_task(self.group, self.case)

        self.assertEqual(task.assignment, self.assignment)
        recipients = list(task.recipients.order_by('rank'))
        self.assertEqual([(row.user, row.kind) for row in recipients], [
            (self.primary, TatActionTaskRecipient.KIND_PRIMARY),
            (self.backup, TatActionTaskRecipient.KIND_BACKUP),
        ])
        self.assertLessEqual(recipients[0].deliver_after, timezone.now())
        self.assertGreater(recipients[1].deliver_after, timezone.now())

    @patch('core.services.tat_notifications._telegram_request', return_value={'message_id': 77})
    def test_known_unconnected_primary_immediately_soft_escalates_to_backup(self, telegram):
        TatPrivateAlertConnection.objects.create(
            user=self.primary, status=TatPrivateAlertConnection.STATUS_UNCONNECTED,
        )
        TatPrivateAlertConnection.objects.create(
            user=self.backup, status=TatPrivateAlertConnection.STATUS_CONNECTED,
        )
        task = synchronize_case_task(self.group, self.case)

        dispatch_task(task.pk)

        primary = task.recipients.get(user=self.primary)
        backup = task.recipients.get(user=self.backup)
        self.assertEqual(primary.delivery_state, TatActionTaskRecipient.DELIVERY_UNREACHABLE)
        self.assertEqual(backup.delivery_state, TatActionTaskRecipient.DELIVERY_DELIVERED)
        self.assertEqual(telegram.call_count, 1)

    @patch('core.services.tat_notifications._telegram_request', return_value={'message_id': 78})
    def test_concurrent_safe_dispatch_does_not_repeat_a_delivered_prompt(self, telegram):
        TatPrivateAlertConnection.objects.create(
            user=self.primary, status=TatPrivateAlertConnection.STATUS_CONNECTED,
        )
        task = synchronize_case_task(self.group, self.case)

        dispatch_task(task.pk)
        dispatch_task(task.pk)

        self.assertEqual(telegram.call_count, 1)
        self.assertEqual(
            task.recipients.get(user=self.primary).delivery_state,
            TatActionTaskRecipient.DELIVERY_DELIVERED,
        )

    @patch('core.services.tat_notifications._telegram_request', return_value={'message_id': 79})
    def test_connect_private_alerts_replays_same_request_without_second_message(self, telegram):
        first = connect_private_alerts(self.primary, request_id='connect-request-0001')
        second = connect_private_alerts(self.primary, request_id='connect-request-0001')

        self.assertTrue(first['connected'])
        self.assertTrue(second['connected'])
        self.assertEqual(telegram.call_count, 1)

    def test_same_case_stage_revision_is_idempotent(self):
        first = synchronize_case_task(self.group, self.case)
        second = synchronize_case_task(self.group, self.case)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(TatActionTask.objects.count(), 1)

    def test_revision_change_supersedes_old_task_and_revokes_old_locator(self):
        old = synchronize_case_task(self.group, self.case)
        token = issue_locator(old, self.primary)
        self.case.workflow_revision += 1
        self.case.save(update_fields=['workflow_revision', 'updated_at'])

        current = synchronize_case_task(self.group, self.case)

        old.refresh_from_db()
        locator = resolve_locator(token)
        self.assertEqual(old.status, TatActionTask.STATUS_SUPERSEDED)
        self.assertEqual(old.superseded_by, current)
        self.assertIsNotNone(locator.revoked_at)

    def test_stale_locator_redirects_authorized_recipient_to_current_revision(self):
        old = synchronize_case_task(self.group, self.case)
        token = issue_locator(old, self.primary)
        self.case.workflow_revision += 1
        self.case.save(update_fields=['workflow_revision', 'updated_at'])
        current = synchronize_case_task(self.group, self.case)
        GroupRegistry._instance = None

        response = self.client.post(
            reverse('tat_tracker_task_resolve'),
            data=json.dumps({
                'task_token': f'tt_{token}',
                'init_data': self._signed_init_data(),
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['link_status'], 'expired')
        self.assertEqual(response.json()['data']['task_id'], str(current.pk))

    def test_shadow_mode_records_routing_without_calling_telegram(self):
        workflow = dict(self.group.workflow)
        workflow['tat_notification_mode'] = 'shadow'
        self.group.workflow = workflow
        self.group.save(update_fields=['workflow', 'updated_at'])
        task = synchronize_case_task(self.group, self.case)

        with patch('core.services.tat_notifications._telegram_request') as telegram:
            dispatch_task(task.pk)

        self.assertFalse(telegram.called)
        self.assertEqual(
            task.recipients.get(user=self.primary).delivery_state,
            TatActionTaskRecipient.DELIVERY_SHADOW,
        )

    def test_locator_is_32_chars_hash_only_and_expires_in_72_hours(self):
        task = synchronize_case_task(self.group, self.case)
        token = issue_locator(task, self.primary)
        locator = resolve_locator(token)

        self.assertEqual(len(token), 32)
        self.assertNotEqual(locator.token_hash, token)
        self.assertGreater(locator.expires_at, timezone.now() + timedelta(hours=71))
        self.assertNotIn(token, repr(locator.__dict__))

    def test_inbox_is_personal_and_reports_unread_count(self):
        task = synchronize_case_task(self.group, self.case)

        primary = inbox_payload(self.primary, group=self.group)
        backup = inbox_payload(self.backup, group=self.group)

        self.assertEqual(primary['unread_count'], 1)
        self.assertEqual(backup['unread_count'], 1)
        self.assertEqual(primary['items'][0]['task_id'], str(task.pk))

    @patch('core.services.tat_notifications._telegram_request', return_value={'message_id': 80})
    def test_revoked_primary_scope_hides_task_and_soft_escalates_delivery(self, telegram):
        task = synchronize_case_task(self.group, self.case)
        AccessGrant.objects.filter(user=self.primary, workflow='tat_tracker').update(active=False)
        TatPrivateAlertConnection.objects.create(
            user=self.primary, status=TatPrivateAlertConnection.STATUS_CONNECTED,
        )
        TatPrivateAlertConnection.objects.create(
            user=self.backup, status=TatPrivateAlertConnection.STATUS_CONNECTED,
        )

        self.assertEqual(inbox_payload(self.primary, group=self.group)['total'], 0)
        dispatch_task(task.pk)

        self.assertEqual(
            task.recipients.get(user=self.primary).delivery_state,
            TatActionTaskRecipient.DELIVERY_UNREACHABLE,
        )
        self.assertEqual(
            task.recipients.get(user=self.backup).delivery_state,
            TatActionTaskRecipient.DELIVERY_DELIVERED,
        )
        self.assertEqual(telegram.call_count, 1)

    def test_direct_locator_endpoint_authenticates_and_opens_exact_task(self):
        task = synchronize_case_task(self.group, self.case)
        token = issue_locator(task, self.primary)
        GroupRegistry._instance = None

        response = self.client.post(
            reverse('tat_tracker_task_resolve'),
            data=json.dumps({
                'task_token': f'tt_{token}',
                'init_data': self._signed_init_data(),
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['case_id'], self.case.case_id)
        self.assertEqual(response.json()['data']['stage_key'], 'mpesa_to_admin')
        task.recipients.get(user=self.primary).refresh_from_db()
        self.assertEqual(
            task.recipients.get(user=self.primary).inbox_status,
            TatActionTaskRecipient.INBOX_READ,
        )

    def test_direct_locator_rejects_user_outside_recipient_and_scope(self):
        task = synchronize_case_task(self.group, self.case)
        token = issue_locator(task, self.primary)
        outsider = self._user('outsider', '999')
        self._grant(outsider, 'CA')
        GroupRegistry._instance = None

        response = self.client.post(
            reverse('tat_tracker_task_resolve'),
            data=json.dumps({
                'task_token': f'tt_{token}',
                'init_data': self._signed_init_data('999', 'outsider'),
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 403)

    @patch('core.services.tat_notifications._telegram_request')
    def test_unrelated_unreachable_cases_update_one_cumulative_group_count(self, telegram):
        telegram.side_effect = [
            {'message_id': 501},
            {},
        ]
        isolated_group = GroupSheetConfiguration.objects.create(
            group_id='-100-unassigned-tat', display_name='Unassigned TAT',
            sheet_id='sheet-unassigned', sheet_name='TRACKER-Business',
            workflow={'type': 'tat_tracker', 'tat_notification_mode': 'hybrid'},
        )
        first = self._case('JBL-BS-2026-UNASSIGNED-1', branch='Mombasa')
        second = self._case('JBL-BS-2026-UNASSIGNED-2', branch='Mombasa')
        first.group_id = isolated_group.group_id
        second.group_id = isolated_group.group_id
        first.save(update_fields=['group_id'])
        second.save(update_fields=['group_id'])
        first_task = synchronize_case_task(isolated_group, first)
        second_task = synchronize_case_task(isolated_group, second)
        self.assertTrue(first_task.recipient_snapshot['delivery_exception'])
        self.assertTrue(second_task.recipient_snapshot['delivery_exception'])

        refresh_group_exception(isolated_group.pk, role='BRO')
        refresh_group_exception(isolated_group.pk, role='BRO')

        status = TatGroupExceptionStatus.objects.get(
            group_configuration=isolated_group, responsible_role='BRO',
        )
        self.assertEqual(status.unresolved_count, 2)
        self.assertEqual(status.telegram_message_id, '501')
        self.assertEqual(telegram.call_args_list[0].args[0], 'sendMessage')
        self.assertEqual(telegram.call_args_list[1].args[0], 'editMessageText')
