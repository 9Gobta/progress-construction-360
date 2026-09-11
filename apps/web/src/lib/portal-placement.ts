export const VIRTUAL_CAMERA_HEIGHT = 180;

export type GroundPortalPlacement = {
  horizontalDistance: number;
  x: number;
  y: number;
  z: number;
  radius: number;
  pitchDeg: number;
};

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
    radius: Math.min(10, Math.max(1, horizontalDistance * 0.075)),
    pitchDeg: Math.atan2(-VIRTUAL_CAMERA_HEIGHT, horizontalDistance) * 180 / Math.PI,
  };
}
