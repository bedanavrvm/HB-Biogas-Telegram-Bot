import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from core.models import GroupSheetConfiguration
import json

print('All GroupSheetConfiguration records:')
for c in GroupSheetConfiguration.objects.all():
    wf = c.workflow or {}
    print(f'  pk={c.pk} group_id={c.group_id} type={wf.get("type", "<none>")}')
    print(f'  workflow: {json.dumps(wf, indent=4, default=str)[:500]}')
    print()
