from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

from progress_api.services.schedule_import import (
    OPTIONAL_COLUMNS,
    REQUIRED_COLUMNS,
    ImportedActivity,
    add_upper_floor_shoring_activities,
    load_schedule_workbook,
)


def test_workbook_uses_start_finish_when_baseline_is_na(tmp_path: Path) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Task_Table1"
    worksheet.append((*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS))
    worksheet.append(
        (
            "1.งานคานชั้น 1",
            "1",
            "January 15, 2026 8:00 AM",
            "January 31, 2026 5:00 PM",
            "NA",
            "NA",
            "1",
        )
    )
    worksheet.append(
        (
            "1.1.งานผูกเหล็กคานชั้น 1",
            "1.1",
            "January 17, 2026 8:00 AM",
            "January 23, 2026 5:00 PM",
            "NA",
            "NA",
            "0.5",
        )
    )
    path = tmp_path / "schedule.xlsx"
    workbook.save(path)
    workbook.close()

    result = load_schedule_workbook(path)

    assert result.sheet_name == "Task_Table1"
    assert result.used_baseline_dates is False
    assert result.rows[0].is_summary is True
    assert result.rows[1].parent_wbs == "1"
    assert "Start_Date/Finish_Date" in result.warnings[0]
    assert "Percent_Complete was ignored" in result.warnings[1]


def test_upper_floor_schedule_adds_shoring_except_columns() -> None:
    start = datetime(2026, 1, 1)
    finish = datetime(2026, 1, 2)
    rows = tuple(
        ImportedActivity(
            source_row_no=index + 2,
            name=name,
            wbs=wbs,
            parent_wbs=wbs.rpartition(".")[0],
            planned_start=start,
            planned_finish=finish,
            is_summary=False,
        )
        for index, (wbs, name) in enumerate((
            ("1.2.2.1.1", "งานผูกเหล็กคานชั้น 2"),
            ("1.2.2.1.2", "งานเข้าแบบคานชั้น 2"),
            ("1.2.2.2.1", "งานวางแผ่นพื้น PC ชั้น 2"),
            ("1.2.2.3.1", "งานผูกเหล็กเสาชั้น 2"),
            ("1.2.2.4.1", "งานผูกเหล็กบันไดชั้น 2"),
        ))
    )

    normalized, changed = add_upper_floor_shoring_activities(rows)
    by_wbs = {row.wbs: row.name for row in normalized}

    assert changed is True
    assert by_wbs["1.2.2.1.1"] == "งานค้ำยันคานชั้น 2"
    assert by_wbs["1.2.2.1.2"] == "งานผูกเหล็กคานชั้น 2"
    assert by_wbs["1.2.2.2.1"] == "งานค้ำยันพื้นชั้น 2"
    assert by_wbs["1.2.2.4.1"] == "งานค้ำยันบันไดชั้น 2"
    assert by_wbs["1.2.2.3.1"] == "งานผูกเหล็กเสาชั้น 2"
    assert not any("ค้ำยันเสา" in row.name for row in normalized)

    repeated, repeated_change = add_upper_floor_shoring_activities(normalized)
    assert repeated_change is False
    assert repeated == normalized
