MODEL_METADATA = {
    'staff_auth.StaffBrowserAdmission': {
        'domain': 'staff_auth',
        'purpose': 'Explicit existing-staff browser opt-in and current browser-only session revocation generation; never workflow authority.',
        'classification': 'authoritative_record',
        'source_of_truth': True,
        'lifecycle': 'active',
        'retention': 'Retain admission/original staff ID for investigation after user detachment; no automatic purge. Immutable action evidence remains in the compliance ledger.',
        # PK, one-to-one user and original-user uniqueness provide all lookups.
        # No additional explicit queue/status index is justified for this table.
        'index_justifications': {},
    },
}
