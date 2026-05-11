"""
Tests for Google Sheets validation features.

Tests the Sheet Structure Detection and Dropdown Validation safety features.
"""
import logging
from django.test import TestCase
from unittest.mock import Mock, patch, MagicMock
from core.services.sheets import GoogleSheetsService
from core.models import ParsedMessage

logger = logging.getLogger(__name__)


class GoogleSheetsValidationTests(TestCase):
    """Test Google Sheets validation features."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.service = GoogleSheetsService.get_instance()
        
        # Expected schema - 21 columns
        self.expected_columns = [
            'Complaint ID', 'message_id', 'Date Reported', 'Customer Name',
            'Customer ID / Account', 'Phone Number', 'JBL Reported By', 'Branch / Region',
            'Complaint Category', 'Complaint Description', 'raw_message', 'gps_link',
            'image_flag', 'source', 'Loan Status', 'Loan at Risk', 'Risk Level',
            'Status', 'Resolution Details', 'Date Resolved', 'Days Open'
        ]
    
    def test_validate_sheet_structure_success(self):
        """Test successful sheet structure validation."""
        # Mock gspread sheet
        mock_sheet = Mock()
        mock_sheet.row_values = Mock(return_value=self.expected_columns)
        
        # Inject mock
        with patch.object(self.service, 'is_available', return_value=True):
            with patch.object(self.service, '_sheet', mock_sheet):
                is_valid, error_msg = self.service.validate_sheet_structure()
        
        self.assertTrue(is_valid, f"Expected valid structure, got error: {error_msg}")
        self.assertEqual(error_msg, "")
    
    def test_validate_sheet_structure_wrong_column_count(self):
        """Test validation fails with wrong column count."""
        # Only 20 columns instead of 21
        wrong_columns = self.expected_columns[:-1]
        
        mock_sheet = Mock()
        mock_sheet.row_values = Mock(return_value=wrong_columns)
        
        with patch.object(self.service, 'is_available', return_value=True):
            with patch.object(self.service, '_sheet', mock_sheet):
                is_valid, error_msg = self.service.validate_sheet_structure()
        
        self.assertFalse(is_valid, "Expected validation to fail with wrong column count")
        self.assertIn("Missing required sheet column", error_msg)
        self.assertIn("Days Open", error_msg)
    
    def test_validate_sheet_structure_wrong_column_name(self):
        """Test validation fails with wrong column name."""
        # Change one column name
        wrong_columns = self.expected_columns.copy()
        wrong_columns[8] = "Wrong Category Name"  # Should be "Complaint Category"
        
        mock_sheet = Mock()
        mock_sheet.row_values = Mock(return_value=wrong_columns)
        
        with patch.object(self.service, 'is_available', return_value=True):
            with patch.object(self.service, '_sheet', mock_sheet):
                is_valid, error_msg = self.service.validate_sheet_structure()
        
        self.assertFalse(is_valid, "Expected validation to fail with wrong column name")
        self.assertIn("Missing required sheet column", error_msg)
        self.assertIn("Complaint Category", error_msg)
    
    def test_validate_complaint_category_empty(self):
        """Test that empty category is allowed."""
        is_valid, message = self.service.validate_complaint_category("")
        self.assertTrue(is_valid, "Empty category should be allowed")
        
        is_valid, message = self.service.validate_complaint_category("  ")
        self.assertTrue(is_valid, "Whitespace category should be allowed")
    
    def test_validate_complaint_category_valid(self):
        """Test validation with valid category list from API."""
        # Mock the API to return valid categories
        valid_categories = ["Billing", "Service Quality", "Technical Issue", "Refund Request"]
        
        with patch.object(
            self.service, 'get_valid_complaint_categories',
            return_value=valid_categories
        ):
            is_valid, message = self.service.validate_complaint_category("Billing")
            self.assertTrue(is_valid, f"Valid category should pass, got error: {message}")
            
            is_valid, message = self.service.validate_complaint_category("Service Quality")
            self.assertTrue(is_valid, f"Valid category should pass, got error: {message}")
    
    def test_validate_complaint_category_invalid(self):
        """Test validation with invalid category."""
        # Mock the API to return valid categories
        valid_categories = ["Billing", "Service Quality", "Technical Issue", "Refund Request"]
        
        with patch.object(
            self.service, 'get_valid_complaint_categories',
            return_value=valid_categories
        ):
            is_valid, message = self.service.validate_complaint_category("Invalid Category")
            self.assertFalse(is_valid, "Invalid category should fail validation")
            self.assertIn("not in valid list", message)
    
    def test_append_row_with_structure_validation(self):
        """Test that append_row validates structure before writing."""
        # Create test row (21 columns)
        test_row = [str(i) for i in range(21)]
        test_message_id = "test_msg_123"
        
        mock_sheet = Mock()
        mock_sheet.row_values = Mock(return_value=self.expected_columns)
        mock_sheet.get_all_values = Mock(return_value=[self.expected_columns])
        mock_sheet.update = Mock(return_value=True)
        
        # Mock _message_exists to return False (not a duplicate)
        with patch.object(self.service, 'is_available', return_value=True):
            with patch.object(self.service, '_sheet', mock_sheet):
                with patch.object(self.service, '_message_exists', return_value=False):
                    result = self.service.append_row(test_row, message_id=test_message_id)
        
        # Should succeed because structure validation passed
        self.assertTrue(result, "append_row should succeed with valid structure")
        mock_sheet.update.assert_called()
    
    def test_append_row_aborts_on_structure_mismatch(self):
        """Test that append_row aborts if sheet structure doesn't match."""
        # Create test row (21 columns)
        test_row = [str(i) for i in range(21)]
        test_message_id = "test_msg_456"
        
        # Wrong columns
        wrong_columns = self.expected_columns.copy()
        wrong_columns[8] = "Wrong Category"
        
        mock_sheet = Mock()
        mock_sheet.row_values = Mock(return_value=wrong_columns)
        mock_sheet.append_row = Mock(return_value=True)
        
        with patch.object(self.service, 'is_available', return_value=True):
            with patch.object(self.service, '_sheet', mock_sheet):
                result = self.service.append_row(test_row, message_id=test_message_id)
        
        # Should fail because structure validation failed
        self.assertFalse(result, "append_row should fail when structure doesn't match")
        # append_row should NOT have been called
        mock_sheet.append_row.assert_not_called()
    
    def test_append_row_skip_validation_parameter(self):
        """Test that skip_validation=True bypasses structure check."""
        # Create test row (21 columns)
        test_row = [str(i) for i in range(21)]
        test_message_id = "test_msg_789"
        
        mock_sheet = Mock()
        mock_sheet.row_values = Mock(return_value=self.expected_columns)
        mock_sheet.get_all_values = Mock(return_value=[self.expected_columns])
        mock_sheet.update = Mock(return_value=True)
        
        with patch.object(self.service, 'is_available', return_value=True):
            with patch.object(self.service, '_sheet', mock_sheet):
                with patch.object(self.service, '_message_exists', return_value=False):
                    result = self.service.append_row(
                        test_row,
                        message_id=test_message_id,
                        skip_validation=True
                    )
        
        # Should succeed because we skipped validation
        self.assertTrue(result, "append_row should succeed when skip_validation=True")
        mock_sheet.update.assert_called()

    def test_message_exists_reads_message_id_by_header_name(self):
        """Duplicate checks should follow the message_id header, not a fixed index."""
        mock_sheet = Mock()
        shifted_columns = self.expected_columns.copy()
        shifted_columns.insert(2, shifted_columns.pop(1))
        mock_sheet.row_values = Mock(return_value=shifted_columns)
        mock_sheet.col_values = Mock(return_value=["MSG_001"])

        with patch.object(self.service, '_sheet', mock_sheet):
            self.assertTrue(self.service._message_exists("MSG_001"))

        mock_sheet.col_values.assert_called_once_with(3)

    def test_append_row_reorders_to_current_header_order(self):
        """Appends should match the live sheet header order if columns shift."""
        shifted_columns = self.expected_columns.copy()
        shifted_columns.insert(0, shifted_columns.pop(2))  # Date Reported first

        row = ['' for _ in self.expected_columns]
        row[1] = 'MSG_001'
        row[2] = '29/04/2026'

        mock_sheet = Mock()
        mock_sheet.row_values = Mock(return_value=shifted_columns)
        mock_sheet.col_values = Mock(return_value=[])
        mock_sheet.get_all_values = Mock(return_value=[shifted_columns])
        mock_sheet.update = Mock(return_value=True)

        with patch.object(self.service, 'is_available', return_value=True):
            with patch.object(self.service, '_sheet', mock_sheet):
                result = self.service.append_row(row, message_id='MSG_001')

        self.assertTrue(result)
        update_calls = mock_sheet.update.call_args_list
        self.assertEqual(update_calls[0].args[0], 'A2:A2')
        self.assertEqual(update_calls[0].args[1], [['29/04/2026']])
        self.assertEqual(update_calls[0].kwargs['value_input_option'], 'USER_ENTERED')
        self.assertEqual(update_calls[1].args[0], 'C2:H2')
        self.assertEqual(update_calls[1].args[1][0][0], 'MSG_001')
        self.assertEqual(update_calls[1].kwargs['value_input_option'], 'RAW')
        self.assertEqual(update_calls[2].args[0], 'J2:N2')
        self.assertEqual(update_calls[2].kwargs['value_input_option'], 'RAW')
        written_ranges = [call.args[0] for call in update_calls]
        self.assertNotIn('I2:I2', written_ranges)

    def test_append_row_ignores_formula_only_rows(self):
        """Formula-filled rows should not push new cases far below the table."""
        row = ['' for _ in self.expected_columns]
        row[1] = 'MSG_FORMULA_SAFE'
        row[2] = '30/04/2026'

        formula_only_row = ['COMP-000001'] + [''] * 19 + ['0']

        mock_sheet = Mock()
        mock_sheet.row_values = Mock(return_value=self.expected_columns)
        mock_sheet.col_values = Mock(return_value=[])
        mock_sheet.get_all_values = Mock(
            return_value=[
                self.expected_columns,
                formula_only_row,
                formula_only_row,
            ]
        )
        mock_sheet.update = Mock(return_value=True)

        with patch.object(self.service, 'is_available', return_value=True):
            with patch.object(self.service, '_sheet', mock_sheet):
                result = self.service.append_row(row, message_id='MSG_FORMULA_SAFE')

        self.assertTrue(result)
        update_calls = mock_sheet.update.call_args_list
        self.assertEqual(update_calls[0].args[0], 'B2:B2')
        self.assertEqual(update_calls[0].kwargs['value_input_option'], 'RAW')
        self.assertEqual(update_calls[1].args[0], 'C2:C2')
        self.assertEqual(update_calls[1].args[1], [['30/04/2026']])
        self.assertFalse(update_calls[1].args[1][0][0].startswith("'"))
        self.assertEqual(update_calls[1].kwargs['value_input_option'], 'USER_ENTERED')
        self.assertEqual(update_calls[2].args[0], 'D2:H2')
        self.assertEqual(update_calls[2].kwargs['value_input_option'], 'RAW')
        self.assertEqual(update_calls[3].args[0], 'J2:N2')
        self.assertEqual(update_calls[3].kwargs['value_input_option'], 'RAW')
        written_ranges = [call.args[0] for call in update_calls]
        self.assertNotIn('I2:I2', written_ranges)

    def test_update_case_row_writes_only_workflow_columns(self):
        """Status updates should not overwrite bot intake or formula columns."""
        mock_sheet = Mock()
        mock_sheet.row_values = Mock(return_value=self.expected_columns)
        mock_sheet.col_values = Mock(return_value=['message_id', 'MSG_001'])
        mock_sheet.update = Mock(return_value=True)

        updates = {
            'Status': 'Closed',
            'Resolution Details': 'Pipe replaced',
            'Date Resolved': '11/05/2026',
            'Customer Name': 'SHOULD NOT WRITE',
            'Days Open': '0',
        }

        with patch.object(self.service, 'is_available', return_value=True):
            with patch.object(self.service, '_sheet', mock_sheet):
                result = self.service.update_case_row('MSG_001', updates)

        self.assertTrue(result)
        update_calls = mock_sheet.update.call_args_list
        self.assertEqual(update_calls[0].args[0], 'R2:S2')
        self.assertEqual(
            update_calls[0].args[1],
            [['Closed', 'Pipe replaced']],
        )
        self.assertEqual(update_calls[0].kwargs['value_input_option'], 'RAW')
        self.assertEqual(update_calls[1].args[0], 'T2:T2')
        self.assertEqual(update_calls[1].args[1], [['11/05/2026']])
        self.assertEqual(
            update_calls[1].kwargs['value_input_option'],
            'USER_ENTERED',
        )
        written_ranges = [call.args[0] for call in update_calls]
        self.assertNotIn('D2:D2', written_ranges)
        self.assertNotIn('U2:U2', written_ranges)

    def test_get_instance_is_keyed_by_sheet_id_and_sheet_name(self):
        """Different tabs in the same spreadsheet should get distinct services."""
        GoogleSheetsService.clear_instances()

        first = GoogleSheetsService.get_instance(
            sheet_id='sheet_1',
            sheet_name='Complaints',
        )
        second = GoogleSheetsService.get_instance(
            sheet_id='sheet_1',
            sheet_name='Support',
        )
        again = GoogleSheetsService.get_instance(
            sheet_id='sheet_1',
            sheet_name='Complaints',
        )

        self.assertIs(first, again)
        self.assertIsNot(first, second)
        self.assertEqual(first._sheet_name, 'Complaints')
        self.assertEqual(second._sheet_name, 'Support')

    def test_custom_schema_builds_rows_with_group_specific_headers(self):
        """A group can use different spreadsheet headers without code changes."""
        schema_config = {
            'columns': [
                'Ticket No', 'Backend ID', 'Reported On', 'Client',
                'Account', 'Mobile', 'Reported By', 'Issue',
                'Case State', 'Fix Notes',
            ],
            'field_headers': {
                'complaint_id': 'Ticket No',
                'message_id': 'Backend ID',
                'date_reported': 'Reported On',
                'customer_name': 'Client',
                'customer_id': 'Account',
                'customer_phone': 'Mobile',
                'reported_by': 'Reported By',
                'complaint_description': 'Issue',
                'status': 'Case State',
                'resolution_details': 'Fix Notes',
            },
            'formula_fields': ['complaint_id'],
            'bot_writable_fields': [
                'message_id', 'date_reported', 'customer_name',
                'customer_id', 'customer_phone', 'reported_by',
                'complaint_description',
            ],
            'case_update_fields': ['status', 'resolution_details'],
        }
        service = GoogleSheetsService.get_instance(
            sheet_id='custom_sheet',
            sheet_name='Cases',
            sheet_schema=schema_config,
        )
        msg = ParsedMessage(
            message_id='MSG_CUSTOM',
            customer_name='Jane Doe',
            customer_id='ACC-7',
            customer_phone='0712345678',
            sender='Field Agent',
            complaint_description='No gas supply',
        )

        row = service.schema.row_for_message(msg)

        self.assertEqual(row[1], 'MSG_CUSTOM')
        self.assertEqual(row[3], 'JANE DOE')
        self.assertEqual(row[5], '0712345678')
        self.assertEqual(row[6], 'Field Agent')
        self.assertEqual(row[7], 'No gas supply')

    def test_custom_schema_updates_configured_workflow_columns(self):
        """Status updates should follow the group's configured workflow headers."""
        schema_config = {
            'columns': ['Backend ID', 'Client', 'Case State', 'Fix Notes'],
            'field_headers': {
                'message_id': 'Backend ID',
                'customer_name': 'Client',
                'status': 'Case State',
                'resolution_details': 'Fix Notes',
            },
            'bot_writable_fields': ['message_id', 'customer_name'],
            'case_update_fields': ['status', 'resolution_details'],
        }
        service = GoogleSheetsService.get_instance(
            sheet_id='custom_update_sheet',
            sheet_name='Cases',
            sheet_schema=schema_config,
        )
        mock_sheet = Mock()
        mock_sheet.row_values = Mock(return_value=schema_config['columns'])
        mock_sheet.col_values = Mock(return_value=['Backend ID', 'MSG_001'])
        mock_sheet.update = Mock(return_value=True)

        with patch.object(service, 'is_available', return_value=True):
            with patch.object(service, '_sheet', mock_sheet):
                result = service.update_case_row(
                    'MSG_001',
                    {
                        'status': 'Closed',
                        'resolution_details': 'Pipe replaced',
                        'Client': 'SHOULD NOT WRITE',
                    },
                )

        self.assertTrue(result)
        update_calls = mock_sheet.update.call_args_list
        self.assertEqual(update_calls[0].args[0], 'C2:D2')
        self.assertEqual(update_calls[0].args[1], [['Closed', 'Pipe replaced']])
        self.assertEqual(len(update_calls), 1)


class ParsedMessageToSheetRowTests(TestCase):
    """Test ParsedMessage.to_sheet_row() produces correct 21-column output."""
    
    def test_to_sheet_row_returns_21_columns(self):
        """Test that to_sheet_row returns exactly 21 columns."""
        msg = ParsedMessage(
            raw_message="Test message",
            message_id="msg_001",
            timestamp="2025-01-15 10:30:00",
            customer_name="John Doe",
            customer_id="CUST_123",
            customer_phone="+256701234567",
            sender="WhatsApp User",
            branch_region="Kampala",
            complaint_category="Billing",
            complaint_description="Double charge on account",
            gps_link="https://maps.google.com/",
            image_flag=True,
            source="WhatsApp"
        )
        
        row = msg.to_sheet_row()
        
        self.assertEqual(len(row), 21, f"Expected 21 columns, got {len(row)}")
    
    def test_to_sheet_row_column_order(self):
        """Test that to_sheet_row puts values in correct columns."""
        msg = ParsedMessage(
            raw_message="Test message",
            message_id="msg_001",
            timestamp="2025-01-15 10:30:00",
            customer_name="John Doe",
            customer_id="CUST_123",
            customer_phone="+256701234567",
            sender="WhatsApp User",
            branch_region="Kampala",
            complaint_category="Billing",
            complaint_description="Double charge",
            gps_link="https://maps.google.com/",
            image_flag=True,
            source="WhatsApp"
        )
        
        row = msg.to_sheet_row()
        
        # Verify key columns are in correct positions
        self.assertEqual(row[0], "", "Column [0] should be blank for Complaint ID formula")
        self.assertEqual(row[1], "msg_001", "Column [1] should be message_id (dedup key)")
        self.assertEqual(row[2], "15/01/2025", "Column [2] should be Date Reported")
        self.assertEqual(row[3], "JOHN DOE", "Column [3] should be Customer Name")
        self.assertEqual(row[4], "CUST_123", "Column [4] should be Customer ID")
        self.assertEqual(row[5], "+256701234567", "Column [5] should be Phone Number")
        self.assertEqual(row[6], "WhatsApp User", "Column [6] should be JBL Reported By")
        self.assertEqual(row[7], "Kampala", "Column [7] should be Branch / Region")
        self.assertEqual(row[8], "Billing", "Column [8] should be Complaint Category")
        self.assertEqual(row[9], "Double charge", "Column [9] should be Complaint Description")
        
        # Verify human fields (14-19) are empty
        for col in range(14, 20):
            self.assertEqual(row[col], "", f"Column [{col}] (human field) should be empty")
    
    def test_to_sheet_row_image_flag_formatting(self):
        """Test that image_flag is formatted as 'TRUE' or ''."""
        # Test with image_flag=True
        msg_with_image = ParsedMessage(
            raw_message="Test",
            message_id="msg_with_img",
            timestamp="2025-01-15 10:30:00",
            customer_name="Test User",
            customer_id="TEST_001",
            customer_phone="+256701234567",
            sender="Test",
            branch_region="Test",
            complaint_category="Test",
            complaint_description="Test",
            gps_link="",
            image_flag=True,
            source="Test"
        )
        row = msg_with_image.to_sheet_row()
        self.assertEqual(row[12], "TRUE", "image_flag=True should be 'TRUE'")
        
        # Test with image_flag=False
        msg_no_image = ParsedMessage(
            raw_message="Test",
            message_id="msg_no_img",
            timestamp="2025-01-15 10:30:00",
            customer_name="Test User",
            customer_id="TEST_001",
            customer_phone="+256701234567",
            sender="Test",
            branch_region="Test",
            complaint_category="Test",
            complaint_description="Test",
            gps_link="",
            image_flag=False,
            source="Test"
        )
        row = msg_no_image.to_sheet_row()
        self.assertEqual(row[12], "", "image_flag=False should be ''")
