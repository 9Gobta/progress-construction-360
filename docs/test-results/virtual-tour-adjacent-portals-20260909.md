# Virtual Tour adjacent-portal repair — 9 September 2026

## Reported issue

Capture 21 December 2025 (`d535cc28-c101-4653-8dd2-a9ea96c230e8`) displayed
warp portals for stations on other parts of the route. A station exposed up to
19 Euclidean-nearest destinations, so a nearby station on the other side of a
wall could be rendered as if it were directly walkable.

## Change

- Portal visibility now follows recorded time order and exposes only the
  immediately previous and next stations.
- Existing navigation graphs were rebuilt for every non-reference capture in
  the project. The protected 20 December 2025 reference capture was skipped.
- Development captures now describe evaluation points as reviewed plan-point
  consistency, not surveyed absolute-position accuracy.

No camera coordinates, route coordinates, calibration points, station count,
or progress inspection records were changed by this repair.

## Verification

- Non-reference stations audited: 46,641
- Minimum outgoing links per station: 1
- Maximum outgoing links per station: 2
- Stations with more than two outgoing links: 0
- 21 December capture: 23 stations and 44 directed route vectors
- Protected reference: 33 stations, unchanged by the backfill command
- API video/spatial tests: 34 passed
- Python lint: passed
- Web ESLint: passed
- TypeScript: passed
- Production build: passed
- API readiness, local web, and public tunnel: HTTP 200

## Accuracy boundary

The repair prevents misleading through-wall navigation links. It does not turn
monocular 360 video into survey-grade coordinates. Absolute position remains
dependent on reviewed plan anchors or an external survey/GNSS/LiDAR reference.
