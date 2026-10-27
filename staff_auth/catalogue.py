MODEL_METADATA = {
    'staff_auth.StaffBrowserSecurityState': {
        'domain': 'staff_auth',
        'purpose': 'Shared PostgreSQL native authentication histories, owner-bound lock leases and used-code markers; no identity assurance or workflow grant.',
        'classification': 'security_state', 'source_of_truth': True, 'lifecycle': 'temporary',
        'retention': 'Retain every live row until database-clock expiry. Bounded preview-first purge_staff_browser_security removes expired rows only; no eviction, global clear or deletion of audit evidence.',
        'index_justifications': {'staff_security_expiry_idx': 'Bound expiry-only security-state maintenance without scanning live authentication rows.'},
    },
    'staff_auth.StaffBrowserSetupGrant': {
        'domain': 'staff_auth',
        'purpose': 'Expiring mailbox-proof and optional first-password state for the exact existing admitted account. Existing passwords are never replaced; no login or workflow authority.',
        'classification': 'security_state',
        'source_of_truth': True,
        'lifecycle': 'temporary',
        'retention': 'Erase native proof at completion. Purge only expired grants with bounded preview-first purge_staff_browser_setups; retain native addresses/passwords and immutable compliance receipts. No automatic scheduler until operational owner acceptance.',
        'index_justifications': {'staff_setup_expiry_idx': 'Bound expiry-only setup-capability cleanup without scanning live grants.'},
    },
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
    'staff_auth.StaffTOTPReplayState': {
        'domain': 'staff_auth',
        'purpose': 'Atomically reserve successful native browser TOTP use across workers without retaining plaintext codes or identities.',
        'classification': 'security_state',
        'source_of_truth': True,
        'lifecycle': 'temporary',
        'retention': 'Keep every live claim until expiry. Expired claims may be renewed in place or removed by bounded preview-first purge_staff_totp_replays; schedule/owner acceptance precedes operational use. No credentials or compliance events are removed.',
        'index_justifications': {
            'staff_totp_replay_expiry_idx': 'Select bounded expired-only cleanup batches without scanning live security claims.',
        },
    },
}
