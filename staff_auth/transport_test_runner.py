"""Restore the migration-only audit fixture for a reused isolated test database."""
from django.test.runner import DiscoverRunner


class ClosedTransportRunner(DiscoverRunner):
    def setup_databases(self, **kwargs):
        result = super().setup_databases(**kwargs)
        from core.models import ComplianceAuditChainState, ComplianceAuditEvent
        if not ComplianceAuditChainState.objects.filter(singleton=1).exists():
            if ComplianceAuditEvent.objects.exists():
                raise RuntimeError('Refuse to recreate a test audit chain over existing evidence.')
            ComplianceAuditChainState.objects.create(singleton=1)
        return result
