# Complaints detail: visual corrections

28 October 2026. This replaces the affected interaction/layout choices in the
earlier Stitch component review. Supplied Stitch code/images remain the styling
reference, with the user's subsequent explicit corrections taking precedence.

The [local gallery](../../../test-results/complaints-ui-corrections/index.html)
contains direct browser previews of the current phone/desktop layout, light and
dark themes, reply chains, map, tabs, clipboard tooltip and top notifications.
The preview uses synthetic data, native authentication and a disposable local
database. Provider transport and visibly labelled map tiles are synthetic.

## What changed

- Metadata values have individual subtle grey cards inside the white section;
  one column below 400px, two above. Dark mode uses corresponding dark surfaces.
- Authorized HB Feedback remains visible beside the other actions. The three-dot
  menu is last at the far right; actions wrap on phones. Its refresh action is real.
- The map is 260–400px tall according to viewport height. Open map pin is an
  outlined footer action, full-width on phones. It opens the retained pin safely.
- Conversation and History divide their tab row evenly, with centred labels.
- Message author/time, body, parent excerpt, attachments and actions wrap
  independently. Text stays readable without widening the viewport. Reply chains
  retain exact parents, including replies to one's own replies; indentation is
  capped visually, with immediate-parent excerpts preserving context.
- Parent excerpts open the selected message and can fetch an older parent using
  the existing focused-message endpoint. Loaded comments are kept unique when
  saving, loading earlier messages or following a parent.
- Copy success is a two-second tooltip anchored to the clicked control. Errors
  remain in the notification area; no separate copied-message row is inserted.
- Notifications stay below the app header in the viewport, including above an
  open dialog. They stay visible during scrolling/resizing. Errors and warnings
  persist until dismissed/resolved; success notices expire. Destructive warning
  confirmations open near the top. Field errors stay beside their controls and
  also get a top summary with a Review fields action. Closing a form clears its
  validation summary. There is no second page-level success banner.

## Conversation and register publication

Plain internal notes/replies remain Django conversation records with no Sheet
job, register revision change or publisher-health announcement. Save confirmation
is simply Note saved or Reply saved. Reading the updated History is independent
of register publication.

The displayed case adopts a confirmed operational save immediately, before its
background refresh finishes. This prevents switching from HB Feedback to an
internal note with the previous local revision; a genuine concurrent change
still retains the existing server conflict protection.

Conversation file progress stays on the corresponding message attachment.
Publication JSON adds `origin` and `comment_key` from the existing upload command
receipt and canonical update. Reused evidence can retain separate message
associations; no new receipt table or customer text storage is introduced.
Polling continues independently of the removed large publication panel so
published file previews become available without reopening the page.

HB Feedback is still an official register update, alongside creation,
corrections, resolution and reopening. Only a real register job produces the
compact toolbar status; generic case sync flags cannot invent a queued update.
The Sheet projection also exposes its opaque job key for stable UI feedback.
Relevant publication failures retain a persistent warning; detailed worker-health
diagnostics and explicit failed-file recovery stay in scoped Complaints IT tools.
The canonical save, retained originals, progress calculations and retry worker
are preserved. No additional Sheet write is made for a reply.

The reply change removes the previous parent-flattening step. The existing
foreign key already supports exact parents; migration
`complaint_conversations.0002_reply_parent_comment` changes its PostgreSQL comment
only. Historical flattened relationships are not rewritten or reconstructed.

## Review method and limits

At the user's direction, this pass uses browser interaction and screenshots
only. No test suites, assertion scripts, lint/typecheck runs or new test files
were used. Production builds were generated solely to display the UI. The UI
source registry records current candidate hashes without changing approved
baselines or claiming automated acceptance.

The browser review includes replying through several generations, replying to
one's own message, attaching a file within that chain, copy feedback, opening
History, HB Feedback validation, form cancellation and the discard warning.
Final captures include 320/390/454/1440px layouts in both themes. These are visual
previews for continued user review, not a claim that the UI is satisfactory.

No deployment, operational database migration, live Google publication,
physical-device or screen-reader review occurred. The comment-only migration
still needs the normal deployment migration step. Existing release flags and
Telegram behavior are unchanged.
