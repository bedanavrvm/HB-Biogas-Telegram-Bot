import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from core.models import AccessGrant
from core.services.telegram_identity import user_access
from origination.models import LoanOriginationApplication, OriginationProductDefinition, OriginationSigningPackage
from origination.services.origination_access import scope_application_queryset
from origination.services.origination_queues import actionable_applications, STATUS_LABELS
from origination.views import portal_origination_applications


class OriginationQueueTests(TestCase):
    def setUp(self):
        self.officer = get_user_model().objects.create_user(username='queue-officer')
        self.viewer = get_user_model().objects.create_user(username='queue-viewer')
        self.product = OriginationProductDefinition.objects.create(
            product_key='queue-fixture', name='Training loan', version=1)
        self.sequence = 0

    def application(self, **values):
        self.sequence += 1
        return LoanOriginationApplication.objects.create(
            reference_number=f'QUEUE-{self.sequence}', product_definition=self.product,
            officer=values.pop('officer', self.officer), branch=values.pop('branch', 'Embu'), **values)

    def access(self, actor, role, branch='Embu'):
        AccessGrant.objects.create(user=actor, workflow='loan_origination', role=role, branch=branch)
        return user_access(actor, 'loan_origination')

    def actions(self, actor, access):
        scoped = scope_application_queryset(LoanOriginationApplication.objects.all(), user=actor, access=access)
        return actionable_applications(scoped, user=actor, access=access)

    def package(self, application, participants, **values):
        return OriginationSigningPackage.objects.create(
            application=application, application_revision=application.revision,
            external_reference=str(application.pk), document_type='training',
            template_version=1, template_sha256='a' * 64, context_snapshot={},
            participants_snapshot=participants, prepared_by=self.viewer, **values)

    def test_owned_drafts_and_corrections_only_not_waiting_or_outside_scope(self):
        access = self.access(self.officer, 'JBL_OFFICER')
        draft = self.application()
        correction = self.application(status='correction_required')
        self.application(status='approved')
        self.application(branch='Nakuru')
        self.application(officer=self.viewer)
        self.assertEqual(self.actions(self.officer, access), {
            str(draft.pk): 'Complete application', str(correction.pk): 'Make corrections'})

    def test_mixed_grants_do_not_borrow_another_grants_branch_for_signing(self):
        self.access(self.viewer, 'OPERATIONS_ADMIN', 'Nakuru')
        access = self.access(self.viewer, 'CA', 'Embu')
        ready = self.application(status='signing_pending')
        outside = self.application(status='signing_pending', branch='Nakuru')
        for row in (ready, outside):
            self.package(row, [{'role':'credit_analyst', 'slots':[{'key':'ca', 'required':True}]}])
        self.assertEqual(self.actions(self.viewer, access), {str(ready.pk): 'Sign application'})

    def test_approver_waits_for_other_participants_and_cannot_approve_own_case(self):
        access = self.access(self.viewer, 'BM')
        waiting = self.application(status='signing_pending', approval_roles_snapshot=['branch_manager'])
        ready = self.application(status='signing_pending', approval_roles_snapshot=['branch_manager'])
        own = self.application(officer=self.viewer, status='signing_pending', approval_roles_snapshot=['branch_manager'])
        bm = {'role':'branch_manager', 'slots':[{'key':'bm', 'required':True}]}
        self.package(waiting, [{'role':'borrower', 'slots':[{'key':'borrower', 'required':True}]}, bm])
        self.package(ready, [bm])
        self.package(own, [bm])
        self.assertEqual(self.actions(self.viewer, access), {str(ready.pk): 'Review and sign'})

    def test_legacy_preparation_review_and_dispatch_remain_available(self):
        access = self.access(self.viewer, 'OPERATIONS_ADMIN')
        pending = self.application(status='ready_for_review')
        review = self.application(status='ready_for_review')
        signing = self.application(status='reviewed')
        self.package(review, [], review_scope_sha256='b' * 64)
        actions = self.actions(self.viewer, access)
        self.assertEqual(actions[str(pending.pk)], 'Prepare packet')
        self.assertEqual(actions[str(signing.pk)], 'Start signing')
        self.assertEqual(actions[str(review.pk)], 'Review application')

    def test_api_counts_filters_labels_and_deduplication(self):
        access = self.access(self.officer, 'JBL_OFFICER')
        self.application()
        correction = self.application(status='correction_required')
        request = RequestFactory().get('/api/origination/api/applications/',
                                       {'queue':'action', 'status':'correction_required'})
        request.origination_user = self.officer
        request.origination_access = access
        with patch('origination.views._capability_error', return_value=None):
            response = portal_origination_applications(request)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['tab_counts']['action'], 2)
        self.assertEqual(data['pagination']['total'], 1)
        self.assertEqual(data['applications'][0]['id'], str(correction.pk))
        self.assertEqual(data['applications'][0]['next_action'], 'Make corrections')
        self.assertEqual(data['applications_label'], 'My applications')
        self.assertEqual(len(data['status_options']), len(LoanOriginationApplication.STATUS_CHOICES))
        self.assertNotIn('_', ''.join(STATUS_LABELS.values()))

    def test_every_status_filter_and_invalid_status(self):
        access = self.access(self.officer, 'JBL_OFFICER')
        for status, _ in LoanOriginationApplication.STATUS_CHOICES:
            row = self.application(status=status)
            request = RequestFactory().get('/api/origination/api/applications/',
                                           {'queue':'applications', 'status':status})
            request.origination_user, request.origination_access = self.officer, access
            with patch('origination.views._capability_error', return_value=None):
                response = portal_origination_applications(request)
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.content)
            self.assertEqual([r['id'] for r in data['applications']], [str(row.pk)])
            self.assertEqual(data['applications'][0]['status_label'], STATUS_LABELS[status])
        request = RequestFactory().get('/api/origination/api/applications/', {'status':'not-real'})
        request.origination_user, request.origination_access = self.officer, access
        with patch('origination.views._capability_error', return_value=None):
            self.assertEqual(portal_origination_applications(request).status_code, 400)

    def test_signature_deep_link_does_not_include_unrelated_drafts(self):
        access = self.access(self.officer, 'JBL_OFFICER')
        self.application()
        row = self.application(status='signing_pending')
        self.package(row, [{'role':'officer', 'slots':['officer-signature']}])
        request = RequestFactory().get('/api/origination/api/applications/',
                                       {'queue':'action', 'signature_only':'1'})
        request.origination_user, request.origination_access = self.officer, access
        with patch('origination.views._capability_error', return_value=None):
            data = json.loads(portal_origination_applications(request).content)
        self.assertEqual(data['pagination']['total'], 1)
        self.assertEqual(data['applications'][0]['id'], str(row.pk))
