"""Versioned, allowlisted references for future explicit Mini App relationships.

References carry no identity data and confer no access. Resolution always
re-evaluates current canonical grants and the owning workflow's visibility.
No identity matching, persistence, external calls or workflow transitions occur.
"""
from dataclasses import dataclass
from types import MappingProxyType
from urllib.parse import urlencode
from uuid import UUID
from functools import wraps

from django.apps import apps
from django.core.exceptions import ValidationError
from django.urls import reverse


class RecordUnavailable(ValueError):
    """Unknown, removed and unauthorized records share one safe failure."""


@dataclass(frozen=True)
class RecordAdapter:
    app: str
    entity: str
    model_label: str
    workflow: str
    view_capability: str
    edit_capabilities: tuple[str, ...]
    route_name: str
    requires_review_session: bool = False

    def generate(self, record):
        if record._meta.label != self.model_label or record.pk is None:
            raise RecordUnavailable('Record unavailable.')
        return {'version': 1, 'app': self.app, 'entity': self.entity, 'id': str(record.pk)}

    def authorize(self, record, user, *, edit=False):
        from core.services.telegram_identity import user_access
        from core.services.workflow_access import workflow_access_decision
        if not user or not user.is_active or not user.is_authenticated:
            return False
        access = user_access(user, self.workflow)
        if not access.get('authorized'):
            return False
        capabilities = self.edit_capabilities if edit else (self.view_capability,)
        if not any(workflow_access_decision(
            user, self.workflow, key, access=access, resource=record,
        ).allowed for key in capabilities):
            return False
        if self.app == 'loan_origination':
            from origination.services.origination_access import DENIED, FULL, application_presentation_mode
            mode = application_presentation_mode(record, user=user, access=access)
            return mode == FULL if edit else mode != DENIED
        return True

    def resolve(self, identifier, user, *, edit=False):
        model = apps.get_model(self.model_label)
        query = model.objects.all()
        if self.app == 'complaint_cases':
            query = query.exclude(complaint_status='')
        elif self.app == 'tat_tracker':
            from core.services.workflow_data_mode import operational_tat_cases
            query = operational_tat_cases(query).filter(is_deleted=False)
        elif self.app == 'spin_credit_analysis':
            from core.services.workflow_data_mode import operational_spin_requests
            query = operational_spin_requests(query)
        try:
            record = query.filter(pk=identifier).first()
        except (ValidationError, ValueError, TypeError):
            record = None
        if record is None or not self.authorize(record, user, edit=edit):
            raise RecordUnavailable('Record unavailable.')
        return record

    def describe(self, reference, user):
        record = resolve_record(reference, user)
        return {'record_ref': self.generate(record), 'label': self.entity.replace('_', ' ').title()}

    def launch(self, reference, user):
        record = resolve_record(reference, user)
        if self.app == 'jawabu_portal':
            url = reverse(self.route_name, kwargs={'farmer_id': str(record.pk)})
        else:
            query = {'record_id': str(record.pk)}
            group = getattr(record, 'group_configuration', None)
            group_id = getattr(group, 'group_id', '') or getattr(record, 'group_id', '')
            if group_id:
                query['group_id'] = str(group_id)
            url = reverse(self.route_name) + '?' + urlencode(query)
        return {'url': url, 'record_ref': self.generate(record),
                'requires_review_session': self.requires_review_session}


_ADAPTERS = (
    RecordAdapter('loan_origination', 'application', 'origination.LoanOriginationApplication',
                  'loan_origination', 'origination.view', ('origination.create', 'origination.review'), 'loan_origination_app'),
    RecordAdapter('complaint_cases', 'case', 'core.ParsedMessage', 'complaint_cases',
                  'complaint.queue.view', ('complaint.case.update',), 'complaint_cases_app'),
    RecordAdapter('tat_tracker', 'case', 'core.TatTrackerCase', 'tat_tracker',
                  'tat.home.view', ('tat.case.create',), 'tat_tracker_app'),
    RecordAdapter('jawabu_portal', 'case', 'core.JawabuFarmerMaster', 'jawabu_portal',
                  'portal.case.read', ('portal.jbl_visit.write',), 'portal_case_history_detail'),
    RecordAdapter('spin_credit_analysis', 'request', 'core.SpinCreditRequest', 'spin_credit_analysis',
                  'spin.request.view', ('spin.request.complete',), 'spin_form'),
    RecordAdapter('farmer_intake', 'intake_batch', 'core.JawabuFarmerUploadBatch', 'jawabu_portal',
                  'portal.imports.view', ('portal.imports.commit',), 'jawabu_farmers_review', True),
    RecordAdapter('fca_review', 'import_record', 'core.FcaImportRecord', 'jawabu_portal',
                  'portal.imports.view', ('portal.imports.commit',), 'fca_review', True),
    RecordAdapter('order_approval', 'order_update', 'core.OrderApprovalUpdate', 'jawabu_portal',
                  'portal.requisition.view', ('portal.requisition.write',), 'order_approval_form', True),
)
RECORD_ADAPTERS = MappingProxyType({(a.app, a.entity): a for a in _ADAPTERS})
_BY_MODEL = {a.model_label: a for a in _ADAPTERS}


def parse_reference(reference):
    if not isinstance(reference, dict) or set(reference) != {'version', 'app', 'entity', 'id'}:
        raise RecordUnavailable('Record unavailable.')
    if type(reference['version']) is not int or reference['version'] != 1:
        raise RecordUnavailable('Record unavailable.')
    if not all(isinstance(reference[key], str) for key in ('app', 'entity', 'id')):
        raise RecordUnavailable('Record unavailable.')
    adapter = RECORD_ADAPTERS.get((reference['app'], reference['entity']))
    try:
        identifier = str(UUID(reference['id']))
    except (ValueError, AttributeError):
        raise RecordUnavailable('Record unavailable.') from None
    if adapter is None or identifier != reference['id']:
        raise RecordUnavailable('Record unavailable.')
    return adapter, identifier


def record_reference(record):
    adapter = _BY_MODEL.get(record._meta.label)
    if adapter is None:
        raise RecordUnavailable('Record unavailable.')
    return adapter.generate(record)


def include_record_reference(parameter):
    """Add a reference to an existing authorized projection without new reads."""
    def decorate(serializer):
        @wraps(serializer)
        def wrapper(*args, **kwargs):
            payload = serializer(*args, **kwargs)
            record = args[0] if args else kwargs.get(parameter)
            if record is not None and isinstance(payload, dict):
                payload['record_ref'] = record_reference(record)
            return payload
        return wrapper
    return decorate


def resolve_record(reference, user, *, edit=False):
    adapter, identifier = parse_reference(reference)
    return adapter.resolve(identifier, user, edit=edit)


def describe_record(reference, user):
    adapter, _ = parse_reference(reference)
    return adapter.describe(reference, user)


def launch_record(reference, user):
    adapter, _ = parse_reference(reference)
    return adapter.launch(reference, user)
