"""Reconstruct a relative camera path from already extracted 360 keyframes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))

from progress_api.services.sfm_localization import (
    _raw_samples,
    _reconstruct,
    _render_faces,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("keyframes", type=Path)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    panoramas = sorted(args.keyframes.glob("*.jpg"))
    if len(panoramas) < 8:
        raise SystemExit("At least eight keyframes are required")
    args.workspace.mkdir(parents=True, exist_ok=True)
    faces = args.workspace / "faces"
    _render_faces(panoramas, faces)
    reconstruction = _reconstruct(faces, args.workspace)
    samples = _raw_samples(reconstruction, {})
    payload = {
        "panoramas": len(panoramas),
        "registered_images": reconstruction.num_reg_images(),
        "points3D": reconstruction.num_points3D(),
        "samples": [
            {
                "timestamp_ms": sample.timestamp_ms,
                "x": sample.x,
                "y": sample.y,
                "relative_z": sample.relative_z,
                "heading_deg": sample.heading_deg,
                "confidence": sample.confidence,
            }
            for sample in samples
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in payload.items() if key != "samples"}, indent=2))
    print(f"samples={len(samples)} output={args.output}")


if __name__ == "__main__":
    main()
