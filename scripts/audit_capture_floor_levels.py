"""Create evenly sampled contact sheets for auditing Capture floor labels."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


def contact_sheet(source: Path, destination: Path, samples: int = 5) -> None:
    video = cv2.VideoCapture(str(source))
    if not video.isOpened():
        raise RuntimeError(f"Cannot open {source}")
    frames = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = float(video.get(cv2.CAP_PROP_FPS))
    selected: list[np.ndarray] = []
    for frame_index in np.linspace(0, max(0, frames - 1), samples, dtype=int):
        video.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
        ok, frame = video.read()
        if not ok:
            continue
        height, width = frame.shape[:2]
        resized = cv2.resize(frame, (720, round(height * 720 / width)))
        seconds = frame_index / max(fps, 1e-9)
        cv2.putText(
            resized,
            f"{seconds:.1f}s",
            (18, 38),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )
        selected.append(resized)
    video.release()
    if not selected:
        raise RuntimeError(f"No frames decoded from {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(destination), np.hstack(selected))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--samples", type=int, default=5)
    args = parser.parse_args()
    contact_sheet(args.source, args.destination, args.samples)


if __name__ == "__main__":
    main()
