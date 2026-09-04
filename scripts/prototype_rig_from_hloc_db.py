"""Reconstruct an HLoc cubemap database with exact panorama rig constraints.

This evaluation script never writes application data.  It reuses the learned
feature matches from ``prototype_hloc_panorama_sfm.py`` and forces the four
perspective faces at each timestamp to share one optical centre.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
from pathlib import Path

import numpy as np
import pycolmap


def face_parts(name: str) -> tuple[str, int, str]:
    frame, face, timestamp = Path(name).stem.split("_")
    return frame, int(face), timestamp


def rotation_about_y(degrees: float) -> pycolmap.Rotation3d:
    half_angle = math.radians(degrees) / 2
    return pycolmap.Rotation3d(
        np.asarray([0.0, math.sin(half_angle), 0.0, math.cos(half_angle)])
    )


def prepare_rig_database(
    source_database: Path,
    source_images: Path,
    workspace: Path,
) -> tuple[Path, Path]:
    workspace.mkdir(parents=True, exist_ok=True)
    database_path = workspace / "database.db"
    image_path = workspace / "images"
    shutil.copy2(source_database, database_path)
    image_path.mkdir(parents=True, exist_ok=True)

    with pycolmap.Database.open(database_path) as database:
        source_camera = database.read_all_cameras()[0]
        camera_ids: list[int] = []
        for _face in range(4):
            camera = pycolmap.Camera(source_camera.todict())
            camera.camera_id = pycolmap.INVALID_CAMERA_ID
            camera_ids.append(database.write_camera(camera))

        for image in database.read_all_images():
            frame, face, timestamp = face_parts(image.name)
            renamed = f"{face}/{frame}_{timestamp}.jpg"
            destination = image_path / renamed
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_images / image.name, destination)
            image.name = renamed
            image.camera_id = camera_ids[face]
            database.update_image(image)

        cameras: list[pycolmap.RigConfigCamera] = []
        for face, yaw in enumerate((0.0, 90.0, 180.0, 270.0)):
            config = pycolmap.RigConfigCamera(
                image_prefix=f"{face}/",
                ref_sensor=face == 0,
            )
            if face:
                config.cam_from_rig = pycolmap.Rigid3d(
                    rotation_about_y(-yaw),
                    np.zeros(3, dtype=np.float64),
                )
            cameras.append(config)
        pycolmap.apply_rig_config(
            [pycolmap.RigConfig(cameras=cameras)],
            database,
        )
    return database_path, image_path


def summarize(model: pycolmap.Reconstruction, workspace: Path) -> None:
    frame_centres: dict[int, np.ndarray] = {}
    centre_spreads: list[float] = []
    for frame in model.frames.values():
        if not frame.has_pose:
            continue
        frame_images = [model.images[data_id.id] for data_id in frame.data_ids]
        timestamp = int(Path(frame_images[0].name).stem.split("_")[-1])
        image_centres = np.stack(
            [image.projection_center() for image in frame_images if image.has_pose]
        )
        centre_spreads.append(
            float(np.max(np.linalg.norm(image_centres - image_centres[0], axis=1)))
        )
        frame_centres[timestamp] = frame.rig_from_world.inverse().translation
    timestamps = sorted(frame_centres)
    ordered = np.stack([frame_centres[key] for key in timestamps])
    steps = np.linalg.norm(np.diff(ordered, axis=0), axis=1)
    centred = ordered - np.mean(ordered, axis=0)
    _u, singular_values, axes = np.linalg.svd(centred, full_matrices=False)
    route_2d = centred @ axes[:2].T
    report = {
        "registered_rig_frames": len(frame_centres),
        "first_timestamp_ms": timestamps[0],
        "last_timestamp_ms": timestamps[-1],
        "max_timestamp_gap_ms": int(np.max(np.diff(timestamps))),
        "same_timestamp_centre_spread_max": float(max(centre_spreads)),
        "step_median": float(np.median(steps)),
        "step_p95": float(np.percentile(steps, 95)),
        "step_max": float(np.max(steps)),
        "out_of_plane_ratio": float(
            singular_values[2] / singular_values[0] if singular_values[0] else 0.0
        ),
        "points3D": model.num_points3D(),
        "mean_reprojection_error_px": float(model.compute_mean_reprojection_error()),
        "trajectory": [
            {"timestamp_ms": timestamp, "xyz": frame_centres[timestamp].tolist()}
            for timestamp in timestamps
        ],
    }
    (workspace / "evaluation.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    np.savetxt(
        workspace / "trajectory_pca_xy.csv",
        np.column_stack((timestamps, route_2d)),
        delimiter=",",
        header="timestamp_ms,x,y",
        comments="",
    )
    print(model.summary())
    print(json.dumps({key: value for key, value in report.items() if key != "trajectory"}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("hloc_database", type=Path)
    parser.add_argument("source_images", type=Path)
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args()

    database, images = prepare_rig_database(
        args.hloc_database,
        args.source_images,
        args.workspace,
    )
    sparse = args.workspace / "sparse"
    sparse.mkdir(parents=True, exist_ok=True)
    options = pycolmap.IncrementalPipelineOptions()
    options.num_threads = 16
    options.min_model_size = 8
    options.ba_refine_sensor_from_rig = False
    options.ba_refine_focal_length = False
    options.ba_refine_extra_params = False
    options.mapper.init_min_num_inliers = 30
    options.mapper.abs_pose_min_num_inliers = 15
    models = pycolmap.incremental_mapping(
        database,
        images,
        sparse,
        options=options,
    )
    if not models:
        raise RuntimeError("Rig-constrained reconstruction produced no model")
    model = max(models.values(), key=lambda item: item.num_reg_frames())
    best = args.workspace / "best-model"
    best.mkdir(parents=True, exist_ok=True)
    model.write(best)
    summarize(model, args.workspace)


if __name__ == "__main__":
    main()
