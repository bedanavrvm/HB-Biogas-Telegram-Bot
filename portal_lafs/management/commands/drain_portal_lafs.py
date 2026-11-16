from django.core.management.base import BaseCommand
from portal_lafs.publication import drain


class Command(BaseCommand):
    help = "Resume at most ten due Portal Biogas LAF Drive archives."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true", help="Make bounded Drive calls; default is inspection only."
        )

    def handle(self, **options):
        if not options["apply"]:
            from core.models import IntegrationOperation

            count = (
                IntegrationOperation.objects.filter(operation_type="portal_laf_archive")
                .exclude(status="succeeded")
                .count()
            )
            self.stdout.write(f"DRY RUN: {count} retained Portal LAF archive operation(s); no Drive calls made.")
            return
        drain()
        self.stdout.write("Portal LAF archive pass completed.")
