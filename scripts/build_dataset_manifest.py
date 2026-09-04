"""Build a reproducible inventory for source construction data without modifying it."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".lrv", ".insv"}
CHUNK_SIZE = 8 * 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def probe_video(path: Path, ffprobe: str | None) -> dict[str, Any] | None:
    if ffprobe is None or path.suffix.lower() not in VIDEO_EXTENSIONS:
        return None

    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration,format_name:stream=index,codec_type,codec_name,width,height,r_frame_rate",
        "-of",
        "json",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, UnicodeDecodeError) as exc:
        return {"probe_status": "failed", "error_type": type(exc).__name__}

    payload = json.loads(completed.stdout)
    video_stream = next(
        (stream for stream in payload.get("streams", []) if stream.get("codec_type") == "video"),
        None,
    )
    format_data = payload.get("format", {})
    return {
        "probe_status": "ok",
        "format_name": format_data.get("format_name"),
        "duration_seconds": (
            round(float(format_data["duration"]), 3) if format_data.get("duration") else None
        ),
        "codec": video_stream.get("codec_name") if video_stream else None,
        "width": video_stream.get("width") if video_stream else None,
        "height": video_stream.get("height") if video_stream else None,
        "frame_rate": video_stream.get("r_frame_rate") if video_stream else None,
    }


def classify(path: Path) -> str:
    extension = path.suffix.lower()
    if extension in VIDEO_EXTENSIONS:
        return "video"
    if extension == ".pdf":
        return "drawing_or_document"
    if extension in {".xlsx", ".csv", ".mpp"}:
        return "schedule"
    if extension in {".rvt", ".ifc"}:
        return "bim"
    return "other"


def build_manifest(data_dir: Path) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    files: list[dict[str, Any]] = []

    for path in sorted(item for item in data_dir.rglob("*") if item.is_file()):
        stat = path.stat()
        relative_path = path.relative_to(data_dir).as_posix()
        item: dict[str, Any] = {
            "relative_path": relative_path,
            "capture_date_hint": path.relative_to(data_dir).parts[0]
            if path.relative_to(data_dir).parts[0].isdigit()
            else None,
            "extension": path.suffix.lower(),
            "kind": classify(path),
            "size_bytes": stat.st_size,
            "modified_at_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            "sha256": sha256_file(path),
        }
        video = probe_video(path, ffprobe)
        if video is not None:
            item["video"] = video
        files.append(item)

    return {
        "manifest_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_root": "Data",
        "source_policy": "read_only",
        "ffprobe_available": ffprobe is not None,
        "summary": {
            "file_count": len(files),
            "total_size_bytes": sum(item["size_bytes"] for item in files),
            "by_kind": {
                kind: sum(1 for item in files if item["kind"] == kind)
                for kind in sorted({item["kind"] for item in files})
            },
        },
        "files": files,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("Data"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("ml/datasets/source-inventory.json"),
    )
    args = parser.parse_args()

    data_dir = args.data_dir.resolve()
    if not data_dir.is_dir():
        raise SystemExit(f"Data directory not found: {data_dir}")

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(data_dir)
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {manifest['summary']['file_count']} files "
        f"({manifest['summary']['total_size_bytes']} bytes) to {output}"
    )


if __name__ == "__main__":
    main()

