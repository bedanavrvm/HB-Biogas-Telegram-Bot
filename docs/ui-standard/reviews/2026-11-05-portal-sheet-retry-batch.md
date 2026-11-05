# Portal App status: field changes and one-click batch retry

The user rejected generic Case Sheet update guidance and requested actual
before/after values, multi-selection and working retry for long-waiting rows.
This adapts the current Portal App status card, compact checkbox controls and
existing sequential publication requests. The rest of each Mini App's recovery
actions retain their own permissions and confirmations.

Portal Sheet rows show the readable case ID, customer, destination, concrete
waiting cause and field changes. The first three known differences are visible;
additional differences and saved fields lacking a retained comparison collapse.
The comparison explicitly uses last recorded Sheet writes, not claimed live
Google values. Generic What to do/support-reference filler is removed from these
rows. No new theme, spacing system or navigation is introduced.

Select displayed or individual rows, move between pages, then Retry selected.
One click processes the selection sequentially, displaying progress and actual
synced/waiting/failed counts. Pending items have a retry action. Active workers,
FIFO, cooldowns and legacy replacement holds remain protected. Exhausted retries
retain their old operation and replay the same successor after interruptions.
The endpoint now executes a bounded manual attempt instead of only requeueing;
the foreground publisher is also awakened and completion events refresh status.

The minimized signed-Django/PostgreSQL Playwright baseline failed with
`0 !== 3` selectable pending rows. A separate browser-request probe returned
`pending` instead of `synced`, confirming the original no-op retry. Probe log:
`test-results/portal-recovery-probe-before.log`.
The corrected journey processes 12 cases across two pages, checks actual local
Sheet values/unique rows, retains business revisions and replays an exhausted
successor. Negative journeys cover scoped denial, identity conflict, cooldown,
active/stale workers, legacy holds, provider failure and repaired-provider retry.
The internal-order preview and publisher use the same field plan and are checked
against the local register. Screenshots include desktop/mobile and dark mode.

Source hashes, captures, browser results and database readback are in
`test-results/portal-recovery-browser/`. No production data/provider write,
release activation, approved baseline change or Phase 6 migration is claimed.
