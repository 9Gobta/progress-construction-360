"""Prototype learned-feature 360 trajectory reconstruction with HLoc.

This is an evaluation tool. It never writes Capture or CameraPose rows.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from itertools import pairwise
from pathlib import Path

import numpy as np
import pycolmap
from progress_api.services.learned_relocalization import _activate_runtime


def image_parts(path: Path) -> tuple[int, int, int]:
    frame, face, timestamp = path.stem.split("_")
    return int(frame), int(face), int(timestamp)


def select_images(image_dir: Path, maximum_timestamp_ms: int | None) -> list[Path]:
    images = sorted(image_dir.glob("*.jpg"), key=image_parts)
    if maximum_timestamp_ms is not None:
        images = [image for image in images if image_parts(image)[2] <= maximum_timestamp_ms]
    if len(images) < 16:
        raise RuntimeError("Not enough cubemap faces for learned reconstruction")
    return images


def write_sequence_pairs(images: list[Path], destination: Path) -> int:
    by_frame_face = {(image_parts(path)[0], image_parts(path)[1]): path for path in images}
    face_count = max(face for _frame, face in by_frame_face) + 1
    pairs: set[tuple[str, str]] = set()
    for (frame, face), source in by_frame_face.items():
        targets = [
            (frame, (face + 1) % face_count),
            (frame + 1, face),
            (frame + 2, face),
            (frame + 1, (face + 1) % face_count),
            (frame + 1, (face - 1) % face_count),
        ]
        for key in targets:
            target = by_frame_face.get(key)
            if target is None:
                continue
            pair = tuple(sorted((source.name, target.name)))
            if pair[0] != pair[1]:
                pairs.add(pair)
    destination.write_text(
        "\n".join(f"{first} {second}" for first, second in sorted(pairs)) + "\n",
        encoding="utf-8",
    )
    return len(pairs)


def summarize(reconstruction: pycolmap.Reconstruction, input_images: list[Path]) -> None:
    timestamps: dict[int, list[np.ndarray]] = defaultdict(list)
    for image in reconstruction.images.values():
        _frame, _face, timestamp = image_parts(Path(image.name))
        timestamps[timestamp].append(image.cam_from_world().inverse().translation)
    input_timestamps = sorted({image_parts(path)[2] for path in input_images})
    covered = sorted(timestamps)
    gaps = [second - first for first, second in pairwise(covered)]
    print(reconstruction.summary())
    print(f"input_timestamps={len(input_timestamps)}")
    print(f"registered_timestamps={len(covered)}")
    print(f"coverage={len(covered) / len(input_timestamps):.4f}")
    print(f"maximum_gap_ms={max(gaps, default=0)}")
    print(f"first_timestamp_ms={covered[0] if covered else -1}")
    print(f"last_timestamp_ms={covered[-1] if covered else -1}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image_dir", type=Path)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--maximum-seconds", type=int)
    args = parser.parse_args()

    _activate_runtime()
    from hloc import extract_features, match_features, reconstruction

    images = select_images(
        args.image_dir,
        args.maximum_seconds * 1000 if args.maximum_seconds is not None else None,
    )
    args.workspace.mkdir(parents=True, exist_ok=True)
    pairs = args.workspace / "sequence-pairs.txt"
    print(f"pairs={write_sequence_pairs(images, pairs)}")
    image_names = [image.name for image in images]
    features = extract_features.main(
        extract_features.confs["disk"],
        args.image_dir,
        args.workspace,
        image_list=image_names,
    )
    matches = match_features.main(
        match_features.confs["disk+lightglue"],
        pairs,
        features,
        matches=args.workspace / "matches-disk-lightglue.h5",
    )
    model = reconstruction.main(
        args.workspace / "sfm",
        args.image_dir,
        pairs,
        features,
        matches,
        camera_mode=pycolmap.CameraMode.SINGLE,
        image_list=image_names,
        image_options={"camera_model": "PINHOLE"},
        mapper_options={
            "min_model_size": 8,
            "mapper": {
                "init_min_num_inliers": 30,
                "abs_pose_min_num_inliers": 15,
            },
        },
    )
    if model is None:
        raise RuntimeError("HLoc could not reconstruct a camera trajectory")
    best_model = args.workspace / "best-model"
    best_model.mkdir(parents=True, exist_ok=True)
    model.write(best_model)
    summarize(model, images)


if __name__ == "__main__":
    main()
