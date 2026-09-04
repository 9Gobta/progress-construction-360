import cv2
import numpy as np
import pytest

from progress_api.services.spherical_scan import (
    SCAN_PITCHES,
    SCAN_YAWS,
    perspective_remap,
    render_spherical_views,
    usable_view_score,
)


def test_default_scan_covers_three_levels_and_all_yaws() -> None:
    panorama = np.zeros((180, 360, 3), dtype=np.uint8)
    views = render_spherical_views(panorama, output_size=32)
    assert len(views) == 24
    assert {view.yaw_deg for view in views} == set(SCAN_YAWS)
    assert {view.pitch_deg for view in views} == set(SCAN_PITCHES)
    assert all(view.image.shape == (32, 32, 3) for view in views)


@pytest.mark.parametrize("yaw_deg", SCAN_YAWS)
@pytest.mark.parametrize("pitch_deg", SCAN_PITCHES)
def test_view_center_points_to_requested_spherical_direction(
    yaw_deg: float, pitch_deg: float
) -> None:
    map_x, map_y = perspective_remap(720, 360, yaw_deg, pitch_deg, 101, 100.0)
    center_x = float(map_x[50, 50])
    center_y = float(map_y[50, 50])
    expected_x = ((yaw_deg / 360.0) + 0.5) * 720
    expected_y = (0.5 - pitch_deg / 180.0) * 360
    if expected_x >= 720:
        expected_x -= 720
    assert center_x == pytest.approx(expected_x, abs=2.0)
    assert center_y == pytest.approx(expected_y, abs=2.0)


def test_usable_view_score_rejects_blue_sky_more_than_textured_site() -> None:
    sky = np.full((128, 128, 3), (230, 160, 80), dtype=np.uint8)
    site = np.zeros((128, 128, 3), dtype=np.uint8)
    for offset in range(0, 128, 8):
        cv2.line(site, (offset, 0), (127 - offset, 127), (80, 130, 180), 2)
    assert usable_view_score(site) > usable_view_score(sky)
