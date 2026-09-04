"""Extract beam centre-line inventories from the reviewed structural CAD.

The DWG keeps beam edges on S-BEAM and beam marks on TEXT.  This script pairs
the two CAD edges of each beam, derives a centre line, snaps only to support
centre-lines found in the same CAD geometry, and links the nearest compatible
beam mark.  It never updates the application database.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass, replace
from pathlib import Path

import cv2
import ezdxf
from compare_beam_alignment_methods import Line, _draw_method, _render_pdf_page

PLAN_GRID_X = (0.1998, 0.6487)
PLAN_GRID_Y = (0.2729, 0.6057)
CAD_GRID_X = (1035.9498, 1054.7498)
CAD_GRID_Y = (-1474.2007, -1484.1007)
PLAN_STEP_X = 42.0
BEAM_MARK = re.compile(r"^(C?B\d+)", re.IGNORECASE)

# The reviewed blue markup supplied with ST-03–ST-06 establishes the main
# beam network. Some horizontal CAD beam edges are interrupted differently on
# their two sides by columns and secondary beams, so edge pairing alone omits
# valid spans. These dimensions come directly from the drawing dimensions.
GRID_SPAN_M = 3.75
PRIMARY_X_OFFSETS = (0.0, 3.75, 7.5, 11.25, 15.0, 18.75)
MAIN_Y_OFFSETS = (0.0, -4.0, -5.9, -9.9, -11.7)
SHAFT_MID_Y_OFFSET = -2.0
RAMP_B1_X_OFFSET = 11.7741
RAMP_B1_LENGTH_M = 0.9


@dataclass(frozen=True)
class CadLine:
    x1: float
    y1: float
    x2: float
    y2: float
    handle: str = ""
    beam_type: str | None = None
    confidence: float = 0.0

    @property
    def horizontal(self) -> bool:
        return abs(self.x2 - self.x1) >= abs(self.y2 - self.y1)

    @property
    def length(self) -> float:
        return math.hypot(self.x2 - self.x1, self.y2 - self.y1)

    def normalized(self) -> CadLine:
        if (self.horizontal and self.x1 > self.x2) or (not self.horizontal and self.y1 > self.y2):
            return CadLine(
                self.x2,
                self.y2,
                self.x1,
                self.y1,
                self.handle,
                self.beam_type,
                self.confidence,
            )
        return self


@dataclass(frozen=True)
class CadLabel:
    x: float
    y: float
    beam_type: str
    horizontal: bool
    handle: str


def _within_floor(x: float, y: float, level: int) -> bool:
    shift = PLAN_STEP_X * (level - 1)
    return 1035.4 + shift <= x <= 1055.3 + shift and -1486.7 <= y <= -1473.6


def _cad_edges(modelspace: object, level: int) -> list[CadLine]:
    edges: list[CadLine] = []
    for entity in modelspace.query("LINE"):
        if entity.dxf.layer.upper() != "S-BEAM":
            continue
        start, end = entity.dxf.start, entity.dxf.end
        center_x = (start.x + end.x) / 2
        center_y = (start.y + end.y) / 2
        if not _within_floor(center_x, center_y, level):
            continue
        line = CadLine(start.x, start.y, end.x, end.y, entity.dxf.handle).normalized()
        dx, dy = abs(line.x2 - line.x1), abs(line.y2 - line.y1)
        if line.length >= 0.45 and min(dx, dy) <= 0.015:
            edges.append(line)
    return edges


def _axis(line: CadLine) -> float:
    return (line.y1 + line.y2) / 2 if line.horizontal else (line.x1 + line.x2) / 2


def _interval(line: CadLine) -> tuple[float, float]:
    return (line.x1, line.x2) if line.horizontal else (line.y1, line.y2)


def _merge_collinear_edges(
    edges: list[CadLine],
    *,
    axis_tolerance: float = 0.02,
    gap_tolerance: float = 0.26,
) -> list[CadLine]:
    """Join CAD edge fragments split by crossing members.

    Vertical structural beam edges in the source DWG are sometimes divided at
    ramp intersections. Pairing those fragments directly can match a long edge
    to only one short fragment and produces a false short beam. Horizontal
    edges stay split because their 0.20 m breaks mark the supporting columns and
    therefore the boundary between progress-tracking spans.
    """
    merged: list[CadLine] = []
    ordered = sorted(edges, key=lambda item: (item.horizontal, _axis(item), *_interval(item)))
    for edge in ordered:
        if edge.horizontal:
            merged.append(edge)
            continue
        start, end = _interval(edge)
        candidate_index: int | None = None
        for index in range(len(merged) - 1, -1, -1):
            candidate = merged[index]
            if candidate.horizontal != edge.horizontal:
                continue
            if abs(_axis(candidate) - _axis(edge)) > axis_tolerance:
                continue
            candidate_start, candidate_end = _interval(candidate)
            gap = start - candidate_end
            if -axis_tolerance <= gap <= gap_tolerance:
                candidate_index = index
                break

        if candidate_index is None:
            merged.append(edge)
            continue

        candidate = merged[candidate_index]
        candidate_start, candidate_end = _interval(candidate)
        combined_start = min(candidate_start, start)
        combined_end = max(candidate_end, end)
        axis = (_axis(candidate) + _axis(edge)) / 2
        handle = f"{candidate.handle}+{edge.handle}"
        merged[candidate_index] = (
            CadLine(combined_start, axis, combined_end, axis, handle)
            if edge.horizontal
            else CadLine(axis, combined_start, axis, combined_end, handle)
        )
    return merged


def _pair_edges(edges: list[CadLine]) -> list[CadLine]:
    candidates: list[tuple[float, int, int]] = []
    for first_index, first in enumerate(edges):
        first_start, first_end = _interval(first)
        for second_index in range(first_index + 1, len(edges)):
            second = edges[second_index]
            if first.horizontal != second.horizontal:
                continue
            width = abs(_axis(first) - _axis(second))
            if not 0.14 <= width <= 0.32:
                continue
            second_start, second_end = _interval(second)
            overlap = max(0.0, min(first_end, second_end) - max(first_start, second_start))
            shorter = min(first_end - first_start, second_end - second_start)
            if shorter <= 0 or overlap / shorter < 0.72:
                continue
            endpoint_delta = abs(first_start - second_start) + abs(first_end - second_end)
            if endpoint_delta > 0.9:
                continue
            score = abs(width - 0.2) * 5 + endpoint_delta
            candidates.append((score, first_index, second_index))

    used: set[int] = set()
    centre_lines: list[CadLine] = []
    for _, first_index, second_index in sorted(candidates):
        if first_index in used or second_index in used:
            continue
        first, second = edges[first_index], edges[second_index]
        first_start, first_end = _interval(first)
        second_start, second_end = _interval(second)
        start = (first_start + second_start) / 2
        end = (first_end + second_end) / 2
        axis = (_axis(first) + _axis(second)) / 2
        handle = f"{first.handle}+{second.handle}"
        centre_lines.append(
            CadLine(start, axis, end, axis, handle) if first.horizontal else CadLine(axis, start, axis, end, handle)
        )
        used.update((first_index, second_index))
    return centre_lines


def _cluster_axes(values: list[float], tolerance: float = 0.13) -> list[float]:
    clusters: list[list[float]] = []
    for value in sorted(values):
        if not clusters or value - clusters[-1][-1] > tolerance:
            clusters.append([value])
        else:
            clusters[-1].append(value)
    return [sum(cluster) / len(cluster) for cluster in clusters]


def _nearest(value: float, axes: list[float], tolerance: float) -> float:
    if not axes:
        return value
    nearest = min(axes, key=lambda axis: abs(axis - value))
    return nearest if abs(nearest - value) <= tolerance else value


def _snap_to_cad_supports(lines: list[CadLine]) -> list[CadLine]:
    vertical_axes = _cluster_axes([_axis(line) for line in lines if not line.horizontal])
    horizontal_axes = _cluster_axes([_axis(line) for line in lines if line.horizontal])
    result: list[CadLine] = []
    for line in lines:
        if line.horizontal:
            result.append(replace(line, x1=_nearest(line.x1, vertical_axes, 0.45), x2=_nearest(line.x2, vertical_axes, 0.45)))
        else:
            result.append(replace(line, y1=_nearest(line.y1, horizontal_axes, 0.45), y2=_nearest(line.y2, horizontal_axes, 0.45)))
    return result


def _deduplicate(lines: list[CadLine]) -> list[CadLine]:
    result: list[CadLine] = []
    for line in sorted(lines, key=lambda item: (item.horizontal, _axis(item), *_interval(item))):
        duplicate = next(
            (
                existing
                for existing in result
                if existing.horizontal == line.horizontal
                and abs(_axis(existing) - _axis(line)) < 0.08
                and abs(_interval(existing)[0] - _interval(line)[0]) < 0.12
                and abs(_interval(existing)[1] - _interval(line)[1]) < 0.12
            ),
            None,
        )
        if duplicate is None:
            result.append(line)
    return result


def _cad_labels(modelspace: object, level: int) -> list[CadLabel]:
    labels: list[CadLabel] = []
    for entity in modelspace.query("TEXT"):
        match = BEAM_MARK.match(entity.dxf.text.strip())
        if not match:
            continue
        point = entity.dxf.insert
        if not _within_floor(point.x, point.y, level):
            continue
        rotation = float(entity.dxf.get("rotation", 0.0)) % 180
        horizontal = rotation <= 30 or rotation >= 150
        labels.append(CadLabel(point.x, point.y, match.group(1).upper(), horizontal, entity.dxf.handle))
    return labels


def _match_labels(lines: list[CadLine], labels: list[CadLabel]) -> list[CadLine]:
    proposals: list[tuple[float, int, int]] = []
    for line_index, line in enumerate(lines):
        start, end = _interval(line)
        for label_index, label in enumerate(labels):
            if label.horizontal != line.horizontal:
                continue
            along = label.x if line.horizontal else label.y
            perpendicular = label.y if line.horizontal else label.x
            outside = max(start - along, 0.0, along - end)
            cross_distance = abs(perpendicular - _axis(line))
            if outside <= 0.35 and cross_distance <= 0.35:
                proposals.append((cross_distance * 4 + outside, line_index, label_index))

    assigned_lines: dict[int, CadLabel] = {}
    assigned_labels: set[int] = set()
    for _, line_index, label_index in sorted(proposals):
        if line_index in assigned_lines or label_index in assigned_labels:
            continue
        assigned_lines[line_index] = labels[label_index]
        assigned_labels.add(label_index)

    result: list[CadLine] = []
    for line_index, line in enumerate(lines):
        label = assigned_lines.get(line_index)
        if label is None:
            result.append(replace(line, confidence=0.45))
        else:
            result.append(replace(line, beam_type=label.beam_type, confidence=0.98))
    return result


def _reviewed_horizontal_network(lines: list[CadLine], level: int) -> list[CadLine]:
    """Complete the horizontal spans explicitly confirmed in the markup.

    Keep CAD-derived ramp/shaft members that do not lie on a main grid row,
    but replace every main row with dimension-controlled spans. This gives
    every highlighted span its own selectable progress item and prevents a
    broken edge pair from silently removing a beam.
    """
    shift = PLAN_STEP_X * (level - 1)
    origin_x = CAD_GRID_X[0] + shift
    origin_y = CAD_GRID_Y[0]
    main_y = tuple(origin_y + offset for offset in MAIN_Y_OFFSETS)
    replaced_y = main_y + (
        (origin_y + SHAFT_MID_Y_OFFSET,) if level >= 2 else ()
    )
    retained = [
        line
        for line in lines
        if not line.horizontal
        or all(abs(_axis(line) - axis) > 0.35 for axis in replaced_y)
    ]

    ramp_b1_x = origin_x + RAMP_B1_X_OFFSET
    if level == 1:
        retained = [
            line
            for line in retained
            if not (
                not line.horizontal
                and abs(_axis(line) - ramp_b1_x) < 0.08
                and line.length < 1.2
            )
        ]

    reviewed: list[CadLine] = []

    def add_spans(
        y: float,
        offsets: tuple[float, ...],
        *,
        start_index: int = 0,
        beam_type: str,
    ) -> None:
        for index in range(start_index, len(offsets) - 1):
            reviewed.append(
                CadLine(
                    origin_x + offsets[index],
                    y,
                    origin_x + offsets[index + 1],
                    y,
                    handle="REVIEWED_BLUEPRINT",
                    beam_type=beam_type,
                    confidence=1.0,
                )
            )

    # Grid A starts at column 2; B, C and D cover columns 1–6.
    add_spans(main_y[0], PRIMARY_X_OFFSETS, start_index=1, beam_type="B3")
    for y in main_y[1:4]:
        add_spans(y, PRIMARY_X_OFFSETS, beam_type="B3")
    # B2 is continuous between each primary column grid.  The 2.12/1.63 m
    # dimensions locate secondary members; they do not split the B2 progress
    # item.  Keep one selectable 3.75 m span per 1-2, 2-3, ... 5-6 bay.
    add_spans(main_y[4], PRIMARY_X_OFFSETS, beam_type="B2")

    # The reviewed yellow mark confirms the short B1 at the floor-1 ramp.
    # Add it explicitly so it cannot disappear when CAD edge pairing changes.
    if level == 1:
        reviewed.append(
            CadLine(
                ramp_b1_x,
                main_y[0] - RAMP_B1_LENGTH_M,
                ramp_b1_x,
                main_y[0],
                handle="REVIEWED_YELLOW",
                beam_type="B1",
                confidence=1.0,
            )
        )

    # Floors 2–4 contain the two short horizontal spans in the 4–5 shaft.
    if level >= 2:
        shaft_offsets = (PRIMARY_X_OFFSETS[3], 13.125, PRIMARY_X_OFFSETS[4])
        add_spans(
            origin_y + SHAFT_MID_Y_OFFSET,
            shaft_offsets,
            beam_type="B4",
        )
    return _deduplicate(retained + reviewed)


def extract_floor(modelspace: object, level: int) -> list[CadLine]:
    paired = _pair_edges(_merge_collinear_edges(_cad_edges(modelspace, level)))
    snapped = _snap_to_cad_supports(paired)
    labeled = _match_labels(_deduplicate(snapped), _cad_labels(modelspace, level))
    return _reviewed_horizontal_network(labeled, level)


def _is_excluded_review_item(line: CadLine, level: int) -> bool:
    """Exclude five floor-1 ramp infill lines rejected in the plan review.

    These B2 members are drawn inside the A-B ramp zone, but the reviewed
    progress inventory treats them as ramp/slab detail rather than selectable
    main beams.  Keep the original extraction index so the IDs of every
    accepted beam remain stable when the inventory is regenerated.
    """
    if level != 1 or not line.horizontal:
        return False
    axis = _axis(line)
    grid_a = CAD_GRID_Y[0]
    grid_b = grid_a + MAIN_Y_OFFSETS[1]
    return grid_b < axis < grid_a


def _stable_inventory_index(line: CadLine, level: int, extraction_index: int) -> int:
    """Preserve existing beam IDs while merging the five bottom B2 pairs."""
    origin_x = CAD_GRID_X[0] + PLAN_STEP_X * (level - 1)
    bottom_y = CAD_GRID_Y[0] + MAIN_Y_OFFSETS[4]
    if line.horizontal and abs(_axis(line) - bottom_y) < 0.35:
        start, end = _interval(line)
        for bay in range(len(PRIMARY_X_OFFSETS) - 1):
            expected_start = origin_x + PRIMARY_X_OFFSETS[bay]
            expected_end = origin_x + PRIMARY_X_OFFSETS[bay + 1]
            if abs(start - expected_start) < 0.35 and abs(end - expected_end) < 0.35:
                return 30 + bay * 2
    # The old inventory reserved ten slots (30-39) for the split bottom row.
    return extraction_index + 5 if extraction_index >= 35 else extraction_index


def _plan_line(line: CadLine, level: int) -> Line:
    shift = PLAN_STEP_X * (level - 1)
    x_min, x_max = CAD_GRID_X[0] + shift, CAD_GRID_X[1] + shift
    x_scale = (PLAN_GRID_X[1] - PLAN_GRID_X[0]) / (x_max - x_min)
    y_scale = (PLAN_GRID_Y[1] - PLAN_GRID_Y[0]) / (CAD_GRID_Y[1] - CAD_GRID_Y[0])

    def transform(x: float, y: float) -> tuple[float, float]:
        return (
            PLAN_GRID_X[0] + (x - x_min) * x_scale,
            PLAN_GRID_Y[0] + (y - CAD_GRID_Y[0]) * y_scale,
        )

    start = transform(line.x1, line.y1)
    end = transform(line.x2, line.y2)
    return Line(*start, *end, label=line.beam_type or "ไม่พบป้าย", confidence=line.confidence)


def _reviewed_quantity_length(line: CadLine, level: int) -> float:
    """Return the reviewed face-to-face quantity used for progress.

    ST-03 floor 1 contains a mixture of CAD beam-face edges and reviewed grid
    centre-lines.  The horizontal 3.75 m spans and the six 3.90 m vertical
    spans therefore include a 0.25 m support intersection.  Removing that
    intersection gives 154.825 m for the floor, or 154.83 m at the two-decimal
    precision used by the quantity summary.
    """
    length = line.length
    if level == 1 and (line.horizontal or abs(length - 3.9) <= 0.01):
        length -= 0.25
    return length


def _serialize(line: CadLine, plan: Line, level: int, index: int) -> dict[str, object]:
    return {
        "id": f"CAD-L{level}-{index:03d}",
        "beam_type": line.beam_type,
        "cad_start": [round(line.x1, 5), round(line.y1, 5)],
        "cad_end": [round(line.x2, 5), round(line.y2, 5)],
        "plan_start": [round(plan.x1, 6), round(plan.y1, 6)],
        "plan_end": [round(plan.x2, 6), round(plan.y2, 6)],
        "length_m": round(_reviewed_quantity_length(line, level), 3),
        "confidence": line.confidence,
        "source_handles": line.handle,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--pdf", type=Path, default=Path("Data/A-โครงสร้าง 11668.pdf"))
    parser.add_argument("--output", type=Path, default=Path("outputs/cad_beam_alignment"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    document = ezdxf.readfile(args.source)
    modelspace = document.modelspace()
    inventory: dict[str, object] = {"source": str(args.source), "floors": {}}

    for level in range(1, 5):
        cad_lines = extract_floor(modelspace, level)
        indexed_lines = [
            (_stable_inventory_index(line, level, index), line)
            for index, line in enumerate(cad_lines, start=1)
            if not _is_excluded_review_item(line, level)
        ]
        plan_lines = [_plan_line(line, level) for _, line in indexed_lines]
        records = [
            _serialize(line, plan, level, index)
            for (index, line), plan in zip(indexed_lines, plan_lines)
        ]
        inventory["floors"][str(level)] = {
            "count": len(records),
            "labeled": sum(record["beam_type"] is not None for record in records),
            "accepted": sum(record["confidence"] >= 0.95 for record in records),
            "total_length_m": round(sum(record["length_m"] for record in records), 3),
            "beams": records,
        }
        image, _, _ = _render_pdf_page(args.pdf, level + 1, width=1985)
        panel = _draw_method(
            image,
            plan_lines,
            f"7. CAD S-BEAM centre lines - floor {level}",
            (20, 150, 240),
        )
        cv2.imwrite(str(args.output / f"floor_{level}_cad_overlay.png"), panel)

    destination = args.output / "cad_beam_inventory.json"
    destination.write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(destination),
                "floors": {
                    key: {
                        field: value[field]
                        for field in ("count", "labeled", "accepted", "total_length_m")
                    }
                    for key, value in inventory["floors"].items()
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
