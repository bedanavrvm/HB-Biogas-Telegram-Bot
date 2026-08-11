from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import JawabuFarmerMaster, PortalVoiceTranscriptionAttempt
from core.services.portal_voice import VoiceInputError, create_transcription, resolve_transcription


VOICE_SETTINGS = {
    'PORTAL_VOICE_INPUT_ENABLED': True,
    'PORTAL_VOICE_PROVIDER': 'groq',
    'GROQ_API_KEY': 'test-key',
    'PORTAL_VOICE_MODEL': 'whisper-large-v3',
    'PORTAL_VOICE_MAX_SECONDS': 30,
    'PORTAL_VOICE_DAILY_REQUEST_LIMIT': 1000,
    'PORTAL_VOICE_DAILY_AUDIO_SECONDS': 14400,
    'PORTAL_VOICE_USER_DAILY_REQUEST_LIMIT': 60,
    'PORTAL_VOICE_RETRY_RETENTION_MINUTES': 60,
}


@override_settings(**VOICE_SETTINGS)
class PortalVoiceServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='voice-officer')
        self.other_user = get_user_model().objects.create_user(username='other-officer')
        self.farmer = JawabuFarmerMaster.objects.create(customer_name='Synthetic Farmer')

    @patch('core.services.portal_voice._call_groq', return_value=('Visit completed successfully.', 2100, 'groq-test'))
    @patch('core.services.portal_voice._drive_upload', return_value='drive-test')
    def test_create_is_idempotent_for_user_request_key(self, drive_upload, call_groq):
        first, replayed = create_transcription(
            user=self.user, farmer=self.farmer, field_name='jbl_visit_comment',
            request_id='voice-request-1', duration_ms=2200,
            audio=b'synthetic-audio', mime_type='audio/webm',
        )
        second, second_replayed = create_transcription(
            user=self.user, farmer=self.farmer, field_name='jbl_visit_comment',
            request_id='voice-request-1', duration_ms=2200,
            audio=b'synthetic-audio', mime_type='audio/webm',
        )
        self.assertFalse(replayed)
        self.assertTrue(second_replayed)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(call_groq.call_count, 1)
        self.assertEqual(drive_upload.call_count, 1)

    @patch('core.services.portal_voice._trash_drive_file')
    def test_acceptance_clears_transcript_and_audio(self, trash_file):
        attempt = PortalVoiceTranscriptionAttempt.objects.create(
            user=self.user, farmer=self.farmer, field_name='final_decision_comment',
            request_id='voice-request-2', audio_hash='a' * 64, audio_size=10,
            audio_mime_type='audio/webm', duration_ms=1000, status='transcribed',
            transcript='Approved after call.', drive_file_id='drive-test', deletion_status='pending',
            expires_at=timezone.now() + timedelta(hours=1),
        )
        resolve_transcription(
            attempt_id=attempt.pk, user=self.user, farmer=self.farmer,
            field_name='final_decision_comment', accepted_text='Approved after the call.',
        )
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, 'accepted')
        self.assertEqual(attempt.transcript, '')
        self.assertEqual(attempt.deletion_status, 'deleted')
        self.assertIsNotNone(attempt.edit_distance)
        trash_file.assert_called_once_with('drive-test')

    def test_other_user_cannot_resolve_attempt(self):
        attempt = PortalVoiceTranscriptionAttempt.objects.create(
            user=self.user, farmer=self.farmer, field_name='jbl_visit_comment',
            request_id='voice-request-3', audio_hash='b' * 64, audio_size=10,
            audio_mime_type='audio/webm', duration_ms=1000, status='transcribed',
            transcript='Private note.', expires_at=timezone.now() + timedelta(hours=1),
        )
        with self.assertRaises(VoiceInputError) as caught:
            resolve_transcription(
                attempt_id=attempt.pk, user=self.other_user, farmer=self.farmer,
                field_name='jbl_visit_comment', accepted=False,
            )
        self.assertEqual(caught.exception.status, 404)

    @override_settings(PORTAL_VOICE_USER_DAILY_REQUEST_LIMIT=1)
    @patch('core.services.portal_voice._call_groq', return_value=('First note.', 1000, 'groq-test'))
    @patch('core.services.portal_voice._drive_upload', return_value='drive-test')
    def test_daily_user_limit_uses_durable_attempts(self, _drive_upload, _call_groq):
        create_transcription(
            user=self.user, farmer=self.farmer, field_name='jbl_visit_comment',
            request_id='voice-request-4', duration_ms=1000,
            audio=b'first-audio', mime_type='audio/webm',
        )
        with self.assertRaises(VoiceInputError) as caught:
            create_transcription(
                user=self.user, farmer=self.farmer, field_name='jbl_visit_comment',
                request_id='voice-request-5', duration_ms=1000,
                audio=b'second-audio', mime_type='audio/webm',
            )
        self.assertEqual(caught.exception.code, 'rate_limited')
