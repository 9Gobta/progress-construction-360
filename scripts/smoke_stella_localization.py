from __future__ import annotations

import argparse
import json
import math
import sys
from itertools import pairwise
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
API_SOURCE = REPOSITORY_ROOT / "apps" / "api" / "src"
sys.path.insert(0, str(API_SOURCE))

from progress_api.services.stella_localization import recover_stella_path
from progress_api.services.video_pipeline import _probe


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Stella VSLAM against a real 360 video and report pose quality."
    )
    parser.add_argument("video", type=Path)
    parser.add_argument("--duration-seconds", type=float)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / ".runtime" / "stella-smoke-result.json",
    )
    args = parser.parse_args()

    source = args.video.resolve()
    payload, stream = _probe(source)
    duration_seconds = args.duration_seconds or float(
        stream.get("duration") or payload.get("format", {}).get("duration") or 0
    )
    if duration_seconds <= 0:
        raise RuntimeError("Video duration is unavailable")
    samples = recover_stella_path(
        source,
        end_timestamp_ms=round(duration_seconds * 1000),
    )
    distances = [
        math.hypot(current.x - previous.x, current.y - previous.y)
        for previous, current in pairwise(samples)
    ]
    result = {
        "video": str(source),
        "duration_seconds": duration_seconds,
        "sample_count": len(samples),
        "mean_confidence": sum(item.confidence for item in samples) / len(samples),
        "path_length_slam_units": sum(distances),
        "largest_step_slam_units": max(distances, default=0.0),
        "start": samples[0].__dict__,
        "end": samples[-1].__dict__,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
