# Visual-inertial integration evidence — 2026-09-14

## Scope

This result covers the new fail-closed integration between raw Insta360 sensor
data, an external metric VIO runner, persisted camera poses, and Virtual Tour
route vectors. It does **not** claim that the 21 December capture has been
relocalized; its source SSD and per-camera calibration were unavailable during
this run.

## Automated evidence

- Final API regression suite: `173 passed in 37.55s`.
- Focused VIO, raw-sensor, and route-vector suite: `44 passed in 16.77s`.
- Web TypeScript check: passed.
- Web ESLint check: passed.
- Python Ruff checks for changed localization code: passed.

The focused tests prove that the integration rejects non-metric positions,
partial tracks, implausible walking jumps, ambiguous coordinate frames, invalid
quaternions, and unordered sensor timestamps. They also prove that a calibrated
metric VIO pose cannot be overwritten by the older two-view essential-matrix
bearing.

## Outstanding real-data gates

1. Extract and audit IMU timestamps from the original 21 December INSV.
2. Calibrate the exact X5 camera-to-IMU transform and time offset.
3. Run a selected VIO engine and retain its canonical trajectory artifact.
4. Confirm capture coverage, gaps, speed, scale, and forward/reverse portal
   reprojection on the real walk.
5. Preserve capture `b78c9804-76c2-4e96-93d4-53cf55ffba3f` unchanged.

Until all five gates pass, the 21 December localization remains incomplete.
