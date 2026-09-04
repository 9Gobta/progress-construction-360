"""Retrieve geometrically verified drone views for a 3x2 cubemap image."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def _read_image(path: Path) -> np.ndarray | None:
    """Read images on Windows even when their path contains non-ASCII text."""
    try:
        encoded = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    if encoded.size == 0:
        return None
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR)


def _feature_image(image: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    scale = min(1.0, 1280.0 / max(height, width))
    if scale < 1.0:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return image


def _features(image: np.ndarray, sift: cv2.SIFT) -> tuple[list[cv2.KeyPoint], np.ndarray | None]:
    image = _feature_image(image)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return sift.detectAndCompute(gray, None)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cubemap", type=Path)
    parser.add_argument("drone_root", type=Path)
    parser.add_argument("reference", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--debug-output", type=Path)
    args = parser.parse_args()

    reference = json.loads(args.reference.read_text(encoding="utf-8"))
    names = [
        item["name"]
        for item in reference["photos"]
        if item.get("gimbal_pitch_deg") is not None
        and float(item["gimbal_pitch_deg"]) > -75.0
    ]
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
    sift = cv2.SIFT_create(nfeatures=5000, contrastThreshold=0.025)
    face_features = [_features(face, sift) for face in faces]
    matcher = cv2.BFMatcher(cv2.NORM_L2)
    results: list[dict[str, object]] = []
    for index, name in enumerate(names, start=1):
        image = _read_image(args.drone_root / name)
        if image is None:
            continue
        drone_keypoints, drone_descriptors = _features(image, sift)
        if drone_descriptors is None:
            continue
        best = {"face": -1, "good_matches": 0, "inliers": 0, "inlier_ratio": 0.0}
        for face_index, (face_keypoints, face_descriptors) in enumerate(face_features):
            if face_descriptors is None:
                continue
            pairs = matcher.knnMatch(face_descriptors, drone_descriptors, k=2)
            good = [first for first, second in pairs if first.distance < 0.72 * second.distance]
            inliers = 0
            if len(good) >= 8:
                source = np.float32([face_keypoints[item.queryIdx].pt for item in good])
                target = np.float32([drone_keypoints[item.trainIdx].pt for item in good])
                _matrix, mask = cv2.findHomography(source, target, cv2.USAC_MAGSAC, 4.0)
                inliers = int(mask.sum()) if mask is not None else 0
            ratio = inliers / max(len(good), 1)
            candidate = {
                "face": face_index,
                "good_matches": len(good),
                "inliers": inliers,
                "inlier_ratio": ratio,
            }
            if (inliers, ratio, len(good)) > (
                int(best["inliers"]),
                float(best["inlier_ratio"]),
                int(best["good_matches"]),
            ):
                best = candidate
        results.append({"name": name, **best})
        if index % 10 == 0:
            print(f"Processed {index}/{len(names)}")
    results.sort(
        key=lambda item: (int(item["inliers"]), float(item["inlier_ratio"]), int(item["good_matches"])),
        reverse=True,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results[:15], indent=2))

    if args.debug_output and results:
        top = results[0]
        face_index = int(top["face"])
        drone_image = _read_image(args.drone_root / str(top["name"]))
        if drone_image is not None and face_index >= 0:
            face_image = _feature_image(faces[face_index])
            drone_image = _feature_image(drone_image)
            face_keypoints, face_descriptors = _features(face_image, sift)
            drone_keypoints, drone_descriptors = _features(drone_image, sift)
            if face_descriptors is not None and drone_descriptors is not None:
                pairs = matcher.knnMatch(face_descriptors, drone_descriptors, k=2)
                good = [first for first, second in pairs if first.distance < 0.72 * second.distance]
                mask_values = [0] * len(good)
                if len(good) >= 8:
                    source = np.float32([face_keypoints[item.queryIdx].pt for item in good])
                    target = np.float32([drone_keypoints[item.trainIdx].pt for item in good])
                    _matrix, mask = cv2.findHomography(source, target, cv2.USAC_MAGSAC, 4.0)
                    if mask is not None:
                        mask_values = mask.ravel().astype(int).tolist()
                debug = cv2.drawMatches(
                    face_image,
                    face_keypoints,
                    drone_image,
                    drone_keypoints,
                    good,
                    None,
                    matchesMask=mask_values,
                    flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS,
                )
                args.debug_output.parent.mkdir(parents=True, exist_ok=True)
                extension = args.debug_output.suffix or ".jpg"
                ok, encoded = cv2.imencode(extension, debug)
                if ok:
                    encoded.tofile(args.debug_output)


if __name__ == "__main__":
    main()
