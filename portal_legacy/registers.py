"""The two reviewed legacy registers use the Portal's canonical partner routing."""
from core.models import JawabuFarmerMaster
from core.services.requisition_partners import PARTNER_HB,PARTNER_ECO,fulfillment_partner_for_farmer

SOURCE_SHEETS=(('Master Data','Master Data'),('Eco-conserve','Eco-conserve'))


def partner_for_source(source):
    if source not in dict(SOURCE_SHEETS):raise ValueError('Choose Master Data or Eco-conserve.')
    return PARTNER_ECO if source=='Eco-conserve' else PARTNER_HB


def owns_case(upload,farmer):
    return farmer.group_configuration_id==upload.batch.group_id and fulfillment_partner_for_farmer(farmer)==partner_for_source(upload.source_sheet)


def case_ids(upload):
    cases=JawabuFarmerMaster.objects.filter(group_configuration_id=upload.batch.group_id).only('pk','group_configuration_id','legacy_fulfillment_partner','county','hb_sales_person')
    return [str(case.pk) for case in cases.iterator(chunk_size=1000) if owns_case(upload,case)]
