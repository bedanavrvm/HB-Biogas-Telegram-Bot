"""Fail closed for writes targeting a Portal owner in a reviewed cutover."""
from .models import LegacyUpload
from django.db.models import Q
from django.core.exceptions import ValidationError


def active(group_id):
    return bool(group_id and LegacyUpload.objects.filter(batch__group_id=group_id,frozen=True).exists())


def request_blocked(request,kwargs):
    frozen=set(LegacyUpload.objects.filter(frozen=True).values_list('batch__group_id',flat=True))
    if not frozen:return False
    if request.path.startswith('/api/portal/legacy/uploads/'):return False
    # The authenticated pump reports a pause; it cannot publish during a cutover.
    if request.path=='/api/portal/publication/pump/':return False
    # IT must be able to recover global maintenance without releasing this owner hold.
    if request.path=='/api/portal/health/maintenance/':return False
    import json
    from core.models import JawabuFarmerMaster,RequisitionBatch,JawabuFarmerUploadBatch,InvoiceUploadBatch
    from payments.models import PaymentBatch
    from django.core.exceptions import FieldError
    try:body=json.loads(request.body or '{}') if request.content_type=='application/json' else request.POST
    except (ValueError,UnicodeDecodeError):body={}
    candidates=[]
    for key in ('group_id','group_configuration_id'):
        if body.get(key):
            # group_id can be a configured owner PK or its external Telegram group identifier.
            from core.models import GroupSheetConfiguration
            query=Q(group_id=str(body[key]))
            if str(body[key]).isdigit():query |= Q(pk=body[key])
            candidates.extend(GroupSheetConfiguration.objects.filter(query).values_list('pk',flat=True))
    for key in ('farmer_id','case_id','batch_id'):
        value=kwargs.get(key) or body.get(key)
        if not value:continue
        for model in (JawabuFarmerMaster,RequisitionBatch,PaymentBatch,JawabuFarmerUploadBatch,InvoiceUploadBatch):
            try:
                field='group_configuration_id' if model is not JawabuFarmerUploadBatch else 'group_id'
                ids=model.objects.filter(pk=value).values_list(field,flat=True)
                if model is JawabuFarmerUploadBatch:
                    from core.models import GroupSheetConfiguration
                    candidates.extend(GroupSheetConfiguration.objects.filter(group_id__in=ids).values_list('pk',flat=True))
                else:candidates.extend(ids)
            except (ValueError,ValidationError,FieldError):continue
    if candidates:return bool(frozen.intersection(candidates))
    # Requests without an accountable target cannot bypass a freeze by omitting ownership.
    return True
