"""
Run this on the production Render shell to diagnose the TAT tracker config.
  python diagnose_tat_prod.py

It is READ-ONLY — no changes are made.
"""
import os, django, json
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.models import GroupSheetConfiguration

print("=" * 60)
print("GroupSheetConfiguration records:")
print("=" * 60)
for c in GroupSheetConfiguration.objects.all():
    wf = c.workflow or {}
    print(f"\n  pk={c.pk}  group_id={c.group_id}  type={wf.get('type', '<none>')}")
    print(f"  sheet_name: {c.sheet_name}")
    # Show products list
    if 'products' in wf:
        print(f"  workflow.products: {wf['products']}")
    # Show staff and their products
    staff = wf.get('staff') or []
    if staff:
        print(f"  staff ({len(staff)} entries):")
        for s in staff:
            print(f"    - {s.get('name') or s.get('telegram_username')} | products={s.get('products')} | sheets={s.get('sheets')} | active={s.get('active', True)}")
    else:
        print("  staff: (none in workflow JSON — checking TatTrackerStaff table...)")
        from core.models import TatTrackerStaff
        ts = TatTrackerStaff.objects.filter(group_config=c)
        if ts.exists():
            print(f"  TatTrackerStaff ({ts.count()} rows):")
            for t in ts:
                print(f"    - {t.name} | products={t.products} | active={t.active}")
        else:
            print("  TatTrackerStaff: (none)")

print("\n" + "=" * 60)
print("GroupRegistry view:")
print("=" * 60)
from core.services.group_config import GroupRegistry
r = GroupRegistry.get_instance()
for gid, gc in r.list_groups().items():
    print(f"\n  group_id={gid}  workflow_type={(gc.workflow or {}).get('type','<none>')}")
    wf = gc.workflow or {}
    if 'products' in wf:
        print(f"  workflow.products: {wf['products']}")
    staff = wf.get('staff') or []
    if staff:
        print(f"  staff ({len(staff)} entries):")
        for s in staff:
            print(f"    - {s.get('name')} | products={s.get('products')}")
