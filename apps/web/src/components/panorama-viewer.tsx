"use client";

import Image from "next/image";
import { useRouter } from "next/navigation";
import {
  ChangeEvent,
  MouseEvent,
  PointerEvent as ReactPointerEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import * as THREE from "three";

import { groundPortalPlacement } from "@/lib/portal-placement";
import type { CaptureDetail, Floor, FloorPlanInfo } from "@/lib/types";

type Keyframe = CaptureDetail["keyframes"][number];
type PlanPosition = { x: number; y: number; headingDeg: number };
type DraftControlPoint = { keyframeId: string; x: number; y: number };
type DraftEvaluationPoint = { keyframeId: string; x: number; y: number };
type DraftStartPoint = { x: number; y: number };

type PanoramaRuntime = {
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  renderer: THREE.WebGLRenderer;
  sphereGeometry: THREE.SphereGeometry;
  sphereMaterial: THREE.MeshBasicMaterial;
  texture: THREE.Texture | null;
  hotspotGeometry: THREE.RingGeometry;
  hotspotMaterial: THREE.MeshBasicMaterial;
  hotspotHitGeometry: THREE.CircleGeometry;
  hotspotHitMaterial: THREE.MeshBasicMaterial;
  hotspotMeshes: THREE.Mesh[];
  routeGuideGeometries: THREE.BufferGeometry[];
  routeGuideMeshes: THREE.Mesh[];
  routeGuideMaterial: THREE.MeshBasicMaterial;
  invalidate: () => void;
  setView: (longitude: number, latitude: number, fov: number) => void;
};

export type PanoramaViewState = {
  longitude: number;
  latitude: number;
  fov: number;
};

type RigidTransform = {
  scaleX: number;
  scaleY: number;
  rotationDeg: number;
  mirror: boolean;
  offsetX: number;
  offsetY: number;
};

function suggestedRigidTransform(detail: CaptureDetail, floorId: string): RigidTransform {
  const frames = detail.keyframes.filter((frame) => (
    frame.pose?.floor_id === floorId
    && frame.pose.visual_x !== null
    && frame.pose.visual_y !== null
  ));
  const first = frames[0]?.pose;
  if (!first || frames.length < 2) {
    return { scaleX: 0.1, scaleY: 0.1, rotationDeg: 0, mirror: false, offsetX: 0, offsetY: 0 };
  }
  const originVisualX = Number(first.visual_x);
  const originVisualY = Number(first.visual_y);
  const alreadyAligned = frames.every((frame) => !frame.pose!.needs_review);
  if (alreadyAligned) {
    const planOriginX = Number(first.x);
    const planOriginY = Number(first.y);
    const candidates = [false, true].map((mirror) => {
      let dot = 0;
      let cross = 0;
      let visualSquared = 0;
      let visualXX = 0;
      let visualXY = 0;
      let visualYY = 0;
      let planXVisualX = 0;
      let planXVisualY = 0;
      let planYVisualX = 0;
      let planYVisualY = 0;
      for (const frame of frames) {
        const visualX = (Number(frame.pose!.visual_x) - originVisualX) * (mirror ? -1 : 1);
        const visualY = Number(frame.pose!.visual_y) - originVisualY;
        const planX = Number(frame.pose!.x) - planOriginX;
        const planY = Number(frame.pose!.y) - planOriginY;
        dot += visualX * planX + visualY * planY;
        cross += visualX * planY - visualY * planX;
        visualSquared += visualX * visualX + visualY * visualY;
        visualXX += visualX * visualX;
        visualXY += visualX * visualY;
        visualYY += visualY * visualY;
        planXVisualX += planX * visualX;
        planXVisualY += planX * visualY;
        planYVisualX += planY * visualX;
        planYVisualY += planY * visualY;
      }
      const fallbackScale = Math.max(
        0.0001,
        Math.hypot(dot, cross) / Math.max(visualSquared, 1e-8),
      );
      const determinant = visualXX * visualYY - visualXY * visualXY;
      let scaleX = fallbackScale;
      let scaleY = fallbackScale;
      let rotation = Math.atan2(cross, dot);
      if (Math.abs(determinant) > 1e-10) {
        const matrixXX = (planXVisualX * visualYY - planXVisualY * visualXY) / determinant;
        const matrixXY = (planXVisualY * visualXX - planXVisualX * visualXY) / determinant;
        const matrixYX = (planYVisualX * visualYY - planYVisualY * visualXY) / determinant;
        const matrixYY = (planYVisualY * visualXX - planYVisualX * visualXY) / determinant;
        scaleX = Math.max(0.0001, Math.hypot(matrixXX, matrixXY));
        scaleY = Math.max(0.0001, Math.hypot(matrixYX, matrixYY));
        const rotationFromX = Math.atan2(-matrixXY, matrixXX);
        const rotationFromY = Math.atan2(matrixYX, matrixYY);
        rotation = Math.atan2(
          Math.sin(rotationFromX) + Math.sin(rotationFromY),
          Math.cos(rotationFromX) + Math.cos(rotationFromY),
        );
      }
      const rotationDeg = rotation * 180 / Math.PI;
      let error = 0;
      for (const frame of frames) {
        const visualX = (Number(frame.pose!.visual_x) - originVisualX) * (mirror ? -1 : 1);
        const visualY = Number(frame.pose!.visual_y) - originVisualY;
        const predictedX = scaleX * (visualX * Math.cos(rotation) - visualY * Math.sin(rotation));
        const predictedY = scaleY * (visualX * Math.sin(rotation) + visualY * Math.cos(rotation));
        const planX = Number(frame.pose!.x) - planOriginX;
        const planY = Number(frame.pose!.y) - planOriginY;
        error += (predictedX - planX) ** 2 + (predictedY - planY) ** 2;
      }
      return { mirror, scaleX, scaleY, rotationDeg, error };
    });
    const best = candidates.reduce((result, candidate) => (
      candidate.error < result.error ? candidate : result
    ));
    return {
      scaleX: best.scaleX,
      scaleY: best.scaleY,
      rotationDeg: best.rotationDeg,
      mirror: best.mirror,
      offsetX: planOriginX - Number(detail.capture.start_x),
      offsetY: planOriginY - Number(detail.capture.start_y),
    };
  }

  const startX = Number(detail.capture.start_x);
  const startY = Number(detail.capture.start_y);
  const limits: number[] = [];
  for (const frame of frames) {
    const dx = Number(frame.pose!.visual_x) - originVisualX;
    const dy = Number(frame.pose!.visual_y) - originVisualY;
    if (dx > 1e-8) limits.push((0.95 - startX) / dx);
    if (dx < -1e-8) limits.push((0.05 - startX) / dx);
    if (dy > 1e-8) limits.push((0.95 - startY) / dy);
    if (dy < -1e-8) limits.push((0.05 - startY) / dy);
  }
  const safeScale = Math.min(...limits.filter((value) => value > 0));
  return {
    scaleX: Number.isFinite(safeScale) ? Math.max(0.0001, safeScale * 0.85) : 0.1,
    scaleY: Number.isFinite(safeScale) ? Math.max(0.0001, safeScale * 0.85) : 0.1,
    rotationDeg: 0,
    mirror: false,
    offsetX: 0,
    offsetY: 0,
  };
}

function transformVisualPose(
  frame: Keyframe,
  originFrame: Keyframe,
  startX: number,
  startY: number,
  scaleX: number,
  scaleY: number,
  rotationDeg: number,
  mirror: boolean,
  offsetX: number,
  offsetY: number,
): PlanPosition | null {
  if (
    !frame.pose
    || !originFrame.pose
    || frame.pose.visual_x === null
    || frame.pose.visual_y === null
    || originFrame.pose.visual_x === null
    || originFrame.pose.visual_y === null
  ) return null;
  const rotation = rotationDeg * Math.PI / 180;
  const cosRotation = Math.cos(rotation);
  const sinRotation = Math.sin(rotation);
  const relativeX = (
    Number(frame.pose.visual_x) - Number(originFrame.pose.visual_x)
  ) * (mirror ? -1 : 1);
  const relativeY = Number(frame.pose.visual_y) - Number(originFrame.pose.visual_y);
  const rotatedX = relativeX * cosRotation - relativeY * sinRotation;
  const rotatedY = relativeX * sinRotation + relativeY * cosRotation;
  const visualHeading = Number(frame.pose.visual_heading_deg ?? 0) * Math.PI / 180;
  const forwardX = Math.sin(visualHeading) * (mirror ? -1 : 1);
  const forwardY = Math.cos(visualHeading);
  const planForwardX = scaleX * (forwardX * cosRotation - forwardY * sinRotation);
  const planForwardY = scaleY * (forwardX * sinRotation + forwardY * cosRotation);
  return {
    x: startX + offsetX + scaleX * rotatedX,
    y: startY + offsetY + scaleY * rotatedY,
    headingDeg: (Math.atan2(planForwardY, planForwardX) * 180 / Math.PI + 360) % 360,
  };
}

function timeLabel(milliseconds: number) {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function confidenceLabel(frame: Keyframe) {
  if (frame.quality_status !== "USABLE") return frame.quality_status;
  if (!frame.pose) return "ยังไม่มีตำแหน่ง";
  if (frame.pose.reviewed_at) return "ตรวจตำแหน่งแล้ว";
  if (frame.pose.needs_review) return "รอจัดแนวบนแปลน";
  return `AI ${(Number(frame.pose.confidence) * 100).toFixed(0)}%`;
}

function normalizedAngle(angle: number) {
  return ((angle + 180) % 360 + 360) % 360 - 180;
}

function visualHeading(frame: Keyframe) {
  return Number(frame.pose?.visual_heading_deg ?? frame.pose?.heading_deg ?? 0);
}

const TOUR_ROUTE_SOURCES = new Set([
  "visual-slam-pose",
  "full-6dof-mesh",
  "stabilized-360-mesh",
]);

function isUsableTourRoute(route: CaptureDetail["route_vectors"][number]) {
  return route.verified
    && TOUR_ROUTE_SOURCES.has(route.direction_source)
    && route.confidence >= 0.25
    && route.distance > 1e-8;
}

function tourFrames(detail: CaptureDetail) {
  // API/database row order is not a playback order. Always build the tour
  // chronologically so a freshly opened capture starts at its earliest
  // available station and the previous/next controls move through time.
  const orderedFrames = [...detail.keyframes].sort((first, second) => (
    first.timestamp_ms - second.timestamp_ms || first.id.localeCompare(second.id)
  ));
  const posed = orderedFrames.filter((frame) => frame.pose !== null);
  const selected = posed.filter((frame) => frame.is_warp_point);
  const connectedIds = new Set(
    detail.route_vectors
      .filter(isUsableTourRoute)
      .flatMap((route) => [route.from_keyframe_id, route.to_keyframe_id]),
  );
  const connected = selected.filter((frame) => connectedIds.has(frame.id));
  // A spatial tour exposes one station per physical place. Legacy captures
  // sometimes marked every half-second frame as a station, including long
  // runs of identical coordinates. Those zero-distance frames cannot form a
  // portal, so prefer graph-backed stations. Still retain the real first and
  // last selected frames: localization may only have a connected route for a
  // middle section of the clip, but opening a capture must never silently
  // begin minutes into the source video.
  if (connected.length >= 2) {
    const boundaryFrames = [selected[0], selected[selected.length - 1]].filter(
      (frame): frame is Keyframe => Boolean(frame),
    );
    return [...new Map(
      [...boundaryFrames, ...connected].map((frame) => [frame.id, frame]),
    ).values()].sort((first, second) => (
      first.timestamp_ms - second.timestamp_ms || first.id.localeCompare(second.id)
    ));
  }
  if (selected.length >= 2) return selected;
  return posed.length ? posed : orderedFrames;
}

export function PanoramaViewer({
  detail,
  projectId,
  floors,
  canEdit,
  onSelectedKeyframeChange,
  onViewStateChange,
  requestedKeyframeId,
  requestedViewToken,
  requestedWorldHeading,
  requestedViewState,
  requestedViewSyncToken,
}: {
  detail: CaptureDetail;
  projectId: string;
  floors: Floor[];
  canEdit: boolean;
  onSelectedKeyframeChange?: (keyframeId: string | null) => void;
  onViewStateChange?: (view: PanoramaViewState) => void;
  requestedKeyframeId?: string | null;
  requestedViewToken?: number;
  requestedWorldHeading?: number | null;
  requestedViewState?: PanoramaViewState | null;
  requestedViewSyncToken?: number;
}) {
  const router = useRouter();
  const initialTourFrames = tourFrames(detail);
  const containerRef = useRef<HTMLDivElement>(null);
  const planFileInputRef = useRef<HTMLInputElement>(null);
  const viewConeRef = useRef<HTMLSpanElement>(null);
  const viewConePlanHeadingRef = useRef(0);
  const pendingKeyframeRef = useRef<string | null>(null);
  // A requested frame is an external command (BIM/plan/parent), not a value to
  // continuously force back into the viewer. Remembering the command prevents
  // an internal portal click from being immediately reverted by the old prop.
  const lastRequestedKeyframeRef = useRef<string | null | undefined>(undefined);
  // Keep only the next decoded 8K panorama.  Retaining every decoded frame
  // can consume more than 100 MB per image and eventually loses the WebGL
  // context, leaving the viewer black.
  const preloadedImageRef = useRef<{
    keyframeId: string;
    image: HTMLImageElement;
  } | null>(null);
  // Decode only immediate tour neighbours so a hotspot click is instant
  // without retaining the whole high-resolution tour in memory.
  const tourImageCacheRef = useRef(new Map<string, HTMLImageElement>());
  const panoramaRuntimeRef = useRef<PanoramaRuntime | null>(null);
  const transformDragRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    offsetX: number;
    offsetY: number;
  } | null>(null);
  const viewRef = useRef({ longitude: 0, latitude: 0, fov: 70 });
  const initialPortalViewAppliedRef = useRef(false);
  const [selectedId, setSelectedId] = useState<string | null>(
    initialTourFrames.find((frame) => (
      frame.id === requestedKeyframeId && frame.pose && frame.is_warp_point
    ))?.id
      ?? initialTourFrames[0]?.id
      ?? null,
  );
  const [activeFloorId, setActiveFloorId] = useState(
    detail.keyframes.find((frame) => frame.pose)?.pose?.floor_id
      ?? detail.capture.start_floor_id,
  );
  const suggestedTransform = useMemo(
    () => suggestedRigidTransform(detail, activeFloorId),
    [activeFloorId, detail],
  );
  const [aligning, setAligning] = useState(false);
  const [draftScaleX, setDraftScaleX] = useState(suggestedTransform.scaleX);
  const [draftScaleY, setDraftScaleY] = useState(suggestedTransform.scaleY);
  const [draftRotation, setDraftRotation] = useState(suggestedTransform.rotationDeg);
  const [draftMirror, setDraftMirror] = useState(suggestedTransform.mirror);
  const [draftOffsetX, setDraftOffsetX] = useState(suggestedTransform.offsetX);
  const [draftOffsetY, setDraftOffsetY] = useState(suggestedTransform.offsetY);
  const [controlPointMode, setControlPointMode] = useState(false);
  const [draftControlPoints, setDraftControlPoints] = useState<DraftControlPoint[]>(
    (detail.control_points ?? []).map((point) => ({
      keyframeId: point.keyframe_id,
      x: Number(point.x),
      y: Number(point.y),
    })),
  );
  const [evaluationMode, setEvaluationMode] = useState(false);
  const [draftEvaluationPoints, setDraftEvaluationPoints] = useState<DraftEvaluationPoint[]>(
    (detail.evaluation_points ?? []).map((point) => ({
      keyframeId: point.keyframe_id,
      x: Number(point.target_x),
      y: Number(point.target_y),
    })),
  );
  const [startPointMode, setStartPointMode] = useState(false);
  const [draftStartPoint, setDraftStartPoint] = useState<DraftStartPoint>({
    x: Number(detail.capture.start_x),
    y: Number(detail.capture.start_y),
  });
  const [mapExpanded, setMapExpanded] = useState(false);
  const [mapToolsOpen, setMapToolsOpen] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [webglUnavailable, setWebglUnavailable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploadedPlanFloorIds, setUploadedPlanFloorIds] = useState<string[]>([]);
  const [planRevision, setPlanRevision] = useState(0);
  const [planInfoState, setPlanInfoState] = useState<{
    floorId: string;
    info: FloorPlanInfo;
  } | null>(null);
  const isHoldout = detail.capture.dataset_split === "HOLDOUT_TEST";
  const canAdjustPath = canEdit && !isHoldout;

  const posedFrames = useMemo(
    () => detail.keyframes.filter((frame) => frame.pose !== null),
    [detail.keyframes],
  );
  const navigableFrames = useMemo(() => tourFrames(detail), [detail]);
  const floorFrames = posedFrames.filter((frame) => frame.pose?.floor_id === activeFloorId);
  const navigableIds = new Set(navigableFrames.map((frame) => frame.id));
  const floorTourFrames = floorFrames.filter((frame) => navigableIds.has(frame.id));
  const visibleFloorStations = floorTourFrames.length >= 2 ? floorTourFrames : floorFrames;
  const floorPathPoints = detail.path_points.filter((point) => point.floor_id === activeFloorId);
  const activeFloor = floors.find((floor) => floor.id === activeFloorId);
  const hasConfiguredPlan = Boolean(
    activeFloor?.has_plan || uploadedPlanFloorIds.includes(activeFloorId),
  );
  const planInfo = planInfoState?.floorId === activeFloorId ? planInfoState.info : null;
  const verifiedPoseCount = floorFrames.filter((frame) => frame.pose && !frame.pose.needs_review).length;
  const alignmentVerified = floorFrames.length >= 2 && verifiedPoseCount === floorFrames.length;
  const humanReviewedPoseCount = floorFrames.filter((frame) => Boolean(frame.pose?.reviewed_at)).length;
  const humanAlignmentVerified = floorFrames.length >= 2 && humanReviewedPoseCount === floorFrames.length;
  const routeAlgorithms = [
    ...floorFrames.map((frame) => frame.pose?.algorithm ?? ""),
    ...floorPathPoints.map((point) => point.algorithm ?? ""),
  ];
  const hasUnalignedPlanRoute = routeAlgorithms.some((algorithm) => {
    const isUnalignedFallback = /(grid6-road-edge-fit|plan-bounds-fit|unaligned-start-anchor|previous-orb|human-anchor-library-orb|previous-route-shape)/.test(algorithm);
    const wasHumanAligned = /(rigid-plan-transform|dev-gt-affine|dev-gt-piecewise)/.test(algorithm);
    return isUnalignedFallback && !wasHumanAligned;
  });
  const usesRepeatedRouteDraft = routeAlgorithms.some((algorithm) => (
    algorithm.includes("previous-route-shape")
  ));
  const persistentMapMatch = (() => {
    for (const frame of floorFrames) {
      const match = frame.pose?.algorithm.match(/persistent-map-v1:[^:]+:(\d+)-anchors/);
      if (match) return { anchorCount: Number(match[1]), accepted: !frame.pose?.needs_review };
    }
    return null;
  })();
  const anchorMatchCount = (() => {
    for (const frame of floorFrames) {
      const match = frame.pose?.algorithm.match(/human-anchor-library-v1:(\d+)-anchors/);
      if (match) return Number(match[1]);
    }
    return 0;
  })();
  const hasExistingCalibration = (detail.control_points ?? []).length > 0;
  const hasExistingEvaluation = (detail.evaluation_points ?? []).length > 0;
  const showCalibrationTools = canAdjustPath && (!alignmentVerified || hasExistingCalibration);
  const showEvaluationTools = canEdit && (isHoldout || hasExistingEvaluation);
  const selected = detail.keyframes.find((frame) => frame.id === selectedId)
    ?? detail.keyframes[0]
    ?? null;
  const usesRigTrajectory = Boolean(
    selected?.pose?.algorithm.startsWith("hloc-rig-"),
  );
  const selectedIndex = selected
    ? navigableFrames.findIndex((frame) => frame.id === selected.id)
    : -1;

  useEffect(() => {
    let cancelled = false;
    if (!activeFloorId || !hasConfiguredPlan) return () => { cancelled = true; };
    fetch(`/api/projects/${projectId}/floors/${activeFloorId}/plan-info`, {
      cache: "no-store",
    })
      .then(async (response) => {
        const payload = await response.json().catch(() => null);
        if (!response.ok) throw new Error(payload?.detail ?? "อ่านข้อมูลหน้าแปลนไม่สำเร็จ");
        if (!cancelled) {
          setPlanInfoState({ floorId: activeFloorId, info: payload as FloorPlanInfo });
        }
      })
      .catch((reason) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "อ่านข้อมูลหน้าแปลนไม่สำเร็จ");
      });
    return () => { cancelled = true; };
  }, [activeFloorId, hasConfiguredPlan, planRevision, projectId]);

  async function uploadFloorPlan(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !activeFloorId) return;
    setBusy(true);
    setError(null);
    try {
      const body = new FormData();
      body.set("file", file);
      const response = await fetch(
        `/api/projects/${projectId}/floors/${activeFloorId}/plan`,
        { method: "POST", body },
      );
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(payload?.detail ?? "อัปโหลดแปลนไม่สำเร็จ");
      setUploadedPlanFloorIds((current) => (
        current.includes(activeFloorId) ? current : [...current, activeFloorId]
      ));
      setPlanRevision(Date.now());
      router.refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "อัปโหลดแปลนไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  async function changeFloorPlanPage(event: ChangeEvent<HTMLSelectElement>) {
    const pageNumber = Number(event.target.value);
    if (!activeFloorId || !Number.isInteger(pageNumber)) return;
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/projects/${projectId}/floors/${activeFloorId}/plan`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ page_number: pageNumber }),
        },
      );
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(payload?.detail ?? "เปลี่ยนหน้าแปลนไม่สำเร็จ");
      setPlanInfoState({ floorId: activeFloorId, info: payload as FloorPlanInfo });
      setPlanRevision(Date.now());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "เปลี่ยนหน้าแปลนไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    onSelectedKeyframeChange?.(selected?.id ?? null);
  }, [onSelectedKeyframeChange, selected?.id]);
  const activeRouteVectors = useMemo(() => {
    if (!selectedId) return [];
    return detail.route_vectors
      .filter((route) => (
        route.from_keyframe_id === selectedId
        && isUsableTourRoute(route)
      ))
      .map((route) => ({
        ...route,
        target: detail.keyframes.find((frame) => frame.id === route.to_keyframe_id),
      }))
      .filter((route): route is typeof route & { target: Keyframe } => Boolean(route.target))
      .sort((first, second) => first.distance - second.distance);
  }, [detail.keyframes, detail.route_vectors, selectedId]);
  const medianRouteDistance = useMemo(() => {
    const nearestBySource = new Map<string, number>();
    for (const route of detail.route_vectors) {
      if (!route.verified || route.distance <= 1e-8) continue;
      const previous = nearestBySource.get(route.from_keyframe_id);
      if (previous === undefined || route.distance < previous) {
        nearestBySource.set(route.from_keyframe_id, route.distance);
      }
    }
    // Camera height must be calibrated against one adjacent walking step, not
    // the median of every visible look-ahead link. Including 2nd-6th portals
    // inflated the height, projected every ring below the viewport and made
    // multiple destinations collapse onto nearly the same screen position.
    const distances = [...nearestBySource.values()]
      .sort((first, second) => first - second);
    return distances[Math.floor(distances.length / 2)] ?? 1;
  }, [detail.route_vectors]);
  const processingActive = detail.jobs.some(
    (job) => ["QUEUED", "RUNNING"].includes(job.status),
  );
  const selectedStationNumber = selectedId
    ? navigableFrames.findIndex((frame) => frame.id === selectedId) + 1
    : 0;

  const keyframeImageUrl = useCallback((frame: Keyframe) => (
    `/api/projects/${projectId}/captures/${detail.capture.id}/keyframes/${frame.id}/image`
  ), [detail.capture.id, projectId]);

  const selectKeyframe = useCallback((frame: Keyframe, preferredWorldHeading?: number) => {
    if (frame.id === selected?.id) {
      if (preferredWorldHeading !== undefined && frame.pose) {
        viewRef.current.longitude = normalizedAngle(preferredWorldHeading - visualHeading(frame));
        panoramaRuntimeRef.current?.setView(
          viewRef.current.longitude,
          viewRef.current.latitude,
          viewRef.current.fov,
        );
        onViewStateChange?.({ ...viewRef.current });
      }
      return;
    }
    if (pendingKeyframeRef.current === frame.id) return;
    const currentWorldHeading = selected?.pose
      ? visualHeading(selected) + viewRef.current.longitude
      : viewRef.current.longitude;
    const targetWorldHeading = preferredWorldHeading ?? currentWorldHeading;
    const commitSelection = (image: HTMLImageElement) => {
      if (pendingKeyframeRef.current !== frame.id) return;
      preloadedImageRef.current = { keyframeId: frame.id, image };
      if (frame.pose) {
        const isMetricSpatialTour = frame.pose.algorithm.includes("+pycolmap-spatial-v1");
        const hasAuthoritativeSpatialTour = frame.pose.algorithm.startsWith("rig-pycolmap-");
        const frameRoutes = isMetricSpatialTour || hasAuthoritativeSpatialTour
          ? detail.route_vectors
            .filter((route) => (
              route.from_keyframe_id === frame.id
              && isUsableTourRoute(route)
            ))
            .map((route) => ({
              ...route,
              target: detail.keyframes.find((candidate) => candidate.id === route.to_keyframe_id),
            }))
            .filter((route) => Boolean(route.target))
            .sort((first, second) => first.distance - second.distance)
          : [];
        const nextPortal = frameRoutes.find((route) => (
          route.target!.timestamp_ms > frame.timestamp_ms
        )) ?? frameRoutes[0];
        // A portal click supplies the world heading of the selected physical
        // destination. Preserve it across the panorama swap; auto-facing a
        // different next portal made a correct station look like the click had
        // landed somewhere else. Automatic portal framing remains a fallback
        // for keyboard/external navigation only.
        if (preferredWorldHeading !== undefined) {
          viewRef.current.longitude = normalizedAngle(
            preferredWorldHeading - visualHeading(frame),
          );
        } else if (nextPortal) {
          viewRef.current.longitude = nextPortal.local_yaw_deg;
          const visualZ = Number(frame.pose.visual_z);
          const visualGroundZ = Number(frame.pose.visual_ground_z);
          const cameraHeight = frame.pose.visual_z !== null
            && frame.pose.visual_ground_z !== null
            && Number.isFinite(visualZ)
            && Number.isFinite(visualGroundZ)
            ? Math.abs(visualZ - visualGroundZ)
            : null;
          const placement = groundPortalPlacement({
            distance: nextPortal.distance,
            localYawDeg: nextPortal.local_yaw_deg,
            reconstructedCameraHeight: cameraHeight,
            fallbackStep: medianRouteDistance,
          });
          viewRef.current.latitude = Math.max(-75, Math.min(20, placement.pitchDeg));
        } else {
          viewRef.current.longitude = normalizedAngle(targetWorldHeading - visualHeading(frame));
        }
        setActiveFloorId(frame.pose.floor_id);
      }
      panoramaRuntimeRef.current?.setView(
        viewRef.current.longitude,
        viewRef.current.latitude,
        viewRef.current.fov,
      );
      setSelectedId(frame.id);
      pendingKeyframeRef.current = null;
    };
    pendingKeyframeRef.current = frame.id;
    const cachedImage = tourImageCacheRef.current.get(frame.id);
    const image = cachedImage ?? new window.Image();
    image.crossOrigin = "anonymous";
    image.decoding = "async";
    image.onload = () => commitSelection(image);
    image.onerror = () => {
      if (pendingKeyframeRef.current !== frame.id) return;
      tourImageCacheRef.current.delete(frame.id);
      pendingKeyframeRef.current = null;
      panoramaRuntimeRef.current?.setView(
        viewRef.current.longitude,
        viewRef.current.latitude,
        viewRef.current.fov,
      );
      setError("โหลดภาพ 360 จุดถัดไปไม่สำเร็จ ระบบยังคงแสดงภาพเดิม");
    };
    if (image.complete && image.naturalWidth > 0) {
      commitSelection(image);
    } else if (!cachedImage) {
      tourImageCacheRef.current.set(frame.id, image);
      image.src = keyframeImageUrl(frame);
    }
  }, [
    detail.keyframes,
    detail.route_vectors,
    keyframeImageUrl,
    medianRouteDistance,
    onViewStateChange,
    selected,
  ]);

  useEffect(() => {
    const cache = tourImageCacheRef.current;
    const neighbours = activeRouteVectors.slice(0, 2);
    const neighbourIds = new Set(neighbours.map((route) => route.target.id));
    for (const route of neighbours) {
      const frame = route.target;
      if (cache.has(frame.id)) continue;
      const image = new window.Image();
      image.crossOrigin = "anonymous";
      image.decoding = "async";
      image.onerror = () => cache.delete(frame.id);
      cache.set(frame.id, image);
      image.src = keyframeImageUrl(frame);
    }
    for (const keyframeId of [...cache.keys()]) {
      if (keyframeId !== selectedId && !neighbourIds.has(keyframeId)) cache.delete(keyframeId);
    }
  }, [activeRouteVectors, keyframeImageUrl, selectedId]);

  const selectedFrameRef = useRef(selected);
  const activeRouteVectorsRef = useRef(activeRouteVectors);
  const medianRouteDistanceRef = useRef(medianRouteDistance);
  const selectKeyframeRef = useRef(selectKeyframe);
  const onViewStateChangeRef = useRef(onViewStateChange);
  useEffect(() => {
    selectedFrameRef.current = selected;
    activeRouteVectorsRef.current = activeRouteVectors;
    medianRouteDistanceRef.current = medianRouteDistance;
    selectKeyframeRef.current = selectKeyframe;
    onViewStateChangeRef.current = onViewStateChange;
  }, [activeRouteVectors, medianRouteDistance, onViewStateChange, selectKeyframe, selected]);

  useEffect(() => {
    if (initialPortalViewAppliedRef.current || !activeRouteVectors.length) return;
    const nearestForward = activeRouteVectors
      .filter((route) => route.target.timestamp_ms > (selected?.timestamp_ms ?? -1))
      .sort((first, second) => first.distance - second.distance)[0]
      ?? activeRouteVectors[0];
    if (!nearestForward) return;
    initialPortalViewAppliedRef.current = true;
    viewRef.current.longitude = nearestForward.local_yaw_deg;
    const pose = selected?.pose;
    const visualZ = Number(pose?.visual_z);
    const visualGroundZ = Number(pose?.visual_ground_z);
    const cameraHeight = pose?.visual_z !== null
      && pose?.visual_z !== undefined
      && pose.visual_ground_z !== null
      && pose.visual_ground_z !== undefined
      && Number.isFinite(visualZ)
      && Number.isFinite(visualGroundZ)
      ? Math.abs(visualZ - visualGroundZ)
      : null;
    const placement = groundPortalPlacement({
      distance: nearestForward.distance,
      localYawDeg: nearestForward.local_yaw_deg,
      reconstructedCameraHeight: cameraHeight,
      fallbackStep: medianRouteDistance,
    });
    viewRef.current.latitude = Math.max(-75, Math.min(20, placement.pitchDeg));
    panoramaRuntimeRef.current?.setView(
      viewRef.current.longitude,
      viewRef.current.latitude,
      viewRef.current.fov,
    );
    onViewStateChange?.({ ...viewRef.current });
  }, [
    activeRouteVectors,
    medianRouteDistance,
    onViewStateChange,
    selected?.pose,
    selected?.timestamp_ms,
  ]);

  useEffect(() => {
    if (!requestedViewState) return;
    viewRef.current = { ...requestedViewState };
    panoramaRuntimeRef.current?.setView(
      requestedViewState.longitude,
      requestedViewState.latitude,
      requestedViewState.fov,
    );
  }, [requestedViewState, requestedViewSyncToken]);

  useEffect(() => {
    const requestKey = requestedKeyframeId
      ? `${requestedKeyframeId}:${requestedViewToken ?? "default"}`
      : null;
    if (lastRequestedKeyframeRef.current === requestKey) return;
    lastRequestedKeyframeRef.current = requestKey;
    if (!requestedKeyframeId) return;
    const requestedFrame = detail.keyframes.find((frame) => frame.id === requestedKeyframeId);
    if (!requestedFrame) return;
    // External consumers (BIM, progress evidence, old URLs) may still point to
    // a dense processing frame.  Route vectors intentionally exist only on
    // selected tour stations, so resolve that request to the nearest station
    // on the same floor instead of entering a panorama with no hotspots.
    const sameFloorStations = navigableFrames.filter((frame) => (
      frame.pose?.floor_id === requestedFrame.pose?.floor_id
    ));
    const candidates = sameFloorStations.length ? sameFloorStations : navigableFrames;
    const requestedStation = requestedFrame.is_warp_point
      ? requestedFrame
      : candidates.reduce<Keyframe | null>((nearest, frame) => (
        !nearest
        || Math.abs(frame.timestamp_ms - requestedFrame.timestamp_ms)
          < Math.abs(nearest.timestamp_ms - requestedFrame.timestamp_ms)
          ? frame
          : nearest
      ), null);
    if (!requestedStation) return;
    const preferredHeading = requestedWorldHeading !== null
      && requestedWorldHeading !== undefined
      && Number.isFinite(Number(requestedWorldHeading))
      ? Number(requestedWorldHeading)
      : undefined;
    if (requestedStation.id === selectedFrameRef.current?.id && preferredHeading === undefined) return;
    const selectionTask = window.setTimeout(() => (
      selectKeyframeRef.current(requestedStation, preferredHeading)
    ), 0);
    return () => window.clearTimeout(selectionTask);
  }, [detail.keyframes, navigableFrames, requestedKeyframeId, requestedViewToken, requestedWorldHeading]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !selectedFrameRef.current) return;
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(viewRef.current.fov, 1, 0.1, 1100);
    let renderer: THREE.WebGLRenderer;
    try {
      // An alpha canvas lets the still-image fallback remain visible on
      // machines where WebGL creation/rendering silently fails. This happens
      // on some remote reviewers' browsers with GPU acceleration disabled.
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      renderer.setClearColor(0x000000, 0);
    } catch {
      window.setTimeout(() => setWebglUnavailable(true), 0);
      return;
    }
    // Keep the ordinary image visible until WebGL has proven that it can
    // render the panorama. A few Windows/browser combinations create a WebGL
    // context successfully but return a completely black framebuffer.
    renderer.domElement.style.visibility = "hidden";
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);
    const geometry = new THREE.SphereGeometry(500, 60, 40);
    geometry.scale(-1, 1, 1);
    const material = new THREE.MeshBasicMaterial({ color: 0xffffff });
    scene.add(new THREE.Mesh(geometry, material));
    // Keep the portal close to Preimage's apparent size and give it a thicker
    // stroke so it remains legible against a busy construction surface.
    const hotspotGeometry = new THREE.RingGeometry(0.58, 1, 48);
    const hotspotMaterial = new THREE.MeshBasicMaterial({
      color: 0xe7efec,
      depthTest: false,
      opacity: 0.72,
      side: THREE.DoubleSide,
      transparent: true,
    });
    const hotspotMeshes: THREE.Mesh[] = [];
    // The invisible disc is slightly wider than the visible ring. This makes
    // touch/click selection forgiving without moving the true 3D destination.
    const hotspotHitGeometry = new THREE.CircleGeometry(1.22, 48);
    const hotspotHitMaterial = new THREE.MeshBasicMaterial({
      colorWrite: false,
      depthTest: false,
      depthWrite: false,
      side: THREE.DoubleSide,
      transparent: true,
    });
    const routeGuideGeometries: THREE.BufferGeometry[] = [];
    const routeGuideMeshes: THREE.Mesh[] = [];
    const routeGuideMaterial = new THREE.MeshBasicMaterial({
      color: 0x63c9f2,
      depthTest: false,
      opacity: 0.72,
      transparent: true,
    });
    let longitude = viewRef.current.longitude;
    let latitude = viewRef.current.latitude;
    let renderRequested = true;
    panoramaRuntimeRef.current = {
      scene,
      camera,
      renderer,
      sphereGeometry: geometry,
      sphereMaterial: material,
      texture: null,
      hotspotGeometry,
      hotspotMaterial,
      hotspotHitGeometry,
      hotspotHitMaterial,
      hotspotMeshes,
      routeGuideGeometries,
      routeGuideMeshes,
      routeGuideMaterial,
      invalidate: () => { renderRequested = true; },
      setView: (nextLongitude, nextLatitude, nextFov) => {
        longitude = nextLongitude;
        latitude = nextLatitude;
        camera.fov = nextFov;
        camera.updateProjectionMatrix();
        renderRequested = true;
      },
    };
    let dragging = false;
    let startX = 0;
    let startY = 0;
    let startLongitude = 0;
    let startLatitude = 0;
    let pointerMoved = false;
    let animation = 0;
    let lastViewStateEmission = 0;
    let lastEmittedView = {
      longitude: Number.NaN,
      latitude: Number.NaN,
      fov: Number.NaN,
    };
    const portalRaycaster = new THREE.Raycaster();
    const portalPointer = new THREE.Vector2();

    const portalHitAt = (clientX: number, clientY: number) => {
      const bounds = renderer.domElement.getBoundingClientRect();
      portalPointer.set(
        ((clientX - bounds.left) / bounds.width) * 2 - 1,
        -((clientY - bounds.top) / bounds.height) * 2 + 1,
      );
      camera.updateMatrixWorld();
      portalRaycaster.setFromCamera(portalPointer, camera);
      // True mesh intersections remove the screen-space ambiguity of
      // overlapping annuli. Three sorts hits nearest-first, matching what the
      // user sees in the panorama.
      return portalRaycaster.intersectObjects(hotspotMeshes, false)[0];
    };

    const resize = () => {
      const width = container.clientWidth;
      const height = container.clientHeight;
      renderer.setSize(width, height, false);
      camera.aspect = width / Math.max(height, 1);
      camera.updateProjectionMatrix();
      renderRequested = true;
    };
    const pointerDown = (event: PointerEvent) => {
      dragging = true;
      startX = event.clientX;
      startY = event.clientY;
      startLongitude = longitude;
      startLatitude = latitude;
      pointerMoved = false;
      renderer.domElement.setPointerCapture(event.pointerId);
    };
    const pointerMove = (event: PointerEvent) => {
      if (!dragging) {
        renderer.domElement.style.cursor = portalHitAt(event.clientX, event.clientY)
          ? "pointer"
          : "grab";
        return;
      }
      if (Math.abs(event.clientX - startX) > 4 || Math.abs(event.clientY - startY) > 4) {
        pointerMoved = true;
      }
      longitude = startLongitude + (startX - event.clientX) * 0.12;
      latitude = startLatitude + (event.clientY - startY) * 0.12;
      renderRequested = true;
    };
    const pointerUp = (event: PointerEvent) => {
      dragging = false;
      renderer.domElement.style.cursor = "grab";
      if (pointerMoved || !hotspotMeshes.length) return;
      const hit = portalHitAt(event.clientX, event.clientY);
      const targetId = hit?.object.userData.targetId as string | undefined;
      const routes = activeRouteVectorsRef.current;
      const selectedRoute = routes.find((route) => route.to_keyframe_id === targetId);
      const target = selectedRoute?.target;
      if (!target || !hit || !selectedRoute) return;
      renderer.domElement.dataset.lastWarpTarget = target.id;
      const sourceFrame = selectedFrameRef.current;
      const targetWorldHeading = sourceFrame?.pose
        ? visualHeading(sourceFrame) + longitude
        : longitude;
      // Full 6DoF tours have a stable world orientation, so preserving the
      // clicked heading produces the reference-tour behaviour. Stella's
      // monocular heading can drift between stations; carrying that angle to
      // the destination can put every next portal behind the camera and make
      // a successful warp look stuck. Let the destination face its nearest
      // forward route in that case, exactly as keyboard navigation does.
      selectKeyframeRef.current(
        target,
        selectedRoute.direction_source === "visual-slam-pose"
          || target.pose?.algorithm.startsWith("stella-vslam-")
          ? undefined
          : targetWorldHeading,
      );
    };
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      camera.fov = Math.min(95, Math.max(35, camera.fov + event.deltaY * 0.04));
      viewRef.current.fov = camera.fov;
      camera.updateProjectionMatrix();
      renderRequested = true;
    };
    const contextLost = (event: Event) => {
      event.preventDefault();
      renderer.domElement.style.visibility = "hidden";
      setWebglUnavailable(true);
    };
    const contextRestored = () => {
      renderer.domElement.style.visibility = "visible";
      setWebglUnavailable(false);
      renderRequested = true;
    };
    const render = (timestamp: number) => {
      if (!renderRequested && !dragging) {
        animation = requestAnimationFrame(render);
        return;
      }
      renderRequested = false;
      latitude = Math.max(-85, Math.min(85, latitude));
      viewRef.current.longitude = longitude;
      viewRef.current.latitude = latitude;
      if (viewConeRef.current && selectedFrameRef.current?.pose) {
        const planHeading = viewConePlanHeadingRef.current + longitude + 90;
        viewConeRef.current.style.transform = `translate(-50%, -88%) rotate(${planHeading}deg)`;
      }
      const phi = THREE.MathUtils.degToRad(90 - latitude);
      // The mirrored sphere maps panorama longitude 0 to -X. Adding 180° keeps
      // the viewer longitude, SfM heading and rendered texture in one frame.
      const theta = THREE.MathUtils.degToRad(longitude + 180);
      camera.lookAt(
        500 * Math.sin(phi) * Math.cos(theta),
        500 * Math.cos(phi),
        500 * Math.sin(phi) * Math.sin(theta),
      );
      camera.updateMatrixWorld();
      try {
        renderer.render(scene, camera);
      } catch {
        renderer.domElement.style.visibility = "hidden";
        setWebglUnavailable(true);
        return;
      }
      if (renderer.domElement.dataset.textureVerification === "pending") {
        let hasVisiblePixel = false;
        try {
          const context = renderer.getContext();
          const pixel = new Uint8Array(4);
          const samplePoints = [
            [0.25, 0.25], [0.5, 0.25], [0.75, 0.25],
            [0.25, 0.5], [0.5, 0.5], [0.75, 0.5],
            [0.25, 0.75], [0.5, 0.75], [0.75, 0.75],
          ];
          for (const [sampleX, sampleY] of samplePoints) {
            context.readPixels(
              Math.floor(context.drawingBufferWidth * sampleX),
              Math.floor(context.drawingBufferHeight * sampleY),
              1,
              1,
              context.RGBA,
              context.UNSIGNED_BYTE,
              pixel,
            );
            if (pixel[3] > 0 && pixel[0] + pixel[1] + pixel[2] > 24) {
              hasVisiblePixel = true;
              break;
            }
          }
        } catch {
          hasVisiblePixel = false;
        }
        if (hasVisiblePixel) {
          renderer.domElement.dataset.textureVerification = "passed";
          renderer.domElement.style.visibility = "visible";
          setWebglUnavailable(false);
        } else {
          const attempts = Number(renderer.domElement.dataset.textureVerificationAttempts ?? 0) + 1;
          renderer.domElement.dataset.textureVerificationAttempts = String(attempts);
          if (attempts >= 3) {
            renderer.domElement.dataset.textureVerification = "failed";
            renderer.domElement.style.visibility = "hidden";
            setWebglUnavailable(true);
          } else {
            renderRequested = true;
          }
        }
      }
      if (timestamp - lastViewStateEmission >= 33) {
        lastViewStateEmission = timestamp;
        const viewChanged = (
          !Number.isFinite(lastEmittedView.longitude)
          || Math.abs(longitude - lastEmittedView.longitude) >= 0.01
          || Math.abs(latitude - lastEmittedView.latitude) >= 0.01
          || Math.abs(camera.fov - lastEmittedView.fov) >= 0.01
        );
        if (viewChanged) {
          lastEmittedView = { longitude, latitude, fov: camera.fov };
          onViewStateChangeRef.current?.(lastEmittedView);
        }
      }
      animation = requestAnimationFrame(render);
    };
    resize();
    window.addEventListener("resize", resize);
    renderer.domElement.addEventListener("pointerdown", pointerDown);
    renderer.domElement.addEventListener("pointermove", pointerMove);
    renderer.domElement.addEventListener("pointerup", pointerUp);
    renderer.domElement.addEventListener("pointercancel", pointerUp);
    renderer.domElement.addEventListener("wheel", wheel, { passive: false });
    renderer.domElement.addEventListener("webglcontextlost", contextLost);
    renderer.domElement.addEventListener("webglcontextrestored", contextRestored);
    render(performance.now());
    return () => {
      cancelAnimationFrame(animation);
      window.removeEventListener("resize", resize);
      renderer.domElement.removeEventListener("webglcontextlost", contextLost);
      renderer.domElement.removeEventListener("webglcontextrestored", contextRestored);
      panoramaRuntimeRef.current?.texture?.dispose();
      geometry.dispose();
      material.dispose();
      hotspotGeometry.dispose();
      hotspotMaterial.dispose();
      hotspotHitGeometry.dispose();
      hotspotHitMaterial.dispose();
      for (const routeGeometry of routeGuideGeometries) routeGeometry.dispose();
      routeGuideMaterial.dispose();
      renderer.dispose();
      renderer.domElement.remove();
      if (panoramaRuntimeRef.current?.renderer === renderer) {
        panoramaRuntimeRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    const runtime = panoramaRuntimeRef.current;
    const selectedFrame = selectedFrameRef.current;
    if (!runtime || !selectedFrame) return;
    let cancelled = false;

    const applyImage = (image: HTMLImageElement) => {
      if (cancelled || panoramaRuntimeRef.current !== runtime) return;
      const nextTexture = new THREE.Texture(image);
      nextTexture.colorSpace = THREE.SRGBColorSpace;
      nextTexture.minFilter = THREE.LinearFilter;
      nextTexture.magFilter = THREE.LinearFilter;
      nextTexture.generateMipmaps = false;
      nextTexture.needsUpdate = true;
      const previousTexture = runtime.texture;
      runtime.texture = nextTexture;
      runtime.sphereMaterial.map = nextTexture;
      runtime.sphereMaterial.needsUpdate = true;
      previousTexture?.dispose();
      runtime.renderer.domElement.style.visibility = "hidden";
      runtime.renderer.domElement.dataset.textureVerification = "pending";
      runtime.renderer.domElement.dataset.textureVerificationAttempts = "0";
      setWebglUnavailable(false);
      runtime.invalidate();
    };

    const preloadedImage = preloadedImageRef.current?.keyframeId === selectedFrame.id
      ? preloadedImageRef.current.image
      : null;
    if (preloadedImage) {
      applyImage(preloadedImage);
    } else {
      const image = new window.Image();
      image.crossOrigin = "anonymous";
      image.decoding = "async";
      image.onload = () => applyImage(image);
      image.onerror = () => {
        if (!cancelled) {
          setError("โหลดภาพ 360 ไม่สำเร็จ ระบบยังคงแสดงภาพเดิม");
        }
      };
      image.src = keyframeImageUrl(selectedFrame);
    }

    return () => {
      cancelled = true;
    };
  // Parent polling can replace `detail` with an equivalent object. Depending
  // on the full selected-frame object made Three.js rebuild the same 4K
  // texture on every poll, producing the visible flash and unnecessary GPU
  // allocations. A panorama texture changes only when its keyframe id changes.
  }, [keyframeImageUrl, selectedId]);

  useEffect(() => {
    const runtime = panoramaRuntimeRef.current;
    if (!runtime) return;

    for (const hotspot of runtime.hotspotMeshes) runtime.scene.remove(hotspot);
    for (const guide of runtime.routeGuideMeshes) runtime.scene.remove(guide);
    for (const geometry of runtime.routeGuideGeometries) geometry.dispose();
    runtime.hotspotMeshes.length = 0;
    runtime.routeGuideMeshes.length = 0;
    runtime.routeGuideGeometries.length = 0;

    if (!selected?.pose) {
      runtime.invalidate();
      return;
    }
    const visualZ = Number(selected.pose.visual_z);
    const visualGroundZ = Number(selected.pose.visual_ground_z);
    const reconstructedCameraHeight = selected.pose.visual_z !== null
      && selected.pose.visual_ground_z !== null
      && Number.isFinite(visualZ)
      && Number.isFinite(visualGroundZ)
      ? Math.abs(visualZ - visualGroundZ)
      : null;
    for (const route of activeRouteVectorsRef.current) {
      const placement = groundPortalPlacement({
        distance: route.distance,
        localYawDeg: route.local_yaw_deg,
        reconstructedCameraHeight,
        fallbackStep: medianRouteDistanceRef.current,
      });
      const targetGround = new THREE.Vector3(
        placement.x,
        placement.y,
        placement.z,
      );
      const hotspot = new THREE.Mesh(runtime.hotspotGeometry, runtime.hotspotMaterial);
      hotspot.position.copy(targetGround);
      // Full-pose routes already point at the reconstructed floor handle.
      // Face the annulus toward the source camera so pitch/roll cannot collapse
      // the target into an unclickable line in the panorama.
      hotspot.rotation.x = -Math.PI / 2;
      hotspot.scale.setScalar(placement.radius);
      hotspot.renderOrder = 3;
      hotspot.userData.targetId = route.to_keyframe_id;
      runtime.hotspotMeshes.push(hotspot);
      runtime.scene.add(hotspot);

      const hitTarget = new THREE.Mesh(
        runtime.hotspotHitGeometry,
        runtime.hotspotHitMaterial,
      );
      hitTarget.position.copy(targetGround);
      hitTarget.rotation.x = -Math.PI / 2;
      hitTarget.scale.setScalar(placement.radius);
      hitTarget.userData.targetId = route.to_keyframe_id;
      runtime.hotspotMeshes.push(hitTarget);
      runtime.scene.add(hitTarget);

    }
    runtime.invalidate();
  }, [activeRouteVectors, medianRouteDistance, selected?.pose]);

  function selectByIndex(index: number) {
    const boundedIndex = Math.min(navigableFrames.length - 1, Math.max(0, index));
    const frame = navigableFrames[boundedIndex];
    if (frame) selectKeyframe(frame);
  }

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "ArrowLeft") selectByIndex(selectedIndex - 1);
      if (event.key === "ArrowRight") selectByIndex(selectedIndex + 1);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  });

  useEffect(() => {
    if (!isPlaying) return;
    const timer = window.setTimeout(() => {
      const frame = navigableFrames[selectedIndex + 1];
      if (frame) selectKeyframe(frame);
      else setIsPlaying(false);
    }, 900);
    return () => window.clearTimeout(timer);
  }, [isPlaying, navigableFrames, selectKeyframe, selectedIndex]);

  async function startLocalization() {
    setBusy(true);
    setError(null);
    setMapExpanded(false);
    setAligning(false);
    const response = await fetch(
      `/api/projects/${projectId}/captures/${detail.capture.id}/localization`,
      { method: "POST" },
    );
    const body = await response.json().catch(() => ({}));
    if (!response.ok) setError(body.detail || "เริ่มคำนวณเส้นทางไม่สำเร็จ");
    else router.refresh();
    setBusy(false);
  }

  const visualFloorFrames = floorFrames.filter((frame) => (
    frame.pose?.visual_x !== null && frame.pose?.visual_y !== null
  ));
  const originFrame = visualFloorFrames[0] ?? null;
  // The API's x/y values are the authoritative plan positions, even while a
  // low-confidence localization is waiting for human review.  Falling back to
  // a second browser-side transform here made the map show a different,
  // tightly-clustered route from the one Stella/localization actually saved.
  // Only render the visual-coordinate preview while the user is actively
  // adjusting the rigid transform.
  const useVisualPreview = aligning;
  // Review-required routes must remain visible. Hiding every saved pose until
  // alignment was verified reduced the map to a single S marker and prevented
  // the reviewer from checking or correcting the route point by point.
  const showSavedPlanRoute = posedFrames.length > 0;
  const displayFramePositions = new Map<string, PlanPosition>();
  for (const frame of floorFrames) {
    if (!frame.pose) continue;
    if (!useVisualPreview) {
      if (!showSavedPlanRoute) continue;
      displayFramePositions.set(frame.id, {
        x: Number(frame.pose.x),
        y: Number(frame.pose.y),
        headingDeg: Number(frame.pose.heading_deg),
      });
      continue;
    }
    if (!originFrame) continue;
    const position = transformVisualPose(
      frame,
      originFrame,
      Number(detail.capture.start_x),
      Number(detail.capture.start_y),
      draftScaleX,
      draftScaleY,
      draftRotation,
      draftMirror,
      draftOffsetX,
      draftOffsetY,
    );
    if (position) displayFramePositions.set(frame.id, position);
  }
  const displayPathPoints = useVisualPreview
    ? visualFloorFrames.flatMap((frame) => {
      const position = displayFramePositions.get(frame.id);
      return position ? [{ timestamp_ms: frame.timestamp_ms, ...position }] : [];
    })
    : showSavedPlanRoute ? floorPathPoints.map((point) => ({
      timestamp_ms: point.timestamp_ms,
      x: Number(point.x),
      y: Number(point.y),
      headingDeg: Number(point.heading_deg),
    })) : [];
  const pathLeavesPlan = displayPathPoints.some((point) => (
    point.x < 0 || point.x > 1 || point.y < 0 || point.y > 1
  ));
  // A SLAM trajectory can have substantially different scale on each axis,
  // especially before enough captures have been calibrated. Keep the sliders
  // wide enough for the first manual alignment while staying inside the API's
  // accepted range (0 < scale <= 10).
  const scaleXMin = Math.max(0.00001, suggestedTransform.scaleX * 0.01);
  const scaleXMax = Math.min(10, Math.max(scaleXMin * 2, suggestedTransform.scaleX * 10));
  const scaleYMin = Math.max(0.00001, suggestedTransform.scaleY * 0.01);
  const scaleYMax = Math.min(10, Math.max(scaleYMin * 2, suggestedTransform.scaleY * 10));

  function toggleRigidAlignment() {
    if (!aligning) {
      setDraftScaleX(suggestedTransform.scaleX);
      setDraftScaleY(suggestedTransform.scaleY);
      setDraftRotation(suggestedTransform.rotationDeg);
      setDraftMirror(suggestedTransform.mirror);
      setDraftOffsetX(suggestedTransform.offsetX);
      setDraftOffsetY(suggestedTransform.offsetY);
      setMapExpanded(true);
      setControlPointMode(false);
      setEvaluationMode(false);
      setStartPointMode(false);
      setError(null);
    }
    setAligning((value) => !value);
  }

  async function saveRigidAlignment() {
    if (pathLeavesPlan) {
      setError("เส้นทางออกนอกแปลน กรุณาลด Scale หรือปรับ Rotation");
      return;
    }
    setBusy(true);
    setError(null);
    const response = await fetch(
      `/api/projects/${projectId}/captures/${detail.capture.id}/path-transform`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          floor_id: activeFloorId,
          scale_x: draftScaleX,
          scale_y: draftScaleY,
          rotation_deg: draftRotation,
          mirror: draftMirror,
          offset_x: draftOffsetX,
          offset_y: draftOffsetY,
        }),
      },
    );
    const body = await response.json().catch(() => ({}));
    if (!response.ok) setError(body.detail || "บันทึกการจัดแนวเส้นทางไม่สำเร็จ");
    else {
      setAligning(false);
      router.refresh();
    }
    setBusy(false);
  }

  async function confirmVirtualTour() {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/projects/${projectId}/captures/${detail.capture.id}/poses/confirm`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ floor_id: activeFloorId }),
        },
      );
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || "ยืนยัน Virtual Tour ไม่สำเร็จ");
      router.refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "ยืนยัน Virtual Tour ไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  function toggleControlPointMode() {
    if (!controlPointMode) {
      setAligning(false);
      setEvaluationMode(false);
      setStartPointMode(false);
      setMapExpanded(true);
      setDraftControlPoints((detail.control_points ?? []).map((point) => ({
        keyframeId: point.keyframe_id,
        x: Number(point.x),
        y: Number(point.y),
      })));
      setError(null);
    }
    setControlPointMode((value) => !value);
  }

  function toggleEvaluationMode() {
    if (!evaluationMode) {
      setAligning(false);
      setControlPointMode(false);
      setStartPointMode(false);
      setMapExpanded(true);
      setDraftEvaluationPoints((detail.evaluation_points ?? []).map((point) => ({
        keyframeId: point.keyframe_id,
        x: Number(point.target_x),
        y: Number(point.target_y),
      })));
      setError(null);
    }
    setEvaluationMode((value) => !value);
  }

  function toggleStartPointMode() {
    if (!startPointMode) {
      const firstFrame = floorFrames[0];
      setAligning(false);
      setControlPointMode(false);
      setEvaluationMode(false);
      setMapExpanded(true);
      setIsPlaying(false);
      setDraftStartPoint({
        x: firstFrame?.pose ? Number(firstFrame.pose.x) : Number(detail.capture.start_x),
        y: firstFrame?.pose ? Number(firstFrame.pose.y) : Number(detail.capture.start_y),
      });
      if (firstFrame) selectKeyframe(firstFrame);
      setError(null);
    }
    setStartPointMode((value) => !value);
  }

  async function saveStartPoint() {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/projects/${projectId}/captures/${detail.capture.id}/start-point`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            floor_id: activeFloorId,
            x: draftStartPoint.x,
            y: draftStartPoint.y,
          }),
        },
      );
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || "บันทึกจุดเริ่มต้นไม่สำเร็จ");
      setStartPointMode(false);
      router.refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "บันทึกจุดเริ่มต้นไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  function removeEvaluationPoint(keyframeId: string) {
    setDraftEvaluationPoints((points) => (
      points.filter((point) => point.keyframeId !== keyframeId)
    ));
  }

  async function saveEvaluationPoints() {
    if (draftEvaluationPoints.length < 5 || draftEvaluationPoints.length > 100) return;
    setBusy(true);
    setError(null);
    const response = await fetch(
      `/api/projects/${projectId}/captures/${detail.capture.id}/path-evaluation-points`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          floor_id: activeFloorId,
          tolerance_normalized: 0.03,
          evaluation_points: draftEvaluationPoints.map((point) => ({
            keyframe_id: point.keyframeId,
            target_x: point.x,
            target_y: point.y,
          })),
        }),
      },
    );
    const body = await response.json().catch(() => ({}));
    if (!response.ok) setError(body.detail || "บันทึก Ground Truth สำหรับวัดผลไม่สำเร็จ");
    else {
      setEvaluationMode(false);
      router.refresh();
    }
    setBusy(false);
  }

  function removeControlPoint(keyframeId: string) {
    setDraftControlPoints((points) => (
      points.filter((point) => point.keyframeId !== keyframeId)
    ));
  }

  async function fitFromControlPoints() {
    if (draftControlPoints.length < 3 || draftControlPoints.length > 5) return;
    setBusy(true);
    setError(null);
    const response = await fetch(
      `/api/projects/${projectId}/captures/${detail.capture.id}/path-control-points/fit`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          floor_id: activeFloorId,
          control_points: draftControlPoints.map((point) => ({
            keyframe_id: point.keyframeId,
            x: point.x,
            y: point.y,
          })),
        }),
      },
    );
    const body = await response.json().catch(() => ({}));
    if (!response.ok) setError(body.detail || "คำนวณจากจุดตรวจสอบไม่สำเร็จ");
    else {
      setControlPointMode(false);
      router.refresh();
    }
    setBusy(false);
  }

  function handlePlanClick(event: MouseEvent<HTMLDivElement>) {
    if (aligning) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const x = Math.min(1, Math.max(0, (event.clientX - bounds.left) / bounds.width));
    const y = Math.min(1, Math.max(0, (event.clientY - bounds.top) / bounds.height));
    if (startPointMode) {
      setDraftStartPoint({ x, y });
      setError(null);
      return;
    }
    if (controlPointMode) {
      if (!selected?.pose || selected.pose.floor_id !== activeFloorId) {
        setError("กรุณาเลือกภาพที่อยู่ในชั้นนี้ก่อนระบุตำแหน่งจริง");
        return;
      }
      setDraftControlPoints((points) => {
        const existing = points.findIndex((point) => point.keyframeId === selected.id);
        if (existing >= 0) {
          return points.map((point, index) => (
            index === existing ? { keyframeId: selected.id, x, y } : point
          ));
        }
        if (points.length >= 5) return points;
        return [...points, { keyframeId: selected.id, x, y }];
      });
      setError(null);
      return;
    }
    if (evaluationMode) {
      if (!selected?.pose || selected.pose.floor_id !== activeFloorId) {
        setError("กรุณาเลือกภาพที่อยู่ในชั้นนี้ก่อนระบุตำแหน่งจริง");
        return;
      }
      if (detail.control_points.some((point) => point.keyframe_id === selected.id)) {
        setError("ภาพนี้ใช้สอบเทียบเส้นทางแล้ว กรุณาเลือกภาพอื่นสำหรับวัดผล");
        return;
      }
      setDraftEvaluationPoints((points) => {
        const existing = points.findIndex((point) => point.keyframeId === selected.id);
        if (existing >= 0) {
          return points.map((point, index) => (
            index === existing ? { keyframeId: selected.id, x, y } : point
          ));
        }
        if (points.length >= 100) return points;
        return [...points, { keyframeId: selected.id, x, y }];
      });
      setError(null);
      return;
    }
    const nearestPathPoint = displayPathPoints.reduce<(typeof displayPathPoints)[number] | null>(
      (nearest, point) => {
        if (!nearest) return point;
        const pointDistance = (point.x - x) ** 2 + (point.y - y) ** 2;
        const nearestDistance = (nearest.x - x) ** 2 + (nearest.y - y) ** 2;
        return pointDistance < nearestDistance ? point : nearest;
      }, null,
    );
    if (!nearestPathPoint) return;
    const nearestFrame = visibleFloorStations.reduce<Keyframe | null>((nearest, frame) => {
      if (!nearest) return frame;
      return Math.abs(frame.timestamp_ms - nearestPathPoint.timestamp_ms)
        < Math.abs(nearest.timestamp_ms - nearestPathPoint.timestamp_ms) ? frame : nearest;
    }, null);
    if (nearestFrame) selectKeyframe(nearestFrame);
  }

  function handleTransformPointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (!aligning) return;
    transformDragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      offsetX: draftOffsetX,
      offsetY: draftOffsetY,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    event.preventDefault();
  }

  function handleTransformPointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    const drag = transformDragRef.current;
    if (!aligning || !drag || drag.pointerId !== event.pointerId) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const nextX = drag.offsetX + (event.clientX - drag.startX) / bounds.width;
    const nextY = drag.offsetY + (event.clientY - drag.startY) / bounds.height;
    setDraftOffsetX(Math.max(-1, Math.min(1, nextX)));
    setDraftOffsetY(Math.max(-1, Math.min(1, nextY)));
  }

  function handleTransformPointerUp(event: ReactPointerEvent<HTMLDivElement>) {
    if (transformDragRef.current?.pointerId !== event.pointerId) return;
    transformDragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  const polyline = displayPathPoints
    .map((point) => `${point.x * 1000},${point.y * 1000}`)
    .join(" ");
  const selectedDisplayPosition = selected
    ? displayFramePositions.get(selected.id) ?? null
    : null;
  useEffect(() => {
    viewConePlanHeadingRef.current = selectedDisplayPosition?.headingDeg ?? 0;
  }, [selectedDisplayPosition?.headingDeg]);
  return (
    <div className="spatial-review openspace-viewer">
      <div className="viewer-main" data-route-count={activeRouteVectors.length} data-tour-station-id={selected?.id ?? ""}>
        {selected ? <div className="panorama-canvas" ref={containerRef}>
          <Image
            alt={`ภาพ 360 จุดที่ ${selected.frame_index + 1}`}
            className="panorama-fallback-image"
            fill
            key={selected.id}
            priority
            sizes="100vw"
            src={keyframeImageUrl(selected)}
            unoptimized
          />
          {webglUnavailable && <span className="panorama-compatibility-note">กำลังแสดงภาพสำรอง — เปิด Hardware acceleration เพื่อหมุนภาพ 360°</span>}
        </div> : <div className="viewer-empty">ยังไม่มีภาพ 360 — รอการประมวลผลไฟล์ต้นทางให้เสร็จ</div>}
        {selected && <div className="virtual-tour-badge"><strong>Virtual Tour · จุด {selectedStationNumber}</strong><span>{activeRouteVectors.length} จุดที่เดินต่อได้จากตำแหน่งนี้ · {navigableFrames.length} จุดวาร์ปทั้งหมด</span></div>}

        <section className={`capture-map-panel floating-map ${mapExpanded ? "is-expanded" : ""} ${aligning ? "is-aligning" : ""}`}>
          <div className="capture-map-toolbar">
            <div><strong>{activeFloor?.name ?? "Floor"}</strong><small>{hasUnalignedPlanRoute ? `ยังไม่ระบุตำแหน่งบนแปลน · ${visibleFloorStations.length} สถานี Virtual Tour` : `${visibleFloorStations.length} สถานี Virtual Tour · ${floorPathPoints.length} จุดเส้นทาง`}</small>{hasUnalignedPlanRoute ? <span className="anchor-alignment-badge">มีเส้นทางสัมพัทธ์ · รอจับตำแหน่งกับแปลน</span> : isHoldout ? <span className="holdout-badge">HOLDOUT TEST · วัด Ground Truth เฉพาะชุดทดสอบ</span> : humanAlignmentVerified ? <span className="auto-alignment-badge">ผู้ตรวจยืนยันตำแหน่งครบแล้ว</span> : persistentMapMatch ? <span className={persistentMapMatch.accepted ? "auto-alignment-badge" : "anchor-alignment-badge"}>AI ใช้แผนที่สะสม · {persistentMapMatch.anchorCount} จุดอ้างอิง{persistentMapMatch.accepted ? " · รอตรวจ Virtual Tour" : " · ความมั่นใจต่ำ"}</span> : alignmentVerified ? <span className="anchor-alignment-badge">ระบบจัดตำแหน่งแล้ว · รอตรวจ Virtual Tour</span> : anchorMatchCount > 0 && <span className="anchor-alignment-badge">AI จับคู่ Landmark {anchorMatchCount} จุดอ้างอิง · รอตรวจ Virtual Tour</span>}</div>
            <button aria-expanded={mapToolsOpen} aria-label="เครื่องมือแผนที่" className={`map-tools-toggle ${mapToolsOpen ? "is-active" : ""}`} onClick={() => setMapToolsOpen((value) => !value)} title="เครื่องมือแผนที่" type="button">•••</button>
            <select aria-label="ชั้นที่แสดงบนแปลน" onChange={(event) => setActiveFloorId(event.target.value)} value={activeFloorId}>
              {floors.map((floor) => <option key={floor.id} value={floor.id}>{floor.name}</option>)}
            </select>
            {planInfo && planInfo.page_count > 1 && <label className="plan-page-selector">
              <span>หน้า</span>
              <select aria-label="เลือกหน้า PDF ของแปลน" disabled={busy} onChange={changeFloorPlanPage} value={planInfo.page_number}>
                {Array.from({ length: planInfo.page_count }, (_, index) => index + 1).map((page) => <option key={page} value={page}>{page} / {planInfo.page_count}</option>)}
              </select>
            </label>}
            <button aria-label={mapExpanded ? "กลับไปภาพ 360" : "ขยายแปลน"} className={`map-expand ${mapExpanded ? "is-return" : ""}`} onClick={() => setMapExpanded((value) => !value)} type="button">{mapExpanded ? "กลับภาพ 360" : "⛶"}</button>
          </div>
          {(mapToolsOpen || aligning || controlPointMode || evaluationMode || startPointMode) && <div className="map-tools-menu">
            {canEdit && <button className="map-align" disabled={busy} onClick={() => planFileInputRef.current?.click()} type="button">{hasConfiguredPlan ? "เปลี่ยนแปลน" : "อัปโหลดแปลน"}</button>}
            {canEdit && posedFrames.length > 0 && <button className={`map-align ${startPointMode ? "is-active" : ""}`} disabled={busy} onClick={toggleStartPointMode} type="button">{startPointMode ? "ยกเลิกแก้จุดเริ่มต้น" : "แก้จุดเริ่มต้น"}</button>}
            {startPointMode && <button className="map-align map-save" disabled={busy} onClick={saveStartPoint} type="button">{busy ? "กำลังบันทึก..." : "บันทึกจุดเริ่มต้น"}</button>}
            {showCalibrationTools && posedFrames.length > 0 && !aligning && !startPointMode && <button className={`map-align ${controlPointMode ? "is-active" : ""}`} disabled={busy} onClick={toggleControlPointMode} type="button">{controlPointMode ? "ยกเลิกกำหนดตำแหน่งจริง" : "กำหนดตำแหน่งจริง 3–5 จุด"}</button>}
            {showEvaluationTools && posedFrames.length > 0 && !aligning && !startPointMode && <button className={`map-align ${evaluationMode ? "is-active" : ""}`} disabled={busy} onClick={toggleEvaluationMode} type="button">{evaluationMode ? "ยกเลิกวัดผล" : "วัดผล Ground Truth"}</button>}
            {canAdjustPath && aligning && <button className="map-align map-save" disabled={busy || pathLeavesPlan} onClick={saveRigidAlignment} type="button">{busy ? "กำลังบันทึก..." : "บันทึกเส้นทาง"}</button>}
            {canAdjustPath && posedFrames.length > 0 && <button className={`map-align ${aligning ? "is-active" : ""}`} disabled={busy} onClick={toggleRigidAlignment} type="button">{aligning ? "ยกเลิกปรับแนว" : alignmentVerified ? "แก้แนวขั้นสูง (ไม่จำเป็น)" : "ปรับแนวเส้นทาง"}</button>}
            {canAdjustPath && <button className="map-align" disabled={busy || processingActive} onClick={startLocalization} type="button">{processingActive ? "กำลังประมวลผล..." : "คำนวณ AI ใหม่"}</button>}
          </div>}
          <input accept=".pdf,image/png,image/jpeg,image/webp" hidden onChange={uploadFloorPlan} ref={planFileInputRef} type="file" />
          <div className={`capture-plan ${aligning ? "is-editing" : ""} ${startPointMode ? "is-setting-start" : ""} ${alignmentVerified && !aligning ? "is-verified" : "is-unverified"}`} onClick={handlePlanClick} onPointerCancel={handleTransformPointerUp} onPointerDown={handleTransformPointerDown} onPointerMove={handleTransformPointerMove} onPointerUp={handleTransformPointerUp} role="presentation">
            {hasConfiguredPlan
              ? <Image alt={`แปลน ${activeFloor?.name ?? "ชั้นอาคาร"}`} fill priority sizes={mapExpanded ? "80vw" : "35vw"} src={`/api/projects/${projectId}/floors/${activeFloorId}/plan?v=${planRevision}`} unoptimized />
              : <div className="missing-floor-plan"><strong>{activeFloor?.name}</strong><span>ยังไม่ได้อัปโหลดแปลนของชั้นนี้</span>{canEdit && <button className="button button-primary" disabled={busy} onClick={(event) => { event.stopPropagation(); planFileInputRef.current?.click(); }} type="button">{busy ? "กำลังอัปโหลด..." : "อัปโหลด PDF หรือรูปภาพ"}</button>}</div>}
            <svg aria-hidden="true" className="capture-path-layer" preserveAspectRatio="none" viewBox="0 0 1000 1000">
              {displayPathPoints.length > 1 && <polyline points={polyline} />}
            </svg>
            {startPointMode && (
              <span
                aria-label="จุดเริ่มต้นใหม่"
                className="capture-start-position is-draft"
                style={{ left: `${draftStartPoint.x * 100}%`, top: `${draftStartPoint.y * 100}%` }}
                title="จุดเริ่มต้นใหม่"
              >S</span>
            )}
            {!startPointMode && (!posedFrames.length || hasUnalignedPlanRoute) && !aligning && detail.capture.start_floor_id === activeFloorId && (
              <span
                aria-label="จุดเริ่มต้นที่เลือก"
                className="capture-start-position"
                style={{
                  left: `${Number(detail.capture.start_x) * 100}%`,
                  top: `${Number(detail.capture.start_y) * 100}%`,
                }}
                title="จุดเริ่มต้นที่เลือก"
              >S</span>
            )}
            {selectedDisplayPosition && selected?.pose?.floor_id === activeFloorId && <><span className="current-view-cone" ref={viewConeRef} style={{ left: `${selectedDisplayPosition.x * 100}%`, top: `${selectedDisplayPosition.y * 100}%`, transform: `translate(-50%, -88%) rotate(${selectedDisplayPosition.headingDeg + 90}deg)` }} /><span aria-label="ตำแหน่งภาพปัจจุบัน" className="current-path-position" style={{ left: `${selectedDisplayPosition.x * 100}%`, top: `${selectedDisplayPosition.y * 100}%` }} /></>}
            {visibleFloorStations.map((frame, index) => {
              const pose = frame.pose!;
              const displayPosition = displayFramePositions.get(frame.id);
              if (!displayPosition) return null;
              const confidence = Number(pose.confidence);
              const className = ["warp-point", selected?.id === frame.id ? "is-selected" : "", pose.needs_review ? "is-low-confidence" : "", pose.reviewed_at ? "is-reviewed" : ""].filter(Boolean).join(" ");
              return <button aria-label={`จุดวาร์ป ${index + 1} เวลา ${timeLabel(frame.timestamp_ms)} ความมั่นใจ ${Math.round(confidence * 100)}%`} className={className} key={frame.id} onClick={(event) => {
                // Editing gestures belong to the plan, even when a dense route
                // station sits under the pointer. Normal review clicks still
                // open the selected 360 station.
                if (startPointMode || aligning) return;
                event.stopPropagation();
                selectKeyframe(frame);
              }} onKeyDown={(event) => {
                if (event.key !== "Enter" && event.key !== " ") return;
                event.preventDefault();
                event.stopPropagation();
                if (startPointMode || aligning) return;
                selectKeyframe(frame);
              }} style={{ left: `${displayPosition.x * 100}%`, top: `${displayPosition.y * 100}%` }} title={`${timeLabel(frame.timestamp_ms)} · ${confidenceLabel(frame)}`} type="button"><span /></button>;
            })}
            {draftControlPoints.map((point, index) => {
              const frame = detail.keyframes.find((item) => item.id === point.keyframeId);
              return <button aria-label={`จุดตรวจสอบ ${index + 1}`} className="control-point-target" key={point.keyframeId} onClick={(event) => { event.stopPropagation(); if (frame) selectKeyframe(frame); }} style={{ left: `${point.x * 100}%`, top: `${point.y * 100}%` }} title={`จุดตรวจ ${index + 1} · ${frame ? timeLabel(frame.timestamp_ms) : ""}`} type="button">{index + 1}</button>;
            })}
            {draftEvaluationPoints.map((point, index) => {
              const frame = detail.keyframes.find((item) => item.id === point.keyframeId);
              return <button aria-label={`Ground Truth ${index + 1}`} className="evaluation-point-target" key={point.keyframeId} onClick={(event) => { event.stopPropagation(); if (frame) selectKeyframe(frame); }} style={{ left: `${point.x * 100}%`, top: `${point.y * 100}%` }} title={`Ground Truth ${index + 1} · ${frame ? timeLabel(frame.timestamp_ms) : ""}`} type="button">{index + 1}</button>;
            })}
          </div>
          {hasUnalignedPlanRoute && !aligning ? <div className="alignment-warning">{usesRepeatedRouteDraft ? "เส้นสีส้มเป็นฉบับรอตรวจที่เทียบรูปทรงกับวันก่อนหน้า ไม่ใช่ตำแหน่งกล้องจริงที่ยืนยันแล้ว" : `${usesRigTrajectory ? "ระบบ 360 rig" : "Stella VSLAM"} คำนวณได้เพียงเส้นทางสัมพัทธ์`} จุดเริ่มต้นเพียงจุดเดียวไม่สามารถระบุทิศ หมุน และสเกลบนแปลนได้ครบ กรุณากด “กำหนดตำแหน่งจริง 3–5 จุด” และระบุตำแหน่งช่วงต้น–กลาง–ปลายก่อนนำไปตรวจ Progress</div> : isHoldout ? <div className="holdout-warning">ชุดทดสอบถูกล็อกไว้ ระบบจะแสดงผลเดิมและอนุญาตเฉพาะการบันทึก Ground Truth เพื่อวัด Accuracy</div> : posedFrames.length > 0 && !alignmentVerified && <div className="alignment-warning">เส้นสีส้มคือเส้นทางสัมพัทธ์จาก {usesRigTrajectory ? "360 rig" : "Stella VSLAM"} ซึ่งยังต้องจับตำแหน่งกับแปลนก่อนใช้อ้างอิง</div>}
          {detail.evaluation_summary && <div className={`evaluation-summary ${detail.evaluation_summary.is_ready ? "is-ready" : ""}`}><strong>{isHoldout ? "Localization Accuracy" : "ความสอดคล้องกับจุดอ้างอิงบนแปลน"} {Number(detail.evaluation_summary.accuracy_percent).toFixed(1)}%</strong><span>{detail.evaluation_summary.within_tolerance_count}/{detail.evaluation_summary.point_count} จุดคลาดเคลื่อนไม่เกิน 3% ของแปลน · {isHoldout ? (detail.evaluation_summary.is_ready ? "พร้อมใช้รายงานผล" : `ต้องมีอย่างน้อย ${detail.evaluation_summary.required_point_count} จุด`) : "ใช้จัดแนวการเดิน ไม่ใช่ค่าพิกัดจากงานสำรวจ"}</span></div>}
          {aligning && <div className="rigid-transform-controls">
            <label><span>Scale X <strong>{draftScaleX.toFixed(4)}</strong></span><input aria-label="Scale X เส้นทาง Stella" max={scaleXMax} min={scaleXMin} onChange={(event) => setDraftScaleX(Number(event.target.value))} step={(scaleXMax - scaleXMin) / 1000} type="range" value={draftScaleX} /></label>
            <label><span>Scale Y <strong>{draftScaleY.toFixed(4)}</strong></span><input aria-label="Scale Y เส้นทาง Stella" max={scaleYMax} min={scaleYMin} onChange={(event) => setDraftScaleY(Number(event.target.value))} step={(scaleYMax - scaleYMin) / 1000} type="range" value={draftScaleY} /></label>
            <label><span>Rotation <strong>{draftRotation.toFixed(1)}°</strong></span><input aria-label="Rotation เส้นทาง Stella" max="180" min="-180" onChange={(event) => setDraftRotation(Number(event.target.value))} step="1" type="range" value={draftRotation} /></label>
            <label><span>เลื่อน X <strong>{(draftOffsetX * 100).toFixed(1)}%</strong></span><input aria-label="เลื่อนเส้นทางแนวนอน" max="1" min="-1" onChange={(event) => setDraftOffsetX(Number(event.target.value))} step="0.001" type="range" value={draftOffsetX} /></label>
            <label><span>เลื่อน Y <strong>{(draftOffsetY * 100).toFixed(1)}%</strong></span><input aria-label="เลื่อนเส้นทางแนวตั้ง" max="1" min="-1" onChange={(event) => setDraftOffsetY(Number(event.target.value))} step="0.001" type="range" value={draftOffsetY} /></label>
            <div className="rigid-transform-actions"><button aria-pressed={draftMirror} className={`button button-secondary ${draftMirror ? "is-active" : ""}`} disabled={busy} onClick={() => setDraftMirror((value) => !value)} type="button">{draftMirror ? "Mirror: เปิด" : "กลับด้าน Mirror"}</button><button className="button button-secondary" disabled={busy} onClick={toggleRigidAlignment} type="button">ยกเลิก</button><button className="button button-primary" disabled={busy || pathLeavesPlan} onClick={saveRigidAlignment} type="button">บันทึกทั้งเส้นทาง</button></div>
          </div>}
          {controlPointMode && <div className="control-point-panel"><div><strong>{draftControlPoints.length}/5 จุด</strong><span>คลิกจุดบนเส้นทางเพื่อเลือกภาพ แล้วคลิกตำแหน่งจริงบนแปลน จุดควรกระจายช่วงต้น–กลาง–ปลาย</span></div><div className="control-point-list">{draftControlPoints.map((point, index) => { const frame = detail.keyframes.find((item) => item.id === point.keyframeId); return <button key={point.keyframeId} onClick={() => removeControlPoint(point.keyframeId)} title="ลบจุดนี้" type="button"><b>{index + 1}</b>{frame ? timeLabel(frame.timestamp_ms) : ""}<i>×</i></button>; })}</div><div className="control-point-actions"><button className="button button-secondary" disabled={busy} onClick={toggleControlPointMode} type="button">ยกเลิก</button><button className="button button-primary" disabled={busy || draftControlPoints.length < 3 || draftControlPoints.length > 5} onClick={fitFromControlPoints} type="button">Auto-fit และบันทึก</button></div></div>}
          {evaluationMode && <div className="control-point-panel evaluation-point-panel"><div><strong>{draftEvaluationPoints.length}/20 จุดวัดผล</strong><span>เลือกภาพที่ไม่ใช่จุดสอบเทียบ แล้วคลิกตำแหน่งจริงบนแปลน เริ่มบันทึกได้ที่ 5 จุดและพร้อมรายงานเมื่อครบ 20 จุด</span></div><div className="control-point-list">{draftEvaluationPoints.map((point, index) => { const frame = detail.keyframes.find((item) => item.id === point.keyframeId); return <button key={point.keyframeId} onClick={() => removeEvaluationPoint(point.keyframeId)} title="ลบจุดนี้" type="button"><b>{index + 1}</b>{frame ? timeLabel(frame.timestamp_ms) : ""}<i>×</i></button>; })}</div><div className="control-point-actions"><button className="button button-secondary" disabled={busy} onClick={toggleEvaluationMode} type="button">ยกเลิก</button><button className="button button-primary" disabled={busy || draftEvaluationPoints.length < 5} onClick={saveEvaluationPoints} type="button">บันทึกและคำนวณ Accuracy</button></div></div>}
          {(aligning || controlPointMode || evaluationMode || startPointMode || mapExpanded) && <p className="map-help">{startPointMode ? "กำลังใช้ภาพวินาที 0 — คลิกตำแหน่งกล้องจริงบนแปลน แล้วกดบันทึก เส้นทางทั้งก้อนจะเลื่อนตาม" : controlPointMode ? "จุดสอบเทียบใช้ปรับเส้นทางและจะไม่ถูกนำไปวัด Accuracy" : evaluationMode ? "เลือกจุดบนเส้นทางเพื่อเปิดภาพ แล้วคลิกตำแหน่งจริงของกล้องบนแปลน" : aligning ? pathLeavesPlan ? "เส้นทางออกนอกแปลน — ลด Scale X/Y, หมุน หรือลากทั้งก้อนกลับเข้ามาก่อนบันทึก" : "ลากเส้นทางเพื่อย้ายทั้งก้อน หรือใช้ Scale X/Y, Rotation, Mirror และตำแหน่ง X/Y โดยจุดทั้งหมดยังเชื่อมกัน" : "คลิกจุดบนเส้นทางเพื่อเปิดภาพ 360"}</p>}
          {mapExpanded && <div className="capture-map-actions">
            {selected?.pose && <div className="pose-summary"><strong>{timeLabel(selected.timestamp_ms)}</strong><span>{activeFloor?.name} · {confidenceLabel(selected)}</span><small>{selected.pose.algorithm}</small></div>}
            {canEdit && posedFrames.length > 0 && <button className="button button-secondary" disabled={busy} onClick={toggleStartPointMode} type="button">{startPointMode ? "ยกเลิกแก้จุดเริ่มต้น" : "แก้จุดเริ่มต้น"}</button>}
            {startPointMode && <button className="button button-primary" disabled={busy} onClick={saveStartPoint} type="button">บันทึกจุดเริ่มต้น</button>}
            {showCalibrationTools && posedFrames.length > 0 && <button className="button button-secondary" disabled={busy} onClick={toggleControlPointMode} type="button">{controlPointMode ? "ยกเลิกกำหนดตำแหน่งจริง" : "กำหนดตำแหน่งจริง 3–5 จุด"}</button>}
            {showEvaluationTools && posedFrames.length > 0 && <button className="button button-secondary" disabled={busy} onClick={toggleEvaluationMode} type="button">{evaluationMode ? "ยกเลิกวัดผล" : "วัดผล Ground Truth"}</button>}
            {canAdjustPath && posedFrames.length > 0 && <button className="button button-secondary" disabled={busy} onClick={toggleRigidAlignment} type="button">{aligning ? "ยกเลิกปรับแนว" : alignmentVerified ? "แก้แนวขั้นสูง (ไม่จำเป็น)" : "ปรับเอง"}</button>}
            {canAdjustPath && alignmentVerified && !humanAlignmentVerified && <button className="button button-primary" disabled={busy} onClick={confirmVirtualTour} type="button">ยืนยันว่า Virtual Tour ตรงกับแปลน</button>}
            {canAdjustPath && <button className="button button-primary" disabled={busy || processingActive} onClick={startLocalization} type="button">{processingActive ? "กำลังประมวลผล..." : "คำนวณ AI ใหม่"}</button>}
          </div>}
          {error && <p className="form-error">{error}</p>}
        </section>

        <div className="viewer-overlay"><strong>{selected ? timeLabel(selected.timestamp_ms) : "No evidence"}</strong><span>{selected?.pose ? `${activeFloor?.name ?? "ไม่ทราบชั้น"} · ${confidenceLabel(selected)}` : "ลากเพื่อหมุน · Scroll เพื่อ Zoom"}</span></div>

        {selected && <div className="image-controls"><button disabled={selectedIndex <= 0} onClick={() => { setIsPlaying(false); selectByIndex(0); }} type="button">|‹</button><button disabled={selectedIndex <= 0} onClick={() => { setIsPlaying(false); selectByIndex(selectedIndex - 1); }} type="button">‹</button><button aria-label={isPlaying ? "หยุดเดินชม" : "เล่นการเดินชม"} className="walkthrough-play" disabled={navigableFrames.length < 2} onClick={() => setIsPlaying((value) => !value)} type="button">{isPlaying ? "Ⅱ" : "▶"}</button><span>{timeLabel(selected.timestamp_ms)}</span><input aria-label="ตำแหน่งภาพ 360" max={Math.max(navigableFrames.length - 1, 0)} min="0" onChange={(event) => { setIsPlaying(false); selectByIndex(Number(event.target.value)); }} step="1" type="range" value={Math.max(selectedIndex, 0)} /><button disabled={selectedIndex >= navigableFrames.length - 1} onClick={() => { setIsPlaying(false); selectByIndex(selectedIndex + 1); }} type="button">›</button><button disabled={selectedIndex >= navigableFrames.length - 1} onClick={() => { setIsPlaying(false); selectByIndex(navigableFrames.length - 1); }} type="button">›|</button></div>}
        {!posedFrames.length && <div className={`localization-empty ${processingActive ? "is-processing" : ""}`}>{processingActive && <span className="processing-state-spinner" aria-hidden="true" />}<strong>{processingActive ? "กำลังคำนวณเส้นทางและตำแหน่งภาพ 360" : "ยังไม่มีตำแหน่งภาพ 360"}</strong><p>{processingActive ? "รอจน Processing ครบ 100% หน้านี้จะอัปเดตอัตโนมัติ" : "การประมวลผลจบแล้วแต่ยังไม่มี Camera Pose กรุณากดคำนวณ AI ใหม่"}</p></div>}
      </div>
    </div>
  );
}
