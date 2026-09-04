"""Render six overlapping horizontal pinhole views from a 2:1 panorama."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import cv2
import numpy as np


def read_image(path: Path) -> np.ndarray:
    encoded = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR) if encoded.size else None
    if image is None:
        raise SystemExit(f"Cannot read {path}")
    return image


def render(panorama: np.ndarray, yaw_deg: float, size: int, fov_deg: float) -> np.ndarray:
    height, width = panorama.shape[:2]
    focal = (size / 2) / math.tan(math.radians(fov_deg) / 2)
    axis = (np.arange(size, dtype=np.float32) - (size - 1) / 2) / focal
    grid_x, grid_y = np.meshgrid(axis, -axis)
    ray_z = np.ones_like(grid_x)
    length = np.sqrt(grid_x**2 + grid_y**2 + ray_z**2)
    ray_x, ray_y, ray_z = grid_x / length, grid_y / length, ray_z / length
    yaw = math.radians(yaw_deg)
    world_x = math.cos(yaw) * ray_x + math.sin(yaw) * ray_z
    world_z = -math.sin(yaw) * ray_x + math.cos(yaw) * ray_z
    longitude = np.arctan2(world_x, world_z)
    latitude = np.arcsin(np.clip(ray_y, -1.0, 1.0))
    map_x = (((longitude / (2 * math.pi)) + 0.5) * width).astype(np.float32)
    map_y = ((0.5 - latitude / math.pi) * height).astype(np.float32)
    return cv2.remap(panorama, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--size", type=int, default=768)
    parser.add_argument("--fov", type=float, default=90.0)
    args = parser.parse_args()
    panorama = read_image(args.source)
    faces = [render(panorama, yaw, args.size, args.fov) for yaw in range(0, 360, 60)]
    cubemap = np.vstack([np.hstack(faces[:3]), np.hstack(faces[3:])])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    success, encoded = cv2.imencode(args.output.suffix or ".jpg", cubemap)
    if not success:
        raise SystemExit("Could not encode output")
    encoded.tofile(args.output)
    print(args.output)


if __name__ == "__main__":
    main()
