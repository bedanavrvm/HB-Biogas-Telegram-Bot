# Portal retry under production pacing

The user reported repeated HTTP 202 responses and rows remaining pending after
the earlier batch retry change. The earlier local verification explicitly set
Portal publication spacing to zero. It therefore missed the real five-second
write interval: the first pass could defer a row and finish the batch while
later selected rows remained behind it in FIFO order.

A signed-Django/PostgreSQL Playwright run reproduced this with normal spacing:
one row synced, subsequent rows returned 202, and the single-click retry never
finished the selected rows without an independent publisher. The failing run
and response capture are retained under `test-results/portal-paced-retry-before.log`
and `test-results/portal-paced-retry/requests-before.json`. This reproduces a code
defect; the supplied production access logs alone do not establish whether that
live queue additionally has a provider/circuit cooldown or another blocker.

## Existing controls and behavior

- The current compact toolbar gains Stop retrying during foreground retry.
  It ends the page's loop after the current request and retains queued work.
- Single and batch retries wait for server-reported pacing before continuing.
  Provider backoff, circuit cooldown, FIFO and active leases remain protected;
  these waits retain a concrete explanation and next retry time.
- Responses/logs state the deferral reason. The card reuses that explanation.
  A circuit-open refusal with zero provider attempts is not a new write failure.
- Per-register completion counts its successful current operation even when a
  separate register for that case remains pending. Superseded work is not counted
  as a successful current write. Scope changes stop the foreground batch.
- Existing buttons, checkbox density and progress feedback are reused. No new
  colors, layout system, baseline replacement or Phase 6 adoption is introduced.

## Local browser evidence

Actual five-second spacing was retained and measured between accepted claims.
The three-row batch, single retry and Stop/resume flows completed and retained
one Sheet row per case. Separate provider-backoff and circuit-cooldown journeys
confirmed no new Sheet rows and no forced provider attempt. The circuit journey
initially exposed incorrect failed-attempt classification; it passed after the
specific circuit-open handling was corrected.

The previous 12-row, cross-page journey and scoped failure/recovery journey also
passed, as did nine shared Portal/TAT/Complaints/Origination browser checks.
Artifacts: `test-results/portal-paced-retry/` (scenario captures, response JSON,
PostgreSQL readback and source hashes). Google transport is simulated. Production
deployment, the exact live blocker and live Google delivery remain unverified.
