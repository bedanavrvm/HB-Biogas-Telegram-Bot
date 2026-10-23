"""Temporary synthetic visual evidence, not a production entrypoint."""
import json
import os
from pathlib import Path
import subprocess
from django.conf import settings
from core.models import AccessGrant
from staff_auth.tests import PASSWORD
from staff_auth.tests_complaints_operations_transport import ComplaintsOperationsTransportTests as Base

class ComparisonTests(Base):
    test_native_authenticated_complaints_workspace = None

    def test_source_bound_comparison(self):
        AccessGrant.objects.create(user=self.user,workflow='complaint_cases',role='IT',group_configuration=self.group)
        root=Path(settings.BASE_DIR)
        for index,phase in enumerate(('before','after')):
            result=subprocess.run([os.environ['STAFF_BROWSER_TEST_NODE'],str(root/'test-results/spec18_compare.js')],
                input=json.dumps({'origin':self.live_server_url,'username':self.user.username,'password':PASSWORD,
                    'code':self.codes[index],'group':str(self.group.pk),'phase':phase}),
                cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=180)
            self.assertEqual(result.returncode,0,result.stderr[-4000:])
            print('Source-bound visual comparison',phase,result.stdout)
