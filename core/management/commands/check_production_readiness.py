"""Validate settings required for a safe production release."""

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.production import production_readiness_issues


class Command(BaseCommand):
    help = 'Check production configuration without calling external services.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--strict',
            action='store_true',
            help='Fail when warnings are present as well as errors.',
        )
        parser.add_argument(
            '--json',
            action='store_true',
            help='Print machine-readable results for deployment tooling.',
        )

    def handle(self, *args, **options):
        issues = production_readiness_issues(settings)
        if options['json']:
            self.stdout.write(
                json.dumps(
                    [issue.__dict__ for issue in issues],
                    sort_keys=True,
                )
            )
        elif not issues:
            self.stdout.write(self.style.SUCCESS('Production readiness checks passed.'))
        else:
            for issue in issues:
                line = f'[{issue.severity.upper()}] {issue.code}: {issue.message}'
                style = self.style.ERROR if issue.severity == 'error' else self.style.WARNING
                self.stdout.write(style(line))

        errors = [issue for issue in issues if issue.severity == 'error']
        if errors or (options['strict'] and issues):
            raise CommandError('Production readiness checks failed.')
