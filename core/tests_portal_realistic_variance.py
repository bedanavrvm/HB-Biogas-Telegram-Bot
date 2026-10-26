"""Synthetic Portal input, chronology and route probes; no external providers."""
from datetime import date, timedelta
import csv
from hashlib import sha256
import hmac
from io import StringIO
import json
from pathlib import Path
import time
from urllib.parse import urlencode
from unittest.mock import patch
from uuid import UUID

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client, TestCase, override_settings
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.utils import timezone

from core.models import AccessGrant, GroupSheetConfiguration, JawabuCustomer, JawabuFarmerMaster, UserProfile


@override_settings(SECURE_SSL_REDIRECT=False, RUNNING_TESTS=True,
                   TELEGRAM_BOT_TOKEN='0:synthetic-portal-variance')
class PortalRealisticVarianceTests(TestCase):
    evidence = []

    @classmethod
    def setUpTestData(cls):
        cls.group = GroupSheetConfiguration.objects.create(
            group_id='synthetic-portal-variance', enabled=True,
            workflow={'type': 'jawabu_homebiogas'})
        cls.clients = {}
        for i, role in enumerate(('IT', 'JBL_OFFICER', 'CREDIT_ANALYST', 'BUSINESS_ADMIN', 'OPERATIONS_ADMIN', 'HB_STAFF')):
            actor = get_user_model().objects.create_user(username=f'synthetic-variance-{role}')
            UserProfile.objects.update_or_create(user=actor, defaults={'telegram_id': str(988000000 + i)})
            AccessGrant.objects.create(user=actor, workflow='jawabu_portal', role=role, group_configuration=cls.group)
            fields = {'auth_date': str(int(time.time())), 'user': json.dumps({'id': 988000000 + i})}
            secret = hmac.new(b'WebAppData', settings.TELEGRAM_BOT_TOKEN.encode(), sha256).digest()
            fields['hash'] = hmac.new(secret, '\n'.join(f'{key}={value}' for key, value in sorted(fields.items())).encode(), sha256).hexdigest()
            cls.clients[role] = Client(HTTP_X_TELEGRAM_INIT_DATA=urlencode(fields), raise_request_exception=False)

    @classmethod
    def tearDownClass(cls):
        output = Path(settings.DATABASES['default']['NAME']).parent / 'variance-probes.json'
        output.write_text(json.dumps(cls.evidence, indent=2, default=str), encoding='utf-8')
        super().tearDownClass()

    def post(self, route, payload, *, role='JBL_OFFICER', args=(), multipart=False, method='POST'):
        payload = {**payload, 'client_request_id': f'variance-{len(self.evidence)}-{time.time_ns()}'}
        client = self.clients[role]
        response = (client.post(reverse(route, args=args), payload) if multipart else
                    client.generic(method, reverse(route, args=args), json.dumps(payload), content_type='application/json'))
        self.evidence.append({'route': route, 'role': role, 'status': response.status_code,
                              'payload': payload, 'response': response.content[:2000].decode(errors='replace')})
        return response

    def lead(self, **values):
        return {'customer_name': 'SYNTHETIC BRO APPLICANT', 'national_id': '99880001',
                'primary_phone': '254700880001', 'county': 'Kiambu', 'sub_county': 'Limuru',
                'village': 'Synthetic village', 'deposit_paid_hbg': '0', **values}

    def test_bro_identity_and_deposit_boundaries(self):
        cases = [
            ('customer_name', '', 400), ('customer_name', '   ', 400),
            ('customer_name', 'X' * 255, 201), ('customer_name', 'X' * 256, 400),
            ('national_id', '', 400), ('national_id', 'AB123', 400),
            ('national_id', '1234567890', 400), ('national_id', '1', 201),
            ('national_id', '000001', 201), ('national_id', '123456789', 201),
            ('primary_phone', '', 400), ('primary_phone', '0712', 400),
            ('primary_phone', '+255700880001', 400), ('primary_phone', '++254700880001', 400),
            *[('primary_phone', phone, 201) for phone in ('0700880001', '254700880001',
               '+254700880001', '00254700880001', '005700880001', '+254 (0) 700-880-001')],
            *[('deposit_paid_hbg', value, 201) for value in ('', '0', '0.00', '1', '4,999.99')],
            *[('deposit_paid_hbg', value, 400) for value in ('-1', 'NaN', 'Infinity', '1e4',
               '5000.001', '10000000000.00', 'paid 5000')],
            ('hb_sales_person', 'X' * 256, 400), ('village', 'X' * 256, 400),
        ]
        for field, value, expected in cases:
            with self.subTest(field=field, value=value), transaction.atomic():
                response = self.post('portal_create_and_complete_jbl_lead', self.lead(**{field: value}), multipart=True)
                self.assertEqual(response.status_code, expected, response.content[:500])
                if expected == 400:
                    self.assertFalse(JawabuFarmerMaster.objects.exists())
                    self.assertFalse(JawabuCustomer.objects.exists())
                else:
                    self.assertTrue(response.json()['deposit_hold'])
                    self.assertFalse(response.json()['visit_logged'])
                    self.assertEqual(JawabuFarmerMaster.objects.count(), 1)
                transaction.set_rollback(True)

    def test_bro_unknown_locations_follow_the_captured_policy(self):
        from core.models import LocationPolicyState
        for mode, expected in [('audit', 201), ('strict', 400)]:
            with self.subTest(mode=mode), transaction.atomic():
                LocationPolicyState.objects.update_or_create(pk=1, defaults={'mode': mode})
                response = self.post('portal_create_and_complete_jbl_lead', self.lead(
                    county='Unmapped county', sub_county='Unmapped constituency'), multipart=True)
                self.assertEqual(response.status_code, expected, response.content)
                transaction.set_rollback(True)

    def test_sysup_accepts_one_whole_file_above_the_internal_chunk_size(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from core.models import JawabuFarmerUploadBatch
        from core.tests_system_export import export_csv
        content = export_csv([{'Customer ID': str(980000 + i), 'Name': f'SYNTHETIC LARGE SOURCE {i}',
                              'ID NO': str(98000000 + i), 'Mobile No': f'2547{i:08}',
                              'Branch': 'Limuru', 'LGF Balance': '0'} for i in range(1201)])
        response = self.post('portal_import_stage', {'file': SimpleUploadedFile('synthetic-whole.csv', content)},
                             role='IT', args=('sysup',), multipart=True)
        self.assertEqual(response.status_code, 201, response.content[:500])
        batch = JawabuFarmerUploadBatch.objects.get()
        self.assertEqual(batch.total_rows, 1201)
        self.assertEqual(len(batch.parsed_rows), 1201)
        self.assertEqual(bytes(batch.source_content), content)
        self.assertEqual(response.json()['batch']['processing_chunk_size'], 400)
        self.assertFalse(JawabuFarmerMaster.objects.exists())

    def test_hb_staff_and_it_can_open_every_hb_actions_workstream(self):
        from core.services.portal_navigation import get_portal_nav_groups
        from core.services.telegram_identity import user_access
        for role in ('HB_STAFF', 'IT'):
            actor = get_user_model().objects.get(username=f'synthetic-variance-{role}')
            items = [item for group in get_portal_nav_groups(actor, access=user_access(actor, 'jawabu_portal')) for item in group['items']]
            self.assertIn('hb_actions', [item['key'] for item in items])
            for workstream in ('deposits', 'installation', 'commissioning'):
                response = self.clients[role].get(reverse('portal_hb_actions_screen'), {'workstream': workstream})
                self.assertEqual(response.status_code, 200, (role, workstream, response.content[:500]))
            for route in ('portal_hb_deposit_list', 'portal_hb_action_list'):
                response = self.clients[role].get(reverse(route))
                self.assertEqual(response.status_code, 200, (role, response.content[:500]))

    def farmup_source(self, rows):
        stream = StringIO()
        writer = csv.writer(stream)
        writer.writerow(['Full Name', 'ID NUMBER', 'HBG Hub', 'Mobile', 'Phone',
                         'Actual Receipts', 'Sign Date', 'Sales Person'])
        writer.writerows(rows)
        return stream.getvalue().encode('utf-8')

    def farmup_row(self, index):
        dates = ('29/02/2024', '31/12/2025', '01/01/2026', '30/04/2026', '30/09/2026')
        return [f'SYNTHETIC BULK O\'NEIL, {index}', str(99700000 + index), 'Kiambu',
                f'254700{index:06}', f'254711{index:06}',
                ('0', '4999.99', '5000.00', '5000.01')[index % 4],
                dates[index % len(dates)], 'Synthetic HB']

    def stage_farmup_source(self, content, *, batch_id=None):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from core.models import JawabuFarmerUploadBatch
        response = self.post('portal_farmup_version' if batch_id else 'portal_farmup_stage',
                             {'file': SimpleUploadedFile('synthetic-bulk.csv', content), 'period': '2026-10'},
                             role='OPERATIONS_ADMIN', args=(batch_id,) if batch_id else (), multipart=True)
        self.assertEqual(response.status_code, 201, response.content[:500])
        return JawabuFarmerUploadBatch.objects.get(pk=response.json()['batch']['id'])

    def test_bulk_farmup_invalid_selection_is_atomic_and_partial_retry_preserves_held_rows(self):
        from core.services.portal_imports import farmup_revision_token
        source_rows = [self.farmup_row(index) for index in range(400)]
        source_rows.extend([list(row) for row in source_rows[:40]])
        for index in range(440, 560):
            row = self.farmup_row(index)
            row[3 if index < 480 else 1 if index < 520 else 5] = (
                '123' if index < 480 else '' if index < 520 else '-1')
            source_rows.append(row)
        content = self.farmup_source(source_rows)
        batch = self.stage_farmup_source(content)
        self.assertEqual(batch.total_rows, 560)
        token = farmup_revision_token(batch)
        rows = [{'row_id': row['row_id'], 'approved': True, 'warning_acknowledged': True}
                for row in batch.parsed_rows]
        payload = {'rows': rows, 'revision_token': token}
        validation = self.post('portal_farmup_validate', payload, role='OPERATIONS_ADMIN', args=(batch.pk,))
        self.assertEqual(validation.status_code, 200, validation.content[:500])
        self.assertEqual(validation.json()['counts']['selected'], 400)
        self.assertEqual(validation.json()['counts']['unresolved'], 160)
        invalid = self.post('portal_farmup_commit', payload, role='OPERATIONS_ADMIN', args=(batch.pk,))
        self.assertEqual(invalid.status_code, 400, invalid.content[:500])
        self.assertFalse(JawabuCustomer.objects.exists())
        self.assertFalse(JawabuFarmerMaster.objects.exists())
        batch.refresh_from_db()
        self.assertEqual(batch.portal_revision, 1)
        for index, row in enumerate(rows):
            row['approved'] = index < 400
        payload['client_request_id'] = 'synthetic-bulk-partial-exact-replay'
        client = self.clients['OPERATIONS_ADMIN']
        url = reverse('portal_farmup_commit', args=(batch.pk,))
        first = client.post(url, json.dumps(payload), content_type='application/json')
        self.assertEqual(first.status_code, 200, first.content[:500])
        self.assertEqual(first.json()['result']['committed'], 400)
        self.assertEqual(first.json()['result']['held'], 160)
        replay = client.post(url, json.dumps(payload), content_type='application/json')
        self.assertEqual(replay.status_code, 200, replay.content[:500])
        self.assertTrue(replay.json()['replayed'])
        self.assertEqual(JawabuFarmerMaster.objects.count(), 400)
        self.assertEqual(JawabuCustomer.objects.count(), 400)
        batch.refresh_from_db()
        self.assertEqual(len(batch.parsed_rows), 160)
        self.assertEqual(sum(bool(row.get('_duplicate_in_upload')) for row in batch.parsed_rows), 40)
        self.assertEqual(bytes(batch.source_content), content)
        self.assertEqual(batch.committed_count, 400)
        changed = {**payload, 'rows': [{**row, 'approved': False} for row in rows]}
        conflict = client.post(url, json.dumps(changed), content_type='application/json')
        self.assertEqual(conflict.status_code, 409, conflict.content[:500])
        stale = self.post('portal_farmup_commit', {'rows': batch.parsed_rows, 'revision_token': token},
                          role='OPERATIONS_ADMIN', args=(batch.pk,))
        self.assertEqual(stale.status_code, 409, stale.content[:500])
        self.assertEqual(JawabuFarmerMaster.objects.count(), 400)

    def test_bulk_monthly_version_reorders_changes_additions_and_removed_held_rows(self):
        from core.services.portal_imports import farmup_revision_token
        from core.models import JawabuFarmerUploadBatch
        source_rows = [self.farmup_row(index) for index in range(600)]
        original = self.farmup_source(source_rows)
        batch = self.stage_farmup_source(original)
        first = self.post('portal_farmup_commit', {
            'rows': [{'row_id': row['row_id'], 'approved': index < 200}
                     for index, row in enumerate(batch.parsed_rows)],
            'revision_token': farmup_revision_token(batch)}, role='OPERATIONS_ADMIN', args=(batch.pk,))
        self.assertEqual(first.status_code, 200, first.content[:500])
        self.assertEqual(first.json()['result']['committed'], 200)
        batch.refresh_from_db()
        latest_rows = [list(row) for row in source_rows[:500]]
        for row in latest_rows[200:250]:
            row[5] = '6500.01'
        latest_rows.extend(self.farmup_row(index) for index in range(600, 700))
        latest_rows.reverse()
        latest = self.farmup_source(latest_rows)
        version = self.stage_farmup_source(latest, batch_id=batch.pk)
        self.assertEqual(version.worklist_id, batch.worklist_id)
        self.assertEqual(version.version_number, 2)
        self.assertEqual(len(version.parsed_rows), 700)
        self.assertEqual(version.reconciliation['source_changed'], 50)
        self.assertEqual(version.reconciliation['removed_from_latest'], 100)
        removed = [row for row in version.parsed_rows if row.get('_source_state') == 'removed']
        self.assertEqual(len(removed), 100)
        self.assertTrue(all(not row['approved'] and row['disposition'] == 'hold' for row in removed))
        selected = set(range(200, 250)) | set(range(600, 700))
        rows = [{**row, 'approved': int(row['National ID']) - 99700000 in selected,
                 'disposition': 'commit_now' if int(row['National ID']) - 99700000 in selected else 'hold',
                 'warning_acknowledged': True} for row in version.parsed_rows]
        payload = {'rows': rows, 'revision_token': farmup_revision_token(version)}
        validation = self.post('portal_farmup_validate', payload, role='OPERATIONS_ADMIN', args=(version.pk,))
        self.assertEqual(validation.status_code, 200, validation.content[:500])
        self.assertEqual(validation.json()['counts']['unchanged'], 200)
        self.assertEqual(validation.json()['counts']['selected'], 150)
        committed = self.post('portal_farmup_commit', payload, role='OPERATIONS_ADMIN', args=(version.pk,))
        self.assertEqual(committed.status_code, 200, committed.content[:500])
        self.assertEqual(committed.json()['result']['committed'], 150)
        self.assertEqual(JawabuFarmerMaster.objects.count(), 350)
        version.refresh_from_db()
        self.assertEqual(version.committed_count, 350)
        pending_ids = {int(row['National ID']) - 99700000 for row in version.parsed_rows}
        self.assertSetEqual(pending_ids - set(range(200)), set(range(250, 600)))
        self.assertEqual(sum(row.get('_source_state') == 'removed' for row in version.parsed_rows), 100)
        self.assertEqual(JawabuFarmerUploadBatch.objects.count(), 2)
        self.assertEqual(bytes(version.source_content), latest)
        batch.refresh_from_db()
        self.assertEqual(bytes(batch.source_content), original)
        self.assertFalse(batch.is_current_version)
        self.evidence.append({'probe': 'bulk_monthly_reconciliation', 'original_source_rows': 600,
                              'latest_source_rows': 600, 'unchanged_existing': 200,
                              'canonical_cases': 350, 'removed_held_preserved': 100,
                              'receipt_held': committed.json()['result']['held'],
                              'uncommitted_held': 350})

    def test_farmup_mixed_date_formats_and_name_limits_reject_invalid_selected_rows(self):
        from core.services.portal_imports import farmup_revision_token
        samples = [('29/02/2024', True), ('2024-02-29', True), ('31-Dec-2025', True),
                   ('January 1, 2026', True), ("'30/04/2026", True), ('30-September-2026', True),
                   ('2025-02-29', False), ('2026-04-31', False), ('not a date', False),
                   ('2026-13-01', False), ('31/02/2026', False), ('00/01/2026', False)]
        source_rows = []
        for index, (value, _valid) in enumerate(samples):
            row = self.farmup_row(index)
            row[6] = value
            source_rows.append(row)
        for index, length in enumerate((255, 256), start=len(samples)):
            row = self.farmup_row(index)
            row[0] = 'X' * length
            source_rows.append(row)
        batch = self.stage_farmup_source(self.farmup_source(source_rows))
        payload = {'rows': [{'row_id': row['row_id'], 'approved': True} for row in batch.parsed_rows],
                   'revision_token': farmup_revision_token(batch)}
        response = self.post('portal_farmup_validate', payload, role='OPERATIONS_ADMIN', args=(batch.pk,))
        self.assertEqual(response.status_code, 200, response.content[:500])
        validation = response.json()['rows']
        for index, (_value, valid) in enumerate(samples):
            with self.subTest(date=_value):
                self.assertEqual(any(issue['severity'] == 'blocker' for issue in validation[index]['issues']), not valid)
        self.assertFalse(validation[-2]['issues'])
        self.assertTrue(any(issue['severity'] == 'blocker' for issue in validation[-1]['issues']))
        committed = self.post('portal_farmup_commit', payload, role='OPERATIONS_ADMIN', args=(batch.pk,))
        self.assertEqual(committed.status_code, 400, committed.content[:500])
        self.assertFalse(JawabuFarmerMaster.objects.exists())
        self.assertFalse(JawabuCustomer.objects.exists())

    @override_settings(PORTAL_PUBLICATION_MIN_SPACING_SECONDS=0)
    def test_bulk_bro_publication_outage_and_lost_write_response_recover_without_duplicates(self):
        from core.models import IntegrationOperation
        from core.services.portal_publication import MASTER_OPERATION, attempt_publication, queued_publication_operations
        from core.tests import FakeJawabuService, FakeMasterDataSheet
        self.group.sheet_id = 'synthetic-bulk-sheet'
        self.group.workflow = {**self.group.workflow, 'master_sync_enabled': True,
                               'master_sheet_id': self.group.sheet_id, 'master_sheet_name': 'Master Data',
                               'master_header_row': 1, 'master_data_start_row': 2}
        self.group.save()
        headers = ['No.', 'Customer Name', 'National ID', 'Primary Phone', 'County', 'Sub-County',
                   'Village', 'Branch', 'Case ID', 'Current Pipeline State', 'JBL Visit Date',
                   'Credit Analysis', 'Final Decision', 'Order No', 'Invoice Number', 'Payment No',
                   'Installation Status', 'Installation Date', 'Commissioning Status', 'Commissioning Date',
                   'Balance Due', 'Deposit Paid to HBG', 'CUSTOMER NO', 'NAME (IMAB)', 'Payment Product',
                   'Mode of Payment', 'Requisition Date']
        sheet = FakeMasterDataSheet(headers)
        sheet.values = [list(headers)]
        with patch('core.services.sheets.GoogleSheetsService.get_instance', side_effect=OSError('Synthetic outage')) as offline:
            for index in range(80):
                response = self.post('portal_create_and_complete_jbl_lead', self.lead(
                    customer_name=f'SYNTHETIC OUTAGE {index}', national_id=str(99600000 + index),
                    primary_phone=f'254700{index:06}'), multipart=True)
                self.assertEqual(response.status_code, 201, response.content[:500])
            offline.assert_not_called()
            first = queued_publication_operations().first()
            self.assertIsNotNone(first)
            self.assertTrue(attempt_publication(first)['error'])
        operations = IntegrationOperation.objects.filter(operation_type=MASTER_OPERATION)
        self.assertEqual(operations.count(), 80)
        self.assertEqual(JawabuFarmerMaster.objects.count(), 80)
        first.refresh_from_db()
        self.assertEqual(first.status, IntegrationOperation.STATUS_RETRYABLE)
        self.assertIsNotNone(first.next_retry_at)
        self.assertFalse(queued_publication_operations().exists())
        self.assertEqual(len(sheet.values), 1)
        operations.filter(pk=first.pk).update(next_retry_at=timezone.now() - timedelta(seconds=1))
        original_update = sheet.batch_update
        lost_responses = []

        def write_then_lose_response(*args, **kwargs):
            result = original_update(*args, **kwargs)
            if len(sheet.values) > 1 and not lost_responses:
                lost_responses.append(True)
                raise TimeoutError('Synthetic response loss after the Sheet accepted the write')
            return result

        with patch('core.services.sheets.GoogleSheetsService.get_instance', return_value=FakeJawabuService(sheet)):
            with patch.object(sheet, 'batch_update', side_effect=write_then_lose_response):
                self.assertTrue(attempt_publication(first)['error'])
            self.assertEqual(len(lost_responses), 1)
            self.assertEqual(len(sheet.values), 2)
            operations.filter(pk=first.pk).update(next_retry_at=timezone.now() - timedelta(seconds=1))
            attempts = 0
            while (operation := queued_publication_operations().first()) is not None:
                self.assertFalse(attempt_publication(operation)['error'])
                attempts += 1
                self.assertLessEqual(attempts, 80)
            self.assertEqual(attempts, 80)
        self.assertEqual(operations.filter(status=IntegrationOperation.STATUS_SUCCEEDED).count(), 80)
        self.assertEqual(JawabuFarmerMaster.objects.count(), 80)
        self.assertEqual(JawabuCustomer.objects.count(), 80)
        self.assertEqual(len(sheet.values) - 1, 80)
        id_column = sheet.values[0].index('Master Record ID')
        self.assertSetEqual({str(row[id_column]) for row in sheet.values[1:]},
                            {str(value) for value in JawabuFarmerMaster.objects.values_list('pk', flat=True)})
        identity_column = sheet.values[0].index('National ID')
        self.assertEqual(len({row[identity_column] for row in sheet.values[1:]}), 80)
        self.evidence.append({'probe': 'bulk_sheet_outage_and_lost_response', 'cases': 80,
                              'succeeded_publications': 80, 'sheet_rows': 80, 'duplicate_rows': 0})

    def test_bro_funded_entry_varied_dates_and_failed_intake_cleanup(self):
        today = timezone.localdate()
        samples = [('2024-02-29', 200), ('2025-12-31', 200), ('2026-01-01', 200),
                   ('2026-04-30', 200), (today.isoformat(), 200),
                   ((today + timedelta(days=1)).isoformat(), 400), ('2025-02-29', 400),
                   ('2026-04-31', 400), ('31/12/2025', 400), ('', 400), ('yesterday', 400)]
        for value, expected in samples:
            with self.subTest(visit_date=value), transaction.atomic():
                response = self.post('portal_create_and_complete_jbl_lead', self.lead(
                    deposit_paid_hbg='5000.00', visit_date=value, visit_status='Rescheduled',
                    location_unavailable_reason='Synthetic indoor visit without GPS'), multipart=True)
                self.assertEqual(response.status_code, expected, response.content[:500])
                if expected == 400:
                    self.assertFalse(JawabuFarmerMaster.objects.exists())
                    self.assertFalse(JawabuCustomer.objects.exists())
                else:
                    farmer = JawabuFarmerMaster.objects.get()
                    self.assertEqual(farmer.jbl_visit_date, date.fromisoformat(value))
                    self.assertFalse(farmer.customer_no)
                transaction.set_rollback(True)

    def test_bro_retry_conflict_identity_and_role_boundaries(self):
        url = reverse('portal_create_and_complete_jbl_lead')
        payload = {**self.lead(), 'client_request_id': 'synthetic-bro-replay-key'}
        first = self.clients['JBL_OFFICER'].post(url, payload)
        self.assertEqual(first.status_code, 201, first.content)
        replay = self.clients['JBL_OFFICER'].post(url, payload)
        self.assertEqual(replay.status_code, 200, replay.content)
        self.assertEqual(JawabuFarmerMaster.objects.count(), 1)
        self.assertEqual(JawabuCustomer.objects.count(), 1)
        changed = self.clients['JBL_OFFICER'].post(url, {**payload, 'deposit_paid_hbg': '100'})
        self.assertEqual(changed.status_code, 409, changed.content)
        duplicate = self.post('portal_create_and_complete_jbl_lead', self.lead(), multipart=True)
        self.assertEqual(duplicate.status_code, 409, duplicate.content)
        for role in ('CREDIT_ANALYST', 'BUSINESS_ADMIN', 'OPERATIONS_ADMIN', 'HB_STAFF'):
            response = self.post('portal_create_and_complete_jbl_lead', self.lead(national_id='99880002'),
                                 role=role, multipart=True)
            self.assertEqual(response.status_code, 403, (role, response.content))
        self.assertEqual(JawabuFarmerMaster.objects.count(), 1)

    def test_credit_and_final_decision_paths_without_sysup(self):
        for stage in ('credit', 'final'):
            for decision, reason in [('Approved', ''), ('Rejected', 'r01'), ('Deferred / On Hold', 'd02')]:
                with self.subTest(stage=stage, decision=decision), transaction.atomic():
                    farmer = JawabuFarmerMaster.objects.create(group_configuration=self.group,
                        customer_name='SYNTHETIC VARIED DECISION', national_id='99880003',
                        primary_phone='254700880003', source='jawabu_office_lead',
                        jbl_visit_date=date(2024, 2, 29), jbl_visit_status='Visited, Awaiting Credit Analysis',
                        deposit_paid_hbg='5000', workflow_state='credit')
                    credit = self.post('portal_set_credit_decision', {
                        'decision': decision if stage == 'credit' else 'Approved',
                        'reason_code': reason if stage == 'credit' else '',
                        'imab_created': 'Yes', 'customer_no': '880003',
                        'workflow_revision': farmer.workflow_revision}, role='CREDIT_ANALYST', args=(farmer.pk,))
                    self.assertEqual(credit.status_code, 200, credit.content)
                    farmer.refresh_from_db()
                    if stage == 'final':
                        final = self.post('portal_set_final_decision', {'final_decision': decision,
                            'reason_code': reason, 'repayment_date': '28', 'repayment_tenor': '12',
                            'workflow_revision': farmer.workflow_revision}, role='BUSINESS_ADMIN', args=(farmer.pk,))
                        self.assertEqual(final.status_code, 200, final.content)
                        farmer.refresh_from_db()
                    self.assertEqual(farmer.workflow_state,
                                     'order' if stage == 'final' and decision == 'Approved' else
                                     'final_review' if decision == 'Approved' else
                                     'rejected' if decision == 'Rejected' else 'deferred')
                    if decision == 'Deferred / On Hold':
                        self.assertEqual((farmer.deferred_until - farmer.deferred_at.date()).days, 60)
                    transaction.set_rollback(True)

    def test_every_portal_route_get_and_post_validation(self):
        farmer = JawabuFarmerMaster.objects.create(group_configuration=self.group,
            customer_name='SYNTHETIC ROUTE CASE', national_id='99880004', primary_phone='254700880004')
        routes = []
        def walk(patterns):
            for item in patterns:
                if isinstance(item, URLResolver):
                    if not item.namespace:
                        walk(item.url_patterns)
                elif isinstance(item, URLPattern) and item.name and (
                        item.name.startswith('portal_') or item.name.startswith('legacy_api_portal_')):
                    routes.append(item)
        walk(get_resolver().url_patterns)
        self.assertGreater(len(routes), 150)
        values = {'farmer_id': str(farmer.pk), 'screen': 'home', 'kind': 'sysup',
                  'queue_key': 'all', 'report_step': 'review', 'document_kind': 'laf',
                  'document_type': 'requisition', 'token': 'synthetic-invalid-token'}
        for route in routes:
            kwargs = {key: values.get(key, 0 if converter.__class__.__name__ == 'IntConverter' else str(UUID(int=1)))
                      for key, converter in route.pattern.converters.items()}
            url = reverse(route.name, kwargs=kwargs)
            extra_methods = {
                'portal_workspace_view_detail': ('PATCH', 'DELETE'),
                'portal_jbl_visit_draft': ('DELETE',), 'portal_credit_decision_draft': ('DELETE',),
                'portal_final_review_draft': ('DELETE',), 'portal_payment_sequence': ('PATCH',),
                'portal_invoice_draft_edit': ('PATCH',),
            }
            for role in ('IT', 'JBL_OFFICER'):
                for method in ('GET', 'POST', *extra_methods.get(route.name, ())):
                    with self.subTest(route=route.name, role=role, method=method), transaction.atomic():
                        request_started = time.monotonic()
                        response = (self.clients[role].get(url) if method == 'GET' else
                                    self.post(route.name, {}, role=role, args=tuple(kwargs.values()), method=method))
                        self.evidence.append({'route': route.name, 'url': url, 'role': role, 'method': method,
                                              'status': response.status_code,
                                              'duration_ms': round((time.monotonic() - request_started) * 1000, 2)})
                        self.assertLess(response.status_code, 500, response.content[:500])
                        transaction.set_rollback(True)
