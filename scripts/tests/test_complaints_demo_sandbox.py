"""Synthetic role journeys use current built-in policy, never operational data."""
from copy import deepcopy
import unittest
from uuid import uuid4
from unittest.mock import patch

from scripts.complaints_demo_sandbox import DemoFailure, Sandbox, sample_image, seed


class RoleJourneyTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = Sandbox(seed())
        self.case = self.sandbox.cases[0]

    def body(self, case=None, **fields):
        return {'epoch': self.sandbox.epoch, 'request_key': str(uuid4()), 'revision': (case or self.case)['revision'], 'fields': fields}

    def act(self, persona, action, case=None, body=None):
        case = case or self.case
        return self.sandbox.mutate(persona, f"groups/{case['group']}/cases/{case['key']}/{action}/", body or self.body(case, note='Synthetic service feedback.'))

    def create_body(self, **changes):
        fields = dict(customer_name='Sample Farmer — New intake', customer_phone='0700000099', customer_id='90000099',
                      branch='Nakuru', category='Gas production', village='Sample village', description='Gas output is low; please inspect the system.')
        fields.update(changes)
        return {**self.body(), 'fields': fields, 'files': [sample_image()]}

    def test_built_in_roles_and_it_override_are_independent(self):
        for persona in ('officer', 'manager', 'it'):
            self.assertTrue(self.sandbox.context(persona)['can_create'])
        self.assertFalse(self.sandbox.context('hb')['can_create'])
        self.assertEqual(self.sandbox.context('portal')['groups'], [])
        self.assertFalse(self.sandbox.can('officer', 'complaint.case.close'))
        self.assertFalse(self.sandbox.can('manager', 'complaint.case.close'))
        self.assertTrue(self.sandbox.can('hb', 'complaint.case.close'))
        self.assertTrue(self.sandbox.can('it', 'complaint.case.close'))
        with self.assertRaises(DemoFailure):
            self.sandbox.read('portal', 'groups/1/cases/', {})

    def test_creation_with_evidence_is_shared_across_roles_and_request_retries(self):
        payload = self.create_body()
        saved = self.sandbox.mutate('officer', 'groups/1/cases/', payload)
        case = saved['case']
        self.assertEqual(case['status'], 'Pending')
        self.assertEqual(case['reference'], 'CMP-11')
        self.assertEqual(case['history'][0]['updated_by'], 'Demo Officer')
        self.assertEqual(len(case['evidence']), 1)
        self.assertEqual(self.sandbox.mutate('officer', 'groups/1/cases/', payload), saved)
        self.assertEqual(len(self.sandbox.cases), 11)
        self.assertEqual(self.sandbox.read('hb', f"groups/1/cases/{case['key']}/", {})['case']['reference'], case['reference'])

    def test_intake_requires_both_identifiers_and_location(self):
        for field in ('customer_name', 'customer_phone', 'customer_id', 'branch', 'category', 'village', 'description'):
            with self.subTest(field=field):
                with self.assertRaises(DemoFailure):
                    self.sandbox.mutate('officer', 'groups/1/cases/', self.create_body(**{field: ''}))
        for changes in ({'customer_phone': 'invalid'}, {'customer_id': 'A123'}, {'branch': 'Outside group'}):
            with self.assertRaises(DemoFailure):
                self.sandbox.mutate('officer', 'groups/1/cases/', self.create_body(**changes))
        self.assertEqual(len(self.sandbox.cases), 10)
        self.assertFalse(self.sandbox.files)

    def test_hb_cannot_create_and_officer_manager_cannot_resolve(self):
        for persona in ('hb', 'portal'):
            with self.assertRaises(DemoFailure) as raised:
                self.sandbox.mutate(persona, 'groups/1/cases/', self.create_body())
            self.assertEqual(raised.exception.status, 403)
        for persona in ('officer', 'manager', 'portal'):
            with self.assertRaises(DemoFailure) as raised:
                self.act(persona, 'resolve')
            self.assertEqual(raised.exception.status, 403)

    def test_comment_does_not_resolve_and_has_revision_actor_and_note(self):
        body = self.body(note='Parts booked; return visit confirmed.')
        saved = self.act('hb', 'comment', body=body)
        self.assertEqual(saved['case']['status'], 'Pending')
        self.assertEqual(saved['case']['revision'], 2)
        self.assertEqual(saved['case']['history'][0]['note'], body['fields']['note'])
        self.assertEqual(saved['case']['history'][0]['updated_by'], 'Demo HB Resolver')
        self.assertEqual(self.act('hb', 'comment', body=body), saved)
        self.assertEqual(len(self.case['history']), 2)

    def test_resolve_reopen_flow_and_closed_comment_denial(self):
        saved = self.act('hb', 'resolve')
        self.assertEqual(saved['case']['status'], 'Resolved')
        with self.assertRaises(DemoFailure):
            self.act('hb', 'comment')
        with self.assertRaises(DemoFailure):
            self.act('officer', 'reopen')
        reopened = self.act('manager', 'reopen')
        self.assertEqual(reopened['case']['status'], 'Pending')
        self.assertEqual(reopened['case']['history'][0]['updated_by'], 'Demo Manager')
        self.assertEqual(reopened['case']['history'][1]['action'], 'resolved')

    def test_missing_details_only_officer_manager_and_existing_identifiers_preserved(self):
        case = self.sandbox.cases[2]
        with self.assertRaises(DemoFailure):
            self.act('hb', 'complete', case, self.body(case, customer_phone='0700000099', customer_id='90000099'))
        saved = self.act('officer', 'complete', case, self.body(case, customer_phone='0700000099', customer_id='90000099'))
        self.assertEqual(saved['case']['status'], 'Pending')
        self.assertEqual(saved['case']['history'][0]['action'], 'details_completed')
        with self.assertRaises(DemoFailure):
            self.act('manager', 'complete', case, self.body(case, customer_phone='0700000098', customer_id='90000098'))

    def test_upload_signature_validation_replay_dedup_and_scope(self):
        body = {**self.body(), 'files': [sample_image()]}
        result = self.act('officer', 'upload', body=body)
        self.assertEqual(len(result['case']['evidence']), 1)
        self.assertEqual(self.act('officer', 'upload', body=body), result)
        self.act('hb', 'upload', body={**self.body(), 'files': [sample_image()]})
        self.assertEqual(len(self.case['evidence']), 1)
        key = self.case['evidence'][0]['key']
        raw, mime = self.sandbox.attachment('manager', key)
        self.assertTrue(raw.startswith(b'\x89PNG'))
        self.assertEqual(mime, 'image/png')
        with self.assertRaises(DemoFailure):
            self.sandbox.attachment('portal', key)
        bad = {**sample_image(), 'name': 'fake.pdf'}
        with self.assertRaises(DemoFailure):
            self.act('officer', 'upload', body={**self.body(), 'files': [bad]})
        foreign = self.sandbox.cases[-1]
        self.act('manager', 'upload', foreign, {**self.body(foreign), 'files': [sample_image()]})
        with self.assertRaises(DemoFailure):
            self.sandbox.attachment('hb', foreign['evidence'][0]['key'])

    def test_upload_limits_and_empty_selection(self):
        for files in ([], [sample_image()] * 11, [{'name': 'bad.png', 'content': 'invalid'}]):
            with self.assertRaises(DemoFailure):
                self.act('officer', 'upload', body={**self.body(), 'files': files})
        self.assertFalse(self.sandbox.files)
        with patch('scripts.complaints_demo_sandbox.MAX_FILE', 1):
            with self.assertRaises(DemoFailure):
                self.act('officer', 'upload', body={**self.body(), 'files': [sample_image()]})
        with patch('scripts.complaints_demo_sandbox.MAX_TOTAL', 1):
            with self.assertRaises(DemoFailure):
                self.act('officer', 'upload', body={**self.body(), 'files': [sample_image()]})
        self.assertFalse(self.sandbox.files)
        self.assertEqual(self.case['revision'], 1)

    def test_stale_revision_payload_conflict_and_reset_generation(self):
        old = self.body(note='First comment')
        self.act('hb', 'comment', body=old)
        changed = deepcopy(old); changed['fields']['note'] = 'Different comment'
        with self.assertRaises(DemoFailure) as raised:
            self.act('hb', 'comment', body=changed)
        self.assertEqual(raised.exception.status, 409)
        stale = self.body(note='Stale draft'); stale['revision'] = 1
        with self.assertRaises(DemoFailure) as raised:
            self.act('hb', 'comment', body=stale)
        self.assertEqual(raised.exception.status, 409)
        upload = {**self.body(), 'files': [sample_image()]}
        self.act('officer', 'upload', body=upload)
        reset = self.body()
        receipt = self.sandbox.mutate('officer', 'reset/', reset)
        self.assertEqual(self.sandbox.mutate('officer', 'reset/', reset), receipt)
        self.assertEqual(len(self.sandbox.cases), 10)
        self.assertFalse(self.sandbox.files)
        with self.assertRaises(DemoFailure) as raised:
            self.act('hb', 'comment', body=old)
        self.assertEqual(raised.exception.status, 409)
        with self.assertRaises(DemoFailure) as raised:
            self.sandbox.mutate('officer', 'groups/1/cases/', self.create_body() | {'epoch': 1})
        self.assertEqual(raised.exception.status, 409)

    def test_group_boundary_shared_branches_and_confidential_source(self):
        page = self.sandbox.read('officer', 'groups/1/cases/', {})
        self.assertEqual({case['branch'] for case in page['items']}, {'Nakuru', 'Eldoret'})
        with self.assertRaises(DemoFailure):
            self.sandbox.read('hb', 'groups/2/cases/', {})
        route = f"groups/1/cases/{self.case['key']}/"
        self.assertNotIn('source', self.sandbox.read('officer', route, {})['case'])
        self.assertIn('source', self.sandbox.read('manager', route, {})['case'])


if __name__ == '__main__':
    unittest.main()
