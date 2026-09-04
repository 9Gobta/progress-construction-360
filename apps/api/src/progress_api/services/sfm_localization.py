from __future__ import annotations

import json
import math
import shutil
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pycolmap

from progress_api.services.temporary_workspace import temporary_workspace

# Keep global 3D key views sparse enough for 7-9 minute site walks. Camera
# rotation is still tracked at 5 FPS below, and poses are sampled at 2 FPS for
# the viewer after global reconstruction.
SFM_FPS = 1
TRACKING_FPS = 5
PATH_SAMPLE_INTERVAL_MS = 500
PANORAMA_WIDTH = 1920
PANORAMA_HEIGHT = 960
FACE_SIZE = 256
FACE_YAWS = (0.0, 90.0, 180.0, 270.0)
MAX_SIFT_FEATURES = 1600
CAMERA_HEIGHT_M = 1.65


class SfMLocalizationError(RuntimeError):
    pass


@dataclass(frozen=True)
class SfMPathSample:
    timestamp_ms: int
    x: float
    y: float
    heading_deg: float
    confidence: float
    relative_z: float = 0.0
    orientation_q: tuple[float, float, float, float] | None = None


def _face_parts(name: str) -> tuple[str, int, str]:
    """Return frame, cubemap face and timestamp for flat or rig image names."""
    path = Path(name)
    parts = path.stem.split("_")
    if len(parts) == 3:
        frame, face, timestamp = parts
        return frame, int(face), timestamp
    if len(parts) == 2 and len(path.parts) >= 2:
        frame, timestamp = parts
        return frame, int(path.parts[-2]), timestamp
    raise SfMLocalizationError(f"Unexpected cubemap image name: {name}")


def _rotation_about_y(degrees: float) -> pycolmap.Rotation3d:
    half_angle = math.radians(degrees) / 2
    return pycolmap.Rotation3d(
        np.asarray([0.0, math.sin(half_angle), 0.0, math.cos(half_angle)])
    )


def _configure_panorama_rig(database_path: Path, image_path: Path) -> None:
    """Make four perspective faces share one exact optical centre per frame.

    Feature extraction initially uses flat, time-ordered image names so
    sequential matching keeps adjacent timestamps together. After extraction
    the images are grouped by sensor prefix and COLMAP's rig constraints lock
    the four face rotations and their common centre.
    """
    with pycolmap.Database.open(database_path) as database:
        source_camera = database.read_all_cameras()[0]
        camera_ids: list[int] = []
        for _face_index in range(len(FACE_YAWS)):
            camera = pycolmap.Camera(source_camera.todict())
            camera.camera_id = pycolmap.INVALID_CAMERA_ID
            camera_ids.append(database.write_camera(camera))

        for image in database.read_all_images():
            frame, face_index, timestamp = _face_parts(image.name)
            old_path = image_path / image.name
            renamed = f"{face_index}/{frame}_{timestamp}.jpg"
            new_path = image_path / renamed
            new_path.parent.mkdir(parents=True, exist_ok=True)
            old_path.rename(new_path)
            image.name = renamed
            image.camera_id = camera_ids[face_index]
            database.update_image(image)

        rig_cameras: list[pycolmap.RigConfigCamera] = []
        for face_index, yaw in enumerate(FACE_YAWS):
            config = pycolmap.RigConfigCamera(
                image_prefix=f"{face_index}/",
                ref_sensor=face_index == 0,
            )
            if face_index:
                config.cam_from_rig = pycolmap.Rigid3d(
                    _rotation_about_y(-yaw),
                    np.zeros(3, dtype=np.float64),
                )
            rig_cameras.append(config)
        pycolmap.apply_rig_config(
            [pycolmap.RigConfig(cameras=rig_cameras)],
            database,
        )


def _perspective_map(
    *, yaw_deg: float, size: int = FACE_SIZE, fov_deg: float = 100.0
) -> tuple[np.ndarray, np.ndarray]:
    focal = (size / 2) / math.tan(math.radians(fov_deg) / 2)
    axis = (np.arange(size, dtype=np.float32) - (size - 1) / 2) / focal
    grid_x, grid_y = np.meshgrid(axis, -axis)
    ray_z = np.ones_like(grid_x)
    length = np.sqrt(grid_x**2 + grid_y**2 + ray_z**2)
    ray_x = grid_x / length
    ray_y = grid_y / length
    ray_z /= length
    yaw = math.radians(yaw_deg)
    world_x = math.cos(yaw) * ray_x + math.sin(yaw) * ray_z
    world_z = -math.sin(yaw) * ray_x + math.cos(yaw) * ray_z
    longitude = np.arctan2(world_x, world_z)
    latitude = np.arcsin(np.clip(ray_y, -1.0, 1.0))
    map_x = ((longitude / (2 * math.pi)) + 0.5) * PANORAMA_WIDTH
    map_y = (0.5 - latitude / math.pi) * PANORAMA_HEIGHT
    return map_x.astype(np.float32), map_y.astype(np.float32)


def _extract_panoramas(
    source: Path,
    output: Path,
    *,
    fps: int = SFM_FPS,
    width: int = PANORAMA_WIDTH,
    height: int = PANORAMA_HEIGHT,
) -> list[Path]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SfMLocalizationError("ffmpeg is not available")
    output.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-y",
        "-v",
        "error",
        "-i",
        str(source),
        "-vf",
        f"fps={fps},scale={width}:{height}",
        "-q:v",
        "3",
        str(output / "%04d.jpg"),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8")
    except subprocess.CalledProcessError as exc:
        raise SfMLocalizationError((exc.stderr or str(exc))[-3000:]) from exc
    panoramas = sorted(output.glob("*.jpg"))
    if len(panoramas) < 4:
        raise SfMLocalizationError("Video has too few panorama samples for 3D reconstruction")
    return panoramas


def _render_faces(panoramas: list[Path], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    maps = [_perspective_map(yaw_deg=yaw) for yaw in FACE_YAWS]
    written = 0
    for frame_index, panorama_path in enumerate(panoramas):
        panorama = cv2.imread(str(panorama_path))
        if panorama is None:
            continue
        timestamp_ms = round(frame_index * 1000 / SFM_FPS)
        for face_index, (map_x, map_y) in enumerate(maps):
            face = cv2.remap(
                panorama,
                map_x,
                map_y,
                cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_WRAP,
            )
            filename = output / f"{frame_index:04d}_{face_index}_{timestamp_ms}.jpg"
            if cv2.imwrite(str(filename), face):
                written += 1
    if written < 16:
        raise SfMLocalizationError("Could not render enough perspective views")


def _yaw_delta_between(previous: np.ndarray, current: np.ndarray) -> float:
    """Estimate panorama yaw change from robust horizontal feature motion."""
    orb = cv2.ORB_create(nfeatures=2400, scaleFactor=1.2, nlevels=8)
    previous_points, previous_descriptors = orb.detectAndCompute(previous, None)
    current_points, current_descriptors = orb.detectAndCompute(current, None)
    if previous_descriptors is None or current_descriptors is None:
        return 0.0
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    pairs = matcher.knnMatch(previous_descriptors, current_descriptors, k=2)
    good = [
        pair[0]
        for pair in pairs
        if len(pair) == 2 and pair[0].distance < 0.72 * pair[1].distance
    ]
    if len(good) < 20:
        return 0.0
    width = previous.shape[1]
    shifts = []
    for match in good:
        shift = (
            current_points[match.trainIdx].pt[0]
            - previous_points[match.queryIdx].pt[0]
        )
        shift = (shift + width / 2) % width - width / 2
        shifts.append(shift)
    median = float(np.median(shifts))
    deviation = float(np.median(np.abs(np.asarray(shifts) - median)))
    inliers = [shift for shift in shifts if abs(shift - median) <= max(8.0, 3 * deviation)]
    if len(inliers) < 12:
        return 0.0
    yaw_delta = -(float(np.median(inliers)) / width) * 360.0
    return max(-45.0, min(45.0, yaw_delta))


def _panorama_yaw_track(panoramas: list[Path]) -> dict[int, float]:
    track: dict[int, float] = {}
    cumulative = 0.0
    previous: np.ndarray | None = None
    for frame_index, path in enumerate(panoramas):
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            continue
        image = cv2.resize(image, (960, 480), interpolation=cv2.INTER_AREA)
        if previous is not None:
            cumulative += _yaw_delta_between(previous, image)
        track[round(frame_index * 1000 / TRACKING_FPS)] = cumulative
        previous = image
    return track


def _yaw_at(track: dict[int, float], timestamp_ms: int) -> float:
    """Interpolate the high-rate visual heading at an SfM keyframe timestamp."""
    if timestamp_ms in track:
        return track[timestamp_ms]
    ordered = sorted(track)
    if not ordered:
        return 0.0
    before = max((item for item in ordered if item < timestamp_ms), default=ordered[0])
    after = min((item for item in ordered if item > timestamp_ms), default=ordered[-1])
    if before == after:
        return track[before]
    ratio = (timestamp_ms - before) / (after - before)
    return track[before] + (track[after] - track[before]) * ratio


def _reconstruct(images: Path, workspace: Path) -> pycolmap.Reconstruction:
    database = workspace / "database.db"
    sparse = workspace / "sparse"
    sparse.mkdir(parents=True, exist_ok=True)
    extraction = pycolmap.FeatureExtractionOptions()
    extraction.max_image_size = FACE_SIZE
    extraction.num_threads = 4
    extraction.sift.max_num_features = MAX_SIFT_FEATURES
    extraction.use_gpu = pycolmap.has_cuda
    device = pycolmap.Device.cuda if pycolmap.has_cuda else pycolmap.Device.cpu
    pycolmap.extract_features(
        database,
        images,
        camera_mode=pycolmap.CameraMode.SINGLE,
        camera_model="PINHOLE",
        extraction_options=extraction,
        device=device,
    )
    _configure_panorama_rig(database, images)
    pairing = pycolmap.SequentialPairingOptions()
    # Filenames are ordered as four faces per timestamp.  An overlap of eight
    # compares the current panorama with its immediate neighbours without the
    # quadratic cost of matching a large temporal window.
    pairing.overlap = 8
    matching = pycolmap.FeatureMatchingOptions()
    matching.num_threads = 4
    matching.use_gpu = pycolmap.has_cuda
    matching.max_num_matches = 6000
    pycolmap.match_sequential(
        database,
        matching_options=matching,
        pairing_options=pairing,
        device=device,
    )
    options = pycolmap.IncrementalPipelineOptions()
    options.num_threads = 4
    options.multiple_models = False
    options.min_model_size = 8
    # Dense temporal sampling already supplies strong local overlap. Running a
    # full global adjustment after every ~10% growth makes a short walkthrough
    # take disproportionately long, so optimize locally while mapping and run
    # the expensive global refinement at wider intervals and at completion.
    options.ba_local_max_num_iterations = 15
    options.ba_global_frames_ratio = 2.0
    options.ba_global_points_ratio = 2.0
    options.ba_global_frames_freq = 1000
    options.ba_global_points_freq = 500_000
    options.ba_global_max_num_iterations = 30
    options.ba_global_max_refinements = 2
    options.ba_refine_sensor_from_rig = False
    options.ba_refine_focal_length = False
    options.ba_refine_extra_params = False
    options.mapper.init_min_num_inliers = 40
    options.mapper.abs_pose_min_num_inliers = 20
    reconstructions = pycolmap.incremental_mapping(
        database, images, sparse, options=options
    )
    if not reconstructions:
        raise SfMLocalizationError("3D reconstruction could not register a camera path")
    reconstruction = max(reconstructions.values(), key=lambda item: item.num_reg_images())
    if reconstruction.num_reg_images() < 8:
        raise SfMLocalizationError("3D reconstruction registered too few camera views")
    return reconstruction


def _panorama_heading(face_heading_deg: float, face_index: int) -> float:
    """Convert a reconstructed cubemap-face heading to panorama zero longitude."""
    return (face_heading_deg + FACE_YAWS[face_index]) % 360


def _horizontal_heading(
    vector: np.ndarray,
    *,
    vertical: np.ndarray,
    axis_x: np.ndarray,
    axis_y: np.ndarray,
) -> float | None:
    """Project a reconstructed panorama ray onto the walking plane."""
    horizontal = vector - float(np.dot(vector, vertical)) * vertical
    norm = float(np.linalg.norm(horizontal))
    if norm < 1e-9:
        return None
    horizontal /= norm
    # Stored visual bearings use +axis_y as 0 degrees and turn toward +axis_x
    # (the same convention used by route-vector generation and the panorama
    # renderer). Keeping this convention here prevents a 90-degree portal
    # offset on newly processed captures.
    return math.degrees(
        math.atan2(float(np.dot(horizontal, axis_x)), float(np.dot(horizontal, axis_y)))
    ) % 360


def _estimate_camera_height(
    camera_centers: np.ndarray,
    points3d: np.ndarray,
    vertical: np.ndarray,
) -> float | None:
    """Estimate the camera-to-walking-surface distance in SfM units.

    Monocular SfM has no metric scale.  The visible tour rings nevertheless
    need the *same* scale as the reconstructed translations; estimating the
    dominant surface below the camera trajectory gives us that missing scale.
    Only points close to the walked route are considered so walls and distant
    excavation faces do not dominate the histogram.
    """
    if len(camera_centers) < 4 or len(points3d) < 50:
        return None
    vertical = np.asarray(vertical, dtype=np.float64)
    vertical /= max(float(np.linalg.norm(vertical)), 1e-9)
    centers = np.asarray(camera_centers, dtype=np.float64)
    points = np.asarray(points3d, dtype=np.float64)
    horizontal_centers = centers - np.outer(centers @ vertical, vertical)
    horizontal_points = points - np.outer(points @ vertical, vertical)
    steps = np.linalg.norm(np.diff(horizontal_centers, axis=0), axis=1)
    positive_steps = steps[(steps > 1e-8) & np.isfinite(steps)]
    if not len(positive_steps):
        return None
    median_step = float(np.median(positive_steps))
    nearest_squared = np.full(len(points), np.inf, dtype=np.float64)
    nearest_indices = np.zeros(len(points), dtype=np.int64)
    # Chunking avoids allocating a points x cameras matrix for long captures.
    for start in range(0, len(points), 4096):
        stop = min(start + 4096, len(points))
        distances = np.sum(
            (
                horizontal_points[start:stop, None, :]
                - horizontal_centers[None, :, :]
            )
            ** 2,
            axis=2,
        )
        local_indices = np.argmin(distances, axis=1)
        nearest_indices[start:stop] = local_indices
        nearest_squared[start:stop] = distances[
            np.arange(stop - start), local_indices
        ]
    heights = np.sum((centers[nearest_indices] - points) * vertical, axis=1)
    close_to_route = np.sqrt(nearest_squared) <= max(median_step * 8.0, 0.5)
    plausible = (
        close_to_route
        & np.isfinite(heights)
        & (heights >= median_step * 1.25)
        & (heights <= median_step * 8.0)
    )
    candidates = heights[plausible]
    if len(candidates) < 30:
        return None
    bin_width = max(median_step * 0.08, 1e-4)
    lower = float(candidates.min())
    upper = float(candidates.max())
    bin_count = max(8, int(math.ceil((upper - lower) / bin_width)))
    histogram, edges = np.histogram(candidates, bins=bin_count, range=(lower, upper))
    # A three-bin moving sum is less sensitive to sparse-point quantisation.
    smoothed = np.convolve(histogram, np.ones(3, dtype=np.int64), mode="same")
    peak = int(np.argmax(smoothed))
    peak_center = float((edges[peak] + edges[peak + 1]) / 2)
    neighbourhood = np.abs(candidates - peak_center) <= bin_width * 2.0
    estimate = float(np.median(candidates[neighbourhood]))
    return estimate if estimate > 1e-8 else None


def _write_spatial_model(
    reconstruction: pycolmap.Reconstruction,
    destination: Path,
    *,
    origin: np.ndarray,
    axis_x: np.ndarray,
    axis_y: np.ndarray,
    vertical: np.ndarray,
    metric_scale: float,
) -> None:
    """Write a compact browser-ready sparse 3-D site model."""
    camera_positions: list[tuple[float, float, float]] = []
    for image in reconstruction.images.values():
        try:
            _frame, face_index, _timestamp = _face_parts(image.name)
        except SfMLocalizationError:
            continue
        if face_index != 0 or not image.has_pose:
            continue
        offset = np.asarray(image.projection_center(), dtype=np.float64) - origin
        camera_positions.append(
            (
                float(np.dot(offset, axis_x)) * metric_scale,
                float(np.dot(offset, vertical)) * metric_scale,
                float(np.dot(offset, axis_y)) * metric_scale,
            )
        )
    cameras = np.asarray(camera_positions, dtype=np.float64)
    if len(cameras):
        horizontal_span = max(float(np.ptp(cameras[:, 0])), float(np.ptp(cameras[:, 2])))
        horizontal_margin = max(8.0, horizontal_span * 0.35)
        minimum = cameras.min(axis=0) - np.asarray([horizontal_margin, 6.0, horizontal_margin])
        maximum = cameras.max(axis=0) + np.asarray([horizontal_margin, 4.0, horizontal_margin])
    else:
        minimum = np.asarray([-math.inf, -math.inf, -math.inf])
        maximum = np.asarray([math.inf, math.inf, math.inf])
    positions: list[float] = []
    colors: list[int] = []
    for point in reconstruction.points3D.values():
        offset = np.asarray(point.xyz, dtype=np.float64) - origin
        position = (
            float(np.dot(offset, axis_x)) * metric_scale,
            float(np.dot(offset, vertical)) * metric_scale,
            float(np.dot(offset, axis_y)) * metric_scale,
        )
        if not all(math.isfinite(value) for value in position):
            continue
        if np.any(np.asarray(position) < minimum) or np.any(np.asarray(position) > maximum):
            continue
        positions.extend(round(value, 3) for value in position)
        color = np.asarray(point.color, dtype=np.uint8)
        colors.extend(int(value) for value in color[:3])
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            {
                "version": 1,
                "coordinate_system": "visual-metric-x-up-y",
                "camera_height_m": CAMERA_HEIGHT_M,
                "point_count": len(positions) // 3,
                "positions": positions,
                "colors": colors,
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


def _raw_samples(
    reconstruction: pycolmap.Reconstruction,
    panorama_yaw_track: dict[int, float],
    *,
    spatial_model_output: Path | None = None,
) -> list[SfMPathSample]:
    centers: dict[int, list[tuple[int, np.ndarray]]] = defaultdict(list)
    panorama_zero_vectors: dict[int, list[tuple[int, np.ndarray]]] = defaultdict(list)
    panorama_rotations: dict[int, list[tuple[int, np.ndarray]]] = defaultdict(list)
    camera_up_vectors: list[np.ndarray] = []
    for image in reconstruction.images.values():
        _frame, face_index, timestamp = _face_parts(image.name)
        timestamp_ms = int(timestamp)
        world_from_camera = image.cam_from_world().inverse()
        centers[timestamp_ms].append((face_index, world_from_camera.translation))
        rotation = world_from_camera.rotation.matrix()
        face_yaw = math.radians(FACE_YAWS[face_index])
        camera_from_panorama = _rotation_about_y(-FACE_YAWS[face_index]).matrix()
        panorama_rotations[timestamp_ms].append(
            (face_index, rotation @ camera_from_panorama)
        )
        # Express the panorama's zero-longitude ray in this cubemap face's
        # camera coordinates, then rotate it into the reconstruction frame.
        local_panorama_zero = np.array(
            [-math.sin(face_yaw), 0.0, math.cos(face_yaw)]
        )
        panorama_zero_vectors[timestamp_ms].append(
            (face_index, rotation @ local_panorama_zero)
        )
        # COLMAP camera coordinates use +Y downward, therefore camera up is -Y.
        camera_up_vectors.append(rotation @ np.array([0.0, -1.0, 0.0]))
    ordered = sorted(centers)
    if len(ordered) < 4:
        raise SfMLocalizationError("3D reconstruction did not cover enough timestamps")
    medians = {}
    for timestamp in ordered:
        candidates = centers[timestamp]
        medians[timestamp] = next(
            (center for face_index, center in candidates if face_index == 0),
            np.median(
                np.stack([center for _face_index, center in candidates]), axis=0
            ),
        )
    origin = medians[ordered[0]]
    up_reference = camera_up_vectors[0]
    aligned_up = [
        vector if float(np.dot(vector, up_reference)) >= 0 else -vector
        for vector in camera_up_vectors
    ]
    vertical = np.mean(np.stack(aligned_up), axis=0)
    vertical /= max(float(np.linalg.norm(vertical)), 1e-9)
    centered = np.stack([medians[timestamp] - origin for timestamp in ordered])
    horizontal_centers = centered - np.outer(centered @ vertical, vertical)
    _u, _singular, axes = np.linalg.svd(horizontal_centers, full_matrices=False)
    axis_x = axes[0] - float(np.dot(axes[0], vertical)) * vertical
    axis_x /= max(float(np.linalg.norm(axis_x)), 1e-9)
    axis_y = np.cross(vertical, axis_x)
    axis_y /= max(float(np.linalg.norm(axis_y)), 1e-9)
    point_positions = np.asarray(
        [point.xyz for point in reconstruction.points3D.values()],
        dtype=np.float64,
    )
    camera_height = _estimate_camera_height(
        np.stack([medians[timestamp] for timestamp in ordered]),
        point_positions,
        vertical,
    )
    metric_scale = CAMERA_HEIGHT_M / camera_height if camera_height else 1.0
    if spatial_model_output is not None:
        _write_spatial_model(
            reconstruction,
            spatial_model_output,
            origin=origin,
            axis_x=axis_x,
            axis_y=axis_y,
            vertical=vertical,
            metric_scale=metric_scale,
        )
    first_zero_candidates = panorama_zero_vectors[ordered[0]]
    first_zero = next(
        (vector for face_index, vector in first_zero_candidates if face_index == 0),
        np.mean(
            np.stack([vector for _face_index, vector in first_zero_candidates]), axis=0
        ),
    )
    initial_heading = math.degrees(
        math.atan2(
            float(np.dot(first_zero, axis_x)), float(np.dot(first_zero, axis_y))
        )
    )
    initial_yaw = _yaw_at(panorama_yaw_track, ordered[0])
    samples: list[SfMPathSample] = []
    canonical_from_reconstruction = np.stack([axis_x, axis_y, vertical])
    for timestamp_ms in ordered:
        center = medians[timestamp_ms] - origin
        zero_candidates = panorama_zero_vectors[timestamp_ms]
        reference = zero_candidates[0][1]
        aligned_zero_vectors = [
            vector if float(np.dot(vector, reference)) >= 0 else -vector
            for _face_index, vector in zero_candidates
        ]
        reconstructed_zero = np.mean(np.stack(aligned_zero_vectors), axis=0)
        # The registered camera rotation is the authoritative panorama
        # orientation. Optical-flow yaw remains only a fallback for a degenerate
        # vertical ray; accumulating it as the primary heading causes drift.
        heading = _horizontal_heading(
            reconstructed_zero,
            vertical=vertical,
            axis_x=axis_x,
            axis_y=axis_y,
        )
        if heading is None:
            heading = (
                initial_heading
                + _yaw_at(panorama_yaw_track, timestamp_ms)
                - initial_yaw
            ) % 360
        rotation_candidates = panorama_rotations[timestamp_ms]
        world_from_panorama = next(
            (matrix for face_index, matrix in rotation_candidates if face_index == 0),
            rotation_candidates[0][1],
        )
        canonical_from_panorama = canonical_from_reconstruction @ world_from_panorama
        orientation_q = tuple(
            float(value) for value in pycolmap.Rotation3d(canonical_from_panorama).quat
        )
        face_coverage = min(1.0, len(centers[timestamp_ms]) / len(FACE_YAWS))
        samples.append(
            SfMPathSample(
                timestamp_ms=timestamp_ms,
                x=float(np.dot(center, axis_x)) * metric_scale,
                y=float(np.dot(center, axis_y)) * metric_scale,
                heading_deg=heading,
                confidence=max(0.2, 0.9 * face_coverage),
                relative_z=float(np.dot(center, vertical)) * metric_scale,
                orientation_q=orientation_q,
            )
        )
    return samples


def _interpolate(samples: list[SfMPathSample], end_timestamp_ms: int) -> list[SfMPathSample]:
    timestamps = np.array([sample.timestamp_ms for sample in samples], dtype=np.float64)
    target = np.arange(
        0, end_timestamp_ms + 1, PATH_SAMPLE_INTERVAL_MS, dtype=np.float64
    )
    xs = np.interp(target, timestamps, [sample.x for sample in samples])
    ys = np.interp(target, timestamps, [sample.y for sample in samples])
    relative_zs = np.interp(target, timestamps, [sample.relative_z for sample in samples])
    headings = np.unwrap(np.radians([sample.heading_deg for sample in samples]))
    interpolated_headings = np.interp(target, timestamps, headings)
    confidences = np.interp(target, timestamps, [sample.confidence for sample in samples])
    interpolated_orientations: list[tuple[float, float, float, float] | None]
    if all(sample.orientation_q is not None for sample in samples):
        quaternions = np.asarray(
            [sample.orientation_q for sample in samples],
            dtype=np.float64,
        )
        for index in range(1, len(quaternions)):
            if float(np.dot(quaternions[index - 1], quaternions[index])) < 0:
                quaternions[index] *= -1
        components = np.column_stack(
            [np.interp(target, timestamps, quaternions[:, axis]) for axis in range(4)]
        )
        components /= np.maximum(
            np.linalg.norm(components, axis=1, keepdims=True),
            1e-9,
        )
        interpolated_orientations = [
            tuple(float(value) for value in quaternion)
            for quaternion in components
        ]
    else:
        interpolated_orientations = [None] * len(target)
    return [
        SfMPathSample(
            timestamp_ms=int(timestamp_ms),
            x=float(x),
            y=float(y),
            heading_deg=math.degrees(float(heading)) % 360,
            confidence=float(confidence),
            relative_z=float(relative_z),
            orientation_q=orientation_q,
        )
        for timestamp_ms, x, y, heading, confidence, relative_z, orientation_q in zip(
            target,
            xs,
            ys,
            interpolated_headings,
            confidences,
            relative_zs,
            interpolated_orientations,
            strict=True,
        )
    ]


def _remove_isolated_spatial_outliers(
    samples: list[SfMPathSample],
) -> list[SfMPathSample]:
    """Drop a one-frame SfM excursion that immediately returns to the route."""
    if len(samples) < 5:
        return samples
    coordinates = np.asarray(
        [(sample.x, sample.y, sample.relative_z) for sample in samples],
        dtype=np.float64,
    )
    steps = np.linalg.norm(np.diff(coordinates, axis=0), axis=1)
    positive_steps = steps[steps > 1e-8]
    if not len(positive_steps):
        return samples
    threshold = max(float(np.median(positive_steps)) * 6.0, 1e-6)
    rejected: set[int] = set()
    for index in range(1, len(samples) - 1):
        left_step = float(np.linalg.norm(coordinates[index] - coordinates[index - 1]))
        right_step = float(np.linalg.norm(coordinates[index + 1] - coordinates[index]))
        bypass_step = float(
            np.linalg.norm(coordinates[index + 1] - coordinates[index - 1])
        )
        if (
            left_step > threshold
            and right_step > threshold
            and bypass_step <= threshold * 2.0
        ):
            rejected.add(index)
    return [sample for index, sample in enumerate(samples) if index not in rejected]


def _smooth_camera_track(samples: list[SfMPathSample]) -> list[SfMPathSample]:
    """Suppress one-frame SfM center jitter without erasing real site turns."""
    if len(samples) < 5:
        return samples
    coordinates = np.array([(sample.x, sample.y) for sample in samples], dtype=np.float64)
    padded = np.pad(coordinates, ((4, 4), (0, 0)), mode="edge")
    kernel = np.array([1, 2, 3, 4, 5, 4, 3, 2, 1], dtype=np.float64) / 25.0
    smoothed = np.column_stack(
        [np.convolve(padded[:, axis], kernel, mode="valid") for axis in range(2)]
    )
    smoothed -= smoothed[0]
    return [
        SfMPathSample(
            timestamp_ms=sample.timestamp_ms,
            x=float(point[0]),
            y=float(point[1]),
            heading_deg=sample.heading_deg,
            confidence=sample.confidence,
            relative_z=sample.relative_z,
            orientation_q=sample.orientation_q,
        )
        for sample, point in zip(samples, smoothed, strict=True)
    ]


def recover_sfm_path(
    source: Path,
    *,
    end_timestamp_ms: int,
    spatial_model_output: Path | None = None,
) -> list[SfMPathSample]:
    with temporary_workspace(prefix="progress-sfm-") as temporary:
        workspace = Path(temporary)
        panoramas = _extract_panoramas(source, workspace / "panoramas")
        tracking_panoramas = _extract_panoramas(
            source,
            workspace / "tracking",
            fps=TRACKING_FPS,
            width=960,
            height=480,
        )
        panorama_yaw_track = _panorama_yaw_track(tracking_panoramas)
        faces = workspace / "faces"
        _render_faces(panoramas, faces)
        reconstruction = _reconstruct(faces, workspace)
        samples = _remove_isolated_spatial_outliers(
            _raw_samples(
                reconstruction,
                panorama_yaw_track,
                spatial_model_output=spatial_model_output,
            )
        )
    return _interpolate(samples, end_timestamp_ms)
