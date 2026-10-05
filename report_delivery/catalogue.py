"""Customer-data-free database governance declarations."""
MODEL_METADATA = {}
for name, purpose, classification, retention in (
    ('ApprovedRecipient', 'Approved report recipient and explicit disclosure scope.', 'authoritative_record', 'Retain until explicit administrative removal; protected while deliveries reference it.'),
    ('ReportSchedule', 'Scoped recurring Portal report configuration and Nairobi dispatch cadence.', 'authoritative_record', 'Retain until administrative removal; protected while deliveries reference it.'),
    ('ScheduleRecipient', 'Explicit approved recipient membership in a report schedule.', 'configuration_state', 'Retain with schedule configuration.'),
    ('ReportDelivery', 'Durable per-recipient submission, retry ownership and provider delivery evidence.', 'authoritative_record', 'Erase payload and report snapshot after 30 days; delete delivery metadata after 180 days.'),
    ('WebhookReceipt', 'Verified immutable provider event receipt and replay guard.', 'immutable_event', 'Delete provider receipt metadata after 180 days.'),
):
    MODEL_METADATA['report_delivery.' + name] = {
        'domain': 'report_delivery', 'purpose': purpose, 'classification': classification,
        'source_of_truth': True, 'lifecycle': 'active', 'retention': retention,
        'index_reasons': {
            'report_delivery_due_idx': 'Find due retry or queued deliveries without scanning retained delivery history.',
            'report_delivery_provider_idx': 'Correlate signed events to a provider submission without scanning 180-day history.',
        } if name == 'ReportDelivery' else {'report_webhook_provider_idx': 'Replay one email’s events in time order, including receipts that preceded API persistence.'} if name == 'WebhookReceipt' else {},
    }
