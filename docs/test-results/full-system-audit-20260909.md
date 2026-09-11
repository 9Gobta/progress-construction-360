# Full-system audit — 9 September 2026

## Outcome

The current local system is operational from an equirectangular 360 MP4 through
processing, Virtual Tour navigation, human progress inspection and Dashboard
reporting. Runtime startup was hardened after a stale Docker socket and a stale
Celery worker were found. No inspection history or protected reference-capture
data was deleted or rewritten.

## Repairs completed

- Restored the `video_cpu` Celery worker and verified a real broker/worker task
  round trip.
- Hardened local startup so a locked Docker/WSL runtime socket is quarantined
  safely before Docker is reopened. Images, volumes and project data are not
  touched.
- Made public-share startup delegate Docker runtime recovery to the hardened
  local startup instead of repeatedly trying to delete one locked socket.
- Prevented cancelled localization jobs from being revived by a stale Celery
  message.
- Rejected an existing Stella trajectory when either its beginning or ending
  remains frozen for more than 25% of the capture. This prevents a repeated
  position from being reused as a valid route.
- Corrected Stella heading conversion so the Virtual Tour viewing direction
  uses the same coordinate basis as the plan route.
- Changed stale/deleted Capture links from an internal server error to a proper
  `404 Not Found` page. The full browser route sweep then passed all nine valid
  pages with no page errors.
- Cleared all current Ruff findings in the maintenance scripts.

## Real 360 processing verification

A 20-second clip was extracted from an actual 7680x3840 equirectangular 360
capture and sent through the same processing service used by uploaded captures.

- Final state: `SUCCEEDED`
- Keyframes produced: 40
- Camera poses produced: 40
- Temporary object-storage files: removed automatically after the test
- Production project/capture/progress rows: not changed by the smoke test

The upload API's storage guard, multipart upload completion and queue creation
are also covered by the API regression suite. Raw `.insv` stitching was not
tested because no licensed `INSTA360_STITCHER_PATH` is configured. The supported
and verified input for this machine is a stitched equirectangular MP4 such as the
7680x3840 H.264 files currently in use.

## Automated verification

- API pytest suite: 147 tests passed.
- API Ruff: passed.
- Web unit tests: 7 passed.
- Web ESLint: passed.
- Web TypeScript typecheck: passed.
- Web production build: passed.
- Alembic source head and active local database revision: `d8a14c2e7b10`.
- PowerShell startup scripts: parsed successfully.
- Celery broker/worker round trip: `system_ping` returned `status=ok`.
- Local browser E2E: passed.
- Public Cloudflare browser E2E: passed at the active public URL.

The browser test verified 100 capture dates, Virtual Tour loading, a station
change, capture/date navigation, four Dashboard KPI cards, 100 Dashboard dates,
five BIM category filters and the saved-viewpoint control. The panorama fallback
image path was used in headless WebGL and loaded successfully.

## Current data integrity snapshot

- Captures: 211 total across 100 dates.
- Capture states: 131 `READY`, 80 `REVIEW_REQUIRED`; none queued, running or
  failed.
- Latest processing attempts: 209 succeeded, 1 cancelled and 1 failed; no
  active jobs.
- Keyframes: 56,411.
- Camera poses: 56,411.
- Dense path points: 56,411.
- Warp stations: 46,688.
- `READY` captures missing a pose: 0.
- `READY` captures missing a warp station: 0.
- Human activity progress entries: 46.
- Beam progress entries: 1,086.
- Structural-element progress entries: 664.
- Total saved human progress evidence: 1,796 entries.
- Protected 20 December 2025 reference capture: still `READY`, with 257
  keyframes, 257 poses and 33 warp stations.

## Items intentionally left for human review

1. The 80 `REVIEW_REQUIRED` captures must be compared against their real 360
   evidence and plan before approval. They are not failed uploads.
2. Beam lengths and slab areas still need drawing/site verification before they
   are used as thesis-grade quantities.
3. The 19 March 2026 capture remains usable from its existing `READY` route, but
   its latest relocalization attempt failed and its externally linked original
   source is no longer present. Reprocessing it requires restoring that source
   file; the historical failed attempt must remain in the audit trail.
4. A newly uploaded stitched MP4 can now be processed into a tour and route.
   Absolute placement may correctly remain `REVIEW_REQUIRED` when there are not
   enough trusted plan/reference matches; a reviewer then supplies or confirms
   the plan alignment instead of the system inventing a location.
5. Raw Insta360 `.insv` input requires the licensed Insta360 MediaSDK wrapper to
   be configured. This is separate from the verified stitched-MP4 workflow.
