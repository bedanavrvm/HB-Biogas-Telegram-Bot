# Advisory LAF publication and durable seed identity

Accepted — 12 October 2026. This revises the document-completeness publication
rule in ADR 0041, not application approval or the signing policies in ADR 0045.

Document publication records an immutable saved PDF/layout, including unfinished
alignment. Missing fields, signers and placements are warnings in every environment.
Authorization, source integrity, valid placement data and concurrency remain enforced.
Published does not imply that an application is ready for signing: required signature
geometry is checked before a signing package or customer links can be created.

Editable copies retain the source's published layout. Only a draft with recorded
provenance from that source is reusable; an unrelated blank seed draft is not a copy.
Reopening a genuine draft preserves its subsequent edits. Historical applications
and signatures are never rewritten.

Environment bootstrap runs once per installation, with completion retained outside
the document catalogue. Fingerprint changes do not authorize automatic reseeding.
Logical seed identity recognizes edited, assigned and retired documents; explicit
force recreates missing seeds without replacing present human work. No new model,
scheduler, duplicate cleanup or automatic application conversion is introduced.

Reversal restores strict publication for future actions only; already published
versions and audit evidence remain retained. Product availability and application
consent/data checks remain distinct from advisory document authoring.
