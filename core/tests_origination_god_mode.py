from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import NoReverseMatch, reverse

from core.models import (
    LoanOriginationApplication,
    OriginationApplicationDocument,
    OriginationApplicationEvent,
    OriginationCorrectionItem,
    OriginationCorrectionRequest,
    OriginationDataField,
    OriginationDataFieldEvent,
    OriginationDocumentTemplate,
    OriginationDocumentTemplateEvent,
    OriginationFieldReviewIssue,
    OriginationProductDefinition,
    OriginationProductDefinitionEvent,
    OriginationProductDocumentAssignment,
    OriginationReportingValue,
    OriginationRequirementEvidence,
    OriginationReviewerNotice,
    OriginationSigningAction,
    OriginationSigningPackage,
    OriginationStampAsset,
    OriginationTemplateConfigurationRevision,
    OperationalLocation,
    Product,
    ProductVersion,
)
from core.services import origination_god_mode
from core.services.origination_god_mode import (
    ORIGINATION_RESET_MODELS,
    OriginationGodModeError,
    preview_full_origination_reset,
    purge_origination_record,
    reset_all_origination_data,
)


class OriginationGodModeTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.superuser = users.objects.create_superuser(
            username='origination-god-mode',
            email='god-mode@example.test',
            password='password',
        )
        self.staff = users.objects.create_user(
            username='ordinary-origination-staff',
            password='password',
            is_staff=True,
        )
        self.global_product = Product.objects.create(
            code='god-mode-test', name='God mode test', category='Testing',
        )
        self.global_product_version = ProductVersion.objects.create(
            product=self.global_product, version=1, created_by=self.superuser,
        )
        self.location = OperationalLocation.objects.create(
            location_type='branch', name='God mode test branch', code='GOD-TEST',
        )
        self.data_field = OriginationDataField.objects.create(
            key='god_mode_customer_name', label='Synthetic customer name',
            data_type=OriginationDataField.TYPE_TEXT, created_by=self.superuser,
        )
        OriginationDataFieldEvent.objects.create(
            data_field=self.data_field, action='created', actor=self.superuser,
        )
        self.product = OriginationProductDefinition.objects.create(
            product_version=self.global_product_version,
            product_key='god-mode-test', name='God mode test', version=1,
            form_schema={'fields': [{'key': 'customer_name', 'type': 'text', 'required': True}]},
            signer_rules=[{'role': 'customer'}], document_type='god_mode_test',
            document_template_name='God mode.pdf', document_template_version=1,
            document_template_sha256='a' * 64, is_active=True,
            lifecycle_status=OriginationProductDefinition.STATUS_PUBLISHED,
            created_by=self.superuser,
        )
        self.template = OriginationDocumentTemplate.objects.create(
            product_definition=self.product, document_key='primary', document_role='primary',
            inclusion_mode='required', document_type='god_mode_test', name='God mode LAF',
            version=1, status='active', source_filename='god-mode.pdf', source_sha256='b' * 64,
            source_byte_size=100, page_count=1, placement_config={}, created_by=self.superuser,
        )
        revision = OriginationTemplateConfigurationRevision.objects.create(
            template=self.template, revision=1, configuration={}, is_published=True,
            created_by=self.superuser,
        )
        self.template.published_configuration_revision = revision
        self.template.drive_file_id = 'drive-file-must-remain'
        self.template.drive_url = 'https://drive.example.test/drive-file-must-remain'
        self.template.save(update_fields=['published_configuration_revision', 'drive_file_id', 'drive_url'])
        OriginationDocumentTemplateEvent.objects.create(
            template=self.template, action='created', actor=self.superuser,
        )
        OriginationProductDefinitionEvent.objects.create(
            product_definition=self.product, action='published', actor=self.superuser,
        )
        self.application = LoanOriginationApplication.objects.create(
            reference_number='ORG-GOD-MODE-TEST', product_definition=self.product,
            officer=self.superuser, branch='Test branch', form_payload={'customer_name': 'Synthetic'},
            schema_snapshot=self.product.form_schema,
            signer_rules_snapshot=self.product.signer_rules,
        )
        OriginationApplicationDocument.objects.create(
            application=self.application, template=self.template,
            document_key='primary', name='Main LAF', document_role='primary',
            inclusion_mode='required', template_snapshot={},
        )
        OriginationApplicationEvent.objects.create(
            application=self.application, action='created', revision=1,
            actor=self.superuser,
        )
        OriginationReportingValue.objects.create(
            application=self.application, data_field=self.data_field,
            field_key=self.data_field.key, value_type=OriginationDataField.TYPE_TEXT,
            sensitivity=self.data_field.sensitivity,
            masking_policy=self.data_field.masking_policy,
            reporting_use=self.data_field.reporting_use,
            export_allowed=self.data_field.export_allowed,
            text_value='Synthetic',
        )
        correction = OriginationCorrectionRequest.objects.create(
            application=self.application, application_revision=1,
            reviewer=self.superuser, summary='Synthetic correction',
        )
        OriginationCorrectionItem.objects.create(
            correction_request=correction,
            target_type=OriginationCorrectionItem.TARGET_FIELD,
            target_key=self.data_field.key,
            target_label=self.data_field.label,
        )
        OriginationRequirementEvidence.objects.create(
            application=self.application, application_revision=1,
            requirement_key='test_id', requirement_label='Synthetic ID',
            original_filename='synthetic.pdf', mime_type='application/pdf',
            byte_size=100, content_sha256='c' * 64,
            drive_file_id='drive-evidence-must-remain',
            drive_url='https://drive.example.test/drive-evidence-must-remain',
            request_id='god-mode-evidence', uploaded_by=self.superuser,
        )
        self.signing_package = OriginationSigningPackage.objects.create(
            application=self.application, application_revision=1,
            external_reference='GOD-MODE-SIGNING-PACKAGE',
            document_type='god_mode_test',
        )
        OriginationReviewerNotice.objects.create(
            application=self.application, package=self.signing_package,
            recipient=self.superuser, created_by=self.superuser,
            notice_type=OriginationReviewerNotice.TYPE_APPROVAL_INVALIDATED,
            message='Synthetic approval invalidation.', request_id='god-mode-reviewer-notice',
        )
        self.stamp_asset = OriginationStampAsset.objects.create(
            name='Synthetic test stamp', environment=OriginationStampAsset.ENV_TEST,
            version=1, image_png=b'synthetic-png-bytes', content_sha256='e' * 64,
            byte_size=19, active=True, created_by=self.superuser,
            activated_by=self.superuser,
        )
        OriginationSigningAction.objects.create(
            package=self.signing_package, document_key='primary', slot_key='stamp',
            signer_role='loan_officer', action_type=OriginationSigningAction.TYPE_STAMP,
            mode=OriginationSigningAction.MODE_TEST, stamp_asset=self.stamp_asset,
            actor=self.superuser, request_id='god-mode-test-stamp',
        )
        OriginationFieldReviewIssue.objects.create(
            product_definition=self.product, legacy_key='legacy_customer_name',
            legacy_type=OriginationDataField.TYPE_TEXT,
            legacy_label='Legacy customer name', suggested_field=self.data_field,
        )

        self.draft_product = OriginationProductDefinition.objects.create(
            product_key='god-mode-draft', name='God mode draft', version=1,
            form_schema={'fields': []}, signer_rules=[], document_type='god_mode_draft',
            lifecycle_status=OriginationProductDefinition.STATUS_DRAFT,
            created_by=self.superuser,
        )
        self.supporting_template = OriginationDocumentTemplate.objects.create(
            product_definition=None, document_key='guarantor_form',
            document_role=OriginationDocumentTemplate.ROLE_SUPPORTING,
            inclusion_mode=OriginationDocumentTemplate.INCLUDE_REQUIRED,
            document_type='god_mode_guarantor', name='Synthetic guarantor form',
            version=1, status=OriginationDocumentTemplate.STATUS_ACTIVE,
            source_filename='guarantor.pdf', source_sha256='d' * 64,
            source_byte_size=100, page_count=1, placement_config={},
            drive_file_id='drive-supporting-template-must-remain',
            drive_url='https://drive.example.test/drive-supporting-template-must-remain',
            created_by=self.superuser,
        )
        self.assignment = OriginationProductDocumentAssignment.objects.create(
            product_definition=self.draft_product,
            template=self.supporting_template,
            document_key='guarantor_form', name='Synthetic guarantor form',
            created_by=self.superuser,
        )
        OriginationApplicationDocument.objects.create(
            application=self.application, template=self.supporting_template,
            assignment=self.assignment, document_key='guarantor_form',
            name='Synthetic guarantor form', document_role='supporting',
            inclusion_mode='required', template_snapshot={},
        )

    def test_service_rejects_non_superuser(self):
        with self.assertRaisesRegex(OriginationGodModeError, 'Superuser'):
            purge_origination_record(
                record=self.product, actor=self.staff, reason='Synthetic test cleanup',
            )

    def test_admin_requires_exact_id_then_purges_only_origination_database_graph(self):
        self.client.force_login(self.superuser)
        url = reverse(
            'admin:core_originationproductdefinition_god_mode_purge',
            args=[self.product.pk],
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Drive files')
        self.assertContains(response, str(self.product.pk))

        response = self.client.post(url, {
            'confirmation': 'wrong-id',
            'reason': 'Removing synthetic test setup',
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(OriginationProductDefinition.objects.filter(pk=self.product.pk).exists())

        response = self.client.post(url, {
            'confirmation': str(self.product.pk),
            'reason': 'Removing synthetic test setup',
        })
        self.assertRedirects(
            response,
            reverse('admin:core_originationproductdefinition_changelist'),
        )
        self.assertFalse(OriginationProductDefinition.objects.filter(pk=self.product.pk).exists())
        self.assertFalse(OriginationDocumentTemplate.objects.filter(pk=self.template.pk).exists())
        self.assertFalse(LoanOriginationApplication.objects.filter(pk=self.application.pk).exists())
        self.assertTrue(get_user_model().objects.filter(pk=self.superuser.pk).exists())

    def test_non_superuser_cannot_open_purge_endpoint(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse(
            'admin:core_originationproductdefinition_god_mode_purge',
            args=[self.product.pk],
        ))
        self.assertEqual(response.status_code, 403)

    def test_god_mode_route_is_not_added_to_other_miniapps(self):
        with self.assertRaises(NoReverseMatch):
            reverse('admin:core_tattrackercase_god_mode_purge', args=['test-record'])

    def test_full_reset_model_registry_covers_every_origination_model(self):
        discovered = {
            model
            for model in apps.get_app_config('core').get_models()
            if model.__name__.startswith('Origination')
            or model is LoanOriginationApplication
        }
        self.assertEqual(set(ORIGINATION_RESET_MODELS), discovered)
        self.assertEqual(len(ORIGINATION_RESET_MODELS), 23)

    def test_full_reset_service_rejects_non_superuser(self):
        before = preview_full_origination_reset()['counts']
        with self.assertRaisesRegex(OriginationGodModeError, 'Superuser'):
            reset_all_origination_data(
                actor=self.staff, reason='Synthetic test cleanup',
            )
        self.assertEqual(preview_full_origination_reset()['counts'], before)

    @override_settings(ORIGINATION_FULL_RESET_ENABLED=False)
    def test_full_reset_endpoint_is_disabled_by_default(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse('admin:core_origination_full_reset'))
        self.assertEqual(response.status_code, 403)

    @override_settings(ORIGINATION_FULL_RESET_ENABLED=True)
    def test_full_reset_endpoint_rejects_non_superuser(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('admin:core_origination_full_reset'))
        self.assertEqual(response.status_code, 403)

    @override_settings(ORIGINATION_FULL_RESET_ENABLED=True)
    def test_full_reset_requires_reason_and_exact_phrase(self):
        self.client.force_login(self.superuser)
        url = reverse('admin:core_origination_full_reset')
        before = preview_full_origination_reset()

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'RESET ALL ORIGINATION DATA')
        self.assertContains(response, 'Google Drive files will remain')
        self.assertContains(response, str(before['total']))

        response = self.client.post(url, {
            'confirmation': 'RESET ORIGINATION',
            'reason': 'Clear synthetic data',
            'request_id': 'wrong-confirmation',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'exact confirmation phrase')
        self.assertEqual(preview_full_origination_reset()['counts'], before['counts'])

        response = self.client.post(url, {
            'confirmation': 'RESET ALL ORIGINATION DATA',
            'reason': '',
            'request_id': 'missing-reason',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Provide a reason')
        self.assertEqual(preview_full_origination_reset()['counts'], before['counts'])

    @override_settings(ORIGINATION_FULL_RESET_ENABLED=True)
    def test_full_reset_clears_only_origination_and_is_retry_safe(self):
        self.client.force_login(self.superuser)
        url = reverse('admin:core_origination_full_reset')
        before = preview_full_origination_reset()
        self.assertTrue(before['total'])
        self.assertEqual(before['counts']['core.OriginationReviewerNotice'], 1)

        response = self.client.post(url, {
            'confirmation': 'RESET ALL ORIGINATION DATA',
            'reason': 'Removing complete synthetic Origination setup',
            'request_id': 'full-reset-test',
        })
        self.assertRedirects(response, url)
        self.assertEqual(preview_full_origination_reset()['total'], 0)

        self.assertTrue(Product.objects.filter(pk=self.global_product.pk).exists())
        self.assertTrue(ProductVersion.objects.filter(pk=self.global_product_version.pk).exists())
        self.assertTrue(OperationalLocation.objects.filter(pk=self.location.pk).exists())
        self.assertTrue(get_user_model().objects.filter(pk=self.superuser.pk).exists())

        # A repeated network submission is harmless and remains successful.
        response = self.client.post(url, {
            'confirmation': 'RESET ALL ORIGINATION DATA',
            'reason': 'Removing complete synthetic Origination setup',
            'request_id': 'full-reset-test',
        })
        self.assertRedirects(response, url)
        self.assertEqual(preview_full_origination_reset()['total'], 0)

    def test_full_reset_rolls_back_every_delete_when_one_step_fails(self):
        before = preview_full_origination_reset()['counts']
        real_delete = origination_god_mode._delete
        call_count = 0

        def fail_during_reset(queryset, counts):
            nonlocal call_count
            call_count += 1
            result = real_delete(queryset, counts)
            if call_count == 4:
                raise RuntimeError('Injected reset failure')
            return result

        with patch.object(origination_god_mode, '_delete', side_effect=fail_during_reset):
            with self.assertRaisesRegex(RuntimeError, 'Injected reset failure'):
                reset_all_origination_data(
                    actor=self.superuser, reason='Rollback test',
                )
        self.assertEqual(preview_full_origination_reset()['counts'], before)

    @override_settings(ORIGINATION_FULL_RESET_ENABLED=True)
    def test_sidebar_reset_link_is_visible_only_to_active_superuser(self):
        from core.admin_navigation import get_admin_navigation

        request = RequestFactory().get('/admin/')
        request.user = self.superuser
        navigation = get_admin_navigation(request)
        reset_items = [
            item
            for group in navigation
            for item in group.get('items', [])
            if item.get('title') == 'Reset all Origination data'
        ]
        self.assertEqual(len(reset_items), 1)
        self.assertTrue(reset_items[0]['permission'](request))

        request.user = self.staff
        self.assertFalse(reset_items[0]['permission'](request))

    @override_settings(ORIGINATION_FULL_RESET_ENABLED=True)
    def test_admin_sidebar_renders_reset_link_when_enabled(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse('admin:index'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Reset all Origination data')

    @override_settings(ORIGINATION_FULL_RESET_ENABLED=False)
    def test_admin_sidebar_hides_reset_link_when_disabled(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse('admin:index'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Reset all Origination data')
