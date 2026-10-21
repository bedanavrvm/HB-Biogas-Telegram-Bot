# Safaricom integration opportunities: operational workflows first

Researched: 19 October 2026. Scope: public, first-party Safaricom documentation only. No account access, production requests, payments, credentials or customer data were used. This note distinguishes an advertised capability from JBL's actual entitlement; no JBL shortcode, settlement arrangement or API product assignment was verified.

## Recommendation in brief

**Confirmed scope boundary:** the owner deliberately excluded actual money transactions and core-banking financial functionality while developing the operational workflows. This is not an implementation defect or unfinished feature to close automatically. Moving money, changing a loan balance or allocating a repayment needs a separately approved financial-integration programme, qualified finance/core-banking input and a properly established operating model.

**Correction after owner feedback:** even an observation-only payment proposal still centres financials too heavily. The immediate question should be **"Which communication, access and security services would make our existing operational workflows easier?"** The payment research below remains a future-reference appendix, not the recommended starting point.

Start by improving customer communication and completing operational follow-ups with the existing providers. Investigate USSD or a two-way customer channel only where real customer access/reply needs justify another channel. Evaluate fraud signals separately; do not force a Daraja integration just because an API exists.

Everything below is research/proposal, not an approved change to workflow, access, financial policy, infrastructure or deployment. Current API availability does not establish JBL's entitlement. No money handling is proposed for the current operational project.

## Keep the service boundaries honest

| Category | What was established | What it means for us |
| --- | --- | --- |
| Ordinary Daraja payment catalogue | The public catalogue is predominantly payment-oriented. | Do not invent complaint-management, general SMS, GPS or document-signing APIs to make it sound broader. [Catalogue](https://developer.safaricom.co.ke/apis) |
| Non-payment Daraja capability | IoT SIM management has an actual documented API, tied to the customer's purchased IoT service. | Relevant to a future connected-equipment programme, not arbitrary customer/staff SIM lookup. [IoT SIM Management](https://developer.safaricom.co.ke/apis/IotSimManagement) |
| Daraja-linked security offering | Safaricom's fraud-intelligence announcement describes SIM-swap-related risk checks for financial institutions through Daraja. | Potential signing/account-security enhancement; current contract, endpoint and JBL eligibility still need confirmation. [Official announcement](https://www.safaricom.co.ke/media-center-landing/press-releases/safaricom-launches-fraud-intelligence-solution-for-financial-sector) |
| Separate enterprise services | Official materials establish SMS/shortcode, USSD and sponsored-data services with their own provisioning. | They are not unlocked by our normal Daraja Consumer Key/Secret. Direct access, approved partner route and current callback/API contracts must be confirmed. [USSD request](https://www.safaricom.co.ke/images/Downloads/Resources_Downloads/VAS/USSD_Code_Application_Form.pdf), [PRS service material](https://www.safaricom.co.ke/images/Downloads/PRS-RATE-CARD.pdf), [Sponsored Data FAQ](https://www.safaricom.co.ke/media-center-landing/frequently-asked-questions/sponsored-data-solution) |
| Separate Mini Program platform | Safaricom documents a Mini Program development and release platform. | Could carry customer service without enabling money movement; it is another frontend and approval process, not a Daraja toggle. [Platform documentation](https://mpesaminiapps.safaricom.co.ke/docs) |

## Operational opportunities: benefits, trade-offs and timing

The following are proposed JBL features, not a claim that each is a separate Safaricom API. Reuse our existing Advanta/Africa's Talking and Telegram transports wherever they already meet the need.

| Opportunity | Concrete fit in our apps | Benefits | Trade-offs / boundaries | Timing |
| --- | --- | --- | --- | --- |
| **Customer acknowledgements and status messages** | Complaints: reference and next step. Portal: visit booked/rescheduled, missing documents, installation arrangements. Origination: signing invitation, withdrawal/change notice and completion confirmation. | Customers do not need Telegram to receive a short operational update; less chasing staff. | Use minimal necessary content, appropriate recipient/notification policy and a source-event deduplication key. Do not expose IDs or application decisions in an unsolicited lock-screen SMS. Existing providers may be sufficient. | Most useful now |
| **Visit reminders and availability replies** | Portal: remind a customer of an agreed visit; let them request a callback or reschedule through an approved reply channel. | Fewer wasted journeys and no-shows. | An alphanumeric sender ID is not automatically reply-capable. A reply is a request, not an immediately applied schedule change; date conflicts still need operational handling. | Reminders now; reply integration after channel setup |
| **Signing delivery and recovery** | Origination: distinguish invitation accepted by provider, delivery observed, link opened, OTP verified and signature saved. Reuse existing delivery evidence; improve only gaps. | Staff can see what to do next instead of repeatedly sending messages. | SMS delivery does not establish reading, identity or consent. Do not create overlapping OTP challenges or change a submitted link's provider automatically. | Most useful now; no new Daraja API needed |
| **Selective staff escalation** | TAT/Portal: an exceptional SMS to the authorised responsible staff member if an urgent task is not acknowledged through the existing private Telegram routing. | Helps when Telegram is missed without duplicating all notifications. | Respect each Mini App's independent role/scope. SMS delivered is not acknowledgement; avoid sending the full case or building a parallel assignment system. | Evaluate actual missed-notification need first |
| **Two-way complaint updates** | Customer sends a reference plus short follow-up, callback request or satisfaction response to a contracted reply-capable number/shortcode. | Feedback enters the existing complaint history instead of a staff member's personal inbox. | Need inbound routing, correlation, abuse controls and customer verification for sensitive details. Never auto-close or reopen from an unverified text. API/reply provisioning is separate from normal outbound SMS. | High-value candidate after outbound basics |
| **USSD complaint/status/callback service** | A short menu for reporting a basic issue, checking limited status or asking for a call without smartphone data. | Reaches feature-phone and low-data customers. | Still needs mobile coverage; sessions expire and cannot handle document viewing, ID photos or full application forms. Keep menus short and responses privacy-safe. Safaricom/CSP provisioning and current network/session terms must be established. | Investigate if the customer population needs it |
| **SIM-swap risk evidence** | Origination: extra context around a sensitive signing-link or saved-phone change; staff identity recovery where appropriate. | A different signal from successful delivery of an OTP to a potentially replaced SIM. | The service's announced existence is not proof JBL can call it today. No universal name/ID lookup; risk handling requires proportionate fallback, not another blanket setup blocker. | Conditional security research |
| **Customer callback / contact-centre linkage** | Complaints: request a human call and retain its outcome in case history; Portal: contact customer about visit/access issues. | Better assisted service for customers who struggle with forms or text. | Requesting a callback can be built in our app now. Automated dialling, call events or recordings need a separately verified telephony contract/API; no self-serve Daraja Voice API was established. Keep recording/retention decisions explicit. | Callback request now; telephony integration later |
| **Sponsored access to selected customer pages** | Explore sponsored data for public-to-authorised document-signing or simple service pages where data cost causes abandonment. | May reduce a real access barrier without changing the business workflow. | Official FAQ requires URL plus static IP and excludes third-party embedded resources from blanket coverage. Render hosting, external assets, Telegram and other origins need assessment; do not promise free Telegram or an entirely sponsored signing journey. Current provisioning must be reconfirmed. | Conditional; not a quick API switch |
| **Customer service inside an M-PESA Mini Program** | Complaint reporting/status, visit requests, document checklist and support content; no payment feature is required for the concept. | A possible customer channel while staff retain the existing Telegram Mini Apps. | Additional authentication, frontend/release maintenance and platform approval. Never assume Telegram grants or identities transfer, or port the staff UI unchanged. Validate distribution/eligibility first. | Longer-term customer-channel decision |
| **Connected equipment diagnostics** | If HB introduces supported devices, combine IoT SIM state with separately supplied equipment telemetry in a complaint/service case. | Can distinguish connectivity trouble from equipment faults and reduce unnecessary visits. | Requires owned/authorised IoT SIMs, hardware/partner telemetry and a service model. SIM connectivity does not prove gas production, installation, customer location or staff attendance. | Future hardware-dependent opportunity |
| **Customer feedback and support education** | After service, a short feedback request; targeted operational instructions about document capture or installation readiness. | Identifies unresolved issues and reduces repeat explanations. | Existing messaging may already suffice. Honour message preferences and frequency; do not treat a survey response as a formal complaint decision or marketing permission. | Useful now if a clear follow-up owner exists |

## Existing code to build on, not replace

- `origination/services/origination_sms.py` already supports `africas_talking` and `advanta`. A direct Safaricom SMS connection would be a third provider, not a new business capability by itself.
- `origination/services/origination_sms_delivery.py` already distinguishes provider submission and delivery evidence. Its existence is a reason to inspect and extend the current path, not build another generic delivery dashboard.
- `core/services/tat_notifications.py` already implements durable private-first task routing. A new communications channel must not become a second role/assignment engine.
- Complaint and Portal workflow services remain the owners of case transitions, visits and comments. An inbound SMS/USSD session is another authorised input channel, not another source of truth.

## Revised priority

1. **Now:** assess concrete customer communication gaps, reuse existing providers, and improve delivery/recovery and callback requests without new infrastructure.
2. **Next if justified:** compare a reply-capable SMS channel and a small USSD service for customer follow-up/access. Obtain the actual service and API terms; do not change SMS supplier merely to say we integrated Safaricom.
3. **Conditional:** investigate SIM-swap security eligibility and sponsored-data feasibility against the actual deployment.
4. **Later:** decide whether an additional customer Mini Program or connected-equipment support earns its maintenance cost.
5. **Separate future scope:** all payment initiation, refunds, financial posting and core-banking work described in the retained appendix below.

The right result may be **no new Daraja integration now**. A useful feature using an existing transport is better than an unnecessary new provider or customer channel.

## Questions to resolve before selecting a new service

1. Which customer updates are actually missing today, and which already work through Advanta, Africa's Talking or Telegram?
2. Do customers need a reply channel, a no-data enquiry channel, or simply clearer existing messages? Those are different problems.
3. Which provider can supply the specific inbound/outbound contract, sender/reply identity, coverage, delivery evidence and support we need?
4. For USSD, what menu is genuinely short enough to finish before timeout, and how will sensitive status enquiries be authenticated?
5. For SIM-swap intelligence, is JBL eligible today, what exact risk evidence is available, and what supported fallback applies when the check is unavailable?
6. For sponsored data, can our hosting and all required resources meet the account-specific network conditions? Telegram traffic must not be assumed covered.
7. Who owns follow-up, message preferences, abuse handling and deletion/retention for each new channel?

Safaricom's published PRS provider list, last updated June 2025, includes both Advanta Africa and AfricasTalking. This supports investigating our existing providers before introducing another connection; it does not prove every service or contract is enabled on our accounts. [Official provider list](https://www.safaricom.co.ke/personal/value-added-services/information-services/prs-providers)

## No new API required for these improvements

- Clickable phone numbers opening the dialler use normal phone links.
- A callback-request list and recorded call outcome can use our existing Django workflow.
- Better signing-page feedback, PDF navigation, form validation, camera controls and compact cards are application improvements, not Safaricom capabilities.
- Existing OTP generation/verification stays document-bound in Origination; a transport or network risk signal cannot replace it.

## How to judge an operational pilot

- Fewer missed visits and fewer manual reminder calls.
- Faster complaint acknowledgement and fewer enquiries asking only for status.
- More completed signing sessions, fewer duplicate invitations and clearer failed-delivery recovery.
- Useful customer replies reaching the right case and responsible staff, without leaking case details.
- Measured use and completion of any USSD menu, not merely its successful provisioning.
- No duplicate alerts, unauthorised workflow changes, role leakage or automatic customer-identity changes.
- Clear ownership and acceptable ongoing support effort for every added channel.

None of these benefits requires us to initiate payments, maintain loan balances or become a core-banking system.

## Brief future financial reference

The earlier research established payment APIs, but they are deliberately not this project's current focus:

- C2B and transaction queries could eventually support receipt evidence. [C2B](https://developer.safaricom.co.ke/apis/CustomerToBusiness), [Transaction Status](https://developer.safaricom.co.ke/apis/TransactionStatus).
- STK requests, business payments, B2C payouts and repayment posting would require separate financial scope, expertise and operating controls. Provider acceptance is not successful payment. [Express](https://developer.safaricom.co.ke/apis/MpesaExpressSimulate), [catalogue](https://developer.safaricom.co.ke/apis).
- B2C's current FAQ says API requests have no later manual portal approval and API reversal is unsupported. These are reasons for careful future design, not a call to implement payouts now. [B2C FAQ](https://developer.safaricom.co.ke/apis/BusinessToCustomer).

No financial project, new communications provider, schema change, deployment or live API action is authorised by this report.

## Research limits

The review used official public Safaricom pages and current local code. Some direct page/PDF opens returned HTTP 403; search-indexed versions supplied the cited content. Published service existence is not a current account entitlement or a verified integration. The fraud announcement is historical, and enterprise/USSD/SMS/sponsorship contracts must be reconfirmed before implementation.

No live account, phone, production endpoint, message, payment, callback registration or customer record was accessed or changed. Only research documentation was edited.
