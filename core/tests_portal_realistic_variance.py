"""Synthetic Portal input, chronology and route probes; no external providers."""
from datetime import date, timedelta
from hashlib import sha256
import hmac
import json
from pathlib import Path
import time
from urllib.parse import urlencode
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
