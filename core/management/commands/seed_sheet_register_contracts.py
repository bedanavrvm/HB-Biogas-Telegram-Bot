"""Preview or create explicit Sheet register contracts; no Sheet calls are made."""
from django.core.management.base import BaseCommand, CommandError

from core.models import GroupSheetConfiguration, SheetRegisterContract
from core.services.sheet_schema import SheetSchema
from core.services.tat_tracker import configured_products, is_tat_tracker_workflow


def _contract_defaults(product):
    return {
        'sheet_name': product.sheet_name,
        'subject_type': SheetRegisterContract.SUBJECT_TAT_CASE,
        'header_row': 2,
        'data_start_row': 5,
        'row_key_header': 'Case ID',
        'expected_headers': ['Case ID', 'ID NUMBER', 'PHONE NUMBER'],
        'field_ownership': {
            'Case ID': {'owner': SheetRegisterContract.OWNER_IMMUTABLE, 'model_field': 'case_id'},
            'ID NUMBER': {'owner': SheetRegisterContract.OWNER_IMMUTABLE, 'model_field': 'national_id', 'comparison': 'digits'},
            'PHONE NUMBER': {'owner': SheetRegisterContract.OWNER_IMMUTABLE, 'model_field': 'primary_phone', 'comparison': 'digits'},
        },
    }


def _standard_register_defaults(config):
    """Derive a schema-only contract for a non-TAT published register.

    The ownership map is conservative: only fields already marked writable by
    Django are backend-owned. Remaining cells are ``derived`` until an
    operator explicitly maps them to a canonical model field.
    """
    schema = SheetSchema.from_config(config.sheet_schema or {})
    headers = list(schema.columns)
    header_row = int((config.workflow or {}).get('header_row') or schema.header_row or 1)
    formula_headers = {schema.normalize(value) for value in schema.formula_headers}
    backend_headers = {
        schema.normalize(value)
        for value in (schema.bot_writable_headers | schema.case_update_headers)
    }
    ownership = {}
    for header in headers:
        normalized = schema.normalize(header)
        if normalized in formula_headers:
            owner = SheetRegisterContract.OWNER_FORMULA
        elif normalized in backend_headers:
            owner = SheetRegisterContract.OWNER_BACKEND
        else:
            owner = SheetRegisterContract.OWNER_DERIVED
        ownership[header] = {'owner': owner}
    return {
        'sheet_name': config.sheet_name,
        'subject_type': SheetRegisterContract.SUBJECT_NONE,
        'header_row': max(header_row, 1),
        'data_start_row': max(header_row, 1) + 1,
        'row_key_header': schema.header('message_id'),
        'expected_headers': headers,
        'field_ownership': ownership,
    }


class Command(BaseCommand):
    help = 'Preview Sheet publication contracts; use --apply to create missing local contract rows only.'

    def add_arguments(self, parser):
        parser.add_argument('--group-id', help='Limit to one configured group.')
        parser.add_argument(
            '--include-standard-registers', action='store_true',
            help='Also stage schema-only contracts for non-TAT Django-published registers.',
        )
        parser.add_argument('--apply', action='store_true', help='Create missing contract rows in Django. Does not call or edit Google Sheets.')

    def handle(self, *args, **options):
        configs = GroupSheetConfiguration.objects.filter(enabled=True)
        group_id = str(options.get('group_id') or '').strip()
        if group_id:
            configs = configs.filter(group_id=group_id)
        configs = list(configs)
        if not configs:
            raise CommandError('No enabled group configuration matched.')

        created = 0
        for config in configs:
            if is_tat_tracker_workflow(config):
                contract_specs = [
                    (f'tat_{product.key}', product.sheet_name, _contract_defaults(product))
                    for product in configured_products(config.workflow)
                ]
            elif options['include_standard_registers']:
                contract_specs = [('published_register', config.sheet_name, _standard_register_defaults(config))]
            else:
                self.stdout.write(
                    f'{config.group_id}: skipped non-TAT register; use --include-standard-registers to stage its schema contract.'
                )
                continue
            for register_key, sheet_name, defaults in contract_specs:
                existing = SheetRegisterContract.objects.filter(
                    group_configuration=config, register_key=register_key,
                ).first()
                if existing:
                    self.stdout.write(f'{config.group_id} / {register_key}: existing contract retained.')
                    continue
                if options['apply']:
                    contract = SheetRegisterContract(
                        group_configuration=config,
                        register_key=register_key,
                        **defaults,
                    )
                    contract.full_clean()
                    contract.save()
                    created += 1
                    self.stdout.write(f'{config.group_id} / {register_key}: created local contract for {sheet_name}.')
                else:
                    self.stdout.write(
                        f'{config.group_id} / {register_key}: would create a local contract for {sheet_name}.'
                    )
        if options['apply']:
            self.stdout.write(f'Created {created} contract(s). Existing contracts were not overwritten.')
        else:
            self.stdout.write('Dry-run only. Re-run with --apply after confirming each target worksheet/header layout.')
