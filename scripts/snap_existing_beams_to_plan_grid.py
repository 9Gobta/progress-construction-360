"""Repair imported beam centrelines using the reviewed structural grid."""

from __future__ import annotations

import argparse
import uuid

from import_ifc_structural_elements import snap_beam_line_to_plan_grid
from progress_api.db import SessionLocal
from progress_api.models import BeamSegment, Floor, Sheet, StructuralElement
from sqlalchemy import select


def repair(project_id: uuid.UUID, *, dry_run: bool) -> dict[str, float | int]:
    changed = 0
    old_total = 0.0
    new_total = 0.0
    with SessionLocal() as db:
        rows = list(
            db.execute(
                select(BeamSegment, Floor.level_index)
                .join(Sheet, BeamSegment.sheet_id == Sheet.id)
                .join(Floor, Sheet.floor_id == Floor.id)
                .where(Floor.project_id == project_id, BeamSegment.is_active.is_(True))
            )
        )
        elements = {
            (element.floor_id, element.code): element
            for element in db.scalars(
                select(StructuralElement).where(
                    StructuralElement.project_id == project_id,
                    StructuralElement.element_kind == "BEAM",
                    StructuralElement.is_active.is_(True),
                )
            )
        }
        for segment, _level in rows:
            old_length = float(segment.length_m or 0)
            old_total += old_length
            line = [
                [float(segment.start_x), float(segment.start_y)],
                [float(segment.end_x), float(segment.end_y)],
            ]
            snapped_line, snapped_length = snap_beam_line_to_plan_grid(line, old_length)
            new_total += snapped_length
            if snapped_line == line and abs(snapped_length - old_length) < 0.0005:
                continue
            changed += 1
            segment.start_x, segment.start_y = snapped_line[0]
            segment.end_x, segment.end_y = snapped_line[1]
            segment.length_m = round(snapped_length, 3)
            segment.source = "PLAN_GRID_SNAPPED"
            floor_id = db.scalar(select(Sheet.floor_id).where(Sheet.id == segment.sheet_id))
            element = elements.get((floor_id, segment.code))
            if element is not None:
                element.geometry_json = {**element.geometry_json, "line": snapped_line}
                element.source = "IFC_PLAN_GRID_SNAPPED"
        if dry_run:
            db.rollback()
        else:
            db.commit()
    return {
        "changed_segments": changed,
        "old_total_length_m": round(old_total, 3),
        "new_total_length_m": round(new_total, 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_id", type=uuid.UUID)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(repair(args.project_id, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
