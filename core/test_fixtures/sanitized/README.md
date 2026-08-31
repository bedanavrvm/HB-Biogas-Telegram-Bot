# Sanitized fixture boundary

This directory is the only approved location for reviewed binary or tabular
test fixtures. Do not copy, transform, redact, or sample a production/customer
file into this directory: incomplete redaction is not synthetic data.

A fixture must:

- be generated entirely from invented people, identifiers, phone numbers,
  addresses, amounts, document metadata, and media;
- contain no real Telegram, Google, Drive, Sheet, signing, or application URL;
- contain no credential, signature, photo, or reusable access token;
- document its test purpose in the tracked-artifact allowlist;
- be classified as `sanitized_test_fixture` and hash-pinned before commit.

Controlled file types are ignored by default. Force-adding a fixture is safe
only after the exact bytes and the corresponding allowlist change have been
reviewed together. Prefer generating a fixture inside a test when practical.
