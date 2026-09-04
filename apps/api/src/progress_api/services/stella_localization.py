from __future__ import annotations

import math
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from progress_api.config import get_settings
from progress_api.services.sfm_localization import SfMPathSample, _interpolate
from progress_api.services.temporary_workspace import temporary_workspace

STELLA_PROXY_WIDTH = 1920
STELLA_PROXY_HEIGHT = 960


class StellaLocalizationError(RuntimeError):
    pass


class StellaUnavailableError(StellaLocalizationError):
    pass


@dataclass(frozen=True)
class TumPose:
    timestamp_seconds: float
    tx: float
    ty: float
    tz: float
    qx: float
    qy: float
    qz: float
    qw: float


def _existing_path(value: str, *, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise StellaUnavailableError(f"{label} not found: {path}")
    return path


def _docker_executable() -> str:
    settings = get_settings()
    candidates = [
        settings.stella_vslam_docker_path,
        shutil.which("docker"),
        r"D:\DockerDesktop\resources\bin\docker.exe",
        r"C:\Program Files\Docker\Docker\resources\bin\docker.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise StellaUnavailableError(
        "Docker CLI not found. Set STELLA_VSLAM_DOCKER_PATH before localization."
    )


def _ffmpeg() -> str:
    executable = shutil.which("ffmpeg")
    if not executable:
        raise StellaUnavailableError("ffmpeg not found in PATH")
    return executable


def parse_tum_trajectory(path: Path) -> list[TumPose]:
    poses: list[TumPose] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 8:
            raise StellaLocalizationError(
                f"Invalid TUM trajectory row {line_number}: expected 8 fields"
            )
        try:
            values = [float(field) for field in fields]
        except ValueError as exc:
            raise StellaLocalizationError(
                f"Invalid number in TUM trajectory row {line_number}"
            ) from exc
        if not all(math.isfinite(value) for value in values):
            raise StellaLocalizationError(
                f"Non-finite value in TUM trajectory row {line_number}"
            )
        poses.append(TumPose(*values))
    if len(poses) < 4:
        raise StellaLocalizationError("Stella tracked fewer than four video frames")
    poses.sort(key=lambda pose: pose.timestamp_seconds)
    return poses


def _rotate_forward(pose: TumPose) -> tuple[float, float, float]:
    """Rotate camera-local +Z into Stella's map coordinate system."""
    norm = math.sqrt(pose.qx**2 + pose.qy**2 + pose.qz**2 + pose.qw**2)
    if norm <= 1e-9:
        return (0.0, 0.0, 1.0)
    qx, qy, qz, qw = (
        pose.qx / norm,
        pose.qy / norm,
        pose.qz / norm,
        pose.qw / norm,
    )
    return (
        2.0 * (qx * qz + qw * qy),
        2.0 * (qy * qz - qw * qx),
        1.0 - 2.0 * (qx * qx + qy * qy),
    )


def tum_poses_to_path(
    poses: list[TumPose],
    *,
    expected_frame_count: int,
    preserve_map_origin: bool = False,
) -> list[SfMPathSample]:
    first = poses[0]
    first_timestamp = first.timestamp_seconds
    tracked_ratio = min(1.0, len(poses) / max(1, expected_frame_count))
    base_confidence = max(0.05, min(0.98, 0.15 + 0.83 * tracked_ratio))
    samples: list[SfMPathSample] = []
    previous_timestamp = first_timestamp
    for pose in poses:
        timestamp_ms = max(0, round((pose.timestamp_seconds - first_timestamp) * 1000))
        forward_x, _forward_y, forward_z = _rotate_forward(pose)
        # Equirectangular longitude zero points along camera-local +Z and
        # increases toward +X. Keep the stored heading in that same convention
        # so a route bearing maps to the correct panorama pixel direction.
        heading = math.degrees(math.atan2(forward_x, forward_z)) % 360.0
        gap_seconds = max(0.0, pose.timestamp_seconds - previous_timestamp)
        gap_penalty = max(0.35, min(1.0, 1.0 / max(1.0, gap_seconds * 2.0)))
        samples.append(
            SfMPathSample(
                timestamp_ms=timestamp_ms,
                x=pose.tx if preserve_map_origin else pose.tx - first.tx,
                # Stella's camera-up convention keeps Y vertical for an upright
                # equirectangular camera, so X/Z form the walking plane.
                y=pose.tz if preserve_map_origin else pose.tz - first.tz,
                heading_deg=heading,
                confidence=base_confidence * gap_penalty,
                relative_z=pose.ty - first.ty,
            )
        )
        previous_timestamp = pose.timestamp_seconds
    return samples


def _make_tracking_proxy(
    source: Path,
    destination: Path,
    *,
    start_seconds: float = 0.0,
    duration_seconds: float | None = None,
) -> None:
    settings = get_settings()
    command = [
        _ffmpeg(),
        "-y",
        "-v",
        "error",
    ]
    if start_seconds > 0:
        command.extend(["-ss", f"{start_seconds:.3f}"])
    command.extend(["-i", str(source)])
    if duration_seconds is not None:
        command.extend(["-t", f"{duration_seconds:.3f}"])
    command.extend(
        [
            "-vf",
            (
                f"fps={settings.stella_vslam_tracking_fps},"
                f"scale={STELLA_PROXY_WIDTH}:{STELLA_PROXY_HEIGHT}"
            ),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            # A single worker already processes one capture at a time. Limit x264
            # as well so a proxy transcode cannot exhaust RAM on the Windows host.
            "-threads",
            "1",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            str(destination),
        ]
    )
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except subprocess.CalledProcessError as exc:
        raise StellaLocalizationError((exc.stderr or str(exc))[-3000:]) from exc


def _run_stella(workspace: Path, *, use_existing_map: bool = False) -> tuple[Path, Path]:
    settings = get_settings()
    vocab = _existing_path(settings.stella_vslam_vocab_path, label="ORB vocabulary")
    config = _existing_path(settings.stella_vslam_config_path, label="Stella config")
    workspace = workspace.resolve()
    output = workspace / "trajectory"
    output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config, workspace / "camera.yaml")
    shutil.copy2(vocab, workspace / "orb_vocab.fbow")

    container_name = f"progress-stella-{uuid.uuid4().hex[:12]}"
    command = [
        _docker_executable(),
        "run",
        "--rm",
        "--name",
        container_name,
        "--entrypoint",
        "/stella_vslam_examples/build/run_video_slam",
        "--mount",
        f"type=bind,source={workspace},target=/work",
        settings.stella_vslam_image,
        "--vocab",
        "/work/orb_vocab.fbow",
        "--video",
        "/work/tracking.mp4",
        "--config",
        "/work/camera.yaml",
        "--frame-skip",
        str(settings.stella_vslam_frame_skip),
        "--no-sleep",
        "--auto-term",
        "--viewer",
        "none",
        "--start-timestamp",
        "0",
        "--eval-log-dir",
        "/work/trajectory",
    ]
    if use_existing_map:
        # A capture that is matched against a trusted map must run in pure
        # localization mode.  Without --disable-mapping Stella extends the
        # loaded map with the new walk, so a weak/incorrect match can pollute
        # the reference map and every later capture.
        command.extend(
            ["--disable-mapping", "--map-db-in", "/work/reference-map.msg"]
        )
    else:
        # Loop bundle adjustment only applies while Stella is building a map.
        # In localization-only mode it can wait forever when the walk never
        # obtains a strong match with the loaded construction map.
        command.append("--wait-loop-ba")
        command.extend(["--map-db-out", "/work/map.msg"])
    # A bad/low-texture capture must not block the chronological backfill for
    # hours.  Relocalization should fail quickly, while fresh mapping gets a
    # larger (but still bounded) window.
    timeout_seconds = (
        min(settings.stella_vslam_timeout_seconds, 300)
        if use_existing_map
        else min(settings.stella_vslam_timeout_seconds, 1200)
    )
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        # Killing docker.exe does not stop its container on Windows. Remove the
        # named temporary container so a timed-out capture cannot consume CPU
        # indefinitely or block later localization jobs.
        subprocess.run(
            [_docker_executable(), "rm", "-f", container_name],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        raise StellaLocalizationError("Stella localization timed out") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc))[-5000:]
        if "Unable to find image" in detail or "pull access denied" in detail:
            raise StellaUnavailableError(
                f"Stella Docker image is not installed: {settings.stella_vslam_image}"
            ) from exc
        raise StellaLocalizationError(detail) from exc
    trajectory = output / "frame_trajectory.txt"
    if not trajectory.is_file():
        raise StellaLocalizationError("Stella did not write frame_trajectory.txt")
    map_database = (
        workspace / "reference-map.msg" if use_existing_map else workspace / "map.msg"
    )
    if not map_database.is_file():
        raise StellaLocalizationError("Stella did not write map.msg")
    return trajectory, map_database


def recover_stella_path(
    source: Path,
    *,
    end_timestamp_ms: int,
    map_db_input: Path | None = None,
    map_db_output: Path | None = None,
) -> list[SfMPathSample]:
    settings = get_settings()
    with temporary_workspace(prefix="progress-stella-") as temporary:
        workspace = Path(temporary)
        _make_tracking_proxy(source, workspace / "tracking.mp4")
        if map_db_input is not None:
            shutil.copy2(map_db_input, workspace / "reference-map.msg")
        trajectory, map_database = _run_stella(
            workspace, use_existing_map=map_db_input is not None
        )
        poses = parse_tum_trajectory(trajectory)
        expected_frames = max(
            1,
            round(
                (end_timestamp_ms / 1000)
                * settings.stella_vslam_tracking_fps
                / settings.stella_vslam_frame_skip
            ),
        )
        samples = tum_poses_to_path(
            poses,
            expected_frame_count=expected_frames,
            preserve_map_origin=map_db_input is not None,
        )
        if map_db_output is not None:
            map_db_output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(map_database, map_db_output)
    coverage_ms = samples[-1].timestamp_ms - samples[0].timestamp_ms
    required_coverage_ms = max(2_000, int(end_timestamp_ms * 0.90))
    if coverage_ms < required_coverage_ms:
        if map_db_input is not None:
            # Let the caller retry as a fresh map. Interpolating a short
            # localization-only result would silently freeze the camera for
            # the rest of the video and publish hundreds of stacked stations.
            raise StellaLocalizationError(
                "Stella reference-map tracking ended before 90% of the video"
            )
        samples = _recover_segmented_stella_path(
            source,
            initial_samples=samples,
            end_timestamp_ms=end_timestamp_ms,
        )
    return _interpolate(samples, end_timestamp_ms)


def _sample_xy_at(samples: list[SfMPathSample], timestamps: np.ndarray) -> np.ndarray:
    source_times = np.asarray([sample.timestamp_ms for sample in samples], dtype=np.float64)
    return np.column_stack(
        [
            np.interp(timestamps, source_times, [sample.x for sample in samples]),
            np.interp(timestamps, source_times, [sample.y for sample in samples]),
        ]
    )


def _align_overlapping_segment(
    base: list[SfMPathSample],
    segment: list[SfMPathSample],
    *,
    overlap_ms: int,
) -> list[SfMPathSample]:
    """Place an independently initialized Stella segment onto an existing path."""
    base_end = base[-1].timestamp_ms
    overlap_start = max(base[0].timestamp_ms, segment[0].timestamp_ms, base_end - overlap_ms)
    overlap_rows = [
        sample
        for sample in segment
        if overlap_start <= sample.timestamp_ms <= base_end
    ]
    if len(overlap_rows) < 12:
        raise StellaLocalizationError("Segment does not have enough overlap to join")

    timestamps = np.asarray(
        [sample.timestamp_ms for sample in overlap_rows], dtype=np.float64
    )
    source = np.asarray([(sample.x, sample.y) for sample in overlap_rows], dtype=np.float64)
    target = _sample_xy_at(base, timestamps)
    source_center = source.mean(axis=0)
    target_center = target.mean(axis=0)
    source_zero = source - source_center
    target_zero = target - target_center
    source_energy = float(np.sum(source_zero**2))
    target_energy = float(np.sum(target_zero**2))
    if source_energy < 1e-7 or target_energy < 1e-7:
        raise StellaLocalizationError("Segment overlap has insufficient camera movement")

    covariance = source_zero.T @ target_zero
    left, singular, right = np.linalg.svd(covariance)
    rotation = right.T @ left.T
    if float(np.linalg.det(rotation)) < 0:
        right[-1, :] *= -1
        rotation = right.T @ left.T
    scale = float(np.sum(singular) / source_energy)
    if not math.isfinite(scale) or not 0.02 <= scale <= 50.0:
        raise StellaLocalizationError("Segment scale is not credible")
    translation = target_center - scale * (rotation @ source_center)
    rotation_deg = math.degrees(math.atan2(rotation[1, 0], rotation[0, 0]))

    source_z = np.asarray([sample.relative_z for sample in overlap_rows], dtype=np.float64)
    base_z = np.interp(
        timestamps,
        [sample.timestamp_ms for sample in base],
        [sample.relative_z for sample in base],
    )
    z_offset = float(np.mean(base_z - scale * source_z))

    aligned: list[SfMPathSample] = []
    for sample in segment:
        position = scale * (rotation @ np.asarray([sample.x, sample.y])) + translation
        aligned.append(
            SfMPathSample(
                timestamp_ms=sample.timestamp_ms,
                x=float(position[0]),
                y=float(position[1]),
                heading_deg=(sample.heading_deg + rotation_deg) % 360.0,
                confidence=min(sample.confidence, 0.85),
                relative_z=scale * sample.relative_z + z_offset,
            )
        )
    return aligned


def _recover_stella_segment(
    source: Path,
    *,
    start_timestamp_ms: int,
    duration_ms: int,
) -> list[SfMPathSample]:
    settings = get_settings()
    with temporary_workspace(prefix="progress-stella-segment-") as temporary:
        workspace = Path(temporary)
        _make_tracking_proxy(
            source,
            workspace / "tracking.mp4",
            start_seconds=start_timestamp_ms / 1000,
            duration_seconds=duration_ms / 1000,
        )
        trajectory, _map_database = _run_stella(workspace)
        poses = parse_tum_trajectory(trajectory)
        expected_frames = max(
            1,
            round(
                (duration_ms / 1000)
                * settings.stella_vslam_tracking_fps
                / settings.stella_vslam_frame_skip
            ),
        )
        local = tum_poses_to_path(poses, expected_frame_count=expected_frames)
    return [
        SfMPathSample(
            timestamp_ms=start_timestamp_ms + sample.timestamp_ms,
            x=sample.x,
            y=sample.y,
            heading_deg=sample.heading_deg,
            confidence=sample.confidence,
            relative_z=sample.relative_z,
        )
        for sample in local
    ]


def _recover_segmented_stella_path(
    source: Path,
    *,
    initial_samples: list[SfMPathSample],
    end_timestamp_ms: int,
    window_ms: int = 35_000,
    overlap_ms: int = 8_000,
) -> list[SfMPathSample]:
    """Extend a lost whole-video track with overlapping fresh Stella maps."""
    stitched = list(initial_samples)
    attempts = 0
    max_attempts = max(2, math.ceil(end_timestamp_ms / max(1, window_ms - overlap_ms)) + 2)
    while stitched[-1].timestamp_ms < end_timestamp_ms - 1_000:
        attempts += 1
        if attempts > max_attempts:
            raise StellaLocalizationError("Segmented Stella recovery exceeded its window limit")
        previous_end = stitched[-1].timestamp_ms
        start_ms = max(0, previous_end - overlap_ms)
        duration_ms = min(window_ms, end_timestamp_ms - start_ms)
        segment = _recover_stella_segment(
            source,
            start_timestamp_ms=start_ms,
            duration_ms=duration_ms,
        )
        aligned = _align_overlapping_segment(
            stitched,
            segment,
            overlap_ms=overlap_ms,
        )
        extension = [sample for sample in aligned if sample.timestamp_ms > previous_end]
        if not extension or extension[-1].timestamp_ms <= previous_end + 1_000:
            raise StellaLocalizationError("Segmented Stella recovery made no forward progress")
        stitched.extend(extension)
    return stitched
