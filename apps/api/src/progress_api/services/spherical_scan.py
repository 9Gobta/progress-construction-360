from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np

SCAN_YAWS = tuple(float(value) for value in range(0, 360, 45))
SCAN_PITCHES = (-45.0, 0.0, 45.0)
SCAN_FOV_DEG = 100.0
SCAN_TILE_SIZE = 640


@dataclass(frozen=True)
class SphericalView:
    """One overlapping perspective view rendered from a 360 panorama."""

    yaw_deg: float
    pitch_deg: float
    fov_deg: float
    image: np.ndarray


@lru_cache(maxsize=128)
def perspective_remap(
    source_width: int,
    source_height: int,
    yaw_deg: float,
    pitch_deg: float,
    output_size: int = SCAN_TILE_SIZE,
    fov_deg: float = SCAN_FOV_DEG,
) -> tuple[np.ndarray, np.ndarray]:
    """Build an equirectangular-to-perspective map for one camera direction."""
    focal = (output_size / 2) / math.tan(math.radians(fov_deg) / 2)
    axis = (
        np.arange(output_size, dtype=np.float32) - (output_size - 1) / 2
    ) / focal
    ray_x, ray_y = np.meshgrid(axis, -axis)
    ray_z = np.ones_like(ray_x)
    length = np.sqrt(ray_x**2 + ray_y**2 + ray_z**2)
    ray_x /= length
    ray_y /= length
    ray_z /= length

    pitch = math.radians(pitch_deg)
    pitched_y = math.cos(pitch) * ray_y + math.sin(pitch) * ray_z
    pitched_z = -math.sin(pitch) * ray_y + math.cos(pitch) * ray_z

    yaw = math.radians(yaw_deg)
    world_x = math.cos(yaw) * ray_x + math.sin(yaw) * pitched_z
    world_z = -math.sin(yaw) * ray_x + math.cos(yaw) * pitched_z
    longitude = np.arctan2(world_x, world_z)
    latitude = np.arcsin(np.clip(pitched_y, -1.0, 1.0))

    # Longitude +pi and -pi are the same equirectangular seam.  Keep the map
    # inside the source image so callers never receive x == source_width.
    map_x = np.mod(
        ((longitude / (2 * math.pi)) + 0.5) * source_width,
        source_width,
    )
    map_y = (0.5 - latitude / math.pi) * source_height
    return map_x.astype(np.float32), map_y.astype(np.float32)


def render_spherical_views(
    panorama: np.ndarray,
    *,
    yaws: tuple[float, ...] = SCAN_YAWS,
    pitches: tuple[float, ...] = SCAN_PITCHES,
    output_size: int = SCAN_TILE_SIZE,
    fov_deg: float = SCAN_FOV_DEG,
) -> list[SphericalView]:
    """Render 8 yaw directions at three pitch levels (24 overlapping views)."""
    if panorama.ndim != 3 or panorama.shape[2] != 3:
        raise ValueError("panorama must be a BGR image")
    source_height, source_width = panorama.shape[:2]
    if source_width < 2 or source_height < 2:
        raise ValueError("panorama is too small")
    views: list[SphericalView] = []
    for pitch_deg in pitches:
        for yaw_deg in yaws:
            map_x, map_y = perspective_remap(
                source_width,
                source_height,
                yaw_deg,
                pitch_deg,
                output_size,
                fov_deg,
            )
            image = cv2.remap(
                panorama,
                map_x,
                map_y,
                cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_WRAP,
            )
            views.append(
                SphericalView(
                    yaw_deg=yaw_deg,
                    pitch_deg=pitch_deg,
                    fov_deg=fov_deg,
                    image=image,
                )
            )
    return views


def usable_view_score(image: np.ndarray) -> float:
    """Reject blank, extremely dark/bright, or sky-dominated detector inputs."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    brightness = float(gray.mean())
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    blue_sky = (
        (hsv[:, :, 0] >= 85)
        & (hsv[:, :, 0] <= 125)
        & (hsv[:, :, 1] >= 35)
        & (hsv[:, :, 2] >= 100)
    )
    sky_ratio = float(blue_sky.mean())
    exposure = max(0.0, 1.0 - abs(brightness - 128.0) / 128.0)
    detail = min(1.0, sharpness / 400.0)
    non_sky = max(0.0, 1.0 - sky_ratio)
    return max(0.0, min(1.0, 0.30 * exposure + 0.35 * detail + 0.35 * non_sky))
