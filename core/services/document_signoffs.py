"""Physical signature/stamp retention for generated finance workbooks.

The Mini App never creates a signature image or claims cryptographic
verification.  An authorised workflow role attests that a paper copy of the
exact retained workbook was signed, stamped, and scanned.  The source workbook
and the scan are both copied into an append-only sign-off record before Drive
upload is attempted, so a Drive outage cannot erase the evidence.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.models import (
    DocumentPhysicalSignoff,
    DocumentPhysicalSignoffEvent,
    DocumentSignoffPolicy,
    PaymentDocument,
    RequisitionBatch,
)
from core.services.document_sync import mark_drive_attempt, mark_drive_failure, mark_drive_success
from core.services.workflow_capabilities import has_capability


logger = logging.getLogger(__name__)

ALLOWED_SCAN_CONTENT_TYPES = {
    'application/pdf',
    'image/jpeg',
    'image/png',
}
ALLOWED_SCAN_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png'}


class PhysicalSignoffError(ValidationError):
    """A safe validation error suitable for the Portal upload response."""


@dataclass(frozen=True)
class SourceArtifact:
    document_type: str
    document: RequisitionBatch | PaymentDocument
    version: int
    filename: str
    content_type: str
    data: bytes

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


def signoff_policy(document_type: str) -> DocumentSignoffPolicy | None:
    return DocumentSignoffPolicy.objects.filter(document_type=document_type, is_active=True).first()


def can_approve_physical_signoff(user, access: dict | None, document_type: str) -> bool:
    """Return whether the resolved Portal identity may attest this scan."""
    if not user or not getattr(user, 'is_active', False):
        return False
    policy = signoff_policy(document_type)
    if not policy:
        return False
    if not has_capability(user, 'jawabu_portal', 'portal.documents.sign', access=access):
        return False
    roles = set((access or {}).get('roles') or [])
    return policy.approval_role in roles


def policy_payload(document_type: str) -> dict:
    policy = signoff_policy(document_type)
    return {
        'configured': bool(policy),
        'approval_role': policy.approval_role if policy else '',
    }


def source_artifact(document_type: str, document_id: str, *, lock: bool = False) -> SourceArtifact:
    """Resolve the exact locally retained workbook eligible for sign-off.

    Existing documents made before local source retention are intentionally
    left as legacy records.  They can be regenerated to create a traceable
    source, but the system never guesses bytes from a Drive link.
    """
    queryset = RequisitionBatch.objects if document_type == DocumentSignoffPolicy.DOCUMENT_REQUISITION else PaymentDocument.objects
    if lock:
        queryset = queryset.select_for_update()
    try:
        document = queryset.get(pk=document_id)
    except (RequisitionBatch.DoesNotExist, PaymentDocument.DoesNotExist) as exc:
        raise PhysicalSignoffError('The generated document was not found.') from exc

    if document_type == DocumentSignoffPolicy.DOCUMENT_REQUISITION:
        if document.status == 'preview':
            raise PhysicalSignoffError('A preview cannot be physically signed. Generate the requisition first.')
        data = bytes(document.file_content or b'')
    elif document_type == DocumentSignoffPolicy.DOCUMENT_PAYMENT:
        if document.status != 'final':
            raise PhysicalSignoffError('Only a final payment schedule can be physically signed.')
        data = bytes(document.file_content or b'')
    else:
        raise PhysicalSignoffError('Select a supported generated document type.')

    if not data:
        raise PhysicalSignoffError(
            'This is a legacy document without its retained source workbook. Regenerate it before attaching a signed scan.'
        )
    return SourceArtifact(
        document_type=document_type,
        document=document,
        version=int(getattr(document, 'version', 0) or 1),
        filename=str(getattr(document, 'filename', '') or 'generated-document.xlsx'),
        content_type=str(getattr(document, 'content_type', '') or 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
        data=data,
    )


def _read_scan(uploaded_file) -> tuple[bytes, str, str]:
    if uploaded_file is None:
        raise PhysicalSignoffError('Choose the signed and stamped PDF, JPG, or PNG scan to upload.')
    filename = str(getattr(uploaded_file, 'name', '') or '').strip()
    suffix = '.' + filename.rsplit('.', 1)[-1].casefold() if '.' in filename else ''
    content_type = str(getattr(uploaded_file, 'content_type', '') or '').casefold()
    if suffix not in ALLOWED_SCAN_EXTENSIONS or content_type not in ALLOWED_SCAN_CONTENT_TYPES:
        raise PhysicalSignoffError('Upload one signed scan as a PDF, JPG, or PNG file.')
    data = uploaded_file.read()
    max_size = int(getattr(settings, 'DOCUMENT_SIGNOFF_MAX_FILE_SIZE_MB', 12) or 12) * 1024 * 1024
    if not data:
        raise PhysicalSignoffError('The signed scan is empty.')
    if len(data) > max_size:
        raise PhysicalSignoffError(f'The signed scan must be {max_size // (1024 * 1024)} MB or smaller.')
    return data, filename, content_type


def _existing_equivalent_signoff(source: SourceArtifact, scan_checksum: str, user) -> DocumentPhysicalSignoff | None:
    filters = {
        'document_type': source.document_type,
        'source_version': source.version,
        'source_checksum': source.checksum,
        'scan_checksum': scan_checksum,
        'uploaded_by': user,
    }
    if source.document_type == DocumentSignoffPolicy.DOCUMENT_REQUISITION:
        filters['requisition_batch'] = source.document
    else:
        filters['payment_document'] = source.document
    return DocumentPhysicalSignoff.objects.filter(
        **filters,
        status__in=[
            DocumentPhysicalSignoff.STATUS_UPLOAD_PENDING,
            DocumentPhysicalSignoff.STATUS_UPLOAD_FAILED,
            DocumentPhysicalSignoff.STATUS_SIGNED_APPROVED,
        ],
    ).order_by('-created_at').first()


def _record_event(signoff, action: str, *, actor=None, note: str = '', metadata: dict | None = None) -> None:
    DocumentPhysicalSignoffEvent.objects.create(
        signoff=signoff,
        action=action,
        actor=actor,
        note=str(note or ''),
        metadata=metadata or {},
    )


def _artifact_filters(source: SourceArtifact) -> dict:
    values = {
        'document_type': source.document_type,
        'source_version': source.version,
    }
    if source.document_type == DocumentSignoffPolicy.DOCUMENT_REQUISITION:
        values['requisition_batch'] = source.document
    else:
        values['payment_document'] = source.document
    return values


def _upload_to_drive(signoff: DocumentPhysicalSignoff, *, actor) -> DocumentPhysicalSignoff:
    """Persist Drive outcome without losing the retained scan after a failure."""
    from core.services.order_approval import GoogleDriveMediaStorage

    mark_drive_attempt(signoff)
    _record_event(signoff, DocumentPhysicalSignoffEvent.ACTION_RETRY_STARTED, actor=actor)
    artifact_key = str(signoff.requisition_batch_id or signoff.payment_document_id)
    extension = signoff.scan_filename.rsplit('.', 1)[-1].casefold() if '.' in signoff.scan_filename else 'pdf'
    safe_name = f'JBL_{signoff.document_type}_signed_v{signoff.source_version}_{signoff.id}.{extension}'
    try:
        file_id, url = GoogleDriveMediaStorage().upload(
            signoff.scan_file_content,
            filename=safe_name,
            mime_type=signoff.scan_content_type,
            id_number='physical_document_signoffs',
            received_at=timezone.now(),
            group_config=None,
            workflow_key='Jawabu/Document Signoffs',
            record_type=signoff.document_type.title(),
            record_key=artifact_key,
        )
    except Exception:
        logger.exception('Physical document sign-off upload failed: signoff=%s', signoff.id)
        signoff.status = DocumentPhysicalSignoff.STATUS_UPLOAD_FAILED
        mark_drive_failure(signoff, 'Drive upload failed; retry required.', error_field='drive_upload_error', update_fields=['status'])
        _record_event(signoff, DocumentPhysicalSignoffEvent.ACTION_UPLOAD_FAILED, actor=actor, note='Drive upload failed; retry required.')
        return signoff

    try:
        with transaction.atomic():
            signoff = DocumentPhysicalSignoff.objects.select_for_update().get(pk=signoff.pk)
            if signoff.status == DocumentPhysicalSignoff.STATUS_SIGNED_APPROVED:
                return signoff
            duplicate = DocumentPhysicalSignoff.objects.select_for_update().filter(
                **_artifact_filters_for_signoff(signoff),
                status=DocumentPhysicalSignoff.STATUS_SIGNED_APPROVED,
            ).exclude(pk=signoff.pk).first()
            if duplicate:
                signoff.status = DocumentPhysicalSignoff.STATUS_REJECTED
                signoff.rejection_reason = 'Another signed scan is already the approved record for this exact document version.'
                signoff.save(update_fields=['status', 'rejection_reason', 'updated_at'])
                _record_event(signoff, DocumentPhysicalSignoffEvent.ACTION_REJECTED, actor=actor, note=signoff.rejection_reason)
                return signoff
            mark_drive_success(signoff, file_id=file_id, url=url, error_field='drive_upload_error')
            signoff.status = DocumentPhysicalSignoff.STATUS_SIGNED_APPROVED
            signoff.approved_by = actor
            signoff.approved_at = timezone.now()
            signoff.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
            _record_event(signoff, DocumentPhysicalSignoffEvent.ACTION_APPROVED, actor=actor, metadata={
                'source_checksum': signoff.source_checksum,
                'scan_checksum': signoff.scan_checksum,
            })
    except IntegrityError:
        # The conditional unique constraint is the final concurrency guard.
        signoff.refresh_from_db()
        if signoff.status != DocumentPhysicalSignoff.STATUS_SIGNED_APPROVED:
            signoff.status = DocumentPhysicalSignoff.STATUS_REJECTED
            signoff.rejection_reason = 'Another signed scan was approved concurrently for this document version.'
            signoff.save(update_fields=['status', 'rejection_reason', 'updated_at'])
            _record_event(signoff, DocumentPhysicalSignoffEvent.ACTION_REJECTED, actor=actor, note=signoff.rejection_reason)
    return signoff


def _artifact_filters_for_signoff(signoff: DocumentPhysicalSignoff) -> dict:
    values = {
        'document_type': signoff.document_type,
        'source_version': signoff.source_version,
    }
    if signoff.document_type == DocumentSignoffPolicy.DOCUMENT_REQUISITION:
        values['requisition_batch_id'] = signoff.requisition_batch_id
    else:
        values['payment_document_id'] = signoff.payment_document_id
    return values


def submit_physical_signoff(*, document_type: str, document_id: str, uploaded_file, actor, access: dict | None, request_id: str = '') -> tuple[DocumentPhysicalSignoff, bool]:
    """Create one attested sign-off attempt, then attempt its Drive upload.

    The boolean is true when a retry/double submit resolves to the same stored
    sign-off.  Database locks plus the scan checksum protect against a mobile
    double tap even when the client did not retain a request identifier.
    """
    if not can_approve_physical_signoff(actor, access, document_type):
        raise PhysicalSignoffError('Your Portal role is not configured to attest this document type.')
    scan_data, scan_filename, scan_content_type = _read_scan(uploaded_file)
    scan_checksum = hashlib.sha256(scan_data).hexdigest()
    request_id = str(request_id or '').strip()

    with transaction.atomic():
        source = source_artifact(document_type, document_id, lock=True)
        if request_id:
            existing_request = DocumentPhysicalSignoff.objects.filter(request_id=request_id).first()
            if existing_request:
                return existing_request, True
        approved = signoff_for_source(source)
        if approved and approved.status == DocumentPhysicalSignoff.STATUS_SIGNED_APPROVED:
            # A physically approved record is immutable.  Do not send a
            # second scan to Drive or let a retry create competing evidence.
            return approved, True
        existing = _existing_equivalent_signoff(source, scan_checksum, actor)
        if existing:
            return existing, True
        values = {
            'document_type': document_type,
            'source_version': source.version,
            'source_filename': source.filename,
            'source_content_type': source.content_type,
            'source_checksum': source.checksum,
            'source_file_content': source.data,
            'scan_filename': scan_filename,
            'scan_content_type': scan_content_type,
            'scan_size': len(scan_data),
            'scan_checksum': scan_checksum,
            'scan_file_content': scan_data,
            'attested_complete': True,
            'uploaded_by': actor,
            'request_id': request_id,
        }
        if document_type == DocumentSignoffPolicy.DOCUMENT_REQUISITION:
            values['requisition_batch'] = source.document
        else:
            values['payment_document'] = source.document
        signoff = DocumentPhysicalSignoff(**values)
        signoff.full_clean()
        signoff.save()
        _record_event(signoff, DocumentPhysicalSignoffEvent.ACTION_SUBMITTED, actor=actor, metadata={
            'source_checksum': source.checksum,
            'scan_checksum': scan_checksum,
        })
    return _upload_to_drive(signoff, actor=actor), False


def retry_physical_signoff(*, signoff_id: str, actor, access: dict | None) -> DocumentPhysicalSignoff:
    signoff = DocumentPhysicalSignoff.objects.select_related('requisition_batch', 'payment_document').get(pk=signoff_id)
    if not can_approve_physical_signoff(actor, access, signoff.document_type):
        raise PhysicalSignoffError('Your Portal role is not configured to retry this signed-scan upload.')
    if signoff.status == DocumentPhysicalSignoff.STATUS_SIGNED_APPROVED:
        return signoff
    if signoff.status != DocumentPhysicalSignoff.STATUS_UPLOAD_FAILED:
        raise PhysicalSignoffError('Only a failed signed-scan upload can be retried.')
    return _upload_to_drive(signoff, actor=actor)


def reject_physical_signoff(*, signoff_id: str, actor, access: dict | None, reason: str) -> DocumentPhysicalSignoff:
    if not str(reason or '').strip():
        raise PhysicalSignoffError('Give a reason before rejecting a signed-scan attempt.')
    with transaction.atomic():
        signoff = DocumentPhysicalSignoff.objects.select_for_update().get(pk=signoff_id)
        if not can_approve_physical_signoff(actor, access, signoff.document_type):
            raise PhysicalSignoffError('Your Portal role is not configured to reject this signed scan.')
        if signoff.status == DocumentPhysicalSignoff.STATUS_SIGNED_APPROVED:
            raise PhysicalSignoffError('An approved signed scan is immutable. Attach a new document version instead.')
        signoff.status = DocumentPhysicalSignoff.STATUS_REJECTED
        signoff.rejection_reason = str(reason).strip()
        signoff.save(update_fields=['status', 'rejection_reason', 'updated_at'])
        _record_event(signoff, DocumentPhysicalSignoffEvent.ACTION_REJECTED, actor=actor, note=signoff.rejection_reason)
    return signoff


def signoff_for_source(source: SourceArtifact) -> DocumentPhysicalSignoff | None:
    matches = DocumentPhysicalSignoff.objects.filter(**_artifact_filters(source))
    return matches.filter(status=DocumentPhysicalSignoff.STATUS_SIGNED_APPROVED).first() or matches.first()


def _artifact_filters(source: SourceArtifact) -> dict:
    values = {'document_type': source.document_type, 'source_version': source.version}
    if source.document_type == DocumentSignoffPolicy.DOCUMENT_REQUISITION:
        values['requisition_batch'] = source.document
    else:
        values['payment_document'] = source.document
    return values


def serialize_physical_signoff(signoff: DocumentPhysicalSignoff | None, *, document_type: str, source_available: bool, can_upload: bool = False) -> dict:
    policy = policy_payload(document_type)
    if signoff is None:
        return {
            'status': 'awaiting_signed_scan' if source_available else 'legacy_not_signable',
            'source_available': source_available,
            'can_upload': can_upload and source_available,
            **policy,
        }
    return {
        'id': str(signoff.id),
        'status': signoff.status,
        'source_available': source_available,
        'can_upload': can_upload and source_available and signoff.status != DocumentPhysicalSignoff.STATUS_SIGNED_APPROVED,
        'approval_role': policy['approval_role'],
        'scan_filename': signoff.scan_filename,
        'scan_checksum': signoff.scan_checksum,
        'source_checksum': signoff.source_checksum,
        'drive_url': signoff.drive_url,
        'drive_error': signoff.drive_upload_error,
        'retry_at': signoff.drive_next_retry_at.isoformat() if signoff.drive_next_retry_at else None,
        'uploaded_at': signoff.created_at.isoformat() if signoff.created_at else None,
        'approved_at': signoff.approved_at.isoformat() if signoff.approved_at else None,
        'rejection_reason': signoff.rejection_reason,
    }


def document_signoff_summary(document_type: str, document, *, can_upload: bool = False) -> dict:
    data = bytes(getattr(document, 'file_content', b'') or b'')
    source_available = bool(data) and (
        document_type == DocumentSignoffPolicy.DOCUMENT_REQUISITION or getattr(document, 'status', '') == 'final'
    )
    if not source_available:
        return serialize_physical_signoff(None, document_type=document_type, source_available=False, can_upload=False)
    source = SourceArtifact(
        document_type=document_type,
        document=document,
        version=int(getattr(document, 'version', 0) or 1),
        filename=str(getattr(document, 'filename', '') or 'generated-document.xlsx'),
        content_type=str(getattr(document, 'content_type', '') or 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
        data=data,
    )
    summary = serialize_physical_signoff(
        signoff_for_source(source),
        document_type=document_type,
        source_available=True,
        can_upload=can_upload,
    )
    previous_filters = {
        'document_type': document_type,
        'status': DocumentPhysicalSignoff.STATUS_SIGNED_APPROVED,
        'source_version__lt': source.version,
    }
    if document_type == DocumentSignoffPolicy.DOCUMENT_REQUISITION:
        previous_filters['requisition_batch'] = document
    else:
        previous_filters['payment_document'] = document
    summary['previous_approved'] = [
        {
            'id': str(item.id),
            'source_version': item.source_version,
            'drive_url': item.drive_url,
            'scan_filename': item.scan_filename,
            'approved_at': item.approved_at.isoformat() if item.approved_at else None,
        }
        for item in DocumentPhysicalSignoff.objects.filter(**previous_filters).order_by('-source_version', '-approved_at')[:5]
    ]
    return summary
