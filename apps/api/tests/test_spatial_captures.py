import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from progress_api.api.routes import captures
from progress_api.models import (
    CameraPose,
    Capture,
    CapturePathPoint,
    Keyframe,
    MediaFile,
    ProcessingJob,
    StructuralElement,
)
from progress_api.object_storage import LocalStorageStatus


def test_route_vectors_link_real_spatial_neighbours() -> None:
    floor_id = uuid.uuid4()
    run_id = uuid.uuid4()
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    rows = [
        (
            SimpleNamespace(id=first_id, quality_status="USABLE", is_warp_point=True),
            object(),
            SimpleNamespace(
                floor_id=floor_id,
                x=Decimal("0.20"),
                y=Decimal("0.30"),
                relative_z_m=None,
                visual_x=Decimal("0"),
                visual_y=Decimal("0"),
                visual_heading_deg=Decimal("0"),
                confidence=Decimal("0.9"),
                localization_run_id=run_id,
            ),
        ),
        (
            SimpleNamespace(id=second_id, quality_status="USABLE", is_warp_point=True),
            object(),
            SimpleNamespace(
                floor_id=floor_id,
                x=Decimal("0.26"),
                y=Decimal("0.38"),
                relative_z_m=None,
                visual_x=Decimal("1"),
                visual_y=Decimal("0"),
                visual_heading_deg=Decimal("0"),
                confidence=Decimal("0.9"),
                localization_run_id=run_id,
            ),
        ),
    ]

    vectors = captures._build_route_vectors(rows)  # type: ignore[arg-type]

    assert {(item.from_keyframe_id, item.to_keyframe_id) for item in vectors} == {
        (first_id, second_id),
        (second_id, first_id),
    }
    forward = next(item for item in vectors if item.from_keyframe_id == first_id)
    assert forward.delta_x == pytest.approx(1)
    assert forward.delta_y == pytest.approx(0)
    assert forward.distance == pytest.approx(1)
    assert forward.bearing_deg == pytest.approx(90)


def test_route_vectors_hide_unverified_portals() -> None:
    floor_id = uuid.uuid4()
    run_id = uuid.uuid4()
    rows = [
        (
            SimpleNamespace(id=uuid.uuid4(), is_warp_point=True),
            object(),
            SimpleNamespace(
                floor_id=floor_id,
                visual_x=Decimal(index),
                visual_y=Decimal("0"),
                visual_heading_deg=Decimal("0"),
                confidence=Decimal("0.9"),
                localization_run_id=run_id,
                needs_review=True,
            ),
        )
        for index in range(2)
    ]

    assert captures._build_route_vectors(rows) == []  # type: ignore[arg-type]


def test_route_vectors_bound_and_invert_legacy_vertical_delta() -> None:
    floor_id = uuid.uuid4()
    run_id = uuid.uuid4()
    ids = [uuid.uuid4(), uuid.uuid4()]

    def rows(algorithm: str):
        return [
            (
                SimpleNamespace(id=ids[index], quality_status="USABLE", is_warp_point=True),
                object(),
                SimpleNamespace(
                    floor_id=floor_id,
                    relative_z_m=Decimal(index),
                    visual_x=Decimal(index),
                    visual_y=Decimal("0"),
                    visual_heading_deg=Decimal("0"),
                    confidence=Decimal("0.9"),
                    localization_run_id=run_id,
                    algorithm=algorithm,
                ),
            )
            for index in range(2)
        ]

    legacy = captures._build_route_vectors(rows("stella-vslam-visual-graph-v4"))
    rig = captures._build_route_vectors(rows("hloc-rig-disk-lightglue-poc-v1"))

    assert next(item for item in legacy if item.from_keyframe_id == ids[0]).delta_z == -0.75
    assert next(item for item in rig if item.from_keyframe_id == ids[0]).delta_z == 1


def test_route_vectors_skip_processing_frames_between_tour_stations() -> None:
    floor_id = uuid.uuid4()
    run_id = uuid.uuid4()
    first_id = uuid.uuid4()
    intermediate_id = uuid.uuid4()
    rows = [
        (
            SimpleNamespace(id=first_id, quality_status="USABLE", is_warp_point=True),
            object(),
            SimpleNamespace(
                floor_id=floor_id,
                x=Decimal("0.10"),
                y=Decimal("0.10"),
                relative_z_m=None,
                visual_x=Decimal("0"),
                visual_y=Decimal("0"),
                visual_heading_deg=Decimal("0"),
                confidence=Decimal("0.9"),
                localization_run_id=run_id,
            ),
        ),
        (
            SimpleNamespace(id=intermediate_id, quality_status="USABLE", is_warp_point=False),
            object(),
            SimpleNamespace(
                floor_id=floor_id,
                x=Decimal("0.11"),
                y=Decimal("0.10"),
                relative_z_m=None,
                visual_x=Decimal("0.1"),
                visual_y=Decimal("0"),
                visual_heading_deg=Decimal("0"),
                confidence=Decimal("0.9"),
                localization_run_id=run_id,
            ),
        ),
    ]

    vectors = captures._build_route_vectors(rows)  # type: ignore[arg-type]

    # With only one selected station we retain the legacy fallback so an old or
    # partially processed capture is not left without navigation.
    assert {(item.from_keyframe_id, item.to_keyframe_id) for item in vectors} == {
        (first_id, intermediate_id),
        (intermediate_id, first_id),
    }


def test_route_vectors_use_only_selected_tour_stations() -> None:
    floor_id = uuid.uuid4()
    run_id = uuid.uuid4()
    ids = [uuid.uuid4() for _ in range(3)]
    rows = []
    for index, frame_id in enumerate(ids):
        rows.append(
            (
                SimpleNamespace(
                    id=frame_id,
                    quality_status="USABLE",
                    is_warp_point=index != 1,
                ),
                object(),
                SimpleNamespace(
                    floor_id=floor_id,
                    x=Decimal("0.1"),
                    y=Decimal("0.1"),
                    relative_z_m=None,
                    visual_x=Decimal(index),
                    visual_y=Decimal("0"),
                    visual_heading_deg=Decimal("0"),
                    confidence=Decimal("0.9"),
                    localization_run_id=run_id,
                ),
            )
        )

    vectors = captures._build_route_vectors(rows)  # type: ignore[arg-type]

    assert {(item.from_keyframe_id, item.to_keyframe_id) for item in vectors} == {
        (ids[0], ids[2]),
        (ids[2], ids[0]),
    }


def test_authoritative_visibility_maps_in_between_frames_to_real_warp_stations() -> None:
    floor_id = uuid.uuid4()
    run_id = uuid.uuid4()
    ids = [uuid.uuid4() for _ in range(3)]
    rows = []
    for index, frame_id in enumerate(ids):
        targets = [str(ids[1]), str(ids[2])] if index == 0 else []
        rows.append(
            (
                SimpleNamespace(
                    id=frame_id,
                    quality_status="USABLE",
                    is_warp_point=index != 1,
                ),
                object(),
                SimpleNamespace(
                    floor_id=floor_id,
                    relative_z_m=None,
                    visual_x=Decimal(index),
                    visual_y=Decimal("0"),
                    visual_heading_deg=Decimal("0"),
                    visibility_target_ids=(
                        "[" + ",".join(f'\"{target}\"' for target in targets) + "]"
                    ),
                    confidence=Decimal("0.9"),
                    localization_run_id=run_id,
                ),
            )
        )

    vectors = captures._build_route_vectors(rows)  # type: ignore[arg-type]

    # The mesh may see a dense processing panorama, but a rendered portal must
    # resolve to a real tour station before the click. Otherwise the client
    # draws one destination and snaps to a different nearby station afterward.
    assert {
        item.to_keyframe_id
        for item in vectors
        if item.from_keyframe_id == ids[0]
    } == {ids[2]}


def test_authoritative_visibility_does_not_jump_across_a_distant_turn() -> None:
    floor_id = uuid.uuid4()
    run_id = uuid.uuid4()
    ids = [uuid.uuid4() for _ in range(8)]
    points = [(0, 0), (1, 0), (2, 0), (3, 0), (3, 1), (3, 2), (3, 3), (2, 3)]
    rows = []
    for index, (frame_id, (x, y)) in enumerate(zip(ids, points, strict=True)):
        rows.append((
            SimpleNamespace(
                id=frame_id,
                capture_id=uuid.uuid4(),
                quality_status="USABLE",
                is_warp_point=True,
            ),
            object(),
            SimpleNamespace(
                floor_id=floor_id,
                relative_z_m=Decimal("0"),
                visual_x=Decimal(x),
                visual_y=Decimal(y),
                visual_heading_deg=Decimal("0"),
                visibility_target_ids=(f'["{ids[-1]}"]' if index == 0 else "[]"),
                confidence=Decimal("0.9"),
                localization_run_id=run_id,
            ),
        ))

    vectors = captures._build_route_vectors(rows)  # type: ignore[arg-type]

    assert not any(
        item.from_keyframe_id == ids[0] and item.to_keyframe_id == ids[-1]
        for item in vectors
    )


def test_generated_visibility_graph_expands_straight_walk_without_manual_portals() -> None:
    """A stale nearest-neighbour graph must not reduce an automatic tour to 2 rings."""
    floor_id = uuid.uuid4()
    run_id = uuid.uuid4()
    ids = [uuid.uuid4() for _ in range(5)]
    rows = [
        (
            SimpleNamespace(
                id=frame_id,
                capture_id=uuid.uuid4(),
                quality_status="USABLE",
                is_warp_point=True,
            ),
            object(),
            SimpleNamespace(
                floor_id=floor_id,
                relative_z_m=Decimal("0"),
                visual_x=Decimal(index),
                visual_y=Decimal("0"),
                visual_heading_deg=Decimal("0"),
                # This mimics an old generated graph that contains only an
                # arbitrary spatial target.  It is not an imported reference.
                visibility_target_ids=(f'["{ids[-1]}"]' if index == 0 else "[]"),
                confidence=Decimal("0.9"),
                localization_run_id=run_id,
            ),
        )
        for index, frame_id in enumerate(ids)
    ]

    vectors = captures._build_route_vectors(rows)  # type: ignore[arg-type]

    assert {
        item.to_keyframe_id for item in vectors if item.from_keyframe_id == ids[0]
    } == {ids[1], ids[2], ids[3], ids[4]}


def test_generated_visibility_graph_covers_a_gently_curving_walk() -> None:
    """A real walkthrough bend should retain several visible forward portals."""
    floor_id = uuid.uuid4()
    run_id = uuid.uuid4()
    ids = [uuid.uuid4() for _ in range(8)]
    points = [
        (0.0, 0.0),
        (1.0, 0.0),
        (1.9, -0.5),
        (2.2, -1.5),
        (2.35, -2.5),
        (2.3, -3.5),
        (1.6, -4.3),
        (0.6, -4.7),
    ]
    rows = [
        (
            SimpleNamespace(
                id=frame_id,
                capture_id=uuid.uuid4(),
                quality_status="USABLE",
                is_warp_point=True,
            ),
            object(),
            SimpleNamespace(
                floor_id=floor_id,
                relative_z_m=Decimal("0"),
                visual_x=Decimal(str(x)),
                visual_y=Decimal(str(y)),
                visual_heading_deg=Decimal("0"),
                visibility_target_ids="[]",
                confidence=Decimal("0.9"),
                localization_run_id=run_id,
            ),
        )
        for frame_id, (x, y) in zip(ids, points, strict=True)
    ]

    vectors = captures._build_route_vectors(rows)  # type: ignore[arg-type]
    second_targets = {
        item.to_keyframe_id
        for item in vectors
        if item.from_keyframe_id == ids[1]
    }

    assert ids[0] in second_targets
    assert set(ids[2:7]).issubset(second_targets)


def test_full_pose_same_floor_portal_stays_below_camera_despite_vertical_drift() -> None:
    floor_id = uuid.uuid4()
    run_id = uuid.uuid4()
    ids = [uuid.uuid4(), uuid.uuid4()]
    rows = []
    for index, frame_id in enumerate(ids):
        rows.append((
            SimpleNamespace(
                id=frame_id,
                capture_id=uuid.uuid4(),
                quality_status="USABLE",
                is_warp_point=True,
            ),
            object(),
            SimpleNamespace(
                floor_id=floor_id,
                relative_z_m=Decimal(index),
                visual_x=Decimal(index),
                visual_y=Decimal("0"),
                visual_z=Decimal(index),
                visual_ground_z=Decimal(index) - Decimal("1.65"),
                visual_heading_deg=Decimal("0"),
                orientation_qx=Decimal("0"),
                orientation_qy=Decimal("0"),
                orientation_qz=Decimal("0"),
                orientation_qw=Decimal("1"),
                visibility_target_ids=(f'["{ids[1]}"]' if index == 0 else "[]"),
                confidence=Decimal("0.9"),
                localization_run_id=run_id,
                algorithm="stella-vslam-visual-graph-v4+pycolmap-spatial-v1",
            ),
        ))

    vectors = captures._build_route_vectors(rows)  # type: ignore[arg-type]
    forward = next(item for item in vectors if item.from_keyframe_id == ids[0])

    assert forward.delta_z == pytest.approx(-1.30)


def test_complete_spatial_pose_does_not_trust_proximity_as_mesh_visibility() -> None:
    """Full camera poses do not make a nearest-neighbour list occlusion-safe."""
    floor_id = uuid.uuid4()
    run_id = uuid.uuid4()
    ids = [uuid.uuid4() for _ in range(9)]
    points = [
        (0, 0), (1, 0), (2, 0), (3, 0), (3, 1),
        (2, 1), (1, 1), (0, 1), (-1, 1),
    ]
    rows = []
    for index, (frame_id, (x, y)) in enumerate(zip(ids, points, strict=True)):
        rows.append((
            SimpleNamespace(
                id=frame_id,
                capture_id=uuid.uuid4(),
                quality_status="USABLE",
                is_warp_point=True,
            ),
            object(),
            SimpleNamespace(
                floor_id=floor_id,
                relative_z_m=Decimal("0"),
                visual_x=Decimal(x),
                visual_y=Decimal(y),
                visual_z=Decimal("1.65"),
                visual_ground_z=Decimal("0"),
                visual_heading_deg=Decimal("0"),
                orientation_qx=Decimal("0"),
                orientation_qy=Decimal("0"),
                orientation_qz=Decimal("0"),
                orientation_qw=Decimal("1"),
                visibility_target_ids=(
                    json.dumps([str(target) for target in ids[1:]])
                    if index == 0
                    else "[]"
                ),
                confidence=Decimal("0.9"),
                localization_run_id=run_id,
                algorithm="stella-vslam-visual-graph-v4+pycolmap-spatial-v1",
            ),
        ))

    vectors = captures._build_route_vectors(rows)  # type: ignore[arg-type]

    targets = {
        item.to_keyframe_id
        for item in vectors
        if item.from_keyframe_id == ids[0]
    }
    assert ids[1] in targets
    assert ids[-1] not in targets
    assert all(
        item.verification_method == "full-6dof-observed-trajectory-corridor"
        for item in vectors
    )
    assert all(
        any(
            reverse.from_keyframe_id == item.to_keyframe_id
            and reverse.to_keyframe_id == item.from_keyframe_id
            for reverse in vectors
        )
        for item in vectors
    )


def test_route_vectors_expose_straight_visible_stations_without_crossing_turns() -> None:
    floor_id = uuid.uuid4()
    run_id = uuid.uuid4()
    straight_ids = [uuid.uuid4() for _ in range(4)]
    straight_rows = []
    for index, frame_id in enumerate(straight_ids):
        straight_rows.append(
            (
                SimpleNamespace(id=frame_id, quality_status="USABLE", is_warp_point=True),
                object(),
                SimpleNamespace(
                    floor_id=floor_id,
                    relative_z_m=None,
                    visual_x=Decimal(index),
                    visual_y=Decimal("0"),
                    visual_heading_deg=Decimal("90"),
                    confidence=Decimal("0.9"),
                    localization_run_id=run_id,
                ),
            )
        )

    straight_vectors = captures._build_route_vectors(straight_rows)  # type: ignore[arg-type]
    assert {
        item.to_keyframe_id for item in straight_vectors if item.from_keyframe_id == straight_ids[0]
    } == set(straight_ids[1:])

    corner_ids = [uuid.uuid4() for _ in range(3)]
    corner_points = [(0, 0), (1, 0), (1, 1)]
    corner_rows = [
        (
            SimpleNamespace(id=frame_id, quality_status="USABLE", is_warp_point=True),
            object(),
            SimpleNamespace(
                floor_id=floor_id,
                relative_z_m=None,
                visual_x=Decimal(x),
                visual_y=Decimal(y),
                visual_heading_deg=Decimal("0"),
                confidence=Decimal("0.9"),
                localization_run_id=run_id,
            ),
        )
        for frame_id, (x, y) in zip(corner_ids, corner_points, strict=True)
    ]
    corner_vectors = captures._build_route_vectors(corner_rows)  # type: ignore[arg-type]
    assert not any(
        item.from_keyframe_id == corner_ids[0] and item.to_keyframe_id == corner_ids[2]
        for item in corner_vectors
    )


def test_route_vector_visual_direction_is_independent_from_plan() -> None:
    floor_id = uuid.uuid4()
    run_id = uuid.uuid4()
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    rows = [
        (
            SimpleNamespace(id=first_id, quality_status="USABLE"),
            object(),
            SimpleNamespace(
                floor_id=floor_id,
                x=Decimal("0.20"),
                y=Decimal("0.20"),
                heading_deg=Decimal("90"),
                relative_z_m=None,
                visual_x=Decimal("0"),
                visual_y=Decimal("0"),
                visual_heading_deg=Decimal("0"),
                confidence=Decimal("0.9"),
                localization_run_id=run_id,
            ),
        ),
        (
            SimpleNamespace(id=second_id, quality_status="USABLE"),
            object(),
            SimpleNamespace(
                floor_id=floor_id,
                x=Decimal("0.20"),
                y=Decimal("0.30"),
                heading_deg=Decimal("90"),
                relative_z_m=None,
                visual_x=Decimal("0"),
                visual_y=Decimal("1"),
                visual_heading_deg=Decimal("0"),
                confidence=Decimal("0.9"),
                localization_run_id=run_id,
            ),
        ),
    ]

    vectors = captures._build_route_vectors(rows)  # type: ignore[arg-type]
    forward = next(item for item in vectors if item.from_keyframe_id == first_id)

    assert forward.bearing_deg == pytest.approx(0)
    assert forward.local_yaw_deg == pytest.approx(0)
    assert forward.direction_source == "visual-slam-pose"
    assert forward.verified is True
    assert forward.confidence == pytest.approx(0.9)


def test_hloc_plan_alignment_does_not_reuse_stale_spatial_pose() -> None:
    floor_id = uuid.uuid4()
    run_id = uuid.uuid4()
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    algorithm = "stella-vslam-visual-graph-v4:previous-hloc-sfm-v1:reference"
    rows = [
        (
            SimpleNamespace(id=first_id, quality_status="USABLE"),
            object(),
            SimpleNamespace(
                floor_id=floor_id,
                x=Decimal("0.20"),
                y=Decimal("0.20"),
                heading_deg=Decimal("0"),
                relative_z_m=None,
                # Deliberately contradictory stale Stella coordinates/pose.
                visual_x=Decimal("0"),
                visual_y=Decimal("0"),
                visual_heading_deg=Decimal("180"),
                visual_z=Decimal("1.65"),
                visual_ground_z=Decimal("0"),
                orientation_qx=Decimal("0"),
                orientation_qy=Decimal("0"),
                orientation_qz=Decimal("0"),
                orientation_qw=Decimal("1"),
                algorithm=algorithm,
                confidence=Decimal("0.9"),
                localization_run_id=run_id,
            ),
        ),
        (
            SimpleNamespace(id=second_id, quality_status="USABLE"),
            object(),
            SimpleNamespace(
                floor_id=floor_id,
                x=Decimal("0.20"),
                y=Decimal("0.30"),
                heading_deg=Decimal("0"),
                relative_z_m=None,
                visual_x=Decimal("1"),
                visual_y=Decimal("0"),
                visual_heading_deg=Decimal("180"),
                visual_z=Decimal("1.65"),
                visual_ground_z=Decimal("0"),
                orientation_qx=Decimal("0"),
                orientation_qy=Decimal("0"),
                orientation_qz=Decimal("0"),
                orientation_qw=Decimal("1"),
                algorithm=algorithm,
                confidence=Decimal("0.9"),
                localization_run_id=run_id,
            ),
        ),
    ]

    vectors = captures._build_route_vectors(rows)  # type: ignore[arg-type]
    forward = next(item for item in vectors if item.from_keyframe_id == first_id)

    assert forward.delta_x == pytest.approx(0)
    assert forward.delta_y == pytest.approx(0.1)
    assert forward.local_yaw_deg == pytest.approx(0)
    assert forward.direction_source == "plan-aligned-heading"


def test_route_vectors_reject_pose_below_manual_review_floor() -> None:
    floor_id = uuid.uuid4()
    run_id = uuid.uuid4()
    rows = [
        (
            SimpleNamespace(id=uuid.uuid4(), quality_status="USABLE"),
            object(),
            SimpleNamespace(
                floor_id=floor_id,
                x=Decimal("0.2"),
                y=Decimal("0.2"),
                relative_z_m=None,
                visual_x=Decimal("0"),
                visual_y=Decimal("0"),
                visual_heading_deg=Decimal("0"),
                confidence=Decimal("0.2"),
                localization_run_id=run_id,
            ),
        ),
        (
            SimpleNamespace(id=uuid.uuid4(), quality_status="USABLE"),
            object(),
            SimpleNamespace(
                floor_id=floor_id,
                x=Decimal("0.3"),
                y=Decimal("0.2"),
                relative_z_m=None,
                visual_x=Decimal("1"),
                visual_y=Decimal("0"),
                visual_heading_deg=Decimal("0"),
                confidence=Decimal("0.9"),
                localization_run_id=run_id,
            ),
        ),
    ]

    assert captures._build_route_vectors(rows) == []  # type: ignore[arg-type]


def _create_project(client: TestClient, headers: dict[str, str]) -> dict[str, object]:
    response = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "อาคารหอพัก 4 ชั้น", "timezone": "Asia/Bangkok"},
    )
    assert response.status_code == 201
    return response.json()


def test_storage_status_blocks_low_disk_and_reports_project_usage(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _create_project(client, auth_headers)
    project_id = project["id"]
    disk = LocalStorageStatus(
        path="C:\\",
        total_bytes=100 * 1024**3,
        free_bytes=9 * 1024**3,
        minimum_free_bytes=50 * 1024**3,
    )
    monkeypatch.setattr(captures, "local_storage_status", lambda: disk)
    monkeypatch.setattr(
        captures,
        "upload_capacity",
        lambda *, file_size_bytes: (False, 52 * 1024**3, disk),
    )

    status_response = client.get(
        f"/api/v1/projects/{project_id}/storage/status",
        headers=auth_headers,
    )
    assert status_response.status_code == 200
    assert status_response.json()["upload_allowed"] is False
    assert status_response.json()["disk_free_bytes"] == 9 * 1024**3

    upload_response = client.post(
        f"/api/v1/projects/{project_id}/media",
        headers=auth_headers,
        json={
            "original_filename": "large.mp4",
            "content_type": "video/mp4",
            "size_bytes": 1024**3,
        },
    )
    assert upload_response.status_code == 507
    assert "52.0 GB" in upload_response.json()["detail"]


def test_floor_and_capture_metadata_are_project_scoped(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    project = _create_project(client, auth_headers)
    project_id = project["id"]

    floor_response = client.post(
        f"/api/v1/projects/{project_id}/floors",
        headers=auth_headers,
        json={"name": "ชั้น 1", "level_index": 1, "elevation_m": 0},
    )
    assert floor_response.status_code == 201
    floor = floor_response.json()

    duplicate_floor = client.post(
        f"/api/v1/projects/{project_id}/floors",
        headers=auth_headers,
        json={"name": "ชั้น 1", "level_index": 2},
    )
    assert duplicate_floor.status_code == 409

    media_response = client.post(
        f"/api/v1/projects/{project_id}/media",
        headers=auth_headers,
        json={
            "original_filename": "VID_20251228_171043_00_013.mp4",
            "content_type": "video/mp4",
            "size_bytes": 1_500_000_000,
        },
    )
    assert media_response.status_code == 201
    media = media_response.json()
    assert media["upload_status"] == "PENDING"
    assert media["object_key"].startswith(f"projects/{project_id}/captures/pending/")

    capture_response = client.post(
        f"/api/v1/projects/{project_id}/captures",
        headers=auth_headers,
        json={
            "source_video_id": media["id"],
            "captured_at": "2025-12-28T17:10:43+07:00",
            "captured_by_text": "Insta360 X5",
            "start_floor_id": floor["id"],
            "start_x": 0.25,
            "start_y": 0.75,
        },
    )
    assert capture_response.status_code == 201
    capture = capture_response.json()
    assert capture["status"] == "UPLOADING"

    duplicate_capture = client.post(
        f"/api/v1/projects/{project_id}/captures",
        headers=auth_headers,
        json={
            "source_video_id": media["id"],
            "captured_at": "2025-12-28T17:10:43+07:00",
            "start_floor_id": floor["id"],
            "start_x": 0.25,
            "start_y": 0.75,
        },
    )
    assert duplicate_capture.status_code == 409

    listed = client.get(
        f"/api/v1/projects/{project_id}/captures",
        headers=auth_headers,
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [capture["id"]]

    other = client.post(
        "/api/v1/auth/register",
        json={
            "email": "unrelated@example.com",
            "display_name": "Unrelated",
            "password": "another-safe-password-123",
        },
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    hidden = client.get(
        f"/api/v1/projects/{project_id}/captures",
        headers=other_headers,
    )
    assert hidden.status_code == 404


def test_admin_can_delete_capture_and_its_media(
    client: TestClient,
    auth_headers: dict[str, str],
    testing_session: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _create_project(client, auth_headers)
    project_id = project["id"]
    floor = client.post(
        f"/api/v1/projects/{project_id}/floors",
        headers=auth_headers,
        json={"name": "ชั้น 1", "level_index": 1},
    ).json()
    media = client.post(
        f"/api/v1/projects/{project_id}/media",
        headers=auth_headers,
        json={
            "original_filename": "bad-capture.mp4",
            "content_type": "video/mp4",
            "size_bytes": 10_000_000,
        },
    ).json()
    capture = client.post(
        f"/api/v1/projects/{project_id}/captures",
        headers=auth_headers,
        json={
            "source_video_id": media["id"],
            "captured_at": "2026-08-22T10:00:00+07:00",
            "start_floor_id": floor["id"],
            "start_x": 0.25,
            "start_y": 0.75,
        },
    ).json()
    deleted_keys: list[str] = []
    monkeypatch.setattr(
        captures,
        "delete_object",
        lambda *, key: deleted_keys.append(key),
    )

    response = client.delete(
        f"/api/v1/projects/{project_id}/captures/{capture['id']}",
        headers=auth_headers,
    )

    assert response.status_code == 204
    assert deleted_keys == [media["object_key"]]
    assert (
        client.get(
            f"/api/v1/projects/{project_id}/captures",
            headers=auth_headers,
        ).json()
        == []
    )
    with testing_session() as db:
        assert db.get(Capture, uuid.UUID(capture["id"])) is None
        assert db.get(MediaFile, uuid.UUID(media["id"])) is None


def test_capture_after_structural_end_date_is_rejected(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    project = _create_project(client, auth_headers)
    project_id = project["id"]
    floor = client.post(
        f"/api/v1/projects/{project_id}/floors",
        headers=auth_headers,
        json={"name": "ชั้น 1", "level_index": 1},
    ).json()
    media = client.post(
        f"/api/v1/projects/{project_id}/media",
        headers=auth_headers,
        json={
            "original_filename": "architecture-only.mp4",
            "content_type": "video/mp4",
            "size_bytes": 10_000_000,
        },
    ).json()
    assert client.patch(
        f"/api/v1/projects/{project_id}/scope",
        headers=auth_headers,
        json={"structural_tracking_end_date": "2026-07-03"},
    ).status_code == 200

    response = client.post(
        f"/api/v1/projects/{project_id}/captures",
        headers=auth_headers,
        json={
            "source_video_id": media["id"],
            "captured_at": "2026-07-04T10:00:00+07:00",
            "start_floor_id": floor["id"],
            "start_x": 0.25,
            "start_y": 0.75,
        },
    )

    assert response.status_code == 422
    assert "สิ้นสุดวันที่ 2026-07-03" in response.json()["detail"]


def test_existing_capture_after_structural_end_date_is_hidden(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    project = _create_project(client, auth_headers)
    project_id = project["id"]
    floor = client.post(
        f"/api/v1/projects/{project_id}/floors",
        headers=auth_headers,
        json={"name": "ชั้น 1", "level_index": 1},
    ).json()
    media = client.post(
        f"/api/v1/projects/{project_id}/media",
        headers=auth_headers,
        json={
            "original_filename": "existing-architecture.mp4",
            "content_type": "video/mp4",
            "size_bytes": 10_000_000,
        },
    ).json()
    capture = client.post(
        f"/api/v1/projects/{project_id}/captures",
        headers=auth_headers,
        json={
            "source_video_id": media["id"],
            "captured_at": "2026-07-04T10:00:00+07:00",
            "start_floor_id": floor["id"],
            "start_x": 0.25,
            "start_y": 0.75,
        },
    ).json()
    assert client.patch(
        f"/api/v1/projects/{project_id}/scope",
        headers=auth_headers,
        json={"structural_tracking_end_date": "2026-07-03"},
    ).status_code == 200

    listed = client.get(
        f"/api/v1/projects/{project_id}/captures", headers=auth_headers
    )
    detail = client.get(
        f"/api/v1/projects/{project_id}/captures/{capture['id']}",
        headers=auth_headers,
    )

    assert listed.status_code == 200
    assert listed.json() == []
    assert detail.status_code == 404
    assert detail.json()["detail"] == "Capture นี้อยู่นอกช่วงติดตามงานโครงสร้าง"


def test_studio_exported_mp4_can_recover_an_insv_capture(
    client: TestClient,
    auth_headers: dict[str, str],
    testing_session: sessionmaker[Session],
) -> None:
    project = _create_project(client, auth_headers)
    project_id = project["id"]
    floor = client.post(
        f"/api/v1/projects/{project_id}/floors",
        headers=auth_headers,
        json={"name": "ชั้น 2", "level_index": 2},
    ).json()
    raw = client.post(
        f"/api/v1/projects/{project_id}/media",
        headers=auth_headers,
        json={
            "original_filename": "VID_20260212_171839_00_007.insv",
            "content_type": "video/x-insta360",
            "size_bytes": 1_900_000_000,
        },
    ).json()
    capture = client.post(
        f"/api/v1/projects/{project_id}/captures",
        headers=auth_headers,
        json={
            "source_video_id": raw["id"],
            "captured_at": "2026-02-12T10:00:00+07:00",
            "start_floor_id": floor["id"],
            "start_x": 0.29,
            "start_y": 0.64,
        },
    ).json()
    with testing_session() as db:
        stored = db.get(Capture, uuid.UUID(capture["id"]))
        assert stored is not None
        stored.status = "STITCHER_REQUIRED"
        db.commit()

    stitched = client.post(
        f"/api/v1/projects/{project_id}/media",
        headers=auth_headers,
        json={
            "original_filename": "VID_20260212_171839_00_007.mp4",
            "content_type": "video/mp4",
            "size_bytes": 1_700_000_000,
        },
    ).json()
    response = client.post(
        f"/api/v1/projects/{project_id}/captures/{capture['id']}/stitched-media",
        headers=auth_headers,
        json={"media_id": stitched["id"]},
    )
    assert response.status_code == 200
    assert response.json()["source_video_id"] == stitched["id"]
    assert response.json()["status"] == "UPLOADING_STITCHED"
    with testing_session() as db:
        raw_media = db.get(MediaFile, uuid.UUID(raw["id"]))
        assert raw_media is not None
        assert raw_media.media_kind == "RAW_VIDEO_ARCHIVE"


def test_capture_rejects_naive_timestamp_and_unsupported_media(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    project = _create_project(client, auth_headers)
    project_id = project["id"]
    floor = client.post(
        f"/api/v1/projects/{project_id}/floors",
        headers=auth_headers,
        json={"name": "ชั้น 1", "level_index": 1},
    ).json()

    raw_insv = client.post(
        f"/api/v1/projects/{project_id}/media",
        headers=auth_headers,
        json={
            "original_filename": "raw.insv",
            "content_type": "video/x-insta360",
            "size_bytes": 1024,
        },
    )
    assert raw_insv.status_code == 201
    assert raw_insv.json()["content_type"] == "video/x-insta360"

    unsupported = client.post(
        f"/api/v1/projects/{project_id}/media",
        headers=auth_headers,
        json={
            "original_filename": "raw.avi",
            "content_type": "video/x-msvideo",
            "size_bytes": 1024,
        },
    )
    assert unsupported.status_code == 422

    media = client.post(
        f"/api/v1/projects/{project_id}/media",
        headers=auth_headers,
        json={
            "original_filename": "capture.mp4",
            "content_type": "video/mp4",
            "size_bytes": 1024,
        },
    ).json()
    naive_timestamp = client.post(
        f"/api/v1/projects/{project_id}/captures",
        headers=auth_headers,
        json={
            "source_video_id": media["id"],
            "captured_at": "2025-12-28T17:10:43",
            "start_floor_id": floor["id"],
            "start_x": 0.5,
            "start_y": 0.5,
        },
    )
    assert naive_timestamp.status_code == 422


def test_resumable_multipart_upload_queues_capture_processing(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    project = _create_project(client, auth_headers)
    project_id = project["id"]
    floor = client.post(
        f"/api/v1/projects/{project_id}/floors",
        headers=auth_headers,
        json={"name": "ชั้น 1", "level_index": 1},
    ).json()
    storage_calls: dict[str, object] = {}
    monkeypatch.setattr(captures, "create_multipart_upload", lambda **_: "upload-1")
    monkeypatch.setattr(
        captures,
        "presign_upload_part",
        lambda **kwargs: f"http://storage.local/part/{kwargs['part_number']}",
    )
    monkeypatch.setattr(captures, "list_multipart_parts", lambda **_: [])
    monkeypatch.setattr(
        captures,
        "complete_multipart_upload",
        lambda **kwargs: storage_calls.update(kwargs),
    )
    monkeypatch.setattr(captures, "object_size", lambda **_: 20_000_000)
    monkeypatch.setattr(captures, "dispatch_video_job", lambda _: None)

    initiated = client.post(
        f"/api/v1/projects/{project_id}/media/multipart",
        headers=auth_headers,
        json={
            "original_filename": "capture-8k.mp4",
            "content_type": "video/mp4",
            "size_bytes": 20_000_000,
        },
    )
    assert initiated.status_code == 201
    upload = initiated.json()
    assert upload["part_count"] == 2
    assert upload["media"]["upload_status"] == "UPLOADING"
    media_id = upload["media"]["id"]

    urls = client.post(
        f"/api/v1/projects/{project_id}/media/{media_id}/multipart/parts",
        headers=auth_headers,
        json={"part_numbers": [2, 1]},
    )
    assert urls.status_code == 200
    assert [item["part_number"] for item in urls.json()["upload_urls"]] == [1, 2]

    capture = client.post(
        f"/api/v1/projects/{project_id}/captures",
        headers=auth_headers,
        json={
            "source_video_id": media_id,
            "captured_at": "2025-12-28T17:10:43+07:00",
            "captured_by_text": "Insta360 X5",
            "start_floor_id": floor["id"],
            "start_x": 0.25,
            "start_y": 0.75,
        },
    )
    assert capture.status_code == 201

    incomplete = client.post(
        f"/api/v1/projects/{project_id}/media/{media_id}/multipart/complete",
        headers=auth_headers,
        json={"parts": [{"part_number": 1, "etag": '"etag-1"'}]},
    )
    assert incomplete.status_code == 422

    completed = client.post(
        f"/api/v1/projects/{project_id}/media/{media_id}/multipart/complete",
        headers=auth_headers,
        json={
            "parts": [
                {"part_number": 2, "etag": '"etag-2"'},
                {"part_number": 1, "etag": '"etag-1"'},
            ]
        },
    )
    assert completed.status_code == 200
    result = completed.json()
    assert result["media"]["upload_status"] == "READY"
    assert result["capture_status"] == "QUEUED"
    assert storage_calls["upload_id"] == "upload-1"
    assert storage_calls["parts"] == [
        {"PartNumber": 1, "ETag": '"etag-1"'},
        {"PartNumber": 2, "ETag": '"etag-2"'},
    ]


def test_retry_is_idempotent_while_job_is_queued(
    client: TestClient,
    auth_headers: dict[str, str],
    testing_session: sessionmaker[Session],
    monkeypatch,
) -> None:
    project = _create_project(client, auth_headers)
    project_id = project["id"]
    floor = client.post(
        f"/api/v1/projects/{project_id}/floors",
        headers=auth_headers,
        json={"name": "Floor 1", "level_index": 1},
    ).json()
    media = client.post(
        f"/api/v1/projects/{project_id}/media",
        headers=auth_headers,
        json={
            "original_filename": "capture.insv",
            "content_type": "video/x-insta360",
            "size_bytes": 1024,
        },
    ).json()
    capture = client.post(
        f"/api/v1/projects/{project_id}/captures",
        headers=auth_headers,
        json={
            "source_video_id": media["id"],
            "captured_at": "2026-02-12T17:18:39+07:00",
            "start_floor_id": floor["id"],
            "start_x": 0.5,
            "start_y": 0.5,
        },
    ).json()
    with testing_session() as db:
        job = ProcessingJob(
            capture_id=uuid.UUID(capture["id"]),
            job_type="VALIDATE_VIDEO",
            status="FAILED",
            progress_percent=5,
            attempt_no=1,
            idempotency_key=f"{capture['id']}:retry-test",
            pipeline_version="test-v1",
        )
        db.add(job)
        db.commit()
        job_id = job.id

    monkeypatch.setattr(captures, "dispatch_video_job", lambda _: None)
    url = f"/api/v1/projects/{project_id}/captures/{capture['id']}/jobs/{job_id}/retry"
    first = client.post(url, headers=auth_headers)
    second = client.post(url, headers=auth_headers)

    assert first.status_code == 200
    assert first.json()["status"] == "QUEUED"
    assert first.json()["attempt_no"] == 2
    assert second.status_code == 200
    assert second.json()["status"] == "QUEUED"
    assert second.json()["attempt_no"] == 2


def test_capture_detail_returns_pose_and_reviewer_can_move_it(
    client: TestClient,
    auth_headers: dict[str, str],
    testing_session: sessionmaker[Session],
) -> None:
    project = _create_project(client, auth_headers)
    project_id = project["id"]
    floor_1 = client.post(
        f"/api/v1/projects/{project_id}/floors",
        headers=auth_headers,
        json={"name": "Floor 1", "level_index": 1},
    ).json()
    floor_2 = client.post(
        f"/api/v1/projects/{project_id}/floors",
        headers=auth_headers,
        json={"name": "Floor 2", "level_index": 2},
    ).json()
    media = client.post(
        f"/api/v1/projects/{project_id}/media",
        headers=auth_headers,
        json={
            "original_filename": "capture.mp4",
            "content_type": "video/mp4",
            "size_bytes": 1024,
        },
    ).json()
    capture = client.post(
        f"/api/v1/projects/{project_id}/captures",
        headers=auth_headers,
        json={
            "source_video_id": media["id"],
            "captured_at": "2025-12-28T17:10:43+07:00",
            "start_floor_id": floor_1["id"],
            "start_x": 0.25,
            "start_y": 0.75,
        },
    ).json()
    with testing_session() as db:
        job = ProcessingJob(
            capture_id=uuid.UUID(capture["id"]),
            job_type="LOCALIZE",
            status="SUCCEEDED",
            progress_percent=100,
            attempt_no=1,
            idempotency_key=f"{capture['id']}:test-localization",
            pipeline_version="test-v1",
        )
        db.add(job)
        db.flush()
        keyframe = Keyframe(
            capture_id=uuid.UUID(capture["id"]),
            media_file_id=uuid.UUID(media["id"]),
            frame_index=0,
            timestamp_ms=0,
            quality_status="USABLE",
        )
        db.add(keyframe)
        db.flush()
        pose = CameraPose(
            keyframe_id=keyframe.id,
            floor_id=uuid.UUID(floor_1["id"]),
            x=Decimal("0.25"),
            y=Decimal("0.75"),
            heading_deg=Decimal("15"),
            confidence=Decimal("0.42"),
            localization_run_id=job.id,
            algorithm="test-v1",
            needs_review=True,
        )
        db.add(pose)
        for timestamp_ms, x in [(0, "0.25"), (10_000, "0.30"), (20_000, "0.35")]:
            db.add(
                CapturePathPoint(
                    capture_id=uuid.UUID(capture["id"]),
                    floor_id=uuid.UUID(floor_1["id"]),
                    timestamp_ms=timestamp_ms,
                    x=Decimal(x),
                    y=Decimal("0.75"),
                    heading_deg=Decimal("15"),
                    confidence=Decimal("0.42"),
                    localization_run_id=job.id,
                    algorithm="test-v1",
                )
            )
        db.commit()
        pose_id = str(pose.id)

    moved = client.patch(
        f"/api/v1/projects/{project_id}/captures/{capture['id']}/poses/{pose_id}",
        headers=auth_headers,
        json={"floor_id": floor_2["id"], "x": 0.4, "y": 0.6, "heading_deg": 90},
    )
    assert moved.status_code == 200
    result = moved.json()
    assert result["floor_id"] == floor_2["id"]
    assert result["x"] == "0.400000"
    assert result["confidence"] == "1.00000"
    assert result["needs_review"] is False
    assert result["reviewed_at"] is not None

    detail = client.get(
        f"/api/v1/projects/{project_id}/captures/{capture['id']}",
        headers=auth_headers,
    )
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["keyframes"][0]["pose"]["id"] == pose_id
    assert len(detail_body["path_points"]) == 3
    assert detail_body["path_points"][0]["x"] == "0.400000"
    assert detail_body["path_points"][0]["y"] == "0.600000"
    assert detail_body["path_points"][0]["floor_id"] == floor_2["id"]
    assert detail_body["path_points"][0]["algorithm"].endswith("+anchor-correction")

    confirmed = client.post(
        f"/api/v1/projects/{project_id}/captures/{capture['id']}/poses/confirm",
        headers=auth_headers,
        params={"floor_id": floor_2["id"]},
    )
    assert confirmed.status_code == 200
    assert len(confirmed.json()) == 1
    assert confirmed.json()[0]["reviewed_at"] is not None
    assert confirmed.json()[0]["algorithm"].endswith("+human-confirmed")

    calibrated = client.post(
        f"/api/v1/projects/{project_id}/captures/{capture['id']}/path-calibration",
        headers=auth_headers,
        json={
            "floor_id": floor_1["id"],
            "anchors": [
                {"timestamp_ms": 10_000, "x": 0.2, "y": 0.2},
                {"timestamp_ms": 20_000, "x": 0.4, "y": 0.2},
            ],
        },
    )
    assert calibrated.status_code == 200
    calibration = calibrated.json()
    assert calibration["path_point_count"] == 2
    assert calibration["pose_count"] == 0
    assert calibration["scale"] == pytest.approx(4.0)

    calibrated_detail = client.get(
        f"/api/v1/projects/{project_id}/captures/{capture['id']}",
        headers=auth_headers,
    ).json()
    floor_1_points = [
        point for point in calibrated_detail["path_points"] if point["floor_id"] == floor_1["id"]
    ]
    assert [point["x"] for point in floor_1_points] == ["0.200000", "0.400000"]
    assert all(point["y"] == "0.200000" for point in floor_1_points)


def test_rigid_path_transform_preserves_stella_track_shape(
    client: TestClient,
    auth_headers: dict[str, str],
    testing_session: sessionmaker[Session],
) -> None:
    project = _create_project(client, auth_headers)
    project_id = project["id"]
    floor = client.post(
        f"/api/v1/projects/{project_id}/floors",
        headers=auth_headers,
        json={"name": "Floor 1", "level_index": 1},
    ).json()
    media = client.post(
        f"/api/v1/projects/{project_id}/media",
        headers=auth_headers,
        json={
            "original_filename": "stella-track.mp4",
            "content_type": "video/mp4",
            "size_bytes": 1024,
        },
    ).json()
    capture = client.post(
        f"/api/v1/projects/{project_id}/captures",
        headers=auth_headers,
        json={
            "source_video_id": media["id"],
            "captured_at": "2025-12-23T10:00:00+07:00",
            "start_floor_id": floor["id"],
            "start_x": 0.5,
            "start_y": 0.5,
        },
    ).json()

    with testing_session() as db:
        job = ProcessingJob(
            capture_id=uuid.UUID(capture["id"]),
            job_type="LOCALIZE",
            status="SUCCEEDED",
            progress_percent=100,
            attempt_no=1,
            idempotency_key=f"{capture['id']}:stella-rigid-test",
            pipeline_version="stella-vslam-test",
        )
        db.add(job)
        db.flush()
        for index, (visual_x, visual_y, heading) in enumerate(
            [("0", "0", "0"), ("1", "0", "90"), ("1", "1", "180")]
        ):
            timestamp_ms = index * 1_000
            keyframe = Keyframe(
                capture_id=uuid.UUID(capture["id"]),
                media_file_id=uuid.UUID(media["id"]),
                frame_index=index,
                timestamp_ms=timestamp_ms,
                quality_status="USABLE",
                is_warp_point=True,
            )
            db.add(keyframe)
            db.flush()
            db.add(
                CameraPose(
                    keyframe_id=keyframe.id,
                    floor_id=uuid.UUID(floor["id"]),
                    x=Decimal("0.5"),
                    y=Decimal("0.5"),
                    heading_deg=Decimal("0"),
                    visual_x=Decimal(visual_x),
                    visual_y=Decimal(visual_y),
                    visual_heading_deg=Decimal(heading),
                    confidence=Decimal("0.9"),
                    localization_run_id=job.id,
                    algorithm="stella-vslam-test:unaligned-start-anchor",
                    needs_review=True,
                )
            )
            db.add(
                CapturePathPoint(
                    capture_id=uuid.UUID(capture["id"]),
                    floor_id=uuid.UUID(floor["id"]),
                    timestamp_ms=timestamp_ms,
                    x=Decimal("0.5"),
                    y=Decimal("0.5"),
                    heading_deg=Decimal("0"),
                    confidence=Decimal("0.9"),
                    localization_run_id=job.id,
                    algorithm="stella-vslam-test:unaligned-start-anchor",
                )
            )
        db.commit()

    url = f"/api/v1/projects/{project_id}/captures/{capture['id']}/path-transform"
    invalid = client.post(
        url,
        headers=auth_headers,
        json={"floor_id": floor["id"], "scale": 1, "rotation_deg": 0},
    )
    assert invalid.status_code == 422

    transformed = client.post(
        url,
        headers=auth_headers,
        json={
            "floor_id": floor["id"],
            "scale_x": 0.1,
            "scale_y": 0.2,
            "rotation_deg": 90,
            "mirror": True,
            "offset_x": 0.1,
            "offset_y": -0.1,
        },
    )
    assert transformed.status_code == 200
    assert transformed.json()["pose_count"] == 3
    assert transformed.json()["path_point_count"] == 3
    assert transformed.json()["mirror"] is True
    assert transformed.json()["offset_x"] == pytest.approx(0.1)
    assert transformed.json()["scale_x"] == pytest.approx(0.1)
    assert transformed.json()["scale_y"] == pytest.approx(0.2)

    detail = client.get(
        f"/api/v1/projects/{project_id}/captures/{capture['id']}",
        headers=auth_headers,
    ).json()
    poses = [frame["pose"] for frame in detail["keyframes"]]
    assert [(pose["visual_x"], pose["visual_y"]) for pose in poses] == [
        ("0.000000", "0.000000"),
        ("1.000000", "0.000000"),
        ("1.000000", "1.000000"),
    ]
    assert [(pose["x"], pose["y"]) for pose in poses] == [
        ("0.600000", "0.400000"),
        ("0.600000", "0.200000"),
        ("0.500000", "0.200000"),
    ]
    assert all(pose["needs_review"] is False for pose in poses)
    assert all(pose["algorithm"].endswith("+rigid-plan-transform") for pose in poses)
    assert detail["capture"]["start_x"] == "0.600000"
    assert detail["capture"]["start_y"] == "0.400000"

    # Independent plan-axis scales keep the route connected and preserve the
    # right angle while allowing different horizontal and vertical lengths.
    plan_points = [(float(pose["x"]), float(pose["y"])) for pose in poses]
    first_segment = (
        plan_points[1][0] - plan_points[0][0],
        plan_points[1][1] - plan_points[0][1],
    )
    second_segment = (
        plan_points[2][0] - plan_points[1][0],
        plan_points[2][1] - plan_points[1][1],
    )
    dot_product = first_segment[0] * second_segment[0] + first_segment[1] * second_segment[1]
    assert dot_product == pytest.approx(0)
    assert first_segment[0] ** 2 + first_segment[1] ** 2 == pytest.approx(0.04)
    assert second_segment[0] ** 2 + second_segment[1] ** 2 == pytest.approx(0.01)

    corrected_start = client.patch(
        f"/api/v1/projects/{project_id}/captures/{capture['id']}/start-point",
        headers=auth_headers,
        json={"floor_id": floor["id"], "x": 0.55, "y": 0.45},
    )
    assert corrected_start.status_code == 200
    assert corrected_start.json()["pose_count"] == 3
    assert corrected_start.json()["path_point_count"] == 3

    corrected_detail = client.get(
        f"/api/v1/projects/{project_id}/captures/{capture['id']}",
        headers=auth_headers,
    ).json()
    corrected_poses = [frame["pose"] for frame in corrected_detail["keyframes"]]
    assert [(pose["x"], pose["y"]) for pose in corrected_poses] == [
        ("0.550000", "0.450000"),
        ("0.550000", "0.250000"),
        ("0.450000", "0.250000"),
    ]
    assert corrected_detail["capture"]["start_x"] == "0.550000"
    assert corrected_detail["capture"]["start_y"] == "0.450000"
    assert all(pose["algorithm"].endswith("+human-start") for pose in corrected_poses)

    control_fit = client.post(
        f"/api/v1/projects/{project_id}/captures/{capture['id']}/path-control-points/fit",
        headers=auth_headers,
        json={
            "floor_id": floor["id"],
            "control_points": [
                {"keyframe_id": detail["keyframes"][0]["id"], "x": 0.2, "y": 0.3},
                {"keyframe_id": detail["keyframes"][1]["id"], "x": 0.4, "y": 0.3},
                {"keyframe_id": detail["keyframes"][2]["id"], "x": 0.4, "y": 0.5},
            ],
        },
    )
    assert control_fit.status_code == 200
    fit_body = control_fit.json()
    assert fit_body["scale"] == pytest.approx(0.2)
    assert fit_body["mirror"] is False
    assert fit_body["rmse_normalized"] == pytest.approx(0)
    assert len(fit_body["control_points"]) == 3

    fitted_detail = client.get(
        f"/api/v1/projects/{project_id}/captures/{capture['id']}",
        headers=auth_headers,
    ).json()
    assert len(fitted_detail["control_points"]) == 3
    assert [(frame["pose"]["x"], frame["pose"]["y"]) for frame in fitted_detail["keyframes"]] == [
        ("0.200000", "0.300000"),
        ("0.400000", "0.300000"),
        ("0.400000", "0.500000"),
    ]


def test_path_evaluation_uses_twenty_held_out_snapshot_points(
    client: TestClient,
    auth_headers: dict[str, str],
    testing_session: sessionmaker[Session],
) -> None:
    project = _create_project(client, auth_headers)
    project_id = project["id"]
    floor = client.post(
        f"/api/v1/projects/{project_id}/floors",
        headers=auth_headers,
        json={"name": "ชั้น 1", "level_index": 1},
    ).json()
    media = client.post(
        f"/api/v1/projects/{project_id}/media",
        headers=auth_headers,
        json={
            "original_filename": "evaluation.mp4",
            "content_type": "video/mp4",
            "size_bytes": 1024,
        },
    ).json()
    capture = client.post(
        f"/api/v1/projects/{project_id}/captures",
        headers=auth_headers,
        json={
            "source_video_id": media["id"],
            "captured_at": "2025-12-23T10:00:00+07:00",
            "start_floor_id": floor["id"],
            "start_x": 0.1,
            "start_y": 0.2,
        },
    ).json()

    keyframe_ids: list[uuid.UUID] = []
    with testing_session() as db:
        job = ProcessingJob(
            capture_id=uuid.UUID(capture["id"]),
            job_type="LOCALIZE",
            status="SUCCEEDED",
            progress_percent=100,
            attempt_no=1,
            idempotency_key=f"{capture['id']}:evaluation-test",
            pipeline_version="stella-vslam-test",
        )
        db.add(job)
        db.flush()
        for index in range(20):
            x = Decimal("0.10") + Decimal(index) * Decimal("0.02")
            keyframe = Keyframe(
                capture_id=uuid.UUID(capture["id"]),
                media_file_id=uuid.UUID(media["id"]),
                frame_index=index,
                timestamp_ms=index * 1_000,
                quality_status="USABLE",
                is_warp_point=True,
            )
            db.add(keyframe)
            db.flush()
            keyframe_ids.append(keyframe.id)
            db.add(
                CameraPose(
                    keyframe_id=keyframe.id,
                    floor_id=uuid.UUID(floor["id"]),
                    x=x,
                    y=Decimal("0.20"),
                    heading_deg=Decimal("0"),
                    visual_x=Decimal(index),
                    visual_y=Decimal("0"),
                    visual_heading_deg=Decimal("0"),
                    confidence=Decimal("0.9"),
                    localization_run_id=job.id,
                    algorithm="stella-vslam-test+rigid-plan-transform",
                    needs_review=False,
                )
            )
        db.commit()

    evaluation_points = []
    for index, keyframe_id in enumerate(keyframe_ids):
        predicted_x = 0.10 + index * 0.02
        evaluation_points.append(
            {
                "keyframe_id": str(keyframe_id),
                "target_x": predicted_x + (0 if index < 16 else 0.04),
                "target_y": 0.20,
            }
        )
    response = client.put(
        f"/api/v1/projects/{project_id}/captures/{capture['id']}/path-evaluation-points",
        headers=auth_headers,
        json={
            "floor_id": floor["id"],
            "tolerance_normalized": 0.03,
            "evaluation_points": evaluation_points,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["point_count"] == 20
    assert body["summary"]["is_ready"] is True
    assert float(body["summary"]["accuracy_percent"]) == pytest.approx(80)
    assert body["summary"]["within_tolerance_count"] == 16

    detail = client.get(
        f"/api/v1/projects/{project_id}/captures/{capture['id']}",
        headers=auth_headers,
    ).json()
    assert len(detail["evaluation_points"]) == 20
    assert float(detail["evaluation_summary"]["accuracy_percent"]) == pytest.approx(80)


def test_holdout_capture_is_identified_and_rejects_path_tuning(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    project = _create_project(client, auth_headers)
    project_id = project["id"]
    floor = client.post(
        f"/api/v1/projects/{project_id}/floors",
        headers=auth_headers,
        json={"name": "Floor 1", "level_index": 1},
    ).json()
    media = client.post(
        f"/api/v1/projects/{project_id}/media",
        headers=auth_headers,
        json={
            "original_filename": "holdout.mp4",
            "content_type": "video/mp4",
            "size_bytes": 1024,
        },
    ).json()
    capture = client.post(
        f"/api/v1/projects/{project_id}/captures",
        headers=auth_headers,
        json={
            "source_video_id": media["id"],
            "captured_at": "2026-01-12T10:00:00+07:00",
            "start_floor_id": floor["id"],
            "start_x": 0.5,
            "start_y": 0.5,
            "dataset_split": "HOLDOUT_TEST",
        },
    )
    assert capture.status_code == 201
    assert capture.json()["dataset_split"] == "HOLDOUT_TEST"

    response = client.post(
        f"/api/v1/projects/{project_id}/captures/{capture.json()['id']}/path-transform",
        headers=auth_headers,
        json={
            "floor_id": floor["id"],
            "scale_x": 0.1,
            "scale_y": 0.1,
            "rotation_deg": 0,
        },
    )
    assert response.status_code == 409
    assert "Holdout" in response.json()["detail"]

    replacement_media = client.post(
        f"/api/v1/projects/{project_id}/media",
        headers=auth_headers,
        json={
            "original_filename": "holdout-replacement.mp4",
            "content_type": "video/mp4",
            "size_bytes": 2048,
        },
    ).json()
    replacement = client.post(
        f"/api/v1/projects/{project_id}/captures",
        headers=auth_headers,
        json={
            "source_video_id": replacement_media["id"],
            "captured_at": "2026-01-12T15:00:00+07:00",
            "start_floor_id": floor["id"],
            "start_x": 0.4,
            "start_y": 0.4,
            "dataset_split": "DEVELOPMENT",
        },
    )
    assert replacement.status_code == 201
    assert replacement.json()["dataset_split"] == "HOLDOUT_TEST"


def test_sub_admin_can_correct_beam_length_but_cannot_replace_codes(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    project = _create_project(client, auth_headers)
    project_id = project["id"]
    floor = client.post(
        f"/api/v1/projects/{project_id}/floors",
        headers=auth_headers,
        json={"name": "ชั้น 1", "level_index": 1},
    ).json()
    created = client.put(
        f"/api/v1/projects/{project_id}/floors/{floor['id']}/beam-segments",
        headers=auth_headers,
        json={
            "sheet_name": "ST-03",
            "segments": [
                {
                    "code": "CB4",
                    "beam_type": "CB4",
                    "start_x": 0.2,
                    "start_y": 0.4,
                    "end_x": 0.3,
                    "end_y": 0.4,
                    "length_m": 1.525,
                },
                {
                    "code": "B2",
                    "beam_type": "B2",
                    "start_x": 0.3,
                    "start_y": 0.4,
                    "end_x": 0.4,
                    "end_y": 0.4,
                    "length_m": 3.75,
                },
            ],
        },
    ).json()

    sub_admin = client.post(
        "/api/v1/auth/register",
        json={
            "email": "sub-admin@example.com",
            "display_name": "Sub Admin",
            "password": "sub-admin-password-123",
        },
    ).json()
    added = client.post(
        f"/api/v1/projects/{project_id}/members",
        headers=auth_headers,
        json={"email": "sub-admin@example.com", "role": "sub_admin"},
    )
    assert added.status_code == 201
    sub_admin_headers = {"Authorization": f"Bearer {sub_admin['access_token']}"}

    cb4 = next(segment for segment in created if segment["code"] == "CB4")
    b2 = next(segment for segment in created if segment["code"] == "B2")
    corrected = client.patch(
        f"/api/v1/projects/{project_id}/floors/{floor['id']}/beam-segments/{cb4['id']}",
        headers=sub_admin_headers,
        json={"length_m": 4.125, "code": "MUST-NOT-CHANGE"},
    )

    assert corrected.status_code == 200
    assert float(corrected.json()["length_m"]) == pytest.approx(4.125)
    assert corrected.json()["source"] == "MANUAL"
    assert corrected.json()["code"] == "CB4"
    assert float(b2["length_m"]) == pytest.approx(3.75)

    forbidden_replace = client.put(
        f"/api/v1/projects/{project_id}/floors/{floor['id']}/beam-segments",
        headers=sub_admin_headers,
        json={
            "sheet_name": "ST-03",
            "segments": [{
                "code": "HACKED",
                "beam_type": "B2",
                "start_x": 0.1,
                "start_y": 0.1,
                "end_x": 0.2,
                "end_y": 0.2,
                "length_m": 9,
            }],
        },
    )
    # Role checks intentionally hide restricted project operations as not found.
    assert forbidden_replace.status_code == 404


def test_sub_admin_can_correct_slab_area_without_changing_code_or_geometry(
    client: TestClient,
    auth_headers: dict[str, str],
    testing_session: sessionmaker[Session],
) -> None:
    project = _create_project(client, auth_headers)
    project_id = project["id"]
    floor = client.post(
        f"/api/v1/projects/{project_id}/floors",
        headers=auth_headers,
        json={"name": "ชั้น 1", "level_index": 1},
    ).json()
    slab_id = uuid.uuid4()
    original_footprint = [[0.1, 0.2], [0.4, 0.2], [0.4, 0.5], [0.1, 0.5]]
    with testing_session() as db:
        db.add(
            StructuralElement(
                id=slab_id,
                project_id=uuid.UUID(project_id),
                floor_id=uuid.UUID(floor["id"]),
                sheet_id=None,
                ifc_global_id=f"ifc-{slab_id.hex[:22]}",
                ifc_type="IfcSlab",
                ifc_storey="ชั้น 1",
                element_kind="SLAB",
                code="S1",
                name="Slab 1",
                geometry_json={"footprint": original_footprint, "area_m2": 12.5},
                source="IFC_PLAN_ALIGNED",
            )
        )
        db.commit()

    sub_admin = client.post(
        "/api/v1/auth/register",
        json={
            "email": "sub-admin-area@example.com",
            "display_name": "Sub Admin Area",
            "password": "sub-admin-password-123",
        },
    ).json()
    added = client.post(
        f"/api/v1/projects/{project_id}/members",
        headers=auth_headers,
        json={"email": "sub-admin-area@example.com", "role": "sub_admin"},
    )
    assert added.status_code == 201
    sub_admin_headers = {"Authorization": f"Bearer {sub_admin['access_token']}"}

    corrected = client.patch(
        f"/api/v1/projects/{project_id}/floors/{floor['id']}/structural-elements/{slab_id}/area",
        headers=sub_admin_headers,
        json={"area_m2": 18.75, "code": "MUST-NOT-CHANGE", "geometry_json": {}},
    )

    assert corrected.status_code == 200
    payload = corrected.json()
    assert payload["code"] == "S1"
    assert payload["geometry_json"]["footprint"] == original_footprint
    assert payload["geometry_json"]["area_m2"] == pytest.approx(18.75)
    assert payload["source"] == "MANUAL"


def test_work_progress_carries_forward_to_later_capture_without_leaking_backward(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    project = _create_project(client, auth_headers)
    project_id = project["id"]
    floor = client.post(
        f"/api/v1/projects/{project_id}/floors",
        headers=auth_headers,
        json={"name": "ชั้น 1", "level_index": 1},
    ).json()

    def create_capture(filename: str, captured_at: str) -> dict:
        media = client.post(
            f"/api/v1/projects/{project_id}/media",
            headers=auth_headers,
            json={
                "original_filename": filename,
                "content_type": "video/mp4",
                "size_bytes": 1024,
            },
        ).json()
        return client.post(
            f"/api/v1/projects/{project_id}/captures",
            headers=auth_headers,
            json={
                "source_video_id": media["id"],
                "captured_at": captured_at,
                "start_floor_id": floor["id"],
                "start_x": 0.2,
                "start_y": 0.4,
            },
        ).json()

    earlier = create_capture("earlier.mp4", "2026-01-01T10:00:00+07:00")
    later = create_capture("later.mp4", "2026-01-02T10:00:00+07:00")
    initial = client.get(
        f"/api/v1/projects/{project_id}/captures/{earlier['id']}/work-progress",
        headers=auth_headers,
        params={"floor_id": floor["id"]},
    ).json()
    item = initial["items"][0]
    saved = client.put(
        f"/api/v1/projects/{project_id}/captures/{later['id']}/work-progress",
        headers=auth_headers,
        json={
            "floor_id": floor["id"],
            "entries": [{"work_item_id": item["work_item_id"], "progress_percent": 35}],
        },
    )
    assert saved.status_code == 200

    later_reloaded = client.get(
        f"/api/v1/projects/{project_id}/captures/{later['id']}/work-progress",
        headers=auth_headers,
        params={"floor_id": floor["id"]},
    ).json()
    earlier_reloaded = client.get(
        f"/api/v1/projects/{project_id}/captures/{earlier['id']}/work-progress",
        headers=auth_headers,
        params={"floor_id": floor["id"]},
    ).json()
    assert next(
        row for row in later_reloaded["items"] if row["work_item_id"] == item["work_item_id"]
    )["progress_percent"] == "35.000"
    assert next(
        row for row in earlier_reloaded["items"] if row["work_item_id"] == item["work_item_id"]
    )["progress_percent"] is None


def test_replacing_beam_plan_cannot_hide_segments_with_progress_history(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    project = _create_project(client, auth_headers)
    project_id = project["id"]
    floor = client.post(
        f"/api/v1/projects/{project_id}/floors",
        headers=auth_headers,
        json={"name": "ชั้น 1", "level_index": 1},
    ).json()
    segment = client.put(
        f"/api/v1/projects/{project_id}/floors/{floor['id']}/beam-segments",
        headers=auth_headers,
        json={
            "sheet_name": "ST-03",
            "segments": [{
                "code": "CB4",
                "beam_type": "CB4",
                "start_x": 0.2,
                "start_y": 0.4,
                "end_x": 0.3,
                "end_y": 0.4,
                "length_m": 1.7,
            }],
        },
    ).json()[0]
    media = client.post(
        f"/api/v1/projects/{project_id}/media",
        headers=auth_headers,
        json={
            "original_filename": "progress.mp4",
            "content_type": "video/mp4",
            "size_bytes": 1024,
        },
    ).json()
    capture = client.post(
        f"/api/v1/projects/{project_id}/captures",
        headers=auth_headers,
        json={
            "source_video_id": media["id"],
            "captured_at": "2026-01-01T10:00:00+07:00",
            "start_floor_id": floor["id"],
            "start_x": 0.2,
            "start_y": 0.4,
        },
    ).json()
    saved = client.put(
        f"/api/v1/projects/{project_id}/captures/{capture['id']}/beam-progress",
        headers=auth_headers,
        json={
            "floor_id": floor["id"],
            "entries": [{
                "beam_segment_id": segment["id"],
                "stage_ranges": {"SETTING_OUT": [{"start_m": 0, "end_m": 1.7}]},
            }],
        },
    )
    assert saved.status_code == 200

    replacement = client.put(
        f"/api/v1/projects/{project_id}/floors/{floor['id']}/beam-segments",
        headers=auth_headers,
        json={
            "sheet_name": "ST-03",
            "segments": [{
                "code": "NEW-CODE",
                "beam_type": "CB4",
                "start_x": 0.2,
                "start_y": 0.4,
                "end_x": 0.3,
                "end_y": 0.4,
                "length_m": 1.7,
            }],
        },
    )
    assert replacement.status_code == 409
    assert "CB4" in replacement.json()["detail"]

    still_visible = client.get(
        f"/api/v1/projects/{project_id}/captures/{capture['id']}/beam-progress",
        headers=auth_headers,
        params={"floor_id": floor["id"]},
    ).json()
    assert still_visible["labeled_count"] == 1
    assert still_visible["items"][0]["code"] == "CB4"


def test_beam_progress_is_stored_per_capture_and_keeps_latest_value(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    project = _create_project(client, auth_headers)
    project_id = project["id"]
    floor = client.post(
        f"/api/v1/projects/{project_id}/floors",
        headers=auth_headers,
        json={"name": "ชั้น 1", "level_index": 1},
    ).json()
    media = client.post(
        f"/api/v1/projects/{project_id}/media",
        headers=auth_headers,
        json={
            "original_filename": "beam-progress.mp4",
            "content_type": "video/mp4",
            "size_bytes": 1024,
        },
    ).json()
    capture = client.post(
        f"/api/v1/projects/{project_id}/captures",
        headers=auth_headers,
        json={
            "source_video_id": media["id"],
            "captured_at": "2025-12-23T10:00:00+07:00",
            "start_floor_id": floor["id"],
            "start_x": 0.2,
            "start_y": 0.4,
        },
    ).json()
    segments_response = client.put(
        f"/api/v1/projects/{project_id}/floors/{floor['id']}/beam-segments",
        headers=auth_headers,
        json={
            "sheet_name": "ST-03",
            "segments": [
                {
                    "code": "F1-B-1-2",
                    "beam_type": "B3",
                    "start_x": 0.2,
                    "start_y": 0.4,
                    "end_x": 0.3,
                    "end_y": 0.4,
                    "length_m": 3.75,
                },
                {
                    "code": "F1-B-2-3",
                    "beam_type": "B3",
                    "start_x": 0.3,
                    "start_y": 0.4,
                    "end_x": 0.4,
                    "end_y": 0.4,
                    "length_m": 3.75,
                },
            ],
        },
    )
    assert segments_response.status_code == 200
    segments = segments_response.json()
    progress_url = f"/api/v1/projects/{project_id}/captures/{capture['id']}/beam-progress"
    first_save = client.put(
        progress_url,
        headers=auth_headers,
        json={
            "floor_id": floor["id"],
            "entries": [
                {"beam_segment_id": segments[0]["id"], "progress_percent": 25},
                {"beam_segment_id": segments[1]["id"], "progress_percent": 75},
            ],
        },
    )
    assert first_save.status_code == 200
    assert float(first_save.json()["weighted_progress_percent"]) == pytest.approx(50)

    stage_save = client.put(
        progress_url,
        headers=auth_headers,
        json={
            "floor_id": floor["id"],
            "entries": [
                {
                    "beam_segment_id": segments[0]["id"],
                    "completed_stages": ["SETTING_OUT", "REBAR", "FORMWORK"],
                },
            ],
        },
    )
    assert stage_save.status_code == 200
    stage_item = next(
        item for item in stage_save.json()["items"]
        if item["beam_segment_id"] == segments[0]["id"]
    )
    assert float(stage_item["progress_percent"]) == pytest.approx(60)
    assert stage_item["completed_stages"] == ["SETTING_OUT", "REBAR", "FORMWORK"]
    assert float(stage_save.json()["total_length_m"]) == pytest.approx(7.5)
    assert float(stage_save.json()["weighted_progress_percent"]) == pytest.approx(67.5)

    range_save = client.put(
        progress_url,
        headers=auth_headers,
        json={
            "floor_id": floor["id"],
            "entries": [
                {
                    "beam_segment_id": segments[0]["id"],
                    "stage_ranges": {
                        "SETTING_OUT": [
                            {"start_m": 0, "end_m": 2},
                            {"start_m": 1.5, "end_m": 3},
                        ],
                        "REBAR": [{"start_m": 0, "end_m": 3.75}],
                    },
                },
            ],
        },
    )
    assert range_save.status_code == 200
    range_payload = range_save.json()
    range_item = next(
        item for item in range_payload["items"]
        if item["beam_segment_id"] == segments[0]["id"]
    )
    assert float(range_item["progress_percent"]) == pytest.approx(36)
    assert len(range_item["stage_ranges"]["SETTING_OUT"]) == 1
    assert float(range_item["stage_ranges"]["SETTING_OUT"][0]["start_m"]) == 0
    assert float(range_item["stage_ranges"]["SETTING_OUT"][0]["end_m"]) == 3
    assert float(range_item["stage_ranges"]["REBAR"][0]["start_m"]) == 0
    assert float(range_item["stage_ranges"]["REBAR"][0]["end_m"]) == 3.75
    summaries = {
        summary["stage"]: summary for summary in range_payload["stage_summaries"]
    }
    # The untouched second beam keeps its previous 75% legacy value, which is
    # interpreted as three complete stages for backward compatibility.
    assert float(summaries["SETTING_OUT"]["completed_length_m"]) == pytest.approx(6.75)
    assert float(summaries["SETTING_OUT"]["progress_percent"]) == pytest.approx(90)
    assert float(summaries["REBAR"]["completed_length_m"]) == pytest.approx(7.5)
    assert float(range_payload["weighted_progress_percent"]) == pytest.approx(55.5)

    second_save = client.put(
        progress_url,
        headers=auth_headers,
        json={
            "floor_id": floor["id"],
            "entries": [
                {"beam_segment_id": segments[0]["id"], "progress_percent": 100},
            ],
        },
    )
    assert second_save.status_code == 200
    latest = client.get(
        progress_url,
        headers=auth_headers,
        params={"floor_id": floor["id"]},
    ).json()
    values = {item["code"]: float(item["progress_percent"]) for item in latest["items"]}
    assert values == {"F1-B-1-2": 100, "F1-B-2-3": 75}


def test_upper_floor_beam_stages_carry_forward_across_capture_dates(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    project = _create_project(client, auth_headers)
    project_id = project["id"]
    floor = client.post(
        f"/api/v1/projects/{project_id}/floors",
        headers=auth_headers,
        json={"name": "ชั้น 2", "level_index": 2},
    ).json()

    captures = []
    for day in (25, 29):
        media = client.post(
            f"/api/v1/projects/{project_id}/media",
            headers=auth_headers,
            json={
                "original_filename": f"beam-progress-2026-01-{day}.mp4",
                "content_type": "video/mp4",
                "size_bytes": 1024,
            },
        ).json()
        captures.append(client.post(
            f"/api/v1/projects/{project_id}/captures",
            headers=auth_headers,
            json={
                "source_video_id": media["id"],
                "captured_at": f"2026-01-{day:02d}T10:00:00+07:00",
                "start_floor_id": floor["id"],
                "start_x": 0.2,
                "start_y": 0.4,
            },
        ).json())

    segment = client.put(
        f"/api/v1/projects/{project_id}/floors/{floor['id']}/beam-segments",
        headers=auth_headers,
        json={
            "sheet_name": "ST-04",
            "segments": [{
                "code": "L2-B-1",
                "beam_type": "B1",
                "start_x": 0.2,
                "start_y": 0.4,
                "end_x": 0.4,
                "end_y": 0.4,
                "length_m": 3.75,
            }],
        },
    ).json()[0]

    def save(capture_id: str, stages: list[str]):
        return client.put(
            f"/api/v1/projects/{project_id}/captures/{capture_id}/beam-progress",
            headers=auth_headers,
            json={
                "floor_id": floor["id"],
                "entries": [{
                    "beam_segment_id": segment["id"],
                    "completed_stages": stages,
                }],
            },
        )

    assert save(captures[0]["id"], ["SHORING"]).status_code == 200
    later = save(captures[1]["id"], ["REBAR"])
    assert later.status_code == 200
    item = later.json()["items"][0]
    assert item["completed_stages"] == ["SHORING", "REBAR"]
    assert float(item["progress_percent"]) == pytest.approx(40)

    carried = client.get(
        f"/api/v1/projects/{project_id}/captures/{captures[1]['id']}/beam-progress",
        headers=auth_headers,
        params={"floor_id": floor["id"]},
    )
    assert carried.status_code == 200
    assert carried.json()["items"][0]["completed_stages"] == ["SHORING", "REBAR"]
