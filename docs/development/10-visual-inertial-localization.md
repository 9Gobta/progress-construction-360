# Metric Visual-Inertial Localization

## Purpose

Virtual Tour portals must represent physical camera stations, not screen-space
decorations. The visual-inertial engine therefore consumes the stitched video
and the original Insta360 INSV together. A run that cannot prove metric scale,
time coverage, and a calibrated camera-to-IMU transform is rejected before it
can replace stored camera poses.

## Processing contract

Configure:

```text
LOCALIZATION_ENGINE=visual_inertial
VISUAL_INERTIAL_RUNNER_PATH=<absolute executable path>
VISUAL_INERTIAL_CALIBRATION_PATH=<calibration for the exact camera unit>
```

The API invokes the runner as:

```text
runner --video <stitched.mp4> --insv <original.insv> \
  --calibration <camera-imu.yaml> --output <trajectory.json>
```

The runner may wrap an audited VIO implementation. Kimera-VIO is the preferred
prototype candidate because it supports mono/stereo plus IMU and uses a BSD
license. OpenVINS and ORB-SLAM3 are useful technical benchmarks, but both use
GPLv3 and require a separate licensing decision before a distributed commercial
product uses them.
It must emit this canonical output:

```json
{
  "schema": "progress360-vio-trajectory-v1",
  "coordinate_frame": "x-forward_y-left_z-up",
  "position_unit": "metre",
  "samples": [
    {
      "timestamp_ms": 0,
      "position_m": [0.0, 0.0, 1.65],
      "camera_to_world_xyzw": [0.0, 0.0, 0.0, 1.0],
      "confidence": 0.95
    }
  ]
}
```

`camera_to_world_xyzw` must describe the stitched panorama camera, not the raw
IMU body. Applying the calibrated IMU-to-camera transform is the runner's
responsibility.

## Safety and acceptance gates

The API rejects the result instead of extrapolating or silently falling back
when any of these conditions is true:

- missing original INSV or exact-camera calibration;
- fewer than three poses, invalid values, unordered timestamps, or a quaternion
  norm error greater than 2%;
- less than 90% capture coverage or a tracking gap greater than 1.5 seconds;
- path length below 0.5 metre or implied walking speed above 4 m/s;
- non-metric positions or an unknown coordinate convention.

The existing absolute plan alignment and human-review gate still apply after
VIO. A metric relative trajectory is not by itself proof of the correct place
on the floor plan.

## X5 sensor extraction

`scripts/extract_insta360_sensor_bundle.py` reads the timestamped gyroscope and
accelerometer stream using `telemetry-parser`. It deliberately labels the axes
as uncalibrated. A rotation copied from a different X5 unit must never be used
as a production camera-to-IMU calibration.

## Remaining hardware-dependent work

1. Connect the SSD containing the 20 and 21 December source INSV files.
2. Record an AprilGrid calibration clip with the same X5 unit and capture mode.
3. Solve camera intrinsics, camera-to-IMU extrinsics, time offset, and IMU noise.
4. Install and wrap the selected VIO engine, then generate the canonical JSON.
5. Run the 21 December capture without changing the protected 20 December
   reference.
6. Accept portals only after forward/reverse station reprojection is inspected
   and recorded under `docs/test-results/`.
