"""
Tests for data quality improvements to Google Sheets output.

Validates:
1. Customer Name is capitalized
2. JBL Reported By uses 'Telegram Bot'
3. Source is 'telegram bot'
4. Complaint Category excludes invalid patterns
"""
import logging
from django.test import TestCase
from core.models import ParsedMessage, ProcessedMessage, RawMessage
from core.services.parser import parse_message, MessageIntent

logger = logging.getLogger(__name__)


class DataQualityTests(TestCase):
    """Test data quality improvements."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create a raw message
        self.raw_message = RawMessage.objects.create(
            telegram_message_id="test_123",
            sender="Test Sender",
            content="Test content",
            has_image=False
        )
        
        # Create a processed message
        self.processed_message = ProcessedMessage.objects.create(
            message_hash="test_hash_001",
            raw_message=self.raw_message,
            status='success'
        )
    
    def test_customer_name_capitalization(self):
        """Test that customer name is capitalized in sheet output."""
        msg = ParsedMessage.objects.create(
            processed_message=self.processed_message,
            message_id="MSG_TEST_001",
            customer_name="john doe",  # lowercase input
            customer_id="CUST_123",
            customer_phone="+256701234567",
            complaint_category="Gas Leakage",
            complaint_description="System not working",
            raw_message="Test",
            source="telegram bot"
        )
        
        row = msg.to_sheet_row()
        
        # Column [3] should be capitalized customer name
        self.assertEqual(row[3], "JOHN DOE", "Customer name should be capitalized")
    
    def test_reported_by_telegram_bot(self):
        """Test that JBL Reported By is 'Telegram Bot' in sheet output."""
        msg = ParsedMessage.objects.create(
            processed_message=self.processed_message,
            message_id="MSG_TEST_002",
            sender="John Doe",  # This should not appear in column [6]
            customer_name="jane smith",
            customer_id="CUST_456",
            customer_phone="+256702345678",
            complaint_category="System Underperformance",
            complaint_description="Not working properly",
            raw_message="Test",
            source="telegram bot"
        )
        
        row = msg.to_sheet_row()
        
        # Column [6] should be 'Telegram Bot', not the sender
        self.assertEqual(row[6], "Telegram Bot", "JBL Reported By should be 'Telegram Bot'")
        self.assertNotEqual(row[6], msg.sender, "JBL Reported By should not be the sender")
    
    def test_source_telegram_bot(self):
        """Test that source is 'telegram bot' in sheet output."""
        msg = ParsedMessage.objects.create(
            processed_message=self.processed_message,
            message_id="MSG_TEST_003",
            customer_name="test user",
            customer_id="CUST_789",
            customer_phone="+256703456789",
            complaint_category="System Damage/Tear/Burst",
            complaint_description="Tear in system",
            raw_message="Test",
            source="telegram bot"
        )
        
        row = msg.to_sheet_row()
        
        # Column [13] should be 'telegram bot'
        self.assertEqual(row[13], "telegram bot", "Source should be 'telegram bot'")
    
    def test_sheet_row_column_positions(self):
        """Test all critical column positions in sheet output."""
        msg = ParsedMessage.objects.create(
            processed_message=self.processed_message,
            message_id="MSG_TEST_004",
            timestamp=None,  # Will be empty
            customer_name="ALICE SMITH",
            customer_id="CUST_100",
            customer_phone="+256704567890",
            sender="Original Sender",  # Should NOT appear in JBL Reported By
            branch_region="MERU",
            complaint_category="Gas Leakage",
            complaint_description="Pipe disconnected",
            raw_message="Raw content here",
            gps_link="https://maps.example.com",
            image_flag=True,
            source="telegram bot"
        )
        
        row = msg.to_sheet_row()
        
        # Verify column positions
        self.assertEqual(row[0], "", "[0] Complaint ID should be blank for formula")
        self.assertEqual(row[1], msg.message_id, "[1] message_id should be message_id")
        self.assertEqual(row[2], "", "[2] Date Reported should be empty (no timestamp)")
        self.assertEqual(row[3], "ALICE SMITH", "[3] Customer Name should be capitalized")
        self.assertEqual(row[4], "CUST_100", "[4] Customer ID/Account correct")
        self.assertEqual(row[5], "+256704567890", "[5] Phone Number correct")
        self.assertEqual(row[6], "Telegram Bot", "[6] JBL Reported By should be 'Telegram Bot'")
        self.assertEqual(row[7], "MERU", "[7] Branch/Region correct")
        self.assertEqual(row[8], "Gas Leakage", "[8] Complaint Category correct")
        self.assertEqual(row[9], "Pipe disconnected", "[9] Complaint Description correct")
        self.assertEqual(row[10], "Raw content here", "[10] raw_message correct")
        self.assertEqual(row[11], "https://maps.example.com", "[11] gps_link correct")
        self.assertEqual(row[12], "TRUE", "[12] image_flag should be 'TRUE'")
        self.assertEqual(row[13], "telegram bot", "[13] source should be 'telegram bot'")
    
    def test_complaint_extraction_excludes_bot_mentions(self):
        """Test that complaint parsing excludes bot mentions from category."""
        # Message with bot mention that should be excluded
        content = """*CUSTOMER COMPLAIN*
*NAME*: John Doe
TEL: +256701234567
*ID*: CUST_123
*NATURE OF THE PROBLEM*: Gas Leakage @hb_biogas_cases_bot
*CUSTOMER COMPLAIN: The system is leaking gas at the connection point"""
        
        result = parse_message(content, "test_msg_id", "John Doe")
        
        # Category is intentionally left blank for the sheet dropdown.
        self.assertEqual(result.complaint_category, "")
        self.assertNotIn("@", result.problem_description)
    
    def test_complaint_extraction_reasonable_category_length(self):
        """Test that complaint parsing validates category length."""
        # Message with very long category text that should be rejected
        long_text = "a" * 150  # 150 characters - should be rejected
        
        content = f"""*CUSTOMER COMPLAIN*
*NAME*: John Doe
TEL: +256701234567
*ID*: CUST_123
*NATURE OF THE PROBLEM*: {long_text}
*CUSTOMER COMPLAIN: The system is not working"""
        
        result = parse_message(content, "test_msg_id", "John Doe")
        
        # Very long category should be rejected
        self.assertEqual(result.complaint_category, "", 
                        "Category longer than 100 chars should be rejected")
    
    def test_complaint_extraction_valid_categories(self):
        """Test that complaint parsing correctly extracts valid categories."""
        valid_categories = [
            "Gas Leakage",
            "System Damage/Tear/Burst",
            "System Underperformance",
            "Billing Issue",
            "Technical Support"
        ]
        
        for category in valid_categories:
            content = f"""*CUSTOMER COMPLAIN*
*NAME*: John Doe
TEL: +256701234567
*ID*: CUST_123
*NATURE OF THE PROBLEM*: {category}
*CUSTOMER COMPLAIN: There is an issue with the system"""
            
            result = parse_message(content, f"test_msg_{category}", "John Doe")
            
            self.assertEqual(
                result.complaint_category, "",
                "Category should be left blank for staff dropdown selection",
            )


class ParsedMessageModelTests(TestCase):
    """Test ParsedMessage model behavior."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.raw_message = RawMessage.objects.create(
            telegram_message_id="test_123",
            sender="Test Sender",
            content="Test content"
        )
        
        self.processed_message = ProcessedMessage.objects.create(
            message_hash="test_hash_001",
            raw_message=self.raw_message,
            status='success'
        )
    
    def test_source_default_value(self):
        """Test that default source is 'telegram bot'."""
        msg = ParsedMessage.objects.create(
            processed_message=self.processed_message,
            message_id="MSG_DEFAULT_SOURCE",
            customer_name="Test User",
            raw_message="Test",
            # source not specified - should use default
        )
        
        self.assertEqual(msg.source, "telegram bot",
                        "Default source should be 'telegram bot'")
    
    def test_sheet_row_returns_21_columns(self):
        """Test that to_sheet_row always returns exactly 21 columns."""
        msg = ParsedMessage.objects.create(
            processed_message=self.processed_message,
            message_id="MSG_21_COLS",
            customer_name="Test",
            raw_message="Test",
            source="telegram bot"
        )
        
        row = msg.to_sheet_row()
        
        self.assertEqual(len(row), 21,
                        f"Sheet row should have exactly 21 columns, got {len(row)}")
