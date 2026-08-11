from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import JawabuFarmerMaster, PortalVoiceTranscriptionAttempt
from core.services.portal_voice import VoiceInputError, _call_groq, create_transcription, resolve_transcription


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

    @patch('core.services.portal_voice._call_groq', return_value=('Visit completed successfully.', 2100, 'groq-test', 'en', -0.1))
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
        call_groq.assert_called_once_with(b'synthetic-audio', 'audio/webm', 'auto')
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
    @patch('core.services.portal_voice._call_groq', return_value=('First note.', 1000, 'groq-test', 'en', -0.2))
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

    @patch('core.services.portal_voice._call_groq', return_value=('Ziara imekamilika.', 1500, 'groq-sw', 'sw', -0.08))
    @patch('core.services.portal_voice._drive_upload', return_value='drive-sw')
    def test_swahili_mode_is_passed_to_provider_and_audited(self, _drive_upload, call_groq):
        attempt, replayed = create_transcription(
            user=self.user, farmer=self.farmer, field_name='jbl_visit_comment',
            request_id='voice-request-sw', duration_ms=1600,
            audio=b'swahili-audio', mime_type='audio/webm', language_mode='sw',
        )
        self.assertFalse(replayed)
        call_groq.assert_called_once_with(b'swahili-audio', 'audio/webm', 'sw')
        self.assertEqual(attempt.requested_language, 'sw')
        self.assertEqual(attempt.detected_language, 'sw')
        self.assertEqual(attempt.average_log_probability, -0.08)

    @patch('core.services.portal_voice._call_groq', return_value=('Ziara imerudiwa.', 1400, 'groq-retry', 'sw', -0.05))
    @patch('core.services.portal_voice._drive_download', return_value=b'retained-audio')
    def test_retry_can_change_retained_audio_from_auto_to_swahili(self, drive_download, call_groq):
        source = PortalVoiceTranscriptionAttempt.objects.create(
            user=self.user, farmer=self.farmer, field_name='jbl_visit_comment',
            request_id='voice-source-auto', audio_hash='c' * 64, audio_size=14,
            audio_mime_type='audio/webm', duration_ms=1500, status='transcribed',
            transcript='Poor automatic result.', drive_file_id='drive-retained',
            deletion_status='pending', requested_language='auto',
            expires_at=timezone.now() + timedelta(hours=1),
        )

        retried, replayed = create_transcription(
            user=self.user, farmer=self.farmer, field_name='jbl_visit_comment',
            request_id='voice-retry-sw', duration_ms=0, source_attempt=source,
            language_mode='sw',
        )

        self.assertFalse(replayed)
        self.assertEqual(retried.source_attempt, source)
        self.assertEqual(retried.requested_language, 'sw')
        drive_download.assert_called_once_with('drive-retained')
        call_groq.assert_called_once_with(b'retained-audio', 'audio/webm', 'sw')

    def test_unsupported_language_is_rejected_before_provider_call(self):
        with self.assertRaises(VoiceInputError) as caught:
            create_transcription(
                user=self.user, farmer=self.farmer, field_name='jbl_visit_comment',
                request_id='voice-request-unsupported', duration_ms=1000,
                audio=b'audio', mime_type='audio/webm', language_mode='fr',
            )
        self.assertEqual(caught.exception.code, 'unsupported_language')

    @patch('core.services.portal_voice.requests.post')
    def test_groq_request_forces_swahili_and_uses_swahili_prompt(self, post):
        response = Mock(status_code=200, headers={'x-request-id': 'groq-request'})
        response.json.return_value = {
            'text': 'Mkulima amelipa amana.', 'duration': 1.2, 'language': 'sw',
            'segments': [{'avg_logprob': -0.12}, {'avg_logprob': -0.08}],
        }
        post.return_value = response

        result = _call_groq(b'swahili-audio', 'audio/webm', 'sw')

        request_data = post.call_args.kwargs['data']
        self.assertEqual(request_data['language'], 'sw')
        self.assertIn('mkulima', request_data['prompt'])
        self.assertEqual(result[3], 'sw')
        self.assertAlmostEqual(result[4], -0.1)

    @patch('core.services.portal_voice.requests.post')
    def test_groq_auto_mode_omits_language_parameter(self, post):
        response = Mock(status_code=200, headers={})
        response.json.return_value = {'text': 'Mixed language note.', 'duration': 1, 'segments': []}
        post.return_value = response

        _call_groq(b'code-switched-audio', 'audio/webm', 'auto')

        self.assertNotIn('language', post.call_args.kwargs['data'])
