"""Generate evidence-first comparisons for beam-to-plan alignment methods.

This tool never writes progress data.  It renders independent proposals so a
reviewer can compare raw IFC projection, the legacy grid snap, raster line
detection, vector-PDF extraction, an explicit reviewed-grid inventory, and a
hybrid consensus.  Low-confidence proposals remain visibly unverified.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pymupdf


@dataclass(frozen=True)
class Line:
    x1: float
    y1: float
    x2: float
    y2: float
    label: str = ""
    confidence: float = 0.0

    @property
    def length(self) -> float:
        return math.hypot(self.x2 - self.x1, self.y2 - self.y1)

    @property
    def horizontal(self) -> bool:
        return abs(self.x2 - self.x1) >= abs(self.y2 - self.y1)

    def normalized(self) -> Line:
        if (self.horizontal and self.x1 > self.x2) or (not self.horizontal and self.y1 > self.y2):
            return Line(self.x2, self.y2, self.x1, self.y1, self.label, self.confidence)
        return self


GRID_X = (0.1998, 0.2889, 0.3783, 0.4674, 0.5570, 0.6487)
GRID_Y = (0.2729, 0.4075, 0.4715, 0.6057)
GRID_LABEL_X = ("1", "2", "3", "4", "5", "6")
GRID_LABEL_Y = ("A", "B", "C", "D")


def _db_lines(db_path: Path, level: int) -> list[Line]:
    if not db_path.exists():
        return []
    query = """
        SELECT se.code, se.geometry_json
        FROM structural_elements se
        JOIN floors f ON f.id = se.floor_id
        WHERE f.level_index = ? AND se.element_kind = 'BEAM' AND se.is_active = 1
        ORDER BY se.code
    """
    result: list[Line] = []
    with sqlite3.connect(db_path) as db:
        for code, geometry_json in db.execute(query, (level,)):
            geometry = json.loads(geometry_json or "{}")
            points = geometry.get("line") or []
            if len(points) != 2:
                continue
            result.append(Line(*points[0], *points[1], label=code, confidence=0.35))
    return result


def _render_pdf_page(pdf_path: Path, page_index: int, width: int) -> tuple[np.ndarray, float, float]:
    document = pymupdf.open(pdf_path)
    page = document[page_index]
    scale = width / page.rect.width
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, 3)
    return cv2.cvtColor(image, cv2.COLOR_RGB2BGR), page.rect.width, page.rect.height


def _merge_axis_lines(lines: Iterable[Line], axis_tolerance: float, gap_tolerance: float) -> list[Line]:
    groups: dict[tuple[bool, int], list[Line]] = defaultdict(list)
    for raw in lines:
        line = raw.normalized()
        axis = (line.y1 + line.y2) / 2 if line.horizontal else (line.x1 + line.x2) / 2
        groups[(line.horizontal, round(axis / axis_tolerance))].append(line)

    merged: list[Line] = []
    for (horizontal, _), group in groups.items():
        axis = float(np.median([(item.y1 + item.y2) / 2 if horizontal else (item.x1 + item.x2) / 2 for item in group]))
        intervals = sorted(
            ((min(item.x1, item.x2), max(item.x1, item.x2)) if horizontal else (min(item.y1, item.y2), max(item.y1, item.y2)))
            for item in group
        )
        start, end = intervals[0]
        for next_start, next_end in intervals[1:]:
            if next_start <= end + gap_tolerance:
                end = max(end, next_end)
            else:
                merged.append(Line(start, axis, end, axis) if horizontal else Line(axis, start, axis, end))
                start, end = next_start, next_end
        merged.append(Line(start, axis, end, axis) if horizontal else Line(axis, start, axis, end))
    return merged


def _vector_candidates(pdf_path: Path, page_index: int) -> list[Line]:
    page = pymupdf.open(pdf_path)[page_index]
    candidates: list[Line] = []
    for drawing in page.get_drawings():
        if drawing.get("dashes") not in {"[] 0", None}:
            continue
        for item in drawing["items"]:
            if item[0] != "l":
                continue
            p1, p2 = item[1], item[2]
            dx, dy = abs(p2.x - p1.x), abs(p2.y - p1.y)
            if max(dx, dy) < 14 or min(dx, dy) > 0.75:
                continue
            line = Line(p1.x / page.rect.width, p1.y / page.rect.height, p2.x / page.rect.width, p2.y / page.rect.height)
            center_x = (line.x1 + line.x2) / 2
            center_y = (line.y1 + line.y2) / 2
            if 0.18 <= center_x <= 0.67 and 0.24 <= center_y <= 0.65:
                candidates.append(line)
    merged = _merge_axis_lines(candidates, axis_tolerance=0.0025, gap_tolerance=0.006)
    return [Line(item.x1, item.y1, item.x2, item.y2, confidence=0.62) for item in merged if item.length >= 0.022]


def _raster_candidates(image: np.ndarray) -> list[Line]:
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 70, 170, apertureSize=3)
    raw = cv2.HoughLinesP(edges, 1, np.pi / 1800, threshold=45, minLineLength=32, maxLineGap=12)
    candidates: list[Line] = []
    if raw is None:
        return candidates
    for x1, y1, x2, y2 in raw[:, 0]:
        dx, dy = abs(x2 - x1), abs(y2 - y1)
        if min(dx, dy) > 3 or max(dx, dy) < 28:
            continue
        line = Line(x1 / width, y1 / height, x2 / width, y2 / height)
        center_x = (line.x1 + line.x2) / 2
        center_y = (line.y1 + line.y2) / 2
        if 0.18 <= center_x <= 0.67 and 0.24 <= center_y <= 0.65:
            candidates.append(line)
    merged = _merge_axis_lines(candidates, axis_tolerance=0.0035, gap_tolerance=0.012)
    return [Line(item.x1, item.y1, item.x2, item.y2, confidence=0.48) for item in merged if item.length >= 0.025]


def _reviewed_grid_inventory() -> list[Line]:
    """Explicit floor-1 interpretation used only as a reviewer comparison.

    It contains the principal grid beams visible on ST-03 and deliberately
    excludes secondary ramp/balcony members. It is not auto-approved data.
    """
    lines: list[Line] = []
    horizontal_spans = {
        "A": (1, 5),
        "B": (0, 5),
        "C": (0, 5),
        "D": (0, 5),
    }
    for row_index, label in enumerate(GRID_LABEL_Y):
        start, end = horizontal_spans[label]
        lines.append(
            Line(GRID_X[start], GRID_Y[row_index], GRID_X[end], GRID_Y[row_index], f"Grid {label}", 0.85)
        )
    vertical_spans = {
        "1": (1, 3),
        "2": (0, 3),
        "3": (0, 3),
        "4": (0, 3),
        "5": (0, 3),
        "6": (0, 3),
    }
    for column_index, label in enumerate(GRID_LABEL_X):
        start, end = vertical_spans[label]
        lines.append(
            Line(GRID_X[column_index], GRID_Y[start], GRID_X[column_index], GRID_Y[end], f"Grid {label}", 0.85)
        )
    return lines


def _line_distance(first: Line, second: Line) -> float:
    if first.horizontal != second.horizontal:
        return 10.0
    first = first.normalized()
    second = second.normalized()
    if first.horizontal:
        axis = abs((first.y1 + first.y2 - second.y1 - second.y2) / 2)
        endpoints = abs(first.x1 - second.x1) + abs(first.x2 - second.x2)
    else:
        axis = abs((first.x1 + first.x2 - second.x1 - second.x2) / 2)
        endpoints = abs(first.y1 - second.y1) + abs(first.y2 - second.y2)
    return axis * 3 + endpoints


def _hybrid_consensus(vector: list[Line], raster: list[Line], reviewed: list[Line]) -> list[Line]:
    result: list[Line] = []
    for target in reviewed:
        vector_score = min((_line_distance(target, item) for item in vector), default=10.0)
        raster_score = min((_line_distance(target, item) for item in raster), default=10.0)
        support = int(vector_score < 0.08) + int(raster_score < 0.10)
        confidence = 0.72 + support * 0.12
        result.append(Line(target.x1, target.y1, target.x2, target.y2, target.label, min(confidence, 0.96)))
    return result


def _crop(image: np.ndarray) -> tuple[np.ndarray, tuple[int, int]]:
    height, width = image.shape[:2]
    x1, y1, x2, y2 = int(width * 0.13), int(height * 0.12), int(width * 0.74), int(height * 0.72)
    return image[y1:y2, x1:x2].copy(), (x1, y1)


def _draw_method(image: np.ndarray, lines: list[Line], title: str, color: tuple[int, int, int]) -> np.ndarray:
    canvas, offset = _crop(image)
    full_height, full_width = image.shape[:2]
    for line in lines:
        p1 = (round(line.x1 * full_width) - offset[0], round(line.y1 * full_height) - offset[1])
        p2 = (round(line.x2 * full_width) - offset[0], round(line.y2 * full_height) - offset[1])
        cv2.line(canvas, p1, p2, (255, 255, 255), 10, cv2.LINE_AA)
        cv2.line(canvas, p1, p2, color, 5, cv2.LINE_AA)
        cv2.circle(canvas, p1, 5, color, -1, cv2.LINE_AA)
        cv2.circle(canvas, p2, 5, color, -1, cv2.LINE_AA)
    cv2.rectangle(canvas, (0, 0), (canvas.shape[1], 70), (18, 25, 24), -1)
    cv2.putText(canvas, title, (22, 31), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(canvas, f"{len(lines)} lines", (22, 57), cv2.FONT_HERSHEY_SIMPLEX, 0.52, color, 2, cv2.LINE_AA)
    return canvas


def _contact_sheet(panels: list[np.ndarray]) -> np.ndarray:
    panel_height = min(panel.shape[0] for panel in panels)
    resized = [cv2.resize(panel, (round(panel.shape[1] * panel_height / panel.shape[0]), panel_height)) for panel in panels]
    columns = 2
    rows = math.ceil(len(resized) / columns)
    width = max(panel.shape[1] for panel in resized)
    sheet = np.full((rows * panel_height, columns * width, 3), 242, dtype=np.uint8)
    for index, panel in enumerate(resized):
        row, column = divmod(index, columns)
        sheet[row * panel_height : (row + 1) * panel_height, column * width : column * width + panel.shape[1]] = panel
    return sheet


def _serialize(lines: list[Line]) -> list[dict[str, object]]:
    return [
        {
            "start": [round(item.x1, 6), round(item.y1, 6)],
            "end": [round(item.x2, 6), round(item.y2, 6)],
            "label": item.label,
            "confidence": round(item.confidence, 3),
        }
        for item in lines
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", type=Path, default=Path("Data/A-โครงสร้าง 11668.pdf"))
    parser.add_argument("--page", type=int, default=3, help="One-based PDF page number")
    parser.add_argument("--level", type=int, default=1)
    parser.add_argument("--live-db", type=Path, default=Path("progress-dev.db"))
    parser.add_argument(
        "--pre-snap-db",
        type=Path,
        default=Path("outputs/progress-dev-before-beam-grid-snap-20260831.db"),
    )
    parser.add_argument("--output", type=Path, default=Path("outputs/beam_alignment_methods"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    image, _, _ = _render_pdf_page(args.pdf, args.page - 1, width=1985)
    raw_ifc = _db_lines(args.pre_snap_db, args.level)
    legacy_snap = _db_lines(args.live_db, args.level)
    raster = _raster_candidates(image)
    vector = _vector_candidates(args.pdf, args.page - 1)
    reviewed = _reviewed_grid_inventory()
    hybrid = _hybrid_consensus(vector, raster, reviewed)

    methods = [
        ("01_raw_ifc", "1. Raw IFC affine projection", raw_ifc, (20, 120, 245)),
        ("02_legacy_snap", "2. Legacy grid snap (current)", legacy_snap, (40, 40, 220)),
        ("03_raster_hough", "3. Raster Hough/LSD proposal", raster, (190, 50, 190)),
        ("04_vector_pdf", "4. Vector PDF extraction", vector, (220, 140, 30)),
        ("05_reviewed_grid", "5. Reviewed grid inventory", reviewed, (40, 175, 80)),
        ("06_hybrid", "6. Hybrid consensus", hybrid, (10, 145, 105)),
    ]
    panels: list[np.ndarray] = []
    payload: dict[str, object] = {
        "source_pdf": str(args.pdf),
        "page": args.page,
        "level": args.level,
        "warning": "Proposals are not approved progress geometry.",
        "methods": {},
    }
    for key, title, lines, color in methods:
        panel = _draw_method(image, lines, title, color)
        panels.append(panel)
        cv2.imwrite(str(args.output / f"{key}.png"), panel)
        payload["methods"][key] = {"title": title, "count": len(lines), "lines": _serialize(lines)}

    contact = _contact_sheet(panels)
    cv2.imwrite(str(args.output / "comparison.png"), contact)
    (args.output / "methods.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    cards = "\n".join(
        f'<figure><img src="{key}.png" alt="{html.escape(title)}"><figcaption>{html.escape(title)} — {len(lines)} lines</figcaption></figure>'
        for key, title, lines, _ in methods
    )
    report = f"""<!doctype html><html lang=\"th\"><meta charset=\"utf-8\"><title>Beam alignment methods</title>
<style>body{{font:16px system-ui;margin:24px;background:#eef2f0;color:#10231d}}h1{{margin-bottom:4px}}.note{{padding:14px;background:#fff3cd;border-radius:10px}}main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(520px,1fr));gap:18px}}figure{{margin:0;background:white;padding:12px;border-radius:12px;box-shadow:0 4px 18px #0001}}img{{width:100%;display:block}}figcaption{{font-weight:700;padding-top:10px}}</style>
<h1>เปรียบเทียบวิธีจับคานกับแบบ ST-03</h1><p class=\"note\">ทุกเส้นเป็นข้อเสนอทดลอง ยังไม่ถูกบันทึกเป็น Progress จริง วิธีที่ 1–4 เป็นอัตโนมัติ วิธีที่ 5 มีผู้ตรวจทาน และวิธีที่ 6 รวมหลักฐานหลายแหล่ง</p><main>{cards}</main></html>"""
    (args.output / "report.html").write_text(report, encoding="utf-8")
    print(json.dumps({"output": str(args.output), "counts": {key: len(lines) for key, _, lines, _ in methods}}, indent=2))


if __name__ == "__main__":
    main()
