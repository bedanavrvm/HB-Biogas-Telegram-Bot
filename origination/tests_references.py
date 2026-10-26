"""Short display references must not rewrite captured application identities."""
from django.db import transaction
from django.test import TestCase

from origination import tests_document_management as fixtures
from origination.services.loan_origination import create_application, serialize_application


class ApplicationReferenceTests(TestCase):
    setUp = fixtures.ManageDocumentsTests.setUp
    _template = fixtures.ManageDocumentsTests._template
    application = fixtures.ManageDocumentsTests.application

    def test_create_replay_and_next_application_allocate_once(self):
        from origination.models import OriginationApplicationReferenceSequence
        first = self.application()
        number = OriginationApplicationReferenceSequence.objects.get(pk=1).last_number
        self.assertEqual(first.reference_number, f'ORG-{number}')
        self.assertEqual(first.display_reference, first.reference_number)
        args = dict(product_key=self.definition.product_key, officer=self.officer,
            branch=self.branch.name, primary_template_id=self.main.pk, supporting_template_ids=[],
            expected_catalogue_revision=self.catalogue['catalogue_revision'])
        replay, replayed = create_application(**args, client_request_id='manage-create')
        self.assertTrue(replayed)
        self.assertEqual(replay.pk, first.pk)
        self.assertEqual(first.schema_snapshot['form_projection_version'], 2)
        self.assertEqual(OriginationApplicationReferenceSequence.objects.get(pk=1).last_number, number)
        second, _ = create_application(**args, client_request_id='another-application')
        self.assertEqual(second.display_reference, f'ORG-{number + 1}')

    def test_cancelled_reference_is_never_reused_and_rollback_does_not_allocate(self):
        from origination.services.application_references import next_application_reference
        first = self.application()
        first.status = 'cancelled'; first.save(update_fields=['status'])
        with transaction.atomic():
            next_ref = next_application_reference()
            transaction.set_rollback(True)
        with transaction.atomic():
            self.assertEqual(next_application_reference(), next_ref)
        self.assertNotEqual(next_ref, first.display_reference)

    def test_api_keeps_original_reference_and_adds_display_alias(self):
        app = self.application()
        app.reference_number = 'ORG-2026-LEGACY'
        app.save(update_fields=['reference_number'])
        payload = serialize_application(app, include_payload=False, actor=self.officer)
        self.assertEqual(payload['reference_number'], 'ORG-2026-LEGACY')
        self.assertEqual(payload['display_reference'], app.display_reference)

    def test_backfill_preserves_bytes_timestamps_and_existing_short_references(self):
        from importlib import import_module
        from django.apps import apps
        from django.db import connection
        from origination.models import LoanOriginationApplication, OriginationApplicationReferenceSequence
        app = self.application()
        app.reference_number = 'ORG-2026-LEGACY'
        app.display_reference = None
        app.save(update_fields=['reference_number', 'display_reference'])
        short = LoanOriginationApplication.objects.create(product_definition=app.product_definition,
            officer=self.officer, reference_number='ORG-30', schema_snapshot={'retained': True},
            template_configuration_snapshot={'unaltered': True})
        original = LoanOriginationApplication.objects.filter(pk=app.pk).values().get()
        migrate = import_module('origination.migrations.0012_application_display_references').assign_references
        editor = type('Editor', (), {'connection': connection})()
        migrate(apps, editor)
        app.refresh_from_db(); short.refresh_from_db()
        self.assertEqual(app.display_reference, 'ORG-31')
        self.assertEqual(short.display_reference, 'ORG-30')
        after = LoanOriginationApplication.objects.filter(pk=app.pk).values().get()
        self.assertEqual({key: value for key, value in after.items() if key != 'display_reference'},
                         {key: value for key, value in original.items() if key != 'display_reference'})
        migrate(apps, editor)
        self.assertEqual(OriginationApplicationReferenceSequence.objects.get(pk=1).last_number, 31)

    def test_search_accepts_friendly_and_historical_reference(self):
        import json
        from django.test import RequestFactory
        from origination.views import portal_origination_applications
        from core.services.telegram_identity import user_access
        app = self.application()
        app.reference_number = 'ORG-2026-LEGACY'
        app.save(update_fields=['reference_number'])
        for reference in [app.display_reference, app.reference_number]:
            request = RequestFactory().get('/', {'q': reference, 'queue': 'applications'})
            from core.models import AccessGrant, WorkflowRoleCapability
            for capability in ['origination.view', 'origination.create']:
                WorkflowRoleCapability.objects.update_or_create(workflow='loan_origination', role='JBL_OFFICER',
                    capability_key=capability, defaults={'effect': 'allow'})
            AccessGrant.objects.get_or_create(user=self.officer, workflow='loan_origination', role='JBL_OFFICER',
                branch=self.branch.name)
            request.origination_user = self.officer
            request.origination_access = user_access(self.officer, 'loan_origination')
            response = portal_origination_applications(request)
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual([row['id'] for row in json.loads(response.content)['applications']], [str(app.pk)])


from unittest import skipUnless
from django.db import connection, close_old_connections
from django.test import TransactionTestCase


@skipUnless(connection.vendor == 'postgresql', 'Reference row locking requires PostgreSQL.')
class ApplicationReferenceConcurrencyTests(TransactionTestCase):
    def test_parallel_allocations_are_distinct(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from origination.models import OriginationApplicationReferenceSequence
        from origination.services.application_references import next_application_reference
        OriginationApplicationReferenceSequence.objects.get_or_create(pk=1)
        barrier = Barrier(2)
        def allocate(_):
            close_old_connections()
            try:
                barrier.wait(timeout=15)
                with transaction.atomic():
                    return next_application_reference()
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            references = list(pool.map(allocate, range(2)))
        self.assertEqual(len(set(references)), 2)
