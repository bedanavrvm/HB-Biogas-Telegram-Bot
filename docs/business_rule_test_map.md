# Business rule to test map

This is the maintained map for rules changed in the current release. Add a
row in the same change as every new policy, approval, transition, financial,
or retry rule; code coverage alone is not sufficient evidence.

| Rule | Allowed-path test | Denied/failure-path test |
|---|---|---|
| Mini App retry key compatibility | `core.tests_reliability.MiniAppRequestIdentityTests.test_header_key_is_bound` | `test_strict_mode_rejects_missing_key` |
| TAT state update replay identity | `core.tests_reliability.MiniAppWritePolicyTests.test_tat_update_accepts_header_retry_key` | `test_tat_update_rejects_invalid_retry_key` |
| Complaint/SPIN retry compatibility | `core.tests_reliability.MiniAppWritePolicyTests.test_complaint_and_spin_accept_legacy_clients` | `test_strict_mode_rejects_legacy_client_for_each_workflow` |
| Bounded external retry/circuit | `core.tests_reliability.ExternalResilienceTests.test_transient_failure_retries_then_succeeds` | `test_circuit_opens_and_blocks_calls` |
| No false external success | `core.tests_reliability.ExternalResilienceTests.test_terminal_failure_is_dead_lettered` | `test_non_transient_error_is_not_retried` |
| Protected stored-state readiness | `core.tests_reliability.ReadinessTests.test_authorized_readiness_uses_no_outbound_call` | `test_readiness_requires_manual_api_token` |

Existing workflow-specific guard, transition, and capability suites remain in
`core/tests_pipeline.py`, `core/tests_tat_tracker.py`, `core/tests_spin_credit.py`,
`core/tests_order_approval.py`, and `core/tests_workflow_capabilities.py`.
