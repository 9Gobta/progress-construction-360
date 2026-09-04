"""Localize perspective faces from a 360 cubemap in a georeferenced drone SfM map."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import pycolmap

INVALID_POINT3D_ID = np.iinfo(np.uint64).max


def _read_image(path: Path) -> np.ndarray | None:
    try:
        encoded = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR) if encoded.size else None


def _colmap_descriptor(descriptors: np.ndarray) -> np.ndarray:
    descriptors = descriptors.astype(np.float32)
    descriptors /= np.maximum(descriptors.sum(axis=1, keepdims=True), 1e-12)
    descriptors = np.sqrt(descriptors)
    return np.clip(np.rint(descriptors * 512.0), 0, 255).astype(np.uint8)


def _site_position(center: np.ndarray, georeference: dict[str, object]) -> dict[str, float]:
    similarity = georeference["colmap_to_reality_similarity"]
    scale = float(similarity["scale"])
    rotation = np.asarray(similarity["rotation"], dtype=np.float64)
    translation = np.asarray(similarity["translation"], dtype=np.float64)
    reality = scale * (rotation @ center) + translation
    affine = np.asarray(georeference["reality_xy_to_site_enu_affine"], dtype=np.float64)
    east, north = np.asarray([reality[0], reality[1], 1.0]) @ affine
    site = georeference["site_wgs84"]
    latitude = float(site["latitude"]) + north / 110_540.0
    longitude = float(site["longitude"]) + east / (
        111_320.0 * np.cos(np.radians(float(site["latitude"])))
    )
    return {
        "east_m": float(east),
        "north_m": float(north),
        "reality_x": float(reality[0]),
        "reality_y": float(reality[1]),
        "reality_z": float(reality[2]),
        "latitude": latitude,
        "longitude": longitude,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cubemap", type=Path)
    parser.add_argument("database", type=Path)
    parser.add_argument("model", type=Path)
    parser.add_argument("georeference", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    cubemap = _read_image(args.cubemap)
    if cubemap is None:
        raise SystemExit(f"Cannot read {args.cubemap}")
    face_height = cubemap.shape[0] // 2
    face_width = cubemap.shape[1] // 3
    faces = [
        cubemap[row * face_height : (row + 1) * face_height, col * face_width : (col + 1) * face_width]
        for row in range(2)
        for col in range(3)
    ]
    reconstruction = pycolmap.Reconstruction(str(args.model))
    database = pycolmap.Database.open(str(args.database))
    image_rows = {item.name: item for item in database.read_all_images()}
    reference_descriptors: dict[int, np.ndarray] = {}
    for image in reconstruction.images.values():
        row = image_rows.get(image.name)
        if row is not None:
            reference_descriptors[int(image.image_id)] = database.read_descriptors(row.image_id)
    database.close()

    sift = cv2.SIFT_create(nfeatures=6000, contrastThreshold=0.012)
    matcher = cv2.BFMatcher(cv2.NORM_L2)
    estimation = pycolmap.AbsolutePoseEstimationOptions()
    estimation.ransac.max_error = 6.0
    estimation.ransac.min_inlier_ratio = 0.08
    refinement = pycolmap.AbsolutePoseRefinementOptions()
    results: list[dict[str, object]] = []
    georeference = json.loads(args.georeference.read_text(encoding="utf-8"))

    for face_index, face in enumerate(faces):
        gray = cv2.cvtColor(face, cv2.COLOR_BGR2GRAY)
        keypoints, descriptors = sift.detectAndCompute(gray, None)
        if descriptors is None:
            continue
        query_descriptors = _colmap_descriptor(descriptors)
        candidates: dict[int, tuple[float, int, int]] = {}
        for image in reconstruction.images.values():
            drone_descriptors = reference_descriptors.get(int(image.image_id))
            if drone_descriptors is None:
                continue
            pairs = matcher.knnMatch(query_descriptors, drone_descriptors, k=2)
            for first, second in pairs:
                if first.distance >= 0.72 * second.distance:
                    continue
                point = image.points2D[first.trainIdx]
                if not point.has_point3D():
                    continue
                point_id = int(point.point3D_id)
                previous = candidates.get(first.queryIdx)
                candidate = (float(first.distance), point_id, int(image.image_id))
                if previous is None or candidate[0] < previous[0]:
                    candidates[first.queryIdx] = candidate
        # Enforce one-to-one 2D-to-3D correspondences before PnP.
        unique: dict[int, tuple[int, float, int]] = {}
        for query_index, (distance, point_id, image_id) in candidates.items():
            previous = unique.get(point_id)
            candidate = (query_index, distance, image_id)
            if previous is None or distance < previous[1]:
                unique[point_id] = candidate
        if len(unique) < 8:
            results.append({"face": face_index, "correspondences": len(unique), "localized": False})
            continue
        points2D = np.asarray(
            [keypoints[item[0]].pt for item in unique.values()], dtype=np.float64
        )
        points3D = np.asarray(
            [reconstruction.points3D[point_id].xyz for point_id in unique], dtype=np.float64
        )
        camera = pycolmap.Camera(
            model="PINHOLE",
            width=face.shape[1],
            height=face.shape[0],
            params=[face.shape[1] / 2.0, face.shape[1] / 2.0, face.shape[1] / 2.0, face.shape[0] / 2.0],
        )
        pose = pycolmap.estimate_and_refine_absolute_pose(
            points2D,
            points3D,
            camera,
            estimation,
            refinement,
        )
        if pose is None:
            results.append({"face": face_index, "correspondences": len(unique), "localized": False})
            continue
        cam_from_world = pose["cam_from_world"]
        center = np.asarray(cam_from_world.inverse().translation, dtype=np.float64)
        inliers = int(pose["num_inliers"])
        results.append(
            {
                "face": face_index,
                "correspondences": len(unique),
                "localized": inliers >= 12,
                "inliers": inliers,
                "inlier_ratio": inliers / len(unique),
                "colmap_center": center.tolist(),
                "site_position": _site_position(center, georeference),
            }
        )
    results.sort(key=lambda item: int(item.get("inliers", 0)), reverse=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
