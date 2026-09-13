from __future__ import annotations

import json
import math
import os
import pickle
import shutil
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from progress_api.config import get_settings


class LearnedRelocalizationUnavailable(RuntimeError):
    """The optional learned image-matching runtime is not ready."""


@dataclass(frozen=True)
class LearnedPlanAnchor:
    """A query panorama localized in a trusted multi-view 3-D reference map."""

    panorama_index: int
    plan_x: float
    plan_y: float
    inliers: int
    localized_faces: int


def _activate_runtime() -> None:
    settings = get_settings()
    candidates = [settings.hloc_python_path, settings.hloc_source_path]
    for candidate in reversed([item for item in candidates if item]):
        resolved = str(Path(candidate).resolve())
        if resolved not in sys.path:
            sys.path.insert(0, resolved)
    if settings.hloc_torch_home:
        os.environ.setdefault("TORCH_HOME", str(Path(settings.hloc_torch_home).resolve()))
    try:
        import hloc  # noqa: F401
        import lightglue  # noqa: F401
    except Exception as exc:  # pragma: no cover - depends on optional runtime
        raise LearnedRelocalizationUnavailable(str(exc)) from exc


def runtime_status() -> tuple[bool, str]:
    try:
        _activate_runtime()
    except LearnedRelocalizationUnavailable as exc:
        return False, str(exc)
    return True, "HLoc + DISK + LightGlue ready"


def _perspective_map(
    panorama_width: int,
    panorama_height: int,
    *,
    yaw_deg: float,
    size: int = 512,
    fov_deg: float = 100.0,
) -> tuple[np.ndarray, np.ndarray]:
    focal = (size / 2) / math.tan(math.radians(fov_deg) / 2)
    axis = (np.arange(size, dtype=np.float32) - (size - 1) / 2) / focal
    grid_x, grid_y = np.meshgrid(axis, -axis)
    ray_z = np.ones_like(grid_x)
    length = np.sqrt(grid_x**2 + grid_y**2 + ray_z**2)
    ray_x, ray_y, ray_z = grid_x / length, grid_y / length, ray_z / length
    yaw = math.radians(yaw_deg)
    world_x = math.cos(yaw) * ray_x + math.sin(yaw) * ray_z
    world_z = -math.sin(yaw) * ray_x + math.cos(yaw) * ray_z
    longitude = np.arctan2(world_x, world_z)
    latitude = np.arcsin(np.clip(ray_y, -1.0, 1.0))
    map_x = ((longitude / (2 * math.pi)) + 0.5) * panorama_width
    map_y = (0.5 - latitude / math.pi) * panorama_height
    return map_x.astype(np.float32), map_y.astype(np.float32)


def _render_views(paths: list[Path], output: Path, prefix: str) -> list[str]:
    names: list[str] = []
    output.mkdir(parents=True, exist_ok=True)
    cached_maps: dict[tuple[int, int, int], tuple[np.ndarray, np.ndarray]] = {}
    for panorama_index, path in enumerate(paths):
        panorama = cv2.imread(str(path))
        if panorama is None or panorama.shape[1] < panorama.shape[0] * 1.8:
            continue
        height, width = panorama.shape[:2]
        for face_index, yaw in enumerate((0, 90, 180, 270)):
            key = (width, height, yaw)
            maps = cached_maps.setdefault(
                key,
                _perspective_map(width, height, yaw_deg=yaw),
            )
            face = cv2.remap(
                panorama,
                maps[0],
                maps[1],
                cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_WRAP,
            )
            relative = f"{prefix}/{panorama_index:05d}_{face_index}.jpg"
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if cv2.imwrite(str(destination), face):
                names.append(relative)
    return names


def _panorama_index(name: str) -> int:
    return int(Path(name).stem.split("_")[0])


def _verified_inliers(
    feature_path: Path,
    match_path: Path,
    query_name: str,
    reference_name: str,
) -> int:
    # h5py is installed with the optional HLoc runtime on the data SSD. Keep
    # this import lazy so the API and ordinary Stella pipeline still start
    # when that SSD/runtime is unavailable.
    import h5py
    from hloc.utils.parsers import names_to_pair, names_to_pair_old

    with h5py.File(str(match_path), "r", libver="latest") as matches_file:
        pair_name = names_to_pair(query_name, reference_name)
        reverse = False
        if pair_name not in matches_file:
            pair_name = names_to_pair(reference_name, query_name)
            reverse = True
        if pair_name not in matches_file:
            old_name = names_to_pair_old(query_name, reference_name)
            if old_name not in matches_file:
                return 0
            pair_name = old_name
        matches = matches_file[pair_name]["matches0"].__array__().astype(int)
    with h5py.File(str(feature_path), "r", libver="latest") as feature_file:
        points0 = feature_file[query_name]["keypoints"].__array__()
        points1 = feature_file[reference_name]["keypoints"].__array__()
    valid0 = np.flatnonzero(matches >= 0)
    if len(valid0) < 8:
        return 0
    valid1 = matches[valid0]
    if reverse:
        points0, points1 = points1, points0
    _matrix, mask = cv2.findFundamentalMat(
        points0[valid0],
        points1[valid1],
        cv2.FM_RANSAC,
        2.0,
        0.999,
    )
    return int(mask.sum()) if mask is not None else 0


def learned_panorama_matches(
    current_paths: list[Path],
    reference_paths: list[Path],
    *,
    workspace: Path,
) -> list[tuple[int, int, int]]:
    """Return geometrically verified (score, current index, reference index).

    Panoramas are rendered into four perspective views. NetVLAD performs broad
    retrieval, while DISK + LightGlue and a fundamental-matrix RANSAC prevent
    repetitive columns/formwork from becoming false plan anchors.
    """
    if not current_paths or not reference_paths:
        return []
    _activate_runtime()
    from hloc import extract_features, match_features, pairs_from_retrieval

    settings = get_settings()
    # Running retrieval over every panorama in a long 8K walk can create well
    # over a thousand LightGlue pairs.  On Windows the native PyTorch runtime
    # may abort the entire Celery process (rather than raise MemoryError),
    # leaving the job stuck at 75%.  A uniformly sampled set still covers the
    # full route and is sufficient for the rigid plan alignment.
    maximum_current_panoramas = 24
    current_indices = list(range(len(current_paths)))
    if len(current_paths) > maximum_current_panoramas:
        current_indices = np.linspace(
            0, len(current_paths) - 1, maximum_current_panoramas, dtype=int
        ).tolist()
        current_paths = [current_paths[index] for index in current_indices]
    maximum_reference_panoramas = max(8, settings.hloc_max_reference_images // 4)
    reference_indices = list(range(len(reference_paths)))
    if len(reference_paths) > maximum_reference_panoramas:
        reference_indices = np.linspace(
            0,
            len(reference_paths) - 1,
            maximum_reference_panoramas,
            dtype=int,
        ).tolist()
        reference_paths = [reference_paths[index] for index in reference_indices]

    image_dir = workspace / "learned-images"
    current_names = _render_views(current_paths, image_dir, "current")
    reference_names = _render_views(reference_paths, image_dir, "reference")
    if not current_names or not reference_names:
        return []

    outputs = workspace / "learned-output"
    retrieval_path = extract_features.main(
        extract_features.confs["netvlad"],
        image_dir,
        outputs,
        as_half=True,
        image_list=current_names + reference_names,
    )
    pairs_path = outputs / "retrieval-pairs.txt"
    pairs_from_retrieval.main(
        retrieval_path,
        pairs_path,
        min(settings.hloc_retrieval_candidates, len(reference_names)),
        query_prefix="current/",
        db_prefix="reference/",
    )
    feature_path = extract_features.main(
        extract_features.confs["disk"],
        image_dir,
        outputs,
        as_half=True,
        image_list=current_names + reference_names,
    )
    match_path = outputs / "disk-lightglue.h5"
    match_features.main(
        match_features.confs["disk+lightglue"],
        pairs_path,
        feature_path,
        matches=match_path,
        overwrite=True,
    )

    panorama_scores: dict[tuple[int, int], list[int]] = defaultdict(list)
    for line in pairs_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        query_name, reference_name = line.split(maxsplit=1)
        score = _verified_inliers(
            feature_path,
            match_path,
            query_name,
            reference_name,
        )
        if score >= settings.hloc_min_geometric_inliers:
            panorama_scores[
                (
                    current_indices[_panorama_index(query_name)],
                    reference_indices[_panorama_index(reference_name)],
                )
            ].append(score)

    scored: list[tuple[int, int, int]] = []
    for (current_index, reference_index), scores in panorama_scores.items():
        scores.sort(reverse=True)
        # A second adjacent view is additional evidence without allowing a
        # single panorama to win just because all four faces look repetitive.
        score = scores[0] + (scores[1] // 4 if len(scores) > 1 else 0)
        scored.append((score, current_index, reference_index))
    return scored


def _add_reference_pairs(
    pairs_path: Path,
    names: list[str],
    panorama_count: int,
) -> None:
    pair_set = {
        tuple(line.split(maxsplit=1))
        for line in pairs_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    name_set = set(names)
    for panorama_index in range(panorama_count):
        for face_index in range(4):
            source = f"reference/{panorama_index:05d}_{face_index}.jpg"
            for delta in (-2, -1, 1, 2):
                target = f"reference/{panorama_index + delta:05d}_{face_index}.jpg"
                if source in name_set and target in name_set:
                    pair_set.add((source, target))
            adjacent = f"reference/{panorama_index:05d}_{(face_index + 1) % 4}.jpg"
            if source in name_set and adjacent in name_set:
                pair_set.add((source, adjacent))
    pairs_path.write_text(
        "\n".join(f"{left} {right}" for left, right in sorted(pair_set)) + "\n",
        encoding="utf-8",
    )


def _reference_cache_root() -> Path:
    settings = get_settings()
    configured = settings.hloc_reference_cache_path
    if configured:
        root = Path(configured)
    elif settings.hloc_torch_home:
        root = Path(settings.hloc_torch_home).parent / "hloc-reference-maps"
    else:
        root = Path(".runtime") / "hloc-reference-maps"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _build_reference_map(
    reference_paths: list[Path],
    reference_positions: list[tuple[float, float]],
    *,
    cache_key: str,
) -> tuple[Path, dict[str, object]]:
    """Build and cache an SfM map tied to human-confirmed plan positions."""
    if len(reference_paths) != len(reference_positions):
        raise ValueError("Reference images and plan positions must have equal length")
    if len(reference_paths) < 8:
        raise LearnedRelocalizationUnavailable("Need at least 8 trusted panoramas")
    _activate_runtime()
    import pycolmap
    from hloc import extract_features, match_features, pairs_from_retrieval, reconstruction

    safe_key = "".join(
        character
        for character in cache_key
        if character.isalnum() or character in "-_"
    )
    cache_dir = _reference_cache_root() / safe_key
    metadata_path = cache_dir / "metadata.json"
    model_dir = cache_dir / "sfm"
    if metadata_path.is_file() and (model_dir / "images.bin").is_file():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        # HLoc assumes that pycolmap's reconstruction dictionary keys are the
        # same as COLMAP's numbered output folders.  That is not always true on
        # Windows: the in-memory reconstruction can contain every image while
        # the model copied to the SfM root is a tiny two-image fragment.  Never
        # trust such a cache because localization would silently retrieve
        # images which do not exist in the stored 3-D model.
        cached_model = pycolmap.Reconstruction(model_dir)
        expected_views = len(metadata.get("reference_names", []))
        minimum_registered = max(8, math.ceil(expected_views * 0.70))
        has_route_mapper = all(
            key in metadata
            for key in ("reference_camera_centres", "reference_plan_points")
        )
        if cached_model.num_reg_images() >= minimum_registered and has_route_mapper:
            return cache_dir, metadata
        del cached_model
        shutil.rmtree(cache_dir, ignore_errors=True)

    build_dir = cache_dir.parent / f".{safe_key}.building-{uuid.uuid4().hex}"
    try:
        image_dir = build_dir / "images"
        output_dir = build_dir / "outputs"
        model_dir_build = build_dir / "sfm"
        output_dir.mkdir(parents=True, exist_ok=True)
        names = _render_views(reference_paths, image_dir, "reference")
        if len(names) < 32:
            raise LearnedRelocalizationUnavailable("Too few usable reference views")
        retrieval_path = extract_features.main(
            extract_features.confs["netvlad"],
            image_dir,
            output_dir,
            as_half=True,
            image_list=names,
        )
        pairs_path = output_dir / "reference-pairs.txt"
        pairs_from_retrieval.main(
            retrieval_path,
            pairs_path,
            min(20, len(names) - 1),
            query_list=names,
            db_list=names,
        )
        _add_reference_pairs(pairs_path, names, len(reference_paths))
        feature_path = extract_features.main(
            extract_features.confs["disk"],
            image_dir,
            output_dir,
            as_half=True,
            image_list=names,
        )
        match_path = output_dir / "reference-disk-lightglue.h5"
        match_features.main(
            match_features.confs["disk+lightglue"],
            pairs_path,
            feature_path,
            matches=match_path,
            overwrite=True,
        )
        model = reconstruction.main(
            model_dir_build,
            image_dir,
            pairs_path,
            feature_path,
            match_path,
            camera_mode=pycolmap.CameraMode.SINGLE,
            image_list=names,
            mapper_options={"min_num_matches": 12},
        )
        if model is None:
            raise LearnedRelocalizationUnavailable(
                "Reference SfM reconstruction produced no model"
            )
        centres: dict[int, list[np.ndarray]] = defaultdict(list)
        for image in model.images.values():
            if not image.has_pose:
                continue
            panorama_index = _panorama_index(image.name)
            centre = np.asarray(image.projection_center(), dtype=np.float64)
            if np.isfinite(centre).all():
                centres[panorama_index].append(centre)
        common = sorted(set(centres) & set(range(len(reference_positions))))
        minimum_coverage = max(8, math.ceil(len(reference_positions) * 0.70))
        if len(common) < minimum_coverage:
            raise LearnedRelocalizationUnavailable(
                f"Reference SfM coverage too low: {len(common)}/{len(reference_positions)}"
            )
        camera_centres = np.asarray(
            [np.mean(centres[index], axis=0) for index in common], dtype=np.float64
        )
        plan_points = np.asarray(
            [reference_positions[index] for index in common], dtype=np.float64
        )
        # A trusted route may already contain piecewise drift correction.  A
        # single global affine transform cannot represent that correction and
        # used to reject otherwise excellent 3-D reconstructions.  Preserve
        # the registered camera centres and their audited plan positions as a
        # piecewise route map instead.  Query cameras are projected onto the
        # nearest 3-D segment and interpolated on the corresponding plan
        # segment below.
        plan_span = np.ptp(plan_points, axis=0)
        plan_diagonal = float(np.linalg.norm(plan_span))
        plan_steps = np.linalg.norm(np.diff(plan_points, axis=0), axis=1)
        if plan_diagonal < 0.08 or not np.isfinite(plan_steps).all():
            raise LearnedRelocalizationUnavailable(
                "Reference route has insufficient audited plan coverage"
            )
        p90_plan_step_ratio = float(
            np.percentile(plan_steps, 90) / max(plan_diagonal, 1e-9)
        )
        if p90_plan_step_ratio > 0.50:
            raise LearnedRelocalizationUnavailable(
                "Reference route contains implausible plan jumps "
                f"(p90={p90_plan_step_ratio:.3f})"
            )
        metadata: dict[str, object] = {
            "reference_names": names,
            "reference_camera_centres": camera_centres.tolist(),
            "reference_plan_points": plan_points.tolist(),
            "covered_panoramas": len(common),
            "total_panoramas": len(reference_positions),
            "p90_plan_step_ratio": p90_plan_step_ratio,
            "registered_views": int(model.num_reg_images()),
        }
        # Persist the exact reconstruction selected and validated above.
        # Do not rely on HLoc's numbered-folder move on Windows (see cache
        # validation above), otherwise a small disconnected model may be saved
        # instead of this largest reconstruction.
        model.write(model_dir_build)
        # pycolmap can keep handles to files in the reconstruction directory on
        # Windows.  Renaming that directory then fails with WinError 5 even
        # though the reconstruction itself completed successfully.  Publish a
        # copy instead and write metadata last so an interrupted copy is never
        # mistaken for a valid cache.
        del model
        shutil.rmtree(image_dir, ignore_errors=True)
        if cache_dir.exists():
            shutil.rmtree(cache_dir, ignore_errors=True)
        shutil.copytree(build_dir, cache_dir)
        (cache_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        shutil.rmtree(build_dir, ignore_errors=True)
        return cache_dir, metadata
    except Exception:
        shutil.rmtree(build_dir, ignore_errors=True)
        raise


def _project_centre_to_plan_route(
    centre: np.ndarray,
    reference_centres: np.ndarray,
    reference_plan: np.ndarray,
) -> np.ndarray:
    """Project a localized 3-D camera onto an audited piecewise plan route."""
    if len(reference_centres) != len(reference_plan) or len(reference_centres) < 2:
        raise LearnedRelocalizationUnavailable("Reference route map is incomplete")
    segment_starts = reference_centres[:-1]
    segment_vectors = reference_centres[1:] - segment_starts
    squared_lengths = np.einsum("ij,ij->i", segment_vectors, segment_vectors)
    valid = squared_lengths > 1e-12
    if not valid.any():
        raise LearnedRelocalizationUnavailable("Reference 3-D route is collapsed")
    fractions = np.zeros(len(segment_vectors), dtype=np.float64)
    fractions[valid] = np.einsum(
        "ij,ij->i",
        centre - segment_starts[valid],
        segment_vectors[valid],
    ) / squared_lengths[valid]
    fractions = np.clip(fractions, 0.0, 1.0)
    projected = segment_starts + segment_vectors * fractions[:, None]
    distances = np.linalg.norm(projected - centre, axis=1)
    distances[~valid] = np.inf
    segment_index = int(np.argmin(distances))
    fraction = float(fractions[segment_index])
    return (
        reference_plan[segment_index] * (1.0 - fraction)
        + reference_plan[segment_index + 1] * fraction
    )


def learned_3d_plan_anchors(
    current_paths: list[Path],
    reference_paths: list[Path],
    reference_positions: list[tuple[float, float]],
    *,
    workspace: Path,
    cache_key: str,
) -> list[LearnedPlanAnchor]:
    """Localize new panoramas in a validated 3-D map and project onto the plan."""
    if not current_paths or not reference_paths:
        return []
    _activate_runtime()
    import pycolmap
    import torch
    from hloc import extract_features, localize_sfm, match_features, pairs_from_retrieval

    settings = get_settings()
    # The anchors only determine the rigid alignment of the complete Stella
    # trajectory; localizing every panorama is unnecessary and made a normal
    # capture take several minutes.  Sample the whole time span so the selected
    # anchors still cover the start, middle and end of the walk.
    # The field laptop can run the learned stack without CUDA, but matching a
    # full 32x24 panorama grid on CPU creates well over a thousand LightGlue
    # pairs and competes with Revit for half an hour.  Use a route-wide pilot
    # sample on CPU; CUDA workers retain the denser production sample.
    cpu_limited = not torch.cuda.is_available()
    maximum_query_panoramas = 12 if cpu_limited else 32
    query_indices = list(range(len(current_paths)))
    if len(current_paths) > maximum_query_panoramas:
        query_indices = np.linspace(
            0, len(current_paths) - 1, maximum_query_panoramas, dtype=int
        ).tolist()
        current_paths = [current_paths[index] for index in query_indices]
    maximum_reference_panoramas = max(8, settings.hloc_max_reference_images // 4)
    if cpu_limited:
        maximum_reference_panoramas = min(maximum_reference_panoramas, 8)
    if len(reference_paths) > maximum_reference_panoramas:
        indices = np.linspace(
            0, len(reference_paths) - 1, maximum_reference_panoramas, dtype=int
        ).tolist()
        reference_paths = [reference_paths[index] for index in indices]
        reference_positions = [reference_positions[index] for index in indices]
    # Include the sampling density in the cache identity.  Otherwise a CPU
    # pilot could accidentally reuse a differently sampled map (or vice versa).
    sampled_cache_key = (
        f"{cache_key}-q{maximum_query_panoramas}-r{len(reference_paths)}"
    )
    cache_dir, metadata = _build_reference_map(
        reference_paths, reference_positions, cache_key=sampled_cache_key
    )
    model = pycolmap.Reconstruction(cache_dir / "sfm")
    reference_names = [str(name) for name in metadata["reference_names"]]

    image_dir = workspace / "images"
    output_dir = workspace / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    current_names = _render_views(current_paths, image_dir, "current")
    if not current_names:
        return []
    query_global = extract_features.main(
        extract_features.confs["netvlad"],
        image_dir,
        output_dir,
        as_half=True,
        image_list=current_names,
    )
    reference_global = cache_dir / "outputs" / "global-feats-netvlad.h5"
    retrieval_pairs = output_dir / "query-reference-pairs.txt"
    pairs_from_retrieval.main(
        query_global,
        retrieval_pairs,
        min(max(5, settings.hloc_retrieval_candidates), len(reference_names)),
        query_list=current_names,
        db_list=reference_names,
        db_descriptors=reference_global,
    )
    query_features = extract_features.main(
        extract_features.confs["disk"],
        image_dir,
        output_dir,
        as_half=True,
        image_list=current_names,
    )
    reference_features = cache_dir / "outputs" / "feats-disk.h5"
    query_matches = output_dir / "query-disk-lightglue.h5"
    match_features.main(
        match_features.confs["disk+lightglue"],
        retrieval_pairs,
        query_features,
        matches=query_matches,
        features_ref=reference_features,
        overwrite=True,
    )
    focal = (512 / 2) / math.tan(math.radians(100.0) / 2)
    query_list = output_dir / "queries.txt"
    query_list.write_text(
        "\n".join(
            f"{name} PINHOLE 512 512 {focal:.8f} {focal:.8f} 255.5 255.5"
            for name in current_names
        )
        + "\n",
        encoding="utf-8",
    )
    result_path = output_dir / "query-poses.txt"
    localize_sfm.main(
        model,
        query_list,
        retrieval_pairs,
        query_features,
        query_matches,
        result_path,
        ransac_thresh=8,
        covisibility_clustering=True,
    )
    with Path(f"{result_path}_logs.pkl").open("rb") as file:
        logs = pickle.load(file)
    centres: dict[int, list[tuple[np.ndarray, int]]] = defaultdict(list)
    for name, log in logs.get("loc", {}).items():
        cluster_index = log.get("best_cluster")
        if cluster_index is None:
            continue
        cluster_logs = log.get("log_clusters", [])
        if not 0 <= int(cluster_index) < len(cluster_logs):
            continue
        result = cluster_logs[int(cluster_index)].get("PnP_ret")
        if result is None:
            continue
        inliers = int(result.get("num_inliers", 0))
        if inliers < settings.hloc_min_geometric_inliers:
            continue
        cam_from_world = result["cam_from_world"]
        centre = np.asarray(cam_from_world.inverse().translation, dtype=np.float64)
        if np.isfinite(centre).all():
            centres[_panorama_index(name)].append((centre, inliers))

    reference_centres = np.asarray(
        metadata["reference_camera_centres"], dtype=np.float64
    )
    reference_plan = np.asarray(metadata["reference_plan_points"], dtype=np.float64)
    anchors: list[LearnedPlanAnchor] = []
    for panorama_index, observations in sorted(centres.items()):
        observations.sort(key=lambda item: item[1], reverse=True)
        selected = observations[:3]
        total_inliers = sum(item[1] for item in selected)
        if (
            len(selected) == 1
            and total_inliers < settings.hloc_min_geometric_inliers * 2
        ):
            continue
        weights = np.asarray([item[1] for item in selected], dtype=np.float64)
        centre = np.average(
            np.asarray([item[0] for item in selected]), axis=0, weights=weights
        )
        plan = _project_centre_to_plan_route(
            centre,
            reference_centres,
            reference_plan,
        )
        if (
            np.isfinite(plan).all()
            and -0.10 <= plan[0] <= 1.10
            and -0.10 <= plan[1] <= 1.10
        ):
            anchors.append(
                LearnedPlanAnchor(
                    # _render_views renumbers the sampled panoramas from zero.
                    # Preserve the original timeline index so an anchor is
                    # applied to the correct Stella pose in the full route.
                    panorama_index=query_indices[panorama_index],
                    plan_x=float(plan[0]),
                    plan_y=float(plan[1]),
                    inliers=total_inliers,
                    localized_faces=len(selected),
                )
            )
    return anchors
