# Origination placement rule and signer controls

The user's instruction is that an unplaced field must never appear while filling
the Mini App. Server projection policy 2 supplies the existing version-1 response
format so already-open clients keep empty sections hidden and filter retained
answers using the server-provided active schema. Mini App JavaScript, HTML, shell,
controls and tokens remain unchanged. No Phase 6 migration or baseline approval
is inferred.

The native Django Admin editor adds Edit beside signatures and inside the Signers
group, reusing its existing buttons/selects and mobile sheet. Edit exposes the
owning person's label, required status and existing identity field links. Copying
a signature keeps that person and adds a paired date placement. Published
documents remain locked. Source: `origination_calibration.js` / `.css` and the
existing `calibrate.html` shell. Admin sources are outside the Mini App ratchet.

Evidence uses native authenticated Admin with synthetic PDF/storage and real
save/reload/publish endpoints in `core/tests_origination_signature_copy_browser.py`.
`scripts/test_origination_signature_copy.js` captures the opened controls at
390/1366px in light/dark under `test-results/origination-signature-copy/`.
Mini App checks use the real server projection compiler through
`origination_queues.spec.js`'s synthetic fixture, verify unplaced guarantor IDs and
empty Signing details stay absent, and check saves omit retained inactive answers
at 320/430/1280px in light/dark. Screenshots are review evidence, not automatic
acceptance or baseline updates. Validation outcomes: `KNOWN_GAPS.md`.
