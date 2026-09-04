from pathlib import Path

import cv2
import numpy as np
import pytest

from progress_api.services.learned_relocalization import _project_centre_to_plan_route
from progress_api.services.localization import (
    EstimatedPathPoint,
    EstimatedPose,
    PlanAlignment,
    _alignment_is_auto_accepted,
    _estimate_prior_affine,
    _estimate_prior_similarity,
    _fit_to_grid_six_road_edge,
    _fit_to_plan,
    _motion_between,
    _poses_at_timestamps,
    _select_unique_visual_matches,
    estimate_keyframe_poses,
    interpolate_piecewise_offsets,
)
from progress_api.services.sfm_localization import SfMPathSample


def _alignment(source: str, confidence: float) -> PlanAlignment:
    return PlanAlignment(
        points=[],
        scale=1.0,
        rotation_deg=0.0,
        mirror=False,
        confidence=confidence,
        source=source,
    )


def test_only_verified_absolute_alignment_can_auto_publish() -> None:
    assert _alignment_is_auto_accepted(
        _alignment("persistent-map-v1:floor-1", 0.80)
    )
    assert not _alignment_is_auto_accepted(
        _alignment("previous-disk-lightglue-v1:capture-id", 0.99)
    )
    assert not _alignment_is_auto_accepted(
        _alignment("previous-orb-v1:capture-id", 0.99)
    )
    assert not _alignment_is_auto_accepted(
        _alignment("grid6-road-edge-fit-v1", 1.0)
    )


def test_3d_camera_projects_onto_corresponding_piecewise_plan_segment() -> None:
    reference_3d = np.asarray(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0]],
        dtype=np.float64,
    )
    audited_plan = np.asarray(
        [[0.2, 0.3], [0.7, 0.3], [0.7, 0.8]], dtype=np.float64
    )

    projected = _project_centre_to_plan_route(
        np.asarray([1.05, 0.4, 0.0], dtype=np.float64),
        reference_3d,
        audited_plan,
    )

    assert projected == pytest.approx([0.7, 0.5])


def test_plan_fit_keeps_path_inside_normalized_floor() -> None:
    relative = [(index * 0.04, index * 0.012, index * 3.0) for index in range(18)]

    fitted, scale = _fit_to_plan(relative, start_x=0.84, start_y=0.78)

    assert fitted[0][0] == 0.84
    assert fitted[0][1] == 0.78
    assert 0.25 <= scale <= 1.0
    assert all(0 <= x <= 1 and 0 <= y <= 1 for x, y, _ in fitted)
    assert len({(round(x, 4), round(y, 4)) for x, y, _ in fitted}) > 5


def test_grid_six_road_edge_fit_uses_vertical_initial_direction() -> None:
    relative = [(index * 0.02, index * 0.01, 0.0) for index in range(20)]

    fitted, scale, _rotation = _fit_to_grid_six_road_edge(
        relative,
        start_x=0.68,
        start_y=0.70,
    )

    initial_dx = fitted[5][0] - fitted[0][0]
    initial_dy = fitted[5][1] - fitted[0][1]
    assert scale > 0
    assert abs(initial_dy) > abs(initial_dx) * 10
    assert initial_dy < 0
    assert all(0.18 <= x <= 0.70 and 0.22 <= y <= 0.76 for x, y, _ in fitted)


def test_orb_motion_uses_visual_displacement() -> None:
    rng = np.random.default_rng(20260821)
    previous = rng.integers(0, 255, size=(480, 960), dtype=np.uint8)
    transform = np.float32([[1, 0, 14], [0, 1, 0]])
    current = cv2.warpAffine(previous, transform, (960, 480))

    motion = _motion_between(previous, current)

    assert motion.step > 0.002
    assert motion.yaw_delta_deg < 0
    assert motion.confidence > 0.5


def test_keyframe_pose_timestamps_map_to_tracking_frames(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "progress_api.services.localization.recover_visual_path",
        lambda _source, end_timestamp_ms: [
            SfMPathSample(
                timestamp_ms=index * 1000,
                x=index * 0.03,
                y=0,
                heading_deg=0,
                confidence=1.0 if index == 0 else 0.8,
            )
            for index in range((end_timestamp_ms // 1000) + 1)
        ],
    )

    poses = estimate_keyframe_poses(
        tmp_path / "source.mp4",
        keyframe_timestamps_ms=[0, 2000, 4000],
        start_x=0.5,
        start_y=0.5,
    )

    assert len(poses) == 3
    assert poses[0].x == 0.5
    assert (poses[-1].x, poses[-1].y) != (poses[0].x, poses[0].y)
    assert poses[0].confidence == 1.0


def test_previous_capture_similarity_keeps_selected_start_fixed() -> None:
    result = _estimate_prior_similarity(
        [
            ((1.0, 0.0), (0.50, 0.40)),
            ((1.0, 1.0), (0.40, 0.40)),
            ((0.0, 1.0), (0.40, 0.30)),
        ],
        start_x=0.50,
        start_y=0.30,
    )

    assert result is not None
    scale, rotation_deg, mirror, confidence, inliers = result
    assert scale == pytest.approx(0.1, abs=0.01)
    assert rotation_deg == pytest.approx(90, abs=2)
    assert mirror is False
    assert confidence >= 0.70
    assert inliers == 3


def test_previous_capture_similarity_can_recover_reflected_stella_axis() -> None:
    result = _estimate_prior_similarity(
        [
            ((1.0, 0.0), (0.60, 0.50)),
            ((1.0, 1.0), (0.60, 0.40)),
            ((0.0, 1.0), (0.50, 0.40)),
        ],
        start_x=0.50,
        start_y=0.50,
    )

    assert result is not None
    scale, rotation_deg, mirror, confidence, inliers = result
    assert scale == pytest.approx(0.1, abs=0.01)
    assert rotation_deg == pytest.approx(0, abs=2)
    assert mirror is True
    assert confidence >= 0.70
    assert inliers == 3


def test_previous_capture_affine_recovers_independent_axis_scales() -> None:
    result = _estimate_prior_affine(
        [
            ((1.0, 0.0), (0.70, 0.50)),
            ((0.0, 1.0), (0.50, 0.40)),
            ((1.0, 1.0), (0.70, 0.40)),
            ((2.0, 1.0), (0.90, 0.40)),
        ],
        start_x=0.50,
        start_y=0.50,
    )

    assert result is not None
    matrix, confidence, inlier_indices = result
    assert matrix[0, 0] == pytest.approx(0.2, abs=0.01)
    assert matrix[1, 1] == pytest.approx(-0.1, abs=0.01)
    assert abs(matrix[0, 1]) < 0.01
    assert abs(matrix[1, 0]) < 0.01
    assert confidence >= 0.70
    assert len(inlier_indices) == 4


def test_piecewise_offsets_pin_start_and_interpolate_drift() -> None:
    offsets = interpolate_piecewise_offsets(
        [0, 1000, 2000, 3000, 4000],
        [(2000, 0.04, -0.02), (4000, 0.08, -0.04)],
    )

    assert offsets[0] == pytest.approx((0.0, 0.0))
    assert offsets[1] == pytest.approx((0.02, -0.01))
    assert offsets[2] == pytest.approx((0.04, -0.02))
    assert offsets[3] == pytest.approx((0.06, -0.03))
    assert offsets[4] == pytest.approx((0.08, -0.04))


def test_visual_reference_matches_are_one_to_one_and_keep_strongest() -> None:
    selected = _select_unique_visual_matches(
        [
            (30, 0, 0),
            (20, 1, 0),
            (25, 1, 1),
            (18, 2, 1),
            (22, 2, 2),
        ]
    )

    assert selected == [(30, 0, 0), (25, 1, 1), (22, 2, 2)]


def test_half_second_keyframe_pose_is_interpolated() -> None:
    path = [
        EstimatedPathPoint(0, EstimatedPose(0, 0, 350, 0.8, relative_z=0.0)),
        EstimatedPathPoint(1000, EstimatedPose(2, 4, 10, 1.0, relative_z=1.5)),
    ]

    pose = _poses_at_timestamps(path, [500])[0]

    assert pose.x == pytest.approx(1)
    assert pose.y == pytest.approx(2)
    assert pose.heading_deg == pytest.approx(0)
    assert pose.confidence == pytest.approx(0.9)
    assert pose.relative_z == pytest.approx(0.75)
