import json
import uuid

from django.contrib.auth import get_user_model
from django.core import signing
from django.test import TestCase
from django.urls import reverse

from core.models import (
    OperationalLocation,
    OriginationDocumentTemplate,
    OriginationProductDefinition,
    Product,
    ProductAvailability,
    ProductVersionEvent,
)
from core.services.origination_setup import (
    OriginationSetupConflict,
    assert_expected_state,
    make_return_token,
    resolve_return_token,
    setup_readiness,
    step_tokens,
)


class OriginationSetupWorkspaceTests(TestCase):
    def setUp(self):
        self.superuser = get_user_model().objects.create_superuser(
            username='setup-admin', email='setup@example.test', password='secret',
        )
        self.staff = get_user_model().objects.create_user(
            username='setup-staff', password='secret', is_staff=True,
        )
        self.branch = OperationalLocation.objects.create(
            location_type='branch', name='Setup Branch', code='SETUP-BRANCH',
        )
        self.dashboard_url = reverse('admin:core_origination_setup_dashboard')

    def test_every_setup_route_requires_active_superuser(self):
        self.client.force_login(self.staff)
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 403)

    def test_dashboard_renders_guided_workspace(self):
        self.client.force_login(self.superuser)
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Product setup workspace')
        self.assertContains(response, 'Start a product')
        self.assertContains(response, 'osw-admin-page')
        self.assertContains(response, 'admin/origination_setup_layout.css')

    def test_start_is_idempotent_and_creates_durable_draft(self):
        self.client.force_login(self.superuser)
        request_id = str(uuid.uuid4())
        payload = {
            'request_id': request_id,
            'name': 'Guided Loan',
            'code': 'guided_loan',
            'category': 'Credit',
            'description': 'Created through the guided setup.',
            'sort_order': 10,
            'branches': [self.branch.pk],
        }
        start_url = reverse('admin:core_origination_setup_start')
        first = self.client.post(start_url, payload)
        second = self.client.post(start_url, payload)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(Product.objects.filter(code='guided_loan').count(), 1)
        definition = OriginationProductDefinition.objects.get(product_key='guided_loan')
        self.assertEqual(definition.lifecycle_status, definition.STATUS_DRAFT)
        self.assertFalse(definition.is_active)
        self.assertTrue(ProductAvailability.objects.filter(
            product=definition.product_version.product,
            branch=self.branch,
            workflow='loan_origination', channel='telegram', active=True,
        ).exists())
        self.assertEqual(ProductVersionEvent.objects.filter(
            action='setup_started', metadata__request_id=request_id,
        ).count(), 1)

    def test_changed_state_is_rejected_and_marks_completed_step_stale(self):
        self.client.force_login(self.superuser)
        self.client.post(reverse('admin:core_origination_setup_start'), {
            'request_id': str(uuid.uuid4()), 'name': 'Conflict Loan',
            'code': 'conflict_loan', 'category': '', 'description': '',
            'sort_order': 0, 'branches': [self.branch.pk],
        })
        definition = OriginationProductDefinition.objects.get(product_key='conflict_loan')
        expected = step_tokens(definition)
        product = definition.product_version.product
        product.description = 'Changed in another tab.'
        product.save()
        with self.assertRaises(OriginationSetupConflict):
            assert_expected_state(definition=definition, expected_tokens=expected)
        identity = next(
            item for item in setup_readiness(definition) if item['key'] == 'identity'
        )
        self.assertEqual(identity['status'], 'stale')

    def test_stale_admin_write_returns_409_without_overwriting(self):
        self.client.force_login(self.superuser)
        self.client.post(reverse('admin:core_origination_setup_start'), {
            'request_id': str(uuid.uuid4()), 'name': 'Concurrent Loan',
            'code': 'concurrent_loan', 'category': '', 'description': 'Original',
            'sort_order': 0, 'branches': [self.branch.pk],
        })
        definition = OriginationProductDefinition.objects.get(product_key='concurrent_loan')
        expected = step_tokens(definition)
        product = definition.product_version.product
        product.description = 'Newer value'
        product.save()
        response = self.client.post(reverse(
            'admin:core_origination_setup_step', args=[definition.pk, 'identity'],
        ), {
            'expected_tokens': json.dumps(expected), 'request_id': str(uuid.uuid4()),
            'name': product.name, 'code': product.code, 'category': product.category,
            'description': 'My stale value', 'sort_order': product.sort_order,
            'branches': [self.branch.pk],
        })
        self.assertEqual(response.status_code, 409)
        product.refresh_from_db()
        self.assertEqual(product.description, 'Newer value')

    def test_signed_calibration_return_token_is_bounded_and_tamper_safe(self):
        definition_id = uuid.uuid4()
        token = make_return_token(definition_id=definition_id, step_key='calibration')
        self.assertEqual(resolve_return_token(token), {
            'definition_id': str(definition_id), 'step_key': 'calibration',
        })
        with self.assertRaises(signing.BadSignature):
            resolve_return_token(token + 'tampered')

    def test_calibration_accepts_only_signed_internal_workspace_return(self):
        self.client.force_login(self.superuser)
        self.client.post(reverse('admin:core_origination_setup_start'), {
            'request_id': str(uuid.uuid4()), 'name': 'Return Loan',
            'code': 'return_loan', 'category': '', 'description': '',
            'sort_order': 0, 'branches': [self.branch.pk],
        })
        definition = OriginationProductDefinition.objects.get(product_key='return_loan')
        template = OriginationDocumentTemplate.objects.create(
            product_definition=definition, document_key='primary',
            document_role='primary', inclusion_mode='required',
            document_type=definition.document_type, name='Return LAF', version=1,
            source_filename='return.pdf', source_sha256='a' * 64,
            source_byte_size=100, page_count=1, placement_config={},
            drive_file_id='test-drive-file', created_by=self.superuser,
        )
        token = make_return_token(definition_id=definition.pk)
        response = self.client.get(
            reverse('admin:core_originationdocumenttemplate_calibrate', args=[template.pk]),
            {'setup_return': token},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['calibration_back_url'], reverse(
            'admin:core_origination_setup_step', args=[definition.pk, 'calibration'],
        ))
        invalid = self.client.get(
            reverse('admin:core_originationdocumenttemplate_calibrate', args=[template.pk]),
            {'setup_return': token + 'tampered'},
        )
        self.assertEqual(
            invalid.context['calibration_back_url'],
            reverse('admin:core_origination_setup_dashboard'),
        )
        self.assertContains(invalid, 'invalid or expired')

    def test_terms_step_posts_expected_state_contract(self):
        self.client.force_login(self.superuser)
        self.client.post(reverse('admin:core_origination_setup_start'), {
            'request_id': str(uuid.uuid4()), 'name': 'Terms Loan',
            'code': 'terms_loan', 'category': '', 'description': '',
            'sort_order': 0, 'branches': [self.branch.pk],
        })
        definition = OriginationProductDefinition.objects.get(product_key='terms_loan')
        response = self.client.get(reverse(
            'admin:core_origination_setup_step', args=[definition.pk, 'terms'],
        ))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="expected_tokens"')
        self.assertEqual(
            json.loads(response.context['expected_tokens']), step_tokens(definition),
        )

    def test_terms_can_save_without_forcing_optional_repeatable_rows(self):
        self.client.force_login(self.superuser)
        self.client.post(reverse('admin:core_origination_setup_start'), {
            'request_id': str(uuid.uuid4()), 'name': 'Optional Rows Loan',
            'code': 'optional_rows_loan', 'category': '', 'description': '',
            'sort_order': 0, 'branches': [self.branch.pk],
        })
        definition = OriginationProductDefinition.objects.get(product_key='optional_rows_loan')
        version = definition.product_version
        payload = {
            'expected_tokens': json.dumps(step_tokens(definition), sort_keys=True),
            'request_id': str(uuid.uuid4()),
            'currency': version.currency, 'min_amount': '1000', 'max_amount': '50000',
            'min_tenor': '1', 'max_tenor': '12', 'tenor_unit': version.tenor_unit,
            'interest_method': version.interest_method, 'interest_rate': '10',
            'interest_rate_period': version.interest_rate_period,
            'repayment_frequency': version.repayment_frequency,
            'quote_amount_field_key': version.quote_amount_field_key,
            'quote_tenor_field_key': version.quote_tenor_field_key,
            'effective_from': version.effective_from.isoformat(), 'effective_to': '',
            'fees-TOTAL_FORMS': '1', 'fees-INITIAL_FORMS': '0',
            'fees-MIN_NUM_FORMS': '0', 'fees-MAX_NUM_FORMS': '1000',
            'fees-0-position': '0', 'fees-0-fee_type': 'fixed',
            'fees-0-calculation_basis': 'principal',
            'fees-0-collection_mode': 'upfront', 'fees-0-mandatory': 'on',
            'requirements-TOTAL_FORMS': '1', 'requirements-INITIAL_FORMS': '0',
            'requirements-MIN_NUM_FORMS': '0', 'requirements-MAX_NUM_FORMS': '1000',
            'requirements-0-position': '0', 'requirements-0-required': 'on',
            'requirements-0-active': 'on',
            'attributes-TOTAL_FORMS': '1', 'attributes-INITIAL_FORMS': '0',
            'attributes-MIN_NUM_FORMS': '0', 'attributes-MAX_NUM_FORMS': '1000',
            'attributes-0-position': '0',
        }
        response = self.client.post(reverse(
            'admin:core_origination_setup_step', args=[definition.pk, 'terms'],
        ), payload)
        self.assertEqual(response.status_code, 302)
        replay = self.client.post(reverse(
            'admin:core_origination_setup_step', args=[definition.pk, 'terms'],
        ), payload)
        self.assertEqual(replay.status_code, 302)
        version.refresh_from_db()
        self.assertEqual(str(version.min_amount), '1000.00')
        self.assertEqual(version.fees.count(), 0)
        self.assertEqual(version.events.filter(
            action='setup_step_completed', metadata__step_key='terms',
        ).count(), 1)
