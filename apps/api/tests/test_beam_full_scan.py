import uuid

import numpy as np

from progress_api.services.beam_full_scan import (
    BeamVisualEvidence,
    PanoramaFrame,
    evidence_for_plan_segment,
    observed_stage,
    scan_panoramas,
    select_full_timeline,
)
from progress_api.services.beam_visual_detector import BeamDetection, stage_from_label


class FakeDetector:
    def __init__(self) -> None:
        self.image_count = 0

    def detect(self, images):
        self.image_count += len(images)
        return [
            [BeamDetection("REBAR", 0.9, (200, 100, 440, 400), "beam rebar cage")]
            for _image in images
        ]


def frame(timestamp_ms: int, *, heading_deg: float = 0.0) -> PanoramaFrame:
    return PanoramaFrame(
        keyframe_id=uuid.uuid4(),
        timestamp_ms=timestamp_ms,
        image=np.zeros((64, 128, 3), dtype=np.uint8),
        camera_x=0.5,
        camera_y=0.5,
        heading_deg=heading_deg,
    )


def test_full_timeline_includes_start_regular_intervals_and_end() -> None:
    frames = [frame(value) for value in (0, 500, 1_000, 2_000, 3_500, 4_100)]
    assert [item.timestamp_ms for item in select_full_timeline(frames, 2_000)] == [
        0,
        2_000,
        4_100,
    ]


def test_scan_runs_24_views_for_every_selected_time() -> None:
    detector = FakeDetector()
    evidence = scan_panoramas([frame(0), frame(2_000), frame(4_000)], detector)
    assert detector.image_count == 72
    assert len(evidence) == 72
    assert {item.pitch_deg for item in evidence} == {-45.0, 0.0, 45.0}


def test_stage_mapping_does_not_treat_absence_as_not_started() -> None:
    assert stage_from_label("installed structural beam reinforcement cage") == "REBAR"
    assert stage_from_label("installed structural beam formwork") == "FORMWORK"
    assert (
        stage_from_label("exposed reinforced concrete beam after formwork removal")
        == "STRIPPED"
    )
    assert stage_from_label("beam reinforcement cage and formwork") is None
    assert stage_from_label("empty construction area") is None


def test_plan_association_uses_real_camera_bearing() -> None:
    matching = BeamVisualEvidence(
        keyframe_id=uuid.uuid4(), timestamp_ms=0, yaw_deg=90, pitch_deg=0,
        stage="REBAR", score=0.9, box_xyxy=(0, 0, 1, 1),
        camera_x=0.5, camera_y=0.5, global_bearing_deg=90,
    )
    wrong_direction = BeamVisualEvidence(
        **{**matching.__dict__, "keyframe_id": uuid.uuid4(), "global_bearing_deg": 270}
    )
    result = evidence_for_plan_segment(
        [matching, wrong_direction], segment_midpoint=(0.6, 0.5), max_plan_distance=0.2
    )
    assert result == [matching]


def test_stage_requires_multiple_distinct_detected_images() -> None:
    base = dict(
        yaw_deg=0.0, pitch_deg=45.0, stage="FORMWORK", score=0.8,
        box_xyxy=(0, 0, 1, 1), camera_x=0.5, camera_y=0.5,
        global_bearing_deg=0.0,
    )
    two = [
        BeamVisualEvidence(keyframe_id=uuid.uuid4(), timestamp_ms=value, **base)
        for value in (0, 2_000)
    ]
    assert observed_stage(two) == (None, 0.0, 0)
    three = two + [
        BeamVisualEvidence(keyframe_id=uuid.uuid4(), timestamp_ms=4_000, **base)
    ]
    stage, confidence, support = observed_stage(three)
    assert stage == "FORMWORK"
    assert confidence > 0
    assert support == 3
