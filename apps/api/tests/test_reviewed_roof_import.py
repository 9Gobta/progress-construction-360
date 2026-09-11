from scripts.import_reviewed_roof_elements import roof_two_elements


def test_twenty_nine_box_rafters_are_four_active_count_groups() -> None:
    elements = roof_two_elements()
    groups = [
        element for element in elements
        if str(element["code"]).startswith("R2-RAFTER-GROUP-")
    ]
    placeholders = [
        element for element in elements
        if "RAFTER" in str(element["code"])
        and "LEGACY" in str(element["code"])
    ]

    assert {element["code"] for element in groups} == {
        "R2-RAFTER-GROUP-UPPER",
        "R2-RAFTER-GROUP-RIGHT",
        "R2-RAFTER-GROUP-LOWER",
        "R2-RAFTER-GROUP-LEFT",
    }
    quantities = {
        element["code"]: element["geometry"]["total_quantity"]
        for element in groups
    }
    assert quantities == {
        "R2-RAFTER-GROUP-UPPER": 7,
        "R2-RAFTER-GROUP-RIGHT": 7,
        "R2-RAFTER-GROUP-LOWER": 12,
        "R2-RAFTER-GROUP-LEFT": 3,
    }
    assert all(element["geometry"]["progress_mode"] == "COUNT" for element in groups)
    assert sum(len(element["geometry"]["lines"]) for element in groups) == 29
    assert len(placeholders) == 25
    assert all(element["is_active"] is False for element in placeholders)
    assert len(elements) == 72


def test_twenty_steel_purlins_are_four_active_count_groups() -> None:
    elements = roof_two_elements()
    groups = [
        element for element in elements
        if str(element["code"]).startswith("R2-PURLIN-GROUP-")
    ]
    placeholders = [
        element for element in elements
        if str(element["code"]).startswith("R2-PURLIN-LEGACY-")
    ]

    assert {element["code"] for element in groups} == {
        "R2-PURLIN-GROUP-UPPER",
        "R2-PURLIN-GROUP-RIGHT",
        "R2-PURLIN-GROUP-LOWER",
        "R2-PURLIN-GROUP-LEFT",
    }
    assert all(element["geometry"]["progress_mode"] == "COUNT" for element in groups)
    assert all(element["geometry"]["total_quantity"] == 5 for element in groups)
    assert sum(len(element["geometry"]["lines"]) for element in groups) == 20
    assert len(placeholders) == 16
    assert all(element["is_active"] is False for element in placeholders)
