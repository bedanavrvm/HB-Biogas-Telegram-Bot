"""Explicit IT corrections retain status history, source provenance and audit."""
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

FIELDS = ('customer_name', 'customer_phone', 'secondary_phone', 'customer_id', 'county',
          'sub_county', 'village', 'branch_region', 'complaint_category', 'complaint_description',
          'timestamp', 'date_resolved')


def values(case):
    return {name: timezone.localtime(getattr(case, name)).isoformat() if name in {'timestamp', 'date_resolved'} and getattr(case, name)
            else getattr(case, name) or '' for name in FIELDS}


def permitted(group, actor, case=None):
    from complaint_publications.services import is_it
    from core.services.complaint_cases import actor_can
    return bool(actor and is_it(actor) and actor_can(group, actor, 'complaint.case.manage', case))


def correct(group, actor, case_id, fields):
    from core.services import complaint_cases as cases
    from core.models import ParsedMessage, ComplaintCaseControl, ComplaintCaseEvent, CaseUpdate
    from core.services.compliance_audit import record_event
    if not permitted(group, actor):
        raise PermissionDenied('Only Complaints IT can correct case fields.')
    if set(fields) - set(FIELDS) - {'reason', 'expected_revision', 'client_request_id', 'group_id', 'init_data'}:
        raise cases.ComplaintCaseError('Only the displayed correction fields can be changed.')
    reason = str(fields.get('reason') or '').strip()
    if len(reason) > 2000:
        raise cases.ComplaintCaseError('Correction notes must be at most 2,000 characters.')
    reason = reason or 'Complaint fields corrected by IT.'
    key = cases.create_request_id(fields.get('client_request_id'))
    digest = cases.mutation_payload_hash({name: fields[name] for name in fields if name in FIELDS or name == 'reason'})
    original = cases._case_for_group(group.group_id, case_id, actor=actor)
    with transaction.atomic():
        case = ParsedMessage.objects.select_for_update().get(pk=original.pk)
        control = ComplaintCaseControl.objects.select_for_update().get(parsed_message=case)
        if not permitted(group, actor, case):
            raise PermissionDenied
        previous = control.events.filter(request_id=key).first()
        if previous:
            if previous.action != 'fields_corrected' or previous.payload_hash != digest:
                raise cases.ComplaintCaseError('That retry identifier belongs to another correction.')
            return cases.case_detail(group, case_id, actor)
        try:
            revision = int(fields.get('expected_revision'))
        except (TypeError, ValueError):
            raise cases.ComplaintCaseError('Refresh the case before saving.')
        if revision != control.revision:
            raise cases.ComplaintCaseConflict('This complaint changed. Review it before saving.', current_revision=control.revision)
        before = values(case)
        changes = {}
        for name in FIELDS:
            if name not in fields or fields[name] == before[name]:
                continue
            if not isinstance(fields[name], str):
                raise cases.ComplaintCaseError('Enter valid correction values.')
            value = fields[name].strip()
            if name in {'timestamp', 'date_resolved'}:
                try:
                    value = parse_datetime(value) if value else None
                except ValueError:
                    raise cases.ComplaintCaseError('Enter a valid date and time.')
                if fields[name].strip() and value is None:
                    raise cases.ComplaintCaseError('Enter a valid date and time.')
                if value and timezone.is_naive(value):
                    value = timezone.make_aware(value, timezone.get_current_timezone())
                if not value and name == 'timestamp' or value and value > timezone.now():
                    raise cases.ComplaintCaseError('Reported date is required; dates cannot be in the future.')
            elif name in {'customer_phone', 'secondary_phone'} and value:
                value = cases.normalize_kenyan_phone(value)
                if not value:
                    raise cases.ComplaintCaseError('Enter a valid Kenyan phone number.')
            elif name == 'customer_id' and value:
                value = cases.numeric_customer_id(value)
            elif len(value) > (5000 if name == 'complaint_description' else case._meta.get_field(name).max_length or 255):
                raise cases.ComplaintCaseError('The corrected value is too long.')
            if name in {'customer_name', 'customer_phone', 'customer_id', 'complaint_description'} and not value:
                raise cases.ComplaintCaseError('Required customer and complaint fields cannot be cleared.')
            changes[name] = value
        if not changes:
            raise cases.ComplaintCaseError('Change at least one field before saving.')
        reported, resolved = changes.get('timestamp', case.timestamp), changes.get('date_resolved', case.date_resolved)
        if resolved and (not reported or resolved < reported or case.complaint_status != 'Closed'):
            raise cases.ComplaintCaseError('Resolved date must follow reporting and belongs only to closed cases.')
        category = cases.resolve_category(group, changes['complaint_category']) if 'complaint_category' in changes else None
        branch = cases.resolve_branch(changes['branch_region']) if changes.get('branch_region') else None
        if changes.get('branch_region') and not branch:
            raise cases.ComplaintCaseError('Choose a configured branch.')
        if {'county', 'sub_county'} & changes.keys():
            from core.services.location_catalog import resolve_location
            county_label = changes.get('county', case.county)
            county = resolve_location(county_label, location_type='county') if county_label else None
            sub = changes.get('sub_county', case.sub_county)
            sub_county = resolve_location(sub, location_type='sub_county', parent=county) if county and sub else None
            if county_label and not county or sub and not sub_county:
                raise cases.ComplaintCaseError('Choose a valid county and sub-county combination.')
        for name, value in changes.items():
            setattr(case, name, value)
        case.save(update_fields=list(changes))
        if category: control.category = category
        if 'branch_region' in changes: control.branch_ref = branch
        if {'county', 'sub_county'} & changes.keys():
            control.county_ref, control.sub_county_ref = county, sub_county
        if 'timestamp' in changes:
            control.sla_started_at = reported
            from datetime import timedelta
            control.sla_due_at = reported + timedelta(hours=control.sla_target_hours)
        case.complaint_control = control
        if not permitted(group, actor, case):
            raise PermissionDenied('The corrected values are outside your Complaints scope.')
        if {'customer_phone', 'customer_id'} & changes.keys():
            control.customer, control.customer_match_status = cases.match_customer(case.customer_id, case.customer_phone)
        control.revision += 1
        control.save()
        after = values(case)
        ComplaintCaseEvent.objects.create(case=control, actor=actor.user, actor_label=actor.name,
            revision=control.revision, action='fields_corrected', request_id=key, payload_hash=digest,
            before_values=before, after_values=after, reason=reason)
        update = CaseUpdate.objects.create(parsed_message=case, group_id=case.group_id, updated_by=actor.name,
            old_status=case.complaint_status, new_status=case.complaint_status, resolution_text=reason,
            raw_update_text='Audited IT field correction', source='mini_app_correction', client_request_id=key)
        record_event(workflow='complaint_cases', action='complaint.case.fields_corrected', category='correction',
            actor=actor.user, subject_type='complaint_case', subject_id=str(case.pk), request_id=key,
            deduplication_key=f'complaint-correction:{control.pk}:{key}', source_model='CaseUpdate', source_event_id=str(update.pk),
            before_values=before, after_values=after, metadata={'reason':reason}, sensitive=True)
        from complaint_publications.services import queue_sheet
        queue_sheet(group, case)
    return cases.case_detail(group, case_id, actor)
