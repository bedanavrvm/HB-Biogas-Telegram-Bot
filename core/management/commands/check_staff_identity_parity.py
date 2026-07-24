import json

from django.core.exceptions import ObjectDoesNotExist
from django.core.management.base import BaseCommand, CommandError

from core.management.commands.migrate_legacy_staff import _legacy_records
from core.models import AccessGrant, LegacyStaffUserMapping, StaffIdentityReview


class Command(BaseCommand):
    help = 'Read-only parity audit between active legacy staff rows and canonical Users.'

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true', help='Emit machine-readable results.')
        parser.add_argument(
            '--allow-pending-reviews', action='store_true',
            help='Do not fail solely because name-only identity reviews remain pending.',
        )

    def handle(self, *args, **options):
        records = _legacy_records()
        failures = []
        checked_users = set()
        mapped_count = 0

        mappings = {
            (mapping.legacy_model, mapping.legacy_id): mapping
            for mapping in LegacyStaffUserMapping.objects.select_related('user', 'user__staff_profile')
        }
        for record in records:
            key = (record['model'], record['id'])
            mapping = mappings.get(key)
            label = f'{record["model"]}:{record["id"]}'
            if mapping is None:
                if not str(record.get('telegram_id') or '').strip():
                    # Name-only rows are deliberately unresolved until their
                    # StaffIdentityReview is completed by an administrator.
                    continue
                failures.append({'record': label, 'issue': 'missing_mapping'})
                continue
            mapped_count += 1
            user = mapping.user
            checked_users.add(user.pk)
            if not user.is_active:
                failures.append({'record': label, 'issue': 'mapped_user_inactive', 'user': user.get_username()})
            try:
                profile = user.staff_profile
            except ObjectDoesNotExist:
                profile = None
            telegram_id = str(record.get('telegram_id') or '').strip()
            if profile is None:
                failures.append({'record': label, 'issue': 'missing_user_profile', 'user': user.get_username()})
            elif telegram_id and profile.telegram_id != telegram_id:
                failures.append({
                    'record': label, 'issue': 'telegram_id_mismatch',
                    'legacy': telegram_id, 'canonical': profile.telegram_id,
                })

            expected_roles = record['roles'] or ['USER']
            expected_branches = record['branches'] or ['']
            expected_products = record['products'] or ['']
            for role in expected_roles:
                for branch in expected_branches:
                    for product in expected_products:
                        grant_exists = AccessGrant.objects.filter(
                            user=user,
                            workflow=record['workflow'],
                            role=role,
                            branch=branch,
                            product=product,
                            group_configuration=record['group'],
                            active=True,
                        ).exists()
                        if not grant_exists:
                            failures.append({
                                'record': label,
                                'issue': 'missing_access_grant',
                                'workflow': record['workflow'],
                                'role': role,
                                'branch': branch,
                                'product': product,
                                'group_id': str(getattr(record['group'], 'pk', '') or ''),
                            })

        pending_reviews = StaffIdentityReview.objects.filter(status='pending').count()
        if pending_reviews and not options['allow_pending_reviews']:
            failures.append({
                'record': 'manual_review_queue',
                'issue': 'pending_identity_reviews',
                'count': pending_reviews,
            })

        result = {
            'ok': not failures,
            'active_legacy_records': len(records),
            'mapped_legacy_records': mapped_count,
            'canonical_users_checked': len(checked_users),
            'pending_identity_reviews': pending_reviews,
            'failures': failures,
        }
        if options['json']:
            self.stdout.write(json.dumps(result, indent=2))
        else:
            self.stdout.write(f"Active legacy records: {result['active_legacy_records']}")
            self.stdout.write(f"Mapped records: {mapped_count}")
            self.stdout.write(f"Canonical users checked: {len(checked_users)}")
            self.stdout.write(f"Pending manual reviews: {pending_reviews}")
            for failure in failures:
                self.stdout.write(self.style.ERROR(
                    f"FAIL {failure['record']}: {failure['issue']}"
                ))
        if failures:
            raise CommandError(f'Staff identity parity failed with {len(failures)} issue(s).')
        self.stdout.write(self.style.SUCCESS('Staff identity parity passed.'))
