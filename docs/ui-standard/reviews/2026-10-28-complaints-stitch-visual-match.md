# Complaints: Stitch visual correction

Date: 28 October 2026. This supersedes the visual composition in the earlier
`2026-10-28-complaints-stitch-detail.md` candidate; its backend/recovery behavior
is retained. The user's explicit instruction replaces ADS styling now and for
future requests. The repository guidance and lint policy record that precedence.

## Reference and implementation

Both `Stitch/Create Complaint/code.html` and `screen.png` were inspected, along
with the exported `DESIGN.md`. The HTML includes interactive states absent from
the resting screenshot. The page implements those states through existing
native operations rather than copying the export's mock actions or sample data.

The resting composition uses Inter 14/20, a 22/28 heading, #FAF9FF canvas,
#F1F3FF insets, white cards, #051A3E text, #004FB6 links, #006C47 resolution,
12px content padding/gaps and a 128px recorded map. The screenshot guides the
borderless metadata values and rounded resting cards; the code guides compact
controls, expanded conversation and dialogs. Dark mode uses the same geometry
with readable surfaces, inverse button text and placeholder colors.

| Section | Actual behavior and reference adaptation |
| --- | --- |
| Header and ribbon | Back to queue, current reference/status and actual previous/next queue positions; 56px header. Company text replaces the export's missing remote logo. |
| Heading and actions | Customer name is the title. Green Resolve follows existing HB/scoped-IT capabilities; Internal note focuses the composer; copy creates the actual case permalink. Secondary HB feedback/Sheet retry stays under the working overflow menu. |
| Metadata | Saved reporter initials, copied National ID, callable phones, branch/type/date/severity and actual case age. No stock portrait or synthetic values enter operational UI. |
| Description | Read-only tinted text block. The user's earlier exclusion of description editing remains. |
| Location | Saved marker, zoom/reset/retry, village overlay, county/constituency cells and saved HTTP(S) map link. No location edits or invented location reference. |
| Attachments | A card appears when files exist. Protected thumbnails, preview, zoom, PDF paging where applicable and downloads retain native authorization. File names and errors wrap legibly. |
| Conversation | Own-workflow Officer, Manager, HB and scoped IT access; actual author/Nairobi time, append-only notes, basic bold, authorized mentions, nested replies, thumbs-up/undo and comment permalinks. Closed/Needs details states preserve their restrictions. |
| Composer | Lavender note panel, attachment/camera selection, bold/mention controls, Save Note, required-text validation and 5,000-character limit. Files keep existing count/byte limits and upload only on save. |
| History | Actual audit events and pagination. Conversation drafts survive tab switches. No fake Work log or public/private tab is added. |
| Resolution and reopen | Existing required note/evidence, HB resolve, Manager reopen and existing scoped-IT technical capabilities. Open-next retains dirty conversation drafts. The sample resolution-code catalogue and assignment remain excluded. |
| Voice | Existing bounded MediaRecorder/transcription/use-text controls receive the reference panel styling in supported, enabled action dialogs. The description remains read-only. |
| Recovery | Offline retention, native password/MFA resume, exact uncertain-save retry and same-file publication recovery remain intact. Confirmed saves generate dismissible in-flow feedback bound to the current case. |

## Browser evidence

Open the [84-screenshot gallery](../../../test-results/complaints-stitch-visual-fix/index.html) for the reference,
before/after and every captured expanded state. Raw journey results are in
`journeys.jsonl`; source/build hashes are in `evidence-manifest.json`.

The browser host uses the actual production artifact, Django/allauth password
plus recovery MFA, native operations/CSRF and a disposable PostgreSQL database.
All users, cases, files and grants are synthetic. Playwright interaction checks
cover notes/mentions/bold, history drafts, replies/reactions/permalinks, concurrent
idempotent retries, storage failure with the same evidence ID, preview/download,
offline/session/uncertain recovery, required resolution, stale draft protection
and Manager reopen. Captures include light/dark, 320/390/454/768/1440/1920 widths,
200% zoom and modal Escape/focus behavior. Checks found and corrected a misplaced
map overlay, compact attachment wrapping and dark action/placeholder contrast.

Recording/transcription captures use browser-generated synthetic audio and an
explicitly intercepted synthetic provider response. They establish UI behavior,
not microphone hardware or production transcription acceptance. The actual
feature-disabled state is also checked. CARTO has no commissioned key here;
working-map interaction uses visibly labelled synthetic tiles, with separate
network-error/retry and disabled-configuration captures; the saved landmark
remains visible when mapping is unavailable. Live cartography is not claimed.

TypeScript, production build/source integrity, the updated lint policy, UI source
ratchet and existing production asset boundary checks supplement the browser
review. No new unit tests or changed business assertions were added. Only the
existing asset fixture gained the required font and licence entries.

## Scope and limits

Inter 4.1 is unmodified and locally served; its licence/provenance and source
hashes are retained. No remote font/Tailwind runtime or new npm dependency. Closed operations/review
asset handlers also serve the allowlisted local font with the correct MIME/CSP;
the fixed synthetic preview and sign-in-only graphs retain their font restrictions.
Production flags, real staff admission, workflow grants and approved UI baselines
are unchanged. No deployment, production data writes, real mail, external Drive
writes, physical-device or screen-reader acceptance occurred.

## Completed checks

- Playwright: six widths, both themes, 200% zoom, all expanded states listed
  above, native interaction/recovery journeys, role boundaries and map fallbacks.
- TypeScript and scoped ESLint: passed with the user-authorized styling policy.
- Production and closed native operations builds: passed; every final production
  source, vendor and output hash verified against the manifest.
- Existing production asset boundary checks: 5 passed on the isolated PostgreSQL
  setup. The initial SQLite-only invocation could not initialize the audit state;
  it is not counted as validation.
- Closed native operations loader: font manifest, MIME and same-origin CSP passed.
- UI source ratchet and `git diff --check`: passed; approved baselines untouched.

`final/` contains the current review captures; other image names retain the
before and intermediate correction evidence. Native functional journeys ran
incrementally as defects were found; final matrix captures bind to the final
frontend sources. Recording/provider responses and map tiles remain explicitly
synthetic, as described above.
