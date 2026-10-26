"""Synthetic Origination checks; ignores .env and allows only loopback network I/O."""
import argparse
import json
import socket

from portal_local_audit import configure, OUTPUT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--postgres', action='store_true', help='Use the isolated loopback cluster on port 55439.')
    parser.add_argument('labels', nargs='*')
    args = parser.parse_args()
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    configure('origination-configuration.sqlite3')

    def local_connect(sock, address):
        if not isinstance(address, tuple) or address[0] not in {'127.0.0.1', 'localhost', '::1'}:
            raise OSError('Synthetic Origination checks allow loopback only')
        return original_connect(sock, address)

    def local_connect_ex(sock, address):
        if not isinstance(address, tuple) or address[0] not in {'127.0.0.1', 'localhost', '::1'}:
            raise OSError('Synthetic Origination checks allow loopback only')
        return original_connect_ex(sock, address)

    socket.socket.connect = local_connect
    socket.socket.connect_ex = local_connect_ex
    # create_connection dynamically calls the guarded socket.connect above.
    def local_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, **kwargs):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
            sock.settimeout(timeout)
        try:
            if source_address:
                sock.bind(source_address)
            sock.connect(address)
            return sock
        except BaseException:
            sock.close()
            raise
    socket.create_connection = local_connection
    from django.conf import settings
    from django.db import connections
    settings.SILENCED_SYSTEM_CHECKS = ['fields.W163', 'models.W046']
    if args.postgres:
        import dj_database_url
        database = dj_database_url.parse('postgresql://origination_test@127.0.0.1:55439/origination_test')
        settings.DATABASES = connections.configure_settings({'default': database})
        connections.settings['default'] = settings.DATABASES['default']
        if hasattr(connections._connections, 'default'):
            del connections['default']
        assert connections['default'].vendor == 'postgresql'
    from django.test.runner import DiscoverRunner
    class Runner(DiscoverRunner):
        def setup_databases(self, **kwargs):
            configuration = super().setup_databases(**kwargs)
            from core.models import ComplianceAuditChainState
            ComplianceAuditChainState.objects.get_or_create(singleton=1)
            from core.models import WorkflowRoleCapability
            from core.services.workflow_capabilities import capability_definitions
            for definition in capability_definitions():
                if definition.workflow == 'loan_origination':
                    for role in definition.default_roles:
                        WorkflowRoleCapability.objects.get_or_create(workflow='loan_origination', role=role,
                            capability_key=definition.key, defaults={'enabled': True, 'effect': 'allow'})
            return configuration

        def run_suite(self, suite, **kwargs):
            self.result = super().run_suite(suite, **kwargs)
            return self.result
    labels = args.labels or ['origination.tests_configuration_isolation']
    runner = Runner(verbosity=1, interactive=False, keepdb=True)
    failures = runner.run_tests(labels)
    summary = {'tests_run': runner.result.testsRun, 'failure_count': failures,
        'database': 'PostgreSQL' if args.postgres else 'SQLite', 'network': 'loopback only', 'labels': labels,
        'failures': [{'test': test.id(), 'traceback': trace} for test, trace in runner.result.failures],
        'errors': [{'test': test.id(), 'traceback': trace} for test, trace in runner.result.errors],
        'skipped': [{'test': test.id(), 'reason': reason} for test, reason in runner.result.skipped]}
    path = OUTPUT / ('origination-postgres-summary.json' if args.postgres else 'origination-sqlite-summary.json')
    path.write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in summary.items() if key not in {'failures', 'errors', 'skipped', 'labels'}}))
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
