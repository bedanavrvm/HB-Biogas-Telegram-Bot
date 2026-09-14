"""Synthetic capture fixtures; no Google/Telegram writes or customer files."""
import io
import random
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

from core.services.jbl_visit_documents import (
    VisitDocumentError, prepare_visit_documents, validated_image,
)
from core.services.jawabu_pipeline import (
    _validate_jbl_media_files, append_jbl_media_uploads, complete_jbl_visit,
    validate_jbl_visit_upload_batch,
)


def photo(name='photo.jpg', seed=1, size=(640, 480)):
    pixels = random.Random(seed).randbytes(size[0] * size[1] * 3)
    output = io.BytesIO()
    with Image.frombytes('RGB', size, pixels) as image:
        image.save(output, 'JPEG', quality=85)
    return SimpleUploadedFile(name, output.getvalue(), content_type='image/jpeg')


def pdf_fixture(pages=2):
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=595, height=842)
        stream = DecodedStreamObject()
        stream.set_data(b'% synthetic fixture padding\n' * 200)
        page[NameObject('/Contents')] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def captures():
    return {'CLIENT_ID_FRONT': [photo('front.jpg', 1)],
            'CLIENT_ID_BACK': [photo('back.jpg', 2)],
            'LAF_PAGE_1': [photo('page-1.jpg', 3)],
            'LAF_PAGE_2': [photo('page-2.jpg', 4)],
            'JBL_VISIT_PHOTO': [photo('site.jpg', 5)]}


def controlled_renderer(category, images):
    return pdf_fixture(1 if category == 'CLIENT_ID' else 2)


@override_settings(MEDIA_MAX_FILE_SIZE_MB=20, PORTAL_JBL_VISIT_MAX_FILES=6,
                   PORTAL_JBL_VISIT_MAX_TOTAL_UPLOAD_MB=40)
class VisitDocumentTests(SimpleTestCase):
    @patch('core.services.jbl_visit_documents.render_document', side_effect=controlled_renderer)
    def test_complete_captures_produce_two_canonical_documents_and_individual_photos(self, renderer):
        source = captures()
        result = prepare_visit_documents(source)
        self.assertEqual(set(result), {'CLIENT_ID', 'LAF', 'JBL_VISIT_PHOTO'})
        self.assertEqual(len(PdfReader(result['CLIENT_ID'][0]).pages), 1)
        self.assertEqual(len(PdfReader(result['LAF'][0]).pages), 2)
        self.assertIs(result['JBL_VISIT_PHOTO'][0], source['JBL_VISIT_PHOTO'][0])
        self.assertEqual([call.args[0] for call in renderer.call_args_list], ['CLIENT_ID', 'LAF'])
        for category in ('CLIENT_ID', 'LAF'):
            result[category][0].seek(0)
            self.assertEqual(_validate_jbl_media_files(result[category], category), '')

    @patch('core.services.jbl_visit_documents.render_document', side_effect=controlled_renderer)
    def test_repeated_captures_generate_stable_hashes_and_bind_order(self, _renderer):
        first = prepare_visit_documents(captures())
        second = prepare_visit_documents(captures())
        self.assertEqual(first['LAF'][0].read(), second['LAF'][0].read())
        reversed_source = captures()
        reversed_source['LAF_PAGE_1'], reversed_source['LAF_PAGE_2'] = reversed_source['LAF_PAGE_2'], reversed_source['LAF_PAGE_1']
        reversed_result = prepare_visit_documents(reversed_source)
        first['LAF'][0].seek(0)
        self.assertNotEqual(first['LAF'][0].read(), reversed_result['LAF'][0].read())

    @patch('core.services.jbl_visit_documents.render_document')
    def test_missing_side_is_named_before_rendering(self, renderer):
        with self.assertRaises(VisitDocumentError) as caught:
            prepare_visit_documents({'CLIENT_ID_FRONT': [photo()]})
        self.assertEqual(caught.exception.field, 'client_id_back')
        renderer.assert_not_called()

    def test_multiple_files_in_one_slot_are_rejected(self):
        with self.assertRaises(VisitDocumentError) as caught:
            prepare_visit_documents({'LAF_PAGE_1': [photo(), photo(seed=2)], 'LAF_PAGE_2': [photo(seed=3)]})
        self.assertEqual(caught.exception.field, 'laf_page_1')

    def test_identical_captures_do_not_complete_a_document(self):
        with self.assertRaisesMessage(VisitDocumentError, 'same photo'):
            prepare_visit_documents({'CLIENT_ID_FRONT': [photo('a.jpg')], 'CLIENT_ID_BACK': [photo('b.jpg')]})

    def test_corrupt_mismatched_and_small_content_is_rejected(self):
        for uploaded in (SimpleUploadedFile('bad.jpg', b'x' * 5000),
                         photo('not-a-png.png'), SimpleUploadedFile('tiny.jpg', b'x')):
            with self.subTest(name=uploaded.name), self.assertRaises(VisitDocumentError):
                validated_image(uploaded, field='laf_page_1')
            self.assertEqual(uploaded.tell(), 0)

    def test_metadata_is_removed_and_portrait_orientation_preserved(self):
        image = validated_image(photo(size=(480, 640)), field='client_id_front')
        with Image.open(io.BytesIO(image)) as decoded:
            self.assertEqual(decoded.size, (480, 640))
            self.assertFalse(decoded.getexif())

    @patch('core.services.jbl_visit_documents.render_document', return_value=pdf_fixture(1))
    def test_wrong_generated_laf_page_count_fails_safely(self, _renderer):
        with self.assertRaisesMessage(VisitDocumentError, 'could not be prepared'):
            prepare_visit_documents({'LAF_PAGE_1': [photo(seed=1)], 'LAF_PAGE_2': [photo(seed=2)]})

    def test_supporting_count_excludes_the_four_fixed_captures(self):
        source = captures()
        source['JBL_VISIT_PHOTO'] = [photo(seed=seed) for seed in range(6)]
        self.assertTrue(validate_jbl_visit_upload_batch(source)[0])
        source['JBL_VISIT_PHOTO'].append(photo(seed=9))
        self.assertEqual(validate_jbl_visit_upload_batch(source)[2], 'jbl_visit_file_count_exceeded')

    @override_settings(PORTAL_JBL_VISIT_MAX_TOTAL_UPLOAD_MB=1)
    def test_combined_size_includes_document_captures(self):
        source = {slot: [SimpleUploadedFile('image.jpg', b'x' * 300000)]
                  for slot in ('CLIENT_ID_FRONT', 'CLIENT_ID_BACK', 'LAF_PAGE_1', 'LAF_PAGE_2')}
        self.assertEqual(validate_jbl_visit_upload_batch(source)[2], 'jbl_visit_total_upload_exceeded')

    def test_pdf_page_contract_cannot_be_bypassed_by_direct_service_upload(self):
        self.assertIn('2-page PDF', _validate_jbl_media_files(
            [SimpleUploadedFile('laf.pdf', pdf_fixture(1))], 'LAF'))

    @patch('core.services.jawabu_pipeline.preflight_jbl_visit_completion', return_value=(True, '', False))
    @patch('core.services.jawabu_approvals.visit_evidence_status', return_value={})
    @patch('core.services.jbl_visit_documents.render_document', side_effect=controlled_renderer)
    @patch('core.services.jawabu_pipeline.append_jbl_media_uploads')
    @patch('core.services.jawabu_pipeline.log_jbl_visit', return_value=(True, ''))
    def test_complete_submission_chains_its_revisions_and_partial_storage_does_not_log(
        self, log_visit, upload, _render, _evidence, _preflight,
    ):
        farmer = SimpleNamespace(refresh_from_db=Mock())
        upload.return_value = (True, '', {'stored_count': 3, 'errors': [], 'workflow_revision': 4})
        kwargs = dict(visit_date=date(2026, 9, 1), officer='Synthetic officer',
                      visit_status='Visited, Awaiting Credit Analysis', expected_revision=1)
        ok, error, result = complete_jbl_visit(farmer, categorized_files=captures(), **kwargs)
        self.assertTrue(ok, error)
        self.assertEqual(log_visit.call_args.kwargs['expected_revision'], 4)
        self.assertEqual(set(upload.call_args.kwargs['categorized_files']), {'CLIENT_ID', 'LAF', 'JBL_VISIT_PHOTO'})
        log_visit.reset_mock()
        upload.return_value = (True, '', {'stored_count': 2, 'errors': [{'category': 'LAF'}]})
        ok, _, result = complete_jbl_visit(farmer, categorized_files=captures(), **kwargs)
        self.assertFalse(ok)
        self.assertTrue(result['evidence_saved'])
        self.assertFalse(result['visit_logged'])
        log_visit.assert_not_called()

    @patch('core.services.jawabu_pipeline.preflight_jbl_visit_completion', return_value=(True, '', False))
    @patch('core.services.jawabu_approvals.visit_evidence_status', return_value={'LAF': 1, 'JBL_VISIT_PHOTO': 1})
    @patch('core.services.jawabu_pipeline.append_jbl_media_uploads')
    def test_missing_id_prevents_forwarding_without_any_upload(self, upload, _evidence, _preflight):
        ok, _, result = complete_jbl_visit(SimpleNamespace(), categorized_files={},
            visit_date=date(2026, 9, 1), officer='Synthetic', visit_status='Visited, Awaiting Credit Analysis')
        self.assertFalse(ok)
        self.assertEqual(result['missing_evidence'], ['CLIENT_ID'])
        upload.assert_not_called()

    @patch('core.services.jawabu_pipeline.preflight_jbl_visit_completion', return_value=(True, '', True))
    @patch('core.services.jbl_visit_documents.render_document')
    def test_committed_retry_does_not_require_recapture_or_repeat_rendering(self, renderer, _preflight):
        ok, _, result = complete_jbl_visit(SimpleNamespace(refresh_from_db=Mock()), categorized_files={},
            visit_date=date(2026, 9, 1), officer='Synthetic', visit_status='Visited, Awaiting Credit Analysis')
        self.assertTrue(ok)
        self.assertTrue(result['already_completed'])
        renderer.assert_not_called()

    @patch('core.services.jawabu_pipeline.append_jbl_media_links', return_value=(True, '', {
        'stored_count': 1, 'skipped_count': 0, 'warnings': ['Could not store a photo.'], 'workflow_revision': 2,
    }))
    def test_partial_supporting_category_is_reported_as_incomplete(self, _upload):
        ok, _, result = append_jbl_media_uploads(SimpleNamespace(jbl_media_urls=''),
            categorized_files={'JBL_VISIT_PHOTO': [photo(seed=1), photo(seed=2)]})
        self.assertTrue(ok)  # Some evidence survived; compound completion rejects errors.
        self.assertTrue(result['partial'])
        self.assertEqual(result['errors'][0]['category'], 'JBL_VISIT_PHOTO')

    def test_real_weasyprint_layout_when_native_libraries_are_available(self):
        try:
            import weasyprint  # noqa: F401
        except OSError:
            self.skipTest('WeasyPrint native libraries are not installed in this Windows environment.')
        result = prepare_visit_documents(captures())
        id_pdf = PdfReader(result['CLIENT_ID'][0])
        laf_pdf = PdfReader(result['LAF'][0])
        self.assertEqual(len(id_pdf.pages), 1)
        self.assertEqual(len(laf_pdf.pages), 2)
        self.assertEqual(len(id_pdf.pages[0].images), 2)
        # WeasyPrint shares the image resource dictionary across pages. Check
        # the actual draw commands, not the resource count on each page.
        import re

        id_draws = re.findall(rb'/([^\s/]+) Do\b', id_pdf.pages[0].get_contents().get_data())
        laf_draws = [re.findall(rb'/([^\s/]+) Do\b', page.get_contents().get_data())
                     for page in laf_pdf.pages]
        self.assertEqual(len(id_draws), 2)
        self.assertEqual(len(set(id_draws)), 2)
        self.assertEqual([len(draws) for draws in laf_draws], [1, 1])
        self.assertNotEqual(laf_draws[0][0], laf_draws[1][0])
        repeated = prepare_visit_documents(captures())
        for category in ('CLIENT_ID', 'LAF'):
            result[category][0].seek(0)
            repeated[category][0].seek(0)
            self.assertEqual(result[category][0].read(), repeated[category][0].read())
