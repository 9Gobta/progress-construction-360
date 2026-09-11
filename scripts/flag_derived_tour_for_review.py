"""Put a derived Virtual Tour back into an explicit human-review state.

This never changes the protected 20 December 2025 reference capture, camera
coordinates, warp stations, route history, or a previous reviewer identity.
It only adds a quality hold when an audit finds that a later capture's route
was derived from a plan constraint and must be checked again against its own
360 evidence.
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from progress_api.db import SessionLocal
from progress_api.models import CameraPose, Capture, Keyframe
from sqlalchemy import select

PROTECTED_REFERENCE_CAPTURE_ID = uuid.UUID("b78c9804-76c2-4e96-93d4-53cf55ffba3f")


def flag_for_review(
    capture_id: uuid.UUID,
    *,
    apply: bool,
    backup_root: Path,
) -> dict[str, object]:
    if capture_id == PROTECTED_REFERENCE_CAPTURE_ID:
        raise RuntimeError("The approved 20/12/2568 reference capture is protected")

    with SessionLocal() as db:
        capture = db.get(Capture, capture_id)
        if capture is None:
            raise RuntimeError("Capture not found")
        rows = list(
            db.execute(
                select(Keyframe, CameraPose)
                .join(CameraPose, CameraPose.keyframe_id == Keyframe.id)
                .where(Keyframe.capture_id == capture_id)
                .order_by(Keyframe.timestamp_ms)
            ).all()
        )
        if not rows:
            raise RuntimeError("Capture has no camera poses")
        derived = [
            pose for _keyframe, pose in rows
            if "plan-route-constrained-v1" in (pose.algorithm or "")
        ]
        if not derived:
            raise RuntimeError("Capture is not marked as a plan-derived route")

        held_before = sum(bool(pose.needs_review) for _keyframe, pose in rows)
        if apply:
            backup_root.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_path = backup_root / f"{capture_id}-before-derived-route-review-{stamp}.json"
            backup_path.write_text(
                json.dumps(
                    {
                        "capture_id": str(capture_id),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "capture_status": capture.status,
                        "poses": [
                            {
                                "keyframe_id": str(keyframe.id),
                                "needs_review": pose.needs_review,
                                "reviewed_by_id": str(pose.reviewed_by_id) if pose.reviewed_by_id else None,
                                "reviewed_at": pose.reviewed_at.isoformat() if pose.reviewed_at else None,
                                "algorithm": pose.algorithm,
                            }
                            for keyframe, pose in rows
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            for _keyframe, pose in rows:
                # Keep the original reviewer and timestamp for auditability.
                # A new human review can later clear this quality hold through
                # the ordinary path-alignment workflow.
                pose.needs_review = True
            capture.status = "REVIEW_REQUIRED"
            db.commit()
        return {
            "capture_id": str(capture_id),
            "pose_count": len(rows),
            "derived_pose_count": len(derived),
            "held_before": held_before,
            "applied": apply,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture_id", type=uuid.UUID)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--backup-root",
        type=Path,
        default=Path(".codex_tmp/derived-tour-review-backups"),
    )
    args = parser.parse_args()
    print(json.dumps(flag_for_review(args.capture_id, apply=args.apply, backup_root=args.backup_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
