export const VIRTUAL_CAMERA_HEIGHT = 180;
const PORTAL_RADIUS_SCALE = 0.115;
const PORTAL_MIN_RADIUS = 1.25;
const PORTAL_MAX_RADIUS = 16;

export type GroundPortalPlacement = {
  horizontalDistance: number;
  x: number;
  y: number;
  z: number;
  radius: number;
  pitchDeg: number;
};

function normalizedAngle(angle: number) {
  return ((angle + 180) % 360 + 360) % 360 - 180;
}

export function portalArrivalViewLongitude({
  targetReturnPortalYaw,
}: {
  targetReturnPortalYaw: number;
}) {
  // Arrive looking exactly away from the station we just left. Carrying the
  // clicked ring's screen offset into the next panorama accumulates a new view
  // error at every hop: after a few warps, turning around no longer centres the
  // physical return point even when both measured portal bearings are correct.
  return normalizedAngle(targetReturnPortalYaw + 180);
}

export function groundPortalPlacement({
  distance,
  localYawDeg,
  localPitchDeg,
  reconstructedCameraHeight,
  fallbackStep,
}: {
  distance: number;
  localYawDeg: number;
  localPitchDeg?: number | null;
  reconstructedCameraHeight: number | null;
  fallbackStep: number;
}): GroundPortalPlacement {
  // 3DVista's floor-hotspot workflow calibrates the scene with the camera's
  // distance from the floor and one known panorama-to-panorama distance. Our
  // SfM trajectory already supplies both in the same arbitrary unit system:
  // camera-to-ground height and station displacement. Their ratio therefore
  // gives a scale-independent floor intersection without trusting monocular Z
  // drift. Older trajectories without a ground estimate retain the proven
  // adjacent-step fallback.
  const safeHeight = reconstructedCameraHeight !== null
    && Number.isFinite(reconstructedCameraHeight)
    && reconstructedCameraHeight > 1e-6
    ? reconstructedCameraHeight
    : Math.max(fallbackStep * 5, 1e-6);
  const safeDistance = Math.max(Number.isFinite(distance) ? distance : 0, 1e-8);
  const horizontalDistance = safeDistance * VIRTUAL_CAMERA_HEIGHT / safeHeight;
  const yaw = localYawDeg * Math.PI / 180;
  const estimatedPitch = Math.atan2(-VIRTUAL_CAMERA_HEIGHT, horizontalDistance) * 180 / Math.PI;
  // The API projects the destination through the source camera's complete
  // pose. Keep that measured vertical ray instead of rebuilding it from a
  // level-camera assumption; otherwise a rolled/pitched panorama paints a
  // correct route on the wrong patch of ground. Floor portals remain below
  // the horizon even when a noisy monocular pose reports a small positive
  // pitch.
  const hasMeasuredPitch = localPitchDeg !== null
    && localPitchDeg !== undefined
    && Number.isFinite(localPitchDeg);
  const pitchDeg = hasMeasuredPitch
    ? Math.max(-80, Math.min(-2, localPitchDeg))
    : estimatedPitch;
  const pitch = pitchDeg * Math.PI / 180;
  return {
    horizontalDistance,
    x: -Math.cos(yaw) * horizontalDistance,
    y: hasMeasuredPitch
      ? Math.tan(pitch) * horizontalDistance
      : -VIRTUAL_CAMERA_HEIGHT,
    z: -Math.sin(yaw) * horizontalDistance,
    radius: Math.min(
      PORTAL_MAX_RADIUS,
      Math.max(PORTAL_MIN_RADIUS, horizontalDistance * PORTAL_RADIUS_SCALE),
    ),
    pitchDeg,
  };
}
