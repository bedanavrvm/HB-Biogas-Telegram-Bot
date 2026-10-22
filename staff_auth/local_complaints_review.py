"""Opt-in human review host reusing the real isolated native-session fixture.

Run only the exact test label in browser/README.md. No production mount, auth
bypass, exported proof, fixture fallback, or connection to the operational DB.
"""
import os
from pathlib import Path
import threading
from unittest import skipUnless

from django.conf import settings
from django.test import override_settings

from core.models import AccessGrant, BranchServiceArea, ComplaintCategory, OperationalLocation
from core.tests_browser_complaints import synthetic_case
from core.services.complaint_cases import ensure_case_control
from django.utils import timezone
from datetime import timedelta
from . import local_complaints_review_urls as review_urls
from . import tests_complaints_operations_transport as operations
from .tests import PASSWORD


@skipUnless(os.environ.get('RUN_COMPLAINTS_LOCAL_REVIEW') == '1', 'Human local-review opt-in only.')
@override_settings(ROOT_URLCONF='staff_auth.local_complaints_review_urls')
class ComplaintsLocalReview(operations.ComplaintsOperationsTransportTests):
    host = '127.0.0.1'
    port = int(os.environ.get('COMPLAINTS_LOCAL_REVIEW_PORT', '8769'))

    def test_native_authenticated_complaints_workspace(self):
        expected = Path(settings.STAFF_BROWSER_LOCAL_REVIEW_DATABASE).resolve()
        self.assertEqual(expected.parent, (settings.BASE_DIR / 'test-results/complaints-local-review').resolve())
        self.assertEqual(Path(settings.DATABASES['default']['NAME']).resolve(), expected)
        from .transport_test_urls import assets
        review_urls.review_assets = assets(operations=True)
        AccessGrant.objects.create(user=self.user, workflow='complaint_cases', role='IT', group_configuration=self.group)
        branch = OperationalLocation.objects.create(location_type='branch', code='LOCAL-REVIEW', name='Local Review Branch')
        county = OperationalLocation.objects.create(location_type='county', code='LOCAL-COUNTY', name='Sample County')
        OperationalLocation.objects.create(location_type='sub_county', code='LOCAL-AREA', name='Sample Constituency', parent=county)
        BranchServiceArea.objects.create(branch=branch, area=county)
        ComplaintCategory.objects.create(key='local-review-service', label='Service issue')
        # Varied review-only records expose density, sorting, filters and charts.
        branches = [branch]
        for index, label in enumerate(('Riverside', 'Hillview')):
            branches.append(OperationalLocation.objects.create(location_type='branch', code=f'REVIEW-{index}', name=f'Sample {label}'))
        categories = ['Service issue', 'Installation', 'Training', 'Maintenance']
        for index in range(20, 56):
            closed = index % 3 == 0
            start = timezone.now() - timedelta(days=(index * 7) % 110, hours=index % 12)
            case = synthetic_case(self.group, index, customer_name=f'Sample Applicant {index}',
                branch_region=branches[index % 3].name, complaint_category=categories[index % 4], timestamp=start,
                complaint_status='Closed' if closed else 'Reopened' if index % 7 == 0 else 'Open',
                date_resolved=start + timedelta(days=2) if closed else None)
            ensure_case_control(case)
        review_urls.review_user, review_urls.review_password = self.user, PASSWORD
        print(f'Local synthetic review ready: {self.live_server_url}/_review/', flush=True)
        # Independent process: the agent remains responsive and test runs use a
        # different database. No credential/proof is written to output or disk.
        try:
            threading.Event().wait(timeout=min(12 * 60 * 60, max(1, int(os.environ.get('COMPLAINTS_LOCAL_REVIEW_SECONDS', '43200')))))
        finally:
            review_urls.review_user, review_urls.review_password = None, ''
            review_urls.review_assets = {}
