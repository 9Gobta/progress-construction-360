from pathlib import Path

from openpyxl import Workbook

from progress_api.services.schedule_import import (
    OPTIONAL_COLUMNS,
    REQUIRED_COLUMNS,
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
