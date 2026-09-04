from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import (
    BranchServiceArea,
    JawabuFarmerMaster,
    LocationConfigurationEvent,
    LocationMappingIssue,
    LocationPolicyState,
    OperationalLocation,
)
from core.services.location_catalog import (
    LocationCatalogError,
    catalog_readiness,
    location_options,
    resolve_location,
    resolve_mapping_issue,
    validate_location_selection,
)
from core.services.branches import global_branch_choices
from core.services.locations import configured_location_names, global_county_choices
from core.services.order_approval import order_approval_branch_choices
from core.services.parser import _canonical_county


class GovernedLocationCatalogTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.staff = user_model.objects.create_user(username='location-staff')
        cls.superuser = user_model.objects.create_superuser(
            username='location-root', email='location-root@example.test', password='test-only-password',
        )

    def setUp(self):
        self.branch = OperationalLocation.objects.get(location_type='branch', code='JBL-BR-EMBU')
        self.county = OperationalLocation.objects.get(location_type='county', code='KE-14')
        self.sub_county = OperationalLocation.objects.get(
            location_type='sub_county', code='KE-14-SC-EMBU-EAST',
        )
        self.other_county = OperationalLocation.objects.get(location_type='county', code='KE-32')
        BranchServiceArea.objects.create(branch=self.branch, area=self.county, is_primary=True)

    def test_verified_seed_has_counties_sub_counties_and_immutable_codes(self):
        self.assertEqual(OperationalLocation.objects.filter(location_type='county').count(), 47)
        self.assertEqual(OperationalLocation.objects.filter(location_type='sub_county').count(), 349)
        self.assertEqual(self.sub_county.parent, self.county)
        self.assertEqual(resolve_location('MURANGA', location_type='county').code, 'KE-21')

    def test_options_are_access_and_service_area_scoped(self):
        payload = location_options(
            user=self.staff,
            access={'branches': [self.branch.name]},
            branch_value=self.branch.code,
            county_value=self.county.code,
        )
        self.assertEqual([item['code'] for item in payload['branches']], [self.branch.code])
        self.assertEqual([item['code'] for item in payload['counties']], [self.county.code])
        self.assertIn(self.sub_county.code, [item['code'] for item in payload['sub_counties']])

    def test_strict_policy_rejects_outside_area_and_audits_superuser_override(self):
        LocationPolicyState.objects.filter(pk=1).update(mode=LocationPolicyState.MODE_STRICT)
        with self.assertRaisesMessage(LocationCatalogError, 'outside this branch service area'):
            validate_location_selection(
                branch_value=self.branch.code,
                county_value=self.other_county.code,
                source_workflow='jawabu_portal',
                source_model='JawabuFarmerMaster',
                source_record_id='strict-rejection',
                actor=self.staff,
            )
        branch, county, _sub_county = validate_location_selection(
            branch_value=self.branch.code,
            county_value=self.other_county.code,
            source_workflow='jawabu_portal',
            source_model='JawabuFarmerMaster',
            source_record_id='strict-override',
            actor=self.superuser,
            override_reason='Approved exceptional field visit.',
            request_id='location-override-1',
        )
        self.assertEqual(branch, self.branch)
        self.assertEqual(county, self.other_county)
        self.assertTrue(LocationConfigurationEvent.objects.filter(
            action='service_area_override', request_id='location-override-1',
        ).exists())

    def test_mapping_resolution_links_ref_without_rewriting_historical_text(self):
        farmer = JawabuFarmerMaster.objects.create(
            customer_name='Synthetic Location Customer', county='Legacy Embu Label',
        )
        issue = LocationMappingIssue.objects.create(
            location_type='county', raw_value='Legacy Embu Label',
            normalized_value='legacy_embu_label', source_workflow='jawabu_portal',
            source_model='JawabuFarmerMaster', source_field='county',
            source_record_id=str(farmer.pk),
        )
        resolve_mapping_issue(issue, location=self.county, actor=self.superuser)
        farmer.refresh_from_db()
        issue.refresh_from_db()
        self.assertEqual(farmer.county, 'Legacy Embu Label')
        self.assertEqual(farmer.county_ref, self.county)
        self.assertEqual(issue.status, LocationMappingIssue.STATUS_RESOLVED)

    def test_readiness_exposes_uncovered_branches(self):
        readiness = catalog_readiness()
        self.assertFalse(readiness['ready'])
        self.assertGreater(len(readiness['uncovered_branches']), 0)
        self.assertEqual(readiness['canonical_counts'], {'counties': 47, 'sub_counties': 349})

    def test_governance_admin_pages_are_available_to_superuser(self):
        self.client.force_login(self.superuser)
        for model_name in (
            'operationallocation', 'operationallocationalias', 'branchservicearea',
            'locationmappingissue', 'locationpolicystate', 'locationconfigurationevent',
        ):
            response = self.client.get(reverse(f'admin:core_{model_name}_changelist'))
            self.assertEqual(response.status_code, 200, model_name)


class OperationalLocationCompatibilityTests(TestCase):
    """Keep the pre-catalogue shared-list and fallback contracts covered."""

    @override_settings(WORKFLOW_BRANCH_CHOICES='Legacy Branch')
    def test_database_branches_override_environment_fallback(self):
        OperationalLocation.objects.create(
            location_type='branch', name='Central Test Branch', code='JBL-BR-CENTRAL-TEST',
        )

        self.assertIn('Central Test Branch', global_branch_choices())
        self.assertIn('CENTRAL TEST BRANCH', order_approval_branch_choices())
        self.assertNotIn('Legacy Branch', global_branch_choices())

    def test_database_counties_feed_parser_canonicalization(self):
        OperationalLocation.objects.create(
            location_type='county', name='JBL Test County', code='KE-TEST-COUNTY',
        )

        self.assertIn('JBL Test County', global_county_choices())
        self.assertEqual(_canonical_county('jbl test county'), 'JBL Test County')

    def test_inactive_values_are_not_returned(self):
        OperationalLocation.objects.create(
            location_type='branch', name='Active Test Branch', code='JBL-BR-ACTIVE-TEST',
        )
        OperationalLocation.objects.create(
            location_type='branch', name='Retired Test Branch', code='JBL-BR-RETIRED-TEST',
            active=False, retired_at=None,
        )

        self.assertIn('Active Test Branch', global_branch_choices())
        self.assertNotIn('Retired Test Branch', global_branch_choices())

    def test_location_lookup_falls_back_when_database_connection_is_aborted(self):
        with patch.object(
            OperationalLocation.objects,
            'filter',
            side_effect=DatabaseError('current transaction is aborted'),
        ):
            self.assertEqual(configured_location_names('branch'), [])

        self.assertIn('Embu', global_branch_choices())

    @override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=False, SECURE_SSL_REDIRECT=False)
    def test_portal_meta_exposes_central_lists(self):
        OperationalLocation.objects.create(
            location_type='branch', name='Central Portal Branch', code='JBL-BR-CENTRAL-PORTAL',
        )
        OperationalLocation.objects.create(
            location_type='county', name='JBL Portal County', code='KE-PORTAL-COUNTY',
        )

        response = self.client.get(reverse('portal_meta'))

        self.assertEqual(response.status_code, 200)
        self.assertIn('Central Portal Branch', response.json()['branches'])
        self.assertIn('JBL Portal County', response.json()['counties'])
        self.assertEqual(response.json()['carto_basemaps'], {
            'enabled': False,
            'light_url': '',
            'dark_url': '',
        })
        self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')

    @override_settings(
        PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=False,
        SECURE_SSL_REDIRECT=False,
        CARTO_BASEMAP_API_KEY='carto key+/=?',
    )
    def test_portal_meta_exposes_url_encoded_carto_tile_templates(self):
        response = self.client.get(reverse('portal_meta'))

        self.assertEqual(response.status_code, 200)
        basemaps = response.json()['carto_basemaps']
        self.assertTrue(basemaps['enabled'])
        self.assertEqual(
            basemaps['light_url'],
            'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/'
            '{z}/{x}/{y}{r}.png?key=carto%20key%2B%2F%3D%3F',
        )
        self.assertEqual(
            basemaps['dark_url'],
            'https://{s}.basemaps.cartocdn.com/dark_all/'
            '{z}/{x}/{y}{r}.png?key=carto%20key%2B%2F%3D%3F',
        )
