import json
import re
from collections import defaultdict

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import (
    AccessGrant, ComplaintCaseStaffMember, JawabuPortalStaffMember,
    LegacyStaffUserMapping, StaffIdentityReview, TatTrackerStaffMember, UserProfile,
)
from core.services.telegram_identity import username_for_telegram_id


def _csv(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value or '').split(',') if item.strip()]


def _name_key(value):
    return re.sub(r'[^a-z0-9]', '', str(value or '').casefold())


def _legacy_records():
    records = []
    for row in JawabuPortalStaffMember.objects.filter(active=True):
        records.append({
            'model': 'JawabuPortalStaffMember', 'id': str(row.pk),
            'telegram_id': row.telegram_id, 'username': '', 'name': row.display_name,
            'workflow': 'jawabu_portal', 'roles': _csv(row.roles),
            'branches': _csv(row.branches), 'products': [], 'group': None,
        })
    for row in ComplaintCaseStaffMember.objects.filter(active=True).select_related('group_configuration'):
        records.append({
            'model': 'ComplaintCaseStaffMember', 'id': str(row.pk),
            'telegram_id': row.telegram_user_id, 'username': row.telegram_username, 'name': row.name,
            'workflow': 'complaint_cases', 'roles': [row.role],
            'branches': [], 'products': [], 'group': row.group_configuration,
        })
    for row in TatTrackerStaffMember.objects.filter(active=True).select_related('group_configuration'):
        records.append({
            'model': 'TatTrackerStaffMember', 'id': str(row.pk),
            'telegram_id': row.telegram_user_id, 'username': row.telegram_username, 'name': row.name,
            'workflow': 'tat_tracker', 'roles': _csv(row.roles),
            'branches': _csv(row.branches), 'products': _csv(row.products),
            'group': row.group_configuration,
        })
    return records


class Command(BaseCommand):
    help = 'Preview or apply migration of legacy Telegram staff into Django Users.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Write the displayed merge plan.')
        parser.add_argument('--json', action='store_true', help='Output the plan as JSON.')

    def handle(self, *args, **options):
        records = _legacy_records()
        by_telegram_id = defaultdict(list)
        name_only = defaultdict(list)
        for record in records:
            telegram_id = str(record['telegram_id'] or '').strip()
            if telegram_id:
                by_telegram_id[telegram_id].append(record)
            else:
                name_only[_name_key(record['name'])].append(record)
        plan = {
            'mode': 'apply' if options['apply'] else 'dry-run',
            'users': [
                {
                    'telegram_id': telegram_id,
                    'username': username_for_telegram_id(telegram_id),
                    'records': [{'model': row['model'], 'id': row['id']} for row in rows],
                    'grants': self._grant_plan(rows),
                }
                for telegram_id, rows in sorted(by_telegram_id.items())
            ],
            'manual_review': [
                {
                    'identity_key': key or 'blank-name',
                    'reason': 'Name-only identity cannot be auto-merged.',
                    'records': [{'model': row['model'], 'id': row['id'], 'name': row['name']} for row in rows],
                }
                for key, rows in sorted(name_only.items())
            ],
        }
        if options['json']:
            self.stdout.write(json.dumps(plan, indent=2))
        else:
            self.stdout.write(f"Mode: {plan['mode']}")
            self.stdout.write(f"High-confidence users: {len(plan['users'])}")
            self.stdout.write(f"Manual-review identities: {len(plan['manual_review'])}")
            for item in plan['users']:
                self.stdout.write(f"  {item['username']}: {len(item['records'])} legacy row(s), {len(item['grants'])} grant(s)")
            for item in plan['manual_review']:
                self.stdout.write(f"  REVIEW {item['identity_key']}: {len(item['records'])} row(s)")
        if not options['apply']:
            self.stdout.write(self.style.WARNING('Dry run only. Re-run with --apply after reviewing this plan.'))
            return
        with transaction.atomic():
            self._apply(by_telegram_id, plan['manual_review'])
        self.stdout.write(self.style.SUCCESS('Legacy staff migration applied.'))

    @staticmethod
    def _grant_plan(rows):
        grants = set()
        for row in rows:
            roles = row['roles'] or ['USER']
            branches = row['branches'] or ['']
            products = row['products'] or ['']
            for role in roles:
                for branch in branches:
                    for product in products:
                        grants.add((row['workflow'], role, branch, product, str(getattr(row['group'], 'pk', '') or '')))
        return [
            {'workflow': item[0], 'role': item[1], 'branch': item[2], 'product': item[3], 'group_id': item[4]}
            for item in sorted(grants)
        ]

    def _apply(self, by_telegram_id, manual_review):
        User = get_user_model()
        for telegram_id, rows in by_telegram_id.items():
            username = username_for_telegram_id(telegram_id)
            existing_profile = UserProfile.objects.select_related('user').filter(telegram_id=telegram_id).first()
            if existing_profile:
                user, created = existing_profile.user, False
            else:
                user, created = User.objects.get_or_create(
                    username=username, defaults={'is_active': True, 'is_staff': False},
                )
            if created:
                user.set_unusable_password()
            names = next((row['name'] for row in rows if row['name']), '')
            parts = str(names).strip().split(None, 1)
            if parts and not user.first_name:
                user.first_name = parts[0]
                user.last_name = parts[1] if len(parts) > 1 else ''
            user.is_active = True
            user.save()
            telegram_username = next((row['username'] for row in rows if row['username']), '')
            UserProfile.objects.update_or_create(
                user=user,
                defaults={'telegram_id': telegram_id, 'telegram_username': telegram_username},
            )
            for row in rows:
                LegacyStaffUserMapping.objects.update_or_create(
                    legacy_model=row['model'], legacy_id=row['id'],
                    defaults={'user': user, 'match_method': 'telegram_id', 'confidence': 'high'},
                )
                for role in row['roles'] or ['USER']:
                    Group.objects.get_or_create(name=role)
                    user.groups.add(Group.objects.get(name=role))
                    for branch in row['branches'] or ['']:
                        for product in row['products'] or ['']:
                            AccessGrant.objects.get_or_create(
                                user=user, workflow=row['workflow'], role=role,
                                branch=branch, product=product,
                                group_configuration=row['group'],
                                defaults={'source': 'legacy_migration'},
                            )
        for item in manual_review:
            StaffIdentityReview.objects.update_or_create(
                identity_key=item['identity_key'], status='pending',
                defaults={
                    'candidate_records': item['records'],
                    'reason': item['reason'],
                },
            )
