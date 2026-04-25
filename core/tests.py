"""
Tests for the biogas telegram bot system.

Run with: python manage.py test
"""
import json
from datetime import datetime
from decimal import Decimal
from django.test import TestCase, override_settings
from django.utils import timezone
from unittest.mock import patch, MagicMock

from core.models import RawMessage, ProcessedMessage, ParsedMessage
from core.services.deduplication import generate_message_hash, is_duplicate
from core.services.parser import parse_message, split_batch_message
from core.services.sheets import GoogleSheetsService, batch_append_messages
from core.services.storage import bulk_resync_to_sheets, process_and_store_message


class DeduplicationServiceTest(TestCase):
    """Test the deduplication service."""
    
    def test_generate_message_hash_deterministic(self):
        """Same inputs should produce same hash."""
        hash1 = generate_message_hash("John", "Sold 3 bread 50 each")
        hash2 = generate_message_hash("John", "Sold 3 bread 50 each")
        self.assertEqual(hash1, hash2)
    
    def test_generate_message_hash_different_content(self):
        """Different content should produce different hash."""
        hash1 = generate_message_hash("John", "Sold 3 bread 50 each")
        hash2 = generate_message_hash("John", "Sold 5 milk 100 each")
        self.assertNotEqual(hash1, hash2)
    
    def test_generate_message_hash_case_insensitive(self):
        """Hash should be case-insensitive for content."""
        hash1 = generate_message_hash("John", "SOLD 3 BREAD 50 EACH")
        hash2 = generate_message_hash("john", "sold 3 bread 50 each")
        self.assertEqual(hash1, hash2)
    
    def test_is_duplicate_new_message(self):
        """New message should not be duplicate."""
        msg_hash = generate_message_hash("Test", "Unique content 12345")
        self.assertFalse(is_duplicate(msg_hash))
    
    def test_is_duplicate_after_processing(self):
        """Message should be duplicate after processing."""
        raw_message = RawMessage.objects.create(
            telegram_message_id='test_123',
            sender='Test User',
            content='Test content for dedup',
        )
        msg_hash = generate_message_hash('Test User', 'Test content for dedup')
        
        ProcessedMessage.objects.create(
            message_hash=msg_hash,
            raw_message=raw_message,
            status='success',
        )
        
        self.assertTrue(is_duplicate(msg_hash))

    def test_is_duplicate_ignores_failed_status(self):
        """Failed processing attempts should not be considered duplicates."""
        raw_message = RawMessage.objects.create(
            telegram_message_id='test_456',
            sender='Test User',
            content='Test content for dedup fail',
        )
        msg_hash = generate_message_hash('Test User', 'Test content for dedup fail')
        ProcessedMessage.objects.create(
            message_hash=msg_hash,
            raw_message=raw_message,
            status='failed',
        )
        self.assertFalse(is_duplicate(msg_hash))


class ParserServiceTest(TestCase):
    """Test the message parser."""
    
    def test_parse_sold_pattern(self):
        """Test parsing 'Sold X item Y each' pattern."""
        result = parse_message("Sold 3 bread 50 each to John", sender="Seller")
        
        self.assertEqual(result.quantity, Decimal('3'))
        self.assertEqual(result.item, 'bread')
        self.assertEqual(result.price, Decimal('50'))
        self.assertGreater(result.confidence, 0.5)
    
    def test_parse_paid_pattern(self):
        """Test parsing 'X paid Y for Z item' pattern."""
        result = parse_message("John paid 200 for 4 milk", sender="John")
        
        self.assertEqual(result.price, Decimal('200'))
        self.assertEqual(result.quantity, Decimal('4'))
        self.assertEqual(result.item, 'milk')
    
    def test_parse_gps_url(self):
        """Test GPS URL extraction."""
        content = "📍 https://maps.app.goo.gl/abc123 Sold 2 bags maize"
        result = parse_message(content, sender="Seller")
        
        self.assertIn('https://maps.app.goo.gl/abc123', result.gps_link)
        self.assertEqual(result.item, 'bags maize')
    
    def test_parse_image_flag(self):
        """Test image flag is set correctly."""
        result = parse_message("Sold 3 bread", has_image=True)
        self.assertTrue(result.image_flag)
    
    def test_parse_empty_message(self):
        """Test empty message handling."""
        result = parse_message("")
        self.assertEqual(result.confidence, 0.0)
        self.assertIn("Empty message content", result.warnings)
    
    def test_split_batch_message(self):
        """Test splitting batch forwarded messages."""
        batch_content = """[14/03/2026, 10:30:15] John: Sold 3 bread 50 each
[14/03/2026, 10:31:20] Mary: John paid 200 for 4 milk"""
        
        messages = split_batch_message(batch_content)
        
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]['sender'], 'John')
        self.assertEqual(messages[1]['sender'], 'Mary')
    
    def test_intent_detection_sale(self):
        """Test intent detection for sale messages."""
        from core.services.parser import detect_message_intent, MessageIntent
        
        result = detect_message_intent("Sold 3 bread 50 each to John")
        self.assertEqual(result, MessageIntent.SALE)
        
        result = detect_message_intent("Delivered 2 bags maize")
        self.assertEqual(result, MessageIntent.SALE)
    
    def test_intent_detection_purchase(self):
        """Test intent detection for purchase messages."""
        from core.services.parser import detect_message_intent, MessageIntent
        
        result = detect_message_intent("John bought 3 bags maize @ 100")
        self.assertEqual(result, MessageIntent.PURCHASE)
        
        result = detect_message_intent("Mary purchased 5 chicken")
        self.assertEqual(result, MessageIntent.PURCHASE)
    
    def test_intent_detection_payment(self):
        """Test intent detection for payment messages."""
        from core.services.parser import detect_message_intent, MessageIntent
        
        result = detect_message_intent("John paid 200 for 4 milk")
        self.assertEqual(result, MessageIntent.PAYMENT)
        
        result = detect_message_intent("Mary sent 500")
        self.assertEqual(result, MessageIntent.PAYMENT)
    
    def test_intent_detection_location(self):
        """Test intent detection for location messages."""
        from core.services.parser import detect_message_intent, MessageIntent
        
        result = detect_message_intent("📍 https://maps.app.goo.gl/abc123 Location update")
        self.assertEqual(result, MessageIntent.LOCATION)
        
        result = detect_message_intent("Location: https://goo.gl/maps/xyz")
        self.assertEqual(result, MessageIntent.LOCATION)
    
    def test_intent_detection_status(self):
        """Test intent detection for status messages."""
        from core.services.parser import detect_message_intent, MessageIntent
        
        result = detect_message_intent("Order arrived at destination")
        self.assertEqual(result, MessageIntent.STATUS)
        
        result = detect_message_intent("Product is ready for pickup")
        self.assertEqual(result, MessageIntent.STATUS)
    
    def test_intent_detection_complaint(self):
        """Test intent detection for complaint messages."""
        from core.services.parser import detect_message_intent, MessageIntent
        
        result = detect_message_intent("*CUSTOMER COMPLAIN* NAME: John Doe TEL: 0712345678 ID: A12345")
        self.assertEqual(result, MessageIntent.COMPLAINT)
        
        result = detect_message_intent("CUSTOMER COMPLAIN NATURE OF THE PROBLEM: No gas supply")
        self.assertEqual(result, MessageIntent.COMPLAINT)
    
    def test_parse_complaint_transaction(self):
        """Test parsing structured complaint/case report."""
        from core.services.parser import MessageIntent

        content = (
            "*CUSTOMER COMPLAIN*\n"
            "NAME: John Doe\n"
            "TEL: 0712345678\n"
            "ID: A12345\n"
            "NATURE OF THE PROBLEM: No gas supply at home\n"
            "Please assist urgently."
        )

        result = parse_message(content, sender="Agent")
        self.assertEqual(result.intent, MessageIntent.COMPLAINT)
        self.assertEqual(result.customer_name, 'John Doe')
        self.assertEqual(result.customer_phone, '0712345678')
        self.assertEqual(result.customer_id, 'A12345')
        self.assertIn('No gas supply', result.problem_description)
        self.assertGreater(result.confidence, 0.0)
    
    def test_parse_with_intent_sale(self):
        """Test parsing with SALE intent."""
        from core.services.parser import MessageIntent
        
        result = parse_message("Sold 3 bread 50 each to John", sender="Seller")
        
        self.assertEqual(result.intent, MessageIntent.SALE)
        self.assertEqual(result.quantity, Decimal('3'))
        self.assertEqual(result.item, 'bread')
        self.assertEqual(result.price, Decimal('50'))
        self.assertGreater(result.confidence, 0.5)
    
    def test_parse_with_intent_purchase(self):
        """Test parsing with PURCHASE intent."""
        from core.services.parser import MessageIntent
        
        result = parse_message("John bought 3 bags maize @ 100", sender="John")
        
        self.assertEqual(result.intent, MessageIntent.PURCHASE)
        self.assertEqual(result.quantity, Decimal('3'))
        self.assertEqual(result.item, 'bags maize')
        self.assertEqual(result.price, Decimal('100'))
    
    def test_parse_with_intent_payment(self):
        """Test parsing with PAYMENT intent."""
        from core.services.parser import MessageIntent
        
        result = parse_message("John paid 200 for 4 milk", sender="John")
        
        self.assertEqual(result.intent, MessageIntent.PAYMENT)
        self.assertEqual(result.price, Decimal('200'))
        self.assertEqual(result.quantity, Decimal('4'))
        self.assertEqual(result.item, 'milk')
    
    def test_parse_with_intent_location(self):
        """Test parsing with SALE intent (transaction with location info)."""
        from core.services.parser import MessageIntent
        
        content = "📍 https://maps.app.goo.gl/abc123 Sold 2 bags maize 150 each"
        result = parse_message(content, sender="Seller")
        
        self.assertEqual(result.intent, MessageIntent.SALE)
        self.assertIn('https://maps.app.goo.gl/abc123', result.gps_link)
        self.assertEqual(result.quantity, Decimal('2'))
        self.assertEqual(result.item, 'bags maize')
        self.assertEqual(result.price, Decimal('150'))
    
    def test_parse_diverse_formats(self):
        """Test parsing various real-world WhatsApp message formats."""
        test_cases = [
            # Standard formats
            ("Sold 5 maize 20 each to Peter", {'qty': '5', 'item': 'maize', 'price': '20'}),
            ("John paid 1000 for 10 bags", {'price': '1000', 'qty': '10', 'item': 'bags'}),
            ("Bought 2 chicken @ 300 each", {'qty': '2', 'item': 'chicken', 'price': '300'}),
            
            # With currency
            ("Sold 3 bread KSH 150 each", {'qty': '3', 'item': 'bread', 'price': '150'}),
            ("Paid 2000 total for fertilizer", {'price': '2000', 'item': 'fertilizer'}),
            
            # With GPS
            ("📍 https://maps.app.goo.gl/xyz Sold 4 milk 50 each", {'gps': True, 'qty': '4', 'item': 'milk', 'price': '50'}),
            
            # Different verbs
            ("Delivered 6 eggs 10 each", {'qty': '6', 'item': 'eggs', 'price': '10'}),
            ("Purchased 1 bag cement @ 500", {'qty': '1', 'item': 'bag cement', 'price': '500'}),
            ("Transferred 750 for 3 tomatoes", {'price': '750', 'qty': '3', 'item': 'tomatoes'}),
            
            # Edge cases
            ("Sold bread", {'item': 'bread'}),  # Missing quantity/price
            ("Paid 100", {'price': '100'}),  # Missing item/quantity
            ("Bought maize", {'item': 'maize'}),  # Missing quantity/price
        ]
        
        for content, expected in test_cases:
            with self.subTest(content=content):
                result = parse_message(content)
                
                if 'qty' in expected:
                    self.assertEqual(result.quantity, Decimal(expected['qty']))
                if 'item' in expected:
                    self.assertEqual(result.item, expected['item'])
                if 'price' in expected:
                    self.assertEqual(result.price, Decimal(expected['price']))
                if 'gps' in expected and expected['gps']:
                    self.assertTrue(result.gps_link)
                
                # Should have reasonable confidence for valid transactions
                if any(key in expected for key in ['qty', 'item', 'price']):
                    self.assertGreater(result.confidence, 0.0)
    
    def test_parse_timestamp_formats(self):
        """Test parsing various timestamp formats."""
        from datetime import datetime
        
        test_cases = [
            ("[14/03/2026, 10:30:15] Sold 3 bread", "%d/%m/%Y %H:%M:%S"),
            ("14/03/2026 10:30 Sold maize", "%d/%m/%Y %H:%M"),
            ("[15-03-2026, 14:45:30] Paid 200", "%d-%m-%Y %H:%M:%S"),
        ]
        
        for content, fmt in test_cases:
            with self.subTest(content=content):
                result = parse_message(content)
                self.assertIsNotNone(result.timestamp)
                # Extract the expected time string from content
                import re
                match = re.search(r'\[?(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})[\s,]+(\d{1,2}:\d{2}(?::\d{2})?)\]?', content)
                if match:
                    expected_time_str = f"{match.group(1)} {match.group(2)}"
                    expected = datetime.strptime(expected_time_str, fmt)
                    self.assertEqual(result.timestamp, expected)
    
    def test_parse_sender_extraction(self):
        """Test sender name extraction from various patterns."""
        test_cases = [
            ("Sold 3 bread to John", "John"),
            ("John paid 200 for milk", "John"),
            ("Mary bought 5 eggs", "Mary"),
            ("Delivered goods to Customer Peter", "Customer Peter"),
        ]
        
        for content, expected_sender in test_cases:
            with self.subTest(content=content):
                result = parse_message(content)
                self.assertEqual(result.sender, expected_sender)


class StorageServiceTest(TestCase):
    """Test the storage service."""
    
    @patch('core.services.storage.append_parsed_message_to_sheet')
    def test_process_and_store_new_message(self, mock_sheet):
        """Test processing and storing a new message."""
        mock_sheet.return_value = True
        
        parsed = process_and_store_message(
            telegram_message_id='test_001',
            content='Sold 3 bread 50 each to John',
            sender='Seller',
            received_at=timezone.now(),
        )
        
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.item, 'bread')
        self.assertEqual(parsed.quantity, Decimal('3'))
        
        # Verify raw message stored
        self.assertTrue(
            RawMessage.objects.filter(telegram_message_id='test_001').exists()
        )
        
        # Verify processed message stored
        self.assertTrue(
            ProcessedMessage.objects.filter(
                raw_message__telegram_message_id='test_001'
            ).exists()
        )
    
    @patch('core.services.storage.append_parsed_message_to_sheet')
    def test_process_duplicate_message(self, mock_sheet):
        """Test that duplicate messages return None."""
        mock_sheet.return_value = True
        
        # Store first message
        result1 = process_and_store_message(
            telegram_message_id='dup_001',
            content='Sold 3 bread 50 each',
            sender='Seller',
            received_at=timezone.now(),
        )
        self.assertIsNotNone(result1)
        
        # Try to store duplicate
        result2 = process_and_store_message(
            telegram_message_id='dup_002',
            content='Sold 3 bread 50 each',
            sender='Seller',
            received_at=timezone.now(),
        )
        self.assertIsNone(result2)

    @patch('core.services.sheets.get_sheets_service')
    def test_append_parsed_message_increments_attempts_on_failure(self, mock_service):
        """A failed sheet sync should increment sync_attempts and record the error."""
        raw_message = RawMessage.objects.create(
            telegram_message_id='fail_sheet',
            sender='Test',
            content='Test content',
        )
        msg_hash = generate_message_hash('Test', 'Test content')
        processed = ProcessedMessage.objects.create(
            message_hash=msg_hash,
            raw_message=raw_message,
        )
        parsed = ParsedMessage.objects.create(
            processed_message=processed,
            message_id='MSG_FAIL_1',
            timestamp=timezone.now(),
            sender='John',
            raw_message='Sold 3 bread 50 each',
            item='bread',
            quantity=Decimal('3'),
            price=Decimal('50'),
            gps_link='',
            image_flag=False,
            source='whatsapp_telegram',
        )

        mock_service.return_value = MagicMock()
        mock_service.return_value.append_row.side_effect = Exception('Sheet unavailable')

        from core.services.sheets import append_parsed_message_to_sheet
        success = append_parsed_message_to_sheet(parsed)

        self.assertFalse(success)
        parsed.refresh_from_db()
        self.assertEqual(parsed.sync_attempts, 1)
        self.assertIn('Sheet unavailable', parsed.last_sync_error)

    def test_bulk_resync_to_sheets_skips_max_attempts(self):
        """Resync should ignore messages that have reached max retry attempts."""
        raw_message = RawMessage.objects.create(
            telegram_message_id='resync_001',
            sender='Test',
            content='Test content',
        )
        msg_hash = generate_message_hash('Test', 'Test content')
        processed = ProcessedMessage.objects.create(
            message_hash=msg_hash,
            raw_message=raw_message,
        )
        ParsedMessage.objects.create(
            processed_message=processed,
            message_id='MSG_RESYNC_1',
            timestamp=timezone.now(),
            sender='John',
            raw_message='Sold 3 bread 50 each',
            item='bread',
            quantity=Decimal('3'),
            price=Decimal('50'),
            gps_link='',
            image_flag=False,
            source='whatsapp_telegram',
            sync_attempts=5,
        )

        result = bulk_resync_to_sheets(limit=10, max_attempts=5)
        self.assertEqual(result['attempted'], 0)
        self.assertEqual(result['success_count'], 0)
        self.assertEqual(result['failed_count'], 0)
        self.assertIn('No eligible unsynced messages', result['errors'])

    def test_batch_append_messages_updates_synced_status(self):
        """Batch sheet sync should update only successfully appended messages."""
        raw_message = RawMessage.objects.create(
            telegram_message_id='test_sheet_batch',
            sender='Test',
            content='Test content',
        )
        msg_hash = generate_message_hash('Test', 'Test content')
        processed = ProcessedMessage.objects.create(
            message_hash=msg_hash,
            raw_message=raw_message,
        )
        parsed1 = ParsedMessage.objects.create(
            processed_message=processed,
            message_id='MSG_BATCH_1',
            timestamp=timezone.now(),
            sender='John',
            raw_message='Sold 3 bread 50 each',
            item='bread',
            quantity=Decimal('3'),
            price=Decimal('50'),
            gps_link='',
            image_flag=False,
            source='whatsapp_telegram',
        )
        parsed2 = ParsedMessage.objects.create(
            processed_message=processed,
            message_id='MSG_BATCH_2',
            timestamp=timezone.now(),
            sender='Mary',
            raw_message='Paid 200 for 4 milk',
            item='milk',
            quantity=Decimal('4'),
            price=Decimal('200'),
            gps_link='',
            image_flag=False,
            source='whatsapp_telegram',
        )

        service = GoogleSheetsService()
        service._initialized = True
        service._sheet = MagicMock()
        service._sheet.col_values.return_value = ['MSG_BATCH_1']
        service._sheet.append_row.return_value = None

        with patch('core.services.sheets.get_sheets_service', return_value=service), \
             patch('core.services.sheets.GoogleSheetsService.is_available', return_value=True):
            result = batch_append_messages([parsed1, parsed2])

        self.assertEqual(result['success_count'], 2)
        self.assertEqual(result['failed_count'], 0)
        self.assertIn('MSG_BATCH_1', result['synced_message_ids'])
        self.assertIn('MSG_BATCH_2', result['synced_message_ids'])

        refreshed = ParsedMessage.objects.filter(message_id__in=['MSG_BATCH_1', 'MSG_BATCH_2'])
        self.assertTrue(all(msg.synced_to_sheets for msg in refreshed))


class TelegramWebhookViewTest(TestCase):
    """Test the Telegram webhook endpoint."""
    
    @patch('core.api.views._process_telegram_message')
    def test_webhook_receives_message(self, mock_process):
        """Test webhook accepts message."""
        mock_process.return_value = {
            'status': 'success',
            'message_id': 'MSG_TEST',
        }
        
        payload = {
            'update_id': 123456,
            'message': {
                'message_id': 789,
                'from': {'id': 123, 'first_name': 'Test'},
                'chat': {'id': -100123, 'type': 'group'},
                'date': 1711123456,
                'text': 'Sold 3 bread 50 each',
            }
        }
        
        response = self.client.post(
            '/api/webhook/telegram/',
            data=json.dumps(payload),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')
    
    def test_webhook_rejects_get(self):
        """Test webhook only accepts POST."""
        response = self.client.get('/api/webhook/telegram/')
        self.assertEqual(response.status_code, 405)
    
    def test_health_check(self):
        """Test health check endpoint."""
        response = self.client.get('/api/health/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'healthy')


class ParsedMessageModelTest(TestCase):
    """Test the ParsedMessage model."""
    
    def test_to_sheet_row(self):
        """Test conversion to Google Sheet row format."""
        raw_message = RawMessage.objects.create(
            telegram_message_id='test_sheet',
            sender='Test',
            content='Test content',
        )
        msg_hash = generate_message_hash('Test', 'Test content')
        processed = ProcessedMessage.objects.create(
            message_hash=msg_hash,
            raw_message=raw_message,
        )
        
        parsed = ParsedMessage.objects.create(
            processed_message=processed,
            message_id='MSG_TEST_SHEET',
            timestamp=timezone.now(),
            sender='John',
            raw_message='Sold 3 bread 50 each',
            customer_name='Jane Doe',
            customer_phone='0712345678',
            customer_id='A12345',
            branch_region='Nairobi',
            complaint_category='System Underperformance',
            complaint_description='No gas supply',
            gps_link='https://maps.example.com/xyz',
            image_flag=True,
            source='whatsapp_telegram',
        )
        
        row = parsed.to_sheet_row()
        
        # Verify 21-column production schema
        self.assertEqual(len(row), 21, f"Expected 21 columns, got {len(row)}")
        
        # [0-1] System/control fields
        self.assertEqual(row[0], 'MSG_TEST_SHEET', "Complaint ID should be message_id")
        self.assertEqual(row[1], 'MSG_TEST_SHEET', "message_id dedup key")
        
        # [2-9] Bot intake fields
        self.assertIsInstance(row[2], str)  # Date Reported
        self.assertEqual(row[3], 'Jane Doe', "Customer Name")
        self.assertEqual(row[4], 'A12345', "Customer ID")
        self.assertEqual(row[5], '0712345678', "Phone Number")
        self.assertEqual(row[6], 'John', "Reported By")
        self.assertEqual(row[7], 'Nairobi', "Branch / Region")
        self.assertEqual(row[8], 'System Underperformance', "Complaint Category")
        self.assertEqual(row[9], 'No gas supply', "Complaint Description")
        
        # [10-13] Raw data / Audit trail
        self.assertEqual(row[10], 'Sold 3 bread 50 each', "raw_message")
        self.assertEqual(row[11], 'https://maps.example.com/xyz', "gps_link")
        self.assertEqual(row[12], 'TRUE', "image_flag as TRUE")
        self.assertEqual(row[13], 'whatsapp_telegram', "source")
        
        # [14-20] Human workflow fields (should be empty for bot-generated row)
        self.assertEqual(row[14], '', "Loan Status (human)")
        self.assertEqual(row[15], '', "Loan at Risk (human)")
        self.assertEqual(row[16], '', "Risk Level (human)")
        self.assertEqual(row[17], '', "Status (human)")
        self.assertEqual(row[18], '', "Resolution Details (human)")
        self.assertEqual(row[19], '', "Date Resolved (human)")
        self.assertEqual(row[20], '', "Days Open (formula - should be empty)")
