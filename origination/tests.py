"""Domain ownership, independent access and future-reference boundaries."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.apps import apps
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import resolve, reverse
from django.utils import timezone

from core.models import AccessGrant, EmergencyAccessGrant, GroupSheetConfiguration, Product, ProductVersion
from core.services.telegram_identity import user_access
from core.services.workflow_capabilities import capability_definitions
from core.services.workflow_links import (
    RECORD_ADAPTERS, RecordUnavailable, describe_record, launch_record, parse_reference,
    record_reference, resolve_record,
)
from origination.models import LoanOriginationApplication, OriginationProductDefinition
from origination.services.origination_access import DENIED, FULL, application_presentation_mode, scope_application_queryset
from origination.services.origination_esign import authorize_staff_signer
from origination.services.loan_origination import OriginationError


class IndependentOriginationTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(username='synthetic-independent-officer')
        self.other = get_user_model().objects.create_user(username='synthetic-independent-other')
        self.product = Product.objects.create(code='synthetic_independent', name='Synthetic independent product')
        self.version = ProductVersion.objects.create(product=self.product, version=1)
        self.definition = OriginationProductDefinition.objects.create(
            product_key='synthetic-independent-form', name='Synthetic independent form', version=1,
            product_version=self.version,
        )
        self.group = GroupSheetConfiguration.objects.create(group_id='synthetic-origin-group', workflow={'type':'loan_origination'})
        self.other_group = GroupSheetConfiguration.objects.create(group_id='synthetic-other-origin-group', workflow={'type':'loan_origination'})
        self.application = LoanOriginationApplication.objects.create(
            officer=self.actor, product_definition=self.definition, product_version=self.version,
            branch='SYNTHETIC-A', group_configuration=self.group,
            client_request_id='synthetic-independent-create', reference_number='ORG-SYNTHETIC-INDEPENDENT',
        )

    def grant(self, *, workflow='loan_origination', role='JBL_OFFICER', branch='SYNTHETIC-A', product='', group=None):
        return AccessGrant.objects.create(user=self.actor, workflow=workflow, role=role,
                                          branch=branch, product=product, group_configuration=group)

    def test_models_and_http_boundary_are_owned_by_app(self):
        owned = list(apps.get_app_config('origination').get_models())
        self.assertEqual(len(owned),27)
        self.assertTrue(all(model._meta.db_table.startswith('core_') for model in owned))
        self.assertTrue(all(model._meta.app_label=='origination' for model in owned))
        self.assertFalse(any('Origination' in model.__name__ for model in apps.get_app_config('core').get_models()))
        self.assertTrue(all(model in admin.site._registry for model in owned))
        self.assertEqual(resolve(reverse('loan_origination_applications')).func.__module__,'origination.views')
        self.assertEqual(reverse('loan_origination_app'),'/origination/')
        self.assertEqual(reverse('loan_origination_signing_short_app'),'/s/')

    @override_settings(ORIGINATION_WEBAPP_REQUIRE_TELEGRAM_AUTH=False, DEBUG=True)
    def test_portal_grants_do_not_authorize_origination(self):
        self.grant(workflow='jawabu_portal',role='IT',branch='')
        self.client.force_login(self.actor)
        self.assertEqual(self.client.get(reverse('loan_origination_applications')).status_code,403)
        self.assertFalse(user_access(self.actor,'loan_origination')['authorized'])
        self.grant()
        response=self.client.get(reverse('loan_origination_applications'))
        self.assertEqual(response.status_code,200)
        self.assertIn(str(self.application.pk),response.content.decode())

    def test_capabilities_belong_only_to_independent_workflow(self):
        definitions=[item for item in capability_definitions() if item.key.startswith('origination.')]
        self.assertEqual(len(definitions),5)
        self.assertEqual({item.workflow for item in definitions},{'loan_origination'})
        self.assertTrue(any('CA' in item.default_roles for item in definitions if item.key.endswith('signing.staff')))

    def test_scope_is_a_complete_tuple_and_legacy_is_not_claimed_by_group_grant(self):
        self.grant(branch='SYNTHETIC-B',product=self.product.code,group=self.group)
        self.grant(branch='SYNTHETIC-A',product='another-product',group=self.group)
        self.grant(branch='SYNTHETIC-A',product=self.product.code,group=self.other_group)
        access=user_access(self.actor,'loan_origination')
        self.assertEqual(application_presentation_mode(self.application,user=self.actor,access=access),DENIED)
        self.assertFalse(scope_application_queryset(LoanOriginationApplication.objects.all(),user=self.actor,access=access).exists())
        self.grant(product=self.product.code,group=self.group)
        access=user_access(self.actor,'loan_origination')
        self.assertEqual(application_presentation_mode(self.application,user=self.actor,access=access),FULL)
        self.application.group_configuration=None
        self.application.save(update_fields=['group_configuration'])
        self.assertEqual(application_presentation_mode(self.application,user=self.actor,access=access),DENIED)
        self.assertFalse(scope_application_queryset(LoanOriginationApplication.objects.all(),user=self.actor,access=access).exists())
        self.grant(product=self.product.code)
        self.assertEqual(application_presentation_mode(self.application,user=self.actor,access=user_access(self.actor,'loan_origination')),FULL)

    def test_owner_visibility_and_temporary_grant_expiry(self):
        grant=EmergencyAccessGrant.objects.create(user=self.actor,workflow='loan_origination',role='JBL_OFFICER',
            branch='SYNTHETIC-A',group_configuration=self.group,expires_at=timezone.now()+timedelta(hours=1),
            reason='Synthetic temporary test',activated_by=self.other)
        self.assertEqual(application_presentation_mode(self.application,user=self.actor,access=user_access(self.actor,'loan_origination')),FULL)
        self.application.officer=self.other
        self.application.save(update_fields=['officer'])
        self.assertEqual(application_presentation_mode(self.application,user=self.actor,access=user_access(self.actor,'loan_origination')),DENIED)
        EmergencyAccessGrant.objects.filter(pk=grant.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertFalse(user_access(self.actor,'loan_origination')['authorized'])

    def test_credit_analyst_slot_has_independent_scoped_authority(self):
        self.grant(role='CA',group=self.group)
        authorize_staff_signer(actor=self.actor,application=self.application,signer_role='credit_analyst')
        with self.assertRaises(OriginationError):
            authorize_staff_signer(actor=self.actor,application=self.application,signer_role='branch_manager')
        self.application.group_configuration=self.other_group
        with self.assertRaises(OriginationError):
            authorize_staff_signer(actor=self.actor,application=self.application,signer_role='credit_analyst')

    def test_origination_reference_rechecks_access_and_does_not_leak_identity(self):
        reference=record_reference(self.application)
        self.assertEqual(set(reference),{'version','app','entity','id'})
        self.assertNotIn('customer',str(reference))
        with self.assertRaises(RecordUnavailable):
            resolve_record(reference,self.actor)
        grant=self.grant(group=self.group)
        self.assertEqual(resolve_record(reference,self.actor).pk,self.application.pk)
        self.assertEqual(describe_record(reference,self.actor)['record_ref'],reference)
        self.assertTrue(launch_record(reference,self.actor)['url'].startswith('/origination/'))
        AccessGrant.objects.filter(pk=grant.pk).update(active=False)
        with self.assertRaises(RecordUnavailable):
            launch_record(reference,self.actor)

    def test_all_eight_adapters_are_registered_and_references_are_allowlisted(self):
        self.assertEqual(len(RECORD_ADAPTERS),8)
        for adapter in RECORD_ADAPTERS.values():
            with self.subTest(app=adapter.app):
                model=apps.get_model(adapter.model_label)
                reference=adapter.generate(model(pk=uuid4()))
                self.assertEqual(parse_reference(reference)[0],adapter)
                with self.assertRaises(RecordUnavailable):
                    resolve_record(reference,self.actor)
                with self.assertRaises(RecordUnavailable):
                    resolve_record(reference,None)
        reference=record_reference(self.application)
        for invalid in [dict(reference,app='auth'),dict(reference,version=True),dict(reference,version=2),
                        dict(reference,id='invalid'),dict(reference,phone='synthetic')]:
            with self.assertRaises(RecordUnavailable):
                parse_reference(invalid)

    def test_every_adapter_resolves_existing_records_and_denies_revoked_access(self):
        from core.models import (
            RawMessage, ProcessedMessage, ParsedMessage, TatTrackerCase, SpinCreditRequest,
            JawabuFarmerMaster, JawabuFarmerUploadBatch, FcaImportRecord, OrderApprovalUpdate,
        )
        raw=RawMessage.objects.create(telegram_message_id='synthetic-reference-message')
        processed=ProcessedMessage.objects.create(raw_message=raw,message_hash='synthetic-reference-hash')
        records=[
            self.application,
            ParsedMessage.objects.create(processed_message=processed,message_id='synthetic-complaint',complaint_status='Pending'),
            TatTrackerCase.objects.create(case_id='TAT-SYNTHETIC-REF',data_mode='production',product_key='synthetic'),
            SpinCreditRequest.objects.create(data_mode='production',source_message_hash='synthetic-spin-ref'),
            JawabuFarmerMaster.objects.create(external_id='synthetic-portal-reference'),
            JawabuFarmerUploadBatch.objects.create(group_id='synthetic-intake-reference'),
            FcaImportRecord.objects.create(group_id='synthetic-fca-reference'),
            OrderApprovalUpdate.objects.create(group_id='synthetic-order-reference'),
        ]
        grants=[self.grant(workflow=workflow,role='IT',branch='') for workflow in
                {'loan_origination','jawabu_portal','complaint_cases','tat_tracker','spin_credit_analysis'}]
        for record in records:
            reference=record_reference(record)
            with self.subTest(app=reference['app']):
                self.assertEqual(resolve_record(reference,self.actor).pk,record.pk)
                self.assertEqual(describe_record(reference,self.actor)['record_ref'],reference)
                launch=launch_record(reference,self.actor)
                self.assertTrue(launch['url'].startswith('/'))
                self.assertNotIn('token',launch['url'])
                self.assertNotIn('national_id',launch['url'])
        AccessGrant.objects.filter(pk__in=[grant.pk for grant in grants]).update(active=False)
        for record in records:
            with self.assertRaises(RecordUnavailable):
                resolve_record(record_reference(record),self.actor)
