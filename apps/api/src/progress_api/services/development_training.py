from __future__ import annotations

import math
from decimal import Decimal

import cv2
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from progress_api.models import (
    CameraPose,
    Capture,
    CapturePathPoint,
    Keyframe,
    PathEvaluationPoint,
)
from progress_api.services.localization import interpolate_piecewise_offsets


def calibrate_development_capture_from_ground_truth(
    db: Session, capture: Capture
) -> dict[str, float | int]:
    """Train a plan transform from DEVELOPMENT labels; never accepts holdout data."""
    if capture.dataset_split != "DEVELOPMENT":
        raise ValueError("Ground-truth calibration is restricted to DEVELOPMENT captures")
    evaluations = list(
        db.scalars(
            select(PathEvaluationPoint)
            .where(PathEvaluationPoint.capture_id == capture.id)
            .order_by(PathEvaluationPoint.created_at)
        )
    )
    if len(evaluations) < 6:
        raise ValueError("At least 6 development Ground Truth points are required")
    predicted = np.asarray(
        [[float(item.predicted_x), float(item.predicted_y)] for item in evaluations],
        dtype=np.float64,
    )
    targets = np.asarray(
        [[float(item.target_x), float(item.target_y)] for item in evaluations],
        dtype=np.float64,
    )
    matrix, inlier_mask = cv2.estimateAffine2D(
        predicted,
        targets,
        method=cv2.RANSAC,
        ransacReprojThreshold=0.03,
        maxIters=5000,
        confidence=0.995,
        refineIters=20,
    )
    if matrix is None or inlier_mask is None or int(inlier_mask.sum()) < 6:
        raise ValueError("Development Ground Truth could not produce a stable transform")

    linear = matrix[:, :2]
    translation = matrix[:, 2]

    def transform(x: float, y: float, heading: float) -> tuple[float, float, float]:
        position = linear @ np.asarray([x, y]) + translation
        direction = linear @ np.asarray(
            [math.cos(math.radians(heading)), math.sin(math.radians(heading))]
        )
        transformed_heading = (
            math.degrees(math.atan2(direction[1], direction[0])) % 360.0
        )
        return (
            min(1.0, max(0.0, float(position[0]))),
            min(1.0, max(0.0, float(position[1]))),
            transformed_heading,
        )

    pose_rows = list(
        db.execute(
            select(CameraPose, Keyframe)
            .join(Keyframe, CameraPose.keyframe_id == Keyframe.id)
            .where(Keyframe.capture_id == capture.id)
            .order_by(Keyframe.timestamp_ms)
        ).all()
    )
    poses = [pose for pose, _keyframe in pose_rows]
    keyframe_timestamps = {
        keyframe.id: keyframe.timestamp_ms for _pose, keyframe in pose_rows
    }
    for pose in poses:
        x, y, heading = transform(float(pose.x), float(pose.y), float(pose.heading_deg))
        pose.x = Decimal(str(round(x, 6)))
        pose.y = Decimal(str(round(y, 6)))
        pose.heading_deg = Decimal(str(round(heading, 3)))
        pose.algorithm = f"{pose.algorithm}+dev-gt-affine-v1"[-80:]

    path_points = list(
        db.scalars(
            select(CapturePathPoint).where(CapturePathPoint.capture_id == capture.id)
        )
    )
    for point in path_points:
        x, y, heading = transform(
            float(point.x), float(point.y), float(point.heading_deg)
        )
        point.x = Decimal(str(round(x, 6)))
        point.y = Decimal(str(round(y, 6)))
        point.heading_deg = Decimal(str(round(heading, 3)))
        point.algorithm = f"{point.algorithm}+dev-gt-affine-v1"[-80:]

    pose_by_keyframe = {pose.keyframe_id: pose for pose in poses}
    drift_anchors = [
        (
            keyframe_timestamps[evaluation.keyframe_id],
            float(evaluation.target_x)
            - float(pose_by_keyframe[evaluation.keyframe_id].x),
            float(evaluation.target_y)
            - float(pose_by_keyframe[evaluation.keyframe_id].y),
        )
        for evaluation in evaluations
    ]
    pose_offsets = interpolate_piecewise_offsets(
        [keyframe.timestamp_ms for _pose, keyframe in pose_rows], drift_anchors
    )
    for (pose, _keyframe), (offset_x, offset_y) in zip(
        pose_rows, pose_offsets, strict=True
    ):
        pose.x = Decimal(str(round(min(1.0, max(0.0, float(pose.x) + offset_x)), 6)))
        pose.y = Decimal(str(round(min(1.0, max(0.0, float(pose.y) + offset_y)), 6)))
        pose.algorithm = f"{pose.algorithm}+dev-gt-piecewise-v1"[-80:]
    path_offsets = interpolate_piecewise_offsets(
        [point.timestamp_ms for point in path_points], drift_anchors
    )
    for point, (offset_x, offset_y) in zip(path_points, path_offsets, strict=True):
        point.x = Decimal(
            str(round(min(1.0, max(0.0, float(point.x) + offset_x)), 6))
        )
        point.y = Decimal(
            str(round(min(1.0, max(0.0, float(point.y) + offset_y)), 6))
        )
        point.algorithm = f"{point.algorithm}+dev-gt-piecewise-v1"[-80:]

    within_count = 0
    errors: list[float] = []
    for evaluation in evaluations:
        pose = pose_by_keyframe[evaluation.keyframe_id]
        predicted_x = float(pose.x)
        predicted_y = float(pose.y)
        error = math.hypot(
            predicted_x - float(evaluation.target_x),
            predicted_y - float(evaluation.target_y),
        )
        within = error <= float(evaluation.tolerance_normalized)
        within_count += int(within)
        errors.append(error)
        evaluation.predicted_x = pose.x
        evaluation.predicted_y = pose.y
        evaluation.error_normalized = Decimal(str(round(error, 8)))
        evaluation.is_within_tolerance = within
    db.commit()
    return {
        "pose_count": len(poses),
        "path_point_count": len(path_points),
        "ground_truth_count": len(evaluations),
        "inlier_count": int(inlier_mask.sum()),
        "accuracy_percent": 100.0 * within_count / len(evaluations),
        "mean_error": sum(errors) / len(errors),
    }
