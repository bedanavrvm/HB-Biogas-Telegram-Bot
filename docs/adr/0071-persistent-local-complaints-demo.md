# ADR 0071: persistent local Complaints demo

Date: 20 October 2026. Status: accepted for local implementation under the user's
agreement to make the synthetic Complaints demo accessible in a browser.

Addendum: ADR 0072 supersedes the read-only simulator scope with role-based
local actions, in-memory uploads and an immutable v2 seed. The native staff
boundary remains read-only; operational gates and the original availability
decision remain unchanged.

## Decision

Serve a separate React/ADS demo on loopback port 8767. Reuse the P2a workspace
with an injected synthetic read transport. Open directly into cases; clearly
label synthetic data and provide working Exit/Open demo actions. Do not collect
passwords, simulate company assurance or enable the dormant staff channel.

The standalone Python server does not initialize Django, import settings, read
`.env`, contact external services or open any application/test database. Its
dedicated ignored SQLite file holds only a deterministic, integrity-checked
synthetic JSON fixture. This is reproducible review storage, not a persistent
operational domain model or workflow source of truth. Its lifecycle is local
review only, retention until manual removal, and restart reuses identical fixture
rows. No schema/migration or production database catalogue entry changes.

Create the fixture only at the fixed `test-results/complaints-local-demo/` path;
reject symlinks and unrecognized/modified stores. Requests open it read-only.
Serve verified build assets and only `/demo-api/complaints/v1/` GET/HEAD reads;
reject mutations, foreign Hosts/Origins and supplied authentication headers.
Do not log requests/query strings, accept credentials, set cookies, or read
browser storage. The demo transport omits cookies. Bind only 127.0.0.1 and
retain no-store/no-referrer/nosniff/CSP restrictions.

Use a distinct build/manifest kind and entry. Reject native auth/closed-workflow
builds at the demo server and keep the existing zero-connect preview separate.
The native P2a API retains company assurance plus owning Complaint authorization;
this synthetic demo does not exercise or replace that boundary. Production
remains disabled/unmounted and M1/privacy/named-reader gates stay open.

## Design and verification

Reuse actual Navigation System/ADS workspace components and existing tokens.
Current official sources consulted: navigation-system/layout/code,
section-message/usage and primitives/text/code at https://atlassian.design/ .
Record explicit full links and applied decisions in browser/DESIGN.md. Synthetic
status is ordinary persistent page context, with no repeated confirmation steps.

Validate fixture isolation/restart integrity, assets/source hashes, read routes,
search/status/paging/detail, forbidden routes/credentials/writes, cookie omission,
Exit/Open behavior, normal/error views in both themes/mobile, and the unchanged
native Complaints boundary. No dependency, provider, migration, production grant,
Telegram change, merge or deployment. Rollback stops the local process and removes
the separate demo entry from review; operational records remain untouched.
