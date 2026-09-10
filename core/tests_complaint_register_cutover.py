import importlib
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from django.apps import apps

from core.models import (
    AccessControlChangeRequest,
    CaseUpdate,
    ComplaintCaseImportBatch,
    ComplaintCaseImportItem,
    ComplaintCaseControl,
    ComplaintCategory,
    ComplaintCategoryAlias,
    GroupSheetConfiguration,
    ParsedMessage,
    ProcessedMessage,
    RawMessage,
    WorkflowRoleCapability,
)
from core.services.sheet_schema import COMPLAINT_REGISTER_FIELD_HEADERS, SheetSchema
from core.services.sheets import GoogleSheetsService
from core.services.group_config import GroupRegistry


EXPECTED_HEADERS = [
    '#', 'Complaint ID', 'Date Reported', 'Status', 'Customer Name',
    'Customer National ID', 'Primary Phone Number', 'Secondary Phone No',
    'County', 'Constituency', 'Village', 'Branch', 'JBL Reported By',
    'Complaint Type', 'Complaint Description', 'GPS Link',
    'Resolution Details', 'Date Resolved', 'Days Open', 'Resolution History',
]


class ComplaintRegisterCutoverTests(TestCase):
    def setUp(self):
        raw = RawMessage.objects.create(
            telegram_message_id='internal-uuid-like-id', content='private source',
        )
        processed = ProcessedMessage.objects.create(
            message_hash='complaint-register-cutover-hash', raw_message=raw,
        )
        self.case = ParsedMessage.objects.create(
            processed_message=processed,
            message_id='internal-uuid-like-id',
            timestamp=timezone.now(),
            sender='Officer Example',
            raw_message='private source',
            customer_name='Example Customer',
            customer_phone='254700000001',
            secondary_phone='254700000002',
            customer_id='00123456',
            county='Nakuru County',
            sub_county='Nakuru East',
            village='Test Village',
            branch_region='Nakuru',
            complaint_category='Product issue',
            complaint_description='The unit requires attention.',
            complaint_status='Reopened',
            resolution_details='First resolution did not hold.',
            group_id='-100-cutover',
        )
        ComplaintCaseControl.objects.create(
            parsed_message=self.case, reference_number='CMP-897',
        )
        CaseUpdate.objects.create(
            parsed_message=self.case, group_id=self.case.group_id,
            updated_by='Resolver One', old_status='Open', new_status='Closed',
            resolution_text='Initial repair completed.',
        )
        CaseUpdate.objects.create(
            parsed_message=self.case, group_id=self.case.group_id,
            updated_by='Manager One', old_status='Closed', new_status='Reopened',
            resolution_text='Customer reported the issue again.',
        )

    def test_v2_schema_is_fixed_and_uses_complaint_id_as_row_key(self):
        schema = SheetSchema.from_config({
            'schema_version': 2,
            'header_row': 1,
            'data_start_row': 2,
            'row_key_field': 'message_id',
            'columns': ['unsafe legacy override'],
            'field_headers': {'complaint_id': 'Unsafe override'},
        })

        self.assertEqual(schema.columns, EXPECTED_HEADERS)
        self.assertEqual(schema.header_row, 1)
        self.assertEqual(schema.row_key_field, 'complaint_id')
        self.assertTrue(schema.strict_headers)
        self.assertNotIn('Days Open', schema.formula_headers)
        self.assertIn('Days Open', schema.bot_writable_headers)
        self.assertIn('Days Open', schema.case_update_headers)

    def test_projection_has_twenty_columns_and_full_resolution_history(self):
        schema = SheetSchema.from_config({'schema_version': 2})
        row = schema.row_for_message(self.case)

        self.assertEqual(len(row), 20)
        self.assertEqual(row[1], 'CMP-897')
        self.assertEqual(row[3], 'REOPENED')
        self.assertEqual(row[6], '254700000001')
        self.assertEqual(row[7], '254700000002')
        self.assertEqual(row[8:12], ['Nakuru County', 'Nakuru East', 'Test Village', 'Nakuru'])
        self.assertEqual(row[12], 'Officer Example')
        self.assertEqual(row[18], 0)
        self.assertIn('Resolver One - CLOSED: Initial repair completed.', row[19])
        self.assertIn('Manager One - REOPENED: Customer reported the issue again.', row[19])
        self.assertNotIn('internal-uuid-like-id', row)
        self.assertNotIn('private source', row)

    def test_strict_sheet_contract_accepts_only_exact_row_one_headers(self):
        service = GoogleSheetsService(
            sheet_id='test-sheet', sheet_name='Complaints',
            sheet_schema={'schema_version': 2, 'header_row': 1},
        )
        sheet = Mock()
        sheet.row_values.return_value = EXPECTED_HEADERS
        with patch.object(service, 'is_available', return_value=True), patch.object(service, '_sheet', sheet):
            self.assertEqual(service.validate_sheet_structure(), (True, ''))

            sheet.row_values.return_value = EXPECTED_HEADERS + ['Legacy Extra Column']
            valid, message = service.validate_sheet_structure()
            self.assertFalse(valid)
            self.assertIn('exactly these columns in order', message)

            sheet.row_values.return_value = [EXPECTED_HEADERS[1], EXPECTED_HEADERS[0], *EXPECTED_HEADERS[2:]]
            valid, message = service.validate_sheet_structure()
            self.assertFalse(valid)
            self.assertIn('exactly these columns in order', message)

    def test_fixed_header_mapping_matches_the_requested_labels(self):
        self.assertEqual(list(COMPLAINT_REGISTER_FIELD_HEADERS.values()), EXPECTED_HEADERS)

    def test_cutover_cancels_inflight_imports_and_preserves_reopen_state(self):
        prepare_cutover = importlib.import_module(
            'core.migrations.0162_complaint_register_cutover'
        ).prepare_cutover

        config = GroupSheetConfiguration.objects.create(
            group_id='-100-migration', sheet_id='sheet', sheet_name='Complaints',
            workflow={'type': 'case'}, sheet_schema={'columns': ['legacy']},
        )
        batch = ComplaintCaseImportBatch.objects.create(
            group_id=config.group_id, source_telegram_message_id='archived-source',
            source_hash='a' * 64, status=ComplaintCaseImportBatch.STATUS_RUNNING,
        )
        item = ComplaintCaseImportItem.objects.create(
            batch=batch, source_index=0, status=ComplaintCaseImportItem.STATUS_RUNNING,
        )
        self.case.complaint_status = 'Open'
        self.case.save(update_fields=['complaint_status'])
        CaseUpdate.objects.create(
            parsed_message=self.case, group_id=self.case.group_id,
            old_status='Closed', new_status='Open', resolution_text='Legacy reopen.',
        )

        prepare_cutover(apps, None)

        batch.refresh_from_db()
        item.refresh_from_db()
        config.refresh_from_db()
        self.case.refresh_from_db()
        self.assertEqual(batch.status, ComplaintCaseImportBatch.STATUS_CANCELLED)
        self.assertEqual(item.status, ComplaintCaseImportItem.STATUS_CANCELLED)
        self.assertEqual(batch.last_error_code, 'complaint_import_retired')
        self.assertEqual(item.last_error_code, 'complaint_import_retired')
        self.assertIsNotNone(batch.completed_at)
        self.assertIsNotNone(item.completed_at)
        self.assertEqual(config.sheet_schema['data_start_row'], 2)
        self.assertEqual(config.sheet_schema['row_key_field'], 'complaint_id')
        self.assertEqual(config.workflow['header_row'], 1)
        self.assertEqual(self.case.complaint_status, 'Reopened')

    def test_role_and_category_migration_is_idempotent_and_cancels_conflicting_it_request(self):
        apply_policy = importlib.import_module(
            'core.migrations.0163_it_override_tat_roles_complaint_categories'
        ).apply_policy_and_catalogue
        user = get_user_model().objects.create_user(username='policy-migration-user')
        request = AccessControlChangeRequest.objects.create(
            change_type=AccessControlChangeRequest.TYPE_CAPABILITY,
            workflow='complaint_cases', role='IT', target_roles=['IT'],
            reason='Old editable IT policy.', status=AccessControlChangeRequest.STATUS_PENDING,
            requested_by=user,
        )

        apply_policy(apps, None)
        apply_policy(apps, None)

        request.refresh_from_db()
        self.assertEqual(request.status, AccessControlChangeRequest.STATUS_CANCELLED)
        self.assertEqual(
            set(WorkflowRoleCapability.objects.filter(
                workflow='tat_tracker', capability_key='tat.case.create', effect='allow',
            ).values_list('role', flat=True)),
            {'BRO', 'BUSINESS_ADMIN', 'IT'},
        )
        self.assertEqual(
            set(WorkflowRoleCapability.objects.filter(
                workflow='tat_tracker', capability_key='tat.reports.view', effect='allow',
            ).values_list('role', flat=True)),
            {'MANAGEMENT', 'IT'},
        )
        self.assertTrue(ComplaintCategory.objects.filter(label='Payments & Accounts', active=True).exists())
        self.assertEqual(
            ComplaintCategoryAlias.objects.get(normalized_alias='installation delay').category.label,
            'Installation',
        )

    @override_settings(TELEGRAM_BOT_USERNAME='biogas_bot')
    @patch('core.api.views._process_single_message')
    @patch('core.services.case_updates.handle_case_status_reply')
    def test_configured_complaint_group_accepts_intake_and_status_only_in_miniapp(
        self, status_reply, process_single,
    ):
        from core.api.views import _process_telegram_message

        GroupSheetConfiguration.objects.create(
            group_id='-100777', sheet_id='sheet', sheet_name='Complaints',
            workflow={'type': 'case'},
        )
        GroupRegistry._instance = None
        base = {
            'from': {'id': 800, 'first_name': 'Officer'},
            'chat': {'id': -100777, 'type': 'supergroup'},
            'date': 1711123456,
        }
        created = _process_telegram_message({
            **base, 'message_id': 1,
            'text': '@biogas_bot CUSTOMER COMPLAINT: Unit is not working.',
        })
        updated = _process_telegram_message({
            **base, 'message_id': 2, 'text': 'Status: closed - repaired',
            'reply_to_message': {'message_id': 1},
        })
        imported = _process_telegram_message({
            **base, 'message_id': 3, 'text': '@biogas_bot /batch export text',
        })

        self.assertIn('Complaint Cases Mini App', created['reply_text'])
        self.assertIn('Complaint Cases Mini App', updated['reply_text'])
        self.assertIn('retired', imported['reply_text'])
        process_single.assert_not_called()
        status_reply.assert_not_called()
