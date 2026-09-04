from __future__ import annotations

import pytest

from progress_api.services.localization import (
    _anchor_constrained_alignment,
    _estimate_prior_affine,
    _plan_cluster,
)
from progress_api.services.sfm_localization import SfMPathSample


def test_affine_rejects_plan_matches_confined_to_narrow_strip() -> None:
    correspondences = [
        (
            (0.1 * index, 0.04 * ((index % 2) + 1)),
            (0.2 + 0.06 * index, 0.4 + 0.005 * index),
        )
        for index in range(1, 8)
    ]

    assert _estimate_prior_affine(correspondences, start_x=0.2, start_y=0.4) is None


def test_affine_accepts_well_spread_plan_matches() -> None:
    sources = [
        (0.1, 0.1),
        (0.3, 0.1),
        (0.1, 0.3),
        (0.3, 0.3),
        (0.2, 0.4),
        (0.4, 0.2),
    ]
    correspondences = [
        ((x, y), (0.2 + 0.8 * x, 0.25 + 0.9 * y)) for x, y in sources
    ]

    result = _estimate_prior_affine(correspondences, start_x=0.2, start_y=0.25)

    assert result is not None
    _matrix, _confidence, inliers = result
    assert len(inliers) == len(correspondences)


def test_anchor_alignment_pins_video_start_and_rejects_one_bad_landmark() -> None:
    samples = [
        SfMPathSample(
            timestamp_ms=index * 1000,
            x=0.1 * index,
            y=0.1 * (index % 3),
            heading_deg=0,
            confidence=0.9,
            relative_z=0,
        )
        for index in range(8)
    ]
    correspondences = [
        ((sample.x, sample.y), (0.2 + 0.5 * sample.x, 0.3 + 0.6 * sample.y))
        for sample in samples[1:]
    ]
    correspondences[-1] = (correspondences[-1][0], (0.9, 0.9))

    result = _anchor_constrained_alignment(
        samples,
        correspondences,
        [sample.timestamp_ms for sample in samples[1:]],
        start_x=0.2,
        start_y=0.3,
        source_label="test-anchor",
    )

    assert result is not None
    assert result.points[0][:2] == pytest.approx((0.2, 0.3))
    assert "test-anchor" in result.source
    assert result.points[4][0] == pytest.approx(0.4, abs=0.03)


def test_nearby_human_labels_share_one_plan_landmark_cluster() -> None:
    assert _plan_cluster(0.300, 0.400) == _plan_cluster(0.306, 0.399)
    assert _plan_cluster(0.300, 0.400) != _plan_cluster(0.380, 0.400)
