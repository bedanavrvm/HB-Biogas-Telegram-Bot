"""Render original app shells with synthetic I/O, never operational view calls."""
import base64
import json
import re

from django.contrib.staticfiles import finders
from django.template import Context, Engine
from django.template.loader import render_to_string

from .catalog import APPS, ROOT


def isolate_navigation(html):
    """Adapt navigation I/O only; preserve script attributes/order and UI code.

    An opaque iframe prevents access to the host, but does not prevent a script
    from navigating its own frame. Keep those original app redirects in the
    synthetic adapter instead. Data script URLs retain defer/async semantics.
    """
    def adapt(match):
        name = match['url'].split('?', 1)[0].removeprefix('/static/')
        if name.rsplit('/', 1)[-1].startswith('vendor-'):
            return match[0]
        found = finders.find(name)
        if not found:
            return match[0]
        from pathlib import Path
        source = Path(found).read_text(encoding='utf-8')
        adapted = re.sub(r'\bwindow\.location\.(assign|replace|reload)\b',
                         r'window.UI_SCENE.navigation.\1', source)
        adapted = re.sub(r'\bwindow\.location\.href(?=\s*=(?!=))',
                         'window.UI_SCENE.navigation.href', adapted)
        if adapted == source:
            return match[0]
        encoded = base64.b64encode(adapted.encode()).decode()
        return match[0].replace(match['url'], 'data:text/javascript;base64,' + encoded, 1)
    return re.sub(r'<script\b[^>]*\bsrc=[\'"](?P<url>/static/[^\'"]+\.js(?:\?[^\'"]*)?)[\'"][^>]*>\s*</script>', adapt, html)


def scene_html(app: str, scene: str, state: str, role: str) -> str:
    context = {'group_id': '-100-ui-synthetic', 'active_screen': 'jbl', 'credit_assessment_enabled': False,
               'invoice_upload_max_file_size_mb': 8, 'farmup_max_file_size_mb': 5}
    if app == 'portal':
        context['active_screen'] = {'reports': 'reports', 'settings': 'settings', 'recognition': 'performance',
                                    'detail': 'all', 'preview': 'documents'}.get(scene, 'jbl')
        body = render_to_string('portal/portal.html', context)
        source = (ROOT / APPS[app]['template']).read_text(encoding='utf-8')
        source = re.sub(r'{% block content %}.*?{% endblock %}', body, source, flags=re.S)
        html = Engine.get_default().from_string(source).render(Context(context))
    else:
        name = {'tat': 'tat_tracker/app.html', 'complaints': 'complaint_cases/app.html',
                'origination': 'loan_origination/app.html'}[app]
        html = render_to_string(name, context)
    # Remote Telegram is replaced by the stub, not initialized with host initData.
    html = re.sub(r'<script[^>]+src=[\'"]https?://[^>]+>\s*</script>', '', html)
    html = isolate_navigation(html)
    config = json.dumps({'app': app, 'scene': scene, 'state': state, 'role': role}).replace('<', '\\u003c')
    if app == 'portal':
        count = 0 if state == 'empty' else 20 if state == 'many' else 1
        farmers = [{'id': f'00000000-0000-0000-0000-{index+1:012d}', 'display_number': index+1,
                    'customer_name': 'Synthetic Wanjiku Mwangi-Kamau With A Deliberately Long Applicant Name' if state == 'long' else 'Synthetic Wanjiku Mwangi',
                    'national_id': '00000000', 'primary_phone': '0700000000', 'branch': 'Training branch',
                    'location_label': 'Training village / landmark', 'unit_number': 'TRAIN-01', 'hbg_visit_date_label': '16-10-26'} for index in range(count)]
        fixture = {'farmers': farmers, 'queue_key': 'jbl', 'mode': 'jbl_visit', 'calculated_at': '2026-10-16T09:00:00+03:00',
                   'pagination': {'page': 1, 'pages': 3 if count > 1 else 1, 'total': count, 'page_links': [1, 2, 3]},
                   'empty_title': 'JBL visit queue is clear', 'empty_sub': 'No farmer is waiting for a JBL visit.'}
        values = json.loads(config)
        values['portal_fragment'] = render_to_string('portal/partials/farmer_list.html', fixture)
        values['portal_navigation'] = render_to_string('portal/partials/navigation.html', {'nav_groups': [
            {'label': 'Pipeline', 'items': [{'key': 'jbl', 'url': '/portal/s/jbl/', 'label': 'Visit Queue', 'icon': 'house'}]}]})
        config = json.dumps(values).replace('<', '\\u003c')
    bootstrap = ('<base href="/">'
                 f'<script id="ui-scene-config" type="application/json">{config}</script>'
                 '<script src="/static/ui_review/scene_fixture.js?v=1"></script>')
    html = html.replace('<head>', '<head>' + bootstrap, 1)
    return html.replace('</body>', '<script src="/static/ui_review/scene_driver.js?v=1"></script></body>')
