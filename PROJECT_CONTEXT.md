# Project context

Last reviewed: 4 September 2026

## Project identity

**Progress Construction 360** is a prototype web system for inspecting and
tracking structural construction progress from 360-degree site video. The case
study is a four-storey reinforced-concrete dormitory project.

The system combines:

- a 360-degree Virtual Tour;
- visual localization and a route on a floor plan;
- 3D camera/warp-point visualization;
- human-entered structural progress with evidence and audit history;
- planned-versus-actual dashboards and CSV export;
- IFC/BIM comparison as a product direction.

## Current approved scope

The current scope is **human structural progress + localization assistance**.
The reviewer decides and records progress. AI/CV may help locate the camera on
the plan, but it must not decide construction progress. Historical AI progress
experiments are archived research material, not current production behavior.

Primary scope references:

- `docs/planning/00-planning-index.md`
- `docs/planning/09-scope-v2-human-structural-bim.md`
- `docs/development/09-current-acceptance-status.md`

## Inputs available from the project owner

- stitched 360-degree video;
- floor plans and structural drawings;
- a manually selected starting floor and start point;
- approximate route/anchors when manual correction is required;
- human progress inspections and evidence.

Do not assume GPS, LiDAR, camera depth, surveyed control points, or a precise
metric camera trajectory unless a source explicitly provides it.

## Technical architecture

| Area | Current technology |
|---|---|
| Web | Next.js + TypeScript |
| API | FastAPI + Python + SQLAlchemy/Alembic |
| Development database | SQLite |
| Intended infrastructure | PostgreSQL, Redis, Celery, MinIO/S3 |
| Video | FFmpeg/ffprobe |
| Localization | Stella VSLAM and visual/plan-alignment services |
| BIM | IFC-oriented browser comparison |

Key paths:

- `apps/web/` — user interface
- `apps/api/` — API, database models, migrations, and tests
- `workers/` — background processing entry points
- `scripts/` — local development and data-processing commands
- `docs/planning/` — approved requirements and architecture baseline
- `docs/development/` — implementation notes and acceptance evidence

The nested `real-estate-360-tour/` prototype is an independent local Git
repository and is excluded from this collaboration repository. It is not a
dependency of the current Progress Construction 360 thesis workspace.

## Protected reference capture

The capture dated **20/12/2568 (20 December 2025)**, ID
`b78c9804-76c2-4e96-93d4-53cf55ffba3f`, is the accepted reference for Virtual
Tour appearance, stable/clickable warp points, plan alignment, and 3D
warp-point correspondence. It must not be edited without an explicit request
from the project owner naming this capture.

Other captures should reuse the method and acceptance behavior, not copy the
reference capture's coordinates blindly. Each date has its own video path,
duration, tracking quality, floor, start point, and alignment evidence.

## Confirmed product decisions

- Clicking a warp point changes panorama immediately; no artificial zoom or
  travel animation is required.
- Warp points should remain fixed to world/camera geometry while the panorama
  view rotates or after returning from another point.
- The plan shown must match the active floor. From February 2026 onward, some
  captures require the second-floor plan; floor selection must follow stored
  capture data rather than a date-only guess.
- A Sub Admin may edit inspection geometry such as beam length and inspection
  area, but cannot edit source code.
- Historical human inspections must survive a future WBS revision and be
  remappable to a new WBS item without destroying the original record.

## Current known state and open risks

Use these as a starting checklist, then verify against the current database and
tests before stating them as final results:

- Start points were entered by the owner through 19 March 2026.
- The 6 March 2026 floor-1 capture was reprocessed with segmented Stella
  recovery after tracking loss near second 14 and produced a reviewable route.
- Some captures remain `REVIEW_REQUIRED`; this is a quality gate, not an
  automatic processing failure.
- The dashboard reads cumulative human-progress snapshots up to the selected
  date. Detailed beam-range inspections and WBS remapping need explicit
  end-to-end verification before the dashboard is described as complete.
- Cross-day relocalization and future-plan/WBS migration must not be claimed as
  complete without tests and retained audit history.
- Temporary Cloudflare tunnel URLs are not permanent deployment links and can
  fail when the host process or computer stops.

## Thesis-safe wording

Prefer: "The prototype assists localization and lets a human reviewer record
structural progress from 360-degree evidence."

Avoid: "The AI automatically measures all construction progress" or "the
system achieves Preimage-equivalent accuracy" unless new controlled evidence
actually supports those statements.

## Data and privacy

Real databases, videos, drawings with personal/project-sensitive information,
credentials, and advisor audio stay outside Git. Sanitized summaries and small
figures may be committed after review by the project owner.
