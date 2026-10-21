# Daraja phone / National ID check diagnostics

Researched: 21 October 2026. External-source scope: official Safaricom/Daraja public documentation only, with a separately labelled repository mapping check. No login, credentials, customer data, provider verification calls, or application changes were used.

## Findings

Daraja has an official support and incident channel. Safaricom's Authorization documentation lists the Daraja chatbot, an Incident Management page, and `apisupport@safaricom.co.ke`. The M-Pesa Express documentation also explicitly directs developers to raise an incident through self-services. These establish an escalation route; they do not establish that the account dashboard exposes a detailed log of every Mobile Number Validation call. [Authorization: Support](https://developer.safaricom.co.ke/apis/Authorization), [M-Pesa Express: Go Live and Support](https://developer.safaricom.co.ke/apis/MpesaExpressSimulate).

No public official documentation located in this investigation confirmed a per-request log viewer specifically for Mobile Number Validation / `POST /v1/KYC-validation/validateID`. Its existence, current menu label, visibility by account, retained fields, retention period, and access to backend mismatch reasons remain unverified. Do not tell an operator to use a presumed "API Logs" or "Transactions" menu.

## What can and cannot be inferred

| Question | Evidence and limit |
| --- | --- |
| Can Safaricom investigate a request? | An official incident/support route exists. Ask support whether they can trace the specific KYC request; public material did not establish the exact trace fields required. [Authorization](https://developer.safaricom.co.ke/apis/Authorization). |
| Does a Django access-log HTTP 200 prove that the phone and ID match? | No. That status belongs to the application's endpoint. The supplied access line contains no provider result; this is a protocol-boundary inference, not a claim about Safaricom's KYC contract. |
| Is sandbox equivalent to a real subscriber lookup? | Safaricom describes sandbox apps and simulation. Its Transaction Status documentation describes predefined simulator test data and separate sandbox/production hosts. That is general environment evidence, not confirmation of which KYC phone/ID pairs exist or how arbitrary real pairs behave in the KYC sandbox. [Daraja home](https://developer.safaricom.co.ke/), [Transaction Status: Testing](https://developer.safaricom.co.ke/apis/TransactionStatus). |
| Is `4000` with `status=true` a match, and `4001` with `status=false` a mismatch? | This exact KYC response-code/status contract could not be independently verified from public official material in this investigation. Local adapter rules and unit tests are separate evidence, not provider documentation. Do not generalize payment API success/error codes to this API. |
| Can Transaction Status Query diagnose the KYC lookup? | Its official documentation describes M-PESA transactions and receipt/originator-conversation identifiers. It does not document KYC phone/ID lookups as a supported use. [Transaction Status: Overview and FAQs](https://developer.safaricom.co.ke/apis/TransactionStatus). |

Repository behavior, independently of the official contract: `origination/services/daraja_phone_identity.py:71` accepts only the consistent combination `responseCode='4000'` plus true as `matched`, or `responseCode='4001'` plus false as `not_matched`; other combinations become `unavailable`. It reads `responseRefID`. This source check establishes how this application interprets responses, not that Safaricom currently guarantees that contract.

## Existing project diagnostics

- `config/settings.py` defaults `DARAJA_ENVIRONMENT` to `sandbox`. The deployed Render value was not inspected. An application being online on Render does not establish that it calls the production provider host.
- `origination/services/phone_identity.py::_admit` reuses both matches and mismatches for thirty days. `_receipt` returns `reused`, `checked_at`, `reusable_until` and an application-local `receipt_id`; the receipt ID is not the provider request reference. The Mini App adds a Reused label when applicable. Repeating an app request does not establish that Safaricom was contacted again.
- `OriginationPhoneIdentityCheck` retains the safe `provider_code`, `provider_response_ref`, dispatch/completion times and attempt UUID. The adapter sends that UUID as `requestRefID`. Raw provider response bodies are deliberately not retained.
- Django Admin's **Integration operations** list can be filtered by integration `daraja` and operation type `origination_phone_identity`. Its `source_id` is the attempt/request reference, and its detail includes request identity and execution metadata. A successful operation is not proof of a positive match. The separate phone-check evidence model is not registered in Admin, so do not promise that the operation page displays its provider code or response reference. Retrieving those requires a narrowly scoped read-only evidence lookup or a separately approved diagnostics interface.
- Read-only validation: `manage.py test origination.tests_phone_identity.AdapterTests --noinput --verbosity 1` passed all four synthetic adapter tests. All provider HTTP is mocked. This checks the existing parsing/transport rules; it neither reproduces the reported live false negative nor independently validates Safaricom's response contract. No application code, evidence, cache or deployed settings changed.

## Practical investigation checklist

The following is an engineering recommendation, not an official Safaricom incident-submission contract:

1. Confirm the deployed `DARAJA_ENVIRONMENT` and actual provider hostname. A production-hosted Django service can still call the sandbox. This research did not inspect Render and cannot establish the deployed value.
2. Inspect the persisted check's original time, `requestRefID`, provider code and `responseRefID`, and whether the UI reused an earlier result. A reused mismatch would not produce a new provider call. Caching behavior must be confirmed from the local implementation; it is not documented here as Safaricom behavior.
3. Use the authenticated Daraja account's self-services incident route, or the official API-support email. Ask specifically whether Mobile Number Validation request traces are available in that account and whether support can inspect the request.
4. Prepare the API name/path, environment/host, timestamp with timezone, application name, business shortcode, internal `requestRefID`, provider `responseRefID` if returned, HTTP status, and redacted provider code/message. Preserve gateway `requestId` if an error provides one. These are suggested correlation details; support must confirm which identifiers it uses for this KYC API. Safaricom's B2C documentation independently illustrates gateway `requestId` in errors, without establishing the KYC response shape. [B2C: Sample Error Response](https://developer.safaricom.co.ke/apis/BusinessToCustomer).
5. Ask support to confirm the exact KYC code/status contract, required ID type and formatting, sandbox test-pair rules, production entitlement, and what the observed mismatch means. Share sensitive subscriber details only through the organization's approved private support process. Never send consumer secrets, access tokens, or credentials.

## Research limitations

Public search indexes exposed substantive official documentation, but several live pages returned a JavaScript shell to the reader. The guessed MobileNumberValidation page did not yield a readable official contract. No authenticated dashboard was inspected. A historical official newsletter mentioned incident management under Self Services, but its PDF returned 404 when opened; the current API documentation above supplies the usable support citation instead.

These findings establish the official support path and the uncertainty around dashboard logs. They do not establish the cause of any individual mismatch or verify live subscriber registration.
