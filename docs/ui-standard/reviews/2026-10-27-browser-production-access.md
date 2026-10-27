# Native production access handoff

The user authorized finishing real Complaints browser access. ADR 0075 records
the conditional production mount; deployment and real-account commissioning
remain separate. Reuse the existing StaffAccess ADS Form, Textfield, Button and
SectionMessage patterns. No Mini App migration, approved baseline or candidate
token changes are included.

`browser/src/staff-access.tsx` explains mailbox verification with an existing
password and how to open a separate browser session when Django Admin is signed
in. `auth-transport.ts` retains the username after mailbox-only verification,
accepts the server-owned setup completion state and preserves the Admin session.
It never stores proof, credentials or recovery codes in persistent browser storage.

Official usage consulted on 27 October 2026:

- [ADS Form usage](https://atlassian.design/components/form/usage): retain labels,
  short contextual descriptions/errors and one primary action per access step.
- [ADS Section message](https://atlassian.design/components/section-message/usage):
  persistent, actionable session guidance in the reading sequence.
- [Render Node version](https://render.com/docs/node-version): pin the reviewed
  build runtime and account for environment overrides.
- [Resend idempotency](https://resend.com/docs/dashboard/emails/idempotency-keys):
  retain one grant-bound provider key and payload on retry.

The two staff_auth Admin templates reuse the current Unfold/Admin shell and
server-rendered labeled forms, error notes and review/confirmation controls.
They are outside the Mini App source ratchet. This functional Admin exception
introduces no browser workspace component or new permission policy.

Source-bound native production evidence is generated under
`test-results/browser-production-native/` and
`test-results/complaints-browser-operations/dist-production/` with synthetic
accounts/customer records, loopback-only requests and no provider sends.
Sensitive QR/key/code controls are masked in failure captures; normal captures
are taken after authenticated work is reached. The release checklist records the
final run and unresolved environment/device acceptance. Screenshots and build
checks do not claim human approval, screen-reader testing or production delivery.

Final evidence: both real production-route journeys pass with 87 workflow and
eight access captures. Types/ADS lint/build/source ratchet pass. Desktop light
and mobile dark mailbox-verification screens were visually inspected. Full
verification and pre-existing repository release blockers are recorded in
`docs/runbooks/staff-browser-release-checks-2026-10-27.md`.
