"""Import reviewed IFC geometry into plan-aligned structural inventories.

This is intentionally an explicit project operation: extraction is reviewed
first, then this importer performs idempotent GlobalId upserts. Existing human
progress records are retained; obsolete/demo beam segments are only disabled.
"""

from __future__ import annotations

import argparse
import json
import math
import uuid
from decimal import ROUND_HALF_EVEN, Decimal
from itertools import pairwise
from pathlib import Path

from progress_api.db import SessionLocal
from progress_api.models import BeamSegment, Floor, Sheet, StructuralElement
from sqlalchemy import select

STOREY_TO_LEVEL = {
    "ระดับพื้นชั้นที่ 1": 1,
    "ระดับพื้นชั้นที่ 2": 2,
    "ระดับพื้นชั้นที่ 3": 3,
    "ระดับพื้นชั้นที่ 4": 4,
}
FOUNDATION_STOREY = "ระดับฐานราก"
GROUND_STOREY = "ระดับดินเดิม"
ROOF_STOREYS = {"ระดับพื้น SLAB", "ระดับพื้น SLAB.", "ระดับอะเส่", "ระดับอกไก่"}

# The IFC building axes are rotated 69 degrees in world coordinates.  The
# anchors below are the six numbered and four lettered grid axes read from the
# structural sheets. They are shared by ST-03 through ST-06.
U_AXIS = (math.cos(math.radians(69)), math.sin(math.radians(69)))
V_AXIS = (-U_AXIS[1], U_AXIS[0])
U_WORLD = (0.009, 18.764)
V_WORLD = (15.263, 25.163)
X_PLAN = (0.1998, 0.6487)
Y_PLAN = (0.2729, 0.6057)
PLAN_GRID_X = (0.1998, 0.2889, 0.3783, 0.4674, 0.5570, 0.6487)
PLAN_GRID_Y = (0.2729, 0.4075, 0.4715, 0.6057)
PLAN_GRID_X_LABELS = ("1", "2", "3", "4", "5", "6")
PLAN_GRID_Y_LABELS = ("A", "B", "C", "D")
PLAN_GRID_X_METERS = (0.0, 3.75, 7.50, 11.25, 15.00, 18.75)
PLAN_GRID_Y_METERS = (0.0, 4.00, 5.90, 9.90)
PLAN_BOTTOM_Y = PLAN_GRID_Y[-1] + (1.80 / 9.90) * (PLAN_GRID_Y[-1] - PLAN_GRID_Y[0])
PLAN_RIGHT_EXTENSION_X = PLAN_GRID_X[-1] + (
    0.60 / 18.75
) * (PLAN_GRID_X[-1] - PLAN_GRID_X[0])
# ST-03 divides grid 3-4/A-B into two panels and the two ramp-side bays
# into three panels. Their reviewed B2 centrelines are 0.83 m and 2.36 m
# from grid A. These five lines divide slab panels even though they are not
# part of the user-selectable beam progress inventory.
LEVEL_ONE_UPPER_Y_METERS = (0.0, 0.83, 2.36, 4.0)
# The right-hand floor projection begins at the lower reviewed B2 line in
# grid 5-6/A-B, not at grid B.  Its CAD boundary runs from this line to grid C.
LEVEL_ONE_RIGHT_EXTENSION_TOP_M = 2.36
# The five 1.80 m-deep panels below grid D alternate their internal beam at
# 2.12 m and 1.63 m from the left grid line, as dimensioned on ST-03.
LEVEL_ONE_BOTTOM_SPLIT_M = (2.12, 1.63, 2.12, 1.63, 2.12)
GRID_SNAP_TOLERANCE = 0.012
BEAM_WIDTH_M = 0.20
LEVEL_ONE_SHORT_B1_X_M = 11.817


def _rectangle_union_area(rectangles: list[tuple[float, float, float, float]]) -> float:
    """Return the exact union area of a small set of axis-aligned rectangles."""
    if not rectangles:
        return 0.0
    xs = sorted({value for rectangle in rectangles for value in rectangle[::2]})
    ys = sorted({value for rectangle in rectangles for value in rectangle[1::2]})
    area = 0.0
    for x1, x2 in pairwise(xs):
        mid_x = (x1 + x2) / 2
        for y1, y2 in pairwise(ys):
            mid_y = (y1 + y2) / 2
            if any(
                left <= mid_x <= right and top <= mid_y <= bottom
                for left, top, right, bottom in rectangles
            ):
                area += (x2 - x1) * (y2 - y1)
    return area


def _level_one_beam_rectangles() -> list[tuple[float, float, float, float]]:
    """All ST-03 beam footprints that reduce the clear slab surface."""
    half_width = BEAM_WIDTH_M / 2
    rectangles: list[tuple[float, float, float, float]] = []

    # Horizontal beams: grid A begins at grid 2; the remaining rows span grids 1-6.
    for y, start_x in ((0.0, 3.75), (4.0, 0.0), (5.90, 0.0), (9.90, 0.0), (11.70, 0.0)):
        rectangles.append((start_x, y - half_width, 18.75, y + half_width))

    # Main vertical beams and the five intermediate lines below grid D.
    for x, start_y in ((0.0, 4.0), (3.75, 0.0), (7.50, 0.0),
                       (11.25, 0.0), (15.0, 0.0), (18.75, 0.0)):
        rectangles.append((x - half_width, start_y, x + half_width, 11.70))
    for x in (2.12, 5.38, 9.62, 12.88, 17.12):
        rectangles.append((x - half_width, 9.90, x + half_width, 11.70))

    # The 0.60 m slab projection at the right of grid 6 starts at the lower
    # ramp-side B2 line (2.36 m below A) and continues as one panel to grid C.
    rectangles.extend((
        (
            18.75,
            LEVEL_ONE_RIGHT_EXTENSION_TOP_M - half_width,
            19.35,
            LEVEL_ONE_RIGHT_EXTENSION_TOP_M + half_width,
        ),
        (18.75, 5.90 - half_width, 19.35, 5.90 + half_width),
        (
            19.35 - half_width,
            LEVEL_ONE_RIGHT_EXTENSION_TOP_M,
            19.35 + half_width,
            5.90,
        ),
    ))

    # Five B2 lines divide the upper floor panels. They remain excluded from
    # beam progress selection, but their physical width must be removed from
    # the slab quantity.
    for left, right, y_values in (
        (7.50, 11.25, (0.83,)),
        (11.25, 15.00, (0.83, 2.36)),
        (15.00, 18.75, (0.83, 2.36)),
    ):
        for y in y_values:
            rectangles.append((left, y - half_width, right, y + half_width))

    # The reviewed 0.90 m B1 beside the ramp.
    rectangles.append((
        LEVEL_ONE_SHORT_B1_X_M - half_width,
        0.0,
        LEVEL_ONE_SHORT_B1_X_M + half_width,
        0.90,
    ))
    return rectangles


def _net_floor_one_slab_area(
    left: float, top: float, right: float, bottom: float
) -> tuple[float, float]:
    """Return gross and net slab area after subtracting the beam footprint once."""
    gross_area = (right - left) * (bottom - top)
    clipped_beams: list[tuple[float, float, float, float]] = []
    for beam_left, beam_top, beam_right, beam_bottom in _level_one_beam_rectangles():
        clipped = (
            max(left, beam_left),
            max(top, beam_top),
            min(right, beam_right),
            min(bottom, beam_bottom),
        )
        if clipped[0] < clipped[2] and clipped[1] < clipped[3]:
            clipped_beams.append(clipped)
    return gross_area, gross_area - _rectangle_union_area(clipped_beams)


def reviewed_slab_zones(level: int) -> list[dict[str, object]]:
    """Return selectable slab panels that follow the reviewed sheet boundaries."""
    zones: list[dict[str, object]] = []

    def add_zone(
        zone_id: str,
        label: str,
        x1: float,
        x2: float,
        y1: float,
        y2: float,
        width_m: float,
        depth_m: float,
    ) -> None:
        zones.append({
            "id": zone_id,
            "label": label,
            "x1": x1,
            "x2": x2,
            "y1": y1,
            "y2": y2,
            "area_m2": float(
                (Decimal(str(width_m)) * Decimal(str(depth_m))).quantize(
                    Decimal("0.001"), rounding=ROUND_HALF_EVEN
                )
            ),
        })

    # The regular B-C and C-D rows contain one panel per numbered grid bay.
    for row_label, y_index_1, y_index_2 in (("B-C", 1, 2), ("C-D", 2, 3)):
        depth_m = PLAN_GRID_Y_METERS[y_index_2] - PLAN_GRID_Y_METERS[y_index_1]
        for x_index in range(5):
            width_m = PLAN_GRID_X_METERS[x_index + 1] - PLAN_GRID_X_METERS[x_index]
            bay = f"{PLAN_GRID_X_LABELS[x_index]}-{PLAN_GRID_X_LABELS[x_index + 1]}/{row_label}"
            add_zone(
                f"{x_index + 1}-{row_label}", bay,
                PLAN_GRID_X[x_index], PLAN_GRID_X[x_index + 1],
                PLAN_GRID_Y[y_index_1], PLAN_GRID_Y[y_index_2], width_m, depth_m,
            )

    if level == 1:
        # Grid 2-3 has one panel, grid 3-4 has two, and grids 4-6 each
        # have three panels divided by the B2 lines drawn on ST-03.
        upper_edges_by_x_index = {
            1: (0.0, 4.0),
            2: (0.0, 0.83, 4.0),
            3: LEVEL_ONE_UPPER_Y_METERS,
            4: LEVEL_ONE_UPPER_Y_METERS,
        }
        for x_index, panel_edges in upper_edges_by_x_index.items():
            multiple_panels = len(panel_edges) > 2
            for panel_index, (start_m, end_m) in enumerate(pairwise(panel_edges), start=1):
                y1 = PLAN_GRID_Y[0] + (start_m / 4.0) * (PLAN_GRID_Y[1] - PLAN_GRID_Y[0])
                y2 = PLAN_GRID_Y[0] + (end_m / 4.0) * (PLAN_GRID_Y[1] - PLAN_GRID_Y[0])
                bay = (
                    f"{PLAN_GRID_X_LABELS[x_index]}-{PLAN_GRID_X_LABELS[x_index + 1]}"
                    f"/A-B{f'.{panel_index}' if multiple_panels else ''}"
                )
                add_zone(
                    (
                        f"{x_index + 1}-A-B-{panel_index}"
                        if multiple_panels else f"{x_index + 1}-A-B"
                    ),
                    bay,
                    PLAN_GRID_X[x_index], PLAN_GRID_X[x_index + 1], y1, y2,
                    3.75, float(Decimal(str(end_m)) - Decimal(str(start_m))),
                )

        # Below grid D, each bay is split into the two panels shown on ST-03.
        for x_index, split_m in enumerate(LEVEL_ONE_BOTTOM_SPLIT_M):
            x1, x2 = PLAN_GRID_X[x_index], PLAN_GRID_X[x_index + 1]
            split_x = x1 + (split_m / 3.75) * (x2 - x1)
            widths = (split_m, 3.75 - split_m)
            for panel_index, (panel_x1, panel_x2, width_m) in enumerate(
                ((x1, split_x, widths[0]), (split_x, x2, widths[1])), start=1
            ):
                bay = (
                    f"{PLAN_GRID_X_LABELS[x_index]}-{PLAN_GRID_X_LABELS[x_index + 1]}"
                    f"/D-EXT.{panel_index}"
                )
                add_zone(
                    f"{x_index + 1}-D-EXT-{panel_index}", bay,
                    panel_x1, panel_x2, PLAN_GRID_Y[3], PLAN_BOTTOM_Y,
                    width_m, 1.80,
                )

        # One framed floor projection outside grid 6, from the lower B2 line
        # above grid B down to grid C (the outline marked in the reviewed plan).
        extension_top_y = PLAN_GRID_Y[0] + (
            LEVEL_ONE_RIGHT_EXTENSION_TOP_M / 4.0
        ) * (PLAN_GRID_Y[1] - PLAN_GRID_Y[0])
        add_zone(
            "6-EXT-B-C",
            "6-EXT/B2-C",
            PLAN_GRID_X[-1],
            PLAN_RIGHT_EXTENSION_X,
            extension_top_y,
            PLAN_GRID_Y[2],
            0.60,
            5.90 - LEVEL_ONE_RIGHT_EXTENSION_TOP_M,
        )
    else:
        # The A-B row is regular except grid 4-5, where B2/B4 beams divide
        # the bay into four independent slab panels (1.73 + 2.27 m deep).
        for x_index in (1, 2, 4):
            bay = f"{PLAN_GRID_X_LABELS[x_index]}-{PLAN_GRID_X_LABELS[x_index + 1]}/A-B"
            add_zone(
                f"{x_index + 1}-A-B", bay,
                PLAN_GRID_X[x_index], PLAN_GRID_X[x_index + 1],
                PLAN_GRID_Y[0], PLAN_GRID_Y[1], 3.75, 4.0,
            )

        split_x = (PLAN_GRID_X[3] + PLAN_GRID_X[4]) / 2
        split_y = PLAN_GRID_Y[0] + (1.73 / 4.0) * (PLAN_GRID_Y[1] - PLAN_GRID_Y[0])
        for column_index, (x1, x2) in enumerate(
            ((PLAN_GRID_X[3], split_x), (split_x, PLAN_GRID_X[4])), start=1
        ):
            for row_index, (y1, y2, depth_m) in enumerate(
                (
                    (PLAN_GRID_Y[0], split_y, 1.73),
                    (split_y, PLAN_GRID_Y[1], 2.27),
                ),
                start=1,
            ):
                add_zone(
                    f"4-A-B-{row_index}-{column_index}",
                    f"4-5/A-B.{row_index}.{column_index}",
                    x1, x2, y1, y2, 1.875, depth_m,
                )

        # Every 1.80 m projection below grid D is split by its drawn B2/CB6
        # beam. The alternating 2.12/1.63 m positions follow ST-04–ST-06.
        for x_index, split_m in enumerate(LEVEL_ONE_BOTTOM_SPLIT_M):
            x1, x2 = PLAN_GRID_X[x_index], PLAN_GRID_X[x_index + 1]
            inner_x = x1 + (split_m / 3.75) * (x2 - x1)
            for panel_index, (panel_x1, panel_x2, width_m) in enumerate(
                (
                    (x1, inner_x, split_m),
                    (inner_x, x2, 3.75 - split_m),
                ),
                start=1,
            ):
                add_zone(
                    f"{x_index + 1}-D-EXT-{panel_index}",
                    (
                        f"{PLAN_GRID_X_LABELS[x_index]}-"
                        f"{PLAN_GRID_X_LABELS[x_index + 1]}/D-EXT.{panel_index}"
                    ),
                    panel_x1, panel_x2, PLAN_GRID_Y[3], PLAN_BOTTOM_Y,
                    width_m, 1.80,
                )

        # Cantilever slab CS2 is shown separately on ST-04 through ST-06,
        # immediately left of grid 2. On floors 2 and 3 its top edge is
        # 1.77 m above grid B; floor 4 extends farther upward and starts
        # 1.20 m below grid A. Do not merge it with the 2-3/A-B stair bay.
        cs2_width_m = 1.25
        cs2_depth_m = 2.80 if level == 4 else 1.77
        cs2_top_m = 4.0 - cs2_depth_m
        cs2_x1 = PLAN_GRID_X[1] - (
            cs2_width_m / 3.75
        ) * (PLAN_GRID_X[1] - PLAN_GRID_X[0])
        cs2_y1 = PLAN_GRID_Y[0] + (
            cs2_top_m / 4.0
        ) * (PLAN_GRID_Y[1] - PLAN_GRID_Y[0])
        add_zone(
            "2-CS2-A-B",
            "CS2 · ซ้าย Grid 2 / A-B",
            cs2_x1,
            PLAN_GRID_X[1],
            cs2_y1,
            PLAN_GRID_Y[1],
            cs2_width_m,
            cs2_depth_m,
        )

        # Only ST-04 (floor 2) has the 0.60 m-wide CS1 projection at the
        # right of grid 6 from grid A through grid C. ST-05 and ST-06 stop
        # at grid 6, so floors 3 and 4 must not receive this selectable zone.
        if level == 2:
            add_zone(
                "6-CS1-A-C",
                "CS1 · ขวา Grid 6 / A-C",
                PLAN_GRID_X[-1],
                PLAN_RIGHT_EXTENSION_X,
                PLAN_GRID_Y[0],
                PLAN_GRID_Y[2],
                0.60,
                5.90,
            )

    if level == 1:
        # Area quantities use the clear slab surface. The plan zones themselves
        # run to beam centre-lines for easy selection, so subtract the 0.20 m
        # beam rectangles as a union: intersections are removed only once and
        # only the half of a perimeter beam that lies inside the slab is counted.
        x_axes = (*PLAN_GRID_X, PLAN_RIGHT_EXTENSION_X)
        x_meters = (*PLAN_GRID_X_METERS, 19.35)
        y_axes = (*PLAN_GRID_Y, PLAN_BOTTOM_Y)
        y_meters = (*PLAN_GRID_Y_METERS, 11.70)

        def to_meters(value: float, axes: tuple[float, ...], meters: tuple[float, ...]) -> float:
            for index, (start, end) in enumerate(pairwise(axes)):
                if start - 1e-9 <= value <= end + 1e-9:
                    ratio = (value - start) / (end - start)
                    return meters[index] + ratio * (meters[index + 1] - meters[index])
            raise ValueError(f"plan coordinate {value} falls outside reviewed axes")

        exact_net_areas: list[Decimal] = []
        for zone in zones:
            left = to_meters(float(zone["x1"]), x_axes, x_meters)
            right = to_meters(float(zone["x2"]), x_axes, x_meters)
            top = to_meters(float(zone["y1"]), y_axes, y_meters)
            bottom = to_meters(float(zone["y2"]), y_axes, y_meters)
            _gross_area, net_area = _net_floor_one_slab_area(left, top, right, bottom)
            gross_area = Decimal(str(zone["area_m2"]))
            exact_net = Decimal(str(net_area))
            exact_net_areas.append(exact_net)
            rounded_net = exact_net.quantize(Decimal("0.001"), rounding=ROUND_HALF_EVEN)
            zone["gross_area_m2"] = float(gross_area)
            zone["area_m2"] = float(rounded_net)

        # Preserve the exact floor total after the individual 0.001 m2 values
        # are rounded for storage. Assign the millimetre-square residual to the
        # largest zone so the API sum remains 178.225 m2.
        target_total = sum(exact_net_areas, Decimal(0)).quantize(
            Decimal("0.001"), rounding=ROUND_HALF_EVEN
        )
        rounded_total = sum((Decimal(str(zone["area_m2"])) for zone in zones), Decimal(0))
        largest_zone = max(zones, key=lambda item: float(item["area_m2"]))
        largest_zone["area_m2"] = float(
            Decimal(str(largest_zone["area_m2"])) + target_total - rounded_total
        )
        for zone in zones:
            zone["beam_area_m2"] = float(
                Decimal(str(zone["gross_area_m2"])) - Decimal(str(zone["area_m2"]))
            )
    return zones


def reviewed_slab_geometry(level: int, zone: dict[str, object]) -> dict[str, object]:
    """Build the visible/selectable clear-floor polygon for one reviewed zone."""
    x1, x2 = float(zone["x1"]), float(zone["x2"])
    y1, y2 = float(zone["y1"]), float(zone["y2"])
    full_right_projection = (
        (level == 1 and zone["id"] == "6-EXT-B-C")
        or (level == 2 and zone["id"] == "6-CS1-A-C")
    )
    if full_right_projection:
        # The reviewed green outlines for the narrow right projections use
        # their complete framed footprints. Do not shrink these already-small
        # 0.60 m-wide zones on all four sides. Floor 1 retains its separately
        # calculated clear/net area while floor 2 retains its plan area.
        inset_x = inset_y = 0.0
    elif level == 1:
        inset_x = (BEAM_WIDTH_M / 2 / 18.75) * (PLAN_GRID_X[-1] - PLAN_GRID_X[0])
        inset_y = (BEAM_WIDTH_M / 2 / 9.90) * (PLAN_GRID_Y[-1] - PLAN_GRID_Y[0])
    else:
        inset_x = inset_y = 0.002
    return {
        "area_m2": zone["area_m2"],
        **(
            {
                "gross_area_m2": zone["gross_area_m2"],
                "beam_area_m2": zone["beam_area_m2"],
            }
            if "gross_area_m2" in zone else {}
        ),
        "line": [[x1 + inset_x, (y1 + y2) / 2], [x2 - inset_x, (y1 + y2) / 2]],
        "footprint": [
            [x1 + inset_x, y1 + inset_y],
            [x2 - inset_x, y1 + inset_y],
            [x2 - inset_x, y2 - inset_y],
            [x1 + inset_x, y2 - inset_y],
        ],
    }


def _normalized(point: list[float]) -> list[float]:
    x, y = point[:2]
    u = x * U_AXIS[0] + y * U_AXIS[1]
    v = x * V_AXIS[0] + y * V_AXIS[1]
    nx = X_PLAN[0] + (u - U_WORLD[0]) * (X_PLAN[1] - X_PLAN[0]) / (U_WORLD[1] - U_WORLD[0])
    ny = Y_PLAN[0] + (v - V_WORLD[0]) * (Y_PLAN[1] - Y_PLAN[0]) / (V_WORLD[1] - V_WORLD[0])
    return [round(max(0.0, min(1.0, nx)), 6), round(max(0.0, min(1.0, ny)), 6)]


def _nearest_grid_index(value: float, axes: tuple[float, ...]) -> int | None:
    index = min(range(len(axes)), key=lambda item: abs(axes[item] - value))
    return index if abs(axes[index] - value) <= GRID_SNAP_TOLERANCE else None


def align_column_geometry_to_reviewed_plan(
    geometry: dict[str, list[list[float]]],
) -> dict[str, list[list[float]]]:
    """Apply the reviewed 23-column topology shown on ST-03 through ST-06.

    The IFC export places the first lower-left column at A/1 even though the
    structural sheets show no building at that bay. The physical column is at
    D/1. Preserve the IFC footprint dimensions and move only that known point.
    """
    footprint = geometry.get("footprint", [])
    if not footprint:
        return geometry
    center_x = sum(point[0] for point in footprint) / len(footprint)
    center_y = sum(point[1] for point in footprint) / len(footprint)
    x_index = _nearest_grid_index(center_x, PLAN_GRID_X)
    y_index = _nearest_grid_index(center_y, PLAN_GRID_Y)
    if x_index != 0 or y_index != 0:
        return geometry
    delta_y = PLAN_GRID_Y[3] - PLAN_GRID_Y[0]
    return {
        key: [[round(point[0], 6), round(point[1] + delta_y, 6)] for point in points]
        for key, points in geometry.items()
    }


def snap_beam_line_to_plan_grid(
    line: list[list[float]],
    fallback_length_m: float,
) -> tuple[list[list[float]], float]:
    """Extend clear IFC beam geometry to verified structural-grid intersections.

    Revit beam solids normally stop at column faces, while progress quantities
    are measured by grid span.  Snap only when both endpoints independently
    match two distinct reviewed axes; ambiguous short and diagonal members are
    intentionally left unchanged.
    """
    start = [float(line[0][0]), float(line[0][1])]
    end = [float(line[1][0]), float(line[1][1])]
    dx = abs(end[0] - start[0])
    dy = abs(end[1] - start[1])
    if dx >= dy * 3:
        start_index = _nearest_grid_index(start[0], PLAN_GRID_X)
        end_index = _nearest_grid_index(end[0], PLAN_GRID_X)
        if start_index is not None and end_index is not None and start_index != end_index:
            start[0] = PLAN_GRID_X[start_index]
            end[0] = PLAN_GRID_X[end_index]
            row_index = _nearest_grid_index((start[1] + end[1]) / 2, PLAN_GRID_Y)
            if row_index is not None:
                start[1] = end[1] = PLAN_GRID_Y[row_index]
            length = abs(PLAN_GRID_X_METERS[end_index] - PLAN_GRID_X_METERS[start_index])
            return [[round(value, 6) for value in start], [round(value, 6) for value in end]], length
    elif dy >= dx * 3:
        start_index = _nearest_grid_index(start[1], PLAN_GRID_Y)
        end_index = _nearest_grid_index(end[1], PLAN_GRID_Y)
        if start_index is not None and end_index is not None and start_index != end_index:
            start[1] = PLAN_GRID_Y[start_index]
            end[1] = PLAN_GRID_Y[end_index]
            column_index = _nearest_grid_index((start[0] + end[0]) / 2, PLAN_GRID_X)
            if column_index is not None:
                start[0] = end[0] = PLAN_GRID_X[column_index]
            length = abs(PLAN_GRID_Y_METERS[end_index] - PLAN_GRID_Y_METERS[start_index])
            return [[round(value, 6) for value in start], [round(value, 6) for value in end]], length
    return [[round(value, 6) for value in start], [round(value, 6) for value in end]], fallback_length_m


def _kind(element: dict[str, object]) -> str | None:
    ifc_type = str(element["ifc_type"])
    name = str(element.get("name") or "")
    storey = str(element.get("storey") or "")
    if name.startswith("Stairs") or ifc_type in {"IfcStair", "IfcStairFlight"}:
        return "STAIR"
    if storey == FOUNDATION_STOREY and ifc_type == "IfcSlab":
        return "FOUNDATION"
    if storey == FOUNDATION_STOREY and ifc_type == "IfcColumn":
        return "PEDESTAL"
    if ifc_type == "IfcBeam" and "DIV03330" in name and "คาน" in name:
        return "BEAM"
    if ifc_type == "IfcColumn" and storey in STOREY_TO_LEVEL:
        return "COLUMN"
    if ifc_type == "IfcSlab" and storey in STOREY_TO_LEVEL:
        return "SLAB"
    if ifc_type == "IfcBeam" and (storey in ROOF_STOREYS or "ROOF" in name.upper()):
        return "ROOF"
    return None


def _level(element: dict[str, object], kind: str) -> int | None:
    storey = str(element.get("storey") or "")
    if kind in {"FOUNDATION", "PEDESTAL"}:
        return 1
    if kind == "ROOF":
        return 4
    return STOREY_TO_LEVEL.get(storey)


def _short_name(element: dict[str, object]) -> str:
    name = str(element.get("name") or element["ifc_type"])
    return name.rsplit(" : ", 1)[-1].strip()


def import_elements(project_id: uuid.UUID, source: Path) -> dict[str, object]:
    data = json.loads(source.read_text(encoding="utf-8"))
    with SessionLocal() as db:
        floors = {
            floor.level_index: floor
            for floor in db.scalars(select(Floor).where(Floor.project_id == project_id))
        }
        sheets = {
            level: db.scalar(
                select(Sheet)
                .where(Sheet.floor_id == floor.id, Sheet.sheet_type == "STRUCTURAL")
                .order_by(Sheet.created_at)
            )
            for level, floor in floors.items()
        }
        existing = {
            item.ifc_global_id: item
            for item in db.scalars(
                select(StructuralElement).where(StructuralElement.project_id == project_id)
            )
        }
        for item in existing.values():
            item.is_active = False
        for sheet in sheets.values():
            if sheet is not None:
                for segment in db.scalars(select(BeamSegment).where(BeamSegment.sheet_id == sheet.id)):
                    segment.is_active = False

        counts: dict[str, int] = {}
        floor_counts: dict[str, dict[str, int]] = {}
        for raw in data["elements"]:
            kind = _kind(raw)
            if kind is None:
                continue
            level = _level(raw, kind)
            floor = floors.get(level) if level is not None else None
            if floor is None:
                continue
            sheet = sheets.get(level)
            geometry = raw["plan_geometry"]
            line = [_normalized(point) for point in geometry["line"]]
            footprint = [_normalized(point) for point in geometry["footprint"]]
            normalized_geometry = {"line": line, "footprint": footprint}
            if kind == "COLUMN":
                normalized_geometry = align_column_geometry_to_reviewed_plan(
                    normalized_geometry
                )
            global_id = str(raw["global_id"])
            code = f"{_short_name(raw)} · {global_id[-6:]}"
            element = existing.get(global_id)
            if element is None:
                element = StructuralElement(project_id=project_id, ifc_global_id=global_id)
                db.add(element)
            element.floor_id = floor.id
            element.sheet_id = sheet.id if sheet else None
            element.ifc_type = str(raw["ifc_type"])
            element.ifc_storey = str(raw.get("storey") or "") or None
            element.element_kind = kind
            element.code = code
            element.name = str(raw.get("name") or "") or None
            element.geometry_json = normalized_geometry
            element.source = "IFC_PLAN_ALIGNED"
            element.is_active = True
            counts[kind] = counts.get(kind, 0) + 1
            per_floor = floor_counts.setdefault(str(level), {})
            per_floor[kind] = per_floor.get(kind, 0) + 1

            if kind == "BEAM" and sheet is not None:
                segment = db.scalar(
                    select(BeamSegment).where(
                        BeamSegment.sheet_id == sheet.id,
                        BeamSegment.code == code,
                    )
                )
                if segment is None:
                    segment = BeamSegment(sheet_id=sheet.id, code=code)
                    db.add(segment)
                world_line = raw["plan_geometry"]["line"]
                dx = float(world_line[1][0]) - float(world_line[0][0])
                dy = float(world_line[1][1]) - float(world_line[0][1])
                snapped_line, measured_length = snap_beam_line_to_plan_grid(
                    line, math.hypot(dx, dy)
                )
                element.geometry_json = {**normalized_geometry, "line": snapped_line}
                segment.beam_type = _short_name(raw)
                segment.start_x, segment.start_y = snapped_line[0]
                segment.end_x, segment.end_y = snapped_line[1]
                segment.length_m = round(measured_length, 3)
                segment.source = "IFC_PLAN_ALIGNED"
                segment.is_active = True

        # Floor slabs are documented as PC/S/GS zones on the structural
        # sheets but are not exported as physical IfcSlab products in this
        # Revit IFC. Keep the reviewed building footprint as plan zones:
        # A-B/2-6 and B-D/1-6. ST-03 additionally splits the ramp-side bays
        # and the 1.80 m-deep panels below grid D at their drawn beam lines.
        for level in range(1, 5):
            floor = floors.get(level)
            sheet = sheets.get(level)
            if floor is None:
                continue
            for zone in reviewed_slab_zones(level):
                bay = str(zone["label"])
                global_id = f"PLAN-SLAB-L{level}-{zone['id']}"
                element = existing.get(global_id)
                if element is None:
                    element = StructuralElement(project_id=project_id, ifc_global_id=global_id)
                    db.add(element)
                element.floor_id = floor.id
                element.sheet_id = sheet.id if sheet else None
                element.ifc_type = "PLAN_GRID_ZONE"
                element.ifc_storey = f"PLAN LEVEL {level}"
                element.element_kind = "SLAB"
                element.code = f"พื้นที่ {bay}"
                element.name = f"พื้นที่พื้นตามกริด {bay}"
                element.geometry_json = reviewed_slab_geometry(level, zone)
                element.source = "PLAN_GRID"
                element.is_active = True
                counts["SLAB"] = counts.get("SLAB", 0) + 1
                per_floor = floor_counts.setdefault(str(level), {})
                per_floor["SLAB"] = per_floor.get("SLAB", 0) + 1

        db.commit()
        return {"counts": counts, "floors": floor_counts}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_id", type=uuid.UUID)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    print(json.dumps(import_elements(args.project_id, args.source), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
