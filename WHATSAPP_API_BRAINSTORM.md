# WhatsApp API Brainstorm

Created: 2026-04-30  
Context: current system receives tagged Telegram messages, parses complaint cases, stores them in Django, and syncs with Google Sheets as source of truth.

## Short Answer

Using the official WhatsApp Business Platform / Cloud API is attractive if the goal is to receive cases directly from customers or field staff through WhatsApp 1:1 chats. It is less attractive if the current workflow depends on internal group-chat reporting, because the official Cloud API is built around business-to-user conversations, webhooks, templates, and phone-number based messaging, not reading arbitrary WhatsApp group messages.

Best likely use:

- Customer or agent sends a case to one official WhatsApp business number.
- Meta sends our backend a webhook.
- We parse the message using the same parser.
- We write to Google Sheets and Django.
- We optionally reply with acknowledgement, case ID, status, or missing-field prompts.

Worst likely use:

- Trying to replace Telegram group intake with a WhatsApp group bot that reads all group messages. The official API is not designed for that. Unofficial WhatsApp Web automation libraries may appear to solve it, but they carry ban, reliability, and compliance risk.

## What We Can Do

### Receive Customer/Agent Messages

With Cloud API webhooks, we can receive inbound messages sent to the WhatsApp business number. This fits complaint intake well:

- free-form text
- images
- voice notes or documents if we choose to support media
- location shares
- contact details
- message status callbacks

Backend impact:

- Add a WhatsApp webhook endpoint, similar to the existing Telegram webhook.
- Normalize inbound WhatsApp payloads into the same internal `RawMessage` / parser path.
- Keep Google Sheets sync exactly as it is.

### Send Replies

We can send:

- acknowledgement replies when a case is created
- missing-field prompts such as "Please send customer phone number"
- status updates
- escalation messages
- structured quick replies/buttons, depending on message type and UI needs

Important distinction:

- Within the customer service window, free-form replies are allowed.
- Outside that window, we generally need approved message templates.

### Use Templates for Outbound Notifications

Templates are useful for:

- "Your complaint has been received"
- "Technician assigned"
- "Visit scheduled"
- "Complaint resolved"
- "Please rate the service"

They are not ideal for highly variable, free-form outreach unless the template is designed carefully and approved.

### Improve Data Quality

WhatsApp could improve intake because we can guide users interactively:

- ask one missing field at a time
- validate phone/account number immediately
- show buttons for complaint category
- confirm extracted case summary before saving
- request location/image only when needed

This is a major advantage over parsing messy group messages.

## What We Cannot Reliably Do

### Read WhatsApp Group Chats Like a Telegram Bot

The official WhatsApp Business Platform is not a general WhatsApp group bot API. If the current workflow is "staff post cases in a group and tag the bot", WhatsApp API is not a direct equivalent.

Possible alternatives:

- Keep Telegram for staff group intake.
- Use WhatsApp 1:1 intake for customers and field agents.
- Create a WhatsApp "dispatcher number" where staff forward/send cases directly.
- Build a web/mobile form for staff and use WhatsApp only for customer-facing communication.

### Freely Message Anyone Anytime

WhatsApp requires business messaging rules:

- users must have opted in for certain outbound messages
- free-form business replies are constrained by the customer service window
- outbound notifications need approved templates
- template category affects cost
- spammy or low-quality messaging can affect limits/quality

### Avoid Meta/BSP Policy Dependency

With WhatsApp API, Meta becomes part of the critical path:

- account review/business verification
- template approval
- rate limits and quality ratings
- policy changes
- pricing changes
- phone number restrictions

### Use It as a General-Purpose AI Assistant Channel

Meta has introduced policy changes aimed at AI providers/general-purpose assistants on WhatsApp Business Platform. A business-specific support bot for complaint intake is a different use case, but we should avoid positioning the product as a general chatbot on WhatsApp.

## What We Gain

### Better User Adoption

WhatsApp is already familiar to customers and field teams. This could reduce training and increase direct reporting.

### Cleaner Intake Flow

Instead of relying only on heuristics, we can move toward guided collection:

1. User sends complaint.
2. Bot extracts fields.
3. Bot asks only for missing fields.
4. Bot confirms case summary.
5. Backend writes a complete case.

### Direct Customer Communication

Telegram is mostly an internal/staff workflow. WhatsApp gives us a customer-facing channel:

- customer receives case ID
- customer can send photos/location
- support can follow up directly
- resolution confirmation can happen in the same thread

### Better Audit Trail

The backend can store:

- WhatsApp message IDs
- delivery/read status
- customer replies
- timestamps
- media references

This is cleaner than relying on staff to relay everything through a group.

### Fewer Parser Edge Cases Over Time

The current parser has to infer names, IDs, phones, complaint descriptions, and case boundaries from inconsistent text. WhatsApp 1:1 automation can ask structured follow-up questions and reduce ambiguity.

## What We Lose

### Group-Based Operational Visibility

Telegram group intake gives everyone visibility. WhatsApp 1:1 intake is private by default. We would need a dashboard, Google Sheet, or notification channel to replace the "everyone sees the case arrive" effect.

### Simplicity

Current Telegram integration is simple:

- tagged bot messages
- webhook
- parse
- sync to sheet

WhatsApp API adds:

- Meta Business setup
- WABA setup
- permanent tokens/system users
- phone number management
- webhook verification
- template management
- pricing management
- policy compliance

### Fast Experimentation

Telegram bots are flexible. WhatsApp production flows require more setup and often template approval before outbound use.

### Informal Batch Reporting

Staff can dump multiple cases into Telegram. WhatsApp 1:1 can support batch text, but the better WhatsApp-native pattern is one guided case at a time. Batch parsing can remain, but it is not the strongest use of WhatsApp.

## Advantages

- Customers already use WhatsApp.
- Better for direct support and follow-up.
- Supports media/location-rich complaint evidence.
- Webhooks fit the existing backend architecture.
- Can reuse the parser, storage, deduplication, and Sheets sync.
- Can reduce messy parsing by asking follow-up questions.
- Can provide immediate confirmation and case IDs.
- Better delivery/read status than Telegram group scraping.
- More professional customer-facing channel.

## Disadvantages

- Official API does not replace a Telegram-style group bot.
- Costs are variable and country/category dependent.
- Requires opt-in and template discipline.
- More vendor/platform dependency.
- Template approval can slow changes.
- Account quality or policy problems can disrupt messaging.
- Implementation and operations are heavier.
- Existing WhatsApp number may need migration rules; a number used on the normal WhatsApp app cannot simply be used freely as an API number without considering registration/migration.
- Staff may lose the convenience of one shared group unless we build dashboard/notifications.

## Cost Model

As of current 2026 references, Meta pricing is centered on delivered template messages, with rates depending on:

- recipient country/calling code
- template category
- message volume tier
- whether the message is inside a free customer service/free entry window
- whether a BSP/vendor adds markup or monthly platform fees

Typical categories:

- Marketing: promotions, campaigns, upsells; usually highest cost.
- Utility: transactional/status updates; usually lower cost.
- Authentication: OTPs/verification.
- Service/customer support: customer-initiated free-form replies inside the allowed window are generally free.

Important current pricing points to verify before build:

- Meta's official rate card effective date.
- Kenya-specific USD rates for utility, marketing, authentication, and service/referral if applicable.
- BSP markup, if not using Cloud API directly.
- Monthly platform fee if using Twilio, 360dialog, WATI, MessageBird, etc.
- Whether all our messages are inbound/support replies or whether we need outbound templates.

### Cost Scenarios

#### Scenario A: Inbound-only complaint intake

Customers/agents message us first. Bot replies within the customer service window.

Expected cost:

- lowest
- mostly engineering/hosting
- minimal Meta messaging fees if replies stay within free windows
- possible BSP monthly fee if using a provider

Operationally this is the best fit.

#### Scenario B: Inbound intake plus case updates

User sends complaint; we later send technician assigned/resolved messages.

Expected cost:

- moderate
- status updates outside the service window likely need utility templates
- costs scale with number of delivered template messages

#### Scenario C: Proactive outreach/campaigns

Business initiates messages to customers.

Expected cost:

- highest
- requires opt-in
- may be marketing category
- quality/spam risk is higher

## Architecture Option

### Keep Current System, Add WhatsApp as Another Inbound Channel

Recommended first design:

```text
WhatsApp Cloud API webhook
        |
        v
Normalize inbound payload
        |
        v
Existing parser
        |
        v
RawMessage + ParsedMessage
        |
        v
Google Sheets sync
        |
        v
Optional WhatsApp acknowledgement
```

This avoids rewriting the backend. Telegram remains available. WhatsApp becomes an additional source.

### New Components Needed

- `WhatsAppWebhookView`
- webhook verification token handling
- signature validation if supported/required in our setup
- WhatsApp message normalizer
- media download service
- outbound message service
- template registry/config
- delivery status tracking
- opt-in tracking if outbound messaging is used
- environment variables for WABA ID, phone number ID, access token, verify token

## Parser Impact

WhatsApp does not eliminate parsing on day one. People will still send messages like:

```text
Henry Mwenda
24289449
0720809218/0726011961
Requesting for a jiko relocation
```

But WhatsApp lets us improve reliability with guided repair:

- If no phone: ask for phone.
- If no name: ask for customer name.
- If no description: ask "What is the issue/request?"
- If multiple possible IDs: ask user to confirm.
- If all required fields exist: create case immediately.

This shifts the system from "parse perfectly or fail silently" to "parse what we can, then ask for the missing field."

## Data Model Impact

Suggested additions:

- `source_channel`: `telegram`, `whatsapp`, `manual`, etc.
- `source_message_id`: WhatsApp `wamid...`
- `source_chat_id` / `wa_id`
- `customer_wa_id`
- `conversation_state`
- `last_customer_message_at`
- `last_outbound_template_at`
- `delivery_status`
- `template_name`
- `template_category`

## Sheet Impact

Google Sheets can remain source of truth. Add optional columns only if useful:

- Source Channel
- WhatsApp Message ID
- WhatsApp Phone/WA ID
- Last Reply Status

But avoid changing the sheet unless we need the extra visibility. The current backend can map WhatsApp messages into the same existing columns.

## Compliance / Policy Watchpoints

- Make opt-in explicit if sending outbound templates.
- Keep message templates specific and non-spammy.
- Avoid unofficial WhatsApp Web scraping/automation.
- Avoid presenting this as a general-purpose AI assistant.
- Store only necessary personal data.
- Decide retention period for raw messages/media.
- Be careful with customer IDs and phone numbers in logs.

## Migration Strategy

### Phase 1: Feasibility Spike

- Create a Meta test app/WABA.
- Configure Cloud API webhook locally/staging.
- Receive a simple inbound text.
- Normalize it into existing parser.
- Write to test Google Sheet.
- Send a basic acknowledgement.

Success criteria:

- one inbound WhatsApp message creates exactly one backend case and one sheet row
- deduplication works
- failure states are visible

### Phase 2: Pilot with Staff

- Use one WhatsApp business number.
- Ask 3-5 staff to send real-world case formats directly to the number.
- Keep Telegram running in parallel.
- Compare parser accuracy and operational friction.

Success criteria:

- at least same extraction accuracy as Telegram
- fewer missing required fields due to follow-up prompts
- no silent sync failures

### Phase 3: Customer-Facing Intake

- Add opt-in language.
- Add template acknowledgements/status updates.
- Add dashboard or Telegram notification for new WhatsApp cases.

Success criteria:

- customers can submit and receive case IDs
- staff still have operational visibility
- cost per case is understood

## Decision Matrix

| Question | WhatsApp API Fit |
|---|---|
| Direct customer complaint intake | Strong |
| Staff 1:1 case submission | Strong |
| Internal group bot replacement | Weak |
| Structured follow-up for missing fields | Strong |
| Bulk informal case dumps | Medium |
| Proactive marketing/campaigns | Possible but costly/risky |
| Low-cost experimentation | Weaker than Telegram |
| Professional customer-facing channel | Strong |

## Recommendation

Do not replace Telegram immediately.

Best next step is to add WhatsApp as a second inbound channel and run a pilot. Keep Telegram for internal group workflows, while WhatsApp handles direct staff/customer submissions. If the pilot shows WhatsApp gives cleaner data and better follow-up, we can gradually move intake there.

The key product decision:

- If the goal is internal staff batch reporting: stay with Telegram or build a staff form.
- If the goal is customer/agent direct case intake and follow-up: WhatsApp API is worth piloting.

## Open Questions

- Do we want customers to message directly, or only staff/agents?
- Do we need outbound status updates, or just inbound intake?
- Which WhatsApp number would be used?
- Are we okay losing group-chat visibility, or should new WhatsApp cases be mirrored into Telegram?
- Who owns Meta Business/WABA setup?
- Do we use Cloud API directly or a BSP?
- What is the expected monthly case volume?
- How many outbound template messages per case?
- Do we need media/location support in phase 1?

## Sources

- Meta WhatsApp Business Platform pricing: https://developers.facebook.com/docs/whatsapp/pricing/
- Meta Cloud API overview, Postman mirror/collection: https://www.postman.com/meta/a31742be-ce5c-4b9d-a828-e10ee7f7a5a3/documentation/wlk6lh4/whatsapp-cloud-api
- Meta pricing documentation mirror, updated 2026-03-30: https://support2.chatarchitect.com/books/meta-whatsapp/page/pricing-on-the-whatsapp-business-platform-developer-documentation
- Meta AI provider policy documentation mirror, updated 2026-03-04: https://support2.chatarchitect.com/books/meta-whatsapp/page/new-pricing-policy-for-ai-providers-leveraging-the-whatsapp-business-platform-developer-documentation
- Meta pricing update references and rate-card effective date discussion: https://cloudfon.atlassian.net/wiki/spaces/CX/pages/535232517/Pricing%2Bupdates%2Bon%2Bthe%2BWhatsApp%2BBusiness%2BPlatform
