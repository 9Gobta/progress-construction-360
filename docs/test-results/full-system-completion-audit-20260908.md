# Full-system completion audit — 8 September 2026

## Outcome

The software paths in the current human-verified structural-progress scope are
implemented and passed the final regression pass. No production inspection
history, capture route, or protected reference-capture data was edited.

## Fixes completed in this pass

- Isolated pytest upload tests from the host machine's configured storage guard.
  Production uploads still enforce the real free-space threshold.
- Added explicit keyboard activation for plan warp points after client hydration.
- Corrected the browser smoke test to wait for React/panorama hydration before
  exercising route and BIM controls.
- Added native Windows Redis startup and native MinIO fallback to
  `scripts/start_local_dev.ps1`, so Docker Desktop is no longer required when
  the portable/local services are available.
- Started Redis and the Celery video worker without restarting the web, API,
  MinIO or Cloudflare tunnel.
- Updated the Windows Auto Start task to use the hardened startup path.

## Automated verification

- API pytest suite: 137 passed.
- API Ruff: passed.
- Web unit tests: 7 passed.
- Web ESLint: passed.
- Web TypeScript typecheck: passed.
- Web production build: passed.
- Alembic source head and database revision: `c2f94a6b7180`.
- Celery broker/worker round trip: `system_ping` returned `status=ok`.
- Local browser E2E: passed.
- Public Cloudflare browser E2E: passed.

The browser E2E verified 100 capture dates, a Virtual Tour station change,
capture/date navigation, the next panorama image, four Dashboard KPI cards,
100 Dashboard dates, five BIM category filters, and the per-station BIM
viewpoint control.

## Runtime/data audit

- Captures: 211 total; 126 `READY`, 85 `REVIEW_REQUIRED`.
- Current capture states: zero `QUEUED`, zero `RUNNING`, zero `FAILED`.
- Floor plans: 7 floors and 7 active plan sheets.
- Structural inventory: 618 active items (219 beams, 92 columns, 115 slabs,
  137 roof items, 23 foundations, 23 pedestals and 9 stairs).
- Schedule: 159 activities.
- Progress evidence: 44 manual activity entries, 159 structural-element entries
  and 633 beam progress entries.
- BIM: three ready IFC media versions; active model streaming was verified by E2E.

## Work that must remain human-controlled

- The 85 `REVIEW_REQUIRED` captures are intentionally not auto-approved. A
  reviewer must compare each route with its actual 360 evidence and plan.
- Beam lengths and slab areas still require drawing/site verification before
  thesis-grade quantity claims are made.
- Historical `FAILED`/`CANCELLED` processing-job rows remain in the audit trail.
  Their captures are usable (`READY`) or were explicitly cancelled by the
  owner; the records must not be deleted or silently rewritten.

## Host maintenance note

Docker Desktop in the current Windows session has a locked stale internal
socket. This does not affect the web, API, MinIO, Redis, existing Virtual Tours,
BIM, Dashboard or Progress inspection. The configured Stella VSLAM engine does
need Docker for a brand-new localization run. Auto Start now attempts to remove
that socket before Docker starts and launches Docker as a non-blocking
localization dependency; one normal Windows restart is still required before a
new Stella localization job can be guaranteed on this host.
