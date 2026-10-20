"""Process-memory Complaint journeys. Never import Django or deployment settings."""
from __future__ import annotations

import ast
import base64
import binascii
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from threading import RLock
from uuid import NAMESPACE_URL, uuid4, uuid5
import struct
import zlib

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {
    'officer': ('OFFICER', 'Complaint Officer', 'Demo Officer', ('1', '2')),
    'manager': ('MANAGER', 'Complaint Manager', 'Demo Manager', ('1', '2')),
    'hb': ('HB_STAFF', 'HB Resolver', 'Demo HB Resolver', ('1',)),
    'it': ('IT', 'IT Support', 'Demo IT', ('1', '2')),
    'portal': ('PORTAL_ONLY', 'Portal HB — no Complaints access', 'Demo Portal HB', ()),
}
ACTIONS = {'comment': ('complaint.case.comment', 'Add resolution comment'),
           'resolve': ('complaint.case.close', 'Resolve complaint'),
           'reopen': ('complaint.case.reopen', 'Reopen complaint'),
           'complete': ('complaint.case.details.complete', 'Complete missing details'),
           'upload': ('complaint.case.evidence.manage', 'Upload evidence')}
LOCATIONS = [
    {'branch': 'Nakuru', 'county': 'Nakuru', 'constituency': 'Nakuru East'},
    {'branch': 'Eldoret', 'county': 'Uasin Gishu', 'constituency': 'Ainabkoi'},
    {'branch': 'Kericho', 'county': 'Kericho', 'constituency': 'Ainamoi'},
]
CATEGORIES = ['Gas production', 'Gas leakage', 'Maintenance', 'Installation follow-up']
MAX_FILE = 10 * 1024 * 1024
MAX_TOTAL = 30 * 1024 * 1024


def builtin_capabilities():
    roles = {role: set() for role, *_ in PROFILES.values()}
    tree = ast.parse((ROOT / 'core/services/workflow_capabilities.py').read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != 'CapabilityDefinition' or len(node.args) < 5:
            continue
        if not isinstance(node.args[1], ast.Constant) or node.args[1].value != 'complaint_cases':
            continue
        key = ast.literal_eval(node.args[0])
        for value in node.args[4].args:
            role = ast.literal_eval(value)
            if role in roles:
                roles[role].add(key)
        roles['IT'].add(key)  # Existing mandatory, scoped workflow IT override.
    return roles


def seed():
    scenarios = [
        ('Sample Farmer — Njoro', 'Nakuru', 'Gas production', 'Digester gas output has fallen over the last week. Farmer requests a service visit.', 'Pending'),
        ('Sample Farmer — Kapsoya', 'Eldoret', 'Gas leakage', 'Gas smell near the inlet connector. Inspection and a repair update are required.', 'Pending'),
        ('Sample Farmer — Lanet', 'Nakuru', 'Maintenance', 'Forwarded historical report has no confirmed customer identifiers.', 'Needs details'),
        ('Sample Farmer — Bahati', 'Nakuru', 'Installation follow-up', 'Installation is complete but the farmer needs operating guidance.', 'Pending'),
        ('Sample Farmer — Kesses', 'Eldoret', 'Gas production', 'Flame is weak despite normal daily feeding. Follow up on the service booking.', 'Pending'),
        ('Sample Farmer — Molo', 'Nakuru', 'Maintenance', 'Outlet valve is stiff. The field team has requested replacement parts.', 'Pending'),
        ('Sample Farmer — Pipeline', 'Nakuru', 'Maintenance', 'A joint inspection with the farmer is scheduled for the next field visit.', 'Pending'),
        ('Sample Farmer — Rongai', 'Nakuru', 'Gas leakage', 'Connector seal replaced and leak test passed with the farmer present.', 'Resolved'),
        ('Sample Farmer — Pioneer', 'Eldoret', 'Gas production', 'Feeding routine adjusted; farmer confirmed normal gas output.', 'Resolved'),
    ]
    cases = []
    for number, (name, branch, category, description, status) in enumerate(scenarios, 1):
        location = next(item for item in LOCATIONS if item['branch'] == branch)
        cases.append({'key': str(uuid5(NAMESPACE_URL, f'jbl-complaints-role-demo-v2:{number}')),
                      'reference': f'CMP-{number}', 'group': '1', 'customer_name': name,
                      'customer_phone': '' if status == 'Needs details' else f'070000{number:04d}',
                      'customer_id': '' if status == 'Needs details' else f'9000{number:04d}',
                      **location, 'village': 'Sample service area', 'category': category,
                      'description': description, 'status': status, 'revision': 1,
                      'reported_at': f'{number + 10:02d} Oct 2026 09:00', 'evidence': [],
                      'source': 'Synthetic forwarded complaint; original sender and source are confidential.',
                      'history': [{'action': 'resolved' if status == 'Resolved' else 'created',
                                   'status': status, 'created_at': f'{number + 10:02d} Oct 2026 10:00',
                                   'updated_by': 'Demo HB Resolver' if status == 'Resolved' else 'Demo Officer',
                                   'actor_affiliation': 'HB' if status == 'Resolved' else 'JBL',
                                   'note': 'Repair confirmed with the farmer.' if status == 'Resolved' else 'Complaint recorded from synthetic intake.'}],
                      'history_truncated': False})
    partner = deepcopy(cases[0])
    partner.update(key=str(uuid5(NAMESPACE_URL, 'jbl-complaints-role-demo-v2:10')), reference='CMP-10',
                   group='2', customer_name='Sample Farmer — Ainamoi', **LOCATIONS[2])
    cases.append(partner)
    return {'groups': [{'key': '1', 'label': 'HomeBiogas service'}, {'key': '2', 'label': 'Partner service'}], 'cases': cases}


class DemoFailure(Exception):
    def __init__(self, status, message, fields=None):
        self.status, self.message, self.fields = status, message, fields or {}


def stamp():
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=3))).strftime('%d %b %Y %H:%M')


def sample_image():
    # A first-party inspection illustration, not a customer photo or UI palette.
    width, height = 240, 140
    pixels = bytearray()
    for y in range(height):
        pixels.append(0)
        for x in range(width):
            tank = ((x - 120) / 70) ** 2 + ((y - 75) / 48) ** 2 <= 1
            pixels.extend((45, 125, 85) if tank else (235, 241, 235))

    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data) & 0xffffffff)
    raw = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!IIBBBBB', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b'')
    return {'name': 'sample-inspection.png', 'content': base64.b64encode(raw).decode(), 'type': 'image/png'}


class Sandbox:
    def __init__(self, data):
        self.seed = deepcopy(data)
        self.capabilities = builtin_capabilities()
        self.lock = RLock()
        self.epoch, self.receipts = 1, {}
        self.cases, self.files = deepcopy(data['cases']), {}

    def profile(self, persona):
        if persona not in PROFILES:
            raise DemoFailure(403, 'Choose an available demo role.')
        return PROFILES[persona]

    def can(self, persona, capability):
        return capability in self.capabilities[self.profile(persona)[0]]

    def group(self, persona, key):
        if key not in self.profile(persona)[3] or not self.can(persona, 'complaint.queue.view'):
            raise DemoFailure(403, 'This demo role has no Complaints access in this workspace.')

    def find(self, persona, group, key):
        self.group(persona, group)
        case = next((item for item in self.cases if item['key'] == key and item['group'] == group), None)
        if case is None:
            raise DemoFailure(404, 'This complaint is not available in this workspace.')
        return case

    def actions(self, persona, case):
        allowed = []
        for key, (capability, label) in ACTIONS.items():
            if not self.can(persona, capability):
                continue
            if key in {'comment', 'resolve'} and case['status'] == 'Resolved':
                continue
            if key == 'reopen' and case['status'] != 'Resolved':
                continue
            if key == 'complete' and case['status'] != 'Needs details':
                continue
            allowed.append({'value': key, 'label': label})
        return allowed

    def detail(self, persona, case):
        result = deepcopy(case)
        result.update(epoch=self.epoch, actions=self.actions(persona, case))
        if not self.can(persona, 'complaint.case.source.view'):
            result.pop('source', None)
        return result

    def context(self, persona):
        role, label, actor, groups = self.profile(persona)
        return {'epoch': self.epoch, 'role': role, 'label': label, 'actor': actor,
                'personas': [{'value': key, 'label': value[1]} for key, value in PROFILES.items()],
                'can_create': self.can(persona, 'complaint.case.create'),
                'groups': [item for item in self.seed['groups'] if item['key'] in groups],
                'locations': LOCATIONS, 'categories': CATEGORIES}

    def read(self, persona, route, params):
        with self.lock:
            self.profile(persona)
            if route == 'context/' and not params:
                return self.context(persona)
            if route == 'sample-evidence/' and not params:
                if not self.can(persona, 'complaint.case.evidence.manage'):
                    raise DemoFailure(403, 'This role cannot upload evidence.')
                return sample_image()
            if route == 'groups/' and not params:
                return {'groups': self.context(persona)['groups']}
            match = re.fullmatch(r'groups/(\d+)/cases/(?:([a-f0-9-]{36})/)?', route)
            if not match:
                raise DemoFailure(404, 'Demo page not found.')
            group, key = match.groups()
            self.group(persona, group)
            if key and not params:
                return {'case': self.detail(persona, self.find(persona, group, key))}
            if key or set(params) - {'q', 'status', 'page'} or any(len(value) != 1 for value in params.values()):
                raise DemoFailure(400, 'Refresh the queue and try again.')
            query, status, page = (params.get(key, [default])[0] for key, default in (('q', ''), ('status', 'pending'), ('page', '1')))
            if len(query) > 150 or status not in {'pending', 'resolved', 'all'} or not page.isascii() or not page.isdigit() or len(page) > 6 or int(page) < 1:
                raise DemoFailure(400, 'Choose a valid search, status and page.')
            cases = [case for case in self.cases if case['group'] == group and
                     (status == 'all' or (case['status'] == 'Resolved') == (status == 'resolved')) and
                     (not query.strip() or any(query.strip().casefold() in case[key].casefold() for key in ('reference', 'customer_name')))]
            if status != 'pending':
                cases.reverse()
            pages = max(1, (len(cases) + 3) // 4)
            current = min(int(page), pages)
            fields = ('key', 'reference', 'customer_name', 'branch', 'category', 'status', 'reported_at')
            return {'items': [{key: case[key] for key in fields} for case in cases[(current - 1) * 4:current * 4]],
                    'pagination': {'page': current, 'pages': pages, 'total': len(cases), 'page_size': 4}}

    def attachment(self, persona, key):
        with self.lock:
            if key not in self.files:
                raise DemoFailure(404, 'Evidence is not available. Reset may have cleared it.')
            item = self.files[key]
            self.find(persona, item['group'], item['case'])
            if not self.can(persona, 'complaint.case.evidence.view'):
                raise DemoFailure(403, 'This role cannot view complaint evidence.')
            return item['bytes'], item['type']

    def validate_files(self, items):
        if not isinstance(items, list) or len(items) > 10:
            raise DemoFailure(400, 'Choose at most ten evidence files.')
        results, total = [], 0
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get('name'), str) or not isinstance(item.get('content'), str):
                raise DemoFailure(400, 'Choose a valid evidence file.')
            name = item['name'].replace('\\', '/').split('/')[-1][:150]
            try:
                raw = base64.b64decode(item['content'], validate=True)
            except (ValueError, binascii.Error):
                raise DemoFailure(400, 'The evidence file could not be read.') from None
            total += len(raw)
            if not raw or len(raw) > MAX_FILE or total > MAX_TOTAL:
                raise DemoFailure(400, 'Use files up to 10 MB each and 30 MB per update.')
            suffix, mime = Path(name).suffix.lower(), ''
            if suffix in {'.jpg', '.jpeg'} and raw.startswith(b'\xff\xd8\xff'):
                mime = 'image/jpeg'
            elif suffix == '.png' and raw.startswith(b'\x89PNG\r\n\x1a\n'):
                mime = 'image/png'
            elif suffix == '.webp' and raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
                mime = 'image/webp'
            elif suffix == '.pdf' and raw.startswith(b'%PDF-'):
                mime = 'application/pdf'
            if not mime:
                raise DemoFailure(400, 'Evidence must be a genuine JPEG, PNG, WebP or PDF.')
            results.append({'name': name, 'type': mime, 'bytes': raw, 'sha256': hashlib.sha256(raw).hexdigest()})
        if sum(len(item['bytes']) for item in self.files.values()) + total > 60 * 1024 * 1024:
            raise DemoFailure(400, 'Demo storage is full. Reset the demo to clear its local uploads.')
        return results

    def attach(self, case, items, actor):
        for item in items:
            if any(evidence['sha256'] == item['sha256'] for evidence in case['evidence']):
                continue
            key = str(uuid4())
            self.files[key] = {**item, 'case': case['key'], 'group': case['group']}
            case['evidence'].append({'key': key, 'name': item['name'], 'type': item['type'],
                                     'size': len(item['bytes']), 'sha256': item['sha256'],
                                     'uploaded_by': actor, 'created_at': stamp()})

    @staticmethod
    def text(fields, key, label, limit=5000):
        value = fields.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise DemoFailure(400, f'Enter {label.lower()}.', {key: f'Enter {label.lower()}.'})
        return value.strip()

    def identifiers(self, fields, case=None):
        phone = self.text(fields, 'customer_phone', 'a primary phone number', 30)
        phone = re.sub(r'[\s()-]', '', phone)
        identifier = self.text(fields, 'customer_id', 'a Customer National ID', 30)
        if not re.fullmatch(r'(?:0|\+?254)[17]\d{8}', phone):
            raise DemoFailure(400, 'Enter a valid Kenyan primary phone number.', {'customer_phone': 'Use a Kenyan phone number.'})
        if not identifier.isascii() or not identifier.isdigit():
            raise DemoFailure(400, 'Customer National ID must contain digits only.', {'customer_id': 'Use digits only.'})
        if case and any(case.get(key) and case[key] != value for key, value in [('customer_phone', phone), ('customer_id', identifier)]):
            raise DemoFailure(400, 'Existing identifiers cannot be replaced through missing-details completion.')
        return phone, identifier

    def mutate(self, persona, route, payload):
        with self.lock:
            _, _, actor, _ = self.profile(persona)
            if not isinstance(payload, dict) or len(self.receipts) >= 500:
                raise DemoFailure(400, 'Restart the demo before continuing.')
            request = payload.get('request_key')
            if not isinstance(request, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{8,80}', request):
                raise DemoFailure(400, 'Refresh this action before saving.')
            digest = hashlib.sha256(json.dumps([persona, route, payload], sort_keys=True).encode()).hexdigest()
            if request in self.receipts:
                old_digest, result = self.receipts[request]
                if old_digest != digest:
                    raise DemoFailure(409, 'This retry belongs to a different action. Refresh and review the case.')
                if route != 'reset/' and payload.get('epoch') != self.epoch:
                    raise DemoFailure(409, 'The demo was reset. Refresh before saving.')
                return deepcopy(result)
            if type(payload.get('epoch')) is not int or payload['epoch'] != self.epoch:
                raise DemoFailure(409, 'The demo was reset. Refresh before saving.')
            if route == 'reset/':
                self.epoch += 1
                self.cases, self.files = deepcopy(self.seed['cases']), {}
                result = {'epoch': self.epoch, 'message': 'Demo reset. Sample cases restored and uploads cleared.'}
            else:
                match = re.fullmatch(r'groups/(\d+)/cases/(?:([a-f0-9-]{36})/(\w+)/)?', route)
                if not match:
                    raise DemoFailure(404, 'Demo action not found.')
                group, key, action = match.groups()
                self.group(persona, group)
                fields = payload.get('fields', {})
                if not isinstance(fields, dict):
                    raise DemoFailure(400, 'Review the entered details.')
                if key is None:
                    if not self.can(persona, 'complaint.case.create'):
                        raise DemoFailure(403, 'This role cannot create complaints.')
                    name = self.text(fields, 'customer_name', 'a customer name', 150)
                    phone, identifier = self.identifiers(fields)
                    branch = self.text(fields, 'branch', 'a branch', 150)
                    location = next((item for item in LOCATIONS if item['branch'] == branch), None)
                    category = self.text(fields, 'category', 'a complaint category', 150)
                    if location is None or category not in CATEGORIES or (group == '2' and branch != 'Kericho') or (group == '1' and branch == 'Kericho'):
                        raise DemoFailure(400, 'Choose a branch and category available in this workspace.')
                    description = self.text(fields, 'description', 'a complaint description')
                    village = self.text(fields, 'village', 'a village or nearby landmark', 150)
                    files = self.validate_files(payload.get('files', []))
                    number = max(int(item['reference'].split('-')[1]) for item in self.cases) + 1
                    case = {'key': str(uuid4()), 'reference': f'CMP-{number}', 'group': group,
                            'customer_name': name, 'customer_phone': phone, 'customer_id': identifier,
                            **location, 'village': village, 'category': category, 'description': description,
                            'status': 'Pending', 'revision': 1, 'reported_at': stamp(), 'history': [],
                            'history_truncated': False, 'evidence': [], 'source': 'Recorded in the local demo intake.'}
                    self.attach(case, files, actor)
                    self.cases.append(case)
                    event, note = 'created', 'Complaint recorded' + (' with evidence.' if files else '.')
                else:
                    case = self.find(persona, group, key)
                    if action not in ACTIONS or not self.can(persona, ACTIONS[action][0]):
                        raise DemoFailure(403, 'This demo role does not permit that complaint action.')
                    if type(payload.get('revision')) is not int or payload['revision'] != case['revision']:
                        raise DemoFailure(409, 'This complaint changed. Refresh and review the latest details; your draft is retained.')
                    if action not in {item['value'] for item in self.actions(persona, case)}:
                        raise DemoFailure(400, 'That action is not available in the current complaint state.')
                    if action == 'complete':
                        phone, identifier = self.identifiers(fields, case)
                        case.update(customer_phone=phone, customer_id=identifier, status='Pending')
                        event, note = 'details_completed', 'Missing customer identifiers completed.'
                    elif action == 'upload':
                        files = self.validate_files(payload.get('files', []))
                        if not files:
                            raise DemoFailure(400, 'Choose at least one evidence file.')
                        self.attach(case, files, actor)
                        event, note = 'evidence_uploaded', 'Evidence attached to the complaint.'
                    else:
                        note = self.text(fields, 'note', 'a resolution comment' if action == 'comment' else 'a resolution note' if action == 'resolve' else 'a reason for reopening')
                        event = {'comment': 'commented', 'resolve': 'resolved', 'reopen': 'reopened'}[action]
                        if action != 'comment':
                            case['status'] = 'Resolved' if action == 'resolve' else 'Pending'
                    case['revision'] += 1
                case['history'].insert(0, {'action': event, 'status': case['status'], 'created_at': stamp(),
                                           'updated_by': actor, 'actor_affiliation': 'HB' if persona == 'hb' else 'JBL' if persona in {'officer', 'manager'} else 'IT', 'note': note})
                result = {'case': self.detail(persona, case), 'message': f"{case['reference']}: {dict(created='Complaint recorded.', commented='Resolution comment saved. The case remains open.', resolved='Complaint resolved.', reopened='Complaint reopened.', details_completed='Missing details completed.', evidence_uploaded='Evidence uploaded.')[event]}"}
            self.receipts[request] = digest, deepcopy(result)
            return result
