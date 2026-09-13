from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

FACE_YAWS = (0.0, 90.0, 180.0, 270.0)
FACE_SIZE = 512
FACE_FOV_DEG = 100.0
MIN_FACE_INLIERS = 30
MAX_DIRECTION_DISPERSION_DEG = 18.0


@dataclass(frozen=True)
class VerifiedPortalDirection:
    forward_yaw_deg: float
    backward_yaw_deg: float
    inliers: int
    dispersion_deg: float
    confidence: float


def _normalized_angle(angle: float) -> float:
    return (angle + 180.0) % 360.0 - 180.0


def _perspective_map(
    width: int,
    height: int,
    yaw_deg: float,
) -> tuple[np.ndarray, np.ndarray, float]:
    focal = (FACE_SIZE / 2) / math.tan(math.radians(FACE_FOV_DEG) / 2)
    axis = (np.arange(FACE_SIZE, dtype=np.float32) - (FACE_SIZE - 1) / 2) / focal
    grid_x, grid_y = np.meshgrid(axis, -axis)
    ray_z = np.ones_like(grid_x)
    length = np.sqrt(grid_x**2 + grid_y**2 + ray_z**2)
    ray_x = grid_x / length
    ray_y = grid_y / length
    ray_z /= length
    yaw = math.radians(yaw_deg)
    panorama_x = math.cos(yaw) * ray_x + math.sin(yaw) * ray_z
    panorama_z = -math.sin(yaw) * ray_x + math.cos(yaw) * ray_z
    longitude = np.arctan2(panorama_x, panorama_z)
    latitude = np.arcsin(np.clip(ray_y, -1.0, 1.0))
    map_x = ((longitude / (2 * math.pi)) + 0.5) * width
    map_y = (0.5 - latitude / math.pi) * height
    return map_x.astype(np.float32), map_y.astype(np.float32), focal


def _panorama_vector(face_vector: np.ndarray, face_yaw_deg: float) -> np.ndarray:
    yaw = math.radians(face_yaw_deg)
    x, y, z = (float(value) for value in face_vector)
    return np.asarray(
        [math.cos(yaw) * x + math.sin(yaw) * z, y, -math.sin(yaw) * x + math.cos(yaw) * z]
    )


def _weighted_direction(
    candidates: list[tuple[int, float]],
) -> tuple[float, float]:
    total = sum(weight for weight, _angle in candidates)
    sin_sum = sum(weight * math.sin(math.radians(angle)) for weight, angle in candidates)
    cos_sum = sum(weight * math.cos(math.radians(angle)) for weight, angle in candidates)
    mean = math.degrees(math.atan2(sin_sum, cos_sum))
    dispersion = sum(
        weight * abs(_normalized_angle(angle - mean)) for weight, angle in candidates
    ) / max(total, 1)
    return _normalized_angle(mean), dispersion


def estimate_portal_direction(
    source_path: Path,
    target_path: Path,
) -> VerifiedPortalDirection | None:
    """Measure the camera-to-camera bearing directly from two panoramas.

    The 3-D reconstruction supplies scale and gravity, but a portal's horizontal
    bearing is re-checked here from the pair that the user will actually cross.
    This prevents accumulated trajectory interpolation error from being painted
    as a physically exact floor ring.
    """
    source = cv2.imread(str(source_path), cv2.IMREAD_GRAYSCALE)
    target = cv2.imread(str(target_path), cv2.IMREAD_GRAYSCALE)
    if source is None or target is None or source.shape != target.shape:
        return None
    sift = cv2.SIFT_create(nfeatures=3500)
    forward: list[tuple[int, float]] = []
    backward: list[tuple[int, float]] = []
    for face_yaw in FACE_YAWS:
        map_x, map_y, focal = _perspective_map(source.shape[1], source.shape[0], face_yaw)
        source_face = cv2.remap(
            source, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP
        )
        target_face = cv2.remap(
            target, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP
        )
        source_points, source_descriptors = sift.detectAndCompute(source_face, None)
        target_points, target_descriptors = sift.detectAndCompute(target_face, None)
        if source_descriptors is None or target_descriptors is None:
            continue
        pairs = cv2.BFMatcher().knnMatch(source_descriptors, target_descriptors, k=2)
        good = [
            pair[0]
            for pair in pairs
            if len(pair) == 2 and pair[0].distance < 0.70 * pair[1].distance
        ]
        if len(good) < MIN_FACE_INLIERS:
            continue
        source_xy = np.float32([source_points[item.queryIdx].pt for item in good])
        target_xy = np.float32([target_points[item.trainIdx].pt for item in good])
        centre = (FACE_SIZE - 1) / 2
        intrinsics = np.asarray(
            [[focal, 0.0, centre], [0.0, focal, centre], [0.0, 0.0, 1.0]],
            dtype=np.float64,
        )
        essential, mask = cv2.findEssentialMat(
            source_xy,
            target_xy,
            intrinsics,
            method=cv2.RANSAC,
            prob=0.999,
            threshold=1.5,
        )
        if essential is None or mask is None:
            continue
        inliers, rotation, translation, _mask = cv2.recoverPose(
            essential, source_xy, target_xy, intrinsics, mask=mask
        )
        if inliers < MIN_FACE_INLIERS:
            continue
        # OpenCV returns camera2_from_camera1=[R|t]. Therefore camera 2's
        # centre in camera 1 is -R^T t, while camera 1's centre in camera 2 is t.
        target_in_source = _panorama_vector(
            (-rotation.T @ translation).reshape(3), face_yaw
        )
        source_in_target = _panorama_vector(translation.reshape(3), face_yaw)
        forward.append(
            (inliers, math.degrees(math.atan2(target_in_source[0], target_in_source[2])))
        )
        backward.append(
            (inliers, math.degrees(math.atan2(source_in_target[0], source_in_target[2])))
        )
    if not forward or not backward:
        return None
    forward_yaw, forward_dispersion = _weighted_direction(forward)
    backward_yaw, backward_dispersion = _weighted_direction(backward)
    dispersion = max(forward_dispersion, backward_dispersion)
    if dispersion > MAX_DIRECTION_DISPERSION_DEG:
        return None
    inliers = sum(weight for weight, _angle in forward)
    face_score = min(1.0, len(forward) / len(FACE_YAWS))
    inlier_score = min(1.0, inliers / 240.0)
    agreement_score = max(0.0, 1.0 - dispersion / MAX_DIRECTION_DISPERSION_DEG)
    confidence = 0.35 * face_score + 0.35 * inlier_score + 0.30 * agreement_score
    return VerifiedPortalDirection(
        forward_yaw_deg=forward_yaw,
        backward_yaw_deg=backward_yaw,
        inliers=inliers,
        dispersion_deg=dispersion,
        confidence=min(1.0, confidence),
    )
