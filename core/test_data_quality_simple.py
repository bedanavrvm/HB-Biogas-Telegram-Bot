"""
Simple tests for data quality improvements without database dependency.

Validates:
1. Customer Name is capitalized in to_sheet_row()
2. JBL Reported By uses 'Telegram Bot'
3. Source is 'telegram bot'
"""
import unittest
from unittest.mock import MagicMock
from datetime import datetime
from core.models import ParsedMessage


class DataQualitySimpleTests(unittest.TestCase):
    """Test data quality improvements without database."""
    
    def test_customer_name_capitalization(self):
        """Test that customer name is capitalized in sheet output."""
        msg = ParsedMessage()
        msg.message_id = "MSG_TEST_001"
        msg.customer_name = "john doe"  # lowercase
        msg.customer_id = "CUST_123"
        msg.customer_phone = "+256701234567"
        msg.sender = "Ignored Sender"
        msg.branch_region = "MERU"
        msg.complaint_category = "Gas Leakage"
        msg.complaint_description = "System not working"
        msg.raw_message = "Test"
        msg.gps_link = ""
        msg.image_flag = False
        msg.source = "telegram bot"
        msg.loan_status = ""
        msg.loan_at_risk = ""
        msg.risk_level = ""
        msg.complaint_status = ""
        msg.resolution_details = ""
        msg.date_resolved = None
        msg.days_open = None
        msg.timestamp = None
        
        row = msg.to_sheet_row()
        
        # Column [3] should be capitalized customer name
        self.assertEqual(row[3], "JOHN DOE", "Customer name should be capitalized")
        self.assertEqual(len(row), 21, "Row should have 21 columns")
    
    def test_reported_by_telegram_bot(self):
        """Test that JBL Reported By is 'Telegram Bot' in sheet output."""
        msg = ParsedMessage()
        msg.message_id = "MSG_TEST_002"
        msg.customer_name = "jane smith"
        msg.customer_id = "CUST_456"
        msg.customer_phone = "+256702345678"
        msg.sender = "SHOULD_NOT_APPEAR"  # This should NOT appear in column [6]
        msg.branch_region = "NAIROBI"
        msg.complaint_category = "System Underperformance"
        msg.complaint_description = "Not working properly"
        msg.raw_message = "Test"
        msg.gps_link = ""
        msg.image_flag = False
        msg.source = "telegram bot"
        msg.loan_status = ""
        msg.loan_at_risk = ""
        msg.risk_level = ""
        msg.complaint_status = ""
        msg.resolution_details = ""
        msg.date_resolved = None
        msg.days_open = None
        msg.timestamp = None
        
        row = msg.to_sheet_row()
        
        # Column [6] should be 'Telegram Bot', not the sender
        self.assertEqual(row[6], "Telegram Bot", "JBL Reported By should be 'Telegram Bot'")
        self.assertNotEqual(row[6], msg.sender, "Should not use sender name")
    
    def test_source_telegram_bot(self):
        """Test that source is 'telegram bot' in sheet output."""
        msg = ParsedMessage()
        msg.message_id = "MSG_TEST_003"
        msg.customer_name = "test user"
        msg.customer_id = "CUST_789"
        msg.customer_phone = "+256703456789"
        msg.sender = "Test"
        msg.branch_region = ""
        msg.complaint_category = "System Damage/Tear/Burst"
        msg.complaint_description = "Tear in system"
        msg.raw_message = "Test"
        msg.gps_link = ""
        msg.image_flag = False
        msg.source = "telegram bot"  # Set to telegram bot
        msg.loan_status = ""
        msg.loan_at_risk = ""
        msg.risk_level = ""
        msg.complaint_status = ""
        msg.resolution_details = ""
        msg.date_resolved = None
        msg.days_open = None
        msg.timestamp = None
        
        row = msg.to_sheet_row()
        
        # Column [13] should be 'telegram bot'
        self.assertEqual(row[13], "telegram bot", "Source should be 'telegram bot'")
    
    def test_complaint_id_uses_message_id(self):
        """Test that Complaint ID (column [0]) is blank, message_id (column [1]) uses message_id."""
        msg = ParsedMessage()
        msg.message_id = "MSG_UNIQUE_12345"
        msg.customer_name = "Test"
        msg.customer_id = ""
        msg.customer_phone = ""
        msg.sender = ""
        msg.branch_region = ""
        msg.complaint_category = ""
        msg.complaint_description = ""
        msg.raw_message = ""
        msg.gps_link = ""
        msg.image_flag = False
        msg.source = "telegram bot"
        msg.loan_status = ""
        msg.loan_at_risk = ""
        msg.risk_level = ""
        msg.complaint_status = ""
        msg.resolution_details = ""
        msg.date_resolved = None
        msg.days_open = None
        msg.timestamp = None
        
        row = msg.to_sheet_row()
        
        # Column [0] should be blank (different from message_id)
        self.assertEqual(row[0], "", "Complaint ID should be blank")
        # Column [1] should be message_id
        self.assertEqual(row[1], "MSG_UNIQUE_12345", "message_id column should be message_id")
    
    def test_all_column_positions(self):
        """Test all column positions in sheet output."""
        msg = ParsedMessage()
        msg.message_id = "MSG_001"
        msg.timestamp = None
        msg.customer_name = "alice smith"
        msg.customer_id = "CUST_100"
        msg.customer_phone = "+256704567890"
        msg.sender = "Original Sender"
        msg.branch_region = "MERU"
        msg.complaint_category = "Gas Leakage"
        msg.complaint_description = "Pipe disconnected"
        msg.raw_message = "Raw content here"
        msg.gps_link = "https://maps.example.com"
        msg.image_flag = True
        msg.source = "telegram bot"
        msg.loan_status = ""
        msg.loan_at_risk = ""
        msg.risk_level = ""
        msg.complaint_status = ""
        msg.resolution_details = ""
        msg.date_resolved = None
        msg.days_open = None
        
        row = msg.to_sheet_row()
        
        # Verify all 21 columns
        self.assertEqual(len(row), 21, "Should have exactly 21 columns")
        
        # Verify critical columns
        self.assertEqual(row[0], "", "[0] Complaint ID = blank (different from message_id)")
        self.assertEqual(row[1], "MSG_001", "[1] message_id = message_id")
        self.assertEqual(row[2], "", "[2] Date (no timestamp)")
        self.assertEqual(row[3], "ALICE SMITH", "[3] Customer Name (capitalized)")
        self.assertEqual(row[4], "CUST_100", "[4] Customer ID")
        self.assertEqual(row[5], "+256704567890", "[5] Phone")
        self.assertEqual(row[6], "Telegram Bot", "[6] JBL Reported By")
        self.assertEqual(row[7], "MERU", "[7] Branch/Region")
        self.assertEqual(row[8], "Gas Leakage", "[8] Complaint Category")
        self.assertEqual(row[9], "Pipe disconnected", "[9] Complaint Description")
        self.assertEqual(row[10], "Raw content here", "[10] raw_message")
        self.assertEqual(row[11], "https://maps.example.com", "[11] gps_link")
        self.assertEqual(row[12], "TRUE", "[12] image_flag = TRUE")
        self.assertEqual(row[13], "telegram bot", "[13] source = telegram bot")

    def test_date_reported_format_is_day_month_year(self):
        """Date Reported should be formatted as dd/mm/yyyy."""
        msg = ParsedMessage()
        msg.message_id = "MSG_DATE"
        msg.timestamp = datetime(2026, 4, 29, 14, 30)
        msg.customer_name = ""
        msg.customer_id = ""
        msg.customer_phone = ""
        msg.sender = ""
        msg.branch_region = ""
        msg.complaint_category = ""
        msg.complaint_description = ""
        msg.raw_message = ""
        msg.gps_link = ""
        msg.image_flag = False
        msg.source = "telegram bot"
        msg.loan_status = ""
        msg.loan_at_risk = ""
        msg.risk_level = ""
        msg.complaint_status = ""
        msg.resolution_details = ""
        msg.date_resolved = None
        msg.days_open = None

        row = msg.to_sheet_row()

        self.assertEqual(row[2], "29/04/2026")


if __name__ == '__main__':
    unittest.main()
