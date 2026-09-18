"""Server-owned state transitions for TAT credit assessments."""

from __future__ import annotations

import hashlib
import json
import re
import base64
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import PurePath
from typing import Any, Iterable

from cryptography.fernet import Fernet, InvalidToken
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .models import (
    AnalysisPackage,
    AnalysisQuestion,
    AssessmentDecision,
    AssessmentDocument,
    AssessmentEvent,
    AssessmentSecret,
    CreditAssessment,
    QuestionResponse,
    QuestionValidationEvent,
    StatementMailReceipt,
)


MPESA_FILENAME_RE = re.compile(
    r'^MPESA_Statement_(?P<first>\d{4}-\d{2}-\d{2})_to_'
    r'(?P<second>\d{4}-\d{2}-\d{2})_(?P<phone>254[0-9xX*]+)\.pdf$',
    re.IGNORECASE,
)
MASKED_PHONE_RE = re.compile(r'254[0-9xX*]{6,15}')
ROLE_ALIASES = {'CREDIT_ANALYST': 'CA'}
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024


class AssessmentError(ValueError):
    def __init__(self, message: str, *, code: str = 'credit_assessment_invalid', status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class ParsedStatementName:
    period_start: date
    period_end: date
    masked_phone: str
    full_year: bool


def parse_statement_filename(filename: str) -> ParsedStatementName:
    match = MPESA_FILENAME_RE.match(PurePath(str(filename or '')).name)
    if not match:
        raise AssessmentError(
            'Use the original M-PESA statement PDF filename.',
            code='statement_filename_invalid',
        )
    try:
        first = date.fromisoformat(match.group('first'))
        second = date.fromisoformat(match.group('second'))
    except ValueError as exc:
        raise AssessmentError('The statement filename contains an invalid date.', code='statement_period_invalid') from exc
    start, end = sorted((first, second))
    return ParsedStatementName(
        period_start=start,
        period_end=end,
        masked_phone=match.group('phone'),
        full_year=end >= start + relativedelta(months=12),
    )


def normalize_phone(value: str) -> str:
    digits = re.sub(r'\D', '', str(value or ''))
    if digits.startswith('0') and len(digits) == 10:
        return f'254{digits[1:]}'
    if digits.startswith('7') and len(digits) == 9:
        return f'254{digits}'
    return digits


def masked_phone_matches(masked: str, full_phone: str) -> bool:
    normalized = normalize_phone(full_phone)
    masked_value = str(masked or '').strip()
    if not normalized or not masked_value:
        return False
    # Provider exports are inconsistent about how many x/* characters replace
    # the hidden middle digits. Match the visible prefix and suffix, not the
    # placeholder count.
    hidden = re.search(r'[xX*]+', masked_value)
    if not hidden:
        return normalized == normalize_phone(masked_value)
    prefix = re.sub(r'\D', '', masked_value[:hidden.start()])
    suffix = re.sub(r'\D', '', masked_value[hidden.end():])
    return bool(prefix and suffix and normalized.startswith(prefix) and normalized.endswith(suffix) and len(normalized) >= len(prefix) + len(suffix))


def _roles(user: dict) -> set[str]:
    roles = {str(value or '').strip().upper() for value in (user.get('roles') or [])}
    return {ROLE_ALIASES.get(role, role) for role in roles}


def _require_role(user: dict, *allowed: str) -> None:
    roles = _roles(user)
    if 'IT' not in roles and not roles.intersection({ROLE_ALIASES.get(role, role) for role in allowed}):
        raise AssessmentError('This action is assigned to another role.', code='credit_assessment_permission_denied', status=403)


def _actor(user: dict):
    actor = user.get('_canonical_user')
    if actor is None:
        raise AssessmentError('Your staff identity could not be resolved.', code='credit_assessment_identity_missing', status=403)
    return actor


def _expect_revision(assessment: CreditAssessment, expected_revision: Any) -> None:
    try:
        expected = int(expected_revision)
    except (TypeError, ValueError) as exc:
        raise AssessmentError('Refresh the case before continuing.', code='credit_assessment_revision_required', status=409) from exc
    if expected != assessment.revision:
        raise AssessmentError('This assessment changed. Refresh it before continuing.', code='credit_assessment_revision_conflict', status=409)


def _existing_event(assessment: CreditAssessment, request_id: str) -> bool:
    return bool(request_id and assessment.events.filter(request_id=request_id).exists())


def _event(assessment: CreditAssessment, action: str, actor, request_id: str, metadata: dict | None = None) -> None:
    AssessmentEvent.objects.create(
        assessment=assessment,
        action=action,
        revision=assessment.revision,
        actor=actor,
        request_id=request_id,
        metadata=metadata or {},
    )


def _advance(assessment: CreditAssessment, state: str) -> None:
    assessment.state = state
    assessment.revision += 1
    assessment.save(update_fields=['state', 'revision', 'updated_at'])


def _digest(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _keyring() -> tuple[str, bytes]:
    version = str(getattr(settings, 'CREDIT_ASSESSMENT_SECRET_KEY_VERSION', 'v1') or 'v1')
    configured = str(getattr(settings, 'CREDIT_ASSESSMENT_SECRET_KEY', '') or '').strip()
    key = configured.encode('ascii') if configured else base64.urlsafe_b64encode(hashlib.sha256(
        f'credit-assessment-passcode:{version}:{settings.SECRET_KEY}'.encode('utf-8'),
    ).digest())
    try:
        Fernet(key)
    except (ValueError, TypeError) as exc:
        raise AssessmentError('Statement passcode storage is not configured.', code='credit_assessment_secret_unavailable', status=503) from exc
    return version, key


def set_statement_passcode(assessment: CreditAssessment, passcode: str) -> None:
    cleaned = str(passcode or '').strip()
    if not cleaned or len(cleaned) > 128:
        raise AssessmentError('Enter the statement passcode.', code='statement_passcode_required')
    version, key = _keyring()
    ciphertext = Fernet(key).encrypt(cleaned.encode('utf-8')).decode('ascii')
    AssessmentSecret.objects.update_or_create(
        assessment=assessment,
        defaults={'ciphertext': ciphertext, 'key_version': version, 'destroyed_at': None},
    )


def statement_passcode_for_preview(assessment: CreditAssessment, user: dict) -> str:
    """Decrypt a statement passcode for an authorized in-memory preview.

    This never returns the value to the browser. The evidence endpoint records
    the preview itself; it must not incorrectly count this as a passcode reveal.
    """
    _require_role(user, 'BRO', 'BM', 'CA')
    secret = AssessmentSecret.objects.filter(assessment=assessment).first()
    if not secret or secret.destroyed_at or not secret.ciphertext:
        return ''
    version, key = _keyring()
    if secret.key_version != version:
        raise AssessmentError(
            'The statement passcode key requires rotation support.',
            code='statement_passcode_key_mismatch', status=503,
        )
    try:
        return Fernet(key).decrypt(secret.ciphertext.encode('ascii')).decode('utf-8')
    except InvalidToken as exc:
        raise AssessmentError(
            'The statement passcode could not be decrypted.',
            code='statement_passcode_unavailable', status=503,
        ) from exc


@transaction.atomic
def reveal_statement_passcode(assessment: CreditAssessment, user: dict, request_id: str) -> str:
    _require_role(user, 'CA')
    actor = _actor(user)
    locked = CreditAssessment.objects.select_for_update().get(pk=assessment.pk)
    try:
        secret = AssessmentSecret.objects.select_for_update().get(assessment=locked)
    except AssessmentSecret.DoesNotExist as exc:
        raise AssessmentError('No statement passcode is available.', code='statement_passcode_missing', status=404) from exc
    if secret.destroyed_at or not secret.ciphertext:
        raise AssessmentError('The statement passcode has already been destroyed.', code='statement_passcode_destroyed', status=410)
    value = statement_passcode_for_preview(locked, user)
    if not _existing_event(locked, request_id):
        secret.reveal_count += 1
        secret.last_revealed_at = timezone.now()
        secret.save(update_fields=['reveal_count', 'last_revealed_at', 'updated_at'])
        _event(locked, 'statement.passcode_revealed', actor, request_id, {'reveal_count': secret.reveal_count})
    return value


@transaction.atomic
def destroy_statement_passcode(assessment: CreditAssessment, user: dict, request_id: str) -> CreditAssessment:
    _require_role(user, 'CA')
    actor = _actor(user)
    locked = CreditAssessment.objects.select_for_update().get(pk=assessment.pk)
    secret = AssessmentSecret.objects.select_for_update().filter(assessment=locked).first()
    if not secret or secret.destroyed_at:
        return locked
    secret.ciphertext = ''
    secret.destroyed_at = timezone.now()
    secret.save(update_fields=['ciphertext', 'destroyed_at', 'updated_at'])
    _event(locked, 'statement.passcode_destroyed', actor, request_id)
    return locked


def _read_pdf(file_obj) -> tuple[bytes, str, str]:
    name = PurePath(str(getattr(file_obj, 'name', '') or 'document.pdf')).name[:255]
    data = file_obj.read(MAX_DOCUMENT_BYTES + 1)
    try:
        file_obj.seek(0)
    except (AttributeError, OSError):
        pass
    if len(data) > MAX_DOCUMENT_BYTES:
        raise AssessmentError('The PDF is larger than 20 MB.', code='credit_document_too_large')
    if not data.startswith(b'%PDF-'):
        raise AssessmentError('Upload a valid PDF document.', code='credit_document_invalid')
    return data, name, hashlib.sha256(data).hexdigest()


def _store_document(assessment: CreditAssessment, document_type: str, file_obj, actor) -> AssessmentDocument:
    data, name, content_hash = _read_pdf(file_obj)
    duplicate = assessment.documents.filter(document_type=document_type, content_hash=content_hash).first()
    if duplicate:
        return duplicate
    next_version = (assessment.documents.filter(document_type=document_type).aggregate(value=Max('version'))['value'] or 0) + 1
    from core.services.order_approval import GoogleDriveMediaStorage
    storage = GoogleDriveMediaStorage()
    drive_file_id, _drive_url = storage.upload(
        data,
        name,
        'application/pdf',
        assessment.tat_case.national_id or assessment.tat_case.case_id,
        timezone.now(),
        workflow_key='credit_assessment',
        record_type=document_type,
        record_key=str(assessment.pk),
    )
    assessment.documents.filter(document_type=document_type, is_current=True).update(is_current=False)
    return AssessmentDocument.objects.create(
        assessment=assessment,
        document_type=document_type,
        version=next_version,
        original_filename=name,
        mime_type='application/pdf',
        size=len(data),
        content_hash=content_hash,
        drive_file_id=drive_file_id,
        uploaded_by=actor,
    )


def current_document(assessment: CreditAssessment, document_type: str) -> AssessmentDocument | None:
    return assessment.documents.filter(document_type=document_type, is_current=True).order_by('-version').first()


@transaction.atomic
def get_or_create_assessment(*, case, user: dict, request_id: str = '') -> CreditAssessment:
    _require_role(user, 'BRO')
    actor = _actor(user)
    assessment, created = CreditAssessment.objects.select_for_update().get_or_create(
        tat_case=case,
        defaults={'created_by': actor},
    )
    if created:
        _event(assessment, 'assessment.created', actor, request_id)
    return assessment


def statement_candidates(assessment: CreditAssessment, user: dict, *, days: int = 30) -> list[StatementMailReceipt]:
    actor = _actor(user)
    cutoff = timezone.now() - timedelta(days=max(1, min(days, 180)))
    email = str(actor.email or '').strip().casefold()
    candidates = StatementMailReceipt.objects.filter(
        status__in=[StatementMailReceipt.STATUS_UNCLAIMED, StatementMailReceipt.STATUS_AMBIGUOUS],
        inbox_received_at__gte=cutoff,
        forwarding_sender__iexact=email,
    ).order_by('-inbox_received_at')
    return [item for item in candidates if masked_phone_matches(item.masked_phone_pattern, assessment.tat_case.primary_phone)]


@transaction.atomic
def confirm_statement(*, assessment: CreditAssessment, receipt_id: str, user: dict, expected_revision: Any, request_id: str) -> CreditAssessment:
    _require_role(user, 'BRO', 'CA')
    actor = _actor(user)
    locked = CreditAssessment.objects.select_for_update().select_related('tat_case').get(pk=assessment.pk)
    if _existing_event(locked, request_id):
        return locked
    _expect_revision(locked, expected_revision)
    receipt = StatementMailReceipt.objects.select_for_update().filter(pk=receipt_id).first()
    if not receipt or receipt.status not in {receipt.STATUS_UNCLAIMED, receipt.STATUS_AMBIGUOUS}:
        raise AssessmentError('This statement is no longer available.', code='statement_candidate_unavailable', status=409)
    if not masked_phone_matches(receipt.masked_phone_pattern, locked.tat_case.primary_phone):
        raise AssessmentError('The statement phone does not match this case.', code='statement_phone_mismatch', status=409)
    actor_email = str(actor.email or '').strip().casefold()
    if 'IT' not in _roles(user) and receipt.forwarding_sender.casefold() != actor_email and 'CA' not in _roles(user):
        raise AssessmentError('This statement was forwarded by another staff member.', code='statement_sender_mismatch', status=403)
    receipt.status = receipt.STATUS_LINKED
    receipt.save(update_fields=['status'])
    locked.statement_receipt = receipt
    locked.statement_period_start = receipt.statement_period_start
    locked.statement_period_end = receipt.statement_period_end
    locked.statement_full_year = receipt.statement_full_year
    locked.revision += 1
    locked.save(update_fields=['statement_receipt', 'statement_period_start', 'statement_period_end', 'statement_full_year', 'revision', 'updated_at'])
    _event(locked, 'statement.confirmed', actor, request_id, {'receipt_id': str(receipt.pk), 'full_year': receipt.statement_full_year})
    return locked


@transaction.atomic
def submit_pre_appraisal(
    *, assessment: CreditAssessment, user: dict, expected_revision: Any, request_id: str,
    pre_appraisal_file, signed_laf_reference: str, signed_laf_hash: str, passcode: str,
) -> CreditAssessment:
    _require_role(user, 'BRO')
    actor = _actor(user)
    locked = CreditAssessment.objects.select_for_update().select_related('tat_case', 'statement_receipt').get(pk=assessment.pk)
    if _existing_event(locked, request_id):
        return locked
    _expect_revision(locked, expected_revision)
    if locked.state not in {locked.STATE_DRAFT, locked.STATE_RETURNED_PRE_ANALYSIS}:
        raise AssessmentError('This pre-appraisal is no longer editable.', code='pre_appraisal_locked', status=409)
    if not locked.statement_receipt_id:
        raise AssessmentError('Confirm the customer’s M-PESA statement first.', code='statement_required')
    # Signed-LAF evidence will become a governed file upload. Do not expose a
    # storage reference or SHA-256 implementation detail as staff data entry in
    # the interim. Retain compatibility with an older client only when it sends
    # a complete reference/hash pair.
    reference = str(signed_laf_reference or '').strip()
    laf_hash = re.sub(r'[^0-9a-f]', '', str(signed_laf_hash or '').casefold())
    if reference or laf_hash:
        if not reference or len(laf_hash) != 64:
            raise AssessmentError('The supplied signed LAF reference is incomplete.', code='signed_laf_invalid')
    if pre_appraisal_file:
        _store_document(locked, AssessmentDocument.TYPE_PRE_APPRAISAL, pre_appraisal_file, actor)
    if not current_document(locked, AssessmentDocument.TYPE_PRE_APPRAISAL):
        raise AssessmentError('Upload the completed pre-appraisal form.', code='pre_appraisal_document_required')
    set_statement_passcode(locked, passcode)
    if reference and laf_hash:
        locked.signed_laf_reference = reference[:255]
        locked.signed_laf_hash = laf_hash
        locked.save(update_fields=['signed_laf_reference', 'signed_laf_hash', 'updated_at'])
    _advance(locked, locked.STATE_PENDING_AUTHORIZATION)
    _event(locked, 'pre_appraisal.submitted', actor, request_id, {'statement_full_year': locked.statement_full_year, 'laf_hash': laf_hash})
    return locked


def _evidence_digest(assessment: CreditAssessment, package: AnalysisPackage | None = None) -> str:
    documents = list(assessment.documents.filter(is_current=True).order_by('document_type').values_list('document_type', 'content_hash', 'version'))
    return _digest({
        'assessment': str(assessment.pk),
        'revision': assessment.revision,
        'documents': documents,
        'laf_hash': assessment.signed_laf_hash,
        'package': package.content_digest if package else '',
    })


@transaction.atomic
def manager_authorize(*, assessment: CreditAssessment, user: dict, expected_revision: Any, request_id: str, action: str, comment: str = '') -> CreditAssessment:
    _require_role(user, 'BM')
    actor = _actor(user)
    locked = CreditAssessment.objects.select_for_update().get(pk=assessment.pk)
    prior = locked.decisions.filter(request_id=request_id).first()
    if prior:
        return locked
    _expect_revision(locked, expected_revision)
    if locked.state != locked.STATE_PENDING_AUTHORIZATION:
        raise AssessmentError('This case is not awaiting analysis authorization.', code='authorization_state_invalid', status=409)
    if locked.created_by_id and locked.created_by_id == actor.pk and 'IT' not in _roles(user):
        raise AssessmentError('The officer who prepared this case cannot authorize it.', code='maker_checker_conflict', status=403)
    action = str(action or '').strip().casefold()
    if action not in {AssessmentDecision.ACTION_APPROVED, AssessmentDecision.ACTION_RETURNED, AssessmentDecision.ACTION_DECLINED}:
        raise AssessmentError('Choose approve, return, or decline.', code='authorization_action_invalid')
    cleaned_comment = str(comment or '').strip()
    if action == AssessmentDecision.ACTION_RETURNED and locked.statement_full_year is not False:
        raise AssessmentError('Return is available only when the statement does not cover a full year.', code='authorization_return_not_available')
    if action == AssessmentDecision.ACTION_APPROVED and locked.statement_full_year is not True:
        raise AssessmentError('A full twelve-month statement is required before analysis can be authorized.', code='statement_full_year_required')
    if action != AssessmentDecision.ACTION_APPROVED and not cleaned_comment:
        raise AssessmentError('Enter a reason for this decision.', code='decision_comment_required')
    AssessmentDecision.objects.create(
        assessment=locked, gate=AssessmentDecision.GATE_AUTHORIZATION, action=action,
        assessment_revision=locked.revision, evidence_digest=_evidence_digest(locked),
        comment=cleaned_comment, actor=actor, request_id=request_id,
    )
    target = {
        AssessmentDecision.ACTION_APPROVED: locked.STATE_ANALYSIS,
        AssessmentDecision.ACTION_RETURNED: locked.STATE_RETURNED_PRE_ANALYSIS,
        AssessmentDecision.ACTION_DECLINED: locked.STATE_DECLINED,
    }[action]
    _advance(locked, target)
    _event(locked, f'authorization.{action}', actor, '', {'decision_request_id': request_id})
    if action == AssessmentDecision.ACTION_DECLINED:
        locked.tat_case.status = 'Declined'
        locked.tat_case.workflow_revision += 1
        locked.tat_case.save(update_fields=['status', 'workflow_revision', 'updated_at'])
    return locked


@transaction.atomic
def submit_analysis(
    *, assessment: CreditAssessment, user: dict, expected_revision: Any, request_id: str,
    analysis_file, questions: Iterable[str], spin_file=None, crb_file=None,
) -> CreditAssessment:
    _require_role(user, 'CA')
    actor = _actor(user)
    locked = CreditAssessment.objects.select_for_update().get(pk=assessment.pk)
    if _existing_event(locked, request_id):
        return locked
    _expect_revision(locked, expected_revision)
    if locked.state != locked.STATE_ANALYSIS:
        raise AssessmentError('This case is not ready for credit analysis.', code='analysis_state_invalid', status=409)
    if not analysis_file:
        raise AssessmentError('Upload the consolidated credit-analysis report.', code='analysis_report_required')
    analysis_document = _store_document(locked, AssessmentDocument.TYPE_ANALYSIS_REPORT, analysis_file, actor)
    if spin_file:
        _store_document(locked, AssessmentDocument.TYPE_SPIN_REPORT, spin_file, actor)
    if crb_file:
        _store_document(locked, AssessmentDocument.TYPE_CRB_REPORT, crb_file, actor)
    clean_questions = [str(value or '').strip() for value in questions if str(value or '').strip()]
    package_revision = (locked.analysis_packages.aggregate(value=Max('revision'))['value'] or 0) + 1
    digest = _digest({'analysis_hash': analysis_document.content_hash, 'questions': clean_questions, 'revision': package_revision})
    package = AnalysisPackage.objects.create(
        assessment=locked, revision=package_revision, analysis_document=analysis_document,
        submitted_by=actor, content_digest=digest,
    )
    AnalysisQuestion.objects.bulk_create([
        AnalysisQuestion(package=package, sequence=index, text=text, created_by=actor)
        for index, text in enumerate(clean_questions, start=1)
    ])
    # Once the analyst has produced the consolidated report, retaining the
    # source-PDF passcode has no operational purpose. Keep only destruction
    # metadata and the prior audited reveal count.
    secret = AssessmentSecret.objects.select_for_update().filter(assessment=locked, destroyed_at__isnull=True).first()
    if secret:
        secret.ciphertext = ''
        secret.destroyed_at = timezone.now()
        secret.save(update_fields=['ciphertext', 'destroyed_at', 'updated_at'])
    _advance(locked, locked.STATE_BRO_REVIEW)
    _event(locked, 'analysis.submitted', actor, request_id, {
        'package_revision': package_revision,
        'question_count': len(clean_questions),
        'statement_passcode_destroyed': bool(secret),
    })
    return locked


def _latest_package(assessment: CreditAssessment) -> AnalysisPackage:
    package = assessment.analysis_packages.order_by('-revision').first()
    if not package:
        raise AssessmentError('No submitted analysis package exists.', code='analysis_package_missing', status=409)
    return package


@transaction.atomic
def bro_review(*, assessment: CreditAssessment, user: dict, expected_revision: Any, request_id: str, responses: dict[str, str] | None = None) -> CreditAssessment:
    _require_role(user, 'BRO')
    actor = _actor(user)
    locked = CreditAssessment.objects.select_for_update().get(pk=assessment.pk)
    if _existing_event(locked, request_id):
        return locked
    _expect_revision(locked, expected_revision)
    if locked.state not in {locked.STATE_BRO_REVIEW, locked.STATE_RETURNED_TO_BRO}:
        raise AssessmentError('This case is not awaiting BRO review.', code='bro_review_state_invalid', status=409)
    package = _latest_package(locked)
    questions = list(package.questions.order_by('sequence'))
    supplied = responses or {}
    for question in questions:
        text = str(supplied.get(str(question.pk), '') or '').strip()
        if not text:
            raise AssessmentError('Answer every analyst question before submitting.', code='question_response_required')
        revision = (question.responses.aggregate(value=Max('revision'))['value'] or 0) + 1
        QuestionResponse.objects.create(question=question, revision=revision, text=text, responded_by=actor)
    _advance(locked, locked.STATE_ANALYST_VALIDATION if questions else locked.STATE_PENDING_DECISION)
    _event(locked, 'bro.reviewed_analysis', actor, request_id, {'package_revision': package.revision, 'question_count': len(questions)})
    return locked


def _latest_response(question: AnalysisQuestion) -> QuestionResponse | None:
    return question.responses.order_by('-revision').first()


@transaction.atomic
def validate_responses(*, assessment: CreditAssessment, user: dict, expected_revision: Any, request_id: str, outcomes: dict[str, dict]) -> CreditAssessment:
    _require_role(user, 'CA')
    actor = _actor(user)
    locked = CreditAssessment.objects.select_for_update().get(pk=assessment.pk)
    if _existing_event(locked, request_id):
        return locked
    _expect_revision(locked, expected_revision)
    if locked.state != locked.STATE_ANALYST_VALIDATION:
        raise AssessmentError('This case is not awaiting analyst validation.', code='validation_state_invalid', status=409)
    package = _latest_package(locked)
    returned = False
    for question in package.questions.order_by('sequence'):
        response = _latest_response(question)
        if not response:
            raise AssessmentError('Every question needs a BRO response.', code='question_response_required')
        item = outcomes.get(str(question.pk)) or {}
        outcome = str(item.get('outcome') or '').strip().casefold()
        comment = str(item.get('comment') or '').strip()
        if outcome not in {QuestionValidationEvent.OUTCOME_ACCEPTED, QuestionValidationEvent.OUTCOME_RETURNED}:
            raise AssessmentError('Validate every BRO response.', code='question_validation_required')
        if outcome == QuestionValidationEvent.OUTCOME_RETURNED and not comment:
            raise AssessmentError('Explain what the BRO must correct.', code='question_validation_comment_required')
        QuestionValidationEvent.objects.create(
            response=response, outcome=outcome, comment=comment,
            validated_by=actor, request_id=f'{request_id}:{question.pk}',
        )
        returned = returned or outcome == QuestionValidationEvent.OUTCOME_RETURNED
    _advance(locked, locked.STATE_BRO_REVIEW if returned else locked.STATE_PENDING_DECISION)
    _event(locked, 'responses.validated', actor, request_id, {'returned': returned, 'package_revision': package.revision})
    return locked


@transaction.atomic
def manager_decide(*, assessment: CreditAssessment, user: dict, expected_revision: Any, request_id: str, action: str, comment: str) -> CreditAssessment:
    _require_role(user, 'BM')
    actor = _actor(user)
    locked = CreditAssessment.objects.select_for_update().get(pk=assessment.pk)
    if locked.decisions.filter(request_id=request_id).exists():
        return locked
    _expect_revision(locked, expected_revision)
    if locked.state != locked.STATE_PENDING_DECISION:
        raise AssessmentError('This case is not awaiting the final decision.', code='final_decision_state_invalid', status=409)
    action = str(action or '').strip().casefold()
    if action not in {AssessmentDecision.ACTION_APPROVED, AssessmentDecision.ACTION_RETURNED, AssessmentDecision.ACTION_DECLINED}:
        raise AssessmentError('Choose approve, return to BRO, or decline.', code='final_decision_action_invalid')
    cleaned_comment = str(comment or '').strip()
    if not cleaned_comment:
        raise AssessmentError('Enter the Branch Manager comment.', code='decision_comment_required')
    package = _latest_package(locked)
    if package.submitted_by_id and package.submitted_by_id == actor.pk and 'IT' not in _roles(user):
        raise AssessmentError('The analyst who prepared this report cannot make the final decision.', code='maker_checker_conflict', status=403)
    AssessmentDecision.objects.create(
        assessment=locked, gate=AssessmentDecision.GATE_FINAL, action=action,
        assessment_revision=locked.revision, package=package,
        evidence_digest=_evidence_digest(locked, package), comment=cleaned_comment,
        actor=actor, request_id=request_id,
    )
    target = {
        AssessmentDecision.ACTION_APPROVED: locked.STATE_APPROVED,
        AssessmentDecision.ACTION_RETURNED: locked.STATE_RETURNED_TO_BRO,
        AssessmentDecision.ACTION_DECLINED: locked.STATE_DECLINED,
    }[action]
    _advance(locked, target)
    _event(locked, f'final_decision.{action}', actor, '', {'decision_request_id': request_id, 'package_revision': package.revision})
    if action == AssessmentDecision.ACTION_DECLINED:
        locked.tat_case.status = 'Declined'
        locked.tat_case.workflow_revision += 1
        locked.tat_case.save(update_fields=['status', 'workflow_revision', 'updated_at'])
    return locked


def serialize_assessment(assessment: CreditAssessment, user: dict) -> dict:
    package = assessment.analysis_packages.order_by('-revision').first()
    roles = _roles(user)
    documents = []
    may_view_evidence = bool(roles.intersection({'BRO', 'BM', 'CA', 'IT'}))
    for item in assessment.documents.filter(is_current=True).order_by('document_type') if may_view_evidence else []:
        documents.append({
            'id': str(item.pk), 'type': item.document_type,
            'label': item.get_document_type_display(), 'filename': item.original_filename,
            'version': item.version, 'size': item.size, 'source': 'document',
        })
    questions = []
    if package and may_view_evidence:
        for question in package.questions.order_by('sequence'):
            response = _latest_response(question)
            validation = response.validation_events.order_by('-created_at').first() if response else None
            questions.append({
                'id': str(question.pk), 'text': question.text,
                'response': response.text if response else '',
                'response_revision': response.revision if response else None,
                'validation': validation.outcome if validation else '',
                'validation_comment': validation.comment if validation else '',
            })
    receipt = assessment.statement_receipt
    if receipt and may_view_evidence:
        documents.insert(0, {
            'id': str(receipt.pk), 'type': AssessmentDocument.TYPE_MPESA_STATEMENT,
            'label': 'M-PESA statement', 'filename': receipt.attachment_name,
            'version': 1, 'size': receipt.attachment_size, 'source': 'statement',
        })
    original_to_inbox = None
    inbox_to_case = None
    total_to_case = None
    if receipt:
        linked_at = assessment.events.filter(action='statement.confirmed').order_by('-created_at').values_list('created_at', flat=True).first() or assessment.created_at
        inbox_to_case = max(0, int((linked_at - receipt.inbox_received_at).total_seconds()))
        if receipt.original_sent_at:
            original_to_inbox = max(0, int((receipt.inbox_received_at - receipt.original_sent_at).total_seconds()))
            total_to_case = max(0, int((linked_at - receipt.original_sent_at).total_seconds()))
    action_roles = {
        assessment.STATE_DRAFT: 'BRO', assessment.STATE_RETURNED_PRE_ANALYSIS: 'BRO',
        assessment.STATE_PENDING_AUTHORIZATION: 'BM', assessment.STATE_ANALYSIS: 'CA',
        assessment.STATE_BRO_REVIEW: 'BRO', assessment.STATE_RETURNED_TO_BRO: 'BRO',
        assessment.STATE_ANALYST_VALIDATION: 'CA', assessment.STATE_PENDING_DECISION: 'BM',
    }
    required_role = action_roles.get(assessment.state, '')
    can_act = 'IT' in roles or (required_role and required_role in roles)
    secret = AssessmentSecret.objects.filter(assessment=assessment).only('destroyed_at', 'ciphertext').first()
    return {
        'id': str(assessment.pk), 'state': assessment.state,
        'state_label': assessment.get_state_display(), 'revision': assessment.revision,
        'required_role': required_role, 'can_act': bool(can_act),
        'statement': None if not receipt else {
            'id': str(receipt.pk), 'filename': receipt.attachment_name,
            'customer_name': receipt.customer_name,
            'period_start': receipt.statement_period_start.isoformat() if receipt.statement_period_start else '',
            'period_end': receipt.statement_period_end.isoformat() if receipt.statement_period_end else '',
            'full_year': receipt.statement_full_year,
            'received_at': receipt.inbox_received_at.isoformat(),
            'original_sent_at': receipt.original_sent_at.isoformat() if receipt.original_sent_at else '',
            'time_source': receipt.original_time_source,
        },
        'timing': {
            'original_to_forwarding_seconds': original_to_inbox,
            'inbox_to_case_seconds': inbox_to_case,
            'original_to_case_seconds': total_to_case,
        },
        'signed_laf_reference': assessment.signed_laf_reference,
        'documents': documents,
        'package_revision': package.revision if package else None,
        'questions': questions,
        'has_passcode': bool(secret and not secret.destroyed_at and secret.ciphertext),
    }
