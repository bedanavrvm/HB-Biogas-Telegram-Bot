# Complaints Main Page

28 October 2026. Implements the user-supplied `Stitch/Main Page` reference in the
native Complaints queue. Both the complete HTML/CSS/interaction code and PNG were
inspected, alongside its design notes. The existing case-detail corrections are
retained. No approved screenshot baseline or browser release gate is changed.

Open the [local screenshot gallery](../../../test-results/complaints-main-page/index.html).
It contains phone/desktop, both themes, menus, search/filter/sort, pagination,
creation, queue actions, Reports and account-navigation previews. Earlier captures
are kept separately as iteration evidence. They use synthetic native-session data
and a disposable PostgreSQL database; no operational customer data or provider
credentials appear in the captures.

## Design and behavior

- Compact workspace header with the existing wordmark and real workspace picker;
  theme, search, tools and account controls remain available.
- White title ribbon, real total, green New complaint action and horizontally
  scrolling All complaints/Open/Needs details/Resolved pills.
- Search/filter/sort strip with actual active facets and workspace label. Search
  still posts identifiers privately to the server, with no customer values in URLs.
- White triage cards with a blue expanded-state accent, reference/status/date,
  customer name, type/branch, optional contact inset, real HB comment/file counts,
  saved map link and canonical SLA. Long content wraps within phone widths.
- First card initially expanded. Card menus show/hide contact details and offer
  the currently authorized existing actions. Clicking the card/name/reference
  opens the detail; phone/map/copy/menu controls keep their own behavior.
- Resolve, HB Feedback, reopen and missing-details completion reuse the existing
  forms, validation, revision/idempotency and publication behavior. A confirmed
  queue action refreshes the cards and counts without navigating into the case.
- Five records per server page, accurate result range, previous/next and usable
  page-dot controls. Queue/detail/Back navigation keeps the selected queue/order.
- Bottom Queue/Search/Reports/Profile navigation. Search focuses the real queue
  search; Reports respects its existing capability; Profile opens the staff
  account menu with Settings and Sign out. No separate profile backend is invented.

## Backend and intentional adaptations

The native queue read projection adds authorized per-case actions, evidence
counts and a validated canonical map URL. Its Needs details filter selects
historical `Review Needed` cases; it creates no new workflow status. Open keeps
the existing unresolved scope, including Reopened and Needs details. Resolved is
presentation of Closed. Total/pill counts are workspace-wide; search/facets narrow
the displayed result range. All complaints is the new reference default unless
an explicit URL or saved preference chooses otherwise.

The small creation sheet in the export opens the actual complete creation form
as a bottom sheet on phones and a dialog on larger screens;
required identifiers, locations, catalogues and upload limits are preserved.
The source's sample dates, March filter, assignments, new statuses, notification
bell and static page counts are not operational facts. Prior exclusions remain.
The user explicitly confirmed **leave Customer verified out**. Remote demo image,
Google font and Tailwind runtimes are not added. Local Inter and installed icons
provide the reference's visual treatment. Missing closure attribution is not
invented. Dark mode preserves the geometry with readable surfaces.

## Review method and limits

Direct Playwright browser interaction and screenshot inspection only, following
the user's UI-only workflow. No test suites, assertion scripts, lint/typecheck
runs or new test files are part of this change. The production artifact is built
only to show the current UI. Source ratchet entries record the candidate and this
review without changing approved baseline hashes.

The browser review included status switching, a historical Needs details record,
contact expansion, card menus, search, sort, page navigation, creation-sheet entry,
queue Resolve and missing-details forms, Reports and Profile. One synthetic
resolution was saved through the existing form and then viewed in the Resolved
queue. Final views cover 320/390/427/768/1440px, both themes and 200% zoom.
The local preview's temporary historical Needs details state was restored after
its capture. No real external publication was performed.

No production deployment, real Google writes, physical-device or screen-reader
acceptance occurred. The page is available as a visual candidate for continued
user feedback; screenshots do not imply that the design has been approved.
