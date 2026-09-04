"""Fit a COLMAP drone reconstruction to RealityScan and site ENU coordinates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pycolmap


def _similarity(source: np.ndarray, target: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    source_mean = source.mean(axis=0)
    target_mean = target.mean(axis=0)
    source_centered = source - source_mean
    target_centered = target - target_mean
    covariance = target_centered.T @ source_centered / len(source)
    left, singular, right_t = np.linalg.svd(covariance)
    sign = np.ones(3)
    if np.linalg.det(left @ right_t) < 0:
        sign[-1] = -1.0
    rotation = left @ np.diag(sign) @ right_t
    variance = float(np.mean(np.sum(source_centered * source_centered, axis=1)))
    if variance <= 1e-12:
        raise ValueError("Degenerate source camera positions")
    scale = float(np.sum(singular * sign) / variance)
    translation = target_mean - scale * (rotation @ source_mean)
    return scale, rotation, translation


def _transform(
    points: np.ndarray, scale: float, rotation: np.ndarray, translation: np.ndarray
) -> np.ndarray:
    return (scale * (rotation @ points.T)).T + translation


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model", type=Path)
    parser.add_argument("reference", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threshold-m", type=float, default=2.0)
    args = parser.parse_args()

    reconstruction = pycolmap.Reconstruction(str(args.model))
    reference = json.loads(args.reference.read_text(encoding="utf-8"))
    by_name = {str(item["name"]): item for item in reference["photos"]}
    names: list[str] = []
    source: list[np.ndarray] = []
    target: list[np.ndarray] = []
    for image in reconstruction.images.values():
        item = by_name.get(image.name)
        if item is None or item.get("reality_z") is None:
            continue
        names.append(image.name)
        source.append(np.asarray(image.projection_center(), dtype=np.float64))
        target.append(
            np.asarray(
                [item["reality_x"], item["reality_y"], item["reality_z"]],
                dtype=np.float64,
            )
        )
    source_array = np.asarray(source)
    target_array = np.asarray(target)
    if len(source_array) < 4:
        raise SystemExit("Need at least four shared camera positions")

    rng = np.random.default_rng(20260826)
    best_inliers = np.zeros(len(source_array), dtype=bool)
    best_error = float("inf")
    for _ in range(2000):
        indices = rng.choice(len(source_array), size=3, replace=False)
        try:
            scale, rotation, translation = _similarity(
                source_array[indices], target_array[indices]
            )
        except (ValueError, np.linalg.LinAlgError):
            continue
        residuals = np.linalg.norm(
            _transform(source_array, scale, rotation, translation) - target_array,
            axis=1,
        )
        inliers = residuals <= args.threshold_m
        error = float(np.mean(residuals[inliers])) if inliers.any() else float("inf")
        if (int(inliers.sum()), -error) > (int(best_inliers.sum()), -best_error):
            best_inliers = inliers
            best_error = error
    if int(best_inliers.sum()) < 4:
        raise SystemExit("Could not georeference the reconstruction reliably")
    scale, rotation, translation = _similarity(
        source_array[best_inliers], target_array[best_inliers]
    )
    residuals = np.linalg.norm(
        _transform(source_array, scale, rotation, translation) - target_array,
        axis=1,
    )
    inliers = residuals <= args.threshold_m
    affine = reference["reality_xy_to_site_enu_affine"]
    result = {
        "model_path": str(args.model),
        "shared_cameras": len(names),
        "inlier_cameras": int(inliers.sum()),
        "rmse_m": float(np.sqrt(np.mean(np.square(residuals[inliers])))),
        "median_error_m": float(np.median(residuals[inliers])),
        "p95_error_m": float(np.percentile(residuals[inliers], 95)),
        "colmap_to_reality_similarity": {
            "scale": scale,
            "rotation": rotation.tolist(),
            "translation": translation.tolist(),
        },
        "reality_xy_to_site_enu_affine": affine,
        "site_wgs84": reference["site_wgs84"],
        "camera_errors": [
            {"name": name, "error_m": float(error), "inlier": bool(inlier)}
            for name, error, inlier in zip(names, residuals, inliers, strict=True)
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({key: result[key] for key in [
        "shared_cameras", "inlier_cameras", "rmse_m", "median_error_m", "p95_error_m"
    ]}, indent=2))


if __name__ == "__main__":
    main()
