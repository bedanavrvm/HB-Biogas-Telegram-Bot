"""Synthetic TAT remarks, framing and native-download regressions."""
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import SimpleTestCase, TestCase, TransactionTestCase, RequestFactory
from django.urls import resolve
from django.utils import timezone

from core.models import AccessGrant, GroupSheetConfiguration, TatTrackerCase, IntegrationOperation


class MiniAppFrameTests(SimpleTestCase):
    def test_other_csp_directives_survive_and_json_is_never_exempt(self):
        from core.miniapp_security import MiniAppFramePolicyMiddleware
        request = RequestFactory().get('/tat-tracker/', HTTP_ORIGIN='https://untrusted.example')
        request.resolver_match = resolve('/tat-tracker/')
        response = HttpResponse('page', headers={'Content-Security-Policy': "default-src 'self'; frame-ancestors 'none'", 'X-Frame-Options': 'DENY'})
        result = MiniAppFramePolicyMiddleware(lambda request: response)(request)
        self.assertEqual(result['Content-Security-Policy'], "default-src 'self'; frame-ancestors 'self' https://web.telegram.org")
        self.assertNotIn('untrusted.example', result['Content-Security-Policy'])
        result = MiniAppFramePolicyMiddleware(lambda request: HttpResponse('{}', content_type='application/json'))(request)
        self.assertFalse(getattr(result, 'xframe_options_exempt', False))
        result = MiniAppFramePolicyMiddleware(lambda request: HttpResponse('Link expired', status=400))(request)
        self.assertTrue(result.xframe_options_exempt)

    def test_only_reviewed_html_controllers_allow_telegram_frames(self):
        from core.miniapp_security import MiniAppFramePolicyMiddleware
        middleware = MiniAppFramePolicyMiddleware(lambda request: HttpResponse('page'))
        for path in ('/tat-tracker/', '/complaints/', '/portal/', '/portal/s/settings/', '/origination/', '/s/'):
            with self.subTest(path=path):
                request = RequestFactory().get(path)
                request.resolver_match = resolve(path)
                response = middleware(request)
                self.assertTrue(response.xframe_options_exempt)
                self.assertEqual(response['Content-Security-Policy'], "frame-ancestors 'self' https://web.telegram.org")
        for path in ('/admin/login/', '/api/tat-tracker/detail/', '/health/'):
            request = RequestFactory().get(path)
            request.resolver_match = resolve(path)
            response = middleware(request)
            self.assertFalse(getattr(response, 'xframe_options_exempt', False))
            self.assertNotIn('Content-Security-Policy', response)

    def test_live_middleware_order_allows_tat_but_not_admin(self):
        response = self.client.get('/tat-tracker/')
        self.assertNotIn('X-Frame-Options', response)
        self.assertIn('https://web.telegram.org', response['Content-Security-Policy'])
        self.assertEqual(self.client.get('/admin/login/')['X-Frame-Options'], 'DENY')


class TatRemarkTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser('remark-root', password='synthetic-only', first_name='Jane', last_name='Example')
        self.group = GroupSheetConfiguration.objects.create(
            group_id='-100-remarks-synthetic', sheet_id='synthetic', sheet_name='TAT Register', tat_sheet_projection_enabled=True,
            workflow={'type': 'tat_tracker', 'products': ['business'], 'branches': ['Nakuru']},
        )
        self.user = {'_canonical_user': self.actor}
        self.case = TatTrackerCase.objects.create(
            group_id=self.group.group_id, case_id='SYNTHETIC-REMARK-1', product_key='business',
            branch='Nakuru', remarks='Earlier note', status='Disbursed',
            configuration_binding_status=TatTrackerCase.CONFIG_LEGACY_ASSUMED,
            stage_values={'created': timezone.now().isoformat()}, current_stage='', last_updated_by='Original actor',
        )

    def save(self, text='Please follow up.', key='remark-request-1', user=None):
        from core.services.tat_comments import add_remark
        return add_remark(self.group, user or self.user, self.case.case_id, text, request_id=key)

    def test_append_retains_legacy_and_never_moves_terminal_clock_or_revision(self):
        before = (self.case.updated_at, self.case.workflow_revision, self.case.stage_values, self.case.last_updated_by)
        with patch('core.services.tat_tracker.get_sheets_service') as provider:
            event, operation = self.save()
            provider.assert_not_called()
        self.case.refresh_from_db()
        self.assertEqual((self.case.updated_at, self.case.workflow_revision, self.case.stage_values, self.case.last_updated_by), before)
        self.assertEqual(self.case.status, 'Disbursed')
        self.assertIn('Earlier note\n────────────────────\nPlease follow up.', self.case.remarks)
        self.assertIn('Jane Example', self.case.remarks)
        self.assertEqual(event.actor_user, self.actor)
        self.assertEqual(event.old_value, 'Earlier note')
        self.assertEqual(operation.status, IntegrationOperation.STATUS_PENDING)
        from core.models import TatActionTask
        self.assertFalse(TatActionTask.objects.filter(case=self.case).exists())

    def test_replay_is_idempotent_and_different_text_conflicts(self):
        first, operation = self.save()
        second, replay = self.save()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(operation.pk, replay.pk)
        self.case.refresh_from_db()
        self.assertEqual(self.case.remarks.count('Please follow up.'), 1)
        from core.services.tat_comments import RemarkConflict
        with self.assertRaises(RemarkConflict):
            self.save('Changed text')

    def test_invalid_notes_and_missing_request_keys_are_rejected(self):
        for value, key in (('', 'a'), ('   ', 'b'), ('x' * 5001, 'c'), ([], 'd'), ('valid', ''), ('valid', 'x' * 129)):
            with self.subTest(value=str(value)[:10], key=key[:10]):
                with self.assertRaises(ValueError):
                    self.save(value, key)
        self.assertFalse(self.case.events.exists())

    def test_anonymous_unresolved_and_deleted_cases_are_not_writable(self):
        from django.core.exceptions import PermissionDenied
        with self.assertRaises(PermissionDenied):
            self.save(user={'roles': ['IT']})
        self.case.configuration_binding_status = TatTrackerCase.CONFIG_UNRESOLVED
        self.case.save(update_fields=['configuration_binding_status'])
        with self.assertRaises(ValueError):
            self.save()
        self.case.is_deleted = True
        self.case.save(update_fields=['is_deleted'])
        with self.assertRaises(TatTrackerCase.DoesNotExist):
            self.save()

    def test_named_sheet_projection_changes_only_remarks_and_retries_current_text(self):
        from core.test_named_sheet import NamedSheet, service_for
        from core.services.tat_comments import publish_remark
        first, _ = self.save()
        self.save('Second person can comment too.', 'remark-request-2')
        sheet = NamedSheet(['Other', 'Remarks / Delays', 'Case ID'], [['keep', '', self.case.case_id]])
        original_updated = self.case.updated_at
        with patch('core.services.tat_tracker.get_sheets_service', return_value=service_for(sheet)):
            publish_remark(first.pk)
            publish_remark(first.pk)
        self.case.refresh_from_db()
        self.assertEqual(sheet.rows[1], ['keep', self.case.remarks, self.case.case_id])
        self.assertEqual(self.case.updated_at, original_updated)
        self.assertIn('Second person', sheet.rows[1][1])

    def test_first_case_publication_keeps_formula_like_remarks_literal(self):
        from core.test_named_sheet import NamedSheet, service_for, tat_headers
        from core.services.tat_tracker import product_for_case, sync_case_to_sheet
        from core.services.sheet_columns import NamedColumns
        self.save('=This is a literal staff note, not a formula')
        sheet = NamedSheet(tat_headers(product_for_case(self.case), include_global=True))
        with patch('core.services.tat_tracker.get_sheets_service', return_value=service_for(sheet)), \
             patch('core.services.tat_tracker.cached_tat_sheet_headers', return_value=sheet.headers), \
             patch('core.services.tat_tracker.format_tat_sheet_case_row'), \
             patch('core.services.tat_tracker.should_sync_secondary_sheets', return_value=False):
            sync_case_to_sheet(self.group, self.case)
        columns = NamedColumns(sheet.headers)
        self.assertEqual(columns.value(sheet.appended_rows[0][0][0], 'Remarks / Delays'), '')
        self.assertIn('=This is a literal', sheet.value(2, 'Remarks / Delays'))
        self.assertTrue(any(item[2] == 'RAW' for item in sheet.updates))

    def test_timeline_comments_are_not_value_change_rows(self):
        from core.services.workflow_timeline import tat_case_timeline
        self.save()
        row = tat_case_timeline(self.case)['entries'][0]
        self.assertEqual(row['value_kind'], 'comment')
        self.assertEqual(row['detail'], 'Please follow up.')
        self.assertEqual(row['changes'], [])

    def test_current_case_scopes_and_roles_are_used_not_client_labels_or_cached_grants(self):
        officer = get_user_model().objects.create_user('scoped-officer', first_name='Real', last_name='Actor')
        grant = AccessGrant.objects.create(user=officer, workflow='tat_tracker', role='BRO', branch='Nakuru', product='business', group_configuration=self.group)
        user = {'_canonical_user': officer, 'name': 'Fake label', 'roles': ['BM'], 'telegram_id': 'synthetic'}
        event, _ = self.save(user=user)
        self.assertEqual(event.actor_name, 'Real Actor')
        self.assertEqual(event.actor_role, 'BRO')
        from django.core.exceptions import PermissionDenied
        grant.active = False
        grant.save(update_fields=['active'])
        with self.assertRaises(PermissionDenied):
            self.save('Cannot use revoked access', 'request-revoked', user=user)
        grant.active = True
        grant.branch = 'Other branch'
        grant.save(update_fields=['active', 'branch'])
        with self.assertRaises(PermissionDenied):
            self.save('Cannot cross branch scope', 'request-wrong-branch', user=user)

    def test_same_request_key_from_another_actor_is_not_a_replay(self):
        from core.services.tat_comments import RemarkConflict
        self.save()
        another = get_user_model().objects.create_superuser('second-root', password='synthetic')
        with self.assertRaises(RemarkConflict):
            self.save(user={'_canonical_user': another})

    def test_sheet_failure_is_durable_without_losing_saved_remark(self):
        from core.services.tat_comments import process_remark_publications
        from core.test_named_sheet import NamedSheet, service_for
        event, operation = self.save()
        before = self.case.updated_at
        with patch('core.services.tat_comments.publish_remark', side_effect=RuntimeError('connection error synthetic')):
            self.assertEqual(process_remark_publications(), 1)
        operation.refresh_from_db()
        self.assertEqual(operation.status, IntegrationOperation.STATUS_RETRYABLE)
        self.case.refresh_from_db()
        self.assertEqual(self.case.updated_at, before)
        self.assertIn('Please follow up.', self.case.remarks)
        IntegrationOperation.objects.filter(pk=operation.pk).update(next_retry_at=timezone.now())
        sheet = NamedSheet(['Case ID', 'Remarks / Delays'], [[self.case.case_id, '']])
        with patch('core.services.tat_tracker.get_sheets_service', return_value=service_for(sheet)):
            self.assertEqual(process_remark_publications(), 1)
        operation.refresh_from_db()
        event.refresh_from_db()
        self.assertEqual(operation.status, IntegrationOperation.STATUS_SUCCEEDED)
        self.assertTrue(event.synced_to_sheet)

    def test_reviewed_failed_projection_can_be_requeued_without_resubmitting_notes(self):
        from core.services.tat_comments import retry_remark_publication
        _, operation = self.save()
        IntegrationOperation.objects.filter(pk=operation.pk).update(status=IntegrationOperation.STATUS_DEAD_LETTER, attempts=5)
        with patch('core.services.tat_tracker.get_sheets_service') as provider:
            self.assertTrue(retry_remark_publication(operation.pk, actor=self.actor))
            self.assertFalse(retry_remark_publication(operation.pk, actor=self.actor))
            provider.assert_not_called()
        operation.refresh_from_db()
        self.assertEqual(operation.status, IntegrationOperation.STATUS_PENDING)
        self.assertEqual(operation.attempts, 0)
        self.assertEqual(self.case.events.count(), 1)
        from django.core.exceptions import PermissionDenied
        officer = get_user_model().objects.create_user('retry-officer')
        with self.assertRaises(PermissionDenied):
            retry_remark_publication(operation.pk, actor=officer)

    def test_unsafe_sheet_headers_and_duplicate_rows_never_write(self):
        from core.services.tat_comments import publish_remark
        from core.test_named_sheet import NamedSheet, service_for
        event, _ = self.save()
        for sheet in (NamedSheet(['Case ID', 'Other']),
                      NamedSheet(['Case ID', 'Remarks / Delays', 'remarks / delays']),
                      NamedSheet(['Case ID', 'Remarks / Delays'], [[self.case.case_id], [self.case.case_id]])):
            with self.subTest(headers=sheet.headers):
                with patch('core.services.tat_tracker.get_sheets_service', return_value=service_for(sheet)):
                    with self.assertRaises(ValueError):
                        publish_remark(event.pk)
                self.assertFalse(sheet.updates)

    def test_explicit_legacy_remarks_alias_is_supported_without_positional_fallback(self):
        from core.services.tat_comments import publish_remark
        from core.test_named_sheet import NamedSheet, service_for
        event, _ = self.save()
        sheet = NamedSheet(['Case ID', 'Other', 'Remarks'], [[self.case.case_id, 'keep', '']])
        with patch('core.services.tat_tracker.get_sheets_service', return_value=service_for(sheet)):
            publish_remark(event.pk)
        self.assertIn('Please follow up.', sheet.rows[1][2])
        self.assertEqual(sheet.rows[1][1], 'keep')

    def test_first_remark_preserves_legacy_notes_without_duplicating_their_activity(self):
        from core.services.workflow_timeline import tat_case_timeline
        self.case.events.create(group_id=self.case.group_id, stage_key='remarks', stage_label='Remarks / Delays', new_value=self.case.remarks)
        self.save()
        rows = tat_case_timeline(self.case)['entries']
        self.assertFalse(any(row['stage'] == 'Earlier remarks' for row in rows))

    def test_redacted_remark_never_reappears_in_unattributed_history(self):
        from core.services.workflow_timeline import tat_case_timeline
        event, _ = self.save()
        with patch('core.services.workflow_timeline._annotations', return_value=({f'tat:{event.pk}': SimpleNamespace(note='Restricted')}, [])):
            rows = tat_case_timeline(self.case)['entries']
        self.assertFalse(any('Please follow up.' in row['detail'] or row['stage'] == 'Earlier remarks' for row in rows))

    def test_stale_stage_publisher_uses_latest_notes_and_preserves_failure_evidence(self):
        from core.services.tat_tracker import _sync_case_to_sheet_with_lock, sync_case_to_sheet
        self.save()
        with patch('core.services.tat_tracker.get_sheets_service', side_effect=RuntimeError('synthetic unavailable')):
            with self.assertRaises(RuntimeError):
                _sync_case_to_sheet_with_lock(self.group, self.case)
        self.assertIn('Please follow up.', self.case.remarks)
        with patch('core.services.tat_tracker._sync_case_to_sheet_with_lock', side_effect=RuntimeError('synthetic unavailable')):
            with self.assertRaises(RuntimeError):
                sync_case_to_sheet(self.group, self.case)
        self.case.refresh_from_db()
        self.assertEqual(self.case.sync_error, 'synthetic unavailable')

    def test_disabled_projection_saves_without_reserving_provider_work(self):
        self.group.tat_sheet_projection_enabled = False
        self.group.save(update_fields=['tat_sheet_projection_enabled'])
        event, operation = self.save()
        self.assertIsNone(operation)
        self.assertEqual(event.new_value, 'Please follow up.')

    def test_batch_retry_routes_commented_cases_through_locked_literal_publication(self):
        from core.services.tat_tracker import sync_tat_batch_created_cases
        from core.test_named_sheet import NamedSheet, service_for, tat_headers
        self.save('=A literal staff note', 'batch-literal-note')
        from core.services.tat_tracker import product_for_case
        sheet = NamedSheet(tat_headers(product_for_case(self.case), include_global=True))
        with patch('core.services.tat_tracker.get_sheets_service', return_value=service_for(sheet)), \
                patch('core.services.tat_tracker.cached_tat_sheet_headers', return_value=sheet.row_values(1)), \
                patch('core.services.tat_tracker.sync_case_to_sheet', return_value=True) as locked_publish, \
                patch('core.services.tat_tracker.append_tat_batch_rows') as bulk_append:
            result = sync_tat_batch_created_cases(self.group, [self.case])
        locked_publish.assert_called_once_with(self.group, self.case)
        bulk_append.assert_not_called()
        self.assertEqual(result['synced'], 1)

    def test_missing_saved_sheet_configuration_does_not_block_canonical_note(self):
        legacy_group = SimpleNamespace(group_id=self.group.group_id, workflow=self.group.workflow, tat_sheet_projection_enabled=True)
        from core.services.tat_comments import add_remark
        with patch('core.services.telegram_identity.database_group_configuration', return_value=None):
            event, operation = add_remark(legacy_group, self.user, self.case.case_id, 'Keep this note.', request_id='legacy-config-note')
        self.assertEqual(event.new_value, 'Keep this note.')
        self.assertEqual(operation.status, IntegrationOperation.STATUS_PENDING)
        self.assertIsNone(operation.metadata['group_configuration_id'])

    def test_closed_pilot_case_is_read_only_even_with_superuser(self):
        from core.services.workflow_data_mode import WorkflowModeChanged
        self.case.data_mode = 'pilot'
        self.case.save(update_fields=['data_mode'])
        with patch('core.services.workflow_data_mode.mode_snapshot', return_value=SimpleNamespace(mode='production', pilot_cycle_id=None, mode_version=1)):
            with self.assertRaises(WorkflowModeChanged):
                self.save()

    def test_timeline_ordinary_timestamps_and_outcomes_have_distinct_display_types(self):
        from core.services.workflow_timeline import tat_case_timeline
        self.case.events.create(group_id=self.case.group_id, stage_key='mpesa_to_admin', stage_label='M-PESA sent',
                                new_value='14-10-2026 09:30', actor_name='Synthetic BRO')
        self.case.events.create(group_id=self.case.group_id, stage_key='bro_applied', stage_label='Loan applied', new_value='Met')
        entries = tat_case_timeline(self.case)['entries']
        timestamp = next(row for row in entries if row['stage'] == 'M-PESA sent')
        outcome = next(row for row in entries if row['stage'] == 'Loan applied')
        self.assertEqual(timestamp['value_kind'], 'timestamp')
        self.assertEqual(timestamp['changes'], [])
        self.assertEqual(outcome['outcome'], 'Met')

    def test_old_replace_remarks_path_is_rejected(self):
        from core.services.tat_tracker import apply_update, TatUpdateValidationError
        with self.assertRaises(TatUpdateValidationError):
            apply_update(self.case, self.user, {'field': 'remarks', 'value': 'overwrite'})
        self.case.refresh_from_db()
        self.assertEqual(self.case.remarks, 'Earlier note')

    def test_comment_api_returns_saved_detail_and_keeps_legacy_endpoint_separate(self):
        import json
        context = (self.group.group_id, self.group, {}, self.user, None)
        body = {'case_id': self.case.case_id, 'comment_text': 'API follow-up', 'client_request_id': 'api-remark-request'}
        with patch('core.api.views._tat_context', return_value=context):
            response = self.client.post('/api/tat-tracker/comments/', data=json.dumps(body), content_type='application/json')
            replay = self.client.post('/api/tat-tracker/comments/', data=json.dumps(body), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(response.json()['data']['can_comment'])
        self.assertTrue(response.json()['sheet_projection']['pending'])
        self.assertEqual(self.case.events.filter(transition_code='comment.add').count(), 1)

    def test_missing_telegram_authentication_never_creates_a_comment(self):
        import json
        response = self.client.post('/api/tat-tracker/comments/', data=json.dumps({'case_id': self.case.case_id, 'comment_text': 'Unauthorized', 'client_request_id': 'unauthorized-key'}), content_type='application/json')
        self.assertGreaterEqual(response.status_code, 400)
        self.assertLess(response.status_code, 500)
        self.assertFalse(self.case.events.exists())

    def test_comment_api_rejects_uploads_and_invalid_json_shapes_without_server_error(self):
        self.assertEqual(self.client.post('/api/tat-tracker/comments/', data={'comment_text': 'wrong format'}).status_code, 415)
        self.assertEqual(self.client.post('/api/tat-tracker/comments/', data='[]', content_type='application/json').status_code, 400)
        self.assertFalse(self.case.events.exists())

    def test_download_get_head_expose_same_named_attachment_and_web_cors(self):
        from core.api.views import tat_tracker_reports_download
        payload = {'user_id': self.actor.pk, 'group_id': self.group.group_id, 'filters': {},
                   'request_id': 'report-request', 'filename': 'tat-report-14-10-26.xlsx'}
        with patch('core.services.tat_reporting.decode_report_download', return_value=payload), \
             patch('core.services.group_config.GroupRegistry.get_instance', return_value=SimpleNamespace(get_group=lambda key: self.group)), \
             patch('core.services.tat_reporting.export_report_xlsx', return_value=(b'workbook', 1)):
            responses = [tat_tracker_reports_download(RequestFactory().generic(method, '/download/'), 'synthetic') for method in ('GET', 'HEAD')]
        for response in responses:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Access-Control-Allow-Origin'], 'https://web.telegram.org')
            self.assertEqual(response['Content-Disposition'], 'attachment; filename="tat-report-14-10-26.xlsx"')
            self.assertEqual(response['Content-Length'], '8')
        self.assertEqual(responses[1].content, b'')


class TatRemarkConcurrencyTests(TransactionTestCase):
    def setUp(self):
        from django.db import connection
        if connection.vendor != 'postgresql':
            self.skipTest('Requires actual PostgreSQL row locking.')
        from core.models import ComplianceAuditChainState
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        self.actor = get_user_model().objects.create_superuser('concurrent-remark-root', password='synthetic-only')
        self.group = GroupSheetConfiguration.objects.create(group_id='-100-concurrent-remarks', workflow={'type': 'tat_tracker'})
        self.case = TatTrackerCase.objects.create(group_id=self.group.group_id, case_id='SYNTHETIC-CONCURRENT-1',
                                                product_key='business', status='Declined', configuration_binding_status=TatTrackerCase.CONFIG_LEGACY_ASSUMED)

    def _concurrent(self, notes):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections
        from core.services.tat_comments import add_remark
        barrier = Barrier(2)

        def save(note):
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.actor.pk)
                group = GroupSheetConfiguration.objects.get(pk=self.group.pk)
                barrier.wait(timeout=10)
                return str(add_remark(group, {'_canonical_user': actor}, self.case.case_id, note[0], request_id=note[1])[0].pk)
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(save, note) for note in notes]
            return [future.result(timeout=20) for future in futures]

    def test_concurrent_replay_creates_one_event_and_one_note(self):
        results = self._concurrent([('Same note', 'same-request'), ('Same note', 'same-request')])
        self.assertEqual(results[0], results[1])
        self.case.refresh_from_db()
        self.assertEqual(self.case.remarks.count('Same note'), 1)
        self.assertEqual(self.case.events.count(), 1)

    def test_concurrent_different_comments_both_survive_without_clock_change(self):
        before = self.case.updated_at
        results = self._concurrent([('First note', 'first-request'), ('Second note', 'second-request')])
        self.assertNotEqual(results[0], results[1])
        self.case.refresh_from_db()
        self.assertIn('First note', self.case.remarks)
        self.assertIn('Second note', self.case.remarks)
        self.assertEqual(self.case.updated_at, before)
        self.assertEqual(self.case.status, 'Declined')
