"""Validate TAT production readiness without external calls or writes."""

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.services.tat_production import tat_production_readiness_issues


class Command(BaseCommand):
    help = 'Check local TAT production configuration, routing, and scheduler health.'

    def add_arguments(self, parser):
        parser.add_argument('--strict', action='store_true', help='Fail on warnings as well as errors.')
        parser.add_argument('--json', action='store_true', help='Print machine-readable results.')

    def handle(self, *args, **options):
        issues = tat_production_readiness_issues(settings)
        if options['json']:
            self.stdout.write(json.dumps([issue.__dict__ for issue in issues], sort_keys=True))
        elif not issues:
            self.stdout.write(self.style.SUCCESS('TAT production readiness checks passed.'))
        else:
            for issue in issues:
                style = self.style.ERROR if issue.severity == 'error' else self.style.WARNING
                self.stdout.write(style(f'[{issue.severity.upper()}] {issue.code}: {issue.message}'))
        if any(issue.severity == 'error' for issue in issues) or (options['strict'] and issues):
            raise CommandError('TAT production readiness checks failed.')
