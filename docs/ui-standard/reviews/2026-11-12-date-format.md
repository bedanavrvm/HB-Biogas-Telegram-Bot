# Fixed dd/mm/yyyy presentation

User direction on 12/11/2026: dates must always use dd/mm/yyyy everywhere.
AGENTS.md Quick reference records this across workflows, staff surfaces and
future work. The explicit user request is also retained in the authorized memory
update note. Machine storage and payloads retain ISO values.

## Implementation

JBL actual and planned visit entry reuse the existing formatted text field with
calendar button. Both display a two-digit day/month and four-digit year separated
by slashes, independently of browser locale. Typed and calendar-picked values
feed the existing ISO hidden fields and draft storage. Restored drafts reformat
their displayed values. Invalid or partial typing clears the ISO field so an old
valid value cannot be submitted silently. The minimum planned-date rule remains.

Shared Mini App date/date-time helpers and graph labels now display dd/mm/yyyy.
Date-only slash input is parsed day-first; timestamps retain Nairobi conversion.
Portal fallback labels, visit card labels and rescheduling reminders use the same
format. Consumer asset versions advance, including shared consumers outside
Portal, so cached scripts cannot retain the previous formatter.

## Verification

The focused Playwright checks pass for shared graph labels, visit repayment
visibility and fixed date entry under en-US. Entry of 23/11/2026 saves the ISO date
2026-11-23; the month-boundary value 04/03/2026 stays March 4. An impossible date
clears transport state. Calendar selection formats as 03/12/2026.
All 22 Portal dashboard tests passed on a freshly migrated isolated PostgreSQL
test database, including the slash-formatted reminder assertion. The Node suite,
all 180 first-party JavaScript syntax checks, Ruff and UI source checks passed.

The real Django Portal was exercised with signed synthetic Telegram identity
and isolated PostgreSQL, with external hosts blocked and Google transports
stubbed. Desktop 1280 x 1000 and mobile 390 x 844 light/dark screenshots under a
US browser locale were visually inspected in `test-results/date-format-review/`.
HBG Visit Date displays 31/10/2026 and Next visit date displays 13/11/2026. The
checks also cover durable draft restore, required-date feedback and successful
case save with ISO database readback. No page errors occurred. Evidence spacing
and the always-visible media section remain intact.

This fixes the current visit flow and the shared formatters. It is not a full
audit or conversion of every older independently formatted screen, document or
historical export. Production deployment and physical device pickers were not
checked. Design migration and workflow authority remain unchanged.
