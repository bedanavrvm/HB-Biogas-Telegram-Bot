"""Temporary synthetic visual evidence, not a production entrypoint."""
import json
import os
from pathlib import Path
import subprocess
from io import BytesIO
from unittest.mock import patch
from PIL import Image
from pypdf import PdfWriter
from django.conf import settings
from core.models import AccessGrant, CaseUpdate, ComplaintCaseEvidence
from staff_auth.tests import PASSWORD
from staff_auth.tests_complaints_operations_transport import ComplaintsOperationsTransportTests as Base

class ComparisonTests(Base):
    test_native_authenticated_complaints_workspace = None

    def test_source_bound_comparison(self):
        AccessGrant.objects.create(user=self.user,workflow='complaint_cases',role='IT',group_configuration=self.group)
        picture=BytesIO();Image.new('RGB',(600,400),'#336699').save(picture,'PNG')
        pdf=BytesIO();writer=PdfWriter();writer.add_blank_page(width=300,height=400);writer.write(pdf)
        files={'synthetic-image':picture.getvalue(),'synthetic-pdf':pdf.getvalue()}
        for name,mime,key in [('Synthetic comparison.png','image/png','synthetic-image'),('Synthetic comparison.pdf','application/pdf','synthetic-pdf')]:
            case=self.cases[6]
            update=CaseUpdate.objects.create(parsed_message=case,group_id=case.group_id,old_status='Open',new_status='Open',source='mini_app',updated_by='Synthetic evidence officer')
            ComplaintCaseEvidence.objects.create(parsed_message=case,case_update=update,group_id=case.group_id,original_filename=name,mime_type=mime,upload_status='success',drive_file_id=key,size=len(files[key]),uploaded_by='Synthetic evidence officer')
        root=Path(settings.BASE_DIR)
        with self.settings(GOOGLE_DRIVE_MEDIA_FOLDER_ID='synthetic-private-folder'),patch('core.services.order_approval.GoogleDriveMediaStorage.download',side_effect=lambda key:files[key]):
            for index,phase in enumerate(('before','after')):
                result=subprocess.run([os.environ['STAFF_BROWSER_TEST_NODE'],str(root/'test-results/spec18_compare.js')],
                    input=json.dumps({'origin':self.live_server_url,'username':self.user.username,'password':PASSWORD,
                        'code':self.codes[index],'group':str(self.group.pk),'phase':phase}),
                    cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=180)
                self.assertEqual(result.returncode,0,result.stderr[-4000:])
                print('Source-bound visual comparison',phase,result.stdout)
