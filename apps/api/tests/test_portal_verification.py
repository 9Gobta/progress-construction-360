from progress_api.services.portal_verification import _weighted_direction


def test_weighted_direction_handles_panorama_seam() -> None:
    direction, dispersion = _weighted_direction([(100, 179.0), (100, -179.0)])

    assert abs(abs(direction) - 180.0) < 0.01
    assert dispersion == 1.0


def test_weighted_direction_prioritizes_stronger_geometric_result() -> None:
    direction, dispersion = _weighted_direction([(300, 30.0), (30, 45.0)])

    assert 30.0 < direction < 32.0
    assert dispersion < 3.0
