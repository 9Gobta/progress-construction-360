"""Prototype 360 video trajectory recovery with COLMAP structure-from-motion."""

from __future__ import annotations

import argparse
import math
import os
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
import pycolmap


def perspective_map(
    pano_width: int,
    pano_height: int,
    *,
    yaw_deg: float,
    size: int,
    fov_deg: float = 100.0,
) -> tuple[np.ndarray, np.ndarray]:
    focal = (size / 2) / math.tan(math.radians(fov_deg) / 2)
    axis = (np.arange(size, dtype=np.float32) - (size - 1) / 2) / focal
    grid_x, grid_y = np.meshgrid(axis, -axis)
    ray_z = np.ones_like(grid_x)
    length = np.sqrt(grid_x**2 + grid_y**2 + ray_z**2)
    ray_x = grid_x / length
    ray_y = grid_y / length
    ray_z /= length
    yaw = math.radians(yaw_deg)
    world_x = math.cos(yaw) * ray_x + math.sin(yaw) * ray_z
    world_z = -math.sin(yaw) * ray_x + math.cos(yaw) * ray_z
    longitude = np.arctan2(world_x, world_z)
    latitude = np.arcsin(np.clip(ray_y, -1.0, 1.0))
    map_x = ((longitude / (2 * math.pi)) + 0.5) * pano_width
    map_y = (0.5 - latitude / math.pi) * pano_height
    return map_x.astype(np.float32), map_y.astype(np.float32)


def extract_panoramas(video: Path, output: Path, interval_seconds: int) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    ffmpeg = os.environ.get("FFMPEG_BINARY") or shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg was not found; set FFMPEG_BINARY to ffmpeg.exe")
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-v",
            "error",
            "-i",
            str(video),
            "-vf",
            f"fps=1/{interval_seconds},scale=1920:960",
            "-q:v",
            "3",
            str(output / "%04d.jpg"),
        ],
        check=True,
    )
    return sorted(output.glob("*.jpg"))


def render_faces(panoramas: list[Path], output: Path, interval_seconds: int) -> None:
    output.mkdir(parents=True, exist_ok=True)
    maps = [
        perspective_map(1920, 960, yaw_deg=yaw, size=512)
        for yaw in (0.0, 90.0, 180.0, 270.0)
    ]
    for frame_index, panorama_path in enumerate(panoramas):
        panorama = cv2.imread(str(panorama_path))
        if panorama is None:
            continue
        timestamp_ms = frame_index * interval_seconds * 1000
        for face_index, (map_x, map_y) in enumerate(maps):
            face = cv2.remap(
                panorama,
                map_x,
                map_y,
                cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_WRAP,
            )
            cv2.imwrite(str(output / f"{frame_index:04d}_{face_index}_{timestamp_ms}.jpg"), face)


def reconstruct(images: Path, workspace: Path) -> dict[int, pycolmap.Reconstruction]:
    database = workspace / "database.db"
    sparse = workspace / "sparse"
    sparse.mkdir(parents=True, exist_ok=True)
    extraction = pycolmap.FeatureExtractionOptions()
    extraction.max_image_size = 1024
    extraction.num_threads = 4
    extraction.use_gpu = False
    pycolmap.extract_features(
        database,
        images,
        camera_mode=pycolmap.CameraMode.SINGLE,
        camera_model="PINHOLE",
        extraction_options=extraction,
        device=pycolmap.Device.cpu,
    )
    pairing = pycolmap.SequentialPairingOptions()
    pairing.overlap = 12
    matching = pycolmap.FeatureMatchingOptions()
    matching.num_threads = 4
    matching.use_gpu = False
    pycolmap.match_sequential(
        database,
        matching_options=matching,
        pairing_options=pairing,
        device=pycolmap.Device.cpu,
    )
    options = pycolmap.IncrementalPipelineOptions()
    options.num_threads = 4
    options.min_model_size = 8
    options.mapper.init_min_num_inliers = 40
    options.mapper.abs_pose_min_num_inliers = 20
    return pycolmap.incremental_mapping(database, images, sparse, options=options)


def print_trajectory(reconstruction: pycolmap.Reconstruction) -> None:
    centers: dict[int, list[np.ndarray]] = defaultdict(list)
    for image in reconstruction.images.values():
        timestamp_ms = int(image.name.rsplit("_", 1)[1].split(".", 1)[0])
        centers[timestamp_ms].append(image.cam_from_world().inverse().translation)
    for timestamp_ms in sorted(centers):
        center = np.median(np.stack(centers[timestamp_ms]), axis=0)
        print(
            timestamp_ms,
            len(centers[timestamp_ms]),
            *(round(float(value), 5) for value in center),
            sep=",",
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--interval", type=int, default=5)
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Extract panoramas and perspective faces without running legacy COLMAP SfM.",
    )
    args = parser.parse_args()
    args.workspace.mkdir(parents=True, exist_ok=True)
    panoramas = extract_panoramas(args.video, args.workspace / "panoramas", args.interval)
    render_faces(panoramas, args.workspace / "faces", args.interval)
    if args.prepare_only:
        print(f"panoramas={len(panoramas)}")
        print(f"faces={len(list((args.workspace / 'faces').glob('*.jpg')))}")
        return
    reconstructions = reconstruct(args.workspace / "faces", args.workspace)
    if not reconstructions:
        raise RuntimeError("COLMAP could not reconstruct a camera trajectory")
    reconstruction = max(reconstructions.values(), key=lambda item: item.num_reg_images())
    print(reconstruction.summary())
    print_trajectory(reconstruction)


if __name__ == "__main__":
    main()
