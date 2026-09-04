"""Import reviewed DWG beam centre-lines as the active progress inventory.

The operation is idempotent and preserves historical progress attached to old
segments. Superseded IFC/demo beam segments and structural beam overlays are
disabled instead of deleted.
"""

from __future__ import annotations

import argparse
import json
import uuid
from decimal import Decimal
from pathlib import Path

from progress_api.db import SessionLocal
from progress_api.models import BeamSegment, Floor, Sheet, StructuralElement
from sqlalchemy import select


def reviewed_beam_record(level: int, raw: dict[str, object]) -> dict[str, object]:
    """Keep reviewed CAD geometry and face-to-face quantities unchanged."""
    return raw


def import_inventory(
    project_id: uuid.UUID, source: Path
) -> dict[str, dict[str, int | float]]:
    inventory = json.loads(source.read_text(encoding="utf-8"))
    results: dict[str, dict[str, int | float]] = {}
    with SessionLocal() as db:
        floors = {
            floor.level_index: floor
            for floor in db.scalars(select(Floor).where(Floor.project_id == project_id))
        }
        for level_text, floor_data in inventory["floors"].items():
            level = int(level_text)
            floor = floors.get(level)
            if floor is None:
                raise RuntimeError(f"project has no floor level {level}")
            sheet = db.scalar(
                select(Sheet)
                .where(Sheet.floor_id == floor.id, Sheet.sheet_type == "STRUCTURAL")
                .order_by(Sheet.created_at)
            )
            if sheet is None:
                sheet = Sheet(
                    floor_id=floor.id,
                    name=f"แปลนโครงสร้างชั้น {level}",
                    sheet_type="STRUCTURAL",
                    is_active=True,
                )
                db.add(sheet)
                db.flush()

            existing_segments = {
                segment.code: segment
                for segment in db.scalars(
                    select(BeamSegment).where(BeamSegment.sheet_id == sheet.id)
                )
            }
            for segment in existing_segments.values():
                segment.is_active = False

            existing_elements = {
                element.ifc_global_id: element
                for element in db.scalars(
                    select(StructuralElement).where(
                        StructuralElement.project_id == project_id,
                        StructuralElement.floor_id == floor.id,
                        StructuralElement.element_kind == "BEAM",
                    )
                )
            }
            for element in existing_elements.values():
                element.is_active = False

            total_length = Decimal(0)
            for raw in floor_data["beams"]:
                raw = reviewed_beam_record(level, raw)
                code = str(raw["id"])
                beam_type = str(raw.get("beam_type") or "").strip() or None
                start_x, start_y = (Decimal(str(value)) for value in raw["plan_start"])
                end_x, end_y = (Decimal(str(value)) for value in raw["plan_end"])
                length_m = Decimal(str(raw["length_m"]))
                total_length += length_m

                segment = existing_segments.get(code)
                if segment is None:
                    segment = BeamSegment(sheet_id=sheet.id, code=code)
                    db.add(segment)
                segment.beam_type = beam_type
                segment.start_x = start_x
                segment.start_y = start_y
                segment.end_x = end_x
                segment.end_y = end_y
                segment.length_m = length_m
                segment.source = "CAD_DWG"
                segment.is_active = True

                global_id = f"CAD-BEAM-{code}"
                element = existing_elements.get(global_id)
                if element is None:
                    element = StructuralElement(
                        project_id=project_id,
                        ifc_global_id=global_id,
                    )
                    db.add(element)
                element.floor_id = floor.id
                element.sheet_id = sheet.id
                element.ifc_type = "CAD_BEAM_CENTERLINE"
                element.ifc_storey = f"CAD LEVEL {level}"
                element.element_kind = "BEAM"
                element.code = code
                element.name = f"คาน {beam_type}" if beam_type else "คานรอตรวจป้าย"
                element.geometry_json = {
                    "line": [[float(start_x), float(start_y)], [float(end_x), float(end_y)]]
                }
                element.source = "CAD_DWG"
                element.is_active = True

            results[level_text] = {
                "segments": len(floor_data["beams"]),
                "total_length_m": float(total_length),
            }
        db.commit()
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_id", type=uuid.UUID)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            import_inventory(args.project_id, args.source),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
