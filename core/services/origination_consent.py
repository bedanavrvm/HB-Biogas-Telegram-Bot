"""Governed conditional-approval wording and deterministic packet notice pages."""

from __future__ import annotations

from io import BytesIO
from typing import Any

from django.conf import settings
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from core.models import (
    LoanOriginationApplication,
    OriginationConsentPolicyVersion,
    OriginationDocumentTemplate,
)


class OriginationConsentError(ValueError):
    pass


def conditional_approval_enabled() -> bool:
    return bool(getattr(settings, 'ORIGINATION_CONDITIONAL_APPROVAL_ENABLED', False))


def active_consent_policy() -> OriginationConsentPolicyVersion:
    if not conditional_approval_enabled():
        raise OriginationConsentError('Conditional approval is not enabled for this environment.')
    policy = OriginationConsentPolicyVersion.objects.filter(
        status=OriginationConsentPolicyVersion.STATUS_ACTIVE,
    ).first()
    if not policy:
        raise OriginationConsentError(
            'Publish the compliance-approved Origination consent policy before enabling this flow.'
        )
    if policy.content_sha256 != policy._content_hash():
        raise OriginationConsentError('The active Origination consent policy failed its integrity check.')
    return policy


def policy_snapshot(policy: OriginationConsentPolicyVersion) -> dict[str, Any]:
    return {
        'id': str(policy.pk),
        'version': policy.version,
        'content_sha256': policy.content_sha256,
        'packet_clause': policy.packet_clause,
        'signer_consent_text': policy.signer_consent_text,
        'signer_completion_text': policy.signer_completion_text,
        'resigning_text': policy.resigning_text,
        'approval_reference': policy.approval_reference,
        'approved_at': policy.approved_at.isoformat() if policy.approved_at else '',
    }


def _wrapped_lines(text: str, *, font: str, size: float, width: float) -> list[str]:
    lines: list[str] = []
    for paragraph in str(text or '').replace('\r', '').split('\n'):
        words = paragraph.split()
        if not words:
            lines.append('')
            continue
        line = words.pop(0)
        for word in words:
            candidate = f'{line} {word}'
            if stringWidth(candidate, font, size) <= width:
                line = candidate
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def render_notice_page(
    *, policy: OriginationConsentPolicyVersion, reference_number: str,
) -> bytes:
    """Return one deterministic, self-explanatory A4 notice page."""
    output = BytesIO()
    width, height = A4
    pdf = canvas.Canvas(output, pagesize=A4, pageCompression=1, invariant=1)
    margin = 54
    pdf.setFont('Helvetica-Bold', 14)
    pdf.drawString(margin, height - margin, 'JBL CONDITIONAL APPROVAL AND SIGNING NOTICE')
    pdf.setFont('Helvetica', 8)
    pdf.drawString(margin, height - margin - 20, f'Application: {reference_number}')
    pdf.drawRightString(width - margin, height - margin - 20, f'Consent version: {policy.version}')
    pdf.setLineWidth(.6)
    pdf.line(margin, height - margin - 30, width - margin, height - margin - 30)
    y = height - margin - 54
    pdf.setFont('Helvetica', 10)
    for line in _wrapped_lines(
        policy.packet_clause, font='Helvetica', size=10, width=width - margin * 2,
    ):
        if y < margin + 45:
            raise OriginationConsentError('The approved packet clause does not fit on one notice page.')
        pdf.drawString(margin, y, line)
        y -= 14
    pdf.setFont('Helvetica', 7)
    pdf.drawString(margin, margin, f'Policy SHA-256: {policy.content_sha256}')
    pdf.save()
    return output.getvalue()


def _primary_has_native_clause(
    application: LoanOriginationApplication, policy: OriginationConsentPolicyVersion,
) -> bool:
    primary = application.packet_documents.filter(document_role='primary', selected=True).first()
    snapshot = primary.template_snapshot if primary else {}
    source_hash = str(snapshot.get('sha256') or application.product_definition.document_template_sha256 or '')
    if not source_hash:
        return False
    return OriginationDocumentTemplate.objects.filter(
        source_sha256=source_hash,
        native_consent_policy=policy,
        native_consent_attested_by__isnull=False,
        native_consent_attested_at__isnull=False,
    ).exclude(native_consent_attestation_reference='').exists()


def apply_consent_notice(
    *, application: LoanOriginationApplication, packet_pdf: bytes,
    document_manifest: list[dict[str, Any]], policy: OriginationConsentPolicyVersion,
) -> tuple[bytes, list[dict[str, Any]], str]:
    """Put approved wording inside the exact bytes before they are hashed."""
    if _primary_has_native_clause(application, policy):
        return packet_pdf, document_manifest, 'native_template'
    notice = render_notice_page(policy=policy, reference_number=application.reference_number)
    writer = PdfWriter()
    for page in PdfReader(BytesIO(notice)).pages:
        writer.add_page(page)
    for page in PdfReader(BytesIO(packet_pdf)).pages:
        writer.add_page(page)
    output = BytesIO()
    writer.write(output)
    notice_manifest = {
        'key': 'conditional_approval_notice',
        'name': 'Conditional approval and signing notice',
        'template': {'configuration': {}},
        'rendered_sha256': __import__('hashlib').sha256(notice).hexdigest(),
        'signer_rules': [],
        'page_count': 1,
        'consent_policy_version': policy.version,
        'consent_policy_sha256': policy.content_sha256,
    }
    return output.getvalue(), [notice_manifest, *document_manifest], 'notice_page'
