# Full-system regression audit — 11 September 2026

## Scope and outcome

The human-reviewed structural-progress workflow was re-tested after the
cross-date carry-forward and multi-selection fixes. The supported stitched
equirectangular MP4 workflow, Virtual Tour data, plan-specific structural
progress, Dashboard, comparison view, BIM routes and Field Notes routes are
operational. No production inspection record was deleted or rewritten.

## Repairs completed in this pass

- Progress stages now accumulate across distinct Capture dates while the newest
  save on the same Capture remains the correction for that Capture. A later
  rebar/formwork observation therefore no longer hides earlier shoring work.
- Beam-range removal now applies the matching range to every beam selected on
  the plan. Full-length ranges are mapped to each selected beam's own length,
  so mixed beam lengths can be cleared together safely.
- The Windows auto-start task now runs an idempotent health check every five
  minutes in addition to the logon trigger. This recovers a stale video worker
  or public tunnel after sleep, power loss or a broker reconnection failure.
  Concurrent health checks are suppressed.
- The stale worker found during this audit was restarted through the normal
  local-startup path and returned a successful Celery ping.

## Automated verification

- API pytest suite: **155 passed**.
- API and maintenance-script Ruff check: passed.
- Web unit tests: **14 passed**, including full-length and partial-range bulk
  removal across selected beams.
- Web ESLint: passed.
- Web TypeScript typecheck: passed.
- Next.js production build: passed.
- Alembic source head and active database revision:
  `b82c6f1d3502`.
- PowerShell auto-start script parsed and the installed task was verified with
  two triggers: logon plus `PT5M` health checks, `IgnoreNew` overlap policy.

## Real pipeline smoke test

A read-only 20-second excerpt from the non-protected 21 December 2025 stitched
360 MP4 was processed through the production video pipeline using an in-memory
database and an isolated temporary object prefix.

- Final state: `SUCCEEDED`
- Keyframes: **40**
- Camera poses: **40**
- Temporary local clip: removed after the test
- Temporary object-storage prefix: removed by the smoke test
- Production Capture and Progress rows: unchanged

The default synthetic colour-bar clip was not accepted by Stella because it has
no real translational camera motion. This is expected for visual SLAM and is not
evidence of failure on supported real 360 capture video.

## Authenticated runtime verification

Authenticated server rendering returned HTTP 200 locally for Projects, the
29 January Viewer/Progress page, Dashboard, date comparison and Field Notes.
The same Projects, Viewer/Progress and Dashboard checks returned HTTP 200
through the active Cloudflare public URL. None redirected back to Login.

The live API returned the following project snapshot:

- 131 structural-scope Captures across 80 dates.
- First date: 20 December 2025.
- Last date: 3 July 2026.
- Dates after the configured structural cutoff: **0**.
- Every Capture begins with a keyframe at `0 ms`; no 1:20 start regression.
- 29 January Floor 2 beam items: **55**, with shoring visible on **55/55**.
- 29 January Floor 2 slab items: **29**, with shoring visible on **29/29**.
- Dashboard comparison activities: **142**.
- Project floors/plans: **7**.
- BIM versions exposed by the API: **3**.

## Data-integrity guardrails

- READY Captures missing a camera pose: **0**.
- READY Captures missing a warp station: **0**.
- Beam evidence pointing to a missing/wrong-Capture keyframe: **0**.
- Structural-element evidence pointing to a missing/wrong-Capture keyframe:
  **0**.
- Protected 20 December 2025 reference Capture remains `READY` with 257
  keyframes, 257 camera poses, 33 warp stations, first timestamp `0 ms` and last
  timestamp `128000 ms`.

## Human-controlled acceptance that remains

`REVIEW_REQUIRED` localization is intentionally not auto-approved. Route and
warp-point accuracy for those Captures still requires a reviewer to compare the
plan with the real 360 evidence. Beam lengths, slab areas and any newly entered
site quantities likewise remain human-verified values rather than inferred or
fabricated measurements.
