from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from core.models import (
    LoanOriginationApplication,
    OriginationApplicationEvent,
    OriginationProductDefinition,
)
from core.services.loan_origination import (
    OriginationConflict,
    OriginationError,
    create_application,
    prepare_signing_package,
    review_application,
    save_application_fields,
    submit_for_review,
)


class LoanOriginationServiceTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.officer = user_model.objects.create_user(username='origination-officer')
        self.reviewer = user_model.objects.create_user(username='origination-reviewer')
        self.product = OriginationProductDefinition.objects.create(
            product_key='pilot-product',
            name='Synthetic pilot product',
            version=1,
            form_schema={'fields': [
                {'key': 'customer_name', 'type': 'text', 'required': True},
                {'key': 'consent', 'type': 'boolean', 'required': True},
            ]},
            signer_rules=[{'role': 'customer'}, {'role': 'officer'}],
            document_type='synthetic_loan_agreement',
            is_active=True,
        )
        self.audit_patch = patch('core.services.compliance_audit.record_event')
        self.audit_patch.start()
        self.addCleanup(self.audit_patch.stop)

    def test_active_product_requires_complete_contract(self):
        definition = OriginationProductDefinition(
            product_key='invalid', name='Invalid', version=1, is_active=True,
            form_schema={}, signer_rules=[], document_type='',
        )
        with self.assertRaises(ValidationError):
            definition.full_clean()

    def test_create_and_write_requests_are_idempotent_and_revision_checked(self):
        application, replayed = create_application(
            product_key=self.product.product_key,
            officer=self.officer,
            branch='Synthetic Branch',
            client_request_id='create-1',
        )
        repeated, replayed_again = create_application(
            product_key=self.product.product_key,
            officer=self.officer,
            branch='Another Branch',
            client_request_id='create-1',
        )
        self.assertFalse(replayed)
        self.assertTrue(replayed_again)
        self.assertEqual(repeated.pk, application.pk)

        saved = save_application_fields(
            application_id=application.pk,
            actor=self.officer,
            payload={'customer_name': 'Synthetic Customer', 'consent': True},
            expected_revision=1,
            request_id='save-1',
        )
        replayed_save = save_application_fields(
            application_id=application.pk,
            actor=self.officer,
            payload={'customer_name': 'Changed', 'consent': False},
            expected_revision=1,
            request_id='save-1',
        )
        self.assertEqual(replayed_save.revision, saved.revision)
        self.assertEqual(replayed_save.form_payload, saved.form_payload)
        with self.assertRaises(OriginationConflict):
            save_application_fields(
                application_id=application.pk,
                actor=self.officer,
                payload=saved.form_payload,
                expected_revision=1,
                request_id='save-stale',
            )

    def test_review_is_maker_checker_and_signing_preparation_has_no_dispatch(self):
        application, _ = create_application(
            product_key=self.product.product_key,
            officer=self.officer,
            branch='Synthetic Branch',
            client_request_id='create-flow',
        )
        application = save_application_fields(
            application_id=application.pk,
            actor=self.officer,
            payload={'customer_name': 'Synthetic Customer', 'consent': True},
            expected_revision=1,
            request_id='save-flow',
        )
        application = submit_for_review(
            application_id=application.pk,
            actor=self.officer,
            expected_revision=application.revision,
            request_id='submit-flow',
        )
        with self.assertRaises(OriginationError):
            review_application(
                application_id=application.pk,
                actor=self.officer,
                expected_revision=application.revision,
                request_id='self-review',
                decision='approve',
            )
        application = review_application(
            application_id=application.pk,
            actor=self.reviewer,
            expected_revision=application.revision,
            request_id='review-flow',
            decision='approve',
        )
        package, replayed = prepare_signing_package(
            application_id=application.pk,
            actor=self.reviewer,
            expected_revision=application.revision,
            request_id='signing-flow',
        )
        repeated, replayed_again = prepare_signing_package(
            application_id=application.pk,
            actor=self.reviewer,
            expected_revision=application.revision + 1,
            request_id='signing-flow',
        )
        application.refresh_from_db()
        self.assertFalse(replayed)
        self.assertTrue(replayed_again)
        self.assertEqual(repeated.pk, package.pk)
        self.assertEqual(application.status, LoanOriginationApplication.STATUS_SIGNING_PENDING)
        self.assertEqual(OriginationApplicationEvent.objects.filter(application=application).count(), 5)

    def test_non_approval_review_requires_reason(self):
        application, _ = create_application(
            product_key=self.product.product_key,
            officer=self.officer,
            branch='Synthetic Branch',
            client_request_id='create-correction',
        )
        application.form_payload = {'customer_name': 'Synthetic Customer', 'consent': True}
        application.status = LoanOriginationApplication.STATUS_READY_FOR_REVIEW
        application.save(update_fields=['form_payload', 'status'])
        with self.assertRaises(OriginationError):
            review_application(
                application_id=application.pk,
                actor=self.reviewer,
                expected_revision=application.revision,
                request_id='correction-review',
                decision='request_correction',
            )
