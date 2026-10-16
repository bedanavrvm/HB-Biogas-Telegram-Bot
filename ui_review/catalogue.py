MODEL_METADATA = {
    f'ui_review.{name}': {
        'domain': 'ui_review', 'purpose': purpose, 'classification': classification,
        'source_of_truth': True, 'lifecycle': 'active',
        'retention': 'Retain indefinitely until a separately approved design-history retention policy. No operational or external deletion.',
    }
    for name, purpose, classification in [
        ('ReviewRevision', 'Exact source-bound synthetic UI comparisons and evidence manifests.', 'source_evidence'),
        ('ReviewDecision', 'Append-only human design choices and explicitly recorded device checks.', 'immutable_event'),
        ('StandardRelease', 'Immutable approved design selections; never authorizes app migration.', 'authoritative_record'),
    ]
}
