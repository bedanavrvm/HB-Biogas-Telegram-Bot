"""Verify that the ADMIN-to-BUSINESS_ADMIN data migration is unambiguous."""
from django.core.management.base import BaseCommand, CommandError

from core.services.business_admin import legacy_business_admin_cutover_issues


class Command(BaseCommand):
    help = 'Read-only preflight for the workflow ADMIN to BUSINESS_ADMIN cutover.'

    def add_arguments(self, parser):
        parser.add_argument('--strict', action='store_true', help='Exit non-zero when cutover blockers exist.')

    def handle(self, *args, **options):
        issues = legacy_business_admin_cutover_issues()
        if not issues:
            self.stdout.write(self.style.SUCCESS('Business Administrator cutover preflight passed.'))
            return
        for issue in issues:
            self.stderr.write(self.style.ERROR(f'[{issue.code}] {issue.message}'))
        if options['strict']:
            raise CommandError('Business Administrator cutover preflight failed.')
