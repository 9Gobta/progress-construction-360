"""Fit plan alignment from development Ground Truth only."""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from progress_api.db import SessionLocal
from progress_api.models import Capture
from progress_api.services.development_training import (
    calibrate_development_capture_from_ground_truth,
)


def main() -> None:
    with SessionLocal() as db:
        captures = list(
            db.scalars(
                select(Capture)
                .where(Capture.dataset_split == "DEVELOPMENT")
                .order_by(Capture.captured_at)
            )
        )
        for capture in captures:
            try:
                result = calibrate_development_capture_from_ground_truth(db, capture)
            except ValueError as exc:
                print(f"SKIP {capture.captured_at.date()} {exc}")
                continue
            print(f"TRAINED {capture.captured_at.date()} {result}")


if __name__ == "__main__":
    main()
