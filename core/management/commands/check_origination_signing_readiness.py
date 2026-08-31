"""Validate enabled Origination signing without external operations."""

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.services.origination_production import origination_signing_readiness_issues


class Command(BaseCommand):
    help = 'Check local Origination signing configuration and governed consent readiness.'

    def add_arguments(self, parser):
        parser.add_argument('--strict', action='store_true', help='Fail on warnings as well as errors.')
        parser.add_argument('--json', action='store_true', help='Print machine-readable results.')

    def handle(self, *args, **options):
        issues = origination_signing_readiness_issues(settings)
        if options['json']:
            self.stdout.write(json.dumps([issue.__dict__ for issue in issues], sort_keys=True))
        elif not issues:
            self.stdout.write(self.style.SUCCESS('Origination signing readiness checks passed.'))
        else:
            for issue in issues:
                style = self.style.ERROR if issue.severity == 'error' else self.style.WARNING
                self.stdout.write(style(f'[{issue.severity.upper()}] {issue.code}: {issue.message}'))
        if any(issue.severity == 'error' for issue in issues) or (options['strict'] and issues):
            raise CommandError('Origination signing readiness checks failed.')
