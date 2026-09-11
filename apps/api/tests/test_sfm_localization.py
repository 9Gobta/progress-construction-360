import numpy as np
import pytest

from progress_api.services.sfm_localization import (
    FACE_SIZE,
    SfMPathSample,
    _estimate_camera_height,
    _face_parts,
    _horizontal_heading,
    _interpolate,
    _panorama_heading,
    _perspective_map,
    _remove_isolated_spatial_outliers,
    _smooth_camera_track,
    _yaw_delta_between,
)


def test_camera_height_is_estimated_from_surface_below_route() -> None:
    centers = np.asarray([[float(index), 2.0, 0.0] for index in range(8)])
    floor = np.asarray(
        [[x, 0.35 + 0.01 * ((index % 3) - 1), z]
         for index, x in enumerate(np.linspace(0, 7, 120))
         for z in (-0.3, 0.0, 0.3)]
    )
    wall = np.asarray([[3.0, y, 2.0] for y in np.linspace(-2, 4, 80)])

    height = _estimate_camera_height(
        centers, np.vstack([floor, wall]), np.asarray([0.0, 1.0, 0.0])
    )

    assert height == pytest.approx(1.65, abs=0.04)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("0012_3_12000.jpg", ("0012", 3, "12000")),
        ("3/0012_12000.jpg", ("0012", 3, "12000")),
    ],
)
def test_cubemap_image_name_supports_flat_and_rig_layout(
    name: str, expected: tuple[str, int, str]
) -> None:
    assert _face_parts(name) == expected


def test_perspective_map_stays_inside_equirectangular_frame() -> None:
    map_x, map_y = _perspective_map(yaw_deg=90)

    assert map_x.shape == (FACE_SIZE, FACE_SIZE)
    assert map_y.shape == (FACE_SIZE, FACE_SIZE)
    assert np.isfinite(map_x).all()
    assert np.isfinite(map_y).all()
    assert float(map_x.min()) >= 0
    assert float(map_x.max()) <= 1920
    assert float(map_y.min()) >= 0
    assert float(map_y.max()) <= 960


def test_cubemap_face_heading_is_converted_to_panorama_axis() -> None:
    # Face 0 looks along the panorama's zero-longitude axis. Face 1 is rendered
    # 90 degrees clockwise, so its reconstructed heading must be unrotated.
    assert _panorama_heading(90, 0) == 90
    assert _panorama_heading(0, 1) == 90


def test_panorama_yaw_uses_horizontal_feature_motion() -> None:
    rng = np.random.default_rng(20260822)
    previous = rng.integers(0, 255, size=(480, 960), dtype=np.uint8)
    current = np.roll(previous, 20, axis=1)

    yaw_delta = _yaw_delta_between(previous, current)

    assert yaw_delta == pytest.approx(-7.5, abs=1.0)


def test_reconstructed_panorama_ray_maps_to_walking_plane_heading() -> None:
    vertical = np.array([0.0, 1.0, 0.0])
    axis_x = np.array([1.0, 0.0, 0.0])
    axis_y = np.array([0.0, 0.0, 1.0])

    assert _horizontal_heading(
        np.array([1.0, 0.2, 0.0]),
        vertical=vertical,
        axis_x=axis_x,
        axis_y=axis_y,
    ) == pytest.approx(90)
    assert _horizontal_heading(
        np.array([0.0, -0.1, 1.0]),
        vertical=vertical,
        axis_x=axis_x,
        axis_y=axis_y,
    ) == pytest.approx(0)


def test_sfm_path_interpolation_preserves_turn_and_stop() -> None:
    samples = [
        SfMPathSample(0, 0, 0, 0, 0.9),
        SfMPathSample(5_000, 1, 0, 0, 0.9),
        SfMPathSample(10_000, 1, 0, 90, 0.8),
        SfMPathSample(15_000, 1, 1, 90, 0.8),
    ]

    result = _interpolate(samples, 15_000)

    assert len(result) == 31
    assert (result[10].x, result[10].y) == (1, 0)
    assert (result[20].x, result[20].y) == (1, 0)
    assert (result[30].x, result[30].y) == (1, 1)
    assert result[20].heading_deg == 90


def test_sfm_path_interpolation_preserves_relative_height() -> None:
    samples = [
        SfMPathSample(0, 0, 0, 0, 0.9, relative_z=0),
        SfMPathSample(1_000, 1, 0, 0, 0.9, relative_z=2),
    ]

    result = _interpolate(samples, 1_000)

    assert result[1].relative_z == pytest.approx(1)


def test_sfm_path_interpolation_preserves_normalized_orientation() -> None:
    samples = [
        SfMPathSample(
            0,
            0,
            0,
            0,
            0.9,
            orientation_q=(0.0, 0.0, 0.0, 1.0),
        ),
        # The same quaternion hemisphere must be selected before interpolation.
        SfMPathSample(
            1_000,
            1,
            0,
            180,
            0.9,
            orientation_q=(0.0, -1.0, 0.0, 0.0),
        ),
    ]

    result = _interpolate(samples, 1_000)

    midpoint = np.asarray(result[1].orientation_q)
    assert np.linalg.norm(midpoint) == pytest.approx(1.0)
    assert midpoint == pytest.approx((0.0, -2**-0.5, 0.0, 2**-0.5))


def test_camera_track_smoothing_reduces_single_frame_jitter() -> None:
    samples = [
        SfMPathSample(index * 1000, float(index), 8.0 if index == 3 else 0.0, 0, 0.9)
        for index in range(7)
    ]

    smoothed = _smooth_camera_track(samples)

    assert smoothed[3].y < 3
    assert smoothed[0].x == pytest.approx(0)
    assert smoothed[0].y == pytest.approx(0)


def test_isolated_spatial_excursion_is_removed_before_smoothing() -> None:
    samples = [
        SfMPathSample(0, 0, 0, 0, 0.9),
        SfMPathSample(1_000, 1, 0, 0, 0.9),
        SfMPathSample(2_000, 2, 0, 0, 0.9),
        SfMPathSample(3_000, 40, 30, 0, 0.9, relative_z=8),
        SfMPathSample(4_000, 3, 0, 0, 0.9),
        SfMPathSample(5_000, 4, 0, 0, 0.9),
        SfMPathSample(6_000, 5, 0, 0, 0.9),
        SfMPathSample(7_000, 6, 0, 0, 0.9),
    ]

    result = _remove_isolated_spatial_outliers(samples)

    assert [sample.timestamp_ms for sample in result] == [
        0,
        1_000,
        2_000,
        4_000,
        5_000,
        6_000,
        7_000,
    ]
