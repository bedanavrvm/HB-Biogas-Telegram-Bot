from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

from core.management.commands.seed_origination_packet_demo import (
    PRODUCT_KEY,
    SUPPORTING_DOCUMENT_KEY,
    _synthetic_pdf,
)
from core.models import (
    OriginationDataField,
    OriginationDocumentTemplate,
    OriginationProductDefinition,
    OriginationProductDocumentAssignment,
)
from core.services.loan_origination import create_application


@override_settings(GOOGLE_DRIVE_MEDIA_FOLDER_ID='synthetic-drive-root')
class OriginationPacketDemoSeedCommandTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser(
            'demo-seed-admin', 'demo-seed@example.test', 'password',
        )

    def test_dry_run_does_not_create_records(self):
        output = StringIO()

        call_command(
            'seed_origination_packet_demo', '--actor', self.actor.username,
            stdout=output,
        )

        self.assertIn('Dry run', output.getvalue())
        self.assertFalse(OriginationProductDefinition.objects.filter(product_key=PRODUCT_KEY).exists())

    @patch('core.services.compliance_audit.record_event')
    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_apply_creates_published_packet_and_is_repeatable(self, storage_class, _audit):
        storage = storage_class.return_value
        uploaded = {}

        def upload(pdf_data, filename, *_args, **_kwargs):
            file_id = 'drive-demo-guarantor' if 'guarantor' in filename else 'drive-demo-primary'
            uploaded[file_id] = pdf_data
            return file_id, f'https://drive.test/{file_id}'

        storage.upload.side_effect = upload
        storage.download.side_effect = lambda file_id: uploaded[file_id]
        output = StringIO()

        call_command(
            'seed_origination_packet_demo', '--actor', self.actor.username,
            '--apply', stdout=output,
        )

        product = OriginationProductDefinition.objects.get(product_key=PRODUCT_KEY)
        self.assertTrue(product.is_active)
        self.assertEqual(product.lifecycle_status, product.STATUS_PUBLISHED)
        self.assertEqual(len(product.form_schema['fields']), 2)
        self.assertEqual(OriginationDataField.objects.filter(key__startswith='demo_').count(), 4)
        supporting = OriginationDocumentTemplate.objects.get(document_key=SUPPORTING_DOCUMENT_KEY)
        self.assertEqual(supporting.status, supporting.STATUS_ACTIVE)
        self.assertEqual(len(supporting.form_schema['fields']), 4)
        assignment = OriginationProductDocumentAssignment.objects.get(
            product_definition=product, document_key=SUPPORTING_DOCUMENT_KEY,
        )
        self.assertEqual(
            assignment.version_policy,
            OriginationProductDocumentAssignment.VERSION_LATEST_COMPATIBLE,
        )
        application, replayed = create_application(
            product_key=PRODUCT_KEY, officer=self.actor,
            branch='Demo Branch', client_request_id='demo-seed-application',
        )
        self.assertFalse(replayed)
        self.assertEqual(application.packet_documents.count(), 2)
        support_document = application.packet_documents.get(document_key=SUPPORTING_DOCUMENT_KEY)
        self.assertTrue(support_document.selected)
        self.assertEqual(len(support_document.schema_snapshot['fields']), 4)
        self.assertIn('supporting document', output.getvalue())

        second_output = StringIO()
        call_command(
            'seed_origination_packet_demo', '--actor', self.actor.username,
            '--apply', stdout=second_output,
        )
        self.assertIn('Demo already exists', second_output.getvalue())
        self.assertEqual(OriginationProductDefinition.objects.filter(product_key=PRODUCT_KEY).count(), 1)
