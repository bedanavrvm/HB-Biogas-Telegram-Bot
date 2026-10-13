# Business rule to test map

This is the maintained map for rules changed in the current release. Add a
row in the same change as every new policy, approval, transition, financial,
or retry rule; code coverage alone is not sufficient evidence.

| Rule | Allowed-path test | Denied/failure-path test |
|---|---|---|
| TAT native export keeps current access and frozen period | `core.tests_tat_tracker.TatTrackerWorkflowTest.test_native_report_download_preserves_period_rechecks_actor_and_keeps_binary_clients` | Same test checks revoked access/tampering; `core.tests_tat_report_presentation.TatReportPresentationPolicyTests.test_download_token_hides_filters_and_rejects_expiry_and_tampering` |
| BRO corrections use current explicit roster without rewriting history | `core.tests_tat_tracker.TatTrackerWorkflowTest.test_bro_correction_resolves_identity_and_preserves_history` | Same test rejects removed/unknown BROs; `test_it_bootstrap_keeps_explicit_bro_roster_without_inventing_it_assignment` |
| Personal task counts and paging | `core.tests_tat_notifications.TatPrivateTaskTests.test_personal_inbox_api_pages_ten_and_read_count_is_not_total` | Same test checks invalid paging; browser `personal inbox pages ten, preserves rows on failure and hides a zero unread badge` |
| Mini App retry key compatibility | `core.tests_reliability.MiniAppRequestIdentityTests.test_header_key_is_bound` | `test_strict_mode_rejects_missing_key` |
| TAT state update replay identity | `core.tests_reliability.MiniAppWritePolicyTests.test_tat_update_accepts_header_retry_key` | `test_tat_update_rejects_invalid_retry_key` |
| TAT private delivery is idempotent | `core.tests_tat_notifications.TatPrivateTaskTests.test_concurrent_safe_dispatch_does_not_repeat_a_delivered_prompt` | `test_revoked_primary_scope_hides_task_and_soft_escalates_delivery` |
| TAT notification runner overlap lease | `core.tests_tat_notifications.TatPrivateTaskTests.test_notification_processor_records_success_and_releases_lock` | `test_notification_processor_skips_an_overlapping_run`, `test_notification_processor_recovers_an_expired_lock` |
| TAT production gate | `core.tests_tat_production.TatProductionReadinessTests.test_readiness_command_supports_json_success` | `test_group_requires_sheet_contract_access_and_responsibility_coverage`, `test_telegram_auth_cannot_be_disabled` |
| Complaint/SPIN retry compatibility | `core.tests_reliability.MiniAppWritePolicyTests.test_complaint_and_spin_accept_legacy_clients` | `test_strict_mode_rejects_legacy_client_for_each_workflow` |
| Bounded external retry/circuit | `core.tests_reliability.ExternalResilienceTests.test_transient_failure_retries_then_succeeds` | `test_circuit_opens_and_blocks_calls` |
| No false external success | `core.tests_reliability.ExternalResilienceTests.test_terminal_failure_is_dead_lettered` | `test_non_transient_error_is_not_retried` |
| Protected stored-state readiness | `core.tests_reliability.ReadinessTests.test_authorized_readiness_uses_no_outbound_call` | `test_readiness_requires_manual_api_token` |

Existing workflow-specific guard, transition, and capability suites remain in
`core/tests_pipeline.py`, `core/tests_tat_tracker.py`, `core/tests_spin_credit.py`,
`core/tests_order_approval.py`, and `core/tests_workflow_capabilities.py`.
