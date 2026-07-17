"""Boundary client for TAT approval certificates in the e-signature service."""
from __future__ import annotations

from typing import Any

import requests
from django.conf import settings

from core.models import TatTrackerApprovalCertificate


def dispatch_certificate(certificate: TatTrackerApprovalCertificate) -> dict[str, Any]:
    """Create and Telegram-authorize a remote BM approval certificate."""
    base_url = str(getattr(settings, 'ESIGNATURES_BASE_URL', '')).rstrip('/')
    api_key = str(getattr(settings, 'ESIGNATURES_API_KEY', ''))
    if not base_url or not api_key:
        raise ValueError('E-signature integration is not configured.')
    response = requests.post(
        f'{base_url}/api/v1/integrations/signing-sessions/',
        headers={'Authorization': f'Bearer {api_key}', 'Idempotency-Key': f'tat-{certificate.id}-create'},
        json=certificate_payload(certificate),
        timeout=15,
    )
    response.raise_for_status()
    approval = requests.post(
        f'{base_url}/api/v1/integrations/signing-sessions/{certificate.external_reference}/telegram-approve/',
        headers={'Authorization': f'Bearer {api_key}', 'Idempotency-Key': f'tat-{certificate.id}-telegram-approve'},
        json={'telegram_user_id': certificate.staff_member.telegram_user_id},
        timeout=15,
    )
    approval.raise_for_status()
    return approval.json()


def certificate_payload(certificate: TatTrackerApprovalCertificate) -> dict[str, Any]:
    case = certificate.case
    signer = certificate.staff_member
    return {
        'reference_number': certificate.external_reference,
        'document_type': 'tat_bm_approval_certificate',
        'expiry_days': 2,
        'generate_unsigned': True,
        'renderer_name': 'reportlab',
        'context': {
            'reference_number': certificate.external_reference,
            'case_id': case.case_id,
            'client_name': case.client_name,
            'branch': case.branch,
            'amount': str(case.amount or ''),
            'product_label': case.product_label,
            'stage_label': 'BM response to CA',
            'stamped_at': certificate.created_at.isoformat(),
            'branch_manager_name': signer.name,
        },
        'parties': [{
            'role': 'branch_manager',
            'full_name': signer.name,
            'id_number': signer.signing_national_id,
            'phone_number': signer.signing_phone_number,
            'email': signer.signing_email,
            'signing_order': 1,
        }],
    }

