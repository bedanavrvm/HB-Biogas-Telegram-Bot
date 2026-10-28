MODEL_METADATA = {
    f'complaint_conversations.{name}': {
        'domain': 'complaints', 'purpose': purpose,
        'classification': 'authoritative_record', 'source_of_truth': True, 'lifecycle': 'active',
        'retention': 'Retain with the owning complaint and its audit history; no automatic purge. Scoped testing deletion follows the disclosed case closure; external Drive files survive.',
    }
    for name, purpose in (
        ('CommentContext', 'Immutable browser staff-comment authorship, reply and retry bindings over canonical CaseUpdate text.'),
        ('CommentMention', 'Explicit authorized staff mentions retained as comment content; no authority or notification delivery.'),
        ('CommentReaction', 'Versioned per-actor comment acknowledgement; accepted changes have immutable compliance-audit receipts.'),
    )
}
