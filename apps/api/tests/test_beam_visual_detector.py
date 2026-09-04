from progress_api.services.beam_visual_detector import is_plausible_beam_box


def test_horizontal_beam_box_is_accepted() -> None:
    assert is_plausible_beam_box(
        (80.0, 250.0, 500.0, 330.0), image_width=640, image_height=640
    )


def test_vertical_column_cage_is_rejected() -> None:
    assert not is_plausible_beam_box(
        (280.0, 80.0, 350.0, 540.0), image_width=640, image_height=640
    )


def test_tiny_false_positive_is_rejected() -> None:
    assert not is_plausible_beam_box(
        (10.0, 10.0, 30.0, 20.0), image_width=640, image_height=640
    )
