# Sheet recovery and legacy receipts

Implemented 2 November 2026. Django remains the operational source of truth;
the retained legacy records supply explicitly reviewed historical facts.

## Order references

Master Data and Eco-conserve project recognized references as digits only:
`Order 123`, `HB-123` and `ECO-123` become `123`; `HB-00047` becomes `00047`.
The database, app, official documents and internal order register retain full
references. Case IDs and group/partner routing still identify destination rows.

Exceptional labels such as buyoffs retain their complete text. The legacy
import flags unsupported allocator references for review and retains originals.
If no canonical order reference exists, a unique retained legacy reference is
projected without inventing an order. Conflicting references are flagged and
must not overwrite the Sheet's order field. Existing rows adopt the display
format on their next normal publication; no live bulk rewrite was performed.

## Complaints recovery

Open Settings → App status in Telegram or Settings → Sheet publication status
in the browser. Check status refreshes the saved publication state. The card
shows known failure causes, required missing headers, the job reference,
publisher heartbeat, last attempt and scheduled retry time in Nairobi time.
Original files remain retained while publication is unresolved.

Missing/duplicate headers, empty headers, disabled projection, unavailable
publisher and provider failures have separate guidance. Unknown provider
failures remain unknown; raw provider responses and credentials are not shown.
The reported cause is the last recorded failure, not proof of current provider
availability. Ordinary comment saves and diagnostics HTTP 200 responses do not
prove that Google Sheets was updated.

For the newly required column, add the exact **JBL Verification Comments**
header to the configured Complaint register. Header positions can vary.
Correct credentials/access or projection configuration when indicated.
If the publisher is not reporting, verify the existing scheduled worker:

```sh
python manage.py drain_complaint_publications --apply --limit 10 --max-seconds 50
```

Schedule it every minute. Without `--apply`, it only reports due work. A retry
button does not start an absent worker or fix Google credentials.

After correcting the cause, authorized staff with the current Complaint
`complaint.case.sync.retry` grant can request Retry publication. It queues an
audited successor for exhausted work or a missing job. Pending work keeps its
lease and backoff; retries do not recreate comments, resolutions, case events
or files. Other Mini App grants confer no Complaint authority. Successful
publication clears the issue automatically. See the existing
[publisher runbook](complaints-browser-publications.md).

The recovery-card crash was a shared interface mismatch: report recovery read
`group.pk`, while Complaints supplied a `GroupConfig`. Filtering by the stable
group identifier supports both configuration objects and database rows,
including the existing TAT caller.

## Legacy JBL receipts

The legacy importer recognizes **Deposit Paid to JBL** and **Deposit / JBL**,
including values retained under older opaque legacy column keys. It validates
amounts as finite, nonnegative Decimal values with at most two decimal places.
Original values remain in the legacy record; normalized amounts remain in its
proposal. No new receipt table or database migration is required.

Case history identifies this value as **Legacy deposit received by JBL**.
The amount projects to its dedicated JBL receipt column, retaining cents.
Blank values remain unknown, zero remains zero, and invalid or conflicting
amounts are flagged rather than selected or fabricated.

This receipt does not populate SysUp's LGF balance, the HB receipt, deposit
eligibility, payment calculations or a current outstanding-transfer balance.
SysUp's misleadingly named `system_deposit_paid_jbl` remains LGF. FarmUp
continues to supply the HB deposit unless the HB Actions deposit editor has
taken ownership. Sheet typing during FarmUp publication preserves JBL receipt
cents rather than rounding this independent amount to whole shillings.

The initial lead form and the future transfer/confirmation workflow are not
extended by this change. No production import or live Google write occurred.
