"""Apply reviewed slab marks and workflows to existing slab zones."""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from import_ifc_structural_elements import reviewed_slab_type, reviewed_slab_zones
from progress_api.db import SessionLocal
from progress_api.models import Floor, StructuralElement
from sqlalchemy import select


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_id", type=uuid.UUID)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--levels", nargs="+", type=int, default=[1, 2, 3, 4])
    parser.add_argument(
        "--backup",
        type=Path,
        default=Path(".codex_tmp/slab-types-before-floor1-20260908.json"),
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        rows = db.execute(
            select(Floor, StructuralElement)
            .join(StructuralElement, StructuralElement.floor_id == Floor.id)
            .where(
                Floor.project_id == args.project_id,
                Floor.level_index.in_(tuple(args.levels)),
                StructuralElement.element_kind == "SLAB",
                StructuralElement.is_active.is_(True),
            )
            .order_by(Floor.level_index, StructuralElement.ifc_global_id)
        ).all()
        zone_labels = {
            level: {str(zone["id"]): str(zone["label"]) for zone in reviewed_slab_zones(level)}
            for level in args.levels
        }
        updates: list[tuple[StructuralElement, str, str, str]] = []
        backup_rows: list[dict[str, object]] = []
        for floor, element in rows:
            prefix = f"PLAN-SLAB-L{floor.level_index}-"
            if not element.ifc_global_id.startswith(prefix):
                raise RuntimeError(f"Unexpected slab identity: {element.ifc_global_id}")
            zone_id = element.ifc_global_id.removeprefix(prefix)
            slab_type = reviewed_slab_type(floor.level_index, zone_id)
            if slab_type is None:
                raise RuntimeError(f"Missing reviewed slab type: {element.ifc_global_id}")
            workflow = (
                "S1_FLOOR_1"
                if floor.level_index == 1 and slab_type == "S1"
                else slab_type
            )
            label = zone_labels[floor.level_index].get(zone_id)
            if label is None:
                raise RuntimeError(f"Missing reviewed slab label: {element.ifc_global_id}")
            updates.append((element, slab_type, workflow, label))
            backup_rows.append({
                "id": str(element.id),
                "floor_level": floor.level_index,
                "ifc_global_id": element.ifc_global_id,
                "geometry_json": element.geometry_json,
            })

        counts = {
            slab_type: sum(
                1 for _element, value, _workflow, _label in updates if value == slab_type
            )
            for slab_type in ("GS", "S1", "PC1")
        }
        if args.apply:
            args.backup.parent.mkdir(parents=True, exist_ok=True)
            args.backup.write_text(json.dumps({
                "created_at": datetime.now(timezone.utc).isoformat(),
                "project_id": str(args.project_id),
                "rows": backup_rows,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            for element, slab_type, workflow, label in updates:
                element.code = f"พื้นที่ {label}"
                element.name = f"พื้นที่พื้นตามกริด {label}"
                element.geometry_json = {
                    **element.geometry_json,
                    "slab_type": slab_type,
                    "slab_workflow": workflow,
                }
            db.commit()
        print(json.dumps({
            "mode": "apply" if args.apply else "preview",
            "total": len(updates),
            "counts": counts,
            "backup": str(args.backup) if args.apply else None,
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
