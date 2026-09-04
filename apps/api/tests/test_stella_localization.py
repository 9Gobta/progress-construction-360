import math
from pathlib import Path

import pytest

from progress_api.services import stella_localization
from progress_api.services.sfm_localization import SfMPathSample
from progress_api.services.stella_localization import (
    StellaLocalizationError,
    TumPose,
    _align_overlapping_segment,
    parse_tum_trajectory,
    tum_poses_to_path,
)


def test_reference_map_uses_pure_localization_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dependency = tmp_path / "dependency"
    dependency.write_text("test", encoding="utf-8")
    (tmp_path / "reference-map.msg").write_bytes(b"reference")
    captured: list[str] = []

    monkeypatch.setattr(
        stella_localization,
        "_existing_path",
        lambda _value, *, label: dependency,
    )

    def fake_run(command: list[str], **_kwargs: object) -> None:
        captured.extend(command)
        trajectory = tmp_path / "trajectory" / "frame_trajectory.txt"
        trajectory.parent.mkdir(parents=True, exist_ok=True)
        trajectory.write_text("", encoding="utf-8")

    monkeypatch.setattr(stella_localization.subprocess, "run", fake_run)

    _, map_database = stella_localization._run_stella(
        tmp_path, use_existing_map=True
    )

    assert "--disable-mapping" in captured
    assert captured[captured.index("--map-db-in") + 1] == "/work/reference-map.msg"
    assert "--map-db-out" not in captured
    assert map_database == tmp_path / "reference-map.msg"


def test_tracking_proxy_limits_encoder_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[str] = []

    monkeypatch.setattr(stella_localization, "_ffmpeg", lambda: "ffmpeg")

    def fake_run(command: list[str], **_kwargs: object) -> None:
        captured.extend(command)

    monkeypatch.setattr(stella_localization.subprocess, "run", fake_run)
    stella_localization._make_tracking_proxy(
        tmp_path / "source.mp4",
        tmp_path / "tracking.mp4",
    )

    assert captured[captured.index("-threads") + 1] == "1"


def test_tracking_proxy_can_extract_a_bounded_segment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[str] = []
    monkeypatch.setattr(stella_localization, "_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(
        stella_localization.subprocess,
        "run",
        lambda command, **_kwargs: captured.extend(command),
    )

    stella_localization._make_tracking_proxy(
        tmp_path / "source.mp4",
        tmp_path / "tracking.mp4",
        start_seconds=12.5,
        duration_seconds=35,
    )

    assert captured[captured.index("-ss") + 1] == "12.500"
    assert captured[captured.index("-t") + 1] == "35.000"


def test_overlapping_segment_is_joined_by_similarity_transform() -> None:
    base = [
        SfMPathSample(timestamp_ms=t, x=t / 1000, y=0, heading_deg=0, confidence=0.9)
        for t in range(0, 10_001, 250)
    ]
    # Same overlap in an independently initialized frame: rotated 90 degrees,
    # translated, and at half the scale.
    segment = [
        SfMPathSample(
            timestamp_ms=t,
            x=5,
            y=-(t / 1000) / 2 + 9,
            heading_deg=90,
            confidence=0.9,
        )
        for t in range(6_000, 15_001, 250)
    ]

    aligned = _align_overlapping_segment(base, segment, overlap_ms=5_000)

    overlap_end = next(sample for sample in aligned if sample.timestamp_ms == 10_000)
    extension_end = aligned[-1]
    assert overlap_end.x == pytest.approx(10, abs=1e-6)
    assert overlap_end.y == pytest.approx(0, abs=1e-6)
    assert extension_end.x == pytest.approx(15, abs=1e-6)
    assert extension_end.y == pytest.approx(0, abs=1e-6)


def test_parse_tum_trajectory_orders_rows(tmp_path: Path) -> None:
    trajectory = tmp_path / "frame_trajectory.txt"
    trajectory.write_text(
        "1.0 1 2 3 0 0 0 1\n0.0 0 2 1 0 0 0 1\n",
        encoding="utf-8",
    )
    with pytest.raises(StellaLocalizationError, match="fewer than four"):
        parse_tum_trajectory(trajectory)

    trajectory.write_text(
        "1.0 1 2 3 0 0 0 1\n"
        "0.0 0 2 1 0 0 0 1\n"
        "0.5 .5 2 2 0 0 0 1\n"
        "1.5 1.5 2 4 0 0 0 1\n",
        encoding="utf-8",
    )
    poses = parse_tum_trajectory(trajectory)
    assert [pose.timestamp_seconds for pose in poses] == [0.0, 0.5, 1.0, 1.5]


def test_tum_camera_translation_becomes_relative_walking_plane() -> None:
    poses = [
        TumPose(0.0, 10, 4, 20, 0, 0, 0, 1),
        TumPose(0.5, 11, 4.5, 22, 0, 0, 0, 1),
        TumPose(1.0, 12, 5, 24, 0, 0, 0, 1),
        TumPose(1.5, 13, 5.5, 26, 0, 0, 0, 1),
    ]
    samples = tum_poses_to_path(poses, expected_frame_count=4)

    assert (samples[0].x, samples[0].y) == (0, 0)
    assert (samples[-1].x, samples[-1].y) == (3, 6)
    assert samples[-1].relative_z == pytest.approx(1.5)
    assert samples[-1].timestamp_ms == 1500
    assert samples[-1].confidence >= 0.9


def test_tum_camera_translation_preserves_shared_map_origin_for_relocalization() -> None:
    poses = [
        TumPose(0.0, 10, 4, 20, 0, 0, 0, 1),
        TumPose(0.5, 11, 4.5, 22, 0, 0, 0, 1),
        TumPose(1.0, 12, 5, 24, 0, 0, 0, 1),
        TumPose(1.5, 13, 5.5, 26, 0, 0, 0, 1),
    ]

    samples = tum_poses_to_path(
        poses,
        expected_frame_count=4,
        preserve_map_origin=True,
    )

    assert (samples[0].x, samples[0].y) == (10, 20)
    assert (samples[-1].x, samples[-1].y) == (13, 26)


def test_tracking_gaps_lower_confidence() -> None:
    poses = [
        TumPose(0.0, 0, 0, 0, 0, 0, 0, 1),
        TumPose(0.1, 1, 0, 0, 0, 0, 0, 1),
        TumPose(0.2, 2, 0, 0, 0, 0, 0, 1),
        TumPose(3.0, 3, 0, 0, 0, 0, 0, 1),
    ]
    samples = tum_poses_to_path(poses, expected_frame_count=30)

    assert samples[-1].confidence < samples[1].confidence
    assert samples[1].confidence < 0.5


def test_camera_heading_uses_equirectangular_longitude_convention() -> None:
    identity = TumPose(0.0, 0, 0, 0, 0, 0, 0, 1)
    quarter_turn_right = TumPose(
        0.5,
        0,
        0,
        0,
        0,
        math.sin(math.pi / 4),
        0,
        math.cos(math.pi / 4),
    )
    poses = [identity, quarter_turn_right, quarter_turn_right, quarter_turn_right]

    samples = tum_poses_to_path(poses, expected_frame_count=4)

    assert samples[0].heading_deg == pytest.approx(0)
    assert samples[1].heading_deg == pytest.approx(90)
