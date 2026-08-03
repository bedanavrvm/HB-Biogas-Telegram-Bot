"""Focused Portal role-split regressions."""

import json
from datetime import date

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from core.api.portal_views import portal_my_visits, portal_requisition_preview
from core.models import AccessGrant, JawabuFarmerMaster
from core.services.jawabu_case360 import record_pipeline_event
from core.services.telegram_identity import user_access


class PortalRoleSeparationTests(TestCase):
    def setUp(self):
        self.officer = get_user_model().objects.create_user(
            username='visit-officer', is_active=True,
        )
        self.other_officer = get_user_model().objects.create_user(
            username='other-visit-officer', is_active=True,
        )
        AccessGrant.objects.create(
            user=self.officer, workflow='jawabu_portal', role='JBL_OFFICER', branch='EMBU',
        )
        self.factory = RequestFactory()

    def _request(self, path, method='get', data=None):
        request = getattr(self.factory, method)(path, data=data or {}, content_type='application/json')
        request.portal_user = self.officer
        request.portal_access = user_access(self.officer, 'jawabu_portal')
        return request

    def test_my_visits_only_returns_cases_with_latest_completion_by_officer(self):
        mine = JawabuFarmerMaster.objects.create(
            customer_name='My Visit', national_id='10000001', primary_phone='254700000001',
            branch='EMBU', status='active', jbl_visit_date=date(2026, 8, 1),
        )
        not_mine = JawabuFarmerMaster.objects.create(
            customer_name='Other Visit', national_id='10000002', primary_phone='254700000002',
            branch='EMBU', status='active', jbl_visit_date=date(2026, 8, 1),
        )
        record_pipeline_event(mine, action='jbl_visit_completed', actor_user=self.officer)
        record_pipeline_event(not_mine, action='jbl_visit_completed', actor_user=self.other_officer)

        response = portal_my_visits(self._request('/api/portal/my-visits/'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item['id'] for item in json.loads(response.content)['farmers']], [str(mine.pk)],
        )

    def test_jbl_officer_cannot_preview_a_requisition_batch(self):
        farmer = JawabuFarmerMaster.objects.create(
            customer_name='Approved Client', national_id='10000003', primary_phone='254700000003',
            branch='EMBU', status='active', final_decision='Approved', workflow_state='order',
        )
        response = portal_requisition_preview(self._request(
            '/api/portal/requisition-queue/preview/', 'post',
            {'farmer_ids': [str(farmer.pk)], 'order_number': 'READ-ONLY', 'requisition_date': '2026-08-03'},
        ))

        self.assertEqual(response.status_code, 403)
