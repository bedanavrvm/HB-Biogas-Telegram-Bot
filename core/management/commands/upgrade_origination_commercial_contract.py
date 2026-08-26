import hashlib
import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core import signing
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import (
    OriginationDataField,
    OriginationDocumentTemplate,
    OriginationProductDefinition,
    OriginationProductDefinitionEvent,
)
from core.services.origination_commercial_terms import (
    COMMERCIAL_KEYS,
    merge_commercial_contract,
)


SALT = 'core.origination.commercial-contract-upgrade.v2'


def _fingerprint(product):
    value = {
        'id': str(product.pk), 'version': product.version,
        'lifecycle_status': product.lifecycle_status,
        'updated_at': product.updated_at.isoformat(),
        'form_schema': product.form_schema,
        'signer_rules': product.signer_rules,
    }
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(',', ':'), default=str,
    ).encode()).hexdigest()


class Command(BaseCommand):
    help = (
        'Dry-run and apply an exact signed manifest that upgrades only editable '
        'Origination product definitions to the governed Commercial Terms contract.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--manifest-out', help='Write the signed dry-run manifest to this file.')
        parser.add_argument('--apply-manifest', help='Apply the signed manifest stored in this file.')
        parser.add_argument('--actor', help='Username of the active Django Superuser applying the manifest.')

    def _catalogue(self):
        fields = {
            item.key: item for item in OriginationDataField.objects.filter(
                key__in=COMMERCIAL_KEYS, active=True,
            )
        }
        missing = sorted(set(COMMERCIAL_KEYS) - set(fields))
        if missing:
            raise CommandError(
                'Apply migrations before running this command. Missing canonical fields: '
                + ', '.join(missing)
            )
        return fields

    def handle(self, *args, **options):
        fields = self._catalogue()
        if options.get('apply_manifest'):
            return self._apply(Path(options['apply_manifest']), options.get('actor'), fields)
        drafts = list(OriginationProductDefinition.objects.filter(
            lifecycle_status=OriginationProductDefinition.STATUS_DRAFT,
            product_version__isnull=False,
        ).order_by('product_key', 'version'))
        records = []
        for product in drafts:
            upgraded = merge_commercial_contract(product.form_schema, fields=fields)
            if upgraded != product.form_schema:
                records.append({
                    'id': str(product.pk), 'fingerprint': _fingerprint(product),
                    'product_key': product.product_key, 'version': product.version,
                })
        successor_required = list(OriginationProductDefinition.objects.filter(
            lifecycle_status=OriginationProductDefinition.STATUS_PUBLISHED,
            product_version__isnull=False,
        ).exclude(product_key__in=[item.product_key for item in drafts]).values(
            'id', 'product_key', 'version',
        ))
        payload = {
            'contract_version': 2,
            'records': records,
            'published_requiring_successor': [
                {**item, 'id': str(item['id'])} for item in successor_required
            ],
        }
        token = signing.dumps(payload, salt=SALT, compress=True)
        output = {
            'mode': 'dry_run', 'draft_update_count': len(records),
            'published_successor_count': len(successor_required),
            'drafts': records,
            'published_requiring_successor': payload['published_requiring_successor'],
        }
        if options.get('manifest_out'):
            path = Path(options['manifest_out'])
            path.write_text(token, encoding='utf-8')
            output['manifest_path'] = str(path.resolve())
        else:
            output['signed_manifest'] = token
        self.stdout.write(json.dumps(output, indent=2, default=str))

    def _apply(self, path, username, fields):
        if not path.is_file():
            raise CommandError(f'Manifest file not found: {path}')
        if not username:
            raise CommandError('--actor is required when applying a manifest.')
        actor = get_user_model().objects.filter(
            username=username, is_active=True, is_superuser=True,
        ).first()
        if not actor:
            raise CommandError('The apply actor must be an active Django Superuser.')
        try:
            payload = signing.loads(path.read_text(encoding='utf-8').strip(), salt=SALT)
        except signing.BadSignature as exc:
            raise CommandError('The commercial-contract manifest is invalid or has been altered.') from exc
        records = payload.get('records') if isinstance(payload, dict) else None
        if payload.get('contract_version') != 2 or not isinstance(records, list):
            raise CommandError('The manifest has an unsupported contract version.')
        with transaction.atomic():
            locked = {
                str(item.pk): item for item in OriginationProductDefinition.objects.select_for_update().filter(
                    pk__in=[record.get('id') for record in records],
                )
            }
            if len(locked) != len(records):
                raise CommandError('One or more manifest targets no longer exist. No changes were applied.')
            for record in records:
                product = locked.get(str(record.get('id')))
                if (
                    not product
                    or product.lifecycle_status != product.STATUS_DRAFT
                    or _fingerprint(product) != record.get('fingerprint')
                ):
                    raise CommandError(
                        f'{record.get("product_key") or record.get("id")} changed after dry-run. '
                        'No changes were applied; generate a fresh manifest.'
                    )
            for record in records:
                product = locked[str(record['id'])]
                product.form_schema = merge_commercial_contract(product.form_schema, fields=fields)
                product.save(update_fields=['form_schema', 'updated_at'])
                product.document_templates.filter(
                    document_role=OriginationDocumentTemplate.ROLE_PRIMARY,
                    status__in=[
                        OriginationDocumentTemplate.STATUS_READY,
                        OriginationDocumentTemplate.STATUS_UPLOAD_FAILED,
                    ],
                ).update(form_schema=product.form_schema)
                OriginationProductDefinitionEvent.objects.create(
                    product_definition=product,
                    action='commercial_contract_upgraded', actor=actor,
                    metadata={
                        'manifest_fingerprint': record['fingerprint'],
                        'contract_version': 2,
                    },
                )
        self.stdout.write(self.style.SUCCESS(
            f'Applied the Commercial Terms contract to {len(records)} exact draft product definition(s). '
            'Existing applications and published definitions were untouched.'
        ))
