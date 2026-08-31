"""Fail-closed audit boundary for Portal access to sensitive JBL evidence."""
from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from core.models import JawabuFarmerMaster, JawabuMediaAccessEvent, MediaAttachment
from core.services.compliance_audit import record_sensitive_access


class JawabuMediaAccessError(ValueError):
    """Raised when an attachment is not valid evidence for the supplied case."""


class JawabuMediaAuditUnavailable(RuntimeError):
    """Raised when access cannot be delivered with a complete audit trail."""


@dataclass(frozen=True)
class JawabuMediaAuditResult:
    access_event: JawabuMediaAccessEvent
    compliance_event_id: str


def _attachment_belongs_to_farmer(
    farmer: JawabuFarmerMaster,
    attachment: MediaAttachment,
) -> bool:
    if attachment.jawabu_farmer_id:
        return attachment.jawabu_farmer_id == farmer.pk
    return (
        attachment.business_key_type == 'id_number'
        and str(attachment.business_key_value or '').strip()
        == str(farmer.national_id or '').strip()
    )


def record_jawabu_media_access(
    *,
    farmer: JawabuFarmerMaster,
    attachment: MediaAttachment,
    actor,
    request_id: str,
    access_route: str,
) -> JawabuMediaAuditResult:
    """Record native and compliance evidence atomically before content leaves Django."""
    if farmer is None or farmer.pk is None or attachment is None or attachment.pk is None:
        raise JawabuMediaAccessError('A saved case and attachment are required.')
    if attachment.upload_status != 'success' or not _attachment_belongs_to_farmer(farmer, attachment):
        raise JawabuMediaAccessError('The evidence does not belong to this case.')
    if actor is not None and not actor.is_active:
        raise JawabuMediaAccessError('The evidence actor is no longer active.')
    normalized_route = str(access_route or '').strip()
    if normalized_route not in {'in_app_preview', 'drive_redirect', 'short_lived_link'}:
        raise JawabuMediaAccessError('The evidence access route is invalid.')
    normalized_request_id = str(request_id or '').strip()
    if not normalized_request_id:
        raise JawabuMediaAccessError('An evidence access correlation identifier is required.')

    try:
        with transaction.atomic():
            access_event = JawabuMediaAccessEvent.objects.create(
                farmer=farmer,
                attachment=attachment,
                actor=actor,
                request_id=normalized_request_id[:128],
            )
            compliance_event = record_sensitive_access(
                workflow='portal',
                action='portal.jbl_media.view',
                subject_type='media_attachment',
                subject_id=str(attachment.pk),
                actor=actor,
                request_id=normalized_request_id,
                metadata={
                    'access_route': normalized_route,
                    'farmer_id': str(farmer.pk),
                    'media_category': attachment.file_type,
                },
            )
    except JawabuMediaAccessError:
        raise
    except Exception as exc:
        raise JawabuMediaAuditUnavailable(
            'Sensitive evidence access could not be audited.'
        ) from exc
    return JawabuMediaAuditResult(
        access_event=access_event,
        compliance_event_id=str(compliance_event.pk),
    )
