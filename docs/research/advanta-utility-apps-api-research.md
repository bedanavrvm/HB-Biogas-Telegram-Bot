# Advanta Utility Apps credentials and Origination SMS

Research date: 16 October 2026. Scope: public, read-only first-party API material; no customer credentials, SMS requests, account changes or production access.

## Finding

The supplied screen is a real Advanta **Utility Apps** credential screen. Its APP KEY / APP TOKEN and one-time token-generation behaviour match Advanta's published Utility Apps authentication instructions. That is not evidence that the user created the wrong application. The verified public example of this authentication is **Airtime**, not transactional SMS. [Advanta Airtime API](https://developers.advantasms.com/airtime-api/)

The public SMS documentation and the **actual downloadable collection linked by that documentation** still describe a separate `apikey` / `partnerID` contract. No Utility Apps SMS/OTP request or conversion from App Name, App Key or App Token to Partner ID was found in those sources. Absence from these sources is not proof that Advanta cannot enable such access. [Advanta SMS API](https://developers.advantasms.com/sms-api/), [officially linked SMS collection](https://www.postman.com/collections/25262064-a68bb57b-3829-425f-bae7-337ca678e2c5)

Accordingly, do not change the existing adapter to guessed v3 URLs or treat the App Token as a Partner ID. Also do not categorically describe Utility Apps as the wrong interface: the available evidence establishes its authentication contract, not every service it can authorize.

## Verified contracts

### Utility Apps

The official instructions locate credentials under QuickSMS -> Utility Apps -> app -> Settings. They specify these request headers:

```http
Content-Type: application/json
App-Key: <server-side app key>
App-Token: <server-side app token>
```

The documented operation is `POST https://{{url}}/api/v3/airtime/send`, with `recipients[]` containing a recipient and monetary amount. It distributes airtime; it is not a text-message operation. The page does not establish a corresponding `/api/v3/sms/send` or OTP route. Token generation displays the token once and invalidates existing tokens. [Advanta Airtime authentication and endpoint](https://developers.advantasms.com/airtime-api/)

The linked code samples are incomplete: they use `/api/endpoint` placeholders and omit the App-Key/App-Token headers specified by the same page. They cannot be copied as a working SMS client. [published documentation source](https://github.com/harrykerry/advanta-africa-apis/blob/master/docs/airtime-api/README.md)

### Published SMS and OTP

The SMS account credentials are `apikey`, `partnerID` and `shortcode` (the Sender ID). The documentation describes obtaining these through Partners; the older marketing page instead describes a button that retrieves both credentials. Neither explanation establishes where a restricted end-user account sees this control. Repeating the Partners instruction does not solve an account whose menu lacks it. [SMS credential instructions](https://developers.advantasms.com/sms-api/), [Advanta Bulk SMS API](https://www.advanta.africa/bulk-sms-api)

Transactional OTP sending is documented as JSON POST to `https://quicksms.advantasms.com/api/services/sendotp`, with `apikey`, `partnerID`, `mobile`, `message` and `shortcode`. Delivery lookup is a separate authenticated request with the resulting message identifier. The sender must still supply the OTP message; this is not a documented service that generates and verifies the OTP for the application. [Send OTP](https://developers.advantasms.com/sms-api/send-otp.html), [Delivery Reports](https://developers.advantasms.com/sms-api/delivery.html)

## Investigation beyond the landing pages

### Officially linked Postman collection

The rendered SMS page hides its collection URL behind an image link. Reading its HTML exposes collection `25262064-a68bb57b-3829-425f-bae7-337ca678e2c5`, workspace `a4f7eece-9e44-4c3d-bae1-c2e1057c8919`. The public workspace belongs to **Advanta API Team**; provenance is the link from Advanta's own documentation, not an assumption that every similarly named Postman account is official. [public workspace](https://www.postman.com/advantaapis/sms-apis/overview), [collection view](https://www.postman.com/advantaapis/sms-apis/collection/1jkm18s/sms-api)

Downloaded the public collection JSON and inspected all ten request definitions. None sends App-Key/App-Token headers or calls a v3 endpoint:

| Request group | Defined methods | Path |
| --- | --- | --- |
| Bulk messages | POST | `/api/services/sendbulk/` |
| Messages | GET, POST | `/api/services/sendsms/` |
| Delivery reports | GET, POST | `/api/services/getdlr/` |
| Balance | GET, POST | `/api/services/getbalance/` (GET has `index.php`) |
| Hashed/OTP labels | one GET, two POST | `/api/services/sendotp/` |

The collection repeats the `apikey` / `partnerID` authentication fields. Two raw OTP examples do not parse as strict JSON, so their raw bodies are not a trustworthy drop-in implementation. These are inspection results from the collection retrieved on the research date; they do not describe private or future collections. [public collection JSON](https://www.postman.com/collections/25262064-a68bb57b-3829-425f-bae7-337ca678e2c5)

The workspace metadata lists only that collection. Its profile publicly features one SMS workspace, so there was no second public Advanta-owned Utility Apps SMS collection to follow from this source. [workspace](https://www.postman.com/advantaapis/sms-apis/overview), [publisher profile](https://www.postman.com/advantaapis)

### Published documentation source

The public documentation names contributor `harrykerry`. That contributor's `advanta-africa-apis` repository contains the corresponding VuePress material, including the Utility Apps Airtime instructions and legacy SMS pages. It corroborates the rendered contract rather than revealing a newer SMS contract. No claim is made that this repository includes Advanta's private server implementation. [documentation source repository](https://github.com/harrykerry/advanta-africa-apis)

## Repository impact

Inspected the current local `origination/services/origination_sms.py` and `config/settings.py`. The implemented Advanta transport calls `sendotp` under `/api/services`, using `ORIGINATION_ADVANTA_API_KEY`, `ORIGINATION_ADVANTA_PARTNER_ID` and `ORIGINATION_ADVANTA_SENDER_ID`. It has no App-Key/App-Token mode. The current integration therefore matches the verified published SMS contract but is **not established as compatible with the Utility Apps credentials the user actually has**.

No application code or configuration was changed by this research. The API documentation mismatch is not a reason to alter OTP verification, signature evidence, authorization, existing signing-link provider binding or retry rules.

## Bounded conclusion and next evidence

What is now established:

- The user's described fields match documented Utility Apps credentials; no screenshot is needed to recognize that interface.
- App Name is a label, not a documented Partner ID.
- App-Key/App-Token are real authentication headers for the documented Airtime operation.
- Public SMS docs, public Postman requests and corresponding documentation source all expose the other authentication contract.
- There is not enough verified public evidence to implement Utility Apps SMS by renaming environment variables.

What remains unverified is narrowly defined: an SMS/OTP endpoint accepting the Utility Apps headers; its request and response shape; whether that app is enabled for transactional SMS; and the delivery-report authentication contract. The user should not have to rediscover the API. If Advanta exposes an account-specific API example or documentation link, inspect that contract; otherwise ask the provider for those exact details, without rotating or disclosing the current token. This is a provider-contract gap after public research, not a request for the user's secrets.

Once an authoritative contract is obtained, adapt only the transport, add fixture-based tests for its actual acknowledgement and delivery responses, and retain Django-owned OTP verification and uncertain-send protections. A real handset test would be a separate explicitly authorized action. Do not probe guessed transactional endpoints to discover the contract.
