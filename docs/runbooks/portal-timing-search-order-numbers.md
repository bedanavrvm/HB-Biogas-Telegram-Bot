# Portal timing, search and order numbers

Updated 17/11/2026.

## Case timing

Case History, its progress strip, reports and TAT target settings share this order:
Intake, JBL Visit, Credit Decision, Final Decision, Order Assigned/Sent to HB,
HB Installation, HB Commissioning. Intake is the starting checkpoint; the six
following stages measure the time since their preceding checkpoint.

Only the current stage runs. Rescheduled and other visit outcomes stay within
JBL Visit. Formal deferrals pause the clock; withdrawal/rejection stops it.
Rework or an invalidated/expired approval returns timing to the affected gate.
An assigned order remains at Order Assigned/Sent to HB until its exact signed
version is accepted and released to HB. Commissioning ends delivery timing;
payment does not end it.

Known later workflow progress closes earlier stages even when their old times
are absent. Such durations display Timing unavailable, rather than zero or a
second running clock. Historical completion flags remain visible without
inventing completion dates. Backward timestamps are excluded from measured
durations. Reports retain historical/date-precision estimate labels and exclude
incomplete historical stages from live SLA measurement.

IT should review Settings / TAT targets after release. Unchanged interval keys
retain their targets. Set targets explicitly for the newly merged Credit
Decision and Order Assigned/Sent to HB boundaries; the old split targets are
not added together. Existing audited event snapshots are never rewritten.

## Search

Enter any remembered name words, in any order: `Juliet Mutegi` and `Mutegi
Juliet` both match the synthetic example `Juliet Kawira Mutegi`. Every entered
word must occur within one name field. ID, phone, order and invoice searches
retain their existing behavior. Access scope and other filters still apply
before results are paged.

## Official order numbers

Settings, the selected-case lookup, preview and generation use the same allocator.
Selection determines the group and HB/Eco-conserve partner. Mixed selections
must be separated. With multiple accessible groups, choose the group in Settings
before adjusting its sequence.

An explicit IT sequence adjustment takes precedence over older released slots.
The allocator reads the existing adjustment/cancellation audit records; it does
not delete claims or rewrite orders. An explicitly selected free slot remains
usable; only cancellations recorded after the last adjustment can override that
selection with a reusable number. Occupied and retired numbers remain
unavailable. Preview reserves nothing; concurrent generation still locks the
sequence and validates the preview revision.

If lookup fails, the number field stays empty with Unavailable as its placeholder.
The error and Retry button appear below the fields. Retry reloads the proposal
without assigning a number. Preview/generation continue to validate access,
eligibility and current numbering server-side. Order dates display `dd/mm/yyyy`;
the calendar retains an ISO machine value.

No data repair, historical timestamp backfill, migration or production action is
required by this change. Deployment and any live operational check are separate.
