# BIM, Dashboard and Virtual Tour readiness — 8 September 2026

## Scope protected during this pass

- No human Progress entry was edited or deleted.
- The protected 20 December 2025 capture was not changed.
- The running local web/API and public Cloudflare tunnel remained online.

## Changes completed

### BIM

- Corrected the IFC viewer axis convention and rejected mirrored registration.
- Registered plan coordinates against IFC structural-element centres on the
  horizontal X/Z plane and followed the 360 camera heading through the same
  transform.
- Isolated the active floor and hid the route marker in first-person follow
  mode.
- Added a separate inspection mode that keeps the IFC model visible together
  with the complete route, a blue camera-position marker and an orange
  horizontal viewing-direction arrow. This makes position and direction
  auditable without changing stored camera poses or Progress records.
- Added live category filters for columns/beams, slabs/roofs, stairs, rebar and
  other IFC products. Rebar and unrelated products start hidden to reduce
  visual clutter.
- Added an authenticated same-origin IFC streaming route. Remote reviewers now
  download the model through the public web URL instead of receiving a
  `localhost:9000` MinIO address that only works on the host computer.
- Added reviewer-authored BIM viewpoints for each 360 station. A reviewer can
  switch to free-view mode, position the IFC camera, save that view and restore
  it later without changing the camera pose, route or human Progress history.
- Added the `bim_viewpoints` migration and applied it after copying
  `progress-dev.db` to a timestamped backup.

### Dashboard

- Made latest-observation selection deterministic even if API rows arrive out
  of order.
- Broke ties using the entry creation time so a correction made for the same
  observation timestamp wins.
- Grouped captures and observations by the Bangkok calendar date instead of
  UTC, preventing late-night entries from appearing on the wrong day.

### Virtual Tour

- Prevented the selected marker from intercepting clicks on another station
  at the same or nearly the same plan coordinate.
- Verified that the 360 fallback image loads when WebGL is unavailable.
- Verified a station change, a full date/capture navigation and the next
  panorama load using real project data.

## Verification evidence

- API regression suite: all tests passed.
- Web unit tests: 7 passed (BIM registration/orientation, IFC categories,
  Dashboard ordering and Bangkok date grouping).
- ESLint: passed.
- TypeScript typecheck: passed.
- Next.js production build: passed.
- Authenticated browser smoke test against the real project:
  - 100 capture dates available;
  - current station and route links loaded;
  - clicking another warp station changed the active panorama;
  - selecting another date navigated to a different capture and loaded its
    first station;
  - Dashboard rendered four KPI cards and 100 dates;
  - BIM rendered five category filters and each filter toggled state;
  - switching BIM from 360-follow mode to free-view exposed an enabled
    per-station viewpoint control.
- Repeated the complete authenticated browser smoke test through the current
  Cloudflare public URL; Virtual Tour station/date changes, Dashboard controls
  and all five BIM filters passed. The 40.9 MB IFC streamed completely through
  the public URL with HTTP 200.
- Restarted only the API process after a parallel port-8001 preflight. The new
  API reported ready, exposed the BIM viewpoint route, and returned HTTP 200
  for an authenticated viewpoint lookup. The web and tunnel processes stayed
  running during this deployment.
- Runtime data baseline: 211 captures, 126 READY, 85 REVIEW_REQUIRED, 56,411
  keyframes/camera poses.
- Integrity audit: zero captures without keyframes, zero keyframes without a
  READY image, zero keyframes without a camera pose, zero captures without a
  warp point, and zero saved visibility targets pointing outside their capture.
- Availability check: localhost web 200, API readiness 200, current public
  Cloudflare URL 200.
- Inspection evidence for the reported 16 January 2026 capture is stored in
  `docs/test-results/bim-direction-floor1-20260908.png`. It shows the IFC,
  route, blue camera marker and orange direction arrow in one view. The IFC
  registration used 23 structural matches at 0.00 m RMS; this validates the
  plan-to-IFC fit, but does not by itself certify the capture's SLAM route.
- The 26 June 2026 comparison in
  `docs/test-results/bim-plan-aligned-20260626.png` verified that inspection
  mode preserves the drawing's screen axes: the active endpoint is on the
  right in both views, route loops extend to the same side of the baseline,
  and the orange BIM arrow points in the same screen direction as the blue
  plan cone.
- `docs/test-results/bim-plan-overlay-20260626.png` adds the actual floor-plan
  crop as a transparent registered plane underneath the IFC. Grid lines,
  structural members, the capture route and direction marker can therefore be
  checked in one coordinate system instead of estimated between two panes.
- `docs/test-results/bim-model-mirrored-only-20260626.png` verifies the requested
  IFC-only vertical reflection. The capture route, active camera marker,
  heading arrow and registered plan remain in their original coordinates;
  only the IFC group is reflected about the building centre along plan Y.
- `docs/test-results/bim-column-grid-aligned-20260626.png` verifies the corrected
  post-mirror placement. Because reflection swaps the physical grid rows, the
  viewer no longer pulls a mirrored column toward the plan location carrying
  the same IFC GlobalId. It aligns the mirrored IFC from the outer column-grid
  extents, keeping the plan and capture route fixed while placing the column
  axes on the drawing grid.
- `docs/test-results/bim-revit-viewcube-20260908.png` verifies the BIM navigation
  controls added for the Revit-style workflow. Camera framing uses only visible
  floor products instead of hidden IFC storeys. The live ViewCube follows the
  camera and exposes all six faces, four edge targets, Home and 90-degree
  left/right turns. Automated browser checks confirmed that Top→Front and
  Front→rotated views render different camera images, middle-button drag pans,
  Shift+middle-button drag orbits, and the interaction produced no page errors.
- `docs/test-results/bim-follow-heading-toward-building-20260626.png` verifies
  the corrected 360/BIM viewing direction for the reported 26 June capture.
  The route and mirrored IFC remain fixed; only the erroneous second reflection
  of the camera vector was removed. An audit of 315 consecutive route steps
  measured 6.95° mean / 5.93° median directional error for the retained
  `plan heading + panorama longitude` convention, versus 173.05° mean error for
  the opposite direction. Browser validation found no page errors.

## Remaining product work

- Field-grade BIM/360 accuracy still depends on route calibration quality for
  each capture; a visually correct IFC registration cannot repair a bad SLAM
  route automatically.
- REVIEW_REQUIRED captures must remain visibly labelled until a reviewer
  confirms their plan alignment.
- Element-level BIM issue workflows and automatic visual-to-IFC registration
  are later OpenSpace-style capabilities; they require more than a viewer-side
  camera correction and must retain human verification.
