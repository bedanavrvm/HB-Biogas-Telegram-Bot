"""Explicit, audited successor preparation; never rewrites an existing case."""
from copy import deepcopy

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.models import ProductVersion, TatConfigurationEvent
from core.services.external_resilience import payload_digest
from core.services.product_catalog import clone_product_version, publish_product_version
from core.services.tat_configuration import GLOBAL_TAT_STAGES


STAGE_KEY = 'bm_analysis_approval'


def _draft_digest(version):
    from core.services.product_catalog import serialize_product_version
    from core.services.tat_configuration import serialize_tat_configuration
    return payload_digest({'terms': serialize_product_version(version),
                           'tat': serialize_tat_configuration(version)})


def inventory(product_codes=()):
    today = timezone.localdate()
    versions = ProductVersion.objects.filter(
        status__in=[ProductVersion.STATUS_PUBLISHED, ProductVersion.STATUS_SCHEDULED],
        tat_configuration__isnull=False, product__active=True,
    ).filter(Q(status=ProductVersion.STATUS_SCHEDULED) | (
        Q(effective_from__lte=today) & (Q(effective_to__isnull=True) | Q(effective_to__gte=today))
    )).select_related('product', 'tat_configuration').order_by('product__code', 'version')
    if product_codes:
        versions = versions.filter(product__code__in=product_codes)
    result = []
    for version in versions:
        keys = [stage.get('key') for stage in version.tat_configuration.stages]
        if 'mpesa_to_admin' not in keys:
            continue
        drafts = list(version.product.versions.filter(status='draft').values_list('pk', flat=True))
        event = TatConfigurationEvent.objects.filter(action='bm_analysis_stage_prepared',
                     metadata__source_version_id=str(version.pk)).first()
        prepared_id = (event.metadata or {}).get('product_version_id') if event else None
        blockers = []
        if version.status == ProductVersion.STATUS_SCHEDULED:
            blockers.append('Review the scheduled product before preparing this change.')
        from origination.models import OriginationProductDefinition
        if OriginationProductDefinition.objects.filter(
            product_version=version, is_active=True, lifecycle_status='published',
        ).exists():
            blockers.append('A published Origination product uses these terms. Coordinate its successor before replacing this shared version.')
        if drafts and (len(drafts) != 1 or str(drafts[0]) != prepared_id):
            blockers.append('An unrelated editable product version already exists.')
        if 'mpesa_verified' not in keys:
            blockers.append('The Admin verification stage needs a reviewed mapping.')
        if STAGE_KEY in keys:
            stage = next(item for item in version.tat_configuration.stages if item.get('key') == STAGE_KEY)
            if (keys.count(STAGE_KEY) != 1 or keys.index(STAGE_KEY) != keys.index('mpesa_to_admin') + 1
                    or stage.get('role') != 'BM' or set(stage.get('options') or []) != {'Approved', 'Declined'}):
                blockers.append('The existing BM stage needs review of its order, role and outcomes.')
        if version.product.versions.filter(status='scheduled').exclude(pk=version.pk).exists():
            blockers.append('A scheduled version needs review before replacement.')
        result.append({'product': version.product.code, 'source_id': str(version.pk),
                       'version': version.version, 'already_present': STAGE_KEY in keys,
                       'prepared_id': prepared_id, 'blockers': blockers})
    return result


@transaction.atomic
def prepare(source_id, *, actor):
    if not actor or not actor.is_active or not actor.is_superuser:
        raise ValueError('Only an active Django Superuser can prepare this TAT change.')
    source = ProductVersion.objects.select_for_update().select_related('product').get(pk=source_id)
    plan = next((row for row in inventory([source.product.code]) if row['source_id'] == str(source.pk)), None)
    if plan is None:
        raise ValueError('This product is no longer eligible for the reviewed rollout.')
    if plan['blockers']:
        raise ValueError(' '.join(plan['blockers']))
    if plan['already_present']:
        return source
    if plan['prepared_id']:
        return ProductVersion.objects.get(pk=plan['prepared_id'])
    draft = clone_product_version(source, actor=actor)
    config = draft.tat_configuration
    before = deepcopy(config.stages)
    stages = deepcopy(config.stages)
    position = next(index for index, stage in enumerate(stages) if stage['key'] == 'mpesa_to_admin')
    stage = deepcopy(next(stage for stage in GLOBAL_TAT_STAGES if stage['key'] == STAGE_KEY))
    stage['sheet_header'] = 'BM analysis approval'
    stages.insert(position + 1, stage)
    config.stages = stages
    config.stage_tat_columns = [*config.stage_tat_columns, {
        'stage_key': STAGE_KEY, 'aliases': ['BM analysis approval TAT Minutes'],
    }]
    config.save()
    draft.save(update_fields=['updated_at'])
    TatConfigurationEvent.objects.create(
        action='bm_analysis_stage_prepared', actor=actor,
        request_id=f'bm-analysis-stage:{source.pk}', reason='Add the distinct BM approval after M-PESA submission for new cases only.',
        before_snapshot={'stages': before}, after_snapshot={'stages': stages},
        metadata={'source_version_id': str(source.pk), 'product_version_id': str(draft.pk),
                  'prepared_digest': _draft_digest(draft)},
    )
    return draft


@transaction.atomic
def publish(draft, *, actor):
    draft = ProductVersion.objects.select_for_update().get(pk=draft.pk)
    if not any(stage.get('key') == STAGE_KEY for stage in draft.tat_configuration.stages):
        raise ValueError('This draft does not contain the reviewed BM stage.')
    if draft.status == ProductVersion.STATUS_DRAFT:
        from origination.models import OriginationProductDefinition
        if OriginationProductDefinition.objects.filter(product_version_id=draft.supersedes_id,
                is_active=True, lifecycle_status='published').exists():
            raise ValueError('Coordinate the published Origination product before replacing this shared version.')
        event = TatConfigurationEvent.objects.filter(action='bm_analysis_stage_prepared',
                     metadata__product_version_id=str(draft.pk)).first()
        if not event or (event.metadata or {}).get('prepared_digest') != _draft_digest(draft):
            raise ValueError('The prepared product changed. Review and publish it through Product setup instead.')
    published = publish_product_version(version=draft, actor=actor, allow_same_day_replacement=True)
    from core.models import WorkflowRoleCapability
    from core.services.workflow_capabilities import capability_definitions
    from core.services.access_control import apply_capability_matrix_direct
    capability_definitions.cache_clear()
    # Preserve every existing matrix choice; add only the explicitly approved
    # BM action using the established audited, policy-versioned Superuser path.
    allowed = set(WorkflowRoleCapability.objects.filter(
        workflow='tat_tracker', role='BM', effect='allow').values_list('capability_key', flat=True))
    apply_capability_matrix_direct(
        requester=actor, workflow='tat_tracker', role='BM',
        capability_keys=allowed | {'tat.stage.bm_analysis_approval.update'},
        reason='Enable the BM analysis approval stage for new TAT loan cycles.',
        request_key=f'bm-analysis-capability:{published.pk}',
    )
    return published
