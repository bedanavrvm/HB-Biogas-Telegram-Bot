"""Real native-session operations; synthetic database, all external IO denied."""
import json
from unittest.mock import patch

from django.test import TestCase, override_settings

from core.models import AccessGrant, CaseUpdate, ComplaintCaseEvent, ComplianceAuditEvent, OperationalLocation, BranchServiceArea
from core import tests_browser_complaints as reads
from staff_auth.tests import TEST_KEY


@override_settings(ROOT_URLCONF='core.test_browser_complaint_urls', STAFF_BROWSER_AUTH_ENABLED=True,
                   STAFF_BROWSER_COMPLAINTS_ENABLED=True, STAFF_MFA_ENCRYPTION_KEYS=[TEST_KEY],
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', SECURE_SSL_REDIRECT=False)
class BrowserComplaintOperationsTests(TestCase):
    setUpTestData = classmethod(reads.BrowserComplaintReadTests.setUpTestData.__func__)
    setUp = reads.BrowserComplaintReadTests.setUp
    post_auth = reads.BrowserComplaintReadTests.post_auth
    login = reads.BrowserComplaintReadTests.login

    @property
    def base(self):
        return f'/api/staff/complaints/operations/v1/groups/{self.group.pk}/'

    def post(self, path, data, csrf=True):
        return self.client.post(self.base + path, json.dumps(data), content_type='application/json',
            **({'HTTP_X_CSRFTOKEN': self.client.cookies['csrftoken'].value} if csrf else {}))

    def grant_role(self, role):
        AccessGrant.objects.create(user=self.user, workflow='complaint_cases', role=role, group_configuration=self.group)

    def test_session_csrf_and_feature_switch_are_independent(self):
        self.assertEqual(self.client.get(self.base + 'bootstrap/').status_code, 401)
        self.login()
        self.assertEqual(self.post('cases/create/', {}, csrf=False).status_code, 403)
        with self.settings(STAFF_BROWSER_COMPLAINTS_ENABLED=False):
            self.assertEqual(self.client.get(self.base + 'bootstrap/').status_code, 404)
            # Restricted v1 remains unaffected by the operations kill switch.
            self.assertEqual(self.client.get(f'/api/staff/complaints/v1/groups/{self.group.pk}/cases/').status_code, 200)

    def test_full_search_projection_and_detail_are_explicit(self):
        self.login()
        data = self.post('cases/', {'q': '999999999999'}).json()
        self.assertEqual(len(data['items']), 7)
        item = data['items'][0]
        self.assertEqual(item['customer_id'], '999999999999')
        self.assertNotIn('case_id', item)
        self.assertNotIn(self.cases[0].message_id, json.dumps(data))
        response = self.client.get(self.base + f'cases/{self.cases[0].pk}/')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn('history', response.json()['case'])
        self.assertNotIn('EXCLUDED_RAW_MESSAGE', response.content.decode())

    def test_foreign_group_and_telegram_credentials_fail_closed(self):
        self.login()
        response = self.client.get(self.base + f'cases/{self.other_case.pk}/')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get(self.base + 'bootstrap/', HTTP_X_TELEGRAM_INIT_DATA='synthetic').status_code, 403)
        self.grant.delete()
        AccessGrant.objects.create(user=self.user, workflow='jawabu_portal', role='IT', group_configuration=self.group)
        self.assertEqual(self.client.get(self.base + 'bootstrap/').status_code, 403)

    def test_create_field_errors_preserve_no_partial_case(self):
        self.login()
        before = ComplaintCaseEvent.objects.count()
        result = self.post('cases/create/', {'client_request_id': 'synthetic-create-001'})
        self.assertEqual(result.status_code, 400, result.content)
        self.assertIn('customer_phone', result.json()['field_errors'])
        self.assertEqual(ComplaintCaseEvent.objects.count(), before)

    def test_valid_create_replays_and_uses_canonical_locations(self):
        county = OperationalLocation.objects.create(location_type='county', code='SYNTHETIC-COUNTY', name='Synthetic County')
        constituency = OperationalLocation.objects.create(location_type='sub_county', code='SYNTHETIC-SUB', name='Synthetic Constituency', parent=county)
        BranchServiceArea.objects.create(branch=self.branch, area=county)
        self.grant.branch = self.branch.name
        self.grant.branch_ref = self.branch
        self.grant.save(update_fields=['branch', 'branch_ref'])
        from core.models import ComplaintCategory
        ComplaintCategory.objects.create(key='synthetic-browser-service', label='Synthetic Browser Service')
        self.login()
        category = self.client.get(self.base + 'bootstrap/').json()['categories'][0]
        body = {'client_request_id': 'synthetic-valid-create-001', 'client_name': 'Synthetic Browser Customer',
            'customer_phone': '0700000098', 'customer_id': '90000098', 'branch_region': self.branch.code,
            'county': county.code, 'sub_county': constituency.code, 'village': 'Synthetic landmark',
            'complaint_category': category, 'complaint_description': 'Synthetic inspection required.'}
        first = self.post('cases/create/', body)
        self.assertEqual(first.status_code, 201, first.content)
        retry = self.post('cases/create/', body)
        self.assertEqual(retry.status_code, 200, retry.content)
        self.assertEqual(first.json()['case']['key'], retry.json()['case']['key'])
        self.assertEqual(first.json()['case']['county'], county.name)
        self.assertEqual(self.post('cases/create/', {**body, 'client_name': 'Changed request'}).status_code, 400)

    def test_comment_retries_revision_conflicts_and_canonical_audit(self):
        self.grant_role('HB_STAFF')
        self.login()
        detail = self.client.get(self.base + f'cases/{self.cases[0].pk}/').json()['case']
        path = f'cases/{self.cases[0].pk}/comment/'
        body = {'client_request_id': 'synthetic-comment-001', 'expected_revision': detail['revision'],
                'comment_text': 'Synthetic inspection scheduled.'}
        first = self.post(path, body)
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(self.post(path, body).status_code, 200)
        self.assertEqual(CaseUpdate.objects.filter(client_request_id=body['client_request_id']).count(), 1)
        self.assertEqual(self.post(path, {**body, 'comment_text': 'Different'}).status_code, 400)
        self.assertEqual(self.post(path, {**body, 'client_request_id': 'synthetic-comment-002'}).status_code, 409)
        event = ComplianceAuditEvent.objects.filter(action='complaint.case.commented').latest('occurred_at')
        self.assertEqual(event.metadata['request_context']['channel'], 'browser')

    def test_role_denied_and_publication_failure_does_not_rollback_resolution(self):
        self.login()
        path = f'cases/{self.cases[0].pk}/resolve/'
        body = {'client_request_id': 'synthetic-resolve-001', 'expected_revision': 1,
                'resolution_text': 'Synthetic repair completed.'}
        self.assertEqual(self.post(path, body).status_code, 403)
        self.grant_role('HB_STAFF')
        detail = self.client.get(self.base + f'cases/{self.cases[0].pk}/').json()['case']
        body['expected_revision'] = detail['revision']
        self.group.complaint_sheet_projection_enabled = True
        self.group.save(update_fields=['complaint_sheet_projection_enabled'])
        with patch('core.services.complaint_cases.update_sheet_case', side_effect=RuntimeError('synthetic outage')):
            response = self.post(path, body)
        self.assertEqual(response.status_code, 200, response.content)
        self.cases[0].refresh_from_db()
        self.assertEqual(self.cases[0].complaint_status, 'Closed')
        self.assertEqual(response.json()['case']['sync_status'], 'failed')

    def test_server_draft_revision_and_no_attachment_storage(self):
        self.login()
        body = {'fields': {'client_name': 'Synthetic draft'}, 'revision': 0}
        self.assertEqual(self.post('draft/', body).status_code, 200)
        self.assertEqual(self.post('draft/', body).status_code, 409)
        draft = self.client.get(self.base + 'draft/').json()['draft']
        self.assertEqual(draft['fields'], body['fields'])
        self.assertEqual(self.post('draft/', {'action': 'discard', 'revision': 0}).status_code, 409)
        self.assertEqual(self.post('draft/', {'action': 'discard', 'key': draft['key'], 'revision': draft['revision']}).status_code, 200)
        self.assertIsNone(self.client.get(self.base + 'draft/').json()['draft'])
        self.assertEqual(self.post('draft/', {'action': 'discard', 'key': draft['key'], 'revision': draft['revision']}).status_code, 200)
        self.post('draft/', body)
        # The new row starts at revision 1 too; a stale discard must not delete it.
        self.assertEqual(self.post('draft/', {'action': 'discard', 'key': draft['key'], 'revision': draft['revision']}).status_code, 409)

    def test_reports_and_export_require_owning_workflow_permission(self):
        self.login()
        self.assertEqual(self.post('reports/', {}).status_code, 403)
        self.grant_role('IT')
        response = self.post('reports/', {})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn('by_time', response.json()['summary'])
        with patch('core.services.complaint_register.export_register_xlsx', return_value=(b'synthetic-xlsx', 7)):
            result = self.post('reports/export/', {'scope': 'filtered', 'filters': {}, 'client_request_id': 'synthetic-export-001'})
        self.assertEqual(result.status_code, 200, result.content)
        self.assertIn('filename=', result['Content-Disposition'])

    def test_email_is_delegated_only_after_current_owning_authorization(self):
        from django.http import JsonResponse
        self.login()
        with patch('report_delivery.views.report_export_response', return_value=JsonResponse({'status': 'queued'})) as dispatch:
            self.assertEqual(self.post('reports/email/', {'email': 'synthetic@example.invalid'}).status_code, 403)
            dispatch.assert_not_called()
            self.grant_role('IT')
            self.assertEqual(self.post('reports/email/', {'email': 'synthetic@example.invalid'}).status_code, 200)
            self.assertEqual(dispatch.call_args.args[:2], (self.user, 'complaint_cases'))

    def test_voice_and_preferences_reject_invalid_values_without_provider_calls(self):
        self.login()
        with patch('core.services.portal_voice.create_transcription') as provider:
            self.assertEqual(self.post('voice/', {'field_name': []}).status_code, 400)
            self.assertEqual(self.post('voice/', {'field_name': 'complaint_resolution_note'}).status_code, 403)
            provider.assert_not_called()
        self.assertEqual(self.post('preferences/', {'preferences': {'default_screen': 'payments'}}).status_code, 400)
        self.assertEqual(self.client.get(self.base + 'recovery/').status_code, 200)
