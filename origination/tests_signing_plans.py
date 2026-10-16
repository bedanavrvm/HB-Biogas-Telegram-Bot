"""Synthetic PostgreSQL-compatible acceptance at the signing-plan seam."""
import hashlib
from io import BytesIO
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from unittest import skipUnless
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction, connection, connections, close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfWriter

from core.models import AccessGrant
from origination.models import (LoanOriginationApplication, OriginationConsentPolicyVersion,
    OriginationProductDefinition, OriginationSigningPackage, OriginationSignerSession, OriginationSigningParticipant,
    OriginationDocumentTemplate, OriginationApplicationDocument)
from origination.services.loan_origination import (OriginationError, OriginationConflict,
    recall_application, serialize_application, _package_review_scope_hash)
from origination.services.loan_origination import confirm_and_start_conditional_signing
from origination.services.origination_consent import active_consent_policy, policy_snapshot
from origination.services.origination_signing_plans import (initialize_plan, configure_plan, freeze_plan, workspace)
from origination.services.origination_esign import (complete_staff_signatures, create_signer_session,
    record_consent_and_signature, issue_otp, verify_otp, resolve_session, serialize_verified_signing)


@override_settings(ORIGINATION_CONDITIONAL_APPROVAL_ENABLED=True, ORIGINATION_ESIGN_ENABLED=True,
    AFRICASTALKING_SMS_ENVIRONMENT='sandbox', AFRICASTALKING_USERNAME='sandbox',
    AFRICASTALKING_API_KEY='synthetic-only', SENTRY_ENVIRONMENT='test',
    APP_BASE_URL='http://127.0.0.1:8765')
class SigningPlanTests(TestCase):
    def setUp(self):
        from core.models import ComplianceAuditChainState
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        users = get_user_model()
        self.officer = users.objects.create_user(username='synthetic-plan-maker', is_superuser=True, is_staff=True)
        self.admin = users.objects.create_user(username='synthetic-plan-admin', is_superuser=True, is_staff=True)
        self.other = users.objects.create_user(username='synthetic-plan-other', is_superuser=True)
        self.outsider = users.objects.create_user(username='synthetic-plan-outsider', is_staff=True)
        rules = []
        for index, (role, key) in enumerate([('borrower','borrower'), ('borrower','joint_borrower'),
                                           ('officer','officer'), ('branch_manager','manager_one'), ('branch_manager','manager_two')]):
            rules.append({'role': role, 'participant_key': key, 'required': True,
                'identity': {'name': f'Synthetic person {index}', 'national_id': f'9900000{index}',
                             'phone': f'25470000000{index}'},
                'slots': [{'document_key':'primary', 'key':f'signature_{index}', 'type':'signature','required':True}]})
        self.definition = OriginationProductDefinition.objects.create(product_key='synthetic-plan', name='Synthetic plan',
            document_type='synthetic', signing_policy='all_required', signer_rules=rules)
        self.application = LoanOriginationApplication.objects.create(reference_number='ORG-SYNTHETIC-PLAN',
            product_definition=self.definition, officer=self.officer, branch='Synthetic branch',
            signing_policy_snapshot='all_required', signer_rules_snapshot=rules,
            schema_snapshot={'fields': []}, form_payload={})
        self.policy = OriginationConsentPolicyVersion.objects.create(version='synthetic-plan-consent', status='active',
            signing_policy='all_required', packet_clause='Synthetic test: all required signers complete approval.',
            signer_consent_text='Synthetic consent.', signer_completion_text='Synthetic signature complete.',
            resigning_text='Synthetic signing must be repeated.', approval_reference='SYNTHETIC-NOT-LEGAL-APPROVAL',
            approved_by=self.admin, approved_at=timezone.now(), created_by=self.admin)
        initialize_plan(self.application)
        self.application.refresh_from_db()
        self.audit = patch('core.services.compliance_audit.record_event')
        self.audit.start()
        self.addCleanup(self.audit.stop)
        self.wake = patch('origination.services.origination_dispatch.wake_operations')
        self.wake.start()
        self.addCleanup(self.wake.stop)

    def package(self):
        pdf = PdfWriter(); pdf.add_blank_page(width=595, height=842)
        stream = BytesIO(); pdf.write(stream)
        content = stream.getvalue()
        participants = freeze_plan(self.application)
        placements = {p['role']+'.'+s['key']: {'page_number':1, 'allowed_area':{'x':20,'y':20+i*45,'width':140,'height':40}}
            for i,p in enumerate(participants) for s in p['slots']}
        result = OriginationSigningPackage(application=self.application, application_revision=self.application.revision,
            external_reference=f'SYNTHETIC-{uuid4()}', document_type='synthetic',
            frozen_unsigned_document=content, unsigned_document_hash=hashlib.sha256(content).hexdigest(),
            context_snapshot={'_signing_plan':{**self.application.signing_plan,'policy':'all_required'}},
            conditional_approval=True, consent_policy=self.policy, consent_policy_snapshot=policy_snapshot(self.policy),
            participants_snapshot=participants, document_manifest_snapshot=[{'key':'primary','page_count':1,
                'template':{'configuration':{'signature_overlay_manifest':{'slots':placements}}}}])
        result.review_scope_sha256 = _package_review_scope_hash(result); result.save()
        self.application.status='signing_pending'; self.application.save(update_fields=['status'])
        return result

    def sign_staff(self, package, participant, actor, request_id=None):
        self.application.refresh_from_db()
        return complete_staff_signatures(package_id=package.pk, signer_role=participant['role'],
            participant_id=participant['participant_id'], actor=actor,
            consent=True,
            signature_capture={'method':'typed','name':actor.username},
            expected_revision=self.application.revision, request_id=request_id or str(uuid4()))

    def sign_external(self, package, participant):
        session, token, _ = create_signer_session(package_id=package.pk, signer_role=participant['role'],
            participant_id=participant['participant_id'], actor=self.officer, request_id=str(uuid4()))
        record_consent_and_signature(raw_token=token, signature_capture={'method':'typed','name':'Synthetic signer'},
            consent=True, access_mode='self_service', ip_hash='synthetic', reviewed_pages=[1], request_id=str(uuid4()))
        challenge, code, _ = issue_otp(raw_token=token, request_id=str(uuid4()), ip_hash='synthetic')
        verify_otp(raw_token=token, code=code, request_id=str(uuid4()), ip_hash='synthetic')
        return session, token

    def test_defaults_are_copied_without_mandatory_admin_visit(self):
        self.assertEqual(self.application.signing_plan_revision,1)
        self.assertEqual(len(freeze_plan(self.application)),5)
        self.definition.signing_defaults=[]; self.definition.signing_policy='legacy'; self.definition.save()
        self.assertEqual(len(freeze_plan(self.application)),5)
        self.assertEqual(self.application.signing_policy_snapshot,'all_required')

    def test_only_active_superuser_can_change_requirements(self):
        with self.assertRaises(PermissionDenied):
            configure_plan(application_id=self.application.pk, actor=self.outsider, choices=[],
                expected_revision=1, expected_plan_revision=1, request_id='denied')

    def test_required_participant_cannot_be_removed(self):
        choices=[{'participant_key':'borrower'}]
        with self.assertRaisesMessage(OriginationError,'required document signer'):
            configure_plan(application_id=self.application.pk, actor=self.admin, choices=choices,
                expected_revision=1,expected_plan_revision=1,request_id='remove-required')

    def test_product_defaults_cannot_omit_a_required_document_placement(self):
        from origination.services.origination_signing_plans import default_choices
        self.definition.signing_defaults = [{'participant_key': 'borrower'}]
        self.definition.save(update_fields=['signing_defaults'])
        self.application.signer_rules_snapshot[-1]['required'] = False
        self.application.save(update_fields=['signer_rules_snapshot'])
        choices = default_choices(self.application)
        self.assertIn('manager_two', [row['participant_key'] for row in choices])

    def test_conflict_and_request_replay_do_not_duplicate_participants(self):
        choices=[{'participant_key':p['participant_key'], 'staff_user_id':self.officer.pk if p['role']=='officer' else self.admin.pk if p['participant_key']=='manager_one' else None}
            for p in self.definition.signer_rules]
        saved=configure_plan(application_id=self.application.pk,actor=self.admin,choices=choices,
            expected_revision=1,expected_plan_revision=1,request_id='configure')
        again=configure_plan(application_id=self.application.pk,actor=self.admin,choices=choices,
            expected_revision=1,expected_plan_revision=1,request_id='configure')
        self.assertEqual(saved.signing_plan,again.signing_plan)
        self.assertEqual(OriginationSigningParticipant.objects.count(),10)
        with self.assertRaises(OriginationConflict):
            configure_plan(application_id=self.application.pk,actor=self.admin,choices=choices,
                expected_revision=1,expected_plan_revision=1,request_id='stale')

    def test_two_borrowers_keep_separate_sessions_and_replay_tokens(self):
        package=self.package(); people=package.participants_snapshot[:2]
        sessions=[]
        for index,p in enumerate(people):
            args=dict(package_id=package.pk,signer_role='borrower',participant_id=p['participant_id'],
                actor=self.officer,request_id=f'session-{index}')
            session,token,_=create_signer_session(**args)
            replay,replay_token,replayed=create_signer_session(**args)
            self.assertTrue(replayed); self.assertEqual(token,replay_token)
            self.assertEqual(resolve_session(token).pk,session.pk)
            sessions.append(session)
        self.assertNotEqual(sessions[0].token_hash,sessions[1].token_hash)
        self.assertEqual(package.signer_sessions.filter(is_active=True).count(),2)
        with self.assertRaisesMessage(OriginationError,'individual signer'):
            create_signer_session(package_id=package.pk,signer_role='borrower',actor=self.officer,request_id='role-only')

    def test_database_rejects_two_active_sessions_for_one_participant(self):
        package=self.package(); p=package.participants_snapshot[0]
        session,token,_=create_signer_session(package_id=package.pk,signer_role='borrower',
            participant_id=p['participant_id'],actor=self.officer,request_id='first-session')
        with self.assertRaises(IntegrityError), transaction.atomic():
            OriginationSignerSession.objects.create(package=package,signer_role='borrower',participant_id=p['participant_id'],
                token_hash='a'*64,token_expires_at=timezone.now(),created_by=self.officer,identity_snapshot={},
                phone_normalized='254700000000',phone_hash='synthetic',phone_last4='0000')

    def test_staff_in_any_order_then_final_borrower_approves_once(self):
        package=self.package(); people=package.participants_snapshot
        self.sign_staff(package,people[3],self.admin)
        self.sign_staff(package,people[4],self.other)
        self.sign_staff(package,people[2],self.officer)
        self.sign_external(package,people[1])
        self.application.refresh_from_db(); self.assertEqual(self.application.status,'partially_signed')
        session,token=self.sign_external(package,people[0])
        self.application.refresh_from_db(); package.refresh_from_db()
        self.assertEqual(self.application.status,'approved')
        self.assertEqual(package.final_approved_signed_document_hash,package.signed_document_hash)
        verify_otp(raw_token=token,code='000000',request_id='replay-complete',ip_hash='synthetic')
        self.assertEqual(self.application.events.filter(action='signatures_completed').count(),1)
        self.assertEqual(workspace(self.application,package,self.officer)['completed_count'],5)

    def test_authenticated_staff_signing_does_not_require_sms_credentials(self):
        package = self.package()
        with override_settings(ORIGINATION_SMS_PROVIDER='advanta', ORIGINATION_ADVANTA_API_KEY='',
                               AFRICASTALKING_API_KEY=''):
            row = next(item for item in workspace(self.application, package, self.officer)['participants']
                       if item['staff_user_id'] == self.officer.pk)
            self.assertTrue(row['can_sign'])
            self.assertTrue(serialize_verified_signing(package)['enabled'])
            self.assertFalse(serialize_verified_signing(package)['delivery_available'])
            self.sign_staff(package, package.participants_snapshot[2], self.officer)
        self.assertTrue(package.actions.filter(actor=self.officer).exists())

    def test_independent_staff_cannot_fill_two_participants(self):
        package=self.package(); people=package.participants_snapshot
        self.sign_staff(package,people[3],self.admin)
        with self.assertRaisesMessage(OriginationError,'different people'):
            self.sign_staff(package,people[4],self.admin)
        with self.assertRaises(OriginationError):
            self.sign_staff(package,people[4],self.outsider)

    def test_staff_acknowledgement_receipt_is_saved_and_retry_is_idempotent(self):
        from django.test import RequestFactory
        from origination.views import portal_origination_staff_signature
        from core.services.telegram_identity import user_access
        package = self.package()
        participant = package.participants_snapshot[3]
        body = {'package_id': str(package.pk), 'signer_role': participant['role'],
                'participant_id': participant['participant_id'], 'revision': self.application.revision,
                'signature_capture': {'method': 'typed', 'name': 'Synthetic Manager'},
                'consent': True, 'client_request_id': 'synthetic-acknowledgement'}
        def submit(actor):
            request = RequestFactory().post('/signing/', data=body, content_type='application/json')
            request.origination_user = actor
            request.origination_access = user_access(actor, 'loan_origination')
            return portal_origination_staff_signature(request, str(self.application.pk))
        first = submit(self.admin)
        self.assertEqual(first.status_code, 200, first.content)
        import json
        data = json.loads(first.content)
        self.assertTrue(data['signature_receipt']['signed_at'])
        self.assertEqual(data['application']['status'], 'partially_signed')
        second = submit(self.admin)
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(json.loads(second.content)['signature_receipt'], data['signature_receipt'])
        self.assertEqual(submit(self.outsider).status_code, 403)
        projected = next(person for person in serialize_verified_signing(package)['participants']
                         if person['participant_id'] == participant['participant_id'])
        self.assertEqual(projected['signature_actor_id'], self.admin.pk)
        self.assertEqual(projected['signed_at'], data['signature_receipt']['signed_at'])

    def test_partial_withdrawal_retires_sessions_and_preserves_history(self):
        package=self.package(); self.sign_external(package,package.participants_snapshot[0])
        original_ids=list(self.application.signing_plan['participants'])
        self.application.refresh_from_db()
        recalled=recall_application(application_id=self.application.pk,actor=self.officer,
            expected_revision=self.application.revision,request_id='withdraw',confirmed_package_id=str(package.pk),
            confirmed_package_hash=package.unsigned_document_hash)
        package.refresh_from_db(); self.assertEqual(recalled.status,'draft'); self.assertEqual(package.status,'cancelled')
        self.assertFalse(package.signer_sessions.filter(is_active=True).exists())
        self.assertTrue(package.actions.filter(invalidation__isnull=False).exists())
        self.assertEqual(len(freeze_plan(recalled)),5)
        self.assertTrue(set(original_ids).isdisjoint(recalled.signing_plan['participants']))
        self.assertIsNone(serialize_application(recalled,actor=self.officer)['signing_package'])

    def test_assignment_and_queue_projection_use_current_authority(self):
        package=self.package()
        result=serialize_application(self.application,actor=self.outsider)
        self.assertFalse(any(p['can_sign'] for p in result['signing_workspace']['participants']))
        self.assertFalse(result['signing_workspace']['can_configure'])
        self.assertEqual(len(serialize_verified_signing(package)['participants']),5)

    def test_officer_queue_keeps_unsent_and_expired_links_actionable_after_signing(self):
        from core.services.telegram_identity import user_access
        from origination.services.origination_queues import actionable_applications
        package = self.package()
        self.sign_staff(package, package.participants_snapshot[2], self.officer)
        access = user_access(self.officer, 'loan_origination')
        scoped = LoanOriginationApplication.objects.filter(pk=self.application.pk)
        def action():
            return actionable_applications(scoped, user=self.officer, access=access).get(str(self.application.pk))
        self.assertEqual(action(), 'Send signing links')
        sessions = []
        for index, person in enumerate(package.participants_snapshot[:2]):
            session, _, _ = create_signer_session(package_id=package.pk, signer_role='borrower',
                participant_id=person['participant_id'], actor=self.officer, access_mode='assisted', request_id=f'queue-link-{index}')
            sessions.append(session)
        self.assertIsNone(action())
        OriginationSignerSession.objects.filter(pk=sessions[0].pk).update(token_expires_at=timezone.now())
        self.assertEqual(action(), 'Send signing links')

    def test_admin_screen_and_denial(self):
        self.client.force_login(self.admin)
        url=reverse('admin:origination_application_signers',args=[self.application.pk])
        response=self.client.get(url)
        self.assertContains(response,'Applicants and other signers')
        self.assertContains(response,'origination_application_signers.js')
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(url).status_code,403)

    def test_consent_cannot_fall_back_to_empty_legacy_roles(self):
        with self.assertRaises(ValueError):
            active_consent_policy(approval_roles=[])
        self.assertEqual(active_consent_policy(signing_policy='all_required').pk,self.policy.pk)

    def test_unchanged_save_keeps_revision_and_preview(self):
        self.application.primary_previewed_revision=self.application.revision
        self.application.save(update_fields=['primary_previewed_revision'])
        choices=[{'participant_key':p['participant_key'], 'staff_user_id':self.officer.pk if p['role']=='officer' else None}
                 for p in self.definition.signer_rules]
        saved=configure_plan(application_id=self.application.pk,actor=self.admin,choices=choices,
            expected_revision=1,expected_plan_revision=1,request_id='same-values')
        self.assertEqual(saved.revision,1)
        self.assertEqual(saved.primary_previewed_revision,1)
        self.assertEqual(OriginationSigningParticipant.objects.count(),5)

    def test_configured_optional_signer_changes_count_without_removing_document_requirements(self):
        self.application.signer_rules_snapshot.append({'role':'witness','participant_key':'witness','required':False,
            'identity':{'name':'Synthetic witness','national_id':'99000009','phone':'254700000009'},
            'slots':[{'key':'witness_signature','document_key':'primary','type':'signature','required':False}]})
        self.application.save(update_fields=['signer_rules_snapshot'])
        choices=[{'participant_key':p['participant_key'],'staff_user_id':self.officer.pk if p['role']=='officer' else None}
                 for p in self.application.signer_rules_snapshot]
        saved=configure_plan(application_id=self.application.pk,actor=self.admin,choices=choices,
            expected_revision=1,expected_plan_revision=1,request_id='add-witness')
        self.assertEqual(workspace(saved)['required_count'],6)
        self.assertTrue(freeze_plan(saved)[-1]['slots'][0]['required'])

    def test_consent_and_frozen_plan_integrity_are_enforced(self):
        package=self.package(); p=package.participants_snapshot[3]
        with self.assertRaisesMessage(OriginationError,'Confirm'):
            complete_staff_signatures(package_id=package.pk,signer_role=p['role'],participant_id=p['participant_id'],
                actor=self.admin,signature_capture={'method':'typed','name':'Synthetic Manager'},
                expected_revision=self.application.revision,request_id='missing-consent')
        package.participants_snapshot[0]['identity']['name']='Changed synthetic identity'
        package.save(update_fields=['participants_snapshot'])
        with self.assertRaisesMessage(OriginationError,'integrity'):
            self.sign_staff(package,p,self.admin)

    def test_admin_autosave_returns_acknowledged_revision_and_denies_submitted_edits(self):
        self.client.force_login(self.admin)
        url=reverse('admin:origination_application_signers',args=[self.application.pk])
        form=self.client.get(url).context['form']
        body={'revision':1,'plan_revision':1,'request_id':'admin-post'}
        for row in form.rows:
            body[row['selected'].name]='on'
            if row['assigned'] and row['key']=='officer': body[row['assigned'].name]=self.officer.pk
        response=self.client.post(url,body,HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json()['ok'])
        self.package()
        body['request_id']='submitted-edit'
        self.assertEqual(self.client.post(url,body,HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code,400)

    def submission_document(self):
        pdf=PdfWriter();pdf.add_blank_page(width=595,height=842)
        stream=BytesIO();pdf.write(stream);source=stream.getvalue()
        rules=self.application.signer_rules_snapshot
        fields,values=[],{}
        for index,rule in enumerate(rules[:2]):
            rule['identity_fields']={kind:f'signer_{index}_{kind}' for kind in ['name','phone','national_id']}
            for kind,key in rule['identity_fields'].items():
                fields.append({'key':key,'type':'text','required':True})
                values[key]=rule['identity'][kind]
        self.application.schema_snapshot={'fields':fields}
        self.application.form_payload=values
        self.application.primary_previewed_revision=self.application.revision
        self.application.save()
        configuration={'signature_overlay_manifest':{'slots':{r['role']+'.'+r['slots'][0]['key']:
            {'page_number':1,'x':20,'y':20+index*50,'width':140,'height':40} for index,r in enumerate(rules)}}}
        template=OriginationDocumentTemplate.objects.create(document_type='synthetic',name='Synthetic signatures',
            version=1,source_filename='synthetic.pdf',source_sha256=hashlib.sha256(source).hexdigest(),
            source_byte_size=len(source),page_count=1,placement_config=configuration,created_by=self.officer)
        OriginationApplicationDocument.objects.create(application=self.application,template=template,
            document_key='primary',name='Synthetic signatures',document_role='primary',schema_snapshot={'fields':[]},
            signer_rules_snapshot=rules,template_snapshot={'sha256':template.source_sha256,'configuration':configuration})
        return source

    def test_single_submission_prepares_real_documents_without_operations(self):
        from pypdf import PdfReader
        source=self.submission_document()
        with patch('origination.services.origination_templates.load_template_source',return_value=source):
            package,replayed=confirm_and_start_conditional_signing(application_id=self.application.pk,
                actor=self.officer,expected_revision=self.application.revision,request_id='direct-submit')
            duplicate,again=confirm_and_start_conditional_signing(application_id=self.application.pk,
                actor=self.officer,expected_revision=1,request_id='direct-submit')
        self.assertFalse(replayed);self.assertTrue(again);self.assertEqual(package.pk,duplicate.pk)
        self.assertEqual(package.application.status,'signing_pending')
        self.assertIsNone(package.reviewed_by)
        self.assertEqual(package.consent_policy.signing_policy,'all_required')
        self.assertEqual(len(PdfReader(BytesIO(bytes(package.frozen_unsigned_document))).pages),2)
        self.assertEqual(len(package.participants_snapshot),5)

    def test_missing_required_placement_is_rejected_before_render_or_links(self):
        self.submission_document()
        document = self.application.packet_documents.get(document_key='primary')
        document.template_snapshot['configuration']['signature_overlay_manifest']['slots'].pop('borrower.signature_0')
        document.save(update_fields=['template_snapshot'])
        with patch('origination.services.origination_documents.render_packet') as render:
            with self.assertRaisesRegex(OriginationError, 'Place the required signatures'):
                confirm_and_start_conditional_signing(application_id=self.application.pk, actor=self.officer,
                    expected_revision=self.application.revision, request_id='missing-placement')
        render.assert_not_called()
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'draft')
        self.assertFalse(self.application.signing_packages.exists())
        self.assertFalse(OriginationSignerSession.objects.filter(package__application=self.application).exists())

    def test_preparation_failure_returns_to_saved_draft(self):
        self.submission_document()
        with patch('origination.services.origination_templates.load_template_source',side_effect=OriginationError('Synthetic render failure')):
            with self.assertRaises(OriginationError):
                confirm_and_start_conditional_signing(application_id=self.application.pk,actor=self.officer,
                    expected_revision=1,request_id='failed-submit')
        self.application.refresh_from_db()
        self.assertEqual(self.application.status,'draft')
        self.assertEqual(self.application.revision,1)
        self.assertTrue(self.application.form_payload)
        self.assertFalse(self.application.signing_packages.exists())

    def test_completed_plan_supplies_only_the_exact_approved_facility_value(self):
        from origination.services.origination_value_contracts import resolve_packet_values
        from origination.tests_value_contracts import schema, field
        self.application.schema_snapshot = schema(field('approved', source='workflow', binding='workflow.approved_amount'))
        self.application.save(update_fields=['schema_snapshot'])
        package = self.package()
        package.context_snapshot.update(_value_contract_version=2, loan_amount='80000.00')
        package.review_scope_sha256 = _package_review_scope_hash(package)
        package.save(update_fields=['context_snapshot', 'review_scope_sha256'])
        self.assertEqual(resolve_packet_values(self.application)['values']['approved'], '')
        for person, actor in zip(package.participants_snapshot[2:], [self.officer, self.admin, self.other]):
            self.sign_staff(package, person, actor)
        for person in package.participants_snapshot[:2]:
            self.sign_external(package, person)
        self.application.refresh_from_db()
        self.assertEqual(resolve_packet_values(self.application)['values']['approved'], '80000.00')
        event = self.application.events.get(action='signatures_completed')
        self.assertEqual(event.after_values['approved_package_revision'], package.application_revision)

    def test_required_stamp_can_complete_approval_and_its_retry_is_idempotent(self):
        from PIL import Image
        from origination.models import OriginationStampAsset
        from origination.services.origination_esign import apply_production_stamp
        rule = self.application.signer_rules_snapshot[-1]
        rule['slots'].append({'document_key': 'primary', 'key': 'manager_stamp', 'type': 'stamp', 'required': True})
        self.application.save(update_fields=['signer_rules_snapshot'])
        choices = [{'participant_key': row['participant_key'],
                    'staff_user_id': self.officer.pk if row['role'] == 'officer' else None}
                   for row in self.application.signer_rules_snapshot]
        # A document change requires its plan to be reviewed, not an in-place edit.
        self.application.signing_plan = {}
        self.application.save(update_fields=['signing_plan'])
        configure_plan(application_id=self.application.pk, actor=self.admin, choices=choices,
            expected_revision=1, expected_plan_revision=1, request_id='stamp-plan')
        self.application.refresh_from_db()
        package = self.package()
        for person in package.participants_snapshot[:2]:
            self.sign_external(package, person)
        for person, actor in zip(package.participants_snapshot[2:], [self.officer, self.admin, self.other]):
            self.sign_staff(package, person, actor)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'partially_signed')
        stream = BytesIO()
        Image.new('RGB', (10, 10), 'green').save(stream, format='PNG')
        content = stream.getvalue()
        stamp = OriginationStampAsset.objects.create(name='Synthetic stamp', environment='production', active=True,
            image_png=content, byte_size=len(content), content_sha256=hashlib.sha256(content).hexdigest(), created_by=self.other)
        args = dict(package_id=package.pk, signer_role='branch_manager', actor=self.other,
            participant_id=package.participants_snapshot[-1]['participant_id'], document_key='primary',
            slot_key='manager_stamp', stamp_asset_id=stamp.pk, expected_revision=self.application.revision,
            request_id='last-required-stamp')
        apply_production_stamp(**args)
        apply_production_stamp(**args)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'approved')
        self.assertEqual(self.application.events.filter(action='signatures_completed').count(), 1)
        self.assertEqual(package.actions.filter(action_type='stamp').count(), 1)


@override_settings(ORIGINATION_CONDITIONAL_APPROVAL_ENABLED=True,ORIGINATION_ESIGN_ENABLED=True,
    AFRICASTALKING_SMS_ENVIRONMENT='sandbox',AFRICASTALKING_USERNAME='sandbox',
    AFRICASTALKING_API_KEY='synthetic-only',SENTRY_ENVIRONMENT='test',APP_BASE_URL='http://127.0.0.1:8765')
@skipUnless(connection.vendor == 'postgresql','Requires PostgreSQL row locks')
class SigningPlanConcurrencyTests(TransactionTestCase):
    def setUp(self):
        SigningPlanTests.setUp(self)

    def test_simultaneous_final_signature_retries_approve_once(self):
        package=SigningPlanTests.package(self)
        people=package.participants_snapshot
        SigningPlanTests.sign_external(self,package,people[0])
        SigningPlanTests.sign_external(self,package,people[1])
        SigningPlanTests.sign_staff(self,package,people[2],self.officer)
        SigningPlanTests.sign_staff(self,package,people[3],self.admin)
        self.application.refresh_from_db()
        revision=self.application.revision
        actor_id=self.other.pk
        def sign():
            close_old_connections()
            try:
                return complete_staff_signatures(package_id=package.pk,signer_role='branch_manager',
                    participant_id=people[4]['participant_id'],actor=get_user_model().objects.get(pk=actor_id),
                    consent=True,signature_capture={'method':'typed','name':'Synthetic final manager'},
                    expected_revision=revision,request_id='concurrent-final').pk
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as workers:
            self.assertEqual(list(workers.map(lambda _:sign(),range(2))),[package.pk,package.pk])
        self.application.refresh_from_db()
        self.assertEqual(self.application.status,'approved')
        self.assertEqual(self.application.events.filter(action='signatures_completed').count(),1)
        self.assertEqual(package.actions.filter(participant_id=people[4]['participant_id']).count(),1)
