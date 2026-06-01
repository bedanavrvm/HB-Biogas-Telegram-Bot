"""
Tests for the biogas telegram bot system.

Run with: python manage.py test
"""
import json
from io import StringIO
from datetime import datetime, timedelta
from decimal import Decimal
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from unittest.mock import patch, MagicMock

from core.models import (
    CaseUpdate,
    GroupSheetConfiguration,
    RawMessage,
    ProcessedMessage,
    ParsedMessage,
)
from core.services.deduplication import generate_message_hash, is_duplicate
from core.services.parser import parse_message, split_batch_message
from core.services.sheets import GoogleSheetsService, batch_append_messages
from core.services.sheet_sync import sync_sheet_to_backend
from core.services.storage import bulk_resync_to_sheets, process_and_store_message


def create_parsed_case(
    message_id: str,
    group_id: str = '-100123',
    customer_name: str = 'Jane Doe',
    customer_phone: str = '0712345678',
    customer_id: str = 'CUST-1',
    description: str = 'No gas supply',
    complaint_status: str = '',
    branch_region: str = '',
    complaint_category: str = '',
    risk_level: str = '',
    synced_to_sheets: bool = False,
    sheet_id: str = '',
    sheet_name: str = '',
    last_sync_error: str = '',
    processed_status: str = 'success',
    created_at=None,
) -> ParsedMessage:
    """Create a parsed case with its raw/processed parents for tests."""
    raw = RawMessage.objects.create(
        telegram_message_id=message_id,
        source_telegram_message_id=message_id,
        sender='Agent',
        content=description,
    )
    processed = ProcessedMessage.objects.create(
        message_hash=generate_message_hash('Agent', f'{message_id}:{description}'),
        raw_message=raw,
        status=processed_status,
    )
    parsed = ParsedMessage.objects.create(
        processed_message=processed,
        message_id=message_id,
        timestamp=created_at or timezone.now(),
        customer_name=customer_name,
        customer_phone=customer_phone,
        customer_id=customer_id,
        branch_region=branch_region,
        complaint_category=complaint_category,
        complaint_status=complaint_status,
        complaint_description=description,
        risk_level=risk_level,
        raw_message=description,
        group_id=group_id,
        sheet_id=sheet_id,
        sheet_name=sheet_name,
        source='telegram bot',
        synced_to_sheets=synced_to_sheets,
        last_sync_error=last_sync_error,
    )
    if created_at:
        ParsedMessage.objects.filter(pk=parsed.pk).update(created_at=created_at)
        parsed.refresh_from_db()
    return parsed


class DeduplicationServiceTest(TestCase):
    """Test the deduplication service."""
    
    def test_generate_message_hash_deterministic(self):
        """Same inputs should produce same hash."""
        hash1 = generate_message_hash("John", "Sold 3 bread 50 each")
        hash2 = generate_message_hash("John", "Sold 3 bread 50 each")
        self.assertEqual(hash1, hash2)


class CaseUpdateServiceTest(TestCase):
    """Test chat-driven case status updates."""

    def _patch_sheet_success(self):
        group_config = MagicMock(sheet_id='sheet_123', sheet_name='Complaints')
        registry = MagicMock()
        registry.get_group.return_value = group_config
        sheet = MagicMock()
        sheet.update_case_row.return_value = True
        return (
            patch('core.services.case_updates.GroupRegistry.get_instance', return_value=registry),
            patch('core.services.case_updates.get_sheets_service', return_value=sheet),
            sheet,
        )

    def test_parse_case_update_resolved(self):
        from core.services.case_updates import parse_case_update

        result = parse_case_update('Status: resolved - jiko relocated')

        self.assertTrue(result.is_update)
        self.assertEqual(result.new_status, 'Closed')
        self.assertEqual(result.resolution_text, 'jiko relocated')

    def test_parse_case_update_uses_note_as_resolution_text(self):
        from core.services.case_updates import parse_case_update

        result = parse_case_update(
            'Status: resolved\nNOTE: Jiko relocated and customer confirmed'
        )

        self.assertTrue(result.is_update)
        self.assertEqual(result.new_status, 'Closed')
        self.assertEqual(
            result.resolution_text,
            'Jiko relocated and customer confirmed',
        )

    def test_reply_status_update_updates_case_and_sheet(self):
        from core.services.case_updates import handle_case_status_reply

        case = create_parsed_case(
            'MSG_UPDATE_1',
            complaint_status='Open',
            synced_to_sheets=True,
        )
        case.processed_message.raw_message.telegram_message_id = '777'
        case.processed_message.raw_message.source_telegram_message_id = '777'
        case.processed_message.raw_message.save()

        registry_patch, sheet_patch, sheet = self._patch_sheet_success()
        with registry_patch, sheet_patch:
            result = handle_case_status_reply(
                group_id='-100123',
                reply_to_telegram_message_id='777',
                update_telegram_message_id='888',
                sender='Peter',
                content='Status: resolved - jiko relocated successfully',
            )

        case.refresh_from_db()
        self.assertEqual(result['status'], 'command')
        self.assertIn('Case updated', result['reply_text'])
        self.assertEqual(case.complaint_status, 'Closed')
        self.assertIsNotNone(case.date_resolved)
        self.assertIn('jiko relocated successfully', case.resolution_details)
        update = CaseUpdate.objects.get(parsed_message=case)
        self.assertEqual(update.sync_status, 'success')
        sheet.update_case_row.assert_called_once()
        args, _ = sheet.update_case_row.call_args
        self.assertEqual(args[0], 'MSG_UPDATE_1')
        self.assertEqual(args[1]['status'], 'Closed')
        self.assertIn('jiko relocated successfully', args[1]['resolution_details'])
        self.assertIn('date_resolved', args[1])

    def test_reply_status_update_writes_note_to_resolution_details(self):
        from core.services.case_updates import handle_case_status_reply

        case = create_parsed_case('MSG_UPDATE_NOTE', complaint_status='Open')
        case.processed_message.raw_message.telegram_message_id = '771'
        case.processed_message.raw_message.source_telegram_message_id = '771'
        case.processed_message.raw_message.save()

        registry_patch, sheet_patch, sheet = self._patch_sheet_success()
        with registry_patch, sheet_patch:
            result = handle_case_status_reply(
                group_id='-100123',
                reply_to_telegram_message_id='771',
                update_telegram_message_id='772',
                sender='Peter',
                content=(
                    'Status: resolved\n'
                    'NOTE: Jiko relocated and customer confirmed'
                ),
            )

        case.refresh_from_db()
        self.assertEqual(result['status'], 'command')
        self.assertEqual(case.complaint_status, 'Closed')
        self.assertIn('Jiko relocated and customer confirmed', case.resolution_details)
        self.assertNotIn('NOTE:', case.resolution_details)
        args, _ = sheet.update_case_row.call_args
        self.assertIn('Jiko relocated and customer confirmed', args[1]['resolution_details'])
        self.assertNotIn('NOTE:', args[1]['resolution_details'])

    def test_reply_status_update_does_not_update_db_when_sheet_fails(self):
        from core.services.case_updates import handle_case_status_reply

        case = create_parsed_case('MSG_UPDATE_FAIL', complaint_status='Open')
        case.processed_message.raw_message.telegram_message_id = '700'
        case.processed_message.raw_message.source_telegram_message_id = '700'
        case.processed_message.raw_message.save()

        group_config = MagicMock(sheet_id='sheet_123', sheet_name='Complaints')
        registry = MagicMock()
        registry.get_group.return_value = group_config
        sheet = MagicMock()
        sheet.update_case_row.return_value = False

        with patch('core.services.case_updates.GroupRegistry.get_instance', return_value=registry):
            with patch('core.services.case_updates.get_sheets_service', return_value=sheet):
                result = handle_case_status_reply(
                    group_id='-100123',
                    reply_to_telegram_message_id='700',
                    update_telegram_message_id='701',
                    sender='Peter',
                    content='Status: resolved - fixed',
                )

        case.refresh_from_db()
        self.assertEqual(case.complaint_status, 'Open')
        self.assertIsNone(case.date_resolved)
        self.assertIn('not update the register', result['reply_text'])
        update = CaseUpdate.objects.get(parsed_message=case)
        self.assertEqual(update.sync_status, 'failed')

    def test_reply_status_update_requires_case_id_for_batch_ambiguity(self):
        from core.services.case_updates import handle_case_status_reply

        first = create_parsed_case('MSG_BATCH_A', customer_name='Alice')
        second = create_parsed_case('MSG_BATCH_B', customer_name='Bob')
        first.processed_message.raw_message.telegram_message_id = '900_0'
        first.processed_message.raw_message.source_telegram_message_id = '900'
        first.processed_message.raw_message.batch_index = 0
        first.processed_message.raw_message.save()
        second.processed_message.raw_message.telegram_message_id = '900_1'
        second.processed_message.raw_message.source_telegram_message_id = '900'
        second.processed_message.raw_message.batch_index = 1
        second.processed_message.raw_message.save()

        result = handle_case_status_reply(
            group_id='-100123',
            reply_to_telegram_message_id='900',
            update_telegram_message_id='901',
            sender='Peter',
            content='Status: resolved',
        )

        self.assertEqual(result['status'], 'command')
        self.assertIn('/update MSG_ID', result['reply_text'])
        self.assertEqual(CaseUpdate.objects.count(), 0)

    def test_reply_to_bot_confirmation_uses_case_id_in_quoted_text(self):
        from core.services.case_updates import handle_case_status_reply

        case = create_parsed_case('MSG_CONFIRM_1', complaint_status='Open')
        registry_patch, sheet_patch, _sheet = self._patch_sheet_success()

        with registry_patch, sheet_patch:
            result = handle_case_status_reply(
                group_id='-100123',
                reply_to_telegram_message_id='999',
                update_telegram_message_id='1000',
                sender='Peter',
                content='Status: resolved - jiko relocated',
                reply_to_text=(
                    'OK. Message received and saved successfully\n'
                    'Case ID: MSG_CONFIRM_1\n'
                    'Captured: Customer Name, Customer Phone'
                ),
            )

        case.refresh_from_db()
        self.assertEqual(result['status'], 'command')
        self.assertEqual(case.complaint_status, 'Closed')
        self.assertIn('jiko relocated', case.resolution_details)

    def test_reply_to_original_case_can_match_from_quoted_case_text(self):
        from core.services.case_updates import handle_case_status_reply

        case = create_parsed_case(
            'MSG_ORIGINAL_TEXT',
            customer_name='Henry mwenda',
            customer_phone='0720809218',
            customer_id='24289449',
            description='Requesting for a jiko relocation',
            complaint_status='Open',
        )
        registry_patch, sheet_patch, _sheet = self._patch_sheet_success()

        with registry_patch, sheet_patch:
            result = handle_case_status_reply(
                group_id='-100123',
                reply_to_telegram_message_id='123',
                update_telegram_message_id='124',
                sender='Peter',
                content='Status: resolved - jiko relocated',
                reply_to_text=(
                    '@hb_biogas_cases_bot Henry  mwenda\n'
                    '24289449\n'
                    '0720809218/0726011961\n\n'
                    'Requesting for a jiko relocation'
                ),
            )

        case.refresh_from_db()
        self.assertEqual(result['status'], 'command')
        self.assertEqual(case.complaint_status, 'Closed')
        self.assertIn('jiko relocated', case.resolution_details)

    def test_explicit_update_command_updates_case(self):
        from core.services.commands import handle_bot_command

        case = create_parsed_case('MSG_CMD_1', complaint_status='Open')
        registry_patch, sheet_patch, _sheet = self._patch_sheet_success()

        with registry_patch, sheet_patch:
            result = handle_bot_command(
                '/update MSG_CMD_1 Status: scheduled for Thursday',
                '-100123',
                sender='Peter',
                telegram_message_id='901',
            )

        case.refresh_from_db()
        self.assertEqual(result['status'], 'command')
        self.assertEqual(case.complaint_status, 'In Progress')
        self.assertIn('scheduled for Thursday', case.resolution_details)


class DeduplicationHashTest(TestCase):
    """Additional deduplication hash tests."""

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

    def test_split_multiple_complaint_cases(self):
        """One message with repeated complaint headers should split into cases."""
        batch_content = """*CUSTOMER COMPLAIN*
NAME: Jane Doe
TEL: 0712345678
ID: A123
NATURE OF THE PROBLEM: No gas supply
*CUSTOMER COMPLAIN: The system has stopped producing gas

*CUSTOMER COMPLAIN*
NAME: John Smith
TEL: 0798765432
ID: B456
NATURE OF THE PROBLEM: Gas leakage
*CUSTOMER COMPLAIN: Gas smell around the digester"""

        messages = split_batch_message(batch_content)

        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]['sender'], 'Jane Doe')
        self.assertEqual(messages[1]['sender'], 'John Smith')
        self.assertIn('The system has stopped producing gas', messages[0]['content'])
        self.assertIn('Gas smell around the digester', messages[1]['content'])

    def test_split_complaint_ignores_description_only_fragment(self):
        """A complaint header without identifiers should not become its own case."""
        batch_content = """*CUSTOMER COMPLAIN*
NAME: Jane Doe
TEL: 0712345678
ID: A123
 NATURE OF COMPLAIN: No gas supply
*CUSTOMER COMPLAIN*
The system has stopped producing gas"""

        messages = split_batch_message(batch_content)

        self.assertEqual(len(messages), 1)

    def test_split_multiple_complaint_cases_merges_description_fragments(self):
        """Description-only complaint fragments belong to the previous case."""
        batch_content = """*CUSTOMER COMPLAIN*
NAME: Jane Doe
TEL: 0712345678
ID: A123
 NATURE OF COMPLAIN: No gas supply
*CUSTOMER COMPLAIN*
The system has stopped producing gas

*CUSTOMER COMPLAIN*
NAME: John Smith
TEL: 0798765432
ID: B456
NATURE OF THE COMPLAINT: Gas leakage
*CUSTOMER COMPLAIN*
Gas smell around the digester"""

        messages = split_batch_message(batch_content)

        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]['sender'], 'Jane Doe')
        self.assertEqual(messages[1]['sender'], 'John Smith')
        self.assertIn('The system has stopped producing gas', messages[0]['content'])
        self.assertIn('Gas smell around the digester', messages[1]['content'])

    def test_split_unlabeled_complaint_cases(self):
        """Unlabeled complaint blocks should still split when complete."""
        batch_content = """*CUSTOMER COMPLAIN*
Jane Doe
0712345678
A123
No gas supply at home

*CUSTOMER COMPLAIN*
John Smith
0798765432
B456
Gas leaking around the digester"""

        messages = split_batch_message(batch_content)

        self.assertEqual(len(messages), 2)
        self.assertIn('Jane Doe', messages[0]['content'])
        self.assertIn('John Smith', messages[1]['content'])
    
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

    def test_parse_complaint_fields_on_one_line_have_clear_boundaries(self):
        """Adjacent labels should not be swallowed into earlier fields."""
        from core.services.parser import MessageIntent

        content = (
            "CUSTOMER COMPLAIN NAME: John Doe TEL: 0712345678 "
            "ID: A12345 NATURE OF COMPLAIN: No gas supply"
        )

        result = parse_message(content, sender="Agent")

        self.assertEqual(result.intent, MessageIntent.COMPLAINT)
        self.assertEqual(result.customer_name, 'John Doe')
        self.assertEqual(result.customer_phone, '0712345678')
        self.assertEqual(result.customer_id, 'A12345')
        self.assertEqual(result.problem_description, 'No gas supply')
        self.assertEqual(result.confidence, 1.0)

    def test_parse_complaint_fields_without_label_separators(self):
        """Labels without punctuation should still define clean field bounds."""
        from core.services.parser import MessageIntent

        content = (
            "CUSTOMER COMPLAIN NAME John Doe TEL NO 0712345678 "
            "ID A12345 NATURE OF COMPLAIN No gas supply at home"
        )

        result = parse_message(content, sender="Agent")

        self.assertEqual(result.intent, MessageIntent.COMPLAINT)
        self.assertEqual(result.customer_name, 'John Doe')
        self.assertEqual(result.customer_phone, '0712345678')
        self.assertEqual(result.customer_id, 'A12345')
        self.assertEqual(result.problem_description, 'No gas supply at home')
        self.assertNotIn('NAME', result.customer_name.upper())
        self.assertNotIn('CUSTOMER COMPLAIN', result.problem_description.upper())

    def test_parse_multiline_complaint_fields_without_separators(self):
        """Line breaks should work as separators, but not be required."""
        content = (
            "CUSTOMER COMPLAIN\n"
            "NAME Jane Doe\n"
            "TEL NO 0712345678\n"
            "ID A12345\n"
            "NATURE OF COMPLAIN No gas supply at home"
        )

        result = parse_message(content, sender="Agent")

        self.assertEqual(result.customer_name, 'Jane Doe')
        self.assertEqual(result.customer_phone, '0712345678')
        self.assertEqual(result.customer_id, 'A12345')
        self.assertEqual(result.problem_description, 'No gas supply at home')

    def test_parse_complaint_description_does_not_swallow_following_labels(self):
        """Problem text should stop before later structured fields."""
        content = (
            "CUSTOMER COMPLAIN NATURE OF COMPLAINT: Burner not working "
            "NAME: Alice Smith TEL: +254712345678 ID: CUST_100"
        )

        result = parse_message(content, sender="Agent")

        self.assertEqual(result.customer_name, 'Alice Smith')
        self.assertEqual(result.customer_phone, '0712345678')
        self.assertEqual(result.customer_id, 'CUST_100')
        self.assertEqual(result.problem_description, 'Burner not working')

    def test_parse_unlabeled_comma_name_and_numeric_id(self):
        """Unlabeled case blocks should allow comma-form names and numeric IDs."""
        content = (
            "CUSTOMER COMPLAIN\n"
            "NYAMU , ROSE RUGURU\n"
            "0721552446\n"
            "11598558\n"
            "Less cooking hrs than expected"
        )

        result = parse_message(content, sender="Agent")

        self.assertEqual(result.customer_name, 'NYAMU, ROSE RUGURU')
        self.assertEqual(result.customer_phone, '0721552446')
        self.assertEqual(result.customer_id, '11598558')
        self.assertEqual(result.problem_description, 'Less cooking hrs than expected')

    def test_parse_of_phone_sentence_name(self):
        """A name before 'of phone:' should be captured as the customer name."""
        from core.services.parser import MessageIntent

        content = (
            "Joseph Mbaabu of phone:0714953414 is requesting for an agronomy training"
        )

        result = parse_message(content, sender="Agent")

        self.assertEqual(result.intent, MessageIntent.COMPLAINT)
        self.assertEqual(result.customer_name, 'Joseph Mbaabu')
        self.assertEqual(result.customer_phone, '0714953414')
        self.assertEqual(
            result.problem_description,
            'is requesting for an agronomy training',
        )

    def test_parse_subject_sentence_name_and_normalises_phone(self):
        """Sentence-subject names are used only inside complaint parsing."""
        from core.services.parser import MessageIntent

        content = (
            "Francis Kaihura Kuria is requesting installation\n"
            "254797963674"
        )

        result = parse_message(content, sender="Agent")

        self.assertEqual(result.intent, MessageIntent.COMPLAINT)
        self.assertEqual(result.customer_name, 'Francis Kaihura Kuria')
        self.assertEqual(result.customer_phone, '0797963674')
        self.assertEqual(result.problem_description, 'is requesting installation')

    def test_parse_status_description_does_not_return_full_message(self):
        """If there is no problem keyword, keep only the non-identity remainder."""
        content = (
            "CUSTOMER COMPLAIN NAME Doreen Gaceri\n"
            "Phone:0718077338\n"
            "ready for installation"
        )

        result = parse_message(content, sender="Agent")

        self.assertEqual(result.customer_name, 'Doreen Gaceri')
        self.assertEqual(result.customer_phone, '0718077338')
        self.assertEqual(result.problem_description, 'ready for installation')
        self.assertNotIn('CUSTOMER COMPLAIN', result.problem_description)
        self.assertNotIn('Phone', result.problem_description)

    def test_parse_unlabeled_bot_tagged_relocation_case(self):
        """Bot-tagged unlabeled blocks should parse identity plus request text."""
        from core.services.parser import MessageIntent

        content = (
            "@hb_biogas_cases_bot Henry  mwenda\n"
            "24289449\n"
            "0720809218/0726011961\n"
            "\n"
            "Requesting for a jiko relocation"
        )

        result = parse_message(content, sender="Agent")

        self.assertEqual(result.intent, MessageIntent.COMPLAINT)
        self.assertEqual(result.customer_name, 'Henry mwenda')
        self.assertEqual(result.customer_id, '24289449')
        self.assertEqual(result.customer_phone, '0720809218')
        self.assertEqual(result.problem_description, 'Requesting for a jiko relocation')

    def test_parse_complaint_description_excludes_trailing_awareness_mentions(self):
        """Trailing @mentions are notification tags, not complaint text."""
        content = (
            "CUSTOMER COMPLAIN\n"
            "Henry mwenda\n"
            "24289449\n"
            "0720809218/0726011961\n"
            "\n"
            "Requesting for a jiko relocation @area_manager"
        )

        result = parse_message(content, sender="Agent")

        self.assertEqual(result.customer_name, 'Henry mwenda')
        self.assertEqual(result.problem_description, 'Requesting for a jiko relocation')
        self.assertNotIn('@area_manager', result.problem_description)

    def test_parse_complaint_description_excludes_spaced_display_mention(self):
        """Display-name mentions such as '@~Eunny K' should be stripped fully."""
        content = (
            "@hb_biogas_cases_bot Henry  mwenda\n"
            "24289449\n"
            "0720809218/0726011961\n"
            "\n"
            "Requesting for a jiko relocation @~Eunny K"
        )

        result = parse_message(content, sender="Agent")

        self.assertEqual(result.customer_name, 'Henry mwenda')
        self.assertEqual(result.problem_description, 'Requesting for a jiko relocation')
        self.assertNotIn('Eunny', result.problem_description)
        self.assertNotIn('K', result.problem_description)

    def test_parse_complaint_description_excludes_final_mention_line(self):
        """A final line containing only mentions should not enter the description."""
        content = (
            "CUSTOMER COMPLAIN NAME Jane Doe TEL 0712345678 "
            "NATURE OF COMPLAIN No gas supply at home\n"
            "@technician @supervisor"
        )

        result = parse_message(content, sender="Agent")

        self.assertEqual(result.problem_description, 'No gas supply at home')
        self.assertNotIn('@technician', result.problem_description)

    def test_parse_unlabeled_complaint_transaction(self):
        """Plain complaint blocks should infer identifiers and description."""
        from core.services.parser import MessageIntent

        content = (
            "CUSTOMER COMPLAIN\n"
            "John Doe\n"
            "0712345678\n"
            "A12345\n"
            "No gas supply at home. Please assist urgently."
        )

        result = parse_message(content, sender="Agent")

        self.assertEqual(result.intent, MessageIntent.COMPLAINT)
        self.assertEqual(result.customer_name, 'John Doe')
        self.assertEqual(result.customer_phone, '0712345678')
        self.assertEqual(result.customer_id, 'A12345')
        self.assertEqual(
            result.problem_description,
            'No gas supply at home. Please assist urgently.',
        )
        self.assertEqual(result.confidence, 1.0)

    def test_parse_unlabeled_complaint_without_header(self):
        """Phone plus complaint language should detect an unlabeled complaint."""
        from core.services.parser import MessageIntent

        content = "Jane Doe 0798765432 B456 biogas is leaking near the valve"

        result = parse_message(content, sender="Agent")

        self.assertEqual(result.intent, MessageIntent.COMPLAINT)
        self.assertEqual(result.customer_name, 'Jane Doe')
        self.assertEqual(result.customer_phone, '0798765432')
        self.assertEqual(result.customer_id, 'B456')
        self.assertEqual(result.problem_description, 'biogas is leaking near the valve')
        self.assertEqual(result.confidence, 1.0)
    
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
                    self.assertEqual(result.timestamp.replace(tzinfo=None), expected)
    
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

    @patch('core.services.sheets.append_parsed_message_to_sheet')
    def test_process_and_store_persists_sheet_identity(self, mock_sheet):
        """Stored cases should retain the sheet they were routed to."""
        mock_sheet.return_value = True

        parsed = process_and_store_message(
            telegram_message_id='test_sheet_identity',
            content='Sold 3 bread 50 each to John',
            sender='Seller',
            received_at=timezone.now(),
            group_id='-100123',
            sheet_id='sheet_123',
            sheet_name='Cases',
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.group_id, '-100123')
        self.assertEqual(parsed.sheet_id, 'sheet_123')
        self.assertEqual(parsed.sheet_name, 'Cases')
        self.assertEqual(mock_sheet.call_args.kwargs['sheet_id'], 'sheet_123')
        self.assertEqual(mock_sheet.call_args.kwargs['sheet_name'], 'Cases')
    
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

    @patch('core.services.storage.append_parsed_message_to_sheet')
    def test_process_and_store_message_sheet_sync_failure(self, mock_sheet):
        """Sheet sync failures should mark message processing as partial."""
        mock_sheet.return_value = False

        parsed = process_and_store_message(
            telegram_message_id='test_sync_fail',
            content='Sold 3 bread 50 each to John',
            sender='Seller',
            received_at=timezone.now(),
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(getattr(parsed, '_processing_status', None), 'partial')
        self.assertEqual(getattr(parsed, '_processing_error', None), 'Google Sheets sync failed')

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
        service._sheet.row_values.return_value = service.SHEET_COLUMNS
        service._sheet.col_values.return_value = ['message_id', 'MSG_BATCH_1']
        service._sheet.get_all_values.return_value = [
            service.SHEET_COLUMNS,
            ['', 'MSG_BATCH_1'] + [''] * 19,
        ]
        service._sheet.update.return_value = None

        with patch('core.services.sheets.get_sheets_service', return_value=service), \
             patch('core.services.sheets.GoogleSheetsService.is_available', return_value=True):
            result = batch_append_messages([parsed1, parsed2])

        self.assertEqual(result['success_count'], 2)
        self.assertEqual(result['failed_count'], 0)
        self.assertIn('MSG_BATCH_1', result['synced_message_ids'])
        self.assertIn('MSG_BATCH_2', result['synced_message_ids'])

        refreshed = ParsedMessage.objects.filter(message_id__in=['MSG_BATCH_1', 'MSG_BATCH_2'])
        self.assertTrue(all(msg.synced_to_sheets for msg in refreshed))

    @patch('core.services.sheet_sync.get_sheets_service')
    def test_sync_sheet_to_backend_mirrors_sheet_rows(self, mock_service):
        """Sheet sync should create, update, and delete local case rows."""
        existing = create_parsed_case(
            'MSG_KEEP',
            customer_name='Old Name',
            complaint_status='Open',
        )
        original_processed_id = existing.processed_message_id
        original_raw = existing.processed_message.raw_message
        original_raw.telegram_message_id = '777'
        original_raw.source_telegram_message_id = '777'
        original_raw.save(update_fields=['telegram_message_id', 'source_telegram_message_id'])
        create_parsed_case('MSG_DELETE')

        service = MagicMock()
        service.is_available.return_value = True
        service.validate_sheet_structure.return_value = (True, '')
        service.fetch_rows.return_value = [
            {
                'row_number': 2,
                'values': {
                    'complaint id': 'COMP-1',
                    'message_id': 'MSG_KEEP',
                    'date reported': '29/04/2026',
                    'customer name': 'Updated Name',
                    'customer id / account': 'ACC-1',
                    'phone number': '0700000001',
                    'jbl reported by': 'Sheet User',
                    'branch / region': 'Nairobi',
                    'complaint category': 'No gas',
                    'complaint description': 'Edited in sheet',
                    'raw_message': 'Edited raw',
                    'gps_link': '',
                    'image_flag': 'TRUE',
                    'source': 'telegram bot',
                    'loan status': 'Active',
                    'loan at risk': 'No',
                    'risk level': 'Low',
                    'status': 'Closed',
                    'resolution details': 'Fixed',
                    'date resolved': '30/04/2026',
                    'days open': '1',
                },
            },
            {
                'row_number': 3,
                'values': {
                    'complaint id': 'COMP-2',
                    'message_id': 'MSG_NEW',
                    'date reported': '30/04/2026',
                    'customer name': 'New Customer',
                    'customer id / account': 'ACC-2',
                    'phone number': '0700000002',
                    'jbl reported by': 'Sheet User',
                    'complaint description': 'Created from sheet',
                    'status': 'Open',
                },
            },
        ]
        mock_service.return_value = service

        result = sync_sheet_to_backend(
            group_id='-100123',
            sheet_id='sheet_123',
            sheet_name='Cases',
            delete_missing=True,
        )

        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['created_count'], 1)
        self.assertEqual(result['updated_count'], 1)
        self.assertEqual(result['deleted_count'], 1)
        self.assertFalse(ParsedMessage.objects.filter(message_id='MSG_DELETE').exists())

        existing.refresh_from_db()
        self.assertEqual(existing.customer_name, 'Updated Name')
        self.assertEqual(existing.complaint_status, 'Closed')
        self.assertEqual(existing.resolution_details, 'Fixed')
        self.assertEqual(existing.sheet_id, 'sheet_123')
        self.assertEqual(existing.sheet_name, 'Cases')
        self.assertTrue(existing.synced_to_sheets)
        self.assertTrue(existing.image_flag)
        self.assertEqual(existing.processed_message_id, original_processed_id)
        self.assertEqual(
            existing.processed_message.raw_message.telegram_message_id,
            '777',
        )

        created = ParsedMessage.objects.get(message_id='MSG_NEW')
        self.assertEqual(created.customer_name, 'New Customer')
        self.assertEqual(created.complaint_description, 'Created from sheet')
        self.assertEqual(created.group_id, '-100123')
        self.assertEqual(created.sheet_id, 'sheet_123')
        self.assertEqual(created.sheet_name, 'Cases')


class GroupConfigurationServiceTest(TestCase):
    """Test admin-managed group routing configuration."""

    def tearDown(self):
        from core.services.group_config import GroupRegistry
        GroupRegistry._instance = None
        super().tearDown()

    @override_settings(GROUP_MAPPING={}, GOOGLE_SHEET_ID='')
    def test_admin_group_configuration_routes_group_to_sheet(self):
        """A group can be configured from the admin UI instead of env JSON."""
        from core.services.group_config import GroupRegistry

        GroupSheetConfiguration.objects.create(
            group_id='-100999',
            display_name='Support Team',
            sheet_id='admin_sheet_123',
            sheet_name='Support Cases',
            sheet_schema={
                'field_headers': {
                    'message_id': 'Backend ID',
                    'customer_name': 'Client',
                },
            },
            workflow={'status_values': ['Open', 'In Progress', 'Closed']},
            parser_rules={'bot_username': 'hb_biogas_cases_bot'},
        )

        GroupRegistry._instance = None
        config = GroupRegistry.get_instance().get_group('-100999')

        self.assertIsNotNone(config)
        self.assertEqual(config.sheet_id, 'admin_sheet_123')
        self.assertEqual(config.sheet_name, 'Support Cases')
        self.assertEqual(config.sheet_schema.header('message_id'), 'Backend ID')
        self.assertEqual(config.workflow['status_values'][0], 'Open')
        self.assertEqual(config.parser_rules['bot_username'], 'hb_biogas_cases_bot')

    @override_settings(
        GROUP_MAPPING={
            '-100999': {
                'sheet_id': 'env_sheet',
                'sheet_name': 'Env Cases',
            },
        },
        GOOGLE_SHEET_ID='',
    )
    def test_admin_group_configuration_overrides_settings_mapping(self):
        """Admin UI config should win over env config for the same group."""
        from core.services.group_config import GroupRegistry

        GroupSheetConfiguration.objects.create(
            group_id='-100999',
            display_name='Admin Team',
            sheet_id='admin_sheet',
            sheet_name='Admin Cases',
        )

        GroupRegistry._instance = None
        config = GroupRegistry.get_instance().get_group('-100999')

        self.assertEqual(config.sheet_id, 'admin_sheet')
        self.assertEqual(config.sheet_name, 'Admin Cases')

    @override_settings(
        STORAGES={
            'default': {
                'BACKEND': 'django.core.files.storage.FileSystemStorage',
            },
            'staticfiles': {
                'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
            },
        },
    )
    def test_group_configuration_admin_changelist_renders(self):
        """Admin changelist should render without template context copy errors."""
        user = get_user_model().objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='password',
        )
        GroupSheetConfiguration.objects.create(
            group_id='-100777',
            display_name='Admin Render Test',
            sheet_id='sheet_777',
            sheet_name='Cases',
        )
        self.client.force_login(user)

        response = self.client.get('/admin/core/groupsheetconfiguration/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Admin Render Test')

    def test_group_configuration_admin_form_generates_order_approval_workflow(self):
        """Order approval preset should avoid hand-written workflow JSON."""
        from core.admin import GroupSheetConfigurationAdminForm

        form = GroupSheetConfigurationAdminForm(data={
            'enabled': 'on',
            'group_id': '-100222',
            'display_name': 'Order Approval',
            'sheet_id': 'sheet_order_123',
            'sheet_name': 'Orders',
            'sheet_schema': '{}',
            'workflow': '{}',
            'parser_rules': '{}',
            'metadata': '{}',
            'workflow_preset': 'order_approval',
            'order_approval_search_tabs': 'Orders',
            'order_approval_match_field': 'id_number',
            'order_approval_media_field': 'media_urls',
            'order_approval_header_row': '3',
            'order_approval_media_root_folder': 'BRO Order Approvals',
        })

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.generated_workflow(),
            {
                'type': 'order_approval',
                'match_field': 'id_number',
                'search_sheet_names': ['Orders'],
                'create_sheet_name': 'Orders',
                'media_field': 'media_urls',
                'record_id_prefix': 'JBL',
                'header_row': 3,
                'media_root_folder': 'BRO Order Approvals',
            },
        )

    def test_workflow_presets_define_order_approval_defaults(self):
        """Future workflow additions should follow the shared preset contract."""
        from core.services.workflow_presets import (
            build_workflow_from_preset,
            defaults_for_preset,
            preset_choices,
        )

        choices = dict(preset_choices())
        self.assertIn('order_approval', choices)
        self.assertEqual(choices['order_approval'], 'Order Approval')

        defaults = defaults_for_preset('order_approval')
        self.assertEqual(defaults['sheet_name'], 'Orders')
        self.assertEqual(defaults['sheet_schema'], {})
        self.assertEqual(defaults['parser_rules'], {})

        workflow = build_workflow_from_preset('order_approval')
        self.assertEqual(workflow['type'], 'order_approval')
        self.assertEqual(
            workflow['search_sheet_names'],
            ['Orders'],
        )
        self.assertEqual(workflow['header_row'], 2)
        self.assertEqual(workflow['media_root_folder'], '')
        self.assertEqual(workflow['record_id_prefix'], 'JBL')

    def test_workflow_preset_overrides_order_approval_tabs(self):
        """Admin can override preset tabs without editing raw JSON."""
        from core.services.workflow_presets import build_workflow_from_preset

        workflow = build_workflow_from_preset(
            'order_approval',
            overrides={
                'search_sheet_names': ['Pending', '190'],
                'match_field': 'id_number',
                'media_field': 'media_urls',
                'header_row': 3,
                'media_root_folder': 'BRO Order Approvals',
            },
        )

        self.assertEqual(workflow['search_sheet_names'], ['Pending', '190'])
        self.assertEqual(workflow['create_sheet_name'], 'Pending')
        self.assertEqual(workflow['header_row'], 3)
        self.assertEqual(workflow['media_root_folder'], 'BRO Order Approvals')

    def test_workflow_preset_uses_first_overridden_tab_for_order_creation(self):
        """New order approval rows are created in the first configured tab."""
        from core.services.workflow_presets import build_workflow_from_preset

        workflow = build_workflow_from_preset(
            'order_approval',
            overrides={
                'search_sheet_names': ['Sheet', 'Archive'],
                'match_field': 'id_number',
                'media_field': 'media_urls',
            },
        )

        self.assertEqual(workflow['search_sheet_names'], ['Sheet', 'Archive'])
        self.assertEqual(workflow['create_sheet_name'], 'Sheet')


class SheetAnalyzerServiceTest(TestCase):
    """Test Google Sheet analysis and schema suggestion."""

    def _mock_sheet_service(self):
        service = MagicMock()
        service.is_available.return_value = True
        service._sheet_id = 'sheet_123'
        service._sheet_name = 'Cases'
        service._api_initialized = True
        service._sheet.get_all_values.return_value = [
            [
                'Complaint ID', 'Backend ID', 'Reported On', 'Client',
                'Mobile', 'Case State', 'Fix Notes', 'Days Open',
            ],
            [
                '=ROW()-1', 'MSG_001', '11/05/2026', 'Jane Doe',
                '0712345678', 'Open', '', '=TODAY()-C2',
            ],
            [
                '=ROW()-1', 'MSG_002', '12/05/2026', 'John Doe',
                '254712345678', 'Closed', 'Fixed pipe', '=TODAY()-C3',
            ],
        ]
        service._sheet.get.return_value = [
            [
                'Complaint ID', 'Backend ID', 'Reported On', 'Client',
                'Mobile', 'Case State', 'Fix Notes', 'Days Open',
            ],
            [
                '=ROW()-1', 'MSG_001', '11/05/2026', 'Jane Doe',
                '0712345678', 'Open', '', '=TODAY()-C2',
            ],
        ]

        metadata_get = MagicMock()
        metadata_get.execute.return_value = {
            'sheets': [
                {
                    'properties': {'title': 'Cases'},
                    'data': [
                        {
                            'rowData': [
                                {'values': [{} for _ in range(8)]},
                                {
                                    'values': [
                                        {}, {}, {}, {}, {},
                                        {
                                            'dataValidation': {
                                                'condition': {
                                                    'type': 'ONE_OF_LIST',
                                                    'values': [
                                                        {'userEnteredValue': 'Open'},
                                                        {'userEnteredValue': 'In Progress'},
                                                        {'userEnteredValue': 'Closed'},
                                                    ],
                                                },
                                            },
                                        },
                                    ],
                                },
                            ],
                        },
                    ],
                },
            ],
        }
        service._sheets_api_service.spreadsheets.return_value.get.return_value = metadata_get
        return service

    @patch('core.services.sheet_analyzer.get_sheets_service')
    def test_analyze_google_sheet_suggests_schema_and_dropdowns(self, mock_service):
        from core.services.sheet_analyzer import analyze_google_sheet

        mock_service.return_value = self._mock_sheet_service()

        result = analyze_google_sheet('sheet_123', 'Cases')

        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['row_count'], 2)
        schema = result['suggested_schema']
        self.assertEqual(schema['field_headers']['message_id'], 'Backend ID')
        self.assertEqual(schema['field_headers']['customer_name'], 'Client')
        self.assertEqual(schema['field_headers']['customer_phone'], 'Mobile')
        self.assertEqual(schema['field_headers']['status'], 'Case State')
        self.assertIn('complaint_id', schema['formula_fields'])
        self.assertIn('days_open', schema['formula_fields'])
        self.assertEqual(
            result['workflow']['dropdown_values']['status'],
            ['Open', 'In Progress', 'Closed'],
        )

    @patch('core.services.sheet_analyzer.list_google_sheet_worksheets')
    @patch('core.services.sheet_analyzer.get_sheets_service')
    def test_analyze_google_sheet_unavailable_result_has_template_defaults(
        self,
        mock_service,
        mock_worksheets,
    ):
        from core.services.sheet_analyzer import analyze_google_sheet

        service = MagicMock()
        service.is_available.return_value = False
        mock_service.return_value = service
        mock_worksheets.return_value = (['Orders'], '')

        result = analyze_google_sheet(
            'sheet_123',
            'Orders',
            workflow={'header_row': 2},
        )

        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['worksheet_titles'], ['Orders'])
        self.assertEqual(result['row_count'], 0)
        self.assertEqual(result['data_row_count'], 0)
        self.assertEqual(result['header_row'], 2)
        self.assertEqual(result['sample_size'], 0)
        self.assertEqual(result['headers'], [])
        self.assertEqual(result['columns'], [])
        self.assertEqual(result['warnings'], [])

    @patch('core.services.sheet_analyzer.get_sheets_service')
    def test_analyze_google_sheet_uses_configured_order_header_row(self, mock_service):
        from core.services.sheet_analyzer import analyze_google_sheet

        service = MagicMock()
        service.is_available.return_value = True
        service._sheet_id = 'sheet_123'
        service._sheet_name = 'Orders'
        service._api_initialized = False
        service._sheet.get_all_values.return_value = [
            ['ORDER APPROVAL FORM'],
            ['DATE VISITED', 'CUSTOMER NAME', 'ID NUMBER', 'Media URLs'],
            ['25-May-2026', 'Jane Doe', '113650221', ''],
        ]
        service._sheet.get.return_value = [
            ['DATE VISITED', 'CUSTOMER NAME', 'ID NUMBER', 'Media URLs'],
            ['25-May-2026', 'Jane Doe', '113650221', ''],
        ]
        mock_service.return_value = service

        result = analyze_google_sheet(
            'sheet_123',
            'Orders',
            workflow={'type': 'order_approval', 'header_row': 2},
        )

        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['header_row'], 2)
        self.assertEqual(result['headers'][2], 'ID NUMBER')
        self.assertEqual(result['warnings'], [])

    @patch('core.services.sheet_analyzer.get_sheets_service')
    def test_analyze_google_sheet_custom_workflow_has_no_complaint_warnings(self, mock_service):
        from core.services.sheet_analyzer import analyze_google_sheet

        service = MagicMock()
        service.is_available.return_value = True
        service._sheet_id = 'sheet_123'
        service._sheet_name = 'Any'
        service._api_initialized = False
        service._sheet.get_all_values.return_value = [
            ['External ID', 'Name', 'Status'],
            ['A1', 'Jane Doe', 'Open'],
        ]
        service._sheet.get.return_value = [
            ['External ID', 'Name', 'Status'],
            ['A1', 'Jane Doe', 'Open'],
        ]
        mock_service.return_value = service

        result = analyze_google_sheet('sheet_123', 'Any', workflow={})

        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['warnings'], [])

    def test_apply_analysis_to_config_saves_schema_workflow_and_metadata(self):
        from core.services.sheet_analyzer import apply_analysis_to_config

        config = GroupSheetConfiguration.objects.create(
            group_id='-100555',
            sheet_id='sheet_123',
            sheet_name='Cases',
        )
        analysis = {
            'suggested_schema': {
                'columns': ['Backend ID', 'Client'],
                'field_headers': {
                    'message_id': 'Backend ID',
                    'customer_name': 'Client',
                },
            },
            'workflow': {
                'dropdown_values': {
                    'status': ['Open', 'Closed'],
                },
            },
            'row_count': 10,
            'sample_size': 5,
            'columns': [{'header': 'Backend ID'}],
            'warnings': [],
        }

        apply_analysis_to_config(config, analysis)

        config.refresh_from_db()
        self.assertEqual(config.sheet_schema['field_headers']['message_id'], 'Backend ID')
        self.assertEqual(config.workflow['dropdown_values']['status'], ['Open', 'Closed'])
        self.assertEqual(config.metadata['sheet_analysis']['row_count'], 10)


class BotCommandServiceTest(TestCase):
    """Test database-backed Telegram bot commands."""

    def test_last_command_returns_latest_group_cases(self):
        """The /last command should return recent cases for the current group."""
        now = timezone.now()
        create_parsed_case(
            'MSG_OLD',
            customer_name='Old Customer',
            description='Older issue',
            created_at=now - timedelta(minutes=10),
        )
        create_parsed_case(
            'MSG_NEW',
            customer_name='New Customer',
            description='Newest issue',
            created_at=now,
        )
        create_parsed_case(
            'MSG_OTHER_GROUP',
            group_id='-999',
            customer_name='Other Group',
            description='Should not appear',
            created_at=now + timedelta(minutes=1),
        )

        from core.services.commands import handle_bot_command

        result = handle_bot_command('/last 2', '-100123')

        self.assertEqual(result['status'], 'command')
        self.assertIn('Latest 2 case(s):', result['reply_text'])
        self.assertIn('NEW CUSTOMER', result['reply_text'])
        self.assertIn('Newest issue', result['reply_text'])
        self.assertIn('OLD CUSTOMER', result['reply_text'])
        self.assertIn('Older issue', result['reply_text'])
        self.assertNotIn('MSG_NEW', result['reply_text'])
        self.assertNotIn('MSG_OLD', result['reply_text'])
        self.assertNotIn('MSG_OTHER_GROUP', result['reply_text'])

    def test_last_command_hides_imported_from_sheets_placeholder(self):
        """List output should not show internal placeholders as problem text."""
        create_parsed_case(
            'MSG_IMPORTED',
            customer_name='Sheet Customer',
            customer_phone='0711111111',
            customer_id='ACC-1',
            description='',
        )
        ParsedMessage.objects.filter(message_id='MSG_IMPORTED').update(
            complaint_description='',
            raw_message='Imported from Google Sheets',
        )

        from core.services.commands import handle_bot_command

        result = handle_bot_command('/last 1', '-100123')

        self.assertEqual(result['status'], 'command')
        self.assertIn('SHEET CUSTOMER', result['reply_text'])
        self.assertIn('Tel: 0711111111', result['reply_text'])
        self.assertIn('Customer ID: ACC-1', result['reply_text'])
        self.assertIn('Problem: no problem description recorded', result['reply_text'])
        self.assertNotIn('Imported from Google Sheets', result['reply_text'])
        self.assertNotIn('MSG_IMPORTED', result['reply_text'])

    def test_last_command_empty_group(self):
        """The command should return a useful empty-state response."""
        from core.services.commands import handle_bot_command

        result = handle_bot_command('last 5', '-100123')

        self.assertEqual(result['status'], 'command')
        self.assertEqual(result['reply_text'], 'No cases found for this group yet.')

    def test_non_command_returns_none(self):
        """Ordinary complaint text should continue to the parser."""
        from core.services.commands import handle_bot_command

        self.assertIsNone(
            handle_bot_command('CUSTOMER COMPLAIN: no gas supply', '-100123')
        )

    def test_case_command_returns_detail(self):
        """The /case command should return a full case view."""
        create_parsed_case(
            'MSG_DETAIL',
            customer_name='Jane Doe',
            customer_phone='0700000000',
            customer_id='ACC-123',
            description='Detailed case description',
            complaint_status='Open',
            synced_to_sheets=True,
        )

        from core.services.commands import handle_bot_command

        result = handle_bot_command('/case MSG_DETAIL', '-100123')

        self.assertEqual(result['status'], 'command')
        self.assertIn('Case MSG_DETAIL', result['reply_text'])
        self.assertIn('Customer: JANE DOE', result['reply_text'])
        self.assertIn('Phone: 0700000000', result['reply_text'])
        self.assertIn('Customer ID: ACC-123', result['reply_text'])
        self.assertIn('Synced: yes', result['reply_text'])

    def test_search_command_matches_customer_and_description(self):
        """Search should scan customer fields and complaint text."""
        create_parsed_case(
            'MSG_LEAK',
            customer_name='Leak Customer',
            customer_phone='0711111111',
            description='Gas leakage near the pipe',
        )
        create_parsed_case(
            'MSG_OTHER',
            customer_name='Other Customer',
            customer_phone='0722222222',
            description='No matching text',
        )

        from core.services.commands import handle_bot_command

        result = handle_bot_command('/search leakage', '-100123')

        self.assertEqual(result['status'], 'command')
        self.assertIn('LEAK CUSTOMER', result['reply_text'])
        self.assertIn('Gas leakage near the pipe', result['reply_text'])
        self.assertNotIn('MSG_LEAK', result['reply_text'])
        self.assertNotIn('OTHER CUSTOMER', result['reply_text'])

    def test_today_command_returns_todays_cases(self):
        """The /today command should show only cases created today."""
        now = timezone.now()
        create_parsed_case('MSG_TODAY', customer_name='Today Customer', created_at=now)
        create_parsed_case('MSG_YESTERDAY', customer_name='Yesterday Customer', created_at=now - timedelta(days=1))

        from core.services.commands import handle_bot_command

        result = handle_bot_command('/today', '-100123')

        self.assertEqual(result['status'], 'command')
        self.assertIn('TODAY CUSTOMER', result['reply_text'])
        self.assertNotIn('YESTERDAY CUSTOMER', result['reply_text'])
        self.assertNotIn('MSG_TODAY', result['reply_text'])

    def test_unsynced_command_returns_unsynced_cases(self):
        """The /unsynced command should show only unsynced rows."""
        create_parsed_case(
            'MSG_UNSYNCED',
            customer_name='Unsynced Customer',
            synced_to_sheets=False,
            last_sync_error='Sheet unavailable',
        )
        create_parsed_case('MSG_SYNCED', customer_name='Saved Customer', synced_to_sheets=True)

        from core.services.commands import handle_bot_command

        result = handle_bot_command('/unsynced 5', '-100123')

        self.assertEqual(result['status'], 'command')
        self.assertIn('UNSYNCED CUSTOMER', result['reply_text'])
        self.assertIn('Sheet unavailable', result['reply_text'])
        self.assertNotIn('SAVED CUSTOMER', result['reply_text'])
        self.assertNotIn('MSG_UNSYNCED', result['reply_text'])

    @override_settings(
        GOOGLE_SHEET_ID='sheet_123',
        GOOGLE_SHEET_TAB_NAME='Cases',
        GROUP_MAPPING={},
    )
    def test_group_command_returns_routing(self):
        """The /group command should show current group routing."""
        from core.services.commands import handle_bot_command
        from core.services.group_config import GroupRegistry

        GroupRegistry._instance = None
        result = handle_bot_command('/group', '-100123')

        self.assertEqual(result['status'], 'command')
        self.assertIn('Group: -100123', result['reply_text'])
        self.assertIn('Sheet ID: sheet_123', result['reply_text'])
        self.assertIn('Sheet tab: Cases', result['reply_text'])
        GroupRegistry._instance = None

    @override_settings(
        GOOGLE_SHEET_ID='sheet_123',
        GOOGLE_SHEET_TAB_NAME='Cases',
        GROUP_MAPPING={},
    )
    def test_health_command_returns_db_and_counts(self):
        """The /health command should return DB status and group counts."""
        from core.services.commands import handle_bot_command
        from core.services.group_config import GroupRegistry

        GroupRegistry._instance = None
        create_parsed_case('MSG_HEALTH', synced_to_sheets=False)

        result = handle_bot_command('/health', '-100123')

        self.assertEqual(result['status'], 'command')
        self.assertIn('Database: ok', result['reply_text'])
        self.assertIn('Group: configured', result['reply_text'])
        self.assertIn('Workflow: case', result['reply_text'])
        self.assertIn('Cases: 1', result['reply_text'])
        self.assertIn('Unsynced: 1', result['reply_text'])
        self.assertIn('Telegram token:', result['reply_text'])
        GroupRegistry._instance = None

    @override_settings(
        GOOGLE_SHEET_ID='',
        GOOGLE_SHEET_TAB_NAME='Cases',
        GROUP_MAPPING={},
        MEDIA_STORAGE_PROVIDER='google_drive',
        MEDIA_MAX_FILE_SIZE_MB=20,
        ORDER_APPROVAL_MAX_TOTAL_UPLOAD_MB=60,
    )
    def test_health_command_returns_order_workflow_diagnostics(self):
        """The /health command should include order workflow counters."""
        from core.models import GroupSheetConfiguration, MediaAttachment, OrderApprovalUpdate
        from core.services.commands import handle_bot_command
        from core.services.group_config import GroupRegistry

        GroupSheetConfiguration.objects.create(
            group_id='-100order',
            display_name='Order group',
            enabled=True,
            sheet_id='sheet_order',
            sheet_name='Orders',
            workflow={
                'type': 'order_approval',
                'search_sheet_names': ['Orders'],
                'header_row': 2,
            },
        )
        OrderApprovalUpdate.objects.create(
            group_id='-100order',
            sheet_id='sheet_order',
            id_number='113650221',
            update_status='failed',
        )
        MediaAttachment.objects.create(
            group_id='-100order',
            telegram_message_id='1',
            telegram_file_id='file_1',
            upload_status='failed',
        )
        GroupRegistry._instance = None

        result = handle_bot_command('/health', '-100order')

        self.assertEqual(result['status'], 'command')
        self.assertIn('Workflow: order_approval', result['reply_text'])
        self.assertIn('Order workflow', result['reply_text'])
        self.assertIn('Failed updates: 1', result['reply_text'])
        self.assertIn('Failed media: 1', result['reply_text'])
        self.assertIn('Order tabs: Orders', result['reply_text'])
        self.assertIn('Max upload total: 60 MB', result['reply_text'])
        self.assertIn('Image previews: off', result['reply_text'])
        GroupRegistry._instance = None

    def test_status_filter_commands(self):
        """Open, pending, and closed commands should filter by status."""
        create_parsed_case('MSG_OPEN', customer_name='Open Customer', complaint_status='Open')
        create_parsed_case('MSG_PENDING', customer_name='Pending Customer', complaint_status='')
        create_parsed_case('MSG_CLOSED', customer_name='Closed Customer', complaint_status='Closed')

        from core.services.commands import handle_bot_command

        open_result = handle_bot_command('/open 10', '-100123')
        pending_result = handle_bot_command('/pending 10', '-100123')
        closed_result = handle_bot_command('/closed 10', '-100123')

        self.assertIn('OPEN CUSTOMER', open_result['reply_text'])
        self.assertIn('PENDING CUSTOMER', open_result['reply_text'])
        self.assertNotIn('CLOSED CUSTOMER', open_result['reply_text'])
        self.assertIn('PENDING CUSTOMER', pending_result['reply_text'])
        self.assertNotIn('OPEN CUSTOMER', pending_result['reply_text'])
        self.assertIn('CLOSED CUSTOMER', closed_result['reply_text'])
        self.assertNotIn('OPEN CUSTOMER', closed_result['reply_text'])

    def test_stale_command_returns_old_not_closed_cases(self):
        """Stale should show old cases that are not closed."""
        now = timezone.now()
        create_parsed_case(
            'MSG_STALE',
            customer_name='Stale Customer',
            complaint_status='Open',
            created_at=now - timedelta(days=10),
        )
        create_parsed_case(
            'MSG_CLOSED_OLD',
            customer_name='Closed Old Customer',
            complaint_status='Closed',
            created_at=now - timedelta(days=10),
        )
        create_parsed_case(
            'MSG_RECENT',
            customer_name='Recent Customer',
            complaint_status='Open',
            created_at=now,
        )

        from core.services.commands import handle_bot_command

        result = handle_bot_command('/stale 7', '-100123')

        self.assertIn('STALE CUSTOMER', result['reply_text'])
        self.assertIn('Age:', result['reply_text'])
        self.assertNotIn('CLOSED OLD CUSTOMER', result['reply_text'])
        self.assertNotIn('RECENT CUSTOMER', result['reply_text'])

    def test_errors_command_returns_sync_errors(self):
        """Errors should show cases with non-empty last_sync_error."""
        create_parsed_case(
            'MSG_ERROR',
            customer_name='Error Customer',
            last_sync_error='Google quota exceeded',
        )
        create_parsed_case('MSG_NO_ERROR', customer_name='No Error Customer', last_sync_error='')

        from core.services.commands import handle_bot_command

        result = handle_bot_command('/errors 10', '-100123')

        self.assertIn('ERROR CUSTOMER', result['reply_text'])
        self.assertIn('Google quota exceeded', result['reply_text'])
        self.assertNotIn('NO ERROR CUSTOMER', result['reply_text'])

    def test_summary_today_command_returns_counts(self):
        """Summary today should count status and sync state for today."""
        now = timezone.now()
        create_parsed_case(
            'MSG_OPEN_SUMMARY',
            complaint_status='Open',
            synced_to_sheets=False,
            last_sync_error='Sheet unavailable',
            created_at=now,
        )
        create_parsed_case(
            'MSG_CLOSED_SUMMARY',
            complaint_status='Closed',
            synced_to_sheets=True,
            created_at=now,
        )
        create_parsed_case(
            'MSG_OLD_SUMMARY',
            complaint_status='Open',
            created_at=now - timedelta(days=2),
        )

        from core.services.commands import handle_bot_command

        result = handle_bot_command('/summary today', '-100123')

        self.assertIn('Summary for today', result['reply_text'])
        self.assertIn('Total: 2', result['reply_text'])
        self.assertIn('Open/not closed: 1', result['reply_text'])
        self.assertIn('Closed: 1', result['reply_text'])
        self.assertIn('Unsynced: 1', result['reply_text'])
        self.assertIn('Sync errors: 1', result['reply_text'])

    def test_summary_week_command_includes_week_cases(self):
        """Summary week should include cases since the start of the local week."""
        now = timezone.now()
        create_parsed_case('MSG_WEEK_1', created_at=now)
        create_parsed_case('MSG_WEEK_2', created_at=now - timedelta(days=1))

        from core.services.commands import handle_bot_command

        result = handle_bot_command('/summary week', '-100123')

        self.assertIn('Summary for this week', result['reply_text'])
        self.assertIn('Total:', result['reply_text'])

    def test_week_command_returns_this_weeks_cases(self):
        """The /week command should list cases created this week."""
        now = timezone.now()
        start_of_week = timezone.localdate() - timedelta(days=timezone.localdate().weekday())
        last_week = timezone.make_aware(
            datetime.combine(start_of_week - timedelta(days=1), datetime.min.time())
        )
        create_parsed_case('MSG_THIS_WEEK', customer_name='This Week Customer', created_at=now)
        create_parsed_case('MSG_LAST_WEEK', customer_name='Last Week Customer', created_at=last_week)

        from core.services.commands import handle_bot_command

        result = handle_bot_command('/week', '-100123')

        self.assertIn("This week's cases", result['reply_text'])
        self.assertIn('THIS WEEK CUSTOMER', result['reply_text'])
        self.assertNotIn('LAST WEEK CUSTOMER', result['reply_text'])

    def test_phone_and_id_commands_lookup_cases(self):
        """Phone and customer ID lookup commands should search specific fields."""
        create_parsed_case(
            'MSG_PHONE',
            customer_name='Lookup Customer',
            customer_phone='0712345000',
            customer_id='ACC-123',
        )
        create_parsed_case(
            'MSG_OTHER_LOOKUP',
            customer_name='Other Lookup Customer',
            customer_phone='0799999999',
            customer_id='ACC-999',
        )

        from core.services.commands import handle_bot_command

        phone_result = handle_bot_command('/phone 0712345', '-100123')
        id_result = handle_bot_command('/id ACC-123', '-100123')

        self.assertIn('LOOKUP CUSTOMER', phone_result['reply_text'])
        self.assertNotIn('OTHER LOOKUP CUSTOMER', phone_result['reply_text'])
        self.assertIn('LOOKUP CUSTOMER', id_result['reply_text'])
        self.assertNotIn('OTHER LOOKUP CUSTOMER', id_result['reply_text'])

    def test_missing_command_returns_cases_missing_requested_field(self):
        """Missing should filter by the requested blank field."""
        create_parsed_case('MSG_MISSING_PHONE', customer_name='Missing Phone Customer', customer_phone='')
        create_parsed_case('MSG_HAS_PHONE', customer_name='Has Phone Customer', customer_phone='0712345678')

        from core.services.commands import handle_bot_command

        result = handle_bot_command('/missing phone 10', '-100123')

        self.assertIn('missing phone number', result['reply_text'])
        self.assertIn('MISSING PHONE CUSTOMER', result['reply_text'])
        self.assertNotIn('HAS PHONE CUSTOMER', result['reply_text'])

    def test_lowconfidence_command_returns_partial_or_incomplete_cases(self):
        """Low-confidence should include partial processing and incomplete cases."""
        create_parsed_case(
            'MSG_PARTIAL_CASE',
            customer_name='Partial Customer',
            processed_status='partial',
        )
        create_parsed_case(
            'MSG_INCOMPLETE_CASE',
            customer_name='',
        )
        create_parsed_case('MSG_COMPLETE_CASE', customer_name='Complete Customer')

        from core.services.commands import handle_bot_command

        result = handle_bot_command('/lowconfidence 10', '-100123')

        self.assertIn('PARTIAL CUSTOMER', result['reply_text'])
        self.assertIn('partial processing', result['reply_text'])
        self.assertIn('UNKNOWN', result['reply_text'])
        self.assertIn('missing name', result['reply_text'])
        self.assertNotIn('COMPLETE CUSTOMER', result['reply_text'])

    def test_risk_command_filters_by_risk_level(self):
        """Risk should return cases matching the requested level."""
        create_parsed_case('MSG_HIGH_RISK', customer_name='High Risk Customer', risk_level='High')
        create_parsed_case('MSG_LOW_RISK', customer_name='Low Risk Customer', risk_level='Low')

        from core.services.commands import handle_bot_command

        result = handle_bot_command('/risk high 10', '-100123')

        self.assertIn('HIGH RISK CUSTOMER', result['reply_text'])
        self.assertNotIn('LOW RISK CUSTOMER', result['reply_text'])

    def test_duplicates_command_reports_repeated_phone_or_customer_id(self):
        """Duplicates should group repeated phone numbers and customer IDs."""
        create_parsed_case(
            'MSG_DUP_1',
            customer_phone='0712000000',
            customer_id='ACC-DUP',
        )
        create_parsed_case(
            'MSG_DUP_2',
            customer_phone='0712000000',
            customer_id='ACC-DUP',
        )
        create_parsed_case(
            'MSG_UNIQUE',
            customer_phone='0799000000',
            customer_id='ACC-UNIQUE',
        )

        from core.services.commands import handle_bot_command

        result = handle_bot_command('/duplicates 30', '-100123')

        self.assertIn('Duplicate hints', result['reply_text'])
        self.assertIn('phone 0712000000: 2 case(s)', result['reply_text'])
        self.assertIn('customer ID ACC-DUP: 2 case(s)', result['reply_text'])
        self.assertNotIn('ACC-UNIQUE', result['reply_text'])

    def test_top_commands_report_regions_and_issues(self):
        """Top commands should aggregate non-blank region and issue fields."""
        create_parsed_case(
            'MSG_REGION_1',
            branch_region='Nairobi',
            complaint_category='Leak',
        )
        create_parsed_case(
            'MSG_REGION_2',
            branch_region='Nairobi',
            complaint_category='Leak',
        )
        create_parsed_case(
            'MSG_REGION_3',
            branch_region='Mombasa',
            complaint_category='No gas',
        )

        from core.services.commands import handle_bot_command

        regions_result = handle_bot_command('/top regions 7', '-100123')
        issues_result = handle_bot_command('/top issues 7', '-100123')

        self.assertIn('Top regions', regions_result['reply_text'])
        self.assertIn('Nairobi: 2', regions_result['reply_text'])
        self.assertIn('Mombasa: 1', regions_result['reply_text'])
        self.assertIn('Top issues', issues_result['reply_text'])
        self.assertIn('Leak: 2', issues_result['reply_text'])
        self.assertIn('No gas: 1', issues_result['reply_text'])

    def test_help_command_lists_useful_commands(self):
        """Help should expose the useful command set."""
        from core.services.commands import handle_bot_command

        result = handle_bot_command('/help', '-100123')

        self.assertIn('/phone 0712345678', result['reply_text'])
        self.assertIn('/missing phone 10', result['reply_text'])
        self.assertIn('/duplicates 30', result['reply_text'])
        self.assertIn('/top regions 7', result['reply_text'])

    def test_help_command_uses_order_approval_group_commands(self):
        """Order approval groups should not see complaint/case commands."""
        from core.services.commands import handle_bot_command
        from core.services.group_config import GroupRegistry

        GroupSheetConfiguration.objects.create(
            group_id='-100order',
            display_name='Order group',
            enabled=True,
            sheet_id='sheet_order',
            sheet_name='Orders',
            workflow={'type': 'order_approval'},
        )
        GroupRegistry._instance = None

        result = handle_bot_command('/help', '-100order')

        self.assertIn('/order - Open the order approval form', result['reply_text'])
        self.assertIn('/form - Open the order approval form', result['reply_text'])
        self.assertIn('/group - Show this chat', result['reply_text'])
        self.assertNotIn('/last 5', result['reply_text'])
        self.assertNotIn('/case MSG_ID', result['reply_text'])


class TelegramCommandMenuTest(TestCase):
    """Test native Telegram command autocomplete sync."""

    @override_settings(TELEGRAM_BOT_TOKEN='token', API_REQUEST_TIMEOUT=5)
    @patch('core.management.commands.sync_telegram_commands.requests.post')
    def test_sync_telegram_commands_sets_workflow_specific_group_scopes(self, mock_post):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {'ok': True, 'result': True}
        mock_post.return_value = response
        GroupSheetConfiguration.objects.create(
            group_id='-100order',
            display_name='Order group',
            enabled=True,
            sheet_id='sheet_order',
            sheet_name='Orders',
            workflow={'type': 'order_approval'},
        )
        GroupSheetConfiguration.objects.create(
            group_id='-100cases',
            display_name='Case group',
            enabled=True,
            sheet_id='sheet_cases',
            sheet_name='Cases',
            workflow={},
        )

        output = StringIO()
        call_command('sync_telegram_commands', stdout=output)

        set_calls = [
            call for call in mock_post.call_args_list
            if call.args[0].endswith('/setMyCommands')
        ]
        delete_calls = [
            call for call in mock_post.call_args_list
            if call.args[0].endswith('/deleteMyCommands')
        ]
        payloads = [call.kwargs['json'] for call in set_calls]
        scopes = [payload['scope'] for payload in payloads]
        self.assertIn({'type': 'all_private_chats'}, scopes)
        self.assertNotIn({'type': 'all_group_chats'}, scopes)
        self.assertIn({'type': 'chat', 'chat_id': '-100order'}, scopes)
        self.assertIn({'type': 'chat', 'chat_id': '-100cases'}, scopes)
        self.assertEqual(
            delete_calls[0].kwargs['json']['scope'],
            {'type': 'all_group_chats'},
        )
        order_payload = next(
            payload for payload in payloads
            if payload['scope'] == {'type': 'chat', 'chat_id': '-100order'}
        )
        order_commands = [item['command'] for item in order_payload['commands']]
        self.assertIn('order', order_commands)
        self.assertIn('form', order_commands)
        self.assertIn('group', order_commands)
        self.assertNotIn('last', order_commands)
        self.assertNotIn('case', order_commands)
        case_payload = next(
            payload for payload in payloads
            if payload['scope'] == {'type': 'chat', 'chat_id': '-100cases'}
        )
        case_commands = [item['command'] for item in case_payload['commands']]
        self.assertIn('last', case_commands)
        self.assertIn('case', case_commands)
        self.assertIn('group', case_commands)
        self.assertNotIn('order', case_commands)

    def test_sync_telegram_commands_dry_run_lists_group_scope_without_token(self):
        GroupSheetConfiguration.objects.create(
            group_id='-100order',
            display_name='Order group',
            enabled=True,
            sheet_id='sheet_order',
            sheet_name='Orders',
            workflow={'type': 'order_approval'},
        )

        output = StringIO()
        call_command('sync_telegram_commands', '--dry-run', '--group-id=-100order', stdout=output)

        text = output.getvalue()
        self.assertIn('Would sync chat -100order', text)
        self.assertIn('/order', text)
        self.assertIn('/group', text)

    @override_settings(TELEGRAM_BOT_TOKEN='token', API_REQUEST_TIMEOUT=5)
    @patch('core.management.commands.sync_telegram_commands.requests.post')
    def test_sync_telegram_commands_updates_migrated_group_id(self, mock_post):
        failed_response = MagicMock()
        failed_response.status_code = 400
        failed_response.text = (
            '{"ok":false,"error_code":400,'
            '"description":"Bad Request: group chat was upgraded to a supergroup chat",'
            '"parameters":{"migrate_to_chat_id":-1003817885962}}'
        )
        failed_response.json.return_value = {
            'ok': False,
            'error_code': 400,
            'description': 'Bad Request: group chat was upgraded to a supergroup chat',
            'parameters': {'migrate_to_chat_id': -1003817885962},
        }
        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {'ok': True, 'result': True}
        mock_post.side_effect = [failed_response, success_response]
        config = GroupSheetConfiguration.objects.create(
            group_id='-5259879581',
            display_name='Order group',
            enabled=True,
            sheet_id='sheet_order',
            sheet_name='Orders',
            workflow={'type': 'order_approval'},
        )

        output = StringIO()
        call_command(
            'sync_telegram_commands',
            '--group-id=-5259879581',
            stdout=output,
        )

        config.refresh_from_db()
        self.assertEqual(config.group_id, '-1003817885962')
        self.assertEqual(config.metadata['migrated_from_chat_id'], '-5259879581')
        payloads = [call.kwargs['json'] for call in mock_post.call_args_list]
        self.assertEqual(payloads[0]['scope'], {'type': 'chat', 'chat_id': '-5259879581'})
        self.assertEqual(payloads[1]['scope'], {'type': 'chat', 'chat_id': '-1003817885962'})
        self.assertIn(
            'Updated migrated Telegram group -5259879581 -> -1003817885962',
            output.getvalue(),
        )


@override_settings(TELEGRAM_WEBHOOK_SECRET=None, DEBUG=True)
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

    @patch('core.api.views._send_telegram_reply')
    @patch('core.api.views._process_telegram_message')
    def test_webhook_returns_partial_response_on_sync_failure(self, mock_process, mock_reply):
        """Webhook should return partial status when Google Sheets sync fails."""
        mock_process.return_value = {
            'status': 'partial',
            'message_id': 'MSG_PARTIAL',
            'error': 'Google Sheets sync failed',
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
        self.assertEqual(data['status'], 'partial')
        self.assertIn('warnings', data)
        self.assertEqual(data['warnings'][0], 'Google Sheets sync failed')
    
    def test_webhook_rejects_get(self):
        """Test webhook only accepts POST."""
        response = self.client.get('/api/webhook/telegram/')
        self.assertEqual(response.status_code, 405)
    
    def test_health_check(self):
        """Test health check endpoint."""
        response = self.client.get('/api/health/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')

    @override_settings(TELEGRAM_WEBHOOK_SECRET='', DEBUG=False)
    def test_webhook_requires_secret_in_production(self):
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

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['code'], 'WEBHOOK_SECRET_REQUIRED')

    @override_settings(TELEGRAM_WEBHOOK_SECRET='expected-secret', DEBUG=False)
    def test_webhook_rejects_invalid_secret(self):
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
            content_type='application/json',
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='wrong-secret',
        )

        self.assertEqual(response.status_code, 401)

    @override_settings(TELEGRAM_BOT_USERNAME='biogas_bot')
    @patch('core.api.views._process_single_message')
    def test_telegram_message_ignored_when_bot_not_tagged(self, mock_process):
        """Webhook messages should not process or sync unless the bot is tagged."""
        from core.api.views import _process_telegram_message

        result = _process_telegram_message({
            'message_id': 123,
            'from': {'first_name': 'Test'},
            'chat': {'id': -100123, 'type': 'group'},
            'date': 1711123456,
            'text': 'CUSTOMER COMPLAIN: no gas supply',
        })

        self.assertEqual(result['status'], 'ignored')
        mock_process.assert_not_called()

    @override_settings(TELEGRAM_BOT_USERNAME='biogas_bot')
    @patch('core.services.case_updates.handle_case_status_reply')
    @patch('core.api.views._process_single_message')
    def test_telegram_status_reply_can_be_untagged(
        self,
        mock_process,
        mock_update,
    ):
        """Untagged Status replies to case messages should route as updates."""
        from core.api.views import _process_telegram_message

        mock_update.return_value = {
            'status': 'command',
            'reply_text': 'OK. Case updated.',
        }

        result = _process_telegram_message({
            'message_id': 456,
            'from': {'first_name': 'Test'},
            'chat': {'id': -100123, 'type': 'group'},
            'date': 1711123456,
            'text': 'Status: resolved - repaired',
            'reply_to_message': {'message_id': 123},
        })

        self.assertEqual(result['status'], 'command')
        mock_update.assert_called_once()
        self.assertEqual(
            mock_update.call_args.kwargs['reply_to_telegram_message_id'],
            '123',
        )
        mock_process.assert_not_called()

    @override_settings(TELEGRAM_BOT_USERNAME='biogas_bot')
    @patch('core.api.views._process_single_message')
    def test_telegram_status_without_reply_returns_help(self, mock_process):
        """Tagged Status text without reply context should not create a case."""
        from core.api.views import _process_telegram_message

        result = _process_telegram_message({
            'message_id': 456,
            'from': {'first_name': 'Test'},
            'chat': {'id': -100123, 'type': 'group'},
            'date': 1711123456,
            'text': '@biogas_bot Status: resolved - repaired',
        })

        self.assertEqual(result['status'], 'command')
        self.assertIn('/update MSG_ID', result['reply_text'])
        mock_process.assert_not_called()

    @override_settings(TELEGRAM_BOT_USERNAME='biogas_bot')
    @patch('core.api.views._process_single_message')
    def test_telegram_message_processes_tagged_content_only(self, mock_process):
        """The bot mention is stripped before parsing real message content."""
        from core.api.views import _process_telegram_message

        mock_process.return_value = {'status': 'success', 'message_id': 'MSG_TEST'}
        result = _process_telegram_message({
            'message_id': 123,
            'from': {'first_name': 'Test'},
            'chat': {'id': -100123, 'type': 'group'},
            'date': 1711123456,
            'text': '@biogas_bot CUSTOMER COMPLAIN: no gas supply',
        })

        self.assertEqual(result['status'], 'success')
        self.assertEqual(
            mock_process.call_args.kwargs['content'],
            'CUSTOMER COMPLAIN: no gas supply',
        )

    @override_settings(TELEGRAM_BOT_USERNAME='biogas_bot')
    @patch('core.api.views._process_single_message')
    def test_order_approval_message_in_case_group_returns_config_help(self, mock_process):
        """Order-style messages should not fall through to complaint sheet sync."""
        from core.api.views import _process_telegram_message
        from core.services.group_config import GroupRegistry

        GroupSheetConfiguration.objects.create(
            group_id='-100123',
            display_name='Misconfigured order group',
            enabled=True,
            sheet_id='sheet_order',
            sheet_name='Orders',
            workflow={},
        )
        GroupRegistry._instance = None

        result = _process_telegram_message({
            'message_id': 123,
            'from': {'first_name': 'Test'},
            'chat': {'id': -100123, 'type': 'supergroup'},
            'date': 1711123456,
            'text': '@biogas_bot\nID: 113650221\nCUSTOMER NAME: Jane Doe',
        })

        self.assertEqual(result['status'], 'command')
        self.assertIn('not configured for Order Approval', result['reply_text'])
        self.assertIn('Workflow preset to Order Approval', result['reply_text'])
        mock_process.assert_not_called()

    @override_settings(TELEGRAM_BOT_USERNAME='biogas_bot')
    @patch('core.api.views._process_single_message')
    def test_telegram_last_command_does_not_process_complaint(self, mock_process):
        """Commands should return a command response without storing/syncing."""
        from core.api.views import _process_telegram_message

        create_parsed_case(
            'MSG_RECENT',
            group_id='-100123',
            customer_name='Recent Customer',
            description='Recent issue',
        )

        result = _process_telegram_message({
            'message_id': 123,
            'from': {'first_name': 'Test'},
            'chat': {'id': -100123, 'type': 'group'},
            'date': 1711123456,
            'text': '@biogas_bot /last 1',
        })

        self.assertEqual(result['status'], 'command')
        self.assertIn('RECENT CUSTOMER', result['reply_text'])
        self.assertIn('Recent issue', result['reply_text'])
        self.assertNotIn('MSG_RECENT', result['reply_text'])
        mock_process.assert_not_called()

    @override_settings(TELEGRAM_BOT_USERNAME='biogas_bot')
    @patch('core.api.views._process_single_message')
    def test_telegram_message_processes_multiple_tagged_complaint_cases(
        self,
        mock_process,
    ):
        """Multiple complaint cases in one tagged message should process separately."""
        from core.api.views import _process_telegram_message

        mock_process.side_effect = [
            {'status': 'success', 'message_id': 'MSG_1'},
            {'status': 'success', 'message_id': 'MSG_2'},
        ]
        payload_text = """@biogas_bot
*CUSTOMER COMPLAIN*
NAME: Jane Doe
TEL: 0712345678
ID: A123
NATURE OF THE PROBLEM: No gas supply
*CUSTOMER COMPLAIN: The system has stopped producing gas

*CUSTOMER COMPLAIN*
NAME: John Smith
TEL: 0798765432
ID: B456
NATURE OF THE PROBLEM: Gas leakage
*CUSTOMER COMPLAIN: Gas smell around the digester"""

        result = _process_telegram_message({
            'message_id': 123,
            'from': {'first_name': 'Test'},
            'chat': {'id': -100123, 'type': 'group'},
            'date': 1711123456,
            'text': payload_text,
        })

        self.assertEqual(result['status'], 'batch_processed')
        self.assertEqual(result['total'], 2)
        self.assertEqual(result['success'], 2)
        self.assertEqual(mock_process.call_count, 2)
        self.assertEqual(
            mock_process.call_args_list[0].kwargs['telegram_message_id'],
            '123_0',
        )
        self.assertEqual(
            mock_process.call_args_list[1].kwargs['telegram_message_id'],
            '123_1',
        )
        self.assertEqual(
            mock_process.call_args_list[0].kwargs['source_telegram_message_id'],
            '123',
        )
        self.assertEqual(mock_process.call_args_list[0].kwargs['batch_index'], 0)
        self.assertEqual(mock_process.call_args_list[1].kwargs['batch_index'], 1)
        self.assertIn('Jane Doe', mock_process.call_args_list[0].kwargs['content'])
        self.assertIn('John Smith', mock_process.call_args_list[1].kwargs['content'])

    @override_settings(TELEGRAM_BOT_TOKEN='token')
    @patch('core.api.views.requests.post')
    def test_telegram_reply_uses_plain_ascii_status_text(self, mock_post):
        """Telegram replies should not contain mojibake status prefixes."""
        from core.api.views import _send_telegram_reply

        _send_telegram_reply(
            {
                'message_id': 123,
                'chat': {'id': -100123},
            },
            {
                'status': 'success',
                'message_id': 'MSG_REPLY_1',
                'captured_fields': {
                    'Sender': 'Agent',
                    'Customer Name': 'Jane',
                    'Phone Number': '0712345678',
                    'Complaint Description': 'No gas supply',
                },
            },
        )

        text = mock_post.call_args.kwargs['data']['text']
        self.assertIn('OK. Message received and saved successfully', text)
        self.assertIn('Case ID: MSG_REPLY_1', text)
        self.assertIn('Captured:\n', text)
        self.assertIn('Sender: Agent', text)
        self.assertIn('Customer Name: Jane', text)
        self.assertIn('Phone Number: 0712345678', text)
        self.assertIn('Complaint Description: No gas supply', text)
        self.assertNotIn('Captured: Customer Name', text)
        self.assertTrue(text.isascii())

    @override_settings(TELEGRAM_BOT_TOKEN='token')
    @patch('core.api.views.requests.post')
    def test_telegram_reply_sends_command_text(self, mock_post):
        """Command responses should be sent directly to Telegram."""
        from core.api.views import _send_telegram_reply

        _send_telegram_reply(
            {
                'message_id': 123,
                'chat': {'id': -100123},
            },
            {
                'status': 'command',
                'reply_text': 'Latest 1 case(s):\n1. MSG_RECENT',
            },
        )

        text = mock_post.call_args.kwargs['data']['text']
        self.assertEqual(text, 'Latest 1 case(s):\n1. MSG_RECENT')

    @patch('core.services.storage.process_and_store_message')
    @patch('core.services.group_config.GroupRegistry.get_instance')
    def test_process_single_message_passes_group_sheet_name(
        self,
        mock_registry_get_instance,
        mock_process_store,
    ):
        """Group-specific worksheet tabs should be forwarded to storage."""
        from core.api.views import _process_single_message

        registry = MagicMock()
        registry.get_group.return_value = MagicMock(
            sheet_id='sheet_123',
            sheet_name='Support Tickets',
            sheet_schema_config={'field_headers': {'message_id': 'Backend ID'}},
        )
        mock_registry_get_instance.return_value = registry

        parsed = MagicMock()
        parsed.message_id = 'MSG_TEST'
        parsed._processing_status = 'success'
        mock_process_store.return_value = parsed

        result = _process_single_message(
            telegram_message_id='123',
            content='CUSTOMER COMPLAIN: no gas',
            sender='Agent',
            has_image=False,
            received_at=timezone.now(),
            group_id='-100123',
        )

        self.assertEqual(result['status'], 'success')
        self.assertEqual(
            mock_process_store.call_args.kwargs['sheet_name'],
            'Support Tickets',
        )
        self.assertEqual(mock_process_store.call_args.kwargs['sheet_id'], 'sheet_123')
        self.assertEqual(
            mock_process_store.call_args.kwargs['sheet_schema'],
            {'field_headers': {'message_id': 'Backend ID'}},
        )


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
        self.assertEqual(row[0], '', "Complaint ID (bot leaves blank for FORMULA field)")
        self.assertEqual(row[1], 'MSG_TEST_SHEET', "message_id dedup key")
        
        # [2-9] Bot intake fields
        self.assertIsInstance(row[2], str)  # Date Reported
        self.assertEqual(row[3], 'JANE DOE', "Customer Name (CAPITALIZED by bot)")
        self.assertEqual(row[4], 'A12345', "Customer ID")
        self.assertEqual(row[5], '0712345678', "Phone Number")
        self.assertEqual(row[6], 'John', "JBL Reported By uses the message sender")
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
