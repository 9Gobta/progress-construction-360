"""Extract structural element extents from an IFC model.

The output is intentionally plain JSON so it can be reviewed before any
database import. Geometry uses world coordinates and retains IFC GlobalIds.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
from collections import Counter
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import numpy as np

IFC_TYPES = (
    "IfcBeam",
    "IfcColumn",
    "IfcSlab",
    "IfcStair",
    "IfcStairFlight",
    "IfcFooting",
    "IfcPile",
)


def _plan_geometry(vertices: np.ndarray) -> dict[str, object]:
    """Return a compact 2D footprint and principal centreline.

    IFC tessellation repeats vertices for triangle faces.  PCA is stable for
    both axis-aligned and rotated framing and avoids guessing a member's
    direction from its world-axis bounding box.
    """
    points = np.unique(vertices[:, :2].round(6), axis=0)
    center = points.mean(axis=0)
    centered = points - center
    covariance = centered.T @ centered
    values, vectors = np.linalg.eigh(covariance)
    direction = vectors[:, int(np.argmax(values))]
    projection = centered @ direction
    line_start = center + direction * float(projection.min())
    line_end = center + direction * float(projection.max())

    # A monotonic-chain hull keeps the output dependency-free and small.
    ordered = sorted({(float(x), float(y)) for x, y in points})

    def cross(origin: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - origin[0]) * (b[1] - origin[1]) - (a[1] - origin[1]) * (b[0] - origin[0])

    lower: list[tuple[float, float]] = []
    for point in ordered:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(ordered):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    hull = lower[:-1] + upper[:-1] if len(ordered) > 2 else ordered
    return {
        "line": [line_start.round(6).tolist(), line_end.round(6).tolist()],
        "footprint": [[round(x, 6), round(y, 6)] for x, y in hull],
    }


def _storey_name(element: object) -> str | None:
    container = ifcopenshell.util.element.get_container(element)
    while container is not None:
        if container.is_a("IfcBuildingStorey"):
            return container.Name or container.LongName
        container = ifcopenshell.util.element.get_container(container)
    return None


def extract(source: Path) -> dict[str, object]:
    model = ifcopenshell.open(str(source))
    included = [element for ifc_type in IFC_TYPES for element in model.by_type(ifc_type)]
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    iterator = ifcopenshell.geom.iterator(
        settings,
        model,
        max(1, min(4, multiprocessing.cpu_count())),
        include=included,
    )
    elements: list[dict[str, object]] = []
    if iterator.initialize():
        while True:
            shape = iterator.get()
            element = model.by_id(shape.id)
            vertices = np.asarray(shape.geometry.verts, dtype=float).reshape((-1, 3))
            minimum = vertices.min(axis=0)
            maximum = vertices.max(axis=0)
            plan_geometry = _plan_geometry(vertices)
            elements.append(
                {
                    "step_id": element.id(),
                    "global_id": element.GlobalId,
                    "ifc_type": element.is_a(),
                    "name": element.Name,
                    "object_type": getattr(element, "ObjectType", None),
                    "predefined_type": str(getattr(element, "PredefinedType", None) or ""),
                    "storey": _storey_name(element),
                    "bounds": {
                        "min": minimum.round(6).tolist(),
                        "max": maximum.round(6).tolist(),
                    },
                    "centroid": ((minimum + maximum) / 2).round(6).tolist(),
                    "plan_geometry": plan_geometry,
                }
            )
            if not iterator.next():
                break
    return {
        "source": source.name,
        "schema": model.schema,
        "counts": dict(Counter(item["ifc_type"] for item in elements)),
        "storeys": dict(Counter(item["storey"] or "UNASSIGNED" for item in elements)),
        "elements": elements,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = extract(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"counts": result["counts"], "storeys": result["storeys"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
