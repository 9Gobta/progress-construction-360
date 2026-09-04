# Stella VSLAM localization POC

Updated: 22 August 2026

## Decision

The production localization path now uses `stella_vslam`. PyCOLMAP remains an
explicit diagnostic option only and is never selected silently.

Stella receives a 1920x960, 15 FPS tracking proxy generated from the stitched
8K equirectangular MP4. The original 8K keyframes remain the visual evidence;
the proxy exists only for visual localization.

## Setup on the Windows development machine

Start Docker Desktop, then run:

```powershell
.\scripts\setup_stella.ps1
```

The script pins Stella to 0.7.0, downloads the official FBoW ORB vocabulary,
and builds `progress-stella-vslam:0.7.0`. Generated source, vocabulary and build
artifacts stay under `.runtime/stella` and are not committed.

## Runtime contract

The worker invokes `run_video_slam` without a viewer and requests:

- `frame_trajectory.txt` in TUM format;
- `keyframe_trajectory.txt` for diagnostics;
- `map.msg` as the input artifact for the future cross-day localization stage.

The current POC consumes the trajectory inside one localization job. Persisting
`map.msg` in object storage and loading it for a later capture is the next stage;
cross-day relocalization is not claimed as complete yet.

Every TUM row is converted to a timestamped relative X/Z camera position,
quaternion-derived heading and tracking confidence. Missing tracking frames and
long time gaps reduce confidence.

## Safety gates

- A missing Docker image, vocabulary or camera config fails localization with a
  specific error. It never falls back to a fabricated path.
- The first capture has unknown monocular scale and plan rotation. Until it is
  aligned using human anchors or a verified previous capture, all plan points
  remain at the user-selected start and every camera pose requires review.
- Low visual tracking confidence also forces review.
- Viewer links continue to use immutable visual coordinates, not provisional
  floor-plan coordinates.

## POC acceptance gate

Run the first 20-30 seconds of `Data/681223/VID_20251223_171559_00_022.mp4` and
accept only when:

1. Stella produces at least four poses and at least 70% tracking coverage.
2. No time gap between displayed neighbouring panoramas exceeds the configured
   navigation threshold.
3. At least 30 manually labelled next/previous links achieve 95% correctness.
4. Unaligned floor-plan data remains `REVIEW_REQUIRED`, never `READY`.

## Result on the first real capture

The 25-second smoke segment completed with 97.6% mean tracking confidence, 51
half-second samples and a largest neighbouring step of 0.0773 SLAM units.

The full 91.1-second `23/12/2568` capture then completed end-to-end through
Celery in 171 seconds. It produced:

- 182 viewer camera poses at 0.5-second intervals;
- 98% mean pose confidence;
- 362 verified temporal next/previous route vectors;
- an 8.217-unit relative camera track with a 0.0964-unit largest step;
- `REVIEW_REQUIRED` for all 182 poses because plan alignment has not been
  manually calibrated.

All provisional plan points stayed exactly at the selected start point. This
is intentional: the viewer navigation can use the visual track, but the system
must not display an invented floor-plan route.

The remaining 95% acceptance item is a human-labelled check of at least 30
visible next/previous hotspots. Floor-plan accuracy is measured separately
after two or more anchors have been placed by the user.
