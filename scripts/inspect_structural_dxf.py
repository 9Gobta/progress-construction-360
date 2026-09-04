"""Inspect layers, layouts and structural sheet anchors in an AutoCAD DXF."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import ezdxf
from ezdxf import bbox


def _text(entity: object) -> str:
    entity_type = entity.dxftype()
    if entity_type == "TEXT":
        return entity.dxf.text
    if entity_type == "MTEXT":
        return entity.plain_text()
    if entity_type == "ATTRIB":
        return entity.dxf.text
    return ""


def inspect(source: Path) -> dict[str, object]:
    document = ezdxf.readfile(source)
    modelspace = document.modelspace()
    type_counts: Counter[str] = Counter()
    layer_counts: Counter[str] = Counter()
    layer_types: dict[str, Counter[str]] = {}
    sheet_anchors: list[dict[str, object]] = []
    beam_labels: list[dict[str, object]] = []
    beam_label_points: list[tuple[float, float, str]] = []

    for entity in modelspace:
        entity_type = entity.dxftype()
        layer = entity.dxf.layer
        type_counts[entity_type] += 1
        layer_counts[layer] += 1
        layer_types.setdefault(layer, Counter())[entity_type] += 1
        value = _text(entity).strip()
        if not value:
            continue
        upper = value.upper().replace(" ", "")
        point = getattr(entity.dxf, "insert", None)
        record = {
            "text": value[:240],
            "layer": layer,
            "insert": [round(float(point.x), 4), round(float(point.y), 4)] if point else None,
        }
        if any(token in upper for token in ("ST-03", "ST-04", "ST-05", "ST-06", "ST03", "ST04", "ST05", "ST06")):
            sheet_anchors.append(record)
        if upper in {"B1", "B2", "B3", "B4", "B5", "B6", "CB1", "CB2", "CB3", "CB4", "CB5", "CB6"}:
            beam_labels.append(record)
            if point:
                beam_label_points.append((float(point.x), float(point.y), upper))

    extent = bbox.extents(modelspace, fast=True)
    layouts = []
    for layout in document.layouts:
        counts = Counter(entity.dxftype() for entity in layout)
        layouts.append({"name": layout.name, "entities": len(layout), "types": dict(counts.most_common(12))})

    return {
        "source": str(source),
        "dxf_version": document.dxfversion,
        "units": int(document.units),
        "modelspace_entities": len(modelspace),
        "modelspace_extents": {
            "min": [extent.extmin.x, extent.extmin.y],
            "max": [extent.extmax.x, extent.extmax.y],
        },
        "entity_types": dict(type_counts.most_common()),
        "layers": [
            {
                "name": name,
                "count": count,
                "types": dict(layer_types[name].most_common(10)),
            }
            for name, count in layer_counts.most_common()
        ],
        "layouts": layouts,
        "sheet_anchors": sheet_anchors,
        "beam_label_count": len(beam_labels),
        "beam_label_bounds": {
            "min": [min(item[0] for item in beam_label_points), min(item[1] for item in beam_label_points)],
            "max": [max(item[0] for item in beam_label_points), max(item[1] for item in beam_label_points)],
        } if beam_label_points else None,
        "beam_label_types": dict(Counter(item[2] for item in beam_label_points).most_common()),
        "beam_label_histogram_x": dict(
            Counter(round(item[0] / 5) * 5 for item in beam_label_points).most_common()
        ),
        "beam_label_histogram_y": dict(
            Counter(round(item[1] / 5) * 5 for item in beam_label_points).most_common()
        ),
        "beam_labels_sample": beam_labels[:100],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = inspect(args.source)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
