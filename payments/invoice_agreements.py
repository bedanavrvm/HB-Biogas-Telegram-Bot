"""Exact signed-letter identity exceptions. No financial facts are approved here."""
import hashlib
import io
from pathlib import Path

from django.db import transaction

from core.models import InvoiceNameChangeBatch, InvoiceNameChangeLetterArtifact
from core.services.invoice_identity import applicant_identity, invoice_identity, normalize_national_id
from core.services.invoice_name_change_letters import _canonical_rows
from payments.models import InvoiceNameAgreement


def agreement_facts(artifact):
    rows, blockers = _canonical_rows(artifact.batch)
    blockers = [message for message in blockers if 'no longer a draft' not in message]
    if blockers or rows != (artifact.payload_snapshot or {}).get('rows'):
        raise ValueError('The case or household details changed. Prepare a new correction letter.')
    items = list(artifact.batch.items.select_related('farmer', 'original_invoice', 'relationship__related_person'))
    if artifact.batch.sent_artifact_id != artifact.pk or not items or any(item.status != 'awaiting_replacement' for item in items):
        raise ValueError('Record the current letter as sent before accepting its signed copy.')
    for item in items:
        current = invoice_identity(item.original_invoice)
        if item.original_invoice.matched_farmer_id != item.farmer_id or item.original_invoice.status != 'matched':
            raise ValueError('The source invoice is no longer matched to this applicant.')
        if any(current[key] != (item.original_identity or {}).get(key) for key in ('normalized_name', 'normalized_national_id', 'normalized_phone')):
            raise ValueError('The invoice identity changed. Prepare a new correction letter.')
        if normalize_national_id(item.relationship.related_person.national_id) != current['normalized_national_id']:
            raise ValueError('The confirmed invoice holder identity changed. Prepare a new correction letter.')
    return {str(item.pk): {
        'invoice_id': str(item.original_invoice_id),
        'invoice': invoice_identity(item.original_invoice),
        'applicant': applicant_identity(item.farmer),
        'relationship_id': str(item.relationship_id),
        'relationship_type': item.relationship.relationship_type,
    } for item in items}


def agreement_clears_item(item):
    if not item.batch_id or not item.batch.sent_artifact_id or item.status != 'awaiting_replacement':
        return False
    agreement = InvoiceNameAgreement.objects.filter(artifact_id=item.batch.sent_artifact_id).select_related('artifact__batch').first()
    if not agreement:
        return False
    try:
        return agreement.identity_facts == agreement_facts(agreement.artifact)
    except ValueError:
        return False


def _validated_scan(upload):
    if not upload:
        raise ValueError('Choose the signed/agreed PDF, JPG or PNG letter.')
    if upload.size > 16 * 1024 * 1024:
        raise ValueError('The signed letter must be 16 MB or smaller.')
    filename = Path(str(upload.name).replace('\\', '/')).name[:255]
    content = upload.read(16 * 1024 * 1024 + 1)
    if not content or len(content) > 16 * 1024 * 1024:
        raise ValueError('The signed letter is empty or too large.')
    suffix = Path(filename).suffix.lower()
    try:
        if suffix == '.pdf' and content.startswith(b'%PDF'):
            from pypdf import PdfReader
            pdf = PdfReader(io.BytesIO(content))
            if pdf.is_encrypted or not len(pdf.pages) or len(pdf.pages) > 8:
                raise ValueError('Upload an unlocked signed letter with 1 to 8 pages.')
            mime = 'application/pdf'
        elif suffix in {'.png', '.jpg', '.jpeg'}:
            from PIL import Image
            with Image.open(io.BytesIO(content)) as image:
                if image.format not in {'PNG', 'JPEG'} or image.width * image.height > 12_000_000:
                    raise ValueError('Use a JPG or PNG letter image below 12 megapixels.')
                mime = 'image/png' if image.format == 'PNG' else 'image/jpeg'
                image.verify()
        else:
            raise ValueError('Upload a PDF, JPG or PNG signed letter.')
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('This signed letter file could not be read. Choose a valid PDF or image.') from exc
    return filename, mime, content


@transaction.atomic
def accept_agreement(batch_id, *, artifact_id, uploaded_file, actor, confirmed):
    if not confirmed:
        raise ValueError('Confirm this is the signed/agreed copy of the displayed letter.')
    filename, mime, content = _validated_scan(uploaded_file)
    # Serialize with sent-request correction/replacement; lock related rows
    # separately so PostgreSQL never locks the nullable side of an outer join.
    from core.models import InvoiceNameChangeItem, JawabuFarmerMaster, ParsedInvoice, JawabuHouseholdRelationship, JawabuRelatedPerson
    items = list(InvoiceNameChangeItem.objects.select_for_update().filter(batch_id=batch_id).order_by('pk'))
    batch = InvoiceNameChangeBatch.objects.select_for_update().get(pk=batch_id)
    artifact = InvoiceNameChangeLetterArtifact.objects.select_for_update().get(pk=artifact_id, batch=batch)
    list(JawabuFarmerMaster.objects.select_for_update().filter(pk__in=[i.farmer_id for i in items]).order_by('pk'))
    list(ParsedInvoice.objects.select_for_update().filter(pk__in=[i.original_invoice_id for i in items]).order_by('pk'))
    relationships = list(JawabuHouseholdRelationship.objects.select_for_update().filter(pk__in=[i.relationship_id for i in items]).order_by('pk'))
    list(JawabuRelatedPerson.objects.select_for_update().filter(pk__in=[r.related_person_id for r in relationships]).order_by('pk'))
    facts = agreement_facts(artifact)
    checksum = hashlib.sha256(content).hexdigest()
    existing = InvoiceNameAgreement.objects.filter(artifact=artifact).first()
    if existing:
        if existing.checksum != checksum or existing.identity_facts != facts:
            raise ValueError('A signed agreement is already retained for this letter. Start a new correction to replace it.')
        return existing
    agreement = InvoiceNameAgreement.objects.create(artifact=artifact, filename=filename,
        content_type=mime, file_content=content, checksum=checksum, identity_facts=facts, accepted_by=actor)
    from core.services.invoice_identity import _record_case_event
    for item in batch.items.select_related('farmer'):
        _record_case_event(item.farmer, action='invoice_name_agreement_accepted', actor=actor,
            request_id=f'invoice-agreement:{agreement.pk}:{item.pk}',
            metadata={'agreement_id': str(agreement.pk), 'artifact_id': str(artifact.pk), 'checksum': checksum})
    return agreement
