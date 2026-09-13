from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from pathlib import Path, PurePath

import cv2
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from progress_api.config import get_settings
from progress_api.models import Capture, Keyframe, MediaFile, ProcessingJob, VideoMetadata
from progress_api.models.base import utc_now
from progress_api.object_storage import download_media_file, upload_file
from progress_api.services.insta360_stitching import (
    Insta360StitcherUnavailable,
    get_stitcher_executable,
    stitch_insv,
)
from progress_api.services.localization import save_camera_poses
from progress_api.services.temporary_workspace import temporary_workspace
from progress_api.worker import celery_app

CAPTURE_FRAME_FPS = 2
# Keep the normal one-second station cadence after localization. Only adjacent
# candidates at exactly the same mapped position are collapsed; dense
# keyframes remain available for review.
WARP_POINT_INTERVAL_SECONDS = 1
SPATIAL_STATION_INTERVAL_SECONDS = 4
SPATIAL_STATION_MAX_GAP_SECONDS = 6
SPATIAL_VISIBLE_PORTAL_LIMIT = 20
PROXY_WIDTH = 1920
PROXY_HEIGHT = 960
# Tracking stays on a light proxy, while selected tour stations keep enough
# detail for a crisp panorama on desktop displays.  4096 is also a safe WebGL
# texture size on substantially more devices than the camera's native 8K.
TOUR_MAX_WIDTH = 4096
MIN_KEYFRAME_SHARPNESS = 25.0


class VideoPipelineError(RuntimeError):
    pass


def measure_keyframe_quality(path: Path) -> tuple[str, float]:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        return "REJECTED", 0.0
    brightness = float(image.mean())
    sharpness = float(cv2.Laplacian(image, cv2.CV_64F).var())
    if brightness < 18.0 or brightness > 238.0:
        return "REJECTED", sharpness
    return ("USABLE" if sharpness >= MIN_KEYFRAME_SHARPNESS else "BLURRY"), sharpness


def classify_keyframe_quality(path: Path) -> str:
    return measure_keyframe_quality(path)[0]


def select_warp_points(quality: list[tuple[str, float]]) -> set[int]:
    """Pick one clear still per window while retaining every still for navigation."""
    if not quality:
        return set()
    window_size = CAPTURE_FRAME_FPS * WARP_POINT_INTERVAL_SECONDS
    status_rank = {"REJECTED": 0, "BLURRY": 1, "USABLE": 2}
    selected: set[int] = set()
    for start in range(0, len(quality), window_size):
        stop = min(start + window_size, len(quality))
        selected.add(
            max(
                range(start, stop),
                key=lambda index: (status_rank[quality[index][0]], quality[index][1]),
            )
        )
    # The tour must always open at the actual beginning and retain its final
    # position. Quality-based selection may otherwise start half a second late
    # or omit the endpoint when a neighbouring still is sharper.
    selected.update({0, len(quality) - 1})
    return selected


@dataclass(frozen=True)
class TourStationSample:
    frame_index: int
    timestamp_ms: int
    quality_status: str
    x: float | None
    y: float | None
    heading_deg: float | None


def remove_consecutive_duplicate_warp_points(
    samples: list[TourStationSample],
    candidates: set[int],
) -> set[int]:
    """Keep the dense cadence while removing only identical adjacent places."""
    selected: set[int] = set()
    candidate_samples = [sample for sample in samples if sample.frame_index in candidates]
    last_position: tuple[float, float] | None = None
    for sample in candidate_samples:
        if sample.x is None or sample.y is None:
            selected.add(sample.frame_index)
            last_position = None
            continue
        position = (float(sample.x), float(sample.y))
        if last_position is None or position != last_position:
            selected.add(sample.frame_index)
            last_position = position
    # The last frame can show the final site state even if the operator stopped
    # at the same physical point, so always retain it.
    if candidate_samples:
        selected.add(candidate_samples[-1].frame_index)
    return selected


def select_spatial_warp_points(samples: list[TourStationSample]) -> set[int]:
    """Select spatially even stations at roughly the reference-tour cadence.

    All localized keyframes remain available for review, but exposing every
    0.5-second frame as a portal produces overlapping rings and makes both the
    panorama and 3-D route unusable.  The reference 20/12 tour averages one
    station per four seconds.  Sampling by travelled arc length (rather than
    time alone) keeps the portals evenly distributed when the operator pauses.
    """
    localized = [
        sample
        for sample in samples
        if sample.x is not None and sample.y is not None and sample.heading_deg is not None
    ]
    if len(localized) <= 2:
        return {sample.frame_index for sample in localized}

    duration_ms = max(0, localized[-1].timestamp_ms - localized[0].timestamp_ms)
    target_count = max(2, round(duration_ms / (SPATIAL_STATION_INTERVAL_SECONDS * 1000)) + 1)
    segment_lengths = [
        math.hypot(float(right.x) - float(left.x), float(right.y) - float(left.y))
        for left, right in zip(localized, localized[1:], strict=False)
    ]
    total_length = sum(segment_lengths)
    if total_length <= 1e-8:
        return {localized[0].frame_index, localized[-1].frame_index}

    spacing = total_length / max(target_count - 1, 1)
    selected = {localized[0].frame_index}
    travelled = 0.0
    for sample, segment_length in zip(localized[1:-1], segment_lengths, strict=False):
        travelled += segment_length
        if travelled < spacing:
            continue
        selected.add(sample.frame_index)
        travelled %= spacing
    minimum_station_distance = max(spacing * 0.35, 1e-6)
    last_selected = next(sample for sample in reversed(localized) if sample.frame_index in selected)
    final = localized[-1]
    if (
        math.hypot(
            float(final.x) - float(last_selected.x),
            float(final.y) - float(last_selected.y),
        )
        >= minimum_station_distance
    ):
        selected.add(final.frame_index)

    # Arc-length sampling can leave a long time gap when the camera moves
    # slowly before a faster section. Keep its spatial distribution, but add
    # real localized frames inside moving gaps so the user never loses a long
    # navigable part of the recording. Exact stationary spans stay sparse.
    sample_by_index = {sample.frame_index: sample for sample in localized}
    selected_by_time = sorted(selected, key=lambda index: sample_by_index[index].timestamp_ms)
    max_gap_ms = SPATIAL_STATION_MAX_GAP_SECONDS * 1000
    target_interval_ms = SPATIAL_STATION_INTERVAL_SECONDS * 1000
    for left_index, right_index in zip(selected_by_time, selected_by_time[1:], strict=False):
        left = sample_by_index[left_index]
        right = sample_by_index[right_index]
        if right.timestamp_ms - left.timestamp_ms <= max_gap_ms:
            continue

        between = [
            sample
            for sample in localized
            if left.timestamp_ms <= sample.timestamp_ms <= right.timestamp_ms
        ]
        movement = sum(
            math.hypot(float(b.x) - float(a.x), float(b.y) - float(a.y))
            for a, b in zip(between, between[1:], strict=False)
        )
        if movement <= 1e-8:
            continue

        target_ms = left.timestamp_ms + target_interval_ms
        while right.timestamp_ms - target_ms > 0:
            candidate = min(
                between,
                key=lambda sample: abs(sample.timestamp_ms - target_ms),
            )
            left_distance = math.hypot(
                float(candidate.x) - float(left.x),
                float(candidate.y) - float(left.y),
            )
            right_distance = math.hypot(
                float(candidate.x) - float(right.x),
                float(candidate.y) - float(right.y),
            )
            if (
                candidate.frame_index not in {left_index, right_index}
                and left_distance >= minimum_station_distance
                and right_distance >= minimum_station_distance
            ):
                selected.add(candidate.frame_index)
            target_ms += target_interval_ms
    return selected


def build_spatial_visibility_targets(
    samples: list[TourStationSample],
    station_indices: set[int],
    *,
    limit: int = SPATIAL_VISIBLE_PORTAL_LIMIT,
) -> dict[int, list[int]]:
    """Build the reference-style portal graph from this capture's own track.

    The approved 20/12 tour exposes several spatially nearby destinations from
    each panorama instead of only the previous/next station.  Use the current
    capture's reconstructed coordinates (never reference coordinates) and cap
    the candidates at the same twenty-portal density as that reference.
    """
    stations = [
        sample
        for sample in samples
        if sample.frame_index in station_indices and sample.x is not None and sample.y is not None
    ]
    graph: dict[int, list[int]] = {}
    for source in stations:
        candidates = sorted(
            (target for target in stations if target.frame_index != source.frame_index),
            key=lambda target: (
                math.hypot(
                    float(target.x) - float(source.x),
                    float(target.y) - float(source.y),
                ),
                abs(target.timestamp_ms - source.timestamp_ms),
                target.frame_index,
            ),
        )
        graph[source.frame_index] = [target.frame_index for target in candidates[: max(0, limit)]]
    return graph


def _extract_tour_panoramas(
    *,
    source: Path,
    destination_dir: Path,
    frame_indices: list[int],
    source_fps: float,
    width: int,
    height: int,
) -> dict[int, Path]:
    """Decode the source once and return crisp stills for selected stations."""
    if width <= PROXY_WIDTH or not frame_indices:
        return {}
    tour_width = min(width, TOUR_MAX_WIDTH)
    tour_height = max(2, round(tour_width * height / width / 2) * 2)
    destination_dir.mkdir(parents=True, exist_ok=True)
    # FFmpeg's expression parser is recursive. Hundreds of ``eq(n, frame)``
    # terms can exhaust its parser stack even though system memory is healthy.
    # Dense tours are cheaper and safer to decode once at the keyframe rate.
    if len(frame_indices) > 64:
        _run(
            [
                _binary("ffmpeg"),
                "-y",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-vf",
                f"fps={CAPTURE_FRAME_FPS},scale={tour_width}:{tour_height}:flags=lanczos",
                "-threads",
                "2",
                "-q:v",
                "2",
                str(destination_dir / "%06d.jpg"),
            ]
        )
        extracted = sorted(destination_dir.glob("*.jpg"))
        if not extracted or frame_indices[-1] >= len(extracted):
            raise VideoPipelineError("สร้างภาพ Virtual Tour ความละเอียดสูงไม่ครบตามจำนวนสถานี")
        return {index: extracted[index] for index in frame_indices}

    source_frame_numbers = [
        round((index / CAPTURE_FRAME_FPS) * source_fps) for index in frame_indices
    ]
    # Direct argv invocation does not need shell quoting, but FFmpeg's filter
    # parser still requires the comma inside eq() to be escaped.
    selection = "+".join(f"eq(n\\,{number})" for number in source_frame_numbers)
    _run(
        [
            _binary("ffmpeg"),
            "-y",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-vf",
            f"select={selection},scale={tour_width}:{tour_height}:flags=lanczos",
            "-fps_mode",
            "vfr",
            "-threads",
            "2",
            "-q:v",
            "2",
            str(destination_dir / "%06d.jpg"),
        ]
    )
    extracted = sorted(destination_dir.glob("*.jpg"))
    if len(extracted) != len(frame_indices):
        raise VideoPipelineError("สร้างภาพ Virtual Tour ความละเอียดสูงไม่สำเร็จ")
    return dict(zip(frame_indices, extracted, strict=True))


def dispatch_video_job(job_id: uuid.UUID) -> None:
    celery_app.send_task(
        "progress_api.worker_tasks.process_video",
        args=[str(job_id)],
        queue="video_cpu",
        retry=False,
    )


def _binary(name: str) -> str:
    configured_dir = os.environ.get("PROGRESS_FFMPEG_DIR")
    if configured_dir:
        configured = Path(configured_dir) / f"{name}.exe"
        if configured.is_file():
            return str(configured)
    path = shutil.which(name)
    if not path:
        raise VideoPipelineError(f"ไม่พบ {name} ใน PATH")
    return path


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8")
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc))[-3000:]
        raise VideoPipelineError(detail) from exc


def _probe(source: Path) -> tuple[dict[str, object], dict[str, object]]:
    result = _run(
        [
            _binary("ffprobe"),
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(source),
        ]
    )
    payload = json.loads(result.stdout)
    streams = payload.get("streams", [])
    stream = next((item for item in streams if item.get("codec_type") == "video"), None)
    if stream is None:
        raise VideoPipelineError("ไฟล์ไม่มี Video stream")
    return payload, stream


def _fps(value: object) -> Decimal:
    try:
        return Decimal(Fraction(str(value)).numerator) / Decimal(Fraction(str(value)).denominator)
    except (ValueError, ZeroDivisionError):
        return Decimal(0)


def _set_progress(
    db: Session, job: ProcessingJob, capture: Capture, value: int, status: str
) -> None:
    job.progress_percent = value
    job.status = "RUNNING"
    # A retry reuses the same job row.  Do not let an error from an older
    # attempt survive after the new attempt has started or succeeded.
    job.error_code = None
    job.error_message = None
    capture.status = status
    if job.started_at is None:
        job.started_at = utc_now()
    db.commit()


def process_video_job(db: Session, job_id: uuid.UUID) -> dict[str, object]:
    job = db.get(ProcessingJob, job_id)
    if job is None:
        raise VideoPipelineError("ไม่พบ Processing Job")
    capture = db.get(Capture, job.capture_id)
    media = db.get(MediaFile, capture.source_video_id) if capture else None
    if capture is None or media is None or media.upload_status != "READY":
        raise VideoPipelineError("Capture หรือไฟล์ต้นทางยังไม่พร้อม")
    if job.status == "SUCCEEDED":
        return {"job_id": str(job.id), "status": job.status}

    try:
        suffix = PurePath(media.original_filename or media.object_key).suffix.lower()
        if suffix == ".insv":
            _set_progress(db, job, capture, 5, "STITCHING")
            get_stitcher_executable()
        else:
            _set_progress(db, job, capture, 5, "VALIDATING")
        with temporary_workspace(prefix="progress-video-") as temporary:
            workdir = Path(temporary)
            source = workdir / f"source{suffix}"
            download_media_file(
                bucket=media.bucket,
                key=media.object_key,
                destination=str(source),
            )
            processing_source = source
            if suffix == ".insv":
                _set_progress(db, job, capture, 10, "STITCHING")
                processing_source = workdir / "stitched.mp4"
                stitch_insv(source=source, destination=processing_source)
                _set_progress(db, job, capture, 20, "VALIDATING")
            payload, stream = _probe(processing_source)
            width = int(stream.get("width", 0))
            height = int(stream.get("height", 0))
            duration = float(
                stream.get("duration") or payload.get("format", {}).get("duration") or 0
            )
            if width <= 0 or height <= 0 or duration <= 0:
                raise VideoPipelineError("Metadata วิดีโอไม่สมบูรณ์")
            equirectangular = abs((width / height) - 2.0) <= 0.05
            if not equirectangular:
                raise VideoPipelineError("วิดีโอต้องเป็น Equirectangular อัตราส่วนประมาณ 2:1")

            metadata = db.scalar(
                select(VideoMetadata).where(VideoMetadata.media_file_id == media.id)
            )
            if metadata is None:
                metadata = VideoMetadata(media_file_id=media.id)
                db.add(metadata)
            metadata.format_name = str(payload.get("format", {}).get("format_name", "unknown"))
            metadata.codec_name = str(stream.get("codec_name", "unknown"))
            metadata.duration_ms = round(duration * 1000)
            metadata.width_px = width
            metadata.height_px = height
            metadata.fps = _fps(stream.get("avg_frame_rate", "0/1"))
            metadata.is_equirectangular = equirectangular
            metadata.ffprobe_json = json.dumps(payload, ensure_ascii=False)
            metadata.validated_at = utc_now()
            db.commit()

            _set_progress(db, job, capture, 25, "EXTRACTING_KEYFRAMES")
            frames_dir = workdir / "keyframes"
            frames_dir.mkdir()
            _run(
                [
                    _binary("ffmpeg"),
                    "-y",
                    "-i",
                    str(processing_source),
                    "-vf",
                    f"fps={CAPTURE_FRAME_FPS},scale={PROXY_WIDTH}:{PROXY_HEIGHT}",
                    "-q:v",
                    "3",
                    str(frames_dir / "%06d.jpg"),
                ]
            )
            db.execute(delete(Keyframe).where(Keyframe.capture_id == capture.id))
            db.flush()
            frames = sorted(frames_dir.glob("*.jpg"))
            if not frames:
                raise VideoPipelineError("ไม่สามารถดึง Keyframe ได้")
            quality = [measure_keyframe_quality(frame) for frame in frames]
            keyframes: list[Keyframe] = []
            media_by_index: dict[int, MediaFile] = {}
            for index, frame in enumerate(frames):
                timestamp_ms = round(index * 1000 / CAPTURE_FRAME_FPS)
                key = (
                    f"projects/{capture.project_id}/captures/{capture.id}/keyframes/{index:06d}.jpg"
                )
                upload_file(key=key, source=str(frame), content_type="image/jpeg")
                frame_media = db.scalar(select(MediaFile).where(MediaFile.object_key == key))
                if frame_media is None:
                    frame_media = MediaFile(
                        project_id=capture.project_id,
                        media_kind="KEYFRAME",
                        bucket=get_settings().s3_bucket,
                        object_key=key,
                        original_filename=frame.name,
                        content_type="image/jpeg",
                        size_bytes=frame.stat().st_size,
                        upload_status="READY",
                    )
                    db.add(frame_media)
                    db.flush()
                else:
                    frame_media.original_filename = frame.name
                    frame_media.content_type = "image/jpeg"
                    frame_media.size_bytes = frame.stat().st_size
                    frame_media.upload_status = "READY"
                keyframe = Keyframe(
                    capture_id=capture.id,
                    media_file_id=frame_media.id,
                    frame_index=index,
                    timestamp_ms=timestamp_ms,
                    quality_status=quality[index][0],
                    is_warp_point=False,
                )
                db.add(keyframe)
                keyframes.append(keyframe)
                media_by_index[index] = frame_media
            db.flush()
            _set_progress(db, job, capture, 75, "LOCALIZING")
            poses = save_camera_poses(db, capture=capture, job=job, source=processing_source)
            pose_by_keyframe = {pose.keyframe_id: pose for pose in poses}
            spatial_samples = []
            for keyframe in keyframes:
                pose = pose_by_keyframe.get(keyframe.id)
                spatial_samples.append(
                    TourStationSample(
                        frame_index=keyframe.frame_index,
                        timestamp_ms=keyframe.timestamp_ms,
                        quality_status=keyframe.quality_status,
                        x=(
                            float(pose.visual_x if pose.visual_x is not None else pose.x)
                            if pose is not None
                            else None
                        ),
                        y=(
                            float(pose.visual_y if pose.visual_y is not None else pose.y)
                            if pose is not None
                            else None
                        ),
                        heading_deg=(
                            float(
                                pose.visual_heading_deg
                                if pose.visual_heading_deg is not None
                                else pose.heading_deg
                            )
                            if pose is not None
                            else None
                        ),
                    )
                )
            # Portal stations represent physical camera locations. Selecting
            # them by elapsed time created duplicate/half-metre stations when
            # the operator paused, so a click visibly moved much less than the
            # ring implied. Sample the reconstructed arc length instead.
            warp_point_indices = select_spatial_warp_points(spatial_samples)
            if len(warp_point_indices) < 2:
                warp_point_indices = select_warp_points(quality)
            for keyframe in keyframes:
                keyframe.is_warp_point = keyframe.frame_index in warp_point_indices

            tour_frames = _extract_tour_panoramas(
                source=processing_source,
                destination_dir=workdir / "tour-panoramas",
                frame_indices=sorted(warp_point_indices),
                source_fps=float(_fps(stream.get("avg_frame_rate", "0/1"))),
                width=width,
                height=height,
            )
            for index, image in tour_frames.items():
                frame_media = media_by_index[index]
                upload_file(
                    key=frame_media.object_key,
                    source=str(image),
                    content_type="image/jpeg",
                )
                frame_media.original_filename = f"tour-4k-{index:06d}.jpg"
                frame_media.content_type = "image/jpeg"
                frame_media.size_bytes = image.stat().st_size
                frame_media.upload_status = "READY"
            job.progress_percent = 100
            job.status = "SUCCEEDED"
            job.error_code = None
            job.error_message = None
            job.finished_at = utc_now()
            capture.status = (
                "REVIEW_REQUIRED" if any(pose.needs_review for pose in poses) else "READY"
            )
            db.commit()
            return {
                "job_id": str(job.id),
                "status": job.status,
                "keyframe_count": len(frames),
                "pose_count": len(poses),
            }
    except Exception as exc:
        db.rollback()
        job = db.get(ProcessingJob, job_id)
        capture = db.get(Capture, job.capture_id) if job else None
        if job:
            job.status = "FAILED"
            job.error_code = type(exc).__name__
            job.error_message = str(exc)[:3000]
            job.finished_at = utc_now()
        if capture:
            capture.status = (
                "STITCHER_REQUIRED" if isinstance(exc, Insta360StitcherUnavailable) else "FAILED"
            )
        db.commit()
        raise
