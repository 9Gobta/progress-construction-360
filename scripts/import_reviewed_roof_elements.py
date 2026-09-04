from __future__ import annotations

import argparse
import json
import uuid
from datetime import date

from progress_api.db import SessionLocal
from progress_api.models import (
    Activity,
    Floor,
    ScheduleVersion,
    Sheet,
    StructuralElement,
)
from sqlalchemy import select

ROOF_AVAILABLE_FROM = date(2026, 6, 16)
ROOF_ACTIVITY_WBS = {
    "PURLIN": "1.2.5.1",
    "KING_POST": "1.2.5.2",
    "RC_BEAM": "1.2.5.3",
    "SLAB": "1.2.5.4",
    "RIDGE": "1.2.5.5",
    "RAFTER_BRIDGE": "1.2.5.6",
    "HIP_RIDGE": "1.2.5.7",
    "BOX_RAFTER": "1.2.5.8",
    "STEEL_PURLIN": "1.2.5.9",
    "COLUMN": "1.2.5.10",
    "TIE_ROD": "1.2.5.11",
}

ROOF_ACTIVITIES = (
    (ROOF_ACTIVITY_WBS["PURLIN"], "งานอะเสชั้นหลังคา"),
    (ROOF_ACTIVITY_WBS["KING_POST"], "งานดั้งชั้นหลังคา"),
    (ROOF_ACTIVITY_WBS["RC_BEAM"], "งานคาน ค.ส.ล. ชั้นหลังคา"),
    (ROOF_ACTIVITY_WBS["SLAB"], "งานพื้นชั้นหลังคา"),
    (ROOF_ACTIVITY_WBS["RIDGE"], "งานอกไก่เหล็ก ST-B1 ชั้นหลังคา"),
    (ROOF_ACTIVITY_WBS["RAFTER_BRIDGE"], "งานสะพานรับจันทันเหล็ก ST-B1 ชั้นหลังคา"),
    (ROOF_ACTIVITY_WBS["HIP_RIDGE"], "งานตะเฆ่สันเหล็กชั้นหลังคา"),
    (ROOF_ACTIVITY_WBS["BOX_RAFTER"], "งานจันทันเหล็กกล่องชั้นหลังคา"),
    (ROOF_ACTIVITY_WBS["STEEL_PURLIN"], "งานแปเหล็กชั้นหลังคา"),
    (ROOF_ACTIVITY_WBS["COLUMN"], "งานเสาชั้นหลังคา"),
    (ROOF_ACTIVITY_WBS["TIE_ROD"], "งาน Tie Rod ชั้นหลังคา"),
)

GRID_X = (0.1998, 0.2889, 0.3783, 0.4674, 0.5570, 0.6487)
GRID_Y = (0.2729, 0.4075, 0.4715, 0.6057)


def line(code: str, activity: str, start: tuple[float, float], end: tuple[float, float]):
    return {
        "code": code,
        "activity_wbs": ROOF_ACTIVITY_WBS[activity],
        "geometry": {"line": [list(start), list(end)]},
    }


def zone(
    code: str,
    activity: str,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
):
    return {
        "code": code,
        "activity_wbs": ROOF_ACTIVITY_WBS[activity],
        "geometry": {
            "line": [[x1, (y1 + y2) / 2], [x2, (y1 + y2) / 2]],
            "footprint": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
        },
    }


def support(code: str, x: float, y: float):
    half_x, half_y = 0.0045, 0.0065
    return zone(
        code,
        "KING_POST",
        x - half_x,
        y - half_y,
        x + half_x,
        y + half_y,
    )


def roof_marker(code: str, activity: str, x: float, y: float):
    half_x, half_y = 0.0045, 0.0065
    return zone(
        code,
        activity,
        x - half_x,
        y - half_y,
        x + half_x,
        y + half_y,
    )


def roof_column_marker(code: str, x: float, y: float):
    # Slightly larger than the printed column symbol so the UI can draw a
    # clean hollow frame around it and provide a comfortable click target.
    half_x, half_y = 0.007, 0.010
    return zone(
        code,
        "COLUMN",
        x - half_x,
        y - half_y,
        x + half_x,
        y + half_y,
    )


def roof_one_elements() -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    purlin_items: list[dict[str, object]] = []
    # ST-07 blue review: every highlighted ST-B1 member is an อะเส.
    for row_name, y, start_index in (
        ("A", GRID_Y[0], 1),
        ("B", GRID_Y[1], 0),
        ("C", GRID_Y[2], 0),
        ("D", GRID_Y[3], 0),
    ):
        for index in range(start_index, 5):
            # Grid 1-2 at rows B and C is the B3 reinforced-concrete
            # stair beam shown on ST-07, not an ST-B1 steel purlin.
            if row_name in {"B", "C"} and index == 0:
                continue
            purlin_items.append(line(
                f"PURLIN1-{row_name}-{index + 1}-{index + 2}",
                "PURLIN",
                (GRID_X[index], y),
                (GRID_X[index + 1], y),
            ))
    for index, x in enumerate(GRID_X):
        start_y = GRID_Y[0] if index >= 1 else GRID_Y[1]
        for row in range(3):
            y1, y2 = GRID_Y[row], GRID_Y[row + 1]
            if y2 <= start_y:
                continue
            # The yellow-reviewed stair frame is reinforced concrete:
            # grid 1 from B-C and grid 2 from A-C.
            if (index == 0 and row == 1) or (index == 1 and row in {0, 1}):
                continue
            purlin_items.append(line(
                f"PURLIN1-{index + 1}-{row + 1}",
                "PURLIN",
                (x, max(y1, start_y)),
                (x, y2),
            ))

    # Two additional ST-B1 members shown between grids 2-3 and 4-5,
    # spanning rows B-C on the reviewed ST-07 markup.
    for index, x in enumerate((0.317, 0.529), start=1):
        purlin_items.append(line(
            f"PURLIN1-B-C-INNER-{index}",
            "PURLIN",
            (x, GRID_Y[1]),
            (x, GRID_Y[2]),
        ))

    items.extend(purlin_items)

    upper = GRID_Y[0] + 0.58 * (GRID_Y[1] - GRID_Y[0])

    # ST-07 Cx symbols: 12 steel king posts (ดั้งเหล็กกล่อง).
    middle_y = (GRID_Y[1] + GRID_Y[2]) / 2
    king_post_beam_offset_y = 0.009
    king_post_points = [
        # The Cx marks sit immediately outside the B/C beam centrelines,
        # at the red-reviewed points rather than on top of the beam lines.
        *((x, GRID_Y[1] - king_post_beam_offset_y) for x in GRID_X[2:5]),
        (GRID_X[1], middle_y),
        (0.317, middle_y),
        (GRID_X[2], middle_y),
        (GRID_X[3], middle_y),
        (0.529, middle_y),
        *((x, GRID_Y[2] + king_post_beam_offset_y) for x in GRID_X[1:5]),
    ]
    for index, (x, y) in enumerate(king_post_points, start=1):
        items.append(roof_marker(f"RKP1-{index}", "KING_POST", x, y))

    # Reinforced-concrete B2/B3 beams stay separate from the ST-B1 purlins.
    items.extend([
        line("RCB1-B2-TOP", "RC_BEAM", (GRID_X[0], upper), (GRID_X[1], upper)),
        line("RCB1-B3-B", "RC_BEAM", (GRID_X[0], GRID_Y[1]), (GRID_X[1], GRID_Y[1])),
        line("RCB1-B3-C", "RC_BEAM", (GRID_X[0], GRID_Y[2]), (GRID_X[1], GRID_Y[2])),
        line("RCB1-B3-L-UPPER", "RC_BEAM", (GRID_X[0], upper), (GRID_X[0], GRID_Y[1])),
        line("RCB1-B3-L-B-C", "RC_BEAM", (GRID_X[0], GRID_Y[1]), (GRID_X[0], GRID_Y[2])),
        line("RCB1-B3-R-A-B", "RC_BEAM", (GRID_X[1], GRID_Y[0]), (GRID_X[1], GRID_Y[1])),
        line("RCB1-B3-R-B-C", "RC_BEAM", (GRID_X[1], GRID_Y[1]), (GRID_X[1], GRID_Y[2])),
    ])

    # The two S1 reinforced-concrete floor panels highlighted at grid 1-2.
    items.extend([
        zone("RSLAB1-S1-UPPER", "SLAB", GRID_X[0], upper, GRID_X[1], GRID_Y[1]),
        zone("RSLAB1-S1-B-C", "SLAB", GRID_X[0], GRID_Y[1], GRID_X[1], GRID_Y[2]),
    ])
    return items


def reviewed_lines(
    code_prefix: str,
    activity: str,
    segments: list[tuple[tuple[float, float], tuple[float, float]]],
) -> list[dict[str, object]]:
    """Create separately selectable members traced from a reviewed markup."""
    return [
        line(f"{code_prefix}-{index}", activity, start, end)
        for index, (start, end) in enumerate(segments, start=1)
    ]


def roof_two_elements() -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    # ST-08 green review: only this B6/B7/CB6 frame is confirmed as
    # reinforced-concrete roof beams. Other roof-two work types are added
    # only after their reviewed locations are supplied.
    curb = [
        ((GRID_X[1], GRID_Y[0]), (GRID_X[2], GRID_Y[0])),
        # Columns at row B interrupt both vertical beams. Keep the A-B and
        # B-lower spans as separate progress items instead of crossing the
        # column with one oversized beam.
        ((GRID_X[1], GRID_Y[0]), (GRID_X[1], GRID_Y[1])),
        ((GRID_X[1], GRID_Y[1]), (GRID_X[1], 0.440)),
        ((GRID_X[2], GRID_Y[0]), (GRID_X[2], GRID_Y[1])),
        ((GRID_X[2], GRID_Y[1]), (GRID_X[2], 0.440)),
        ((GRID_X[1], GRID_Y[1]), (GRID_X[2], GRID_Y[1])),
        ((GRID_X[1], 0.440), (GRID_X[2], 0.440)),
    ]
    for index, (start, end) in enumerate(curb, start=1):
        items.append(line(f"RB2-CURB-{index}", "RC_BEAM", start, end))

    # Four reviewed roof columns at the corners of the B6/B7/CB6 frame.
    # Keep them as compact footprints so their clickable area matches the
    # column symbols instead of covering the adjacent beams or slabs.
    for index, (x, y) in enumerate((
        (GRID_X[1], GRID_Y[0]),
        (GRID_X[2], GRID_Y[0]),
        (GRID_X[1], GRID_Y[1]),
        (GRID_X[2], GRID_Y[1]),
    ), start=1):
        items.append(roof_column_marker(f"RCOL2-{index}", x, y))

    # The reviewed S2 floor is split at the B7 beam. This preserves the two
    # real beam-bounded panels rather than creating one oversized selection.
    items.extend([
        zone(
            "RSLAB2-S2-A-B",
            "SLAB",
            GRID_X[1],
            GRID_Y[0],
            GRID_X[2],
            GRID_Y[1],
        ),
        zone(
            "RSLAB2-S2-LOWER",
            "SLAB",
            GRID_X[1],
            GRID_Y[1],
            GRID_X[2],
            0.440,
        ),
    ])

    # ST-08 colour review. Each colour is a distinct roof work type and each
    # drawn member remains independently selectable in the progress viewer.
    ridge = [
        # The ST-B1 ridge starts after the short left bridge transition and
        # ends at the right transition, matching the latest green review.
        ((0.3179, 0.4395), (0.5283, 0.4395)),
    ]
    rafter_bridge = [
        ((0.2886, 0.4802), (0.5562, 0.4802)),
        ((0.3828, 0.3995), (0.5581, 0.3995)),
        ((0.5568, 0.3981), (0.5568, 0.4824)),
        ((0.2890, 0.4416), (0.2890, 0.4803)),
    ]
    hip_ridge = [
        ((0.5303, 0.4362), (0.6917, 0.2078)),
        ((0.5306, 0.4425), (0.6915, 0.6703)),
        ((0.1548, 0.6703), (0.3159, 0.4422)),
        # Latest orange review: the horizontal left member continues the
        # steel hip-ridge system into the lower-left roof edge.
        ((0.1528, 0.4395), (0.3188, 0.4395)),
        ((0.3811, 0.2080), (0.3811, 0.4381)),
    ]
    box_rafter = [
        # Horizontal rafters stop at the hip lines. They are separate left
        # and right members and must not bridge across the central roof bay.
        ((0.5298, 0.4395), (0.6943, 0.4395)),
        ((0.1538, 0.5075), (0.2725, 0.5075)),
        ((0.5747, 0.5075), (0.6929, 0.5075)),
        ((0.1538, 0.5750), (0.2236, 0.5750)),
        ((0.6230, 0.5750), (0.6929, 0.5750)),
        ((0.1528, 0.6420), (0.1763, 0.6420)),
        ((0.6699, 0.6420), (0.6929, 0.6420)),
        ((0.5747, 0.3726), (0.6924, 0.3726)),
        ((0.6235, 0.3047), (0.6924, 0.3047)),
        ((0.6712, 0.2376), (0.6950, 0.2376)),
        ((0.4019, 0.2073), (0.4019, 0.6738)),
        ((0.4442, 0.2066), (0.4442, 0.6717)),
        ((0.4865, 0.2066), (0.4865, 0.6717)),
        ((0.5283, 0.2073), (0.5283, 0.6752)),
        # On the right roof plane the pink middle portions are purlin-side
        # zones, not box rafters. Keep only the upper and lower rafter pieces.
        ((0.5760, 0.2073), (0.5760, 0.3726)),
        ((0.5760, 0.5075), (0.5760, 0.6717)),
        ((0.6238, 0.2066), (0.6238, 0.3047)),
        ((0.6238, 0.5750), (0.6238, 0.6724)),
        ((0.6712, 0.2073), (0.6712, 0.2376)),
        ((0.6712, 0.6420), (0.6712, 0.6710)),
        ((0.3172, 0.4409), (0.3172, 0.6731)),
        ((0.3602, 0.4423), (0.3602, 0.6738)),
        ((0.2701, 0.5059), (0.2701, 0.6724)),
        ((0.2221, 0.5736), (0.2221, 0.6717)),
        ((0.1748, 0.6406), (0.1748, 0.6717)),
    ]
    # Latest red review: purlins exist only on the roof planes. The four
    # horizontal members and one short vertical inside the orange bridge
    # frame are deliberately excluded.
    steel_purlin = [
        ((0.1523, 0.6735), (0.6938, 0.6735)),
        ((0.1831, 0.6309), (0.6626, 0.6309)),
        ((0.2104, 0.5890), (0.6338, 0.5890)),
        ((0.2427, 0.5483), (0.5942, 0.5483)),
        ((0.2715, 0.5048), (0.5762, 0.5048)),
        ((0.3828, 0.3736), (0.5757, 0.3736)),
        ((0.3828, 0.3315), (0.6055, 0.3315)),
        ((0.3906, 0.2899), (0.6328, 0.2899)),
        ((0.3828, 0.2481), (0.6641, 0.2481)),
        ((0.3809, 0.2049), (0.6948, 0.2049)),
        ((0.1527, 0.4388), (0.1527, 0.6745)),
        ((0.1819, 0.4423), (0.1819, 0.6303)),
        ((0.2111, 0.4402), (0.2111, 0.5881)),
        ((0.2417, 0.4409), (0.2417, 0.5480)),
        ((0.2719, 0.4381), (0.2719, 0.5066)),
        ((0.5748, 0.3725), (0.5748, 0.5066)),
        ((0.6046, 0.3317), (0.6046, 0.5480)),
        ((0.6338, 0.2903), (0.6338, 0.5909)),
        ((0.6638, 0.2495), (0.6638, 0.6323)),
        ((0.6936, 0.2039), (0.6936, 0.6738)),
    ]

    items.extend(reviewed_lines("R2-RIDGE", "RIDGE", ridge))
    items.extend(reviewed_lines("R2-BRIDGE", "RAFTER_BRIDGE", rafter_bridge))
    items.extend(reviewed_lines("R2-HIP", "HIP_RIDGE", hip_ridge))
    items.extend(reviewed_lines("R2-RAFTER", "BOX_RAFTER", box_rafter))
    items.extend(reviewed_lines("R2-PURLIN", "STEEL_PURLIN", steel_purlin))
    return items


def roof_three_elements() -> list[dict[str, object]]:
    # ST-09 blue review: four columns at the corners of grids 2-3 / A-B.
    items = [
        roof_column_marker("RCOL3-1", GRID_X[1], GRID_Y[0]),
        roof_column_marker("RCOL3-2", GRID_X[2], GRID_Y[0]),
        roof_column_marker("RCOL3-3", GRID_X[1], GRID_Y[1]),
        roof_column_marker("RCOL3-4", GRID_X[2], GRID_Y[1]),
    ]

    # ST-09 colour review: purple X = Tie Rod, red horizontals = steel
    # purlins, and the yellow perimeter = box rafters.
    tie_rods = [
        # Tie rods terminate at the column centrelines, not at the outer
        # purlin frame beyond the column symbols.
        ((GRID_X[1], GRID_Y[0]), (GRID_X[2], GRID_Y[1])),
        ((GRID_X[2], GRID_Y[0]), (GRID_X[1], GRID_Y[1])),
    ]
    steel_purlins = [
        ((0.2750, 0.2574), (0.3945, 0.2574)),
        ((0.2750, 0.2975), (0.3945, 0.2975)),
        ((0.2750, 0.3407), (0.3945, 0.3407)),
        ((0.2750, 0.3832), (0.3945, 0.3832)),
        ((0.2750, 0.4240), (0.3945, 0.4240)),
    ]
    box_rafters = [
        ((0.2905, 0.2688), (0.3770, 0.2688)),
        ((0.3770, 0.2688), (0.3770, 0.4126)),
        ((0.3770, 0.4126), (0.2905, 0.4126)),
        ((0.2905, 0.4126), (0.2905, 0.2688)),
    ]
    items.extend(reviewed_lines("R3-TIE", "TIE_ROD", tie_rods))
    items.extend(reviewed_lines("R3-PURLIN", "STEEL_PURLIN", steel_purlins))
    items.extend(reviewed_lines("R3-RAFTER", "BOX_RAFTER", box_rafters))
    return items


REVIEWED_BY_LEVEL = {
    5: roof_one_elements,
    6: roof_two_elements,
    7: roof_three_elements,
}


def ensure_roof_activities(db, project_id: uuid.UUID) -> list[str]:
    schedule = db.scalar(select(ScheduleVersion).where(
        ScheduleVersion.project_id == project_id,
        ScheduleVersion.status == "READY",
        ScheduleVersion.is_baseline.is_(True),
    ).order_by(ScheduleVersion.version_no.desc()))
    if schedule is None:
        schedule = db.scalar(select(ScheduleVersion).where(
            ScheduleVersion.project_id == project_id,
            ScheduleVersion.status == "READY",
        ).order_by(ScheduleVersion.version_no.desc()))
    if schedule is None:
        raise ValueError("missing READY schedule for roof activities")

    activities = list(db.scalars(select(Activity).where(
        Activity.schedule_version_id == schedule.id,
    )))
    by_wbs = {activity.wbs: activity for activity in activities}
    parent = by_wbs.get("1.2.5")
    if parent is None:
        raise ValueError("missing roof summary activity 1.2.5")

    updated: list[str] = []
    next_source_row = max((activity.source_row_no for activity in activities), default=0) + 1
    for wbs, name in ROOF_ACTIVITIES:
        activity = by_wbs.get(wbs)
        if activity is None:
            activity = Activity(
                schedule_version_id=schedule.id,
                parent_activity_id=parent.id,
                wbs=wbs,
                name=name,
                planned_start=parent.planned_start,
                planned_finish=parent.planned_finish,
                percent_complete_source=0,
                is_summary=False,
                weight=None,
                source_row_no=next_source_row,
            )
            db.add(activity)
            by_wbs[wbs] = activity
            next_source_row += 1
        else:
            activity.name = name
            activity.parent_activity_id = parent.id
            activity.is_summary = False
        updated.append(wbs)

    return updated


def import_reviewed_roofs(project_id: uuid.UUID) -> dict[str, object]:
    with SessionLocal() as db:
        updated_activities = ensure_roof_activities(db, project_id)
        floors = {
            floor.level_index: floor
            for floor in db.scalars(select(Floor).where(Floor.project_id == project_id))
        }
        existing = {
            item.ifc_global_id: item
            for item in db.scalars(select(StructuralElement).where(
                StructuralElement.project_id == project_id,
                StructuralElement.ifc_global_id.like("PLAN-ROOF-%"),
            ))
        }
        for item in existing.values():
            item.is_active = False

        # The old IFC roof members were attached to floor 4. Roof work now
        # lives only on the three reviewed roof sheets.
        for item in db.scalars(select(StructuralElement).where(
            StructuralElement.project_id == project_id,
            StructuralElement.element_kind == "ROOF",
            StructuralElement.source == "IFC_PLAN_ALIGNED",
        )):
            item.is_active = False

        counts: dict[str, int] = {}
        for level, factory in REVIEWED_BY_LEVEL.items():
            floor = floors.get(level)
            if floor is None:
                raise ValueError(f"missing roof floor at level_index={level}")
            floor.available_from = ROOF_AVAILABLE_FROM
            sheet = db.scalar(select(Sheet).where(
                Sheet.floor_id == floor.id,
                Sheet.sheet_type == "STRUCTURAL",
                Sheet.is_active.is_(True),
            ).order_by(Sheet.created_at.desc()))
            for index, reviewed in enumerate(factory(), start=1):
                global_id = f"PLAN-ROOF-L{level}-{index:03d}"
                element = existing.get(global_id)
                if element is None:
                    element = StructuralElement(project_id=project_id, ifc_global_id=global_id)
                    db.add(element)
                geometry = dict(reviewed["geometry"])
                geometry["activity_wbs"] = reviewed["activity_wbs"]
                element.floor_id = floor.id
                element.sheet_id = sheet.id if sheet else None
                element.ifc_type = "REVIEWED_ROOF_PLAN_ELEMENT"
                element.ifc_storey = floor.name
                element.element_kind = "ROOF"
                element.code = str(reviewed["code"])
                element.name = f"{floor.name} · {reviewed['activity_wbs']}"
                element.geometry_json = geometry
                element.source = "REVIEWED_ROOF_PLAN"
                element.is_active = True
                counts[floor.name] = counts.get(floor.name, 0) + 1
        db.commit()
        return {
            "available_from": ROOF_AVAILABLE_FROM.isoformat(),
            "updated_activities": updated_activities,
            "counts": counts,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_id", type=uuid.UUID)
    args = parser.parse_args()
    print(json.dumps(import_reviewed_roofs(args.project_id), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
