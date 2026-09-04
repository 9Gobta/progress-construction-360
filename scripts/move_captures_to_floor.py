"""Move captures and all capture-scoped localization rows to one floor.

This preserves route geometry and only changes the floor association.
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("progress-dev.db"))
    parser.add_argument("--floor-id", required=True)
    parser.add_argument("capture_ids", nargs="+")
    return parser.parse_args()


def compact_uuid(value: str) -> str:
    return value.replace("-", "").lower()


def main() -> None:
    args = parse_args()
    floor_id = compact_uuid(args.floor_id)
    capture_ids = [compact_uuid(value) for value in args.capture_ids]
    placeholders = ",".join("?" for _ in capture_ids)
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="microseconds")

    connection = sqlite3.connect(args.database, timeout=60)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        floor = connection.execute(
            "SELECT project_id, name, level_index FROM floors WHERE id = ?", (floor_id,)
        ).fetchone()
        if floor is None:
            raise SystemExit(f"Unknown floor: {floor_id}")

        captures = connection.execute(
            f"SELECT id, project_id, captured_at, start_floor_id FROM captures WHERE id IN ({placeholders})",
            capture_ids,
        ).fetchall()
        found = {row[0] for row in captures}
        missing = sorted(set(capture_ids) - found)
        if missing:
            raise SystemExit(f"Unknown captures: {', '.join(missing)}")
        wrong_project = [row[0] for row in captures if row[1] != floor[0]]
        if wrong_project:
            raise SystemExit(f"Captures are in another project: {', '.join(wrong_project)}")

        with connection:
            connection.execute(
                f"UPDATE captures SET start_floor_id = ?, updated_at = ? WHERE id IN ({placeholders})",
                [floor_id, now, *capture_ids],
            )
            connection.execute(
                f"""
                UPDATE camera_poses
                SET floor_id = ?, updated_at = ?
                WHERE keyframe_id IN (
                    SELECT id FROM keyframes WHERE capture_id IN ({placeholders})
                )
                """,
                [floor_id, now, *capture_ids],
            )
            for table in ("capture_path_points", "path_control_points", "path_evaluation_points"):
                connection.execute(
                    f"UPDATE {table} SET floor_id = ? WHERE capture_id IN ({placeholders})",
                    [floor_id, *capture_ids],
                )

        print(f"Moved {len(captures)} captures to {floor[1]} (level {floor[2]}):")
        for capture in sorted(captures, key=lambda row: row[2]):
            print(f"- {capture[2]} {capture[0]}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
