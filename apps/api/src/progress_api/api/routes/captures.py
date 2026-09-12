import json
import uuid
from datetime import datetime, time, timedelta
from decimal import Decimal
from math import atan2, ceil, cos, degrees, hypot, radians, sin
from pathlib import PurePath

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from progress_api.access import require_project_role
from progress_api.config import get_settings
from progress_api.dependencies import CurrentUser, DbSession
from progress_api.models import (
    CameraPose,
    Capture,
    CaptureDatasetDate,
    CapturePathPoint,
    Floor,
    HumanProgressEntry,
    Keyframe,
    MediaFile,
    MultipartUploadSession,
    PathControlPoint,
    PathEvaluationPoint,
    ProcessingJob,
    Project,
    VideoMetadata,
)
from progress_api.models.base import utc_now
from progress_api.object_storage import (
    EXTERNAL_MEDIA_BUCKET,
    abort_multipart_upload,
    complete_multipart_upload,
    create_multipart_upload,
    delete_object,
    list_multipart_parts,
    local_storage_status,
    object_size,
    presign_get_object,
    presign_upload_part,
    upload_capacity,
)
from progress_api.schemas.capture import (
    CameraPoseRead,
    CameraPoseUpdate,
    CaptureCreate,
    CaptureDetailRead,
    CapturePathPointRead,
    CaptureRead,
    CaptureStartPointUpdate,
    CaptureStartPointUpdateRead,
    KeyframeRead,
    LocalizationRunRead,
    MediaFileCreate,
    MediaFileRead,
    MultipartCompleteRead,
    MultipartCompleteRequest,
    MultipartInitiateRead,
    MultipartPartRead,
    MultipartPartsRequest,
    MultipartPartUrl,
    MultipartStatusRead,
    PathCalibrationRead,
    PathCalibrationRequest,
    PathControlPointFitRead,
    PathControlPointFitRequest,
    PathControlPointRead,
    PathEvaluationPointRead,
    PathEvaluationRead,
    PathEvaluationRequest,
    PathEvaluationSummary,
    ProcessingJobRead,
    RigidPathTransformRead,
    RigidPathTransformRequest,
    RouteVectorRead,
    StitchedMediaAttach,
    StorageStatusRead,
    VideoMetadataRead,
)
from progress_api.services.video_pipeline import dispatch_video_job
from progress_api.worker import celery_app

router = APIRouter()
settings = get_settings()
PART_SIZE_BYTES = 16 * 1024 * 1024
PRESIGNED_URL_TTL = timedelta(hours=1)
# A low-confidence legacy path is still useful for manual Virtual Tour review.
# Keep the floor at Stella's practical minimum;
# confidence is still exposed and never promoted to an automatic progress fact.
ROUTE_VECTOR_MIN_CONFIDENCE = 0.25
ROUTE_VECTOR_MAX_STEP_FACTOR = 4.0
ROUTE_VECTOR_VISIBLE_LOOKAHEAD = 6
ROUTE_VECTOR_MAX_VISIBLE_DISTANCE_FACTOR = 8.0
ROUTE_VECTOR_MIN_STRAIGHTNESS = 0.82
# A visual tour should offer more than one ring in a straight observed walk,
# but never guess that a destination around a corner is visible.  Three sparse
# stations in each direction is enough to feel like a spatial tour while
# remaining conservative when a lightweight SLAM map has no wall mesh.
# Legacy Stella captures have no trustworthy browser-side depth mesh, but their
# ordered visual track is still continuous. Three neighbours and a near-perfect
# straightness requirement reduced a gently curving walkthrough to only one
# ring in each direction (the 21/12 capture is the clearest example). Expose a
# wider local corridor like the accepted reference while still rejecting an
# abrupt 90-degree turn through a wall.
ROUTE_VECTOR_AUTOMATIC_NEIGHBOR_STEPS = 6
ROUTE_VECTOR_AUTOMATIC_MIN_STRAIGHTNESS = 0.75
EVALUATION_REQUIRED_POINT_COUNT = 20
PROTECTED_REFERENCE_CAPTURE_ID = uuid.UUID("b78c9804-76c2-4e96-93d4-53cf55ffba3f")
PORTAL_CAMERA_HEIGHT_M = 1.65
PORTAL_MAX_SAME_FLOOR_HEIGHT_DRIFT_M = 0.35


def _require_upload_capacity(file_size_bytes: int) -> None:
    allowed, required, disk = upload_capacity(file_size_bytes=file_size_bytes)
    if allowed:
        return
    free_gb = disk.free_bytes / 1024**3 if disk else 0
    required_gb = required / 1024**3
    raise HTTPException(
        status_code=507,
        detail=(
            f"พื้นที่จัดเก็บไม่เพียงพอ: เหลือ {free_gb:.1f} GB แต่ไฟล์นี้และพื้นที่ "
            f"ประมวลผลต้องมีอย่างน้อย {required_gb:.1f} GB กรุณาย้าย MinIO/Temp "
            "ไปไดรฟ์ใหม่ก่อนอัปโหลด"
        ),
    )


@router.get("/{project_id}/storage/status", response_model=StorageStatusRead)
def get_storage_status(
    project_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> StorageStatusRead:
    require_project_role(
        db,
        project_id=project_id,
        user_id=user.id,
        allowed_roles={"admin", "sub_admin", "reviewer", "viewer"},
    )
    project_bytes = int(
        db.scalar(
            select(func.coalesce(func.sum(MediaFile.size_bytes), 0)).where(
                MediaFile.project_id == project_id,
                MediaFile.upload_status.in_({"UPLOADING", "READY"}),
            )
        )
        or 0
    )
    disk = local_storage_status()
    minimum = int(settings.storage_min_free_gb * 1024**3)
    if disk is None:
        return StorageStatusRead(
            provider="S3-compatible",
            project_object_bytes=project_bytes,
            minimum_free_bytes=minimum,
            upload_allowed=True,
            message="Object Storage ภายนอกหรือไม่สามารถอ่านพื้นที่ดิสก์ของ Provider ได้",
        )
    allowed = disk.free_bytes >= minimum
    return StorageStatusRead(
        provider="Local MinIO",
        project_object_bytes=project_bytes,
        disk_total_bytes=disk.total_bytes,
        disk_free_bytes=disk.free_bytes,
        minimum_free_bytes=disk.minimum_free_bytes,
        upload_allowed=allowed,
        guard_path=disk.path,
        message=(
            "พร้อมรับไฟล์ แต่ระบบจะตรวจพื้นที่ตามขนาดวิดีโออีกครั้ง"
            if allowed
            else "พื้นที่ต่ำกว่าค่าสำรอง ระบบหยุดรับวิดีโอใหม่เพื่อป้องกันข้อมูลเสียหาย"
        ),
    )


def _require_development_capture(capture: Capture) -> None:
    if capture.dataset_split == "HOLDOUT_TEST":
        raise HTTPException(
            status_code=409,
            detail=("ชุดทดสอบ Holdout ถูกล็อกไว้สำหรับวัดผล ห้ามปรับเส้นทางหรือใช้จุดสอบเทียบ"),
        )


def _evaluation_summary(points: list[PathEvaluationPoint]) -> PathEvaluationSummary | None:
    if not points:
        return None
    count = len(points)
    within = sum(point.is_within_tolerance for point in points)
    squared_errors = sum(float(point.error_normalized) ** 2 for point in points)
    return PathEvaluationSummary(
        point_count=count,
        required_point_count=EVALUATION_REQUIRED_POINT_COUNT,
        is_ready=count >= EVALUATION_REQUIRED_POINT_COUNT,
        tolerance_normalized=points[0].tolerance_normalized,
        within_tolerance_count=within,
        accuracy_percent=Decimal(str(round(within / count * 100, 3))),
        rmse_normalized=Decimal(str(round((squared_errors / count) ** 0.5, 8))),
        max_error_normalized=max(point.error_normalized for point in points),
    )


def _delete_storage_objects(keys: set[str]) -> None:
    """Best-effort cleanup after the database no longer references the files."""
    for key in keys:
        try:
            delete_object(key=key)
        except Exception:
            # A failed object cleanup must not resurrect a deleted Capture. S3
            # lifecycle cleanup can remove an orphan later.
            continue


def _abort_storage_uploads(uploads: list[tuple[str, str]]) -> None:
    for key, upload_id in uploads:
        try:
            abort_multipart_upload(key=key, upload_id=upload_id)
        except Exception:
            continue


def _build_route_vectors(
    rows: list[tuple[Keyframe, MediaFile, CameraPose | None]],
) -> list[RouteVectorRead]:
    """Build only temporally and geometrically supported visual-SfM links.

    Plan proximity is deliberately not used: two images can overlap on a drawing
    while being separated by a wall or by a different part of the walkthrough.
    """
    all_frames = [
        (keyframe, pose)
        for keyframe, _media, pose in rows
        if pose is not None
    ]
    has_authoritative_visibility = any(
        getattr(pose, "visibility_target_ids", None) is not None
        for _, pose in all_frames
    )
    # Every localized panorama is a reviewable station. The station flag is
    # retained so legacy/incomplete captures still have a safe fallback.
    tour_frames = [item for item in all_frames if getattr(item[0], "is_warp_point", False)]
    is_protected_reference = any(
        getattr(keyframe, "capture_id", None) == PROTECTED_REFERENCE_CAPTURE_ID
        for keyframe, _pose in all_frames
    )
    # A successful spatial reconstruction already contains the information
    # needed to decide which panoramas can be seen from one another.  Treat it
    # like an imported visibility graph instead of replacing it with a small
    # chronological neighbourhood.  The latter was the reason the 21/12 tour
    # exposed only 2-5 rings even though its reconstruction stored 20 visible
    # targets per station.
    spatial_graph_poses = [
        pose
        for _keyframe, pose in all_frames
        if getattr(pose, "visibility_target_ids", None) is not None
    ]

    def has_complete_spatial_pose(pose: CameraPose) -> bool:
        return (
            "pycolmap-spatial" in str(getattr(pose, "algorithm", ""))
            and all(
                getattr(pose, field, None) is not None
                for field in (
                    "visual_x",
                    "visual_y",
                    "visual_z",
                    "visual_ground_z",
                    "orientation_qx",
                    "orientation_qy",
                    "orientation_qz",
                    "orientation_qw",
                )
            )
        )

    has_trusted_spatial_visibility = bool(spatial_graph_poses) and all(
        has_complete_spatial_pose(pose) for pose in spatial_graph_poses
    )
    use_stored_visibility_graph = (
        is_protected_reference or has_trusted_spatial_visibility
    )
    # An imported mesh visibility graph may legitimately target an in-between
    # panorama that is not one of the sparse map/timeline stations. Keep every
    # graph node available here; filtering first silently discarded approved
    # visible portals (20 became 1 on the 20/12 reference capture).
    frames = (
        all_frames
        if has_authoritative_visibility
        else (tour_frames if len(tour_frames) >= 2 else all_frames)
    )

    links: set[tuple[uuid.UUID, uuid.UUID]] = set()
    visual_steps: list[float] = []
    for (_first_frame, first), (_second_frame, second) in zip(frames, frames[1:], strict=False):
        values = (
            getattr(first, "visual_x", None),
            getattr(first, "visual_y", None),
            getattr(second, "visual_x", None),
            getattr(second, "visual_y", None),
        )
        if all(value is not None for value in values):
            visual_steps.append(hypot(float(values[2] - values[0]), float(values[3] - values[1])))
    positive_steps = sorted(step for step in visual_steps if step > 1e-8)
    median_step = positive_steps[len(positive_steps) // 2] if positive_steps else 0.0

    # Offer several portals along a straight, observed part of the walk, as a
    # spatial tour does. Never jump across a turn: direct/cumulative distance
    # drops sharply at corners, which also avoids presenting a portal through a
    # wall when no depth mesh is available in the browser.
    for source_index, (source_frame, source) in enumerate(frames):
        cumulative_distance = 0.0
        previous = source
        for target_index in range(
            source_index + 1,
            min(len(frames), source_index + ROUTE_VECTOR_VISIBLE_LOOKAHEAD + 1),
        ):
            target_frame, target = frames[target_index]
            if source.floor_id != target.floor_id:
                break
            if source.localization_run_id != target.localization_run_id:
                break
            if (
                min(float(previous.confidence), float(target.confidence))
                < ROUTE_VECTOR_MIN_CONFIDENCE
            ):
                break
            values = (
                getattr(source, "visual_x", None),
                getattr(source, "visual_y", None),
                getattr(source, "visual_heading_deg", None),
                getattr(previous, "visual_x", None),
                getattr(previous, "visual_y", None),
                getattr(target, "visual_x", None),
                getattr(target, "visual_y", None),
            )
            if any(value is None for value in values):
                break
            segment_distance = hypot(float(values[5] - values[3]), float(values[6] - values[4]))
            if segment_distance <= 1e-8:
                previous = target
                continue
            if median_step and segment_distance > median_step * ROUTE_VECTOR_MAX_STEP_FACTOR:
                break
            cumulative_distance += segment_distance
            direct_distance = hypot(float(values[5] - values[0]), float(values[6] - values[1]))
            straightness = direct_distance / max(cumulative_distance, 1e-8)
            visible_distance = (
                not median_step
                or direct_distance <= median_step * ROUTE_VECTOR_MAX_VISIBLE_DISTANCE_FACTOR
            )
            is_immediate = target_index == source_index + 1
            if is_immediate or (visible_distance and straightness >= ROUTE_VECTOR_MIN_STRAIGHTNESS):
                links.add((source_frame.id, target_frame.id))
                links.add((target_frame.id, source_frame.id))
            previous = target

    # A stored visibility graph supplies candidate links. Post-reference
    # backfills can contain proximity-only candidates, so later captures also
    # require temporal continuity and a straight observed route segment.
    if has_authoritative_visibility:
        links.clear()
        frames_by_id = {str(keyframe.id): (keyframe, pose) for keyframe, pose in frames}
        graph_sources = [
            (keyframe, pose)
            for keyframe, pose in frames
            if getattr(pose, "visibility_target_ids", None) is not None
        ]

        def pose_distance(first: CameraPose, second: CameraPose) -> float:
            if (
                first.visual_x is not None
                and first.visual_y is not None
                and second.visual_x is not None
                and second.visual_y is not None
            ):
                return hypot(
                    float(first.visual_x - second.visual_x),
                    float(first.visual_y - second.visual_y),
                )
            return float("inf")

        station_index_by_id = {
            keyframe.id: index for index, (keyframe, _pose) in enumerate(tour_frames)
        }
        station_steps = [
            pose_distance(first, second)
            for (_first_frame, first), (_second_frame, second) in zip(
                tour_frames, tour_frames[1:], strict=False
            )
        ]
        positive_station_steps = sorted(step for step in station_steps if step > 1e-8)
        median_station_step = (
            positive_station_steps[len(positive_station_steps) // 2]
            if positive_station_steps
            else 0.0
        )

        def is_safe_station_link(source_id: uuid.UUID, target_id: uuid.UUID) -> bool:
            """Reject graph links that jump through an unobserved wall or turn."""
            if use_stored_visibility_graph:
                return True
            source_index = station_index_by_id.get(source_id)
            target_index = station_index_by_id.get(target_id)
            if source_index is None or target_index is None:
                return False
            separation = abs(target_index - source_index)
            if separation == 0 or separation > ROUTE_VECTOR_VISIBLE_LOOKAHEAD:
                return False
            left, right = sorted((source_index, target_index))
            segment_poses = [pose for _frame, pose in tour_frames[left : right + 1]]
            cumulative = sum(
                pose_distance(first, second)
                for first, second in zip(segment_poses, segment_poses[1:], strict=False)
            )
            direct = pose_distance(segment_poses[0], segment_poses[-1])
            if not all(value < float("inf") for value in (cumulative, direct)):
                return False
            if separation == 1:
                return True
            if median_station_step and direct > (
                median_station_step * ROUTE_VECTOR_MAX_VISIBLE_DISTANCE_FACTOR
            ):
                return False
            return direct / max(cumulative, 1e-8) >= ROUTE_VECTOR_MIN_STRAIGHTNESS

        # A generated graph from a lightweight SLAM reconstruction used to be
        # a list of geometrically-nearest stations.  That can join two sides
        # of a wall.  The subsequent safety repair therefore exposed only one
        # previous and one next station, which made an otherwise valid upload
        # feel unlike a Preimage/OpenSpace walk.  Rebuild the non-imported
        # graph from the recorded order instead: expose up to three stations
        # in either direction only while their *own visual track* is almost
        # straight.  At a turn it automatically falls back to the immediate
        # neighbours, so no operator needs to author portals by hand.
        if not use_stored_visibility_graph:
            for source_index, (source_frame, source) in enumerate(tour_frames):
                for target_index in range(
                    max(0, source_index - ROUTE_VECTOR_AUTOMATIC_NEIGHBOR_STEPS),
                    min(
                        len(tour_frames),
                        source_index + ROUTE_VECTOR_AUTOMATIC_NEIGHBOR_STEPS + 1,
                    ),
                ):
                    if source_index == target_index:
                        continue
                    target_frame, target = tour_frames[target_index]
                    if (
                        source.floor_id != target.floor_id
                        or source.localization_run_id != target.localization_run_id
                        or min(float(source.confidence), float(target.confidence))
                        < ROUTE_VECTOR_MIN_CONFIDENCE
                    ):
                        continue
                    left, right = sorted((source_index, target_index))
                    segment_poses = [
                        pose for _frame, pose in tour_frames[left : right + 1]
                    ]
                    steps = [
                        pose_distance(first, second)
                        for first, second in zip(
                            segment_poses, segment_poses[1:], strict=False
                        )
                    ]
                    cumulative = sum(steps)
                    direct = pose_distance(segment_poses[0], segment_poses[-1])
                    if not all(value < float("inf") for value in (cumulative, direct)):
                        continue
                    separation = right - left
                    # The next physical panorama is always a safe, observed
                    # step.  Longer links require a genuinely straight visual
                    # trajectory; this rejects turns and U-shapes rather than
                    # presenting a ring through a wall.
                    if separation == 1 or (
                        cumulative > 1e-8
                        and direct / cumulative
                        >= ROUTE_VECTOR_AUTOMATIC_MIN_STRAIGHTNESS
                    ):
                        links.add((source_frame.id, target_frame.id))
        else:
            # The protected reference and complete spatial reconstructions
            # contain validated visibility graphs. Project their dense graph
            # nodes onto the sparse panorama stations rendered by the client.
            for source_frame, source in tour_frames:
                compatible_sources = [
                    item
                    for item in graph_sources
                    if item[1].floor_id == source.floor_id
                    and item[1].localization_run_id == source.localization_run_id
                ]
                if not compatible_sources:
                    continue
                donor = source
                if getattr(source, "visibility_target_ids", None) is None:
                    _donor_frame, donor = min(
                        compatible_sources,
                        key=lambda item: (
                            pose_distance(source, item[1]),
                            abs(
                                getattr(item[0], "timestamp_ms", 0)
                                - getattr(source_frame, "timestamp_ms", 0)
                            ),
                        ),
                    )
                try:
                    donor_target_ids = json.loads(donor.visibility_target_ids or "[]")
                except (TypeError, ValueError):
                    continue
                for raw_target_id in donor_target_ids:
                    target_item = frames_by_id.get(str(raw_target_id))
                    if target_item is None:
                        continue
                    target_frame, target = target_item
                    compatible_stations = [
                        item
                        for item in tour_frames
                        if item[1].floor_id == target.floor_id
                        and item[1].localization_run_id == target.localization_run_id
                    ]
                    if not compatible_stations:
                        continue
                    mapped_target_id = min(
                        compatible_stations,
                        key=lambda item: (
                            pose_distance(target, item[1]),
                            abs(
                                getattr(item[0], "timestamp_ms", 0)
                                - getattr(target_frame, "timestamp_ms", 0)
                            ),
                        ),
                    )[0].id
                    if (
                        mapped_target_id != source_frame.id
                        and is_safe_station_link(source_frame.id, mapped_target_id)
                    ):
                        links.add((source_frame.id, mapped_target_id))

        # A capture can be re-sampled into a new set of sparse tour stations
        # after its authoritative mesh graph was generated. Resolve both ends
        # of every visible edge onto those current stations. Rendering a portal
        # for a dense in-between frame and then snapping it to a nearby station
        # after the click is precisely the mismatch the user sees as an
        # inaccurate warp. This projection is read-only and never rewrites the
        # protected poses, station flags or reconstruction.
        for source_frame, source in (
            tour_frames if use_stored_visibility_graph else []
        ):
            compatible_sources = [
                item
                for item in graph_sources
                if item[1].floor_id == source.floor_id
                and item[1].localization_run_id == source.localization_run_id
            ]
            if not compatible_sources:
                continue
            donor = source
            if getattr(source, "visibility_target_ids", None) is None:
                _donor_frame, donor = min(
                    compatible_sources,
                    key=lambda item: (
                        pose_distance(source, item[1]),
                        abs(
                            getattr(item[0], "timestamp_ms", 0)
                            - getattr(source_frame, "timestamp_ms", 0)
                        ),
                    ),
                )
            try:
                donor_target_ids = json.loads(donor.visibility_target_ids or "[]")
            except (TypeError, ValueError):
                continue
            for raw_target_id in donor_target_ids:
                target_item = frames_by_id.get(str(raw_target_id))
                if target_item is None:
                    continue
                target_frame, target = target_item
                compatible_stations = [
                    item
                    for item in tour_frames
                    if item[1].floor_id == target.floor_id
                    and item[1].localization_run_id == target.localization_run_id
                ]
                if not compatible_stations:
                    continue
                mapped_target_id = min(
                    compatible_stations,
                    key=lambda item: (
                        pose_distance(target, item[1]),
                        abs(
                            getattr(item[0], "timestamp_ms", 0)
                            - getattr(target_frame, "timestamp_ms", 0)
                        ),
                    ),
                )[0].id
                if (
                    mapped_target_id != source_frame.id
                    and is_safe_station_link(source_frame.id, mapped_target_id)
                ):
                    links.add((source_frame.id, mapped_target_id))

        # A reconstructed visibility graph may be asymmetric because one
        # panorama passed the feature/mesh threshold while the reverse sample
        # narrowly missed it.  A virtual-tour move still needs a deterministic
        # way back to the exact station it came from; otherwise the return ring
        # disappears or the viewer falls back to a different neighbour.
        if has_trusted_spatial_visibility and not is_protected_reference:
            links.update((target_id, source_id) for source_id, target_id in list(links))

    by_id = {keyframe.id: pose for keyframe, pose in frames}
    result: list[RouteVectorRead] = []
    for source_id, target_id in sorted(links, key=lambda pair: (str(pair[0]), str(pair[1]))):
        source = by_id[source_id]
        target = by_id[target_id]
        # A rigid 360 reconstruction has a validated vertical frame. Stella's
        # vertical axis is inverted relative to the viewer and its monocular
        # scale can drift, so legacy height may only be used as a bounded local
        # slope (the web client exposes one immediate Stella station at a time).
        vertical_is_trusted = all(
            str(getattr(pose, "algorithm", "")).startswith(
                ("hloc-rig-", "rig-pycolmap-")
            )
            for pose in (source, target)
        )
        raw_dz = float((target.relative_z_m or 0) - (source.relative_z_m or 0))
        source_visual_x = getattr(source, "visual_x", None)
        source_visual_y = getattr(source, "visual_y", None)
        source_visual_heading = getattr(source, "visual_heading_deg", None)
        target_visual_x = getattr(target, "visual_x", None)
        target_visual_y = getattr(target, "visual_y", None)
        source_visual_z = getattr(source, "visual_z", None)
        target_ground_z = getattr(target, "visual_ground_z", None)
        quaternion = tuple(
            getattr(source, f"orientation_q{axis}", None) for axis in "xyzw"
        )
        has_full_pose = all(
            value is not None
            for value in (source_visual_z, target_ground_z, *quaternion)
        )
        if all(
            value is not None
            for value in (
                source_visual_x,
                source_visual_y,
                source_visual_heading,
                target_visual_x,
                target_visual_y,
            )
        ):
            visual_dx = float(target_visual_x - source_visual_x)
            visual_dy = float(target_visual_y - source_visual_y)
            visual_distance = hypot(visual_dx, visual_dy)
            if visual_distance < 1e-8:
                continue
            if has_full_pose:
                dz = float(target_ground_z - source_visual_z)
                # The post-reference spatial backfill estimates its floor
                # handle from the camera trajectory. Monocular vertical drift
                # can otherwise lift a same-floor portal toward eye level and
                # paint the ring on a wall. Preserve the audited reference
                # exactly, but keep later same-floor portals within a realistic
                # walking-surface band below the current camera.
                if source.floor_id == target.floor_id and not is_protected_reference:
                    target_visual_z = getattr(target, "visual_z", None)
                    if target_visual_z is not None:
                        camera_height_delta = float(target_visual_z - source_visual_z)
                        bounded_delta = max(
                            -PORTAL_MAX_SAME_FLOOR_HEIGHT_DRIFT_M,
                            min(PORTAL_MAX_SAME_FLOOR_HEIGHT_DRIFT_M, camera_height_delta),
                        )
                        dz = bounded_delta - PORTAL_CAMERA_HEIGHT_M
            elif vertical_is_trusted:
                dz = raw_dz
            else:
                maximum_local_rise = visual_distance * 0.75
                dz = max(-maximum_local_rise, min(maximum_local_rise, -raw_dz))
            # Stella's equirectangular zero longitude is +Z (stored as
            # visual_y) and positive longitude turns toward +X (visual_x).
            visual_bearing = degrees(atan2(visual_dx, visual_dy)) % 360
            if has_full_pose:
                # Preimage's quaternion maps panorama-local coordinates to its
                # Z-up reconstruction. Panorama +X is right, +Y is down and +Z
                # is the image-centre ray. Transforming the world displacement
                # by R^T gives an exact, reciprocal projection at every station.
                # The previous heading-only approximation discarded the small
                # per-station roll/yaw terms, so a point appeared to drift after
                # travelling away and returning through several panoramas.
                qx, qy, qz, qw = (float(value) for value in quaternion)
                local_x = (
                    (1 - 2 * (qy * qy + qz * qz)) * visual_dx
                    + 2 * (qx * qy + qz * qw) * visual_dy
                    + 2 * (qx * qz - qy * qw) * dz
                )
                local_y = (
                    2 * (qx * qy - qz * qw) * visual_dx
                    + (1 - 2 * (qx * qx + qz * qz)) * visual_dy
                    + 2 * (qy * qz + qx * qw) * dz
                )
                local_z = (
                    2 * (qx * qz + qy * qw) * visual_dx
                    + 2 * (qy * qz - qx * qw) * visual_dy
                    + (1 - 2 * (qx * qx + qy * qy)) * dz
                )
                local_horizontal = hypot(local_x, local_z)
                local_yaw = degrees(atan2(local_x, local_z))
                local_pitch = degrees(atan2(-local_y, local_horizontal))
            else:
                local_yaw = (
                    visual_bearing - float(source_visual_heading) + 180
                ) % 360 - 180
                local_pitch = degrees(atan2(dz, visual_distance))
        else:
            continue
        confidence = min(float(source.confidence), float(target.confidence))
        result.append(
            RouteVectorRead(
                from_keyframe_id=source_id,
                to_keyframe_id=target_id,
                delta_x=visual_dx,
                delta_y=visual_dy,
                delta_z=dz,
                distance=visual_distance,
                bearing_deg=visual_bearing,
                local_yaw_deg=local_yaw,
                local_pitch_deg=local_pitch,
                direction_source=(
                    "full-6dof-mesh" if has_full_pose else "visual-slam-pose"
                ),
                confidence=confidence,
                verified=True,
                verification_method=(
                    "full-6dof-equirectangular+triangle-mesh-raycast"
                    if has_full_pose
                    else "shared-visual-slam-track+dense-tour-adjacency"
                ),
            )
        )
    return result


def _multipart_scope(
    *, project_id: uuid.UUID, media_id: uuid.UUID, db: DbSession
) -> tuple[MediaFile, MultipartUploadSession]:
    media = db.get(MediaFile, media_id)
    session = db.scalar(
        select(MultipartUploadSession).where(MultipartUploadSession.media_file_id == media_id)
    )
    if media is None or media.project_id != project_id or session is None:
        raise HTTPException(status_code=404, detail="ไม่พบ Multipart Upload")
    return media, session


def _part_count(media: MediaFile, session: MultipartUploadSession) -> int:
    return ceil(media.size_bytes / session.part_size_bytes)


@router.post(
    "/{project_id}/media",
    response_model=MediaFileRead,
    status_code=status.HTTP_201_CREATED,
)
def create_video_metadata(
    project_id: uuid.UUID,
    payload: MediaFileCreate,
    db: DbSession,
    user: CurrentUser,
) -> MediaFile:
    require_project_role(
        db,
        project_id=project_id,
        user_id=user.id,
        allowed_roles={"admin", "reviewer"},
    )
    _require_upload_capacity(payload.size_bytes)
    media_id = uuid.uuid4()
    suffix = PurePath(payload.original_filename).suffix.lower() or ".mp4"
    media = MediaFile(
        id=media_id,
        project_id=project_id,
        media_kind="VIDEO",
        bucket=settings.s3_bucket,
        object_key=f"projects/{project_id}/captures/pending/{media_id}/source/video{suffix}",
        original_filename=payload.original_filename,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
        upload_status="PENDING",
        created_by_id=user.id,
    )
    db.add(media)
    db.commit()
    db.refresh(media)
    return media


@router.post(
    "/{project_id}/media/multipart",
    response_model=MultipartInitiateRead,
    status_code=status.HTTP_201_CREATED,
)
def initiate_video_multipart(
    project_id: uuid.UUID,
    payload: MediaFileCreate,
    db: DbSession,
    user: CurrentUser,
) -> MultipartInitiateRead:
    require_project_role(
        db,
        project_id=project_id,
        user_id=user.id,
        allowed_roles={"admin", "reviewer"},
    )
    _require_upload_capacity(payload.size_bytes)
    media_id = uuid.uuid4()
    suffix = PurePath(payload.original_filename).suffix.lower()
    object_key = f"projects/{project_id}/captures/{media_id}/source/video{suffix}"
    upload_id = create_multipart_upload(key=object_key, content_type=payload.content_type)
    expires_at = utc_now() + PRESIGNED_URL_TTL
    media = MediaFile(
        id=media_id,
        project_id=project_id,
        media_kind="VIDEO",
        bucket=settings.s3_bucket,
        object_key=object_key,
        original_filename=payload.original_filename,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
        upload_status="UPLOADING",
        created_by_id=user.id,
    )
    upload_session = MultipartUploadSession(
        media_file_id=media_id,
        provider_upload_id=upload_id,
        part_size_bytes=PART_SIZE_BYTES,
        status="INITIATED",
        expires_at=expires_at,
    )
    db.add_all([media, upload_session])
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        abort_multipart_upload(key=object_key, upload_id=upload_id)
        raise HTTPException(status_code=409, detail="ไม่สามารถเริ่ม Upload ได้") from None
    db.refresh(media)
    db.refresh(upload_session)
    return MultipartInitiateRead(
        media=MediaFileRead.model_validate(media),
        upload_session_id=upload_session.id,
        part_size_bytes=upload_session.part_size_bytes,
        part_count=_part_count(media, upload_session),
        expires_at=upload_session.expires_at,
    )


def _multipart_status(
    *, media: MediaFile, session: MultipartUploadSession, upload_urls: list[MultipartPartUrl]
) -> MultipartStatusRead:
    uploaded: list[MultipartPartRead] = []
    if session.status == "INITIATED":
        uploaded = [
            MultipartPartRead(
                part_number=int(part["PartNumber"]),
                etag=str(part["ETag"]),
                size_bytes=int(part["Size"]),
            )
            for part in list_multipart_parts(
                key=media.object_key, upload_id=session.provider_upload_id
            )
        ]
    return MultipartStatusRead(
        media_id=media.id,
        original_filename=media.original_filename,
        size_bytes=media.size_bytes,
        upload_session_id=session.id,
        status=session.status,
        part_size_bytes=session.part_size_bytes,
        part_count=_part_count(media, session),
        expires_at=session.expires_at,
        uploaded_parts=uploaded,
        upload_urls=upload_urls,
    )


@router.get(
    "/{project_id}/media/{media_id}/multipart",
    response_model=MultipartStatusRead,
)
def get_multipart_status(
    project_id: uuid.UUID,
    media_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> MultipartStatusRead:
    require_project_role(db, project_id=project_id, user_id=user.id)
    media, upload_session = _multipart_scope(project_id=project_id, media_id=media_id, db=db)
    return _multipart_status(media=media, session=upload_session, upload_urls=[])


@router.post(
    "/{project_id}/media/{media_id}/multipart/parts",
    response_model=MultipartStatusRead,
)
def create_part_urls(
    project_id: uuid.UUID,
    media_id: uuid.UUID,
    payload: MultipartPartsRequest,
    db: DbSession,
    user: CurrentUser,
) -> MultipartStatusRead:
    require_project_role(
        db,
        project_id=project_id,
        user_id=user.id,
        allowed_roles={"admin", "reviewer"},
    )
    media, upload_session = _multipart_scope(project_id=project_id, media_id=media_id, db=db)
    if upload_session.status != "INITIATED":
        raise HTTPException(status_code=409, detail="Upload นี้ไม่ได้อยู่ในสถานะที่ส่งต่อได้")
    count = _part_count(media, upload_session)
    if any(part > count for part in payload.part_numbers):
        raise HTTPException(status_code=422, detail=f"Part number ต้องไม่เกิน {count}")
    upload_session.expires_at = utc_now() + PRESIGNED_URL_TTL
    urls = [
        MultipartPartUrl(
            part_number=part,
            url=presign_upload_part(
                key=media.object_key,
                upload_id=upload_session.provider_upload_id,
                part_number=part,
            ),
        )
        for part in payload.part_numbers
    ]
    db.commit()
    return _multipart_status(media=media, session=upload_session, upload_urls=urls)


@router.post(
    "/{project_id}/media/{media_id}/multipart/complete",
    response_model=MultipartCompleteRead,
)
def finish_video_multipart(
    project_id: uuid.UUID,
    media_id: uuid.UUID,
    payload: MultipartCompleteRequest,
    db: DbSession,
    user: CurrentUser,
) -> MultipartCompleteRead:
    require_project_role(
        db,
        project_id=project_id,
        user_id=user.id,
        allowed_roles={"admin", "reviewer"},
    )
    media, upload_session = _multipart_scope(project_id=project_id, media_id=media_id, db=db)
    capture = db.scalar(select(Capture).where(Capture.source_video_id == media.id))
    if capture is None:
        raise HTTPException(status_code=409, detail="กรุณาระบุ Capture และจุดเริ่มต้นก่อน")
    if upload_session.status != "INITIATED":
        raise HTTPException(status_code=409, detail="Upload นี้ถูกปิดไปแล้ว")
    expected_numbers = list(range(1, _part_count(media, upload_session) + 1))
    if [part.part_number for part in payload.parts] != expected_numbers:
        raise HTTPException(status_code=422, detail="รายการ Parts ไม่ครบหรือไม่ต่อเนื่อง")

    complete_multipart_upload(
        key=media.object_key,
        upload_id=upload_session.provider_upload_id,
        parts=[{"PartNumber": part.part_number, "ETag": part.etag} for part in payload.parts],
    )
    if object_size(key=media.object_key) != media.size_bytes:
        delete_object(key=media.object_key)
        media.upload_status = "FAILED"
        upload_session.status = "FAILED"
        capture.status = "FAILED"
        db.commit()
        raise HTTPException(status_code=422, detail="ขนาดไฟล์หลัง Upload ไม่ตรงกับไฟล์ต้นทาง")

    now = utc_now()
    media.upload_status = "READY"
    upload_session.status = "COMPLETED"
    upload_session.completed_at = now
    capture.status = "QUEUED"
    job = ProcessingJob(
        capture_id=capture.id,
        job_type="VALIDATE_VIDEO",
        status="QUEUED",
        progress_percent=0,
        attempt_no=1,
        idempotency_key=f"{capture.id}:validate-video:{media.id}",
        pipeline_version="capture-v1",
    )
    db.add(job)
    db.commit()
    db.refresh(media)
    db.refresh(job)
    try:
        if job.job_type == "LOCALIZE":
            celery_app.send_task(
                "progress_api.worker_tasks.localize_capture",
                args=[str(job.id)],
                queue="video_cpu",
                retry=False,
            )
        else:
            dispatch_video_job(job.id)
    except Exception:
        pass
    return MultipartCompleteRead(
        media=MediaFileRead.model_validate(media),
        capture_id=capture.id,
        capture_status=capture.status,
        processing_job_id=job.id,
    )


@router.get("/{project_id}/captures/{capture_id}", response_model=CaptureDetailRead)
def get_capture_detail(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> CaptureDetailRead:
    require_project_role(db, project_id=project_id, user_id=user.id)
    capture = db.get(Capture, capture_id)
    if capture is None or capture.project_id != project_id:
        raise HTTPException(status_code=404, detail="ไม่พบ Capture")
    project = db.get(Project, project_id)
    if (
        project
        and project.structural_tracking_end_date
        and capture.captured_at.date() > project.structural_tracking_end_date
    ):
        raise HTTPException(
            status_code=404,
            detail="Capture นี้อยู่นอกช่วงติดตามงานโครงสร้าง",
        )
    metadata = db.scalar(
        select(VideoMetadata).where(VideoMetadata.media_file_id == capture.source_video_id)
    )
    proxy_key = f"projects/{project_id}/captures/{capture_id}/derived/proxy.mp4"
    proxy = db.scalar(select(MediaFile).where(MediaFile.object_key == proxy_key))
    rows = db.execute(
        select(Keyframe, MediaFile, CameraPose)
        .join(MediaFile, MediaFile.id == Keyframe.media_file_id)
        .outerjoin(CameraPose, CameraPose.keyframe_id == Keyframe.id)
        .where(Keyframe.capture_id == capture_id)
        .order_by(Keyframe.timestamp_ms)
    ).all()
    jobs = list(
        db.scalars(
            select(ProcessingJob)
            .where(ProcessingJob.capture_id == capture_id)
            .order_by(ProcessingJob.created_at.desc())
        )
    )
    path_points = list(
        db.scalars(
            select(CapturePathPoint)
            .where(CapturePathPoint.capture_id == capture_id)
            .order_by(CapturePathPoint.timestamp_ms)
        )
    )
    control_points = list(
        db.scalars(
            select(PathControlPoint)
            .where(PathControlPoint.capture_id == capture_id)
            .order_by(PathControlPoint.created_at)
        )
    )
    evaluation_points = list(
        db.scalars(
            select(PathEvaluationPoint)
            .where(PathEvaluationPoint.capture_id == capture_id)
            .order_by(PathEvaluationPoint.created_at)
        )
    )
    return CaptureDetailRead(
        capture=CaptureRead.model_validate(capture),
        metadata=VideoMetadataRead.model_validate(metadata) if metadata else None,
        proxy_url=presign_get_object(key=proxy.object_key) if proxy else None,
        keyframes=[
            KeyframeRead(
                id=keyframe.id,
                frame_index=keyframe.frame_index,
                timestamp_ms=keyframe.timestamp_ms,
                quality_status=keyframe.quality_status,
                is_warp_point=keyframe.is_warp_point,
                image_url=presign_get_object(key=frame_media.object_key),
                pose=CameraPoseRead.model_validate(pose) if pose else None,
            )
            for keyframe, frame_media, pose in rows
        ],
        route_vectors=_build_route_vectors(rows),
        path_points=[CapturePathPointRead.model_validate(point) for point in path_points],
        control_points=[PathControlPointRead.model_validate(point) for point in control_points],
        evaluation_points=[
            PathEvaluationPointRead.model_validate(point) for point in evaluation_points
        ],
        evaluation_summary=_evaluation_summary(evaluation_points),
        jobs=[ProcessingJobRead.model_validate(job) for job in jobs],
    )


@router.get(
    "/{project_id}/captures/{capture_id}/keyframes/{keyframe_id}/image",
    response_class=RedirectResponse,
    include_in_schema=False,
)
def get_keyframe_image(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    keyframe_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> RedirectResponse:
    """Resolve one panorama without rebuilding the full Capture detail payload."""
    require_project_role(db, project_id=project_id, user_id=user.id)
    row = db.execute(
        select(Keyframe, MediaFile)
        .join(MediaFile, MediaFile.id == Keyframe.media_file_id)
        .join(Capture, Capture.id == Keyframe.capture_id)
        .where(
            Capture.id == capture_id,
            Capture.project_id == project_id,
            Keyframe.id == keyframe_id,
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="ไม่พบภาพ 360")
    _keyframe, media = row
    return RedirectResponse(presign_get_object(key=media.object_key), status_code=307)


@router.get("/{project_id}/captures/{capture_id}/spatial-model")
def get_capture_spatial_model(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
):
    require_project_role(
        db,
        project_id=project_id,
        user_id=user.id,
        allowed_roles={"admin", "sub_admin", "reviewer", "viewer"},
    )
    capture = db.get(Capture, capture_id)
    if capture is None or capture.project_id != project_id:
        raise HTTPException(status_code=404, detail="ไม่พบ Capture")
    prefix = f"projects/{project_id}/captures/{capture_id}/localization/"
    media = db.scalar(
        select(MediaFile).where(
            MediaFile.project_id == project_id,
            MediaFile.media_kind == "SFM_SPATIAL_MODEL",
            MediaFile.object_key.like(f"{prefix}%"),
            MediaFile.upload_status == "READY",
        )
    )
    if media is None:
        raise HTTPException(status_code=404, detail="Capture นี้ยังไม่มีโมเดลสามมิติ")
    return RedirectResponse(presign_get_object(key=media.object_key), status_code=307)


@router.post(
    "/{project_id}/captures/{capture_id}/stitched-media",
    response_model=CaptureRead,
)
def attach_stitched_video(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    payload: StitchedMediaAttach,
    db: DbSession,
    user: CurrentUser,
) -> Capture:
    """Attach a Studio-exported 2:1 MP4 to an existing raw INSV capture."""
    require_project_role(
        db, project_id=project_id, user_id=user.id, allowed_roles={"admin", "reviewer"}
    )
    capture = db.get(Capture, capture_id)
    media = db.get(MediaFile, payload.media_id)
    if capture is None or capture.project_id != project_id:
        raise HTTPException(status_code=404, detail="ไม่พบ Capture")
    if capture.status not in {"STITCHER_REQUIRED", "FAILED"}:
        raise HTTPException(
            status_code=409,
            detail="Capture นี้ไม่อยู่ในสถานะที่รอไฟล์ MP4 จาก Insta360 Studio",
        )
    if (
        media is None
        or media.project_id != project_id
        or media.media_kind != "VIDEO"
        or PurePath(media.original_filename or "").suffix.lower() != ".mp4"
        or media.upload_status not in {"UPLOADING", "PENDING"}
    ):
        raise HTTPException(status_code=422, detail="กรุณาเลือกไฟล์ MP4 360 ที่เพิ่งเริ่มอัปโหลด")
    used_by = db.scalar(
        select(Capture.id).where(
            Capture.source_video_id == media.id,
            Capture.id != capture.id,
        )
    )
    if used_by is not None:
        raise HTTPException(status_code=409, detail="ไฟล์นี้ถูกผูกกับ Capture อื่นแล้ว")

    previous_media = db.get(MediaFile, capture.source_video_id)
    if previous_media is not None and previous_media.id != media.id:
        previous_media.media_kind = "RAW_VIDEO_ARCHIVE"
    capture.source_video_id = media.id
    capture.status = "UPLOADING_STITCHED"
    db.commit()
    db.refresh(capture)
    return capture


@router.post(
    "/{project_id}/captures/{capture_id}/localization",
    response_model=LocalizationRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_capture_localization(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> LocalizationRunRead:
    require_project_role(
        db, project_id=project_id, user_id=user.id, allowed_roles={"admin", "reviewer"}
    )
    capture = db.get(Capture, capture_id)
    if capture is None or capture.project_id != project_id:
        raise HTTPException(status_code=404, detail="ไม่พบ Capture")
    if not db.scalar(select(Keyframe.id).where(Keyframe.capture_id == capture_id).limit(1)):
        raise HTTPException(status_code=409, detail="ต้องประมวลผล Keyframe ให้เสร็จก่อน")
    active = db.scalar(
        select(ProcessingJob.id).where(
            ProcessingJob.capture_id == capture_id,
            ProcessingJob.job_type == "LOCALIZE",
            ProcessingJob.status.in_(["QUEUED", "RUNNING"]),
        )
    )
    if active:
        raise HTTPException(status_code=409, detail="Localization กำลังทำงานอยู่")
    job = ProcessingJob(
        capture_id=capture.id,
        job_type="LOCALIZE",
        status="QUEUED",
        progress_percent=0,
        attempt_no=1,
        idempotency_key=f"{capture.id}:localize:{uuid.uuid4()}",
        pipeline_version="stella-vslam-visual-graph-v1",
    )
    capture.status = "QUEUED_LOCALIZATION"
    db.add(job)
    db.commit()
    db.refresh(job)
    celery_app.send_task(
        "progress_api.worker_tasks.localize_capture",
        args=[str(job.id)],
        queue="video_cpu",
        retry=False,
    )
    return LocalizationRunRead(
        job=ProcessingJobRead.model_validate(job), capture_status=capture.status
    )


@router.patch(
    "/{project_id}/captures/{capture_id}/poses/{pose_id}",
    response_model=CameraPoseRead,
)
def review_camera_pose(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    pose_id: uuid.UUID,
    payload: CameraPoseUpdate,
    db: DbSession,
    user: CurrentUser,
) -> CameraPose:
    require_project_role(
        db, project_id=project_id, user_id=user.id, allowed_roles={"admin", "reviewer"}
    )
    pose = db.get(CameraPose, pose_id)
    keyframe = db.get(Keyframe, pose.keyframe_id) if pose else None
    capture = db.get(Capture, capture_id)
    floor = db.get(Floor, payload.floor_id)
    if (
        pose is None
        or keyframe is None
        or keyframe.capture_id != capture_id
        or capture is None
        or capture.project_id != project_id
        or floor is None
        or floor.project_id != project_id
    ):
        raise HTTPException(status_code=404, detail="ไม่พบ Camera Pose ในโครงการนี้")
    _require_development_capture(capture)
    old_x = float(pose.x)
    old_y = float(pose.y)
    delta_x = float(payload.x) - old_x
    delta_y = float(payload.y) - old_y
    correction_window_ms = 30_000
    path_points = list(
        db.scalars(select(CapturePathPoint).where(CapturePathPoint.capture_id == capture_id))
    )
    for point in path_points:
        time_distance = abs(point.timestamp_ms - keyframe.timestamp_ms)
        if time_distance > correction_window_ms:
            continue
        weight = 1.0 - (time_distance / correction_window_ms)
        corrected_x = min(1.0, max(0.0, float(point.x) + delta_x * weight))
        corrected_y = min(1.0, max(0.0, float(point.y) + delta_y * weight))
        point.x = Decimal(str(round(corrected_x, 6)))
        point.y = Decimal(str(round(corrected_y, 6)))
        if time_distance <= 5_000:
            point.floor_id = floor.id
        if not point.algorithm.endswith("+anchor-correction"):
            point.algorithm = f"{point.algorithm}+anchor-correction"
    pose.floor_id = floor.id
    pose.x = payload.x
    pose.y = payload.y
    pose.heading_deg = payload.heading_deg
    pose.confidence = 1
    pose.needs_review = False
    pose.algorithm = f"{pose.algorithm}+human-review"
    pose.reviewed_by_id = user.id
    pose.reviewed_at = utc_now()
    db.commit()
    db.refresh(pose)
    return pose


@router.post(
    "/{project_id}/captures/{capture_id}/poses/confirm",
    response_model=list[CameraPoseRead],
)
def confirm_capture_floor_poses(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    floor_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> list[CameraPose]:
    require_project_role(
        db, project_id=project_id, user_id=user.id, allowed_roles={"admin", "reviewer"}
    )
    capture = db.get(Capture, capture_id)
    floor = db.get(Floor, floor_id)
    if (
        capture is None
        or capture.project_id != project_id
        or floor is None
        or floor.project_id != project_id
    ):
        raise HTTPException(status_code=404, detail="ไม่พบ Capture หรือชั้นอาคาร")
    _require_development_capture(capture)
    poses = list(
        db.scalars(
            select(CameraPose)
            .join(Keyframe, Keyframe.id == CameraPose.keyframe_id)
            .where(
                Keyframe.capture_id == capture_id,
                CameraPose.floor_id == floor_id,
            )
            .order_by(Keyframe.timestamp_ms)
        )
    )
    if not poses:
        raise HTTPException(status_code=409, detail="ยังไม่มีตำแหน่งภาพในชั้นนี้")
    reviewed_at = utc_now()
    for pose in poses:
        pose.needs_review = False
        pose.reviewed_by_id = user.id
        pose.reviewed_at = reviewed_at
        if "+human-confirmed" not in pose.algorithm:
            pose.algorithm = f"{pose.algorithm}+human-confirmed"
    remaining = db.scalar(
        select(func.count(CameraPose.id))
        .join(Keyframe, Keyframe.id == CameraPose.keyframe_id)
        .where(Keyframe.capture_id == capture_id, CameraPose.needs_review.is_(True))
    )
    if not remaining:
        capture.status = "READY"
    db.commit()
    return poses


@router.post(
    "/{project_id}/captures/{capture_id}/path-calibration",
    response_model=PathCalibrationRead,
)
def calibrate_capture_path(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    payload: PathCalibrationRequest,
    db: DbSession,
    user: CurrentUser,
) -> PathCalibrationRead:
    require_project_role(
        db, project_id=project_id, user_id=user.id, allowed_roles={"admin", "reviewer"}
    )
    capture = db.get(Capture, capture_id)
    floor = db.get(Floor, payload.floor_id)
    if (
        capture is None
        or capture.project_id != project_id
        or floor is None
        or floor.project_id != project_id
    ):
        raise HTTPException(status_code=404, detail="ไม่พบ Capture หรือชั้นในโครงการนี้")
    _require_development_capture(capture)
    first_anchor, second_anchor = payload.anchors
    if first_anchor.timestamp_ms == second_anchor.timestamp_ms:
        raise HTTPException(status_code=422, detail="จุดอ้างอิงต้องมาจากคนละตำแหน่งเวลา")

    path_points = list(
        db.scalars(
            select(CapturePathPoint)
            .where(
                CapturePathPoint.capture_id == capture_id,
                CapturePathPoint.floor_id == floor.id,
            )
            .order_by(CapturePathPoint.timestamp_ms)
        )
    )
    if len(path_points) < 2:
        raise HTTPException(status_code=409, detail="ยังไม่มีเส้นทางสำหรับปรับแนว")

    source_points = []
    for anchor in payload.anchors:
        nearest = min(
            path_points,
            key=lambda point: abs(point.timestamp_ms - anchor.timestamp_ms),
        )
        source_points.append((float(nearest.x), float(nearest.y)))
    (source_x1, source_y1), (source_x2, source_y2) = source_points
    target_x1, target_y1 = float(first_anchor.x), float(first_anchor.y)
    target_x2, target_y2 = float(second_anchor.x), float(second_anchor.y)
    source_length = hypot(source_x2 - source_x1, source_y2 - source_y1)
    target_length = hypot(target_x2 - target_x1, target_y2 - target_y1)
    if source_length < 0.01 or target_length < 0.01:
        raise HTTPException(
            status_code=422,
            detail="จุดอ้างอิงทั้งสองต้องห่างกันมากกว่านี้เพื่อคำนวณทิศและสเกล",
        )

    source_angle = atan2(source_y2 - source_y1, source_x2 - source_x1)
    target_angle = atan2(target_y2 - target_y1, target_x2 - target_x1)
    rotation = target_angle - source_angle
    rotation_deg = degrees(rotation)
    scale = target_length / source_length
    cos_r, sin_r = cos(rotation), sin(rotation)

    def transform(x: float, y: float) -> tuple[float, float]:
        relative_x, relative_y = x - source_x1, y - source_y1
        transformed_x = target_x1 + scale * (relative_x * cos_r - relative_y * sin_r)
        transformed_y = target_y1 + scale * (relative_x * sin_r + relative_y * cos_r)
        return min(1.0, max(0.0, transformed_x)), min(1.0, max(0.0, transformed_y))

    for point in path_points:
        x, y = transform(float(point.x), float(point.y))
        point.x = Decimal(str(round(x, 6)))
        point.y = Decimal(str(round(y, 6)))
        point.heading_deg = Decimal(str(round((float(point.heading_deg) + rotation_deg) % 360, 3)))
        if not point.algorithm.endswith("+plan-calibrated"):
            point.algorithm = f"{point.algorithm}+plan-calibrated"

    pose_rows = list(
        db.execute(
            select(CameraPose, Keyframe)
            .join(Keyframe, CameraPose.keyframe_id == Keyframe.id)
            .where(
                Keyframe.capture_id == capture_id,
                CameraPose.floor_id == floor.id,
            )
        ).all()
    )
    for pose, _keyframe in pose_rows:
        x, y = transform(float(pose.x), float(pose.y))
        pose.x = Decimal(str(round(x, 6)))
        pose.y = Decimal(str(round(y, 6)))
        pose.heading_deg = Decimal(str(round((float(pose.heading_deg) + rotation_deg) % 360, 3)))
        pose.needs_review = False
        if not pose.algorithm.endswith("+plan-calibrated"):
            pose.algorithm = f"{pose.algorithm}+plan-calibrated"
    if pose_rows:
        for anchor in payload.anchors:
            nearest_pose, _nearest_keyframe = min(
                pose_rows,
                key=lambda row: abs(row[1].timestamp_ms - anchor.timestamp_ms),
            )
            nearest_pose.confidence = 1
            nearest_pose.needs_review = False
            nearest_pose.reviewed_by_id = user.id
            nearest_pose.reviewed_at = utc_now()
    db.commit()
    return PathCalibrationRead(
        path_point_count=len(path_points),
        pose_count=len(pose_rows),
        scale=scale,
        rotation_deg=rotation_deg,
    )


@router.post(
    "/{project_id}/captures/{capture_id}/path-transform",
    response_model=RigidPathTransformRead,
)
def transform_capture_path_as_rigid_group(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    payload: RigidPathTransformRequest,
    db: DbSession,
    user: CurrentUser,
) -> RigidPathTransformRead:
    """Place an immutable Stella track on a plan using one group transform."""
    require_project_role(
        db, project_id=project_id, user_id=user.id, allowed_roles={"admin", "reviewer"}
    )
    capture = db.get(Capture, capture_id)
    floor = db.get(Floor, payload.floor_id)
    if (
        capture is None
        or capture.project_id != project_id
        or floor is None
        or floor.project_id != project_id
    ):
        raise HTTPException(status_code=404, detail="Capture or floor not found")
    _require_development_capture(capture)

    pose_rows = list(
        db.execute(
            select(CameraPose, Keyframe)
            .join(Keyframe, CameraPose.keyframe_id == Keyframe.id)
            .where(
                Keyframe.capture_id == capture_id,
                CameraPose.visual_x.is_not(None),
                CameraPose.visual_y.is_not(None),
                CameraPose.visual_heading_deg.is_not(None),
            )
            .order_by(Keyframe.timestamp_ms)
        ).all()
    )
    if len(pose_rows) < 2:
        raise HTTPException(
            status_code=409,
            detail="Stella VSLAM has not produced a usable visual path",
        )

    first_pose = pose_rows[0][0]
    origin_visual_x = float(first_pose.visual_x)
    origin_visual_y = float(first_pose.visual_y)
    origin_plan_x = float(capture.start_x)
    origin_plan_y = float(capture.start_y)
    rotation = radians(payload.rotation_deg)
    cos_r, sin_r = cos(rotation), sin(rotation)
    scale_x = payload.scale_x if payload.scale_x is not None else payload.scale
    scale_y = payload.scale_y if payload.scale_y is not None else payload.scale
    assert scale_x is not None and scale_y is not None

    def transform_visual(x: float, y: float) -> tuple[float, float]:
        relative_x = x - origin_visual_x
        relative_y = y - origin_visual_y
        if payload.mirror:
            relative_x = -relative_x
        return (
            origin_plan_x + payload.offset_x + scale_x * (relative_x * cos_r - relative_y * sin_r),
            origin_plan_y + payload.offset_y + scale_y * (relative_x * sin_r + relative_y * cos_r),
        )

    transformed: list[tuple[CameraPose, Keyframe, float, float, float]] = []
    for pose, keyframe in pose_rows:
        x, y = transform_visual(float(pose.visual_x), float(pose.visual_y))
        if not (0 <= x <= 1 and 0 <= y <= 1):
            raise HTTPException(
                status_code=422,
                detail="The path leaves the floor plan. Reduce scale or change rotation.",
            )
        visual_heading = radians(float(pose.visual_heading_deg))
        forward_x = sin(visual_heading)
        forward_y = cos(visual_heading)
        if payload.mirror:
            forward_x = -forward_x
        plan_forward_x = scale_x * (forward_x * cos_r - forward_y * sin_r)
        plan_forward_y = scale_y * (forward_x * sin_r + forward_y * cos_r)
        plan_heading = degrees(atan2(plan_forward_y, plan_forward_x)) % 360
        transformed.append((pose, keyframe, x, y, plan_heading))

    reviewed_at = utc_now()
    for pose, _keyframe, x, y, plan_heading in transformed:
        normalized_heading = round(plan_heading, 3) % 360
        pose.floor_id = floor.id
        pose.x = Decimal(str(round(x, 6)))
        pose.y = Decimal(str(round(y, 6)))
        pose.heading_deg = Decimal(str(normalized_heading))
        pose.needs_review = False
        pose.reviewed_by_id = user.id
        pose.reviewed_at = reviewed_at
        if not pose.algorithm.endswith("+rigid-plan-transform"):
            pose.algorithm = f"{pose.algorithm}+rigid-plan-transform"[:80]

    path_points = list(
        db.scalars(
            select(CapturePathPoint)
            .where(CapturePathPoint.capture_id == capture_id)
            .order_by(CapturePathPoint.timestamp_ms)
        )
    )
    for point in path_points:
        nearest_pose, nearest_keyframe, x, y, plan_heading = min(
            transformed,
            key=lambda item: abs(item[1].timestamp_ms - point.timestamp_ms),
        )
        del nearest_pose, nearest_keyframe
        normalized_heading = round(plan_heading, 3) % 360
        point.floor_id = floor.id
        point.x = Decimal(str(round(x, 6)))
        point.y = Decimal(str(round(y, 6)))
        point.heading_deg = Decimal(str(normalized_heading))
        if not point.algorithm.endswith("+rigid-plan-transform"):
            point.algorithm = f"{point.algorithm}+rigid-plan-transform"[:80]

    # The first camera centre is the capture start after a rigid placement.
    # Keeping Capture.start_* in sync prevents a later re-run from anchoring
    # the new VSLAM path back to the stale point copied during bulk import.
    _first_pose, _first_keyframe, first_x, first_y, _first_heading = transformed[0]
    capture.start_floor_id = floor.id
    capture.start_x = Decimal(str(round(first_x, 6)))
    capture.start_y = Decimal(str(round(first_y, 6)))
    capture.status = "READY"
    db.commit()
    return RigidPathTransformRead(
        path_point_count=len(path_points),
        pose_count=len(pose_rows),
        scale=(scale_x * scale_y) ** 0.5,
        scale_x=scale_x,
        scale_y=scale_y,
        rotation_deg=payload.rotation_deg,
        mirror=payload.mirror,
        offset_x=payload.offset_x,
        offset_y=payload.offset_y,
    )


@router.patch(
    "/{project_id}/captures/{capture_id}/start-point",
    response_model=CaptureStartPointUpdateRead,
)
def correct_capture_start_point(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    payload: CaptureStartPointUpdate,
    db: DbSession,
    user: CurrentUser,
) -> CaptureStartPointUpdateRead:
    """Move a saved camera track as one group so frame zero matches the plan."""
    require_project_role(
        db, project_id=project_id, user_id=user.id, allowed_roles={"admin", "reviewer"}
    )
    capture = db.get(Capture, capture_id)
    floor = db.get(Floor, payload.floor_id)
    if (
        capture is None
        or capture.project_id != project_id
        or floor is None
        or floor.project_id != project_id
    ):
        raise HTTPException(status_code=404, detail="Capture or floor not found")

    pose_rows = list(
        db.execute(
            select(CameraPose, Keyframe)
            .join(Keyframe, CameraPose.keyframe_id == Keyframe.id)
            .where(Keyframe.capture_id == capture_id)
            .order_by(Keyframe.timestamp_ms)
        ).all()
    )
    floor_pose_rows = [row for row in pose_rows if row[0].floor_id == floor.id]
    path_points = list(
        db.scalars(
            select(CapturePathPoint)
            .where(
                CapturePathPoint.capture_id == capture_id,
                CapturePathPoint.floor_id == floor.id,
            )
            .order_by(CapturePathPoint.timestamp_ms)
        )
    )

    target_x = float(payload.x)
    target_y = float(payload.y)
    if floor_pose_rows:
        origin_x = float(floor_pose_rows[0][0].x)
        origin_y = float(floor_pose_rows[0][0].y)
    else:
        origin_x = float(capture.start_x)
        origin_y = float(capture.start_y)
    delta_x = target_x - origin_x
    delta_y = target_y - origin_y

    shifted_positions = [
        (float(pose.x) + delta_x, float(pose.y) + delta_y) for pose, _keyframe in floor_pose_rows
    ] + [(float(point.x) + delta_x, float(point.y) + delta_y) for point in path_points]
    if any(not (0 <= x <= 1 and 0 <= y <= 1) for x, y in shifted_positions):
        raise HTTPException(
            status_code=422,
            detail=(
                "ย้ายจุดเริ่มต้นแล้วมีบางส่วนของเส้นทางออกนอกแปลน ให้ใช้เมนูปรับแนวเส้นทางเพื่อลด Scale หรือหมุนก่อน"
            ),
        )

    reviewed_at = utc_now()
    for pose, _keyframe in floor_pose_rows:
        pose.x = Decimal(str(round(float(pose.x) + delta_x, 6)))
        pose.y = Decimal(str(round(float(pose.y) + delta_y, 6)))
        pose.reviewed_by_id = user.id
        pose.reviewed_at = reviewed_at
        suffix = "+human-start"
        if not pose.algorithm.endswith(suffix):
            pose.algorithm = f"{pose.algorithm}{suffix}"[:80]
    for point in path_points:
        point.x = Decimal(str(round(float(point.x) + delta_x, 6)))
        point.y = Decimal(str(round(float(point.y) + delta_y, 6)))
        suffix = "+human-start"
        if not point.algorithm.endswith(suffix):
            point.algorithm = f"{point.algorithm}{suffix}"[:80]

    capture.start_floor_id = floor.id
    capture.start_x = Decimal(str(round(target_x, 6)))
    capture.start_y = Decimal(str(round(target_y, 6)))
    db.commit()
    return CaptureStartPointUpdateRead(
        floor_id=floor.id,
        x=capture.start_x,
        y=capture.start_y,
        path_point_count=len(path_points),
        pose_count=len(floor_pose_rows),
    )


@router.post(
    "/{project_id}/captures/{capture_id}/path-control-points/fit",
    response_model=PathControlPointFitRead,
)
def fit_capture_path_from_control_points(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    payload: PathControlPointFitRequest,
    db: DbSession,
    user: CurrentUser,
) -> PathControlPointFitRead:
    """Fit one global similarity transform from 3–5 human ground-truth points."""
    require_project_role(
        db, project_id=project_id, user_id=user.id, allowed_roles={"admin", "reviewer"}
    )
    capture = db.get(Capture, capture_id)
    floor = db.get(Floor, payload.floor_id)
    if (
        capture is None
        or capture.project_id != project_id
        or floor is None
        or floor.project_id != project_id
    ):
        raise HTTPException(status_code=404, detail="Capture or floor not found")
    _require_development_capture(capture)
    keyframe_ids = [point.keyframe_id for point in payload.control_points]
    if len(set(keyframe_ids)) != len(keyframe_ids):
        raise HTTPException(status_code=422, detail="Control points must use unique images")

    rows = list(
        db.execute(
            select(Keyframe, CameraPose)
            .join(CameraPose, CameraPose.keyframe_id == Keyframe.id)
            .where(
                Keyframe.capture_id == capture_id,
                Keyframe.id.in_(keyframe_ids),
                CameraPose.visual_x.is_not(None),
                CameraPose.visual_y.is_not(None),
            )
        ).all()
    )
    row_by_id = {keyframe.id: (keyframe, pose) for keyframe, pose in rows}
    if len(row_by_id) != len(keyframe_ids):
        raise HTTPException(
            status_code=409,
            detail="Some selected images do not have a Stella VSLAM pose",
        )

    targets = {
        point.keyframe_id: (float(point.x), float(point.y)) for point in payload.control_points
    }

    def fit_candidate(mirror: bool) -> tuple[float, float, float, float, list[float]]:
        visual = [
            (
                float(row_by_id[keyframe_id][1].visual_x) * (-1 if mirror else 1),
                float(row_by_id[keyframe_id][1].visual_y),
            )
            for keyframe_id in keyframe_ids
        ]
        plan = [targets[keyframe_id] for keyframe_id in keyframe_ids]
        visual_center = (
            sum(point[0] for point in visual) / len(visual),
            sum(point[1] for point in visual) / len(visual),
        )
        plan_center = (
            sum(point[0] for point in plan) / len(plan),
            sum(point[1] for point in plan) / len(plan),
        )
        dot = cross = visual_squared = 0.0
        for visual_point, plan_point in zip(visual, plan, strict=True):
            visual_x = visual_point[0] - visual_center[0]
            visual_y = visual_point[1] - visual_center[1]
            plan_x = plan_point[0] - plan_center[0]
            plan_y = plan_point[1] - plan_center[1]
            dot += visual_x * plan_x + visual_y * plan_y
            cross += visual_x * plan_y - visual_y * plan_x
            visual_squared += visual_x * visual_x + visual_y * visual_y
        if visual_squared < 1e-8:
            raise HTTPException(
                status_code=422,
                detail="Control images are too close together; choose distant points",
            )
        scale = hypot(dot, cross) / visual_squared
        rotation = atan2(cross, dot)
        cos_r, sin_r = cos(rotation), sin(rotation)
        translated_visual_center = (
            scale * (visual_center[0] * cos_r - visual_center[1] * sin_r),
            scale * (visual_center[0] * sin_r + visual_center[1] * cos_r),
        )
        translation_x = plan_center[0] - translated_visual_center[0]
        translation_y = plan_center[1] - translated_visual_center[1]
        errors: list[float] = []
        for visual_point, plan_point in zip(visual, plan, strict=True):
            predicted_x = translation_x + scale * (
                visual_point[0] * cos_r - visual_point[1] * sin_r
            )
            predicted_y = translation_y + scale * (
                visual_point[0] * sin_r + visual_point[1] * cos_r
            )
            errors.append(hypot(predicted_x - plan_point[0], predicted_y - plan_point[1]))
        return scale, degrees(rotation), translation_x, translation_y, errors

    candidates = [(mirror, fit_candidate(mirror)) for mirror in (False, True)]
    mirror, fitted = min(
        candidates,
        key=lambda candidate: sum(error**2 for error in candidate[1][4]),
    )
    scale, rotation_deg, translation_x, translation_y, errors = fitted

    route_origin = db.execute(
        select(CameraPose, Keyframe)
        .join(Keyframe, CameraPose.keyframe_id == Keyframe.id)
        .where(
            Keyframe.capture_id == capture_id,
            CameraPose.visual_x.is_not(None),
            CameraPose.visual_y.is_not(None),
        )
        .order_by(Keyframe.timestamp_ms)
        .limit(1)
    ).first()
    if route_origin is None:
        raise HTTPException(status_code=409, detail="Stella VSLAM path is unavailable")
    origin_pose = route_origin[0]
    origin_visual_x = float(origin_pose.visual_x) * (-1 if mirror else 1)
    origin_visual_y = float(origin_pose.visual_y)
    rotation = radians(rotation_deg)
    transformed_origin_x = translation_x + scale * (
        origin_visual_x * cos(rotation) - origin_visual_y * sin(rotation)
    )
    transformed_origin_y = translation_y + scale * (
        origin_visual_x * sin(rotation) + origin_visual_y * cos(rotation)
    )
    offset_x = transformed_origin_x - float(capture.start_x)
    offset_y = transformed_origin_y - float(capture.start_y)

    transform_result = transform_capture_path_as_rigid_group(
        project_id,
        capture_id,
        RigidPathTransformRequest(
            floor_id=floor.id,
            scale=scale,
            rotation_deg=rotation_deg,
            mirror=mirror,
            offset_x=offset_x,
            offset_y=offset_y,
        ),
        db,
        user,
    )

    db.execute(delete(PathControlPoint).where(PathControlPoint.capture_id == capture_id))
    stored: list[PathControlPoint] = []
    for point, error in zip(payload.control_points, errors, strict=True):
        control_point = PathControlPoint(
            capture_id=capture_id,
            keyframe_id=point.keyframe_id,
            floor_id=floor.id,
            x=point.x,
            y=point.y,
            error_normalized=Decimal(str(round(error, 8))),
            created_by_id=user.id,
        )
        db.add(control_point)
        stored.append(control_point)
    db.commit()
    for point in stored:
        db.refresh(point)

    rmse = (sum(error**2 for error in errors) / len(errors)) ** 0.5
    return PathControlPointFitRead(
        path_point_count=transform_result.path_point_count,
        pose_count=transform_result.pose_count,
        scale=scale,
        rotation_deg=rotation_deg,
        mirror=mirror,
        offset_x=offset_x,
        offset_y=offset_y,
        rmse_normalized=rmse,
        max_error_normalized=max(errors),
        control_points=[PathControlPointRead.model_validate(point) for point in stored],
    )


@router.put(
    "/{project_id}/captures/{capture_id}/path-evaluation-points",
    response_model=PathEvaluationRead,
)
def replace_capture_path_evaluation_points(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    payload: PathEvaluationRequest,
    db: DbSession,
    user: CurrentUser,
) -> PathEvaluationRead:
    """Snapshot held-out plan positions without modifying the fitted path."""
    require_project_role(
        db, project_id=project_id, user_id=user.id, allowed_roles={"admin", "reviewer"}
    )
    capture = db.get(Capture, capture_id)
    floor = db.get(Floor, payload.floor_id)
    if (
        capture is None
        or capture.project_id != project_id
        or floor is None
        or floor.project_id != project_id
    ):
        raise HTTPException(status_code=404, detail="Capture or floor not found")

    keyframe_ids = [point.keyframe_id for point in payload.evaluation_points]
    if len(set(keyframe_ids)) != len(keyframe_ids):
        raise HTTPException(status_code=422, detail="Evaluation points must use unique images")
    calibration_ids = set(
        db.scalars(
            select(PathControlPoint.keyframe_id).where(PathControlPoint.capture_id == capture_id)
        )
    )
    overlap = calibration_ids.intersection(keyframe_ids)
    if overlap:
        raise HTTPException(
            status_code=422,
            detail="Evaluation images must be different from calibration images",
        )

    evaluation_conditions = [
        Keyframe.capture_id == capture_id,
        Keyframe.id.in_(keyframe_ids),
        CameraPose.floor_id == floor.id,
    ]
    if capture.dataset_split != "HOLDOUT_TEST":
        evaluation_conditions.append(CameraPose.needs_review.is_(False))
    rows = list(
        db.execute(
            select(Keyframe, CameraPose)
            .join(CameraPose, CameraPose.keyframe_id == Keyframe.id)
            .where(*evaluation_conditions)
        ).all()
    )
    row_by_id = {keyframe.id: pose for keyframe, pose in rows}
    if len(row_by_id) != len(keyframe_ids):
        raise HTTPException(
            status_code=409,
            detail="Some evaluation images do not have a verified plan position",
        )

    tolerance = float(payload.tolerance_normalized)
    db.execute(delete(PathEvaluationPoint).where(PathEvaluationPoint.capture_id == capture_id))
    stored: list[PathEvaluationPoint] = []
    for item in payload.evaluation_points:
        pose = row_by_id[item.keyframe_id]
        predicted_x = float(pose.x)
        predicted_y = float(pose.y)
        if not (0 <= predicted_x <= 1 and 0 <= predicted_y <= 1):
            raise HTTPException(
                status_code=409,
                detail="The fitted route leaves the plan and cannot be evaluated",
            )
        error = hypot(predicted_x - float(item.target_x), predicted_y - float(item.target_y))
        point = PathEvaluationPoint(
            capture_id=capture_id,
            keyframe_id=item.keyframe_id,
            floor_id=floor.id,
            localization_run_id=pose.localization_run_id,
            target_x=item.target_x,
            target_y=item.target_y,
            predicted_x=Decimal(str(round(predicted_x, 6))),
            predicted_y=Decimal(str(round(predicted_y, 6))),
            error_normalized=Decimal(str(round(error, 8))),
            tolerance_normalized=payload.tolerance_normalized,
            is_within_tolerance=error <= tolerance,
            created_by_id=user.id,
        )
        db.add(point)
        stored.append(point)
    db.commit()
    for point in stored:
        db.refresh(point)
    summary = _evaluation_summary(stored)
    assert summary is not None
    return PathEvaluationRead(
        evaluation_points=[PathEvaluationPointRead.model_validate(point) for point in stored],
        summary=summary,
    )


@router.post(
    "/{project_id}/captures/{capture_id}/jobs/{job_id}/retry",
    response_model=ProcessingJobRead,
)
def retry_capture_job(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    job_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> ProcessingJob:
    require_project_role(
        db, project_id=project_id, user_id=user.id, allowed_roles={"admin", "reviewer"}
    )
    capture = db.get(Capture, capture_id)
    job = db.get(ProcessingJob, job_id)
    if (
        capture is None
        or capture.project_id != project_id
        or job is None
        or job.capture_id != capture.id
    ):
        raise HTTPException(status_code=404, detail="ไม่พบ Processing Job")
    if job.status in {"QUEUED", "RUNNING"}:
        return job
    if job.status != "FAILED":
        raise HTTPException(status_code=409, detail="Job สถานะนี้ Retry ไม่ได้")
    job.status = "QUEUED"
    job.progress_percent = 0
    job.attempt_no += 1
    job.error_code = None
    job.error_message = None
    job.started_at = None
    job.finished_at = None
    capture.status = "QUEUED_LOCALIZATION" if job.job_type == "LOCALIZE" else "QUEUED"
    db.commit()
    db.refresh(job)
    try:
        dispatch_video_job(job.id)
    except Exception:
        pass
    return job


@router.delete(
    "/{project_id}/captures/{capture_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_capture(
    project_id: uuid.UUID,
    capture_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> None:
    require_project_role(
        db,
        project_id=project_id,
        user_id=user.id,
        allowed_roles={"admin"},
    )
    capture = db.get(Capture, capture_id)
    if capture is None or capture.project_id != project_id:
        raise HTTPException(status_code=404, detail="ไม่พบ Capture")

    active_job = db.scalar(
        select(ProcessingJob.id).where(
            ProcessingJob.capture_id == capture_id,
            ProcessingJob.status.in_(["QUEUED", "RUNNING"]),
        )
    )
    if active_job is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Capture กำลังประมวลผล กรุณารอให้งานจบก่อนลบ",
        )

    keyframe_rows = list(
        db.execute(
            select(Keyframe.id, Keyframe.media_file_id).where(Keyframe.capture_id == capture_id)
        ).all()
    )
    keyframe_ids = [row.id for row in keyframe_rows]
    media_ids = {
        *(row.media_file_id for row in keyframe_rows),
        capture.source_video_id,
    }
    capture_prefix = f"projects/{project_id}/captures/{capture_id}/%"
    derived_media = list(
        db.scalars(select(MediaFile).where(MediaFile.object_key.like(capture_prefix)))
    )
    media_ids.update(media.id for media in derived_media)
    media_rows = list(db.scalars(select(MediaFile).where(MediaFile.id.in_(media_ids))))
    object_keys = {
        media.object_key for media in media_rows if media.bucket != EXTERNAL_MEDIA_BUCKET
    }
    media_key_by_id = {media.id: media.object_key for media in media_rows}
    multipart_rows = list(
        db.scalars(
            select(MultipartUploadSession).where(
                MultipartUploadSession.media_file_id.in_(media_ids),
                MultipartUploadSession.status == "INITIATED",
            )
        )
    )
    pending_uploads = [
        (media_key_by_id[row.media_file_id], row.provider_upload_id)
        for row in multipart_rows
        if row.media_file_id in media_key_by_id
    ]

    # SQLite used by tests does not enforce ON DELETE actions. Explicit order
    # also makes the operation predictable on PostgreSQL.
    if keyframe_ids:
        db.execute(delete(CameraPose).where(CameraPose.keyframe_id.in_(keyframe_ids)))
    db.execute(delete(CapturePathPoint).where(CapturePathPoint.capture_id == capture_id))
    db.execute(delete(Keyframe).where(Keyframe.capture_id == capture_id))
    db.execute(delete(ProcessingJob).where(ProcessingJob.capture_id == capture_id))
    db.execute(
        update(HumanProgressEntry)
        .where(HumanProgressEntry.capture_id == capture_id)
        .values(capture_id=None)
    )
    db.delete(capture)
    db.flush()
    if media_ids:
        db.execute(delete(VideoMetadata).where(VideoMetadata.media_file_id.in_(media_ids)))
        db.execute(
            delete(MultipartUploadSession).where(
                MultipartUploadSession.media_file_id.in_(media_ids)
            )
        )
        db.execute(delete(MediaFile).where(MediaFile.id.in_(media_ids)))
    db.commit()

    _abort_storage_uploads(pending_uploads)
    _delete_storage_objects(object_keys)


@router.get("/{project_id}/captures", response_model=list[CaptureRead])
def list_captures(
    project_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> list[Capture]:
    require_project_role(db, project_id=project_id, user_id=user.id)
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="ไม่พบโครงการ")
    query = select(Capture).where(Capture.project_id == project_id)
    if project.structural_tracking_end_date:
        exclusive_end = datetime.combine(
            project.structural_tracking_end_date + timedelta(days=1),
            time.min,
        )
        query = query.where(Capture.captured_at < exclusive_end)
    return list(db.scalars(query.order_by(Capture.captured_at.desc())))


@router.post(
    "/{project_id}/captures",
    response_model=CaptureRead,
    status_code=status.HTTP_201_CREATED,
)
def create_capture(
    project_id: uuid.UUID,
    payload: CaptureCreate,
    db: DbSession,
    user: CurrentUser,
) -> Capture:
    require_project_role(
        db,
        project_id=project_id,
        user_id=user.id,
        allowed_roles={"admin", "reviewer"},
    )
    project = db.get(Project, project_id)
    media = db.get(MediaFile, payload.source_video_id)
    floor = db.get(Floor, payload.start_floor_id)
    if (
        project is None
        or media is None
        or media.project_id != project_id
        or media.media_kind != "VIDEO"
        or floor is None
        or floor.project_id != project_id
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="วิดีโอหรือชั้นเริ่มต้นไม่อยู่ในโครงการนี้",
        )
    if (
        project.structural_tracking_end_date
        and payload.captured_at.date() > project.structural_tracking_end_date
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "วันที่ Capture อยู่นอกช่วงติดตามงานโครงสร้าง "
                f"ซึ่งสิ้นสุดวันที่ {project.structural_tracking_end_date.isoformat()}"
            ),
        )
    existing = db.scalar(select(Capture.id).where(Capture.source_video_id == media.id))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="วิดีโอนี้ถูกผูกกับ Capture แล้ว",
        )
    capture_date = payload.captured_at.date()
    split_assignment = db.scalar(
        select(CaptureDatasetDate).where(
            CaptureDatasetDate.project_id == project_id,
            CaptureDatasetDate.capture_date == capture_date,
        )
    )
    dataset_split = (
        split_assignment.dataset_split if split_assignment is not None else payload.dataset_split
    )
    if split_assignment is None and dataset_split == "HOLDOUT_TEST":
        db.add(
            CaptureDatasetDate(
                project_id=project_id,
                capture_date=capture_date,
                dataset_split=dataset_split,
            )
        )

    capture = Capture(
        project_id=project_id,
        source_video_id=media.id,
        captured_at=payload.captured_at,
        captured_by_text=(payload.captured_by_text or "").strip() or None,
        start_floor_id=floor.id,
        start_x=payload.start_x,
        start_y=payload.start_y,
        notes=(payload.notes or "").strip() or None,
        dataset_split=dataset_split,
        status="UPLOADING",
        created_by_id=user.id,
    )
    db.add(capture)
    db.commit()
    db.refresh(capture)
    return capture
