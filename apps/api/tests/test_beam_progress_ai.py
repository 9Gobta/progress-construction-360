import numpy as np

from progress_api.services.beam_progress_ai import (
    extract_visual_feature,
    progress_stage,
    temporal_progress_predict,
    visual_knn_predict,
    visual_stage_predict,
)


def test_visual_feature_is_deterministic_and_finite() -> None:
    image = np.zeros((128, 256, 3), dtype=np.uint8)
    image[:, :128] = (20, 80, 180)
    first = extract_visual_feature(image)
    second = extract_visual_feature(image.copy())
    assert first.shape == second.shape
    assert len(first) > 60
    assert np.all(np.isfinite(first))
    assert np.allclose(first, second)


def test_visual_knn_prefers_nearest_training_evidence() -> None:
    features = np.asarray([[0.0, 0.0], [0.5, 0.5], [1.0, 1.0], [1.5, 1.5]], dtype=np.float32)
    targets = np.asarray([0.0, 30.0, 70.0, 100.0], dtype=np.float32)
    prediction, confidence = visual_knn_predict(
        features, targets, np.asarray([1.45, 1.45], dtype=np.float32)
    )
    assert 65.0 <= prediction <= 100.0
    assert 0.0 <= confidence <= 1.0


def test_visual_knn_output_is_bounded() -> None:
    features = np.asarray([[0.0], [1.0], [2.0]], dtype=np.float32)
    targets = np.asarray([0.0, 100.0, 100.0], dtype=np.float32)
    prediction, _confidence = visual_knn_predict(
        features, targets, np.asarray([100.0], dtype=np.float32)
    )
    assert 0.0 <= prediction <= 100.0


def test_progress_stage_maps_only_to_observable_work_stages() -> None:
    assert progress_stage(0.0) == "NOT_STARTED"
    assert progress_stage(20.0) == "REBAR"
    assert progress_stage(40.0) == "FORMWORK"
    assert progress_stage(75.0) == "CONCRETED"
    assert progress_stage(100.0) == "STRIPPED"


def test_visual_stage_predict_uses_nearest_image_stage() -> None:
    features = np.asarray(
        [[0.0, 0.0], [0.05, 0.04], [1.0, 1.0], [1.05, 1.04]],
        dtype=np.float32,
    )
    stages = ["NOT_STARTED", "NOT_STARTED", "REBAR", "REBAR"]
    stage, confidence = visual_stage_predict(
        features, stages, np.asarray([0.98, 1.02], dtype=np.float32)
    )
    assert stage == "REBAR"
    assert 0.0 <= confidence <= 1.0


def test_temporal_progress_extrapolates_monotonic_trend() -> None:
    prediction, confidence = temporal_progress_predict(
        ["2025-12-23T10:00:00", "2025-12-26T10:00:00", "2026-01-05T10:00:00"],
        np.asarray([0.0, 20.0, 60.0], dtype=np.float32),
        "2026-01-09T10:00:00",
    )
    assert 70.0 <= prediction <= 100.0
    assert 0.0 <= confidence <= 1.0


def test_temporal_progress_never_learns_negative_construction_slope() -> None:
    prediction, _confidence = temporal_progress_predict(
        ["2026-01-01T10:00:00", "2026-01-02T10:00:00", "2026-01-03T10:00:00"],
        np.asarray([80.0, 60.0, 40.0], dtype=np.float32),
        "2026-01-04T10:00:00",
    )
    assert 0.0 <= prediction <= 100.0
