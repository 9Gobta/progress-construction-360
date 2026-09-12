export const VIRTUAL_CAMERA_HEIGHT = 180;
const PORTAL_RADIUS_SCALE = 0.09;
const PORTAL_MIN_RADIUS = 1.25;
const PORTAL_MAX_RADIUS = 12;

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

export function reciprocalPortalViewLongitude({
  sourceViewLongitude,
  sourcePortalYaw,
  targetReturnPortalYaw,
}: {
  sourceViewLongitude: number;
  sourcePortalYaw: number;
  targetReturnPortalYaw: number;
}) {
  // Preserve the viewer's offset from the selected portal using the reciprocal
  // route itself. This avoids accumulating per-station heading approximation
  // errors when a reviewer repeatedly travels away and back through a tour.
  const portalOffset = normalizedAngle(sourceViewLongitude - sourcePortalYaw);
  return normalizedAngle(targetReturnPortalYaw + 180 + portalOffset);
}

export function groundPortalPlacement({
  distance,
  localYawDeg,
  reconstructedCameraHeight,
  fallbackStep,
}: {
  distance: number;
  localYawDeg: number;
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
  return {
    horizontalDistance,
    x: -Math.cos(yaw) * horizontalDistance,
    y: -VIRTUAL_CAMERA_HEIGHT,
    z: -Math.sin(yaw) * horizontalDistance,
    radius: Math.min(
      PORTAL_MAX_RADIUS,
      Math.max(PORTAL_MIN_RADIUS, horizontalDistance * PORTAL_RADIUS_SCALE),
    ),
    pitchDeg: Math.atan2(-VIRTUAL_CAMERA_HEIGHT, horizontalDistance) * 180 / Math.PI,
  };
}
