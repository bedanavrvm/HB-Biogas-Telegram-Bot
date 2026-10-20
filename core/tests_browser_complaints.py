"""Native company identity plus owning Complaints authorization, synthetic only."""
import json
import time
from datetime import timedelta
from unittest.mock import patch

from allauth.account.models import EmailAddress
from allauth.mfa.totp.internal.auth import TOTP, format_hotp_value, generate_totp_secret, hotp_value
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import Resolver404, resolve
from django.utils import timezone

from core.models import (
    AccessGrant, CaseUpdate, ComplaintCaseControl, ComplaintCaseEvent, GroupSheetConfiguration,
    OperationalLocation, ParsedMessage, ProcessedMessage, RawMessage, WorkflowRoleCapability,
)
from core.services.access_grant_governance import governed_access_grant_mutation
from core.services.workflow_capabilities import default_enabled_capability_keys
from staff_auth.lifecycle import apply_change
from staff_auth.models import StaffBrowserAdmission
from staff_auth.tests import PASSWORD, TEST_KEY, admit_synthetic_user

BASE = '/api/staff/complaints/v1/'


def seed_complaint_policy():
    for role in ('OFFICER', 'MANAGER', 'HB_STAFF', 'IT'):
        for key in default_enabled_capability_keys('complaint_cases', role):
            WorkflowRoleCapability.objects.get_or_create(workflow='complaint_cases', role=role,
                                                         capability_key=key, defaults={'enabled': True, 'effect': 'allow'})


def synthetic_case(group, index, **overrides):
    source = f'synthetic-source-{group.pk}-{index}'
    raw = RawMessage.objects.create(telegram_message_id=source, content='EXCLUDED_RAW_MESSAGE')
    processed = ProcessedMessage.objects.create(message_hash=f'synthetic-hash-{group.pk}-{index}', raw_message=raw)
    fields = dict(group_id=group.group_id, message_id=source, processed_message=processed,
                  timestamp=timezone.now() + timedelta(minutes=index), raw_message='EXCLUDED_RAW_MESSAGE',
                  customer_name=f'Synthetic Customer {index:02d}', customer_phone='0000000000',
                  customer_id='999999999999', branch_region='Synthetic Other Branch',
                  complaint_category='System service', complaint_description='Synthetic digester needs inspection.',
                  complaint_status='Open', gps_link='https://example.invalid/EXCLUDED_LOCATION')
    fields.update(overrides)
    return ParsedMessage.objects.create(**fields)


@override_settings(ROOT_URLCONF='core.test_browser_complaint_urls', STAFF_BROWSER_AUTH_ENABLED=True,
                   STAFF_MFA_ENCRYPTION_KEYS=[TEST_KEY], EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
                   SECURE_SSL_REDIRECT=False)
class BrowserComplaintReadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_complaint_policy()
        cls.user = get_user_model().objects.create_user('complaint_browser_reader', 'reader@example.invalid', PASSWORD)
        with patch('django.utils.timezone.now', return_value=timezone.now() - timedelta(seconds=1)):
            admit_synthetic_user(cls.user)
        EmailAddress.objects.create(user=cls.user, email=cls.user.email, primary=True, verified=True)
        cls.secret = generate_totp_secret()
        TOTP.activate(cls.user, cls.secret)
        cls.group = GroupSheetConfiguration.objects.create(group_id='synthetic-complaint-browser',
                    display_name='Synthetic Complaints', workflow={'type': 'case'}, complaint_sheet_projection_enabled=False)
        cls.other = GroupSheetConfiguration.objects.create(group_id='synthetic-other-complaints',
                    display_name='EXCLUDED_OTHER_GROUP', workflow={'type': 'case'}, complaint_sheet_projection_enabled=False)
        cls.branch = OperationalLocation.objects.create(location_type='branch', code='SYNTHETIC-BROWSER', name='Synthetic Reader Branch')
        with governed_access_grant_mutation('Synthetic browser read fixture'):
            cls.grant = AccessGrant.objects.create(user=cls.user, workflow='complaint_cases', role='OFFICER',
                                                  group_configuration=cls.group, branch=cls.branch)
        cls.cases = [synthetic_case(cls.group, index) for index in range(7)]
        cls.closed = synthetic_case(cls.group, 8, complaint_status='Closed')
        cls.other_case = synthetic_case(cls.other, 0)
        CaseUpdate.objects.create(parsed_message=cls.cases[0], group_id=cls.group.group_id, old_status='Open',
            new_status='Open', updated_by='Synthetic Resolver', source='mini_app_comment',
            resolution_text='EXCLUDED_HISTORY_NOTE', raw_update_text='EXCLUDED_RAW_UPDATE',
            telegram_message_id='EXCLUDED_MESSAGE', gps_link='https://example.invalid/EXCLUDED_GPS')

    def setUp(self):
        cache.clear()
        self.client = Client(enforce_csrf_checks=True)
        self.enterContext(governed_access_grant_mutation('Synthetic browser read test'))
        self.enterContext(patch('socket.socket.connect', side_effect=AssertionError('External network forbidden')))
        self.client.get('/test-staff-auth/v1/session/')

    def post_auth(self, action, values):
        return self.client.post('/test-staff-auth/v1/' + action + '/', data=json.dumps(values),
            content_type='application/json', HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value)

    def login(self):
        self.assertEqual(self.post_auth('login', {'username': self.user.username, 'password': PASSWORD}).status_code, 401)
        code = format_hotp_value(hotp_value(self.secret, int(time.time()) // 30))
        response = self.post_auth('mfa', {'code': code})
        self.assertEqual(response.status_code, 200, response.content)

    def queue(self, **params):
        return self.client.get(f'{BASE}groups/{self.group.pk}/cases/', params)

    def detail(self, case=None, group=None):
        return self.client.get(f'{BASE}groups/{(group or self.group).pk}/cases/{(case or self.cases[0]).pk}/')

    def test_native_identity_and_workflow_authority_are_both_required(self):
        self.assertEqual(self.queue().status_code, 401)
        self.post_auth('login', {'username': self.user.username, 'password': PASSWORD})
        self.assertEqual(self.queue().status_code, 401)
        self.assertEqual(ComplaintCaseControl.objects.count(), 0)

    def test_native_login_reads_shared_branch_queue_and_allowlisted_history(self):
        self.login()
        groups = self.client.get(BASE + 'groups/')
        self.assertEqual(groups.json(), {'groups': [{'key': str(self.group.pk), 'label': self.group.display_name}]})
        queue = self.queue()
        self.assertEqual(queue.status_code, 200, queue.content)
        self.assertEqual(queue.json()['pagination'], {'page': 1, 'pages': 2, 'total': 7, 'page_size': 5})
        item = queue.json()['items'][0]
        self.assertEqual(item['key'], str(self.cases[0].pk))
        self.assertEqual(set(item), {'key', 'reference', 'customer_name', 'branch', 'category', 'status', 'reported_at'})
        detail = self.detail()
        self.assertEqual(detail.status_code, 200, detail.content)
        data = detail.json()['case']
        self.assertEqual(set(data), set(item) | {'description', 'history', 'history_truncated'})
        self.assertEqual(set(data['history'][0]), {'action', 'status', 'created_at', 'updated_by', 'actor_affiliation'})
        self.assertEqual(data['history'][0]['action'], 'commented')
        self.assertEqual(data['branch'], 'Synthetic Other Branch')
        for excluded in ('0000000000', '999999999999', 'EXCLUDED', self.cases[0].message_id, self.group.group_id):
            self.assertNotIn(excluded, (queue.content + detail.content + groups.content).decode())
        self.assertEqual(detail['Cache-Control'], 'no-store, private')
        self.assertEqual(detail['Pragma'], 'no-cache')

    def test_search_status_and_paging_use_owning_queue(self):
        self.login()
        self.assertEqual(len(self.queue(page=2).json()['items']), 2)
        self.assertEqual(self.queue(page=999).json()['pagination']['page'], 2)
        self.assertEqual(self.queue(status='resolved').json()['items'][0]['key'], str(self.closed.pk))
        self.assertEqual(self.queue(status='all').json()['pagination']['total'], 8)
        self.assertEqual(self.queue(q='Customer 03').json()['items'][0]['key'], str(self.cases[3].pk))
        reference = self.queue().json()['items'][0]['reference']
        self.assertEqual(self.queue(q=reference).json()['items'][0]['key'], str(self.cases[0].pk))
        for query in ('0000000000', '999999999999', self.cases[0].message_id):
            self.assertEqual(self.queue(q=query).json()['items'], [])

    def test_foreign_group_and_uuid_never_initialize_foreign_controls(self):
        self.login()
        self.assertEqual(self.detail(self.other_case).status_code, 404)
        self.assertEqual(self.detail(self.other_case, self.other).status_code, 403)
        self.assertEqual(ComplaintCaseControl.objects.count(), 0)

    def test_revoked_and_unrelated_workflow_grants_fail_closed(self):
        self.login()
        self.grant.delete()
        AccessGrant.objects.create(user=self.user, workflow='jawabu_portal', role='IT', group_configuration=self.group)
        self.assertEqual(self.client.get(BASE + 'groups/').json(), {'groups': []})
        self.assertEqual(self.queue().status_code, 403)
        self.assertEqual(self.detail().status_code, 403)
        self.assertEqual(ComplaintCaseControl.objects.count(), 0)

    def test_browser_revocation_blocks_existing_native_session(self):
        self.login()
        row = StaffBrowserAdmission.objects.get(user=self.user)
        apply_change(actor=get_user_model().objects.get(username='synthetic_admission_root'), target_user_id=self.user.pk,
                     action='revoke_sessions', expected_revision=row.revision, request_key='synthetic-complaint-revoke', reason='Synthetic boundary')
        self.assertEqual(self.queue().status_code, 401)

    def test_current_capability_and_enabled_group_are_rechecked(self):
        self.login()
        WorkflowRoleCapability.objects.filter(workflow='complaint_cases', role='OFFICER',
                                               capability_key='complaint.queue.view').update(enabled=True, effect='deny')
        cache.clear()
        self.assertEqual(self.queue().status_code, 403)
        self.assertEqual(self.client.get(BASE + 'groups/').json(), {'groups': []})
        self.group.enabled = False
        self.group.save(update_fields=['enabled'])
        self.assertEqual(self.detail().status_code, 403)
        self.assertEqual(ComplaintCaseControl.objects.count(), 0)

    def test_reads_are_repeatable_without_transitions_or_publication(self):
        self.login()
        self.assertEqual(self.detail().status_code, 200)
        control = ComplaintCaseControl.objects.get(parsed_message=self.cases[0])
        before = (control.reference_number, control.revision, CaseUpdate.objects.count(), ComplaintCaseEvent.objects.count())
        self.assertEqual(self.detail().status_code, 200)
        control.refresh_from_db()
        self.assertEqual((control.reference_number, control.revision, CaseUpdate.objects.count(), ComplaintCaseEvent.objects.count()), before)
        self.cases[0].refresh_from_db()
        self.assertEqual(self.cases[0].complaint_status, 'Open')
        self.assertFalse(self.cases[0].synced_to_sheets)

    def test_invalid_filters_mixed_credentials_and_methods(self):
        self.login()
        for params in ({'q': 'x' * 151}, {'status': 'unexpected'}, {'page': 'nan'}, {'page': 0}, {'page': '9999999'}, {'cursor': 'anything'}):
            with self.subTest(params=params):
                self.assertEqual(self.queue(**params).status_code, 400)
        self.assertEqual(self.client.get(f'{BASE}groups/{self.group.pk}/cases/?page=1&page=2').status_code, 400)
        for header in ('HTTP_AUTHORIZATION', 'HTTP_X_TELEGRAM_INIT_DATA', 'HTTP_X_SESSION_TOKEN'):
            self.assertEqual(self.client.get(BASE + 'groups/', **{header: 'invalid'}).status_code, 403)
        self.assertEqual(self.client.post(BASE + 'groups/', {}, HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value).status_code, 405)

    def test_off_switch_and_production_routes_stay_closed(self):
        with override_settings(STAFF_BROWSER_AUTH_ENABLED=False):
            self.assertEqual(self.queue().status_code, 404)
        for url in (BASE + 'groups/', f'{BASE}groups/1/cases/', '/complaints.html'):
            with self.assertRaises(Resolver404):
                resolve(url, urlconf='config.urls')
