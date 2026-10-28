MODEL_METADATA = {
    'complaint_publications.UploadAttempt': {
        'domain': 'complaints', 'purpose': 'Browser-only upload command, owner, manifest and idempotency binding.',
        'classification': 'authoritative_record', 'source_of_truth': True, 'lifecycle': 'active',
        'retention': 'Uncommitted attempts expire after 24 hours; committed metadata follows owning complaint retention.',
        'index_reasons': {'cmp_upload_expiry_idx': 'Find uncommitted reservations eligible for bounded 24-hour cleanup.'},
    },
    'complaint_publications.UploadFile': {
        'domain': 'complaints', 'purpose': 'Durable private evidence bytes and measured browser/Drive publication progress.',
        'classification': 'source_evidence', 'source_of_truth': True, 'lifecycle': 'active',
        'retention': 'Unpublished bytes retained for IT resolution; successful bytes purged 24 hours after verified publication. Metadata follows the case.',
        'index_reasons': {'cmp_file_purge_idx': 'Find only retained successful payloads due for bounded 24-hour cleanup; purged rows leave the index.'},
    },
}
