"""Build a reusable COLMAP map from the georeferenced project drone survey."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import cv2
import numpy as np
import pycolmap


def _read_image(path: Path) -> np.ndarray | None:
    try:
        encoded = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR) if encoded.size else None


def _write_image(path: Path, image: np.ndarray) -> None:
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError(f"Cannot encode {path.name}")
    encoded.tofile(path)


def _prepare_images(
    source_root: Path,
    image_root: Path,
    names: list[str],
    *,
    max_size: int,
) -> None:
    image_root.mkdir(parents=True, exist_ok=True)
    for index, name in enumerate(names, start=1):
        destination = image_root / name
        if destination.is_file() and destination.stat().st_size > 0:
            continue
        image = _read_image(source_root / name)
        if image is None:
            raise RuntimeError(f"Cannot read drone photo: {source_root / name}")
        height, width = image.shape[:2]
        scale = min(1.0, max_size / max(height, width))
        if scale < 1.0:
            image = cv2.resize(
                image,
                None,
                fx=scale,
                fy=scale,
                interpolation=cv2.INTER_AREA,
            )
        _write_image(destination, image)
        if index % 20 == 0 or index == len(names):
            print(f"Prepared {index}/{len(names)} images", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("drone_root", type=Path)
    parser.add_argument("reference", type=Path)
    parser.add_argument("output_root", type=Path)
    parser.add_argument("--max-size", type=int, default=1600)
    parser.add_argument("--overlap", type=int, default=8)
    parser.add_argument("--max-features", type=int, default=4000)
    parser.add_argument("--oblique-only", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()

    reference = json.loads(args.reference.read_text(encoding="utf-8"))
    selected = reference["photos"]
    if args.oblique_only:
        selected = [
            item
            for item in selected
            if item.get("gimbal_pitch_deg") is not None
            and float(item["gimbal_pitch_deg"]) > -75.0
        ]
    names = [str(item["name"]) for item in selected]
    image_root = args.output_root / "images"
    database_path = args.output_root / "database.db"
    model_root = args.output_root / "models"
    features_marker = args.output_root / "features.done"
    matches_marker = args.output_root / "matches.done"
    if args.rebuild and args.output_root.exists():
        shutil.rmtree(args.output_root)
    args.output_root.mkdir(parents=True, exist_ok=True)
    _prepare_images(
        args.drone_root,
        image_root,
        names,
        max_size=max(640, args.max_size),
    )

    if not features_marker.exists():
        extraction = pycolmap.FeatureExtractionOptions()
        extraction.max_image_size = max(640, args.max_size)
        extraction.sift.max_num_features = max(1000, args.max_features)
        extraction.sift.peak_threshold = 0.012
        pycolmap.extract_features(
            database_path=str(database_path),
            image_path=str(image_root),
            image_names=names,
            camera_mode=pycolmap.CameraMode.SINGLE,
            camera_model="OPENCV",
            extraction_options=extraction,
            device=pycolmap.Device.cpu,
        )
        features_marker.write_text("ok\n", encoding="utf-8")

    if not matches_marker.exists():
        database = pycolmap.Database.open(str(database_path))
        database.clear_matches()
        database.clear_two_view_geometries()
        database.close()
        matching = pycolmap.FeatureMatchingOptions()
        matching.guided_matching = False
        pairing = pycolmap.SequentialPairingOptions()
        pairing.overlap = max(2, args.overlap)
        pairing.quadratic_overlap = True
        pairing.loop_detection = False
        pycolmap.match_sequential(
            database_path=str(database_path),
            matching_options=matching,
            pairing_options=pairing,
            device=pycolmap.Device.cpu,
        )
        matches_marker.write_text("ok\n", encoding="utf-8")

    existing_models = list(model_root.glob("*/images.bin")) if model_root.exists() else []
    if not existing_models:
        model_root.mkdir(parents=True, exist_ok=True)
        options = pycolmap.IncrementalPipelineOptions()
        options.min_model_size = 20
        options.multiple_models = False
        options.mapper.abs_pose_min_num_inliers = 20
        options.mapper.abs_pose_min_inlier_ratio = 0.15
        reconstructions = pycolmap.incremental_mapping(
            database_path=str(database_path),
            image_path=str(image_root),
            output_path=str(model_root),
            options=options,
        )
    else:
        reconstructions = {
            int(path.parent.name): pycolmap.Reconstruction(str(path.parent))
            for path in existing_models
        }

    summary = []
    for model_id, reconstruction in reconstructions.items():
        summary.append(
            {
                "model_id": int(model_id),
                "registered_images": int(reconstruction.num_reg_images()),
                "points3D": int(reconstruction.num_points3D()),
            }
        )
    summary.sort(key=lambda item: item["registered_images"], reverse=True)
    (args.output_root / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
