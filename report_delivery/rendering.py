"""Local PDF and XLSX generation from one captured, JSON-safe dataset."""
import base64
import json
from datetime import datetime, timedelta
from html import escape
from xml.etree import ElementTree

from django.conf import settings
from django.utils import timezone
from django.template.loader import render_to_string
from decimal import Decimal, InvalidOperation
from pathlib import Path

from core.services.portal_reporting import curated_snapshot_xlsx

MAX_PAYLOAD_BYTES = 10 * 1024 * 1024
BRAND_LOGO_ID = 'jawabu-report-logo'
BRAND_LOGO_PATH = Path(__file__).resolve().parent.parent / 'core/static/miniapp/jawabu-logo.png'


def _email_metric(label, value):
    """Presentation only: preserve the captured report and workbook values."""
    display = '—'
    short_label = label
    if value is not None:
        try:
            number = Decimal(str(value))
            if not number.is_finite():
                raise InvalidOperation
            if label.endswith((' (hours)', ' (minutes)')) and number >= 0:
                short_label = label.rsplit(' (', 1)[0]
                minutes = int((number * (60 if label.endswith(' (hours)') else 1)).quantize(Decimal('1')))
                days, remainder = divmod(minutes, 1440)
                hours, minutes = divmod(remainder, 60)
                parts = []
                if days:
                    parts.append(f'{days} day{"s" if days != 1 else ""}')
                if hours:
                    parts.append(f'{hours} hr')
                if minutes:
                    parts.append(f'{minutes} min')
                display = ' '.join(parts) or '0 min'
            else:
                display = f'{number:,.0f}' if number == number.to_integral_value() else f'{number:,.2f}'
                if label.endswith(' (%)'):
                    short_label = label[:-4]
                    display += '%'
        except (InvalidOperation, ValueError):
            display = str(value) if str(value).lower() not in {'nan', 'infinity', '-infinity'} else '—'
    # Missing durations still use the concise label, without implying a zero.
    if label.endswith((' (hours)', ' (minutes)', ' (%)')):
        short_label = label.rsplit(' (', 1)[0]
    tone = 'navy'
    if label in {'Open', 'Stalled cases', 'Declined', 'Over target'}:
        tone = 'pink'
    elif label in {'Resolved', 'Disbursed', 'Resolved on time (%)', 'Within or near target (%)'}:
        tone = 'green'
    elif label in {'Needs details', 'No target available'}:
        tone = 'muted'
    ink, background, accent = {
        'navy': ('#2e3480', '#f1f2f9', '#2e3480'),
        'pink': ('#a31d64', '#fcf1f7', '#c8247a'),
        'green': ('#2f6b17', '#eef8e9', '#6cbe45'),
        'muted': ('#4a5578', '#f6f7fa', '#8a90ab'),
    }[tone]
    return {'label': short_label, 'value': display, 'ink': ink, 'background': background, 'accent': accent,
            'long_value': len(display) > 8}


class ReportTooLarge(ValueError):
    """Narrow report scope before attempting provider delivery."""


def _safe_fetch(url, *args, **kwargs):
    # Reports have no external assets or arbitrary file access.
    raise ValueError('External PDF assets are not permitted.')


def report_basis(preset):
    return {
        'pipeline': 'Current backlog at generation time.',
        'finance': 'Period activity; financial amounts are current recorded values, not historical cash flow.',
        'outcomes': 'Actions recorded during the selected period.',
        'tat': 'Completed-period TAT outcomes; current authorized operational data only.',
        'complaints': 'Complaints reported in this period; resolution status is current at generation.',
    }[preset]


def chart_svg(chart):
    from reportlab.graphics import renderSVG
    from reportlab.graphics.shapes import Drawing, Line, Rect, String
    from reportlab.lib.colors import HexColor
    labels, datasets = chart.get('labels', []), chart.get('datasets', [])
    width, height = 700, 230
    drawing = Drawing(width, height)
    palette = ['#2481cc', '#17875d', '#b57609', '#8753b5', '#bc4148']
    series = [[float(value or 0) for value in dataset.get('values', [])] for dataset in datasets]
    values_all = [value for values in series for value in values]
    maximum = max(values_all + [0])
    minimum = min(values_all + [0])
    span = max(1, maximum - minimum)
    zero = 40 - minimum / span * 140
    count = max(1, len(labels))
    step = 620 / count
    for s, values in enumerate(series):
        color = HexColor(palette[s % len(palette)])
        drawing.add(Rect(40 + (s % 3) * 220, height - 14 - (s // 3) * 15, 7, 7, fillColor=color, strokeColor=None))
        drawing.add(String(52 + (s % 3) * 220, height - 14 - (s // 3) * 15, str(datasets[s].get('label', ''))[:35], fontSize=8))
        points = []
        for i, value in enumerate(values):
            x = 40 + i * step
            y = 40 + (value - minimum) / span * 140
            if chart.get('type') == 'line':
                points.append((x + step / 2, y))
            else:
                bar = step * .8 / max(1, len(series))
                drawing.add(Rect(x + s * bar, min(zero, y), max(1, bar - 1), abs(y - zero), fillColor=color, strokeColor=None))
        for first, second in zip(points, points[1:]):
            drawing.add(Line(*first, *second, strokeColor=color, strokeWidth=2))
    drawing.add(Line(40, zero, 660, zero, strokeColor=HexColor('#d1d5db')))
    # Charts retain every bucket; thin tick labels, not underlying data.
    every = max(1, (len(labels) + 7) // 8)
    for i in range(0, len(labels), every):
        drawing.add(String(40 + i * step, 20, str(labels[i])[:22], fontSize=7))
    drawing.add(String(2, 178, f'{maximum:,.0f}', fontSize=8))
    root = ElementTree.fromstring(renderSVG.drawToString(drawing))
    # Presentation attributes are portable to WeasyPrint's SVG renderer; the
    # ReportLab inline CSS otherwise passes through the HTML CSS parser.
    for node in root.iter():
        for entry in node.attrib.pop('style', '').split(';'):
            if ':' in entry:
                key, value = entry.split(':', 1)
                node.set(key.strip(), value.strip())
    ElementTree.register_namespace('', 'http://www.w3.org/2000/svg')
    return ElementTree.tostring(root, encoding='unicode')


def report_html(snapshot, configuration=None, *, graphs=False):
    period = (configuration or {}).get('period') or snapshot.get('period')
    period_text = f'{period["from"]} to {period["to"]}' if period else 'Current snapshot'
    generated = datetime.fromisoformat(snapshot['run_at'])
    generated_text = timezone.localtime(generated).strftime('%d %b %Y, %H:%M') + ' EAT'
    basis = report_basis(snapshot['preset'])
    due = (configuration or {}).get('due_at')
    delayed = bool(due and generated > datetime.fromisoformat(due) + timedelta(minutes=15))
    items = ''.join(f'<tr><td>{escape(str(key))}</td><td class="value">{escape(str(value))}</td></tr>' for key, value in snapshot['summary'].items())
    charts = ''
    if graphs:
        charts = ''.join('<section class="chart"><h2>' + escape(chart['title']) + '</h2>' + chart_svg(chart) + '<p>' + escape(str(chart.get('context', ''))) + '</p></section>' for chart in snapshot['charts'])
    filters = ', '.join(f'{key.title()}: {value}' for key, value in snapshot['applied_filters'].items() if key in {'branch', 'product', 'county'}) or 'All approved cases in this group'
    return f'''<!doctype html><html><head><meta charset="utf-8"><style>
        @page {{ size:A4; margin:16mm; }} body{{font-family:sans-serif;color:#243244;font-size:11pt}}
        h1{{font-size:20pt}} h2{{font-size:14pt}} table{{width:100%;border-collapse:collapse}}
        td{{padding:7px;border-bottom:1px solid #e3e6eb}} .value{{text-align:right;font-weight:bold}}
        .chart{{break-inside:avoid;margin-top:20px}} svg{{width:100%;height:auto}} p{{line-height:1.4}}
        </style></head><body><h1>{escape(snapshot['preset'].title())} report</h1>
        <p>{escape(period_text)} · Generated {escape(generated_text)}</p>
        {'<p>Delayed delivery: this report was generated after its scheduled time.</p>' if delayed else ''}
        <p>{escape(filters)}</p><p>{escape(basis)}</p><table>{items}</table>
        <p>{snapshot['total_rows']} matching cases; Excel contains {len(snapshot['rows'])} rows.
        Export limit: {snapshot['export_limit']} rows. Summary and charts cover all matching cases.</p>
        {charts}<p>Confidential: for approved recipients only.</p></body></html>'''


def report_pdf(snapshot, configuration=None):
    from weasyprint import HTML
    return HTML(string=report_html(snapshot, configuration, graphs=True), url_fetcher=_safe_fetch).write_pdf()


def build_payload(snapshot, email, configuration):
    context = email_context(snapshot, configuration)
    from .email_charts import chart_png
    chart_attachments = []
    context['email_graphs'] = []
    for index, chart in enumerate(c for c in snapshot.get('charts', []) if c.get('labels') and c.get('datasets')):
        if index >= 3:
            break
        try:
            content = chart_png(chart)
        except (OSError, ValueError, RuntimeError):
            # A presentation failure must not block the canonical Excel report.
            content = None
        if content is None:
            continue
        content_id = f'jawabu-report-chart-{index + 1}'
        chart_attachments.append({'filename': f'report-chart-{index + 1}.png', 'content_type': 'image/png',
                                  'content_id': content_id, 'content': base64.b64encode(content).decode()})
        context['email_graphs'].append({'title': chart['title'], 'src': 'cid:' + content_id,
                                        'alt': chart['title'] + '. Values are listed in the breakdown below.'})
    try:
        logo = {'filename': 'jawabu-logo.png', 'content_type': 'image/png',
                'content_id': BRAND_LOGO_ID, 'content': base64.b64encode(BRAND_LOGO_PATH.read_bytes()).decode()}
    except OSError:
        # A packaging mistake must not prevent delivery of the report itself.
        logo = None
        context['logo_src'] = ''
    stem = f'{snapshot["preset"]}-report-{snapshot["run_at"][:10]}'
    sender = settings.REPORT_EMAIL_FROM
    if sender and '<' not in sender:
        sender = f'JBL BOT <{sender}>'
    payload = {
        'from': sender, 'to': [email],
        'subject': f'JBL · {context["title"]} · {context["period"]}',
        'html': render_to_string('report_delivery/email.html', context),
        'text': render_to_string('report_delivery/email.txt', context),
        'attachments': [
            {'filename': stem + '.xlsx', 'content': snapshot.get('xlsx_content') or base64.b64encode(curated_snapshot_xlsx(snapshot)).decode()},
        ] + ([logo] if logo else []) + chart_attachments,
    }
    if settings.REPORT_EMAIL_REPLY_TO:
        payload['reply_to'] = settings.REPORT_EMAIL_REPLY_TO
    if len(json.dumps(payload).encode()) > MAX_PAYLOAD_BYTES:
        raise ReportTooLarge('Report attachments exceed the safe email size limit. Narrow the schedule scope.')
    return payload


def email_context(snapshot, configuration=None):
    def date_label(value):
        return datetime.fromisoformat(str(value)[:10]).strftime('%d-%b-%Y')

    filters = snapshot.get('applied_filters', {})
    period = snapshot.get('period') or (configuration or {}).get('period')
    start = period.get('from') if period else filters.get('date_from') or filters.get('from')
    end = period.get('to') if period else filters.get('date_to') or filters.get('to')
    period_text = (f'{date_label(start)} – {date_label(end)}' if start and end else
                   f'From {date_label(start)}' if start else f'Through {date_label(end)}' if end else 'Current snapshot')
    generated = timezone.localtime(datetime.fromisoformat(snapshot['run_at'])).strftime('%d-%b-%Y · %H:%M EAT')
    titles = {'pipeline': 'Pipeline overview', 'finance': 'Finance overview', 'outcomes': 'Case outcomes',
              'tat': 'TAT overview', 'complaints': 'Complaints overview'}
    metrics = [_email_metric(label, value) for label, value in snapshot['summary'].items()]
    excluded = {'date_mode', 'month', 'quarter', 'year', 'from', 'to', 'date_from', 'date_to', 'granularity', 'sort', 'group'}
    scope = [{'label': key.replace('_', ' ').capitalize(), 'value': str(value).replace('_', ' ') if key in {'stage', 'view', 'sla_state', 'date_basis'} else str(value)}
             for key, value in filters.items() if value not in (None, '') and key not in excluded]
    breakdowns = []
    for chart in snapshot.get('charts', []):
        labels = chart.get('labels', [])
        datasets = chart.get('datasets', [])
        if not labels or not datasets:
            continue
        headers = [d.get('label', '') for d in datasets]
        rows = []
        for i, label in enumerate(labels):
            values = [_email_metric('', d.get('values', [])[i] if i < len(d.get('values', [])) else None)['value']
                      for d in datasets]
            rows.append({'label': label, 'values': values,
                         'cells': [{'label': header, 'value': value} for header, value in zip(headers, values)]})
        breakdowns.append({'title': chart['title'], 'headers': headers, 'rows': rows})
    # Small breakdowns share a row; multi-series financial tables need full width.
    breakdown_groups, pending = [], []
    for chart in breakdowns:
        if len(chart['headers']) > 2:
            if pending:
                breakdown_groups.append(pending)
                pending = []
            breakdown_groups.append([chart])
        else:
            pending.append(chart)
            if len(pending) == 2:
                breakdown_groups.append(pending)
                pending = []
    if pending:
        breakdown_groups.append(pending)
    exported = snapshot.get('exported_rows', len(snapshot.get('rows', [])))
    basis = report_basis(snapshot['preset'])
    if snapshot['preset'] == 'tat' and filters.get('view', 'current') == 'current':
        basis = 'Current workload at generation time, narrowed by your selected filters.'
    if snapshot['preset'] == 'complaints' and filters.get('date_basis') not in (None, '', 'reported'):
        basis = 'Complaints matching the selected activity dates; status is current at generation.'
    roomy_headline = any(item['long_value'] for item in metrics[:4])
    headline_columns = min(2 if roomy_headline else 4, len(metrics)) or 1
    return {'title': titles.get(snapshot['preset'], 'Report overview'), 'period': period_text, 'generated': generated,
            'basis': basis, 'metrics': metrics, 'headline': metrics[:4],
            'remaining': metrics[4:], 'filters': scope, 'breakdowns': breakdowns,
            'headline_width': 100 // headline_columns, 'roomy_headline': roomy_headline,
            'headline_rows': [metrics[i:i + headline_columns] for i in range(0, min(4, len(metrics)), headline_columns)],
            'remaining_rows': [metrics[i:i + 3] for i in range(4, len(metrics), 3)],
            'breakdown_groups': breakdown_groups, 'logo_src': 'cid:' + BRAND_LOGO_ID,
            'total': snapshot['total_rows'], 'exported': exported, 'truncated': exported < snapshot['total_rows']}
