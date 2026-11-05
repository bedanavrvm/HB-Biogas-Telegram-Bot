"""Customer-directory permission, ranking and no-mutation boundary checks."""
import json
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from complaint_legacy.tests import ImportFixture
from core.models import JawabuCustomer, JawabuFarmerMaster, GroupSheetConfiguration, AccessGrant, ParsedMessage
from core.services.access_grant_governance import governed_access_grant_mutation
from core.tests_complaint_cases import complaint_location_fixture
from core.tests_telegram_authentication import BOT_TOKEN


class DirectoryFixture(ImportFixture):
    def setUp(self):
        super().setUp()
        # Live-server teardown flushes migration seeds; restore the deployed built-in policy.
        from core.models import WorkflowRoleCapability
        from core.services.workflow_capabilities import default_enabled_capability_keys
        for role in ('OFFICER','MANAGER','HB_STAFF','IT'):
            for key in default_enabled_capability_keys('complaint_cases',role):
                WorkflowRoleCapability.objects.get_or_create(workflow='complaint_cases',role=role,capability_key=key,
                    defaults={'enabled':True,'effect':'allow'})
        self.place=complaint_location_fixture()
        self.portal=GroupSheetConfiguration.objects.create(group_id='synthetic-customer-directory',workflow={'type':'jawabu_homebiogas'})
        self.customer=JawabuCustomer.objects.create(national_id='90123456',primary_phone='254712345601')
        self.farmer=JawabuFarmerMaster.objects.create(group_configuration=self.portal,customer=self.customer,
            customer_name='SYNTHETIC ALICE',national_id='90123456',primary_phone='0712345601',secondary_phone='0712345602',
            county='Nakuru County',sub_county='Nakuru East',branch='Nakuru',village='SYNTHETIC VILLAGE')
        self.second=JawabuFarmerMaster.objects.create(group_configuration=self.portal,customer=self.customer,unit_number=2,
            customer_name='SYNTHETIC ALICE',national_id='90123456',primary_phone='0712345601',county='Nakuru County',
            sub_county='Nakuru East',branch='Nakuru',village='OTHER SYNTHETIC VILLAGE')
        self.legacy=JawabuFarmerMaster.objects.create(group_configuration=self.portal,customer_name='SYNTHETIC HISTORICAL',
            national_id='90888888',primary_phone='71234',branch='UNSUPPORTED BRANCH',county='OLD COUNTY',sub_county='OLD AREA',
            source='portal_legacy')

    def suggest(self,body,status=200):
        response=self.client.post(reverse('complaint_cases_customer_suggestions'),json.dumps({'group_id':self.owner.group_id,**body}),
            content_type='application/json',**self.headers)
        self.assertEqual(response.status_code,status,response.content[:800])
        return response.json().get('data',{})


@override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN,COMPLAINT_CASES_WEBAPP_REQUIRE_TELEGRAM_AUTH=True,SECURE_SSL_REDIRECT=False)
class ComplaintCustomerLookupTests(DirectoryFixture,TestCase):
    def test_id_phone_name_order_and_biodata_only_across_portal_branches(self):
        result=self.suggest({'customer_id':'90888888','customer_phone':'0712345601','client_name':'SYNTHETIC ALICE'})
        self.assertEqual(result['matches'][0]['key'],str(self.legacy.pk))
        self.assertEqual(result['matches'][1]['matched_on'],'Primary phone')
        self.assertIn('Different entered ID',result['matches'][1]['conflicts'])
        self.assertEqual(len(result['matches']),3)
        self.assertFalse(AccessGrant.objects.filter(user=self.user,workflow='jawabu_portal').exists())
        self.assertNotIn('invoice',json.dumps(result));self.assertNotIn('deposit',json.dumps(result))
        self.assertFalse(ParsedMessage.objects.exists())

    def test_prefill_replaces_biodata_with_canonical_location_choices_and_keeps_units_distinct(self):
        result=self.suggest({'customer_id':'901'})
        self.assertEqual(len(result['matches']),2)
        selected=self.suggest({'source_key':str(self.farmer.pk)})['selection']
        self.assertEqual(selected['fields']['customer_phone'],'254712345601')
        self.assertEqual(selected['fields']['county'],self.place['county'])
        self.assertEqual(selected['fields']['sub_county'],self.place['sub_county'])
        self.assertEqual(selected['fields']['portal_source_key'],str(self.farmer.pk))
        self.assertEqual(selected['warnings'],[])
        self.assertNotIn('gps_link',selected['fields'])

    def test_legacy_bad_values_are_preserved_and_secondary_numbers_do_not_identify_a_customer(self):
        selected=self.suggest({'source_key':str(self.legacy.pk)})['selection']
        self.assertEqual(selected['fields']['customer_phone'],'71234')
        self.assertEqual(selected['fields']['county'],'')
        self.assertTrue(any('OLD COUNTY' in warning for warning in selected['warnings']))
        self.assertEqual(self.suggest({'customer_phone':'0712345602'})['matches'],[])
        self.assertEqual(self.suggest({'client_name':'zzznomatch'})['matches'],[])
        self.assertEqual(self.suggest({'customer_id':'90'})['matches'],[])
        self.suggest({'source_key':'not-a-uuid'},status=400)

    def test_non_creators_and_unsigned_requests_cannot_read_the_directory(self):
        with governed_access_grant_mutation('Synthetic denied customer-directory role'):
            AccessGrant.objects.filter(user=self.user).delete()
            AccessGrant.objects.create(user=self.user,workflow='complaint_cases',role='HB_STAFF',group_configuration=self.owner)
        self.suggest({'client_name':'SYNTHETIC'},status=403)
        with governed_access_grant_mutation('Synthetic Portal-only directory denial'):
            AccessGrant.objects.filter(user=self.user).delete()
            AccessGrant.objects.create(user=self.user,workflow='jawabu_portal',role='IT',group_configuration=self.portal)
        self.suggest({'client_name':'SYNTHETIC'},status=403)
        self.headers={};self.suggest({'source_key':str(self.farmer.pk)},status=403)

    def test_cross_branch_lookup_does_not_expand_complaint_creation_scope(self):
        from core.models import OperationalLocation
        other=OperationalLocation.objects.create(code='DIRECTORY-OTHER-BRANCH',name='Directory Other Branch',location_type='branch')
        self.farmer.branch=other.name;self.farmer.save(update_fields=['branch'])
        with governed_access_grant_mutation('Synthetic scoped Complaints creator'):
            AccessGrant.objects.filter(user=self.user).delete()
            AccessGrant.objects.create(user=self.user,workflow='complaint_cases',role='OFFICER',branch='Nakuru',group_configuration=self.owner)
        self.assertIn(str(self.farmer.pk),[row['key'] for row in self.suggest({'customer_id':'90123456'})['matches']])
        selected=self.suggest({'source_key':str(self.farmer.pk)})['selection']
        self.assertEqual(selected['fields']['branch_region'],'')
        self.assertIn('within your Complaints permissions',selected['field_issues']['branch_region'])
