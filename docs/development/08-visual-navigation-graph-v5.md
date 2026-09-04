# Visual Navigation Graph v5

Updated: 22 August 2026

## What changed

- Track panorama heading from the stitched MP4 at 5 FPS.
- Reconstruct global camera key views at 1 FPS with cubemap SfM, SIFT matching,
  geometric verification, triangulation, and bundle adjustment.
- Sample the final visual camera track every 0.5 seconds for the 360 viewer.
- Build navigation links only between temporal neighbours from the same SfM run.
- Reject links with missing visual coordinates, confidence below 0.55, a floor
  transition, or an outlier step greater than four times the median visual step.
- Never use plan proximity or a plan-derived bearing to create a 360 hotspot.
- Keep visual reconstruction confidence separate from floor-plan alignment.
- Hide the provisional plan route and plan points until every displayed pose has
  passed plan alignment or human calibration.

## Real-video smoke test

Source: `Data/681223/VID_20251223_171559_00_022.mp4`

- Source duration tested: 90 seconds
- Output visual samples: 181 (0.5-second cadence)
- Runtime: 208.2 seconds on the development machine
- Visual reconstruction confidence: min 0.90, mean 0.90, max 0.90
- Track start: `(0.0, 0.0)` in SfM coordinates
- Track end: `(0.5866, 1.8889)` in SfM coordinates

The SfM coordinates are scale-ambiguous and are intentionally not presented as
verified floor-plan coordinates. A reviewer must align the route to the plan,
or a verified previous capture must supply enough visual correspondences.

## Accuracy gate

This implementation prevents unsupported links from being shown, but the 95%
navigation-link target still requires a labelled evaluation set. For each test
capture, inspect at least 30 displayed links and record whether each hotspot opens
the physically correct neighbouring panorama. Do not report 95% accuracy from the
internal confidence score alone.
