# Virtual Tour reference rollout — 8 September 2026

## Scope

- Reference capture: 20 December 2025, `b78c9804-76c2-4e96-93d4-53cf55ffba3f`
- Project: `c2ade70f-f813-42fa-9a84-050cb5bb0822`
- Applied to every other localized capture without changing the protected reference
- This rollout normalizes Virtual Tour station/navigation behavior. It does not promote a `REVIEW_REQUIRED` localization to verified plan accuracy.

## Data audit and migration

- Localized captures inspected: 211
- Captures missing two poses or two warp points before rollout: 0
- Original exposed stations: 46,874
- Final stations after owner-requested light deduplication: 46,674
- Removed: 200 consecutive same-position duplicates (0.43%) across 9 captures
- Graph-backed stations shown by the Viewer: 46,632; only 42 terminal/unconnected points are hidden
- Non-reference captures updated: 210
- Original per-capture backups: 210 JSON files under `.codex_tmp/tour-station-backups/`
- The superseded 8,048-station state is also recoverable from 210 JSON files under `.codex_tmp/tour-station-spatial-backups-20260908/`
- Captures with zero route vectors after rollout: 0
- The Viewer now excludes zero-distance/unconnected legacy stations from its active tour graph.

An initial four-second spatial sampling result of 8,048 stations was rejected as
too aggressive and rolled back. The production pipeline now starts from the
dense one-second candidate cadence and removes only consecutive candidates at
the exact same localized position, matching the final existing-data policy.

The protected reference remained at 33 stations and 257 poses. A SHA-256 digest over its station flags, plan/visual poses, headings, and visibility targets was identical before and after the rollout:

`36a4a1565738cc958b1d4733c47729f008d65e2b36c7d5e8037a45c7db4ba04f`

## Automated checks

- API route and station tests: 34 passed
- Web ESLint: passed
- Web TypeScript: passed
- Local browser smoke: passed
  - panorama image rendered
  - active station had 3 reachable route portals
  - keyboard/map station selection changed the panorama
  - 100 capture dates available and changing the date loaded a different station
  - Dashboard rendered 4 KPI cards and Productivity
  - BIM rendered 5 category filters and enabled saved viewpoints
- Public Cloudflare browser smoke: passed with the same results

## Final regression

- Ruff over API source, API tests, and the station maintenance command: passed
- Full API pytest suite: 138 passed after the cadence adjustment
- Web ESLint: passed
- Web TypeScript: passed
- Next.js production build: passed (all application and API proxy routes generated)
- Service checks after rollout: local web 200, API readiness 200, public Cloudflare login 200

The focused browser matrix also passed on the protected reference and four
captures that previously contained the largest groups of duplicate/unconnected
stations (13 January, 18 June, 24 June, and 3 July 2026). Every sample rendered
an active route, exposed an alternate station, changed the panorama from the map
with Enter, and emitted no page errors.

## Roof plan black-screen regression

The reported URL for capture `573949f1-d2c6-429b-a279-1f7c0a8ee333` and Roof 2
(`c3f680ae-4925-4a88-b717-4970c951e411`) was reproduced and inspected. The plan
asset and proxy both returned HTTP 200, and the decoded PNG was 2978 × 2105 px.
The blank state was therefore a client transition/loading failure rather than a
missing plan.

The track sheet now keeps an opaque plan-specific loading surface during floor
changes, reports a failed image explicitly, and offers a retry that remounts the
current floor image with a new revision URL. An automated forced-network-failure
check confirmed the error surface appeared instead of a black panel and that
the retry restored the Roof 2 image at 2978 × 2105 px with opacity 1. Web lint,
TypeScript, and the production build passed after the fix.
