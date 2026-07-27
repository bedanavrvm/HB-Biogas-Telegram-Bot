from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import OperationalLocation
from core.services.branches import global_branch_choices
from core.services.locations import global_county_choices
from core.services.order_approval import order_approval_branch_choices
from core.services.parser import _canonical_county


class OperationalLocationTests(TestCase):
    def setUp(self):
        OperationalLocation.objects.all().delete()

    @override_settings(WORKFLOW_BRANCH_CHOICES='Legacy Branch')
    def test_database_branches_override_environment_fallback(self):
        OperationalLocation.objects.create(location_type='branch', name='Central Branch')

        self.assertEqual(global_branch_choices(), ['Central Branch'])
        self.assertEqual(order_approval_branch_choices(), ['CENTRAL BRANCH'])

    def test_database_counties_feed_parser_canonicalization(self):
        OperationalLocation.objects.create(location_type='county', name='JBL County')

        self.assertEqual(global_county_choices(), ['JBL County'])
        self.assertEqual(_canonical_county('jbl county'), 'JBL County')

    def test_inactive_values_are_not_returned(self):
        OperationalLocation.objects.create(location_type='branch', name='Active Branch')
        OperationalLocation.objects.create(location_type='branch', name='Retired Branch', active=False)

        self.assertEqual(global_branch_choices(), ['Active Branch'])

    @override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=False, SECURE_SSL_REDIRECT=False)
    def test_portal_meta_exposes_central_lists(self):
        OperationalLocation.objects.create(location_type='branch', name='Central Branch')
        OperationalLocation.objects.create(location_type='county', name='JBL County')

        response = self.client.get(reverse('portal_meta'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['branches'], ['Central Branch'])
        self.assertEqual(response.json()['counties'], ['JBL County'])
