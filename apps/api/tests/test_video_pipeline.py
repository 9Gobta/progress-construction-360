from pathlib import Path

import cv2
import numpy as np

from progress_api.services.video_pipeline import (
    CAPTURE_FRAME_FPS,
    WARP_POINT_INTERVAL_SECONDS,
    TourStationSample,
    _extract_tour_panoramas,
    build_spatial_visibility_targets,
    classify_keyframe_quality,
    remove_consecutive_duplicate_warp_points,
    select_spatial_warp_points,
    select_warp_points,
)


def _write(path: Path, image: np.ndarray) -> None:
    assert cv2.imwrite(str(path), image)


def test_keyframe_quality_rejects_dark_frame(tmp_path: Path) -> None:
    frame = tmp_path / "dark.jpg"
    _write(frame, np.zeros((240, 480), dtype=np.uint8))

    assert classify_keyframe_quality(frame) == "REJECTED"


def test_keyframe_quality_marks_flat_frame_blurry(tmp_path: Path) -> None:
    frame = tmp_path / "flat.jpg"
    _write(frame, np.full((240, 480), 120, dtype=np.uint8))

    assert classify_keyframe_quality(frame) == "BLURRY"


def test_keyframe_quality_accepts_sharp_frame(tmp_path: Path) -> None:
    frame = tmp_path / "sharp.jpg"
    checker = np.indices((240, 480)).sum(axis=0) % 2
    _write(frame, (checker * 255).astype(np.uint8))

    assert classify_keyframe_quality(frame) == "USABLE"


def test_warp_point_selection_keeps_best_frame_in_each_window() -> None:
    window_size = CAPTURE_FRAME_FPS * WARP_POINT_INTERVAL_SECONDS
    quality = [("BLURRY", float(index)) for index in range(window_size * 2)]
    first_best = min(3, window_size - 1)
    second_best = window_size + min(7, window_size - 1)
    quality[first_best] = ("USABLE", 30.0)
    quality[second_best] = ("USABLE", 80.0)

    assert select_warp_points(quality) == {0, first_best, second_best, len(quality) - 1}


def test_warp_point_selection_keeps_true_start_and_end_for_single_window() -> None:
    quality = [("BLURRY", 1.0), ("USABLE", 10.0)]

    assert select_warp_points(quality) == {0, 1}


def test_spatial_warp_points_are_distributed_by_travelled_distance() -> None:
    samples = [
        TourStationSample(index, index * 500, "USABLE", float(index), 0.0, 0.0)
        for index in range(17)
    ]

    selected = select_spatial_warp_points(samples)

    assert selected == {0, 8, 16}


def test_spatial_warp_points_do_not_stack_during_stationary_video() -> None:
    samples = [
        TourStationSample(index, index * 500, "USABLE", 2.0, 3.0, 0.0) for index in range(17)
    ]

    assert select_spatial_warp_points(samples) == {0, 16}


def test_dense_warp_points_remove_only_consecutive_duplicate_places() -> None:
    samples = [
        TourStationSample(index, index * 1000, "USABLE", x, y, 0)
        for index, (x, y) in enumerate(
            [
                (0, 0),
                (0, 0),
                (1, 0),
                (1, 0),
                (0, 0),
                (0, 0),
            ]
        )
    ]

    assert remove_consecutive_duplicate_warp_points(
        samples,
        {0, 1, 2, 3, 4, 5},
    ) == {0, 2, 4, 5}


def test_spatial_warp_points_do_not_turn_tiny_drift_into_fake_steps() -> None:
    samples = [
        TourStationSample(
            index,
            index * 500,
            "USABLE",
            index * 0.001 if index < 40 else float(index - 39),
            0.0,
            0.0,
        )
        for index in range(81)
    ]

    selected = select_spatial_warp_points(samples)
    selected_times = sorted(samples[index].timestamp_ms for index in selected)

    # The first 20 seconds move only four centimetres in the reconstructed
    # frame. A time-based filler would paint several rings there even though a
    # click could only swap to an almost identical panorama.
    assert all(timestamp == 0 or timestamp >= 20_000 for timestamp in selected_times)


def test_spatial_visibility_targets_use_nearest_real_stations_and_cap_at_twenty() -> None:
    samples = [
        TourStationSample(index, index * 500, "USABLE", float(index), 0.0, 0.0)
        for index in range(25)
    ]
    stations = set(range(25))

    graph = build_spatial_visibility_targets(samples, stations)

    assert len(graph[0]) == 20
    assert graph[0] == list(range(1, 21))
    assert all(
        target in stations and target != source
        for source, targets in graph.items()
        for target in targets
    )


def test_tour_panorama_extraction_decodes_selected_frames_in_one_pass(
    tmp_path: Path,
    monkeypatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str]):
        commands.append(command)
        output = Path(command[-1]).parent
        output.mkdir(parents=True, exist_ok=True)
        (output / "000001.jpg").write_bytes(b"first")
        (output / "000002.jpg").write_bytes(b"second")

    monkeypatch.setattr("progress_api.services.video_pipeline._binary", lambda name: name)
    monkeypatch.setattr("progress_api.services.video_pipeline._run", fake_run)

    result = _extract_tour_panoramas(
        source=tmp_path / "source.mp4",
        destination_dir=tmp_path / "tour",
        frame_indices=[0, 4],
        source_fps=30.0,
        width=7680,
        height=3840,
    )

    assert list(result) == [0, 4]
    assert len(commands) == 1
    assert any("select=eq(n\\,0)+eq(n\\,60)" in argument for argument in commands[0])
