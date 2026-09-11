"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import Image from "next/image";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

import { BimModelUploader } from "@/components/bim-model-uploader";
import { CaptureFieldNotes } from "@/components/capture-field-notes";
import { PanoramaViewer, type PanoramaViewState } from "@/components/panorama-viewer";
import { SpatialTourInspector } from "@/components/spatial-tour-inspector";
import { beamRangeMatchesBulkRemoval, beamStageForActivity, beamStageThreshold, compareWbs, type BeamStageCode } from "@/lib/progress-stage-mapping";
import type { Activity, BeamProgress, BimModel, CaptureDetail, ColumnProgress, ColumnStageCode, FieldNote, Floor, HumanProgressEntry, ProjectMember, RoofProgress, SlabProgress, SlabStageCode, StairProgress, StairStageCode, StructuralElement } from "@/lib/types";

type BeamRange = { start_m: number; end_m: number };
type BeamStageRanges = Partial<Record<BeamStageCode, BeamRange[]>>;
type PlanPoint = [number, number];
type PlanSelectionMode = "replace" | "add" | "subtract";
type PlanSelectionBox = {
  pointerId: number;
  start: PlanPoint;
  current: PlanPoint;
  mode: PlanSelectionMode;
};
type PlanViewport = { scale: number; offsetX: number; offsetY: number };
type PlanPan = { pointerId: number; clientX: number; clientY: number };

const DEFAULT_PLAN_VIEWPORT: PlanViewport = { scale: 1, offsetX: 0, offsetY: 0 };
const MAX_PLAN_SCALE = 6;

const FLOOR_ONE_BEAM_STAGES = [
  { code: "SETTING_OUT", label: "เทลีน / เตรียมแนว" },
  { code: "REBAR", label: "ผูกเหล็ก" },
  { code: "FORMWORK", label: "เข้าแบบ" },
  { code: "CONCRETE", label: "เทคอนกรีต" },
  { code: "STRIP_FORM", label: "แกะแบบ" },
] as const satisfies ReadonlyArray<{ code: BeamStageCode; label: string }>;
const UPPER_FLOOR_BEAM_STAGES = [
  { code: "SHORING", label: "ค้ำยัน" },
  { code: "REBAR", label: "ผูกเหล็ก" },
  { code: "FORMWORK", label: "เข้าแบบ" },
  { code: "CONCRETE", label: "เทคอนกรีต" },
  { code: "STRIP_FORM", label: "ถอดแบบ" },
] as const satisfies ReadonlyArray<{ code: BeamStageCode; label: string }>;

function beamStagesForFloor(levelIndex: number) {
  return levelIndex >= 2 ? UPPER_FLOOR_BEAM_STAGES : FLOOR_ONE_BEAM_STAGES;
}

const COLUMN_STAGES: Array<{ code: ColumnStageCode; label: string }> = [
  { code: "REBAR", label: "ผูกเหล็กเสา" },
  { code: "FORMWORK", label: "เข้าแบบเสา" },
  { code: "CONCRETE", label: "เทคอนกรีตเสา" },
  { code: "STRIP_FORM", label: "ถอดแบบเสา" },
];
const FLOOR_ONE_STAIR_STAGES: Array<{ code: StairStageCode; label: string }> = [
  { code: "REBAR", label: "ผูกเหล็ก" },
  { code: "FORMWORK", label: "เข้าแบบ" },
  { code: "CONCRETE", label: "เทคอนกรีต" },
  { code: "STRIP_FORM", label: "ถอดแบบ" },
];
const UPPER_FLOOR_STAIR_STAGES: Array<{ code: StairStageCode; label: string }> = [
  { code: "SHORING", label: "ค้ำยัน" },
  ...FLOOR_ONE_STAIR_STAGES,
];
type SlabStageOption = { code: SlabStageCode; label: string };
const LEGACY_SLAB_STAGES: SlabStageOption[] = [
  { code: "STEP_1", label: "ขั้นงานพื้น 1" },
  { code: "STEP_2", label: "ขั้นงานพื้น 2" },
  { code: "STEP_3", label: "ขั้นงานพื้น 3" },
  { code: "STEP_4", label: "ขั้นงานพื้น 4" },
  { code: "STEP_5", label: "ขั้นงานพื้น 5" },
];
const GS_SLAB_STAGES: SlabStageOption[] = [
  { code: "SOIL_COMPACTION", label: "บดอัดดิน" },
  { code: "REBAR", label: "ผูกเหล็ก" },
  { code: "FORMWORK", label: "เข้าแบบ" },
  { code: "CONCRETE", label: "เทคอนกรีต" },
  { code: "STRIP_FORM", label: "ถอดแบบ" },
];
const FLOOR_ONE_S1_SLAB_STAGES: SlabStageOption[] = [
  { code: "FORMWORK", label: "เข้าแบบ" },
  { code: "REBAR", label: "ผูกเหล็ก" },
  { code: "CONCRETE", label: "เทคอนกรีต" },
  { code: "STRIP_FORM", label: "ถอดแบบ" },
];
const S1_SLAB_STAGES: SlabStageOption[] = [
  { code: "SHORING", label: "ค้ำยัน" },
  { code: "REBAR", label: "ผูกเหล็ก" },
  { code: "FORMWORK", label: "เข้าแบบ" },
  { code: "CONCRETE", label: "เทคอนกรีต" },
  { code: "STRIP_FORM", label: "ถอดแบบ" },
];
const PC1_SLAB_STAGES: SlabStageOption[] = [
  { code: "SHORING", label: "ค้ำยัน" },
  { code: "PLACE_PRECAST", label: "วางแผ่นพื้น" },
  { code: "REBAR", label: "ใส่เหล็ก" },
  { code: "FORMWORK", label: "เข้าแบบ" },
  { code: "CONCRETE", label: "เทคอนกรีต" },
  { code: "STRIP_FORM", label: "ถอดแบบ" },
];

function slabStageOptions(item: SlabProgress["items"][number]): SlabStageOption[] {
  if (item.geometry_json.slab_type === "GS") return GS_SLAB_STAGES;
  if (item.geometry_json.slab_type === "PC1") return PC1_SLAB_STAGES;
  if (item.geometry_json.slab_workflow === "S1_FLOOR_1") return FLOOR_ONE_S1_SLAB_STAGES;
  if (item.geometry_json.slab_type === "S1") return S1_SLAB_STAGES;
  return LEGACY_SLAB_STAGES;
}

function slabItemProgress(item: SlabProgress["items"][number], stages: SlabStageCode[]) {
  const stageCount = slabStageOptions(item).length;
  return stageCount ? stages.length / stageCount * 100 : 0;
}

function slabStageOptionsForSelection(items: SlabProgress["items"]): SlabStageOption[] {
  if (!items.length) return LEGACY_SLAB_STAGES;
  const optionSets = items.map(slabStageOptions);
  if (optionSets.every((options) => options === optionSets[0])) return optionSets[0];
  const orderedCodes = [...new Set(optionSets.flatMap((options) => options.map((option) => option.code)))];
  return orderedCodes.map((code) => {
    const labels = [...new Set(optionSets.flatMap((options) => (
      options.filter((option) => option.code === code).map((option) => option.label)
    )))];
    return { code, label: labels.join(" / ") };
  });
}

function slabWorkflowSummary(item: SlabProgress["items"][number]) {
  const count = slabStageOptions(item).length;
  const type = item.geometry_json.slab_type ?? "พื้น";
  return `พื้น ${type} มี ${count} ขั้น แต่ละขั้นคิด ${(100 / count).toFixed(count === 6 ? 2 : 0)}%`;
}

const DEFAULT_ROOF_TRACK_OPTIONS = [
  { wbs: "1.2.5.1", label: "อะเส" },
  { wbs: "1.2.5.2", label: "ดั้ง" },
  { wbs: "1.2.5.3", label: "คาน ค.ส.ล." },
  { wbs: "1.2.5.4", label: "พื้น" },
] as const;

const ROOF_TRACK_OPTIONS_BY_LEVEL: Record<number, ReadonlyArray<{ wbs: string; label: string }>> = {
  5: DEFAULT_ROOF_TRACK_OPTIONS,
  6: [
    { wbs: "1.2.5.5", label: "อกไก่เหล็ก ST-B1" },
    { wbs: "1.2.5.6", label: "สะพานรับจันทันเหล็ก ST-B1" },
    { wbs: "1.2.5.7", label: "ตะเฆ่สันเหล็ก" },
    { wbs: "1.2.5.8", label: "จันทันเหล็กกล่อง" },
    { wbs: "1.2.5.9", label: "แปเหล็ก" },
    { wbs: "1.2.5.10", label: "เสา" },
    { wbs: "1.2.5.3", label: "คาน ค.ส.ล." },
    { wbs: "1.2.5.4", label: "พื้น" },
  ],
  7: [
    { wbs: "1.2.5.11", label: "Tie Rod" },
    { wbs: "1.2.5.9", label: "แปเหล็ก" },
    { wbs: "1.2.5.8", label: "จันทันเหล็กกล่อง" },
    { wbs: "1.2.5.10", label: "เสา" },
  ],
};

function normalizeRanges(ranges: BeamRange[]) {
  const ordered = [...ranges].sort((left, right) => left.start_m - right.start_m);
  return ordered.reduce<BeamRange[]>((merged, range) => {
    const previous = merged.at(-1);
    if (previous && range.start_m <= previous.end_m) {
      previous.end_m = Math.max(previous.end_m, range.end_m);
    } else {
      merged.push({ ...range });
    }
    return merged;
  }, []);
}

function clampStageRangesToBeamLength(ranges: BeamStageRanges, lengthM: number, stages: ReadonlyArray<{ code: BeamStageCode }>): BeamStageRanges {
  if (!Number.isFinite(lengthM) || lengthM <= 0) return {};
  return Object.fromEntries(stages.flatMap(({ code }) => {
    const clamped = normalizeRanges((ranges[code] ?? []).flatMap((range) => {
      const startM = Math.max(0, Math.min(lengthM, Number(range.start_m)));
      const endM = Math.max(0, Math.min(lengthM, Number(range.end_m)));
      return Number.isFinite(startM) && Number.isFinite(endM) && endM > startM
        ? [{ start_m: startM, end_m: endM }]
        : [];
    }));
    return clamped.length ? [[code, clamped]] : [];
  })) as BeamStageRanges;
}

function coveredLength(ranges: BeamRange[] | undefined) {
  return normalizeRanges(ranges ?? []).reduce((sum, range) => sum + range.end_m - range.start_m, 0);
}

function formatQuantity2(value: number | string | null | undefined) {
  const numeric = Number(value ?? 0);
  return (Math.round((numeric + 1e-9) * 100) / 100).toFixed(2);
}

function beamStagePercent(
  item: BeamProgress["items"][number],
  ranges: BeamStageRanges | undefined,
  stage: BeamStageCode,
) {
  const length = Number(item.length_m ?? 0);
  return length > 0 ? Math.min(100, (coveredLength(ranges?.[stage]) / length) * 100) : 0;
}

function beamOverallPercent(item: BeamProgress["items"][number], ranges: BeamStageRanges | undefined, stages: ReadonlyArray<{ code: BeamStageCode }>) {
  const length = Number(item.length_m ?? 0);
  if (length <= 0) return 0;
  const completed = stages.reduce((sum, stage) => sum + coveredLength(ranges?.[stage.code]), 0);
  return Math.min(100, (completed / (length * stages.length)) * 100);
}

function slabStageForActivity(name: string, options: SlabStageOption[], fallbackIndex: number): SlabStageCode {
  if (name.includes("ค้ำยัน")) return "SHORING";
  if (name.includes("วางแผ่น") || name.includes("ปูแผ่น")) return "PLACE_PRECAST";
  if (name.includes("ผูกเหล็ก") || name.includes("ใส่เหล็ก")) return "REBAR";
  if (name.includes("เข้าแบบ") || name.includes("ตั้งแบบ")) return "FORMWORK";
  if (name.includes("ถอดแบบ") || name.includes("แกะแบบ")) return "STRIP_FORM";
  if (name.includes("เท") || name.includes("Topping")) return "CONCRETE";
  return options[Math.min(fallbackIndex, options.length - 1)]?.code ?? "STEP_1";
}

function stairStageForActivity(
  name: string,
  options: ReadonlyArray<{ code: StairStageCode }>,
  fallbackIndex: number,
): StairStageCode {
  if (name.includes("ค้ำยัน")) return "SHORING";
  if (name.includes("ผูกเหล็ก") || name.includes("ใส่เหล็ก")) return "REBAR";
  if (name.includes("เข้าแบบ") || name.includes("ตั้งแบบ")) return "FORMWORK";
  if (name.includes("ถอดแบบ") || name.includes("แกะแบบ")) return "STRIP_FORM";
  if (name.includes("เท")) return "CONCRETE";
  return options[Math.min(fallbackIndex, options.length - 1)]?.code ?? "REBAR";
}

function pointInSelectionRect(point: PlanPoint, left: number, top: number, right: number, bottom: number) {
  return point[0] >= left && point[0] <= right && point[1] >= top && point[1] <= bottom;
}

function planSelectionMode(
  modifiers: { ctrlKey: boolean; shiftKey: boolean },
  multiSelectEnabled = false,
): PlanSelectionMode {
  if (modifiers.shiftKey) return "subtract";
  if (modifiers.ctrlKey || multiSelectEnabled) return "add";
  return "replace";
}

function orientation(first: PlanPoint, second: PlanPoint, third: PlanPoint) {
  return (second[0] - first[0]) * (third[1] - first[1])
    - (second[1] - first[1]) * (third[0] - first[0]);
}

function segmentsIntersect(a: PlanPoint, b: PlanPoint, c: PlanPoint, d: PlanPoint) {
  const first = orientation(a, b, c);
  const second = orientation(a, b, d);
  const third = orientation(c, d, a);
  const fourth = orientation(c, d, b);
  const epsilon = 1e-9;
  const onSegment = (start: PlanPoint, point: PlanPoint, end: PlanPoint) => (
    Math.abs(orientation(start, point, end)) <= epsilon
    && point[0] >= Math.min(start[0], end[0]) - epsilon
    && point[0] <= Math.max(start[0], end[0]) + epsilon
    && point[1] >= Math.min(start[1], end[1]) - epsilon
    && point[1] <= Math.max(start[1], end[1]) + epsilon
  );
  if ((first > epsilon && second < -epsilon || first < -epsilon && second > epsilon)
    && (third > epsilon && fourth < -epsilon || third < -epsilon && fourth > epsilon)) return true;
  return Math.abs(first) <= epsilon && onSegment(a, c, b)
    || Math.abs(second) <= epsilon && onSegment(a, d, b)
    || Math.abs(third) <= epsilon && onSegment(c, a, d)
    || Math.abs(fourth) <= epsilon && onSegment(c, b, d);
}

function pointInPolygon(point: PlanPoint, polygon: PlanPoint[]) {
  let inside = false;
  for (let index = 0, previous = polygon.length - 1; index < polygon.length; previous = index++) {
    const currentPoint = polygon[index];
    const previousPoint = polygon[previous];
    if ((currentPoint[1] > point[1]) !== (previousPoint[1] > point[1])
      && point[0] < (previousPoint[0] - currentPoint[0]) * (point[1] - currentPoint[1])
        / (previousPoint[1] - currentPoint[1]) + currentPoint[0]) inside = !inside;
  }
  return inside;
}

function elementSelectionPoints(element: StructuralElement): PlanPoint[] {
  const footprint = element.geometry_json.footprint;
  if (footprint?.length) return footprint as PlanPoint[];
  const lines = element.geometry_json.lines;
  if (lines?.length) return lines.flat() as PlanPoint[];
  const line = element.geometry_json.line;
  if (line?.length) return line as PlanPoint[];
  const center = structuralElementCenter(element);
  return center ? [center] : [];
}

function selectionRectMatchesElement(
  element: StructuralElement,
  box: PlanSelectionBox,
) {
  const left = Math.min(box.start[0], box.current[0]);
  const right = Math.max(box.start[0], box.current[0]);
  const top = Math.min(box.start[1], box.current[1]);
  const bottom = Math.max(box.start[1], box.current[1]);
  const points = elementSelectionPoints(element);
  if (!points.length) return false;
  const windowSelection = box.current[0] >= box.start[0];
  if (windowSelection) return points.every((point) => pointInSelectionRect(point, left, top, right, bottom));
  if (points.some((point) => pointInSelectionRect(point, left, top, right, bottom))) return true;
  const corners: PlanPoint[] = [[left, top], [right, top], [right, bottom], [left, bottom]];
  if (points.length >= 3 && corners.some((corner) => pointInPolygon(corner, points))) return true;
  const elementEdges = points.length >= 3
    ? points.map((point, index) => [point, points[(index + 1) % points.length]] as [PlanPoint, PlanPoint])
    : points.length === 2 ? [[points[0], points[1]] as [PlanPoint, PlanPoint]] : [];
  const rectEdges: Array<[PlanPoint, PlanPoint]> = [
    [corners[0], corners[1]], [corners[1], corners[2]],
    [corners[2], corners[3]], [corners[3], corners[0]],
  ];
  return elementEdges.some(([start, end]) => (
    rectEdges.some(([rectStart, rectEnd]) => segmentsIntersect(start, end, rectStart, rectEnd))
  ));
}

const PLAN_GRID_X = [0.1998, 0.2889, 0.3783, 0.4674, 0.5570, 0.6487] as const;
const PLAN_GRID_Y = [0.2729, 0.4075, 0.4715, 0.6057] as const;
const PLAN_GRID_X_LABELS = ["1", "2", "3", "4", "5", "6"] as const;
const PLAN_GRID_Y_LABELS = ["A", "B", "C", "D"] as const;
function nearestGridIndex(value: number, axes: readonly number[]) {
  const index = axes.reduce((best, axis, candidate) =>
    Math.abs(axis - value) < Math.abs(axes[best] - value) ? candidate : best, 0);
  return Math.abs(axes[index] - value) <= 0.015 ? index : null;
}

function beamDisplayName(item: BeamProgress["items"][number]) {
  const x1 = Number(item.start_x);
  const y1 = Number(item.start_y);
  const x2 = Number(item.end_x);
  const y2 = Number(item.end_y);
  const type = item.beam_type?.trim() || "คาน";
  if (type === "B1" && Math.abs(y2 - y1) >= Math.abs(x2 - x1) * 3) {
    const column = nearestGridIndex((x1 + x2) / 2, PLAN_GRID_X);
    if (column !== null) {
      return `${type} · Grid ${PLAN_GRID_X_LABELS[column]} / A–B2 (คานสั้น)`;
    }
  }
  if (Math.abs(x2 - x1) >= Math.abs(y2 - y1) * 3) {
    const start = nearestGridIndex(x1, PLAN_GRID_X);
    const end = nearestGridIndex(x2, PLAN_GRID_X);
    const row = nearestGridIndex((y1 + y2) / 2, PLAN_GRID_Y);
    if (start !== null && end !== null && start !== end) {
      const rowLabel = row === null ? "แนวนอน" : PLAN_GRID_Y_LABELS[row];
      return `${type} · Grid ${rowLabel} / ${PLAN_GRID_X_LABELS[start]}–${PLAN_GRID_X_LABELS[end]}`;
    }
  } else if (Math.abs(y2 - y1) >= Math.abs(x2 - x1) * 3) {
    const start = nearestGridIndex(y1, PLAN_GRID_Y);
    const end = nearestGridIndex(y2, PLAN_GRID_Y);
    const column = nearestGridIndex((x1 + x2) / 2, PLAN_GRID_X);
    if (start !== null && end !== null && start !== end) {
      const columnLabel = column === null ? "แนวตั้ง" : PLAN_GRID_X_LABELS[column];
      return `${type} · Grid ${columnLabel} / ${PLAN_GRID_Y_LABELS[start]}–${PLAN_GRID_Y_LABELS[end]}`;
    }
  }
  return `${type} · รายละเอียดนอกช่วง Grid หลัก`;
}

const BimViewer = dynamic(() => import("@/components/bim-viewer").then((module) => module.BimViewer), {
  loading: () => <div className="bim-module-loading">กำลังเปิดเครื่องมือ BIM…</div>,
  ssr: false,
});

function structuralElementCenter(element: StructuralElement): [number, number] | null {
  const footprint = element.geometry_json.footprint;
  if (footprint?.length) {
    return [
      footprint.reduce((sum, point) => sum + Number(point[0]), 0) / footprint.length,
      footprint.reduce((sum, point) => sum + Number(point[1]), 0) / footprint.length,
    ];
  }
  const lines = element.geometry_json.lines;
  if (lines?.length) {
    const points = lines.flat();
    return [
      points.reduce((sum, point) => sum + Number(point[0]), 0) / points.length,
      points.reduce((sum, point) => sum + Number(point[1]), 0) / points.length,
    ];
  }
  const line = element.geometry_json.line;
  return line
    ? [(Number(line[0][0]) + Number(line[1][0])) / 2, (Number(line[0][1]) + Number(line[1][1])) / 2]
    : null;
}

export function CaptureReviewWorkspace({
  projectId,
  captureId,
  detail,
  floors,
  activities,
  humanProgress,
  beamProgress,
  columnProgress,
  slabProgress,
  stairProgress,
  roofProgress,
  structuralElements,
  canEdit,
  canEditProgress,
  canEditProgressQuantities,
  canManageBim,
  bimModel,
  fieldNotes,
  members,
  initialFloorId,
  initialKeyframeId,
  initialViewMode,
}: {
  projectId: string;
  captureId: string;
  detail: CaptureDetail;
  floors: Floor[];
  activities: Activity[];
  humanProgress: HumanProgressEntry[];
  beamProgress: BeamProgress | null;
  columnProgress: ColumnProgress | null;
  slabProgress: SlabProgress | null;
  stairProgress: StairProgress | null;
  roofProgress: RoofProgress | null;
  structuralElements: StructuralElement[];
  canEdit: boolean;
  canEditProgress: boolean;
  canEditProgressQuantities: boolean;
  canManageBim: boolean;
  bimModel: BimModel | null;
  fieldNotes: FieldNote[];
  members: ProjectMember[];
  initialFloorId?: string | null;
  initialKeyframeId?: string | null;
  initialViewMode?: "360" | "split" | "bim" | "track" | "3d";
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const chronologicallyOrderedKeyframes = [...detail.keyframes].sort((first, second) => (
    first.timestamp_ms - second.timestamp_ms || first.id.localeCompare(second.id)
  ));
  const defaultTourStation = chronologicallyOrderedKeyframes.find((frame) => (
    frame.is_warp_point && frame.pose
  )) ?? chronologicallyOrderedKeyframes.find((frame) => frame.pose)
    ?? chronologicallyOrderedKeyframes[0];
  const [selectedKeyframeId, setSelectedKeyframeId] = useState<string | null>(
    initialKeyframeId ?? defaultTourStation?.id ?? null,
  );
  const [panoramaView, setPanoramaView] = useState<PanoramaViewState>({
    longitude: 0,
    latitude: 0,
    fov: 70,
  });
  const [viewMode, setViewMode] = useState<"360" | "split" | "bim" | "track" | "3d">(initialViewMode ?? "360");
  const measurableActivities = activities.filter((item) => !item.is_summary && (item.wbs === "1.2" || item.wbs.startsWith("1.2.")));
  const currentActivityIds = useMemo(() => new Set(activities.map((item) => item.id)), [activities]);
  const currentActivityIdByWbs = useMemo(() => new Map(activities.map((item) => [item.wbs, item.id])), [activities]);
  const activeFloor = floors.find((item) => item.id === initialFloorId) ?? floors.find((item) => item.id === detail.capture.start_floor_id) ?? floors[0] ?? null;
  const beamStages = beamStagesForFloor(activeFloor?.level_index ?? 1);
  const stairStageOptions = (activeFloor?.level_index ?? 1) >= 2
    ? UPPER_FLOOR_STAIR_STAGES
    : FLOOR_ONE_STAIR_STAGES;
  function selectPlanFloor(floorId: string) {
    const nextFloor = floors.find((floor) => floor.id === floorId);
    setEditingBeamStage(beamStagesForFloor(nextFloor?.level_index ?? 1)[0].code);
    setPlanViewport(DEFAULT_PLAN_VIEWPORT);
    planPanRef.current = null;
    setIsPlanPanning(false);
    setLoadedPlanFloorId(null);
    setFailedPlanFloorId(null);
    const next = new URLSearchParams(searchParams.toString());
    next.set("floorId", floorId);
    next.set("mode", "track");
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  }
  const floorPrefix = activeFloor
    ? activeFloor.level_index >= 5 ? "1.2.5." : `1.2.${Math.max(1, activeFloor.level_index)}.`
    : "1.2.1.";
  const latestAtCapture = useMemo(() => {
    const result = new Map<string, HumanProgressEntry>();
    const captureTime = new Date(detail.capture.captured_at).getTime();
    for (const row of humanProgress) {
      if (new Date(row.observed_at).getTime() > captureTime) continue;
      const currentId = currentActivityIds.has(row.activity_id)
        ? row.activity_id
        : row.activity_wbs ? currentActivityIdByWbs.get(row.activity_wbs) : undefined;
      if (currentId && !result.has(currentId)) result.set(currentId, row);
    }
    return result;
  }, [currentActivityIdByWbs, currentActivityIds, detail.capture.captured_at, humanProgress]);
  const trackGroups = useMemo(() => {
    const activityByWbs = new Map(activities.map((item) => [item.wbs, item]));
    const colors = ["#24a7e8", "#b58150", "#49bfa9", "#7e6fd1", "#e68a3f", "#3379d5"];
    const groups = new Map<string, Activity[]>();
    for (const activity of measurableActivities.filter((item) => item.wbs.startsWith(floorPrefix))) {
      const key = activity.wbs.split(".").slice(0, 4).join(".");
      groups.set(key, [...(groups.get(key) ?? []), activity]);
    }
    return [...groups.entries()].map(([wbs, unsortedRows], index) => {
      const rows = [...unsortedRows].sort((left, right) => compareWbs(left.wbs, right.wbs));
      const values = rows.map((row) => Number(latestAtCapture.get(row.id)?.progress_percent ?? 0));
      const percent = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
      return { wbs, name: activityByWbs.get(wbs)?.name ?? rows[0]?.name ?? wbs, rows, percent, reviewed: rows.filter((row) => latestAtCapture.has(row.id)).length, color: colors[index % colors.length] };
    });
  }, [activities, floorPrefix, latestAtCapture, measurableActivities]);
  const [visibleTrackGroups, setVisibleTrackGroups] = useState<Record<string, boolean>>({});
  const [showNotStarted, setShowNotStarted] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(trackGroups.map((group) => [group.wbs, true])),
  );
  const beamGroup = trackGroups.find((group) => group.name.includes("คาน")) ?? null;
  const columnGroup = trackGroups.find((group) => (
    group.name.includes("เสา") && !group.name.includes("ฐาน") && !group.name.includes("ตอม่อ")
  )) ?? null;
  const slabGroup = trackGroups.find((group) => group.name.includes("พื้น")) ?? null;
  const stairGroup = trackGroups.find((group) => group.name.includes("บันได")) ?? null;
  const roofGroups = trackGroups.filter((group) => group.name.includes("หลังคา"));
  const isRoofPlan = (activeFloor?.level_index ?? 0) >= 5;
  const roofKingPostGroup = trackGroups.find((group) => group.wbs === "1.2.5.2") ?? null;
  const configuredRoofTrackOptions = ROOF_TRACK_OPTIONS_BY_LEVEL[activeFloor?.level_index ?? 0]
    ?? DEFAULT_ROOF_TRACK_OPTIONS;
  const roofTrackOptions = configuredRoofTrackOptions.flatMap((option) => {
    const group = trackGroups.find((candidate) => candidate.wbs === option.wbs);
    const hasReviewedElements = structuralElements.some((element) => (
      element.element_kind === "ROOF" && element.geometry_json.activity_wbs === option.wbs
    ));
    return group && hasReviewedElements ? [{ ...option, group }] : [];
  });
  const roofGroup = roofGroups.find((group) => structuralElements.some((element) => (
    element.element_kind === "ROOF" && element.geometry_json.activity_wbs === group.wbs
  ))) ?? roofGroups[0] ?? null;
  const captureDay = detail.capture.captured_at.slice(0, 10);
  const firstAvailableRoofFloor = floors.find((floor) => (
    floor.level_index >= 5
    && floor.has_plan
    && (!floor.available_from || floor.available_from <= captureDay)
  )) ?? null;
  const firstRoofActivity = measurableActivities.find((activity) => activity.wbs === "1.2.5.1")
    ?? measurableActivities.find((activity) => activity.wbs.startsWith("1.2.5."))
    ?? null;
  const canOpenRoofPlan = Boolean(roofGroup || (firstAvailableRoofFloor && firstRoofActivity));
  const [selectedTrackActivityId, setSelectedTrackActivityId] = useState<string | null>(
    (activeFloor?.level_index ?? 0) >= 5
      ? roofGroup?.rows[0]?.id ?? null
      : beamGroup?.rows[0]?.id ?? null,
  );
  const [showCaptureTrack, setShowCaptureTrack] = useState(false);
  const [isCameraPickMode, setIsCameraPickMode] = useState(false);
  const [selectedBeamSegmentId, setSelectedBeamSegmentId] = useState<string | null>(null);
  const [selectedColumnId, setSelectedColumnId] = useState<string | null>(null);
  const [columnStages, setColumnStages] = useState<Record<string, ColumnStageCode[]>>(() =>
    Object.fromEntries((columnProgress?.items ?? []).map((item) => [
      item.structural_element_id,
      item.completed_stages,
    ])),
  );
  const [columnSaveBusy, setColumnSaveBusy] = useState(false);
  const [columnSaveMessage, setColumnSaveMessage] = useState<string | null>(null);
  const [selectedSlabId, setSelectedSlabId] = useState<string | null>(null);
  const [selectedStairId, setSelectedStairId] = useState<string | null>(null);
  const [selectedRoofId, setSelectedRoofId] = useState<string | null>(null);
  const [selectedPlanElementIds, setSelectedPlanElementIds] = useState<string[]>([]);
  const [multiSelectEnabled, setMultiSelectEnabled] = useState(true);
  const [planSelectionBox, setPlanSelectionBox] = useState<PlanSelectionBox | null>(null);
  const [slabStages, setSlabStages] = useState<Record<string, SlabStageCode[]>>(() =>
    Object.fromEntries((slabProgress?.items ?? []).map((item) => [
      item.structural_element_id,
      item.completed_stages,
    ])),
  );
  const [slabSaveBusy, setSlabSaveBusy] = useState(false);
  const [slabSaveMessage, setSlabSaveMessage] = useState<string | null>(null);
  const [stairStages, setStairStages] = useState<Record<string, StairStageCode[]>>(() =>
    Object.fromEntries((stairProgress?.items ?? []).map((item) => [
      item.structural_element_id,
      item.completed_stages,
    ])),
  );
  const [stairSaveBusy, setStairSaveBusy] = useState(false);
  const [stairSaveMessage, setStairSaveMessage] = useState<string | null>(null);
  const [roofCompletion, setRoofCompletion] = useState<Record<string, boolean>>(() =>
    Object.fromEntries((roofProgress?.items ?? []).map((item) => [item.structural_element_id, item.complete])),
  );
  const [roofQuantities, setRoofQuantities] = useState<Record<string, number>>(() =>
    Object.fromEntries((roofProgress?.items ?? []).map((item) => [
      item.structural_element_id,
      item.completed_quantity ?? (item.complete ? item.total_quantity ?? 1 : 0),
    ])),
  );
  const [roofTotals, setRoofTotals] = useState<Record<string, number>>(() =>
    Object.fromEntries((roofProgress?.items ?? []).map((item) => [
      item.structural_element_id,
      item.total_quantity ?? 1,
    ])),
  );
  const [roofQuantityDraft, setRoofQuantityDraft] = useState("0");
  const [roofTotalDraft, setRoofTotalDraft] = useState("1");
  const [roofSaveBusy, setRoofSaveBusy] = useState(false);
  const [roofSaveMessage, setRoofSaveMessage] = useState<string | null>(null);

  const [slabAreaDraft, setSlabAreaDraft] = useState("");
  const [slabAreaSaveBusy, setSlabAreaSaveBusy] = useState(false);
  const [beamStageRanges, setBeamStageRanges] = useState<Record<string, BeamStageRanges>>(() =>
    Object.fromEntries((beamProgress?.items ?? []).map((item) => [
      item.beam_segment_id,
      Object.fromEntries(Object.entries(item.stage_ranges).map(([stage, ranges]) => [
        stage,
        ranges?.map((range) => ({ start_m: Number(range.start_m), end_m: Number(range.end_m) })) ?? [],
      ])),
    ])),
  );
  const [editingBeamStage, setEditingBeamStage] = useState<BeamStageCode>(beamStages[0].code);
  const [rangeStartM, setRangeStartM] = useState("0");
  const [rangeEndM, setRangeEndM] = useState("");
  const [beamSaveBusy, setBeamSaveBusy] = useState(false);
  const [beamLengthDraft, setBeamLengthDraft] = useState("");
  const [beamLengthSaveBusy, setBeamLengthSaveBusy] = useState(false);
  const [beamSaveMessage, setBeamSaveMessage] = useState<string | null>(null);
  const [planAspectRatio, setPlanAspectRatio] = useState(1.414);
  const [planViewport, setPlanViewport] = useState<PlanViewport>(DEFAULT_PLAN_VIEWPORT);
  const [isPlanPanning, setIsPlanPanning] = useState(false);
  const [loadedPlanFloorId, setLoadedPlanFloorId] = useState<string | null>(null);
  const [failedPlanFloorId, setFailedPlanFloorId] = useState<string | null>(null);
  const [planImageRevision, setPlanImageRevision] = useState(0);
  const planViewportRef = useRef<HTMLDivElement | null>(null);
  const planImageRef = useRef<HTMLImageElement | null>(null);
  const planPanRef = useRef<PlanPan | null>(null);
  useEffect(() => {
    if (!activeFloor?.has_plan) return;
    let cancelled = false;
    const acceptDecodedImage = () => {
      const image = planImageRef.current;
      if (cancelled || !image?.complete || image.naturalWidth <= 0) return false;
      setFailedPlanFloorId((current) => current === activeFloor.id ? null : current);
      setLoadedPlanFloorId(activeFloor.id);
      return true;
    };
    // Cached images can finish before React receives onLoad after a route
    // transition. Reconcile the actual DOM state so the loading layer cannot
    // remain over a successfully decoded plan.
    const initialCheck = window.setTimeout(acceptDecodedImage, 0);
    const failureTimeout = window.setTimeout(() => {
      if (!acceptDecodedImage() && !cancelled) setFailedPlanFloorId(activeFloor.id);
    }, 15_000);
    return () => {
      cancelled = true;
      window.clearTimeout(initialCheck);
      window.clearTimeout(failureTimeout);
    };
  }, [activeFloor?.has_plan, activeFloor?.id, planImageRevision]);
  useEffect(() => {
    if (viewMode !== "track") return;
    const viewportElement = planViewportRef.current;
    if (!viewportElement) return;
    function handleWheel(event: WheelEvent) {
      event.preventDefault();
      const bounds = viewportElement!.getBoundingClientRect();
      const pointerX = event.clientX - bounds.left;
      const pointerY = event.clientY - bounds.top;
      const wheelDelta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? bounds.height : 1);
      setPlanViewport((current) => {
        const nextScale = Math.max(1, Math.min(MAX_PLAN_SCALE, current.scale * Math.exp(-wheelDelta * 0.0015)));
        if (Math.abs(nextScale - current.scale) < 0.0001) return current;
        if (nextScale <= 1) return DEFAULT_PLAN_VIEWPORT;
        const contentX = (pointerX - current.offsetX) / current.scale;
        const contentY = (pointerY - current.offsetY) / current.scale;
        return {
          scale: nextScale,
          offsetX: Math.max(bounds.width * (1 - nextScale), Math.min(0, pointerX - contentX * nextScale)),
          offsetY: Math.max(bounds.height * (1 - nextScale), Math.min(0, pointerY - contentY * nextScale)),
        };
      });
    }
    viewportElement.addEventListener("wheel", handleWheel, { passive: false });
    return () => viewportElement.removeEventListener("wheel", handleWheel);
  }, [viewMode]);
  useEffect(() => {
    function cancelPlanSelection(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      if (isCameraPickMode) {
        event.preventDefault();
        setIsCameraPickMode(false);
        return;
      }
      const hasSelection = Boolean(
        planSelectionBox
        || selectedPlanElementIds.length
        || selectedBeamSegmentId
        || selectedColumnId
        || selectedSlabId
        || selectedStairId
        || selectedRoofId,
      );
      if (!hasSelection) return;
      event.preventDefault();
      setPlanSelectionBox(null);
      setSelectedPlanElementIds([]);
      setSelectedBeamSegmentId(null);
      setSelectedColumnId(null);
      setSelectedSlabId(null);
      setSelectedStairId(null);
      setSelectedRoofId(null);
      setBeamSaveMessage(null);
      setColumnSaveMessage(null);
      setSlabSaveMessage(null);
      setStairSaveMessage(null);
      setRoofSaveMessage(null);
      setBeamLengthDraft("");
      setSlabAreaDraft("");
      setRangeStartM("0");
      setRangeEndM("");
    }
    window.addEventListener("keydown", cancelPlanSelection);
    return () => window.removeEventListener("keydown", cancelPlanSelection);
  }, [
    isCameraPickMode,
    planSelectionBox,
    selectedBeamSegmentId,
    selectedColumnId,
    selectedPlanElementIds.length,
    selectedRoofId,
    selectedSlabId,
    selectedStairId,
  ]);
  const selectedTrackGroup = trackGroups.find((group) => group.rows.some((row) => row.id === selectedTrackActivityId)) ?? null;
  function selectTrackGroup(group: (typeof trackGroups)[number] | null) {
    if (!group?.rows[0]) return;
    setSelectedTrackActivityId(group.rows[0].id);
    setSelectedBeamSegmentId(null);
    setSelectedColumnId(null);
    setSelectedSlabId(null);
    setSelectedStairId(null);
    setSelectedRoofId(null);
    setSelectedPlanElementIds([]);
    setPlanSelectionBox(null);
    setBeamLengthDraft("");
    setSlabAreaDraft("");
  }
  const selectedStageIndex = selectedTrackGroup?.rows.findIndex((row) => row.id === selectedTrackActivityId) ?? -1;
  const selectedStageThreshold = selectedStageIndex >= 0 && selectedTrackGroup
    ? selectedTrackGroup.name.includes("คาน")
      ? beamStageThreshold(selectedTrackGroup.rows[selectedStageIndex].name, selectedStageIndex, selectedTrackGroup.rows.length)
      : ((selectedStageIndex + 1) * 100) / selectedTrackGroup.rows.length
    : 0;
  const selectedStagePreviousThreshold = selectedStageIndex >= 0 && selectedTrackGroup
    ? selectedTrackGroup.name.includes("คาน")
      ? Math.max(0, selectedStageThreshold - 20)
      : (selectedStageIndex * 100) / selectedTrackGroup.rows.length
    : 0;
  const selectedBeamStageCode = selectedStageIndex >= 0 && selectedTrackGroup
    ? beamStageForActivity(
      selectedTrackGroup.rows[selectedStageIndex].name,
      beamStages,
      selectedStageIndex,
    )
    : beamStages[0].code;
  const floorFrames = detail.keyframes.filter((item) => item.pose?.floor_id === activeFloor?.id && item.pose && Number.isFinite(Number(item.pose.x)) && Number.isFinite(Number(item.pose.y)));
  const elementKindForGroup = useCallback((name: string): StructuralElement["element_kind"] | null => {
    if (name.includes("ฐานราก")) return "FOUNDATION";
    if (name.includes("ตอม่อ")) return "PEDESTAL";
    if (name.includes("บันได")) return "STAIR";
    if (name.includes("หลังคา")) return "ROOF";
    if (name.includes("คาน")) return "BEAM";
    if (name.includes("พื้น")) return "SLAB";
    if (name.includes("เสา")) return "COLUMN";
    return null;
  }, []);
  const selectedElementKind = selectedTrackGroup ? elementKindForGroup(selectedTrackGroup.name) : null;
  const selectedStructuralElements = selectedElementKind
    ? structuralElements
      .filter((item) => (
        item.element_kind === selectedElementKind
        && (selectedElementKind !== "ROOF" || item.geometry_json.activity_wbs === selectedTrackGroup?.wbs)
      ))
      .sort((left, right) => {
        if (selectedElementKind !== "BEAM") return 0;
        const leftLength = Number(beamProgress?.items.find((item) => item.code === left.code)?.length_m ?? 0);
        const rightLength = Number(beamProgress?.items.find((item) => item.code === right.code)?.length_m ?? 0);
        return rightLength - leftLength;
      })
    : [];
  const selectedPlanElementIdSet = useMemo(
    () => new Set(selectedPlanElementIds),
    [selectedPlanElementIds],
  );
  function planElementSelectionMode(
    event: { ctrlKey: boolean; shiftKey: boolean },
    elementId: string,
  ): PlanSelectionMode {
    const mode = planSelectionMode(event, multiSelectEnabled);
    return mode === "add" && !event.ctrlKey && selectedPlanElementIdSet.has(elementId)
      ? "subtract"
      : mode;
  }
  const selectedFrame = detail.keyframes.find((frame) => frame.id === selectedKeyframeId) ?? null;
  const selectedBeamItem = beamProgress?.items.find((item) => item.beam_segment_id === selectedBeamSegmentId) ?? null;
  const selectedBeamCodes = new Set(
    structuralElements
      .filter((element) => element.element_kind === "BEAM" && selectedPlanElementIdSet.has(element.id))
      .map((element) => element.code),
  );
  const selectedBeamItems = beamProgress?.items.filter((item) => selectedBeamCodes.has(item.code)) ?? [];
  const beamItemsToEdit = selectedBeamItems.length
    ? selectedBeamItems
    : selectedBeamItem ? [selectedBeamItem] : [];
  const selectedColumnItem = columnProgress?.items.find((item) => item.structural_element_id === selectedColumnId) ?? null;
  const selectedSlabItem = slabProgress?.items.find((item) => item.structural_element_id === selectedSlabId) ?? null;
  const selectedStairItem = stairProgress?.items.find((item) => item.structural_element_id === selectedStairId) ?? null;
  const selectedRoofItem = roofProgress?.items.find((item) => item.structural_element_id === selectedRoofId) ?? null;
  const selectedRoofUsesCount = selectedRoofItem?.geometry_json.progress_mode === "COUNT";
  const selectedColumnItems = columnProgress?.items.filter((item) => selectedPlanElementIdSet.has(item.structural_element_id)) ?? [];
  const columnItemsToEdit = selectedColumnItems.length ? selectedColumnItems : selectedColumnItem ? [selectedColumnItem] : [];
  const selectedSlabItems = slabProgress?.items.filter((item) => selectedPlanElementIdSet.has(item.structural_element_id)) ?? [];
  const slabItemsToEdit = selectedSlabItems.length ? selectedSlabItems : selectedSlabItem ? [selectedSlabItem] : [];
  const selectedStairItems = stairProgress?.items.filter((item) => selectedPlanElementIdSet.has(item.structural_element_id)) ?? [];
  const stairItemsToEdit = selectedStairItems.length ? selectedStairItems : selectedStairItem ? [selectedStairItem] : [];
  const selectedSlabStageOptions = slabStageOptionsForSelection(slabItemsToEdit);
  const selectedSlabProgress = (() => {
    const denominator = slabItemsToEdit.reduce(
      (sum, item) => sum + Number(item.area_m2) * slabStageOptions(item).length,
      0,
    );
    const completed = slabItemsToEdit.reduce(
      (sum, item) => sum + Number(item.area_m2) * (slabStages[item.structural_element_id]?.length ?? 0),
      0,
    );
    return denominator ? completed / denominator * 100 : 0;
  })();
  const selectedRoofItems = roofProgress?.items.filter((item) => (
    item.activity_wbs === selectedTrackGroup?.wbs
    && selectedPlanElementIdSet.has(item.structural_element_id)
  )) ?? [];
  const roofItemsToEdit = selectedRoofItems.length ? selectedRoofItems : selectedRoofItem ? [selectedRoofItem] : [];
  const roofCountItemsToEdit = roofItemsToEdit.filter((item) => item.geometry_json.progress_mode === "COUNT");
  const roofItemsRecordedOnThisCapture = roofItemsToEdit.filter((item) => item.capture_id === captureId);

  function normalizedPlanPointer(event: ReactPointerEvent<SVGSVGElement>): PlanPoint {
    const bounds = event.currentTarget.getBoundingClientRect();
    return [
      Math.max(0, Math.min(1, (event.clientX - bounds.left) / Math.max(bounds.width, 1))),
      Math.max(0, Math.min(1, (event.clientY - bounds.top) / Math.max(bounds.height, 1))),
    ];
  }

  function clampPlanViewport(viewport: PlanViewport, width: number, height: number): PlanViewport {
    if (viewport.scale <= 1) return DEFAULT_PLAN_VIEWPORT;
    return {
      scale: viewport.scale,
      offsetX: Math.max(width * (1 - viewport.scale), Math.min(0, viewport.offsetX)),
      offsetY: Math.max(height * (1 - viewport.scale), Math.min(0, viewport.offsetY)),
    };
  }

  function beginPlanPan(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 1 || planViewport.scale <= 1) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    planPanRef.current = { pointerId: event.pointerId, clientX: event.clientX, clientY: event.clientY };
    setIsPlanPanning(true);
  }

  function movePlanPan(event: ReactPointerEvent<HTMLDivElement>) {
    const pan = planPanRef.current;
    if (!pan || pan.pointerId !== event.pointerId) return;
    event.preventDefault();
    const deltaX = event.clientX - pan.clientX;
    const deltaY = event.clientY - pan.clientY;
    planPanRef.current = { ...pan, clientX: event.clientX, clientY: event.clientY };
    const bounds = event.currentTarget.getBoundingClientRect();
    setPlanViewport((current) => clampPlanViewport({
      ...current,
      offsetX: current.offsetX + deltaX,
      offsetY: current.offsetY + deltaY,
    }, bounds.width, bounds.height));
  }

  function finishPlanPan(event: ReactPointerEvent<HTMLDivElement>) {
    const pan = planPanRef.current;
    if (!pan || pan.pointerId !== event.pointerId) return;
    event.preventDefault();
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    planPanRef.current = null;
    setIsPlanPanning(false);
  }

  function beginPlanSelection(event: ReactPointerEvent<SVGSVGElement>) {
    if (event.button !== 0) return;
    const target = event.target as SVGElement;
    if (target !== event.currentTarget && !target.classList.contains("plan-selection-surface")) return;
    const start = normalizedPlanPointer(event);
    event.currentTarget.setPointerCapture(event.pointerId);
    setPlanSelectionBox({
      pointerId: event.pointerId,
      start,
      current: start,
      mode: planSelectionMode(event, multiSelectEnabled),
    });
  }

  function movePlanSelection(event: ReactPointerEvent<SVGSVGElement>) {
    if (!planSelectionBox || event.pointerId !== planSelectionBox.pointerId) return;
    // Read the pointer while React's event still has a live currentTarget.
    // State updater callbacks can run after the synthetic event has been released.
    const currentPoint = normalizedPlanPointer(event);
    setPlanSelectionBox((current) => current ? { ...current, current: currentPoint } : null);
  }

  function finishPlanSelection(event: ReactPointerEvent<SVGSVGElement>) {
    if (!planSelectionBox || event.pointerId !== planSelectionBox.pointerId) return;
    const completedBox = { ...planSelectionBox, current: normalizedPlanPointer(event) };
    setPlanSelectionBox(null);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (Math.hypot(
      completedBox.current[0] - completedBox.start[0],
      completedBox.current[1] - completedBox.start[1],
    ) < 0.006) return;
    const matched = selectedStructuralElements.filter((element) => (
      selectionRectMatchesElement(element, completedBox)
    ));
    const matchedIds = matched.map((element) => element.id);
    const nextIds = completedBox.mode === "add"
      ? [...new Set([...selectedPlanElementIds, ...matchedIds])]
      : completedBox.mode === "subtract"
        ? selectedPlanElementIds.filter((id) => !matchedIds.includes(id))
        : matchedIds;
    setSelectedPlanElementIds(nextIds);
    const primary = completedBox.mode === "subtract"
      ? selectedStructuralElements.find((element) => nextIds.includes(element.id)) ?? null
      : matched[0] ?? selectedStructuralElements.find((element) => nextIds.includes(element.id)) ?? null;
    setSelectedBeamSegmentId(null);
    setSelectedColumnId(null);
    setSelectedSlabId(null);
    setSelectedStairId(null);
    setSelectedRoofId(null);
    if (!primary) return;
    if (selectedElementKind === "BEAM") {
      const item = beamProgress?.items.find((candidate) => candidate.code === primary.code);
      if (item) {
        setSelectedBeamSegmentId(item.beam_segment_id);
        setBeamLengthDraft(item.length_m ? Number(item.length_m).toFixed(3) : "");
        setRangeStartM("0");
        setRangeEndM(item.length_m ? Number(item.length_m).toFixed(3) : "");
      }
    } else if (selectedElementKind === "COLUMN") {
      setSelectedColumnId(primary.id);
    } else if (selectedElementKind === "SLAB") {
      const item = slabProgress?.items.find((candidate) => candidate.structural_element_id === primary.id);
      setSelectedSlabId(primary.id);
      setSlabAreaDraft(item?.area_m2 ? Number(item.area_m2).toFixed(3) : "");
    } else if (selectedElementKind === "STAIR") {
      setSelectedStairId(primary.id);
    } else if (selectedElementKind === "ROOF") {
      setSelectedRoofId(primary.id);
      const item = roofProgress?.items.find((candidate) => candidate.structural_element_id === primary.id);
      setRoofQuantityDraft(String(item ? roofQuantities[item.structural_element_id] ?? 0 : 0));
      setRoofTotalDraft(String(item ? roofTotals[item.structural_element_id] ?? item.total_quantity ?? 1 : 1));
    }
  }
  const localColumnProgress = useMemo(() => {
    if (!columnProgress?.items.length) return 0;
    const completed = columnProgress.items.reduce(
      (sum, item) => sum + (columnStages[item.structural_element_id]?.length ?? 0),
      0,
    );
    return completed / (columnProgress.items.length * COLUMN_STAGES.length) * 100;
  }, [columnProgress, columnStages]);
  const localSlabProgress = useMemo(() => {
    if (!slabProgress?.items.length) return 0;
    const completedEquivalentArea = slabProgress.items.reduce(
      (sum, item) => sum + Number(item.area_m2) * (slabStages[item.structural_element_id]?.length ?? 0),
      0,
    );
    const denominator = slabProgress.items.reduce(
      (sum, item) => sum + Number(item.area_m2) * slabStageOptions(item).length,
      0,
    );
    return denominator ? completedEquivalentArea / denominator * 100 : 0;
  }, [slabProgress, slabStages]);
  const localStairProgress = useMemo(() => {
    if (!stairProgress?.items.length || !stairStageOptions.length) return 0;
    const completed = stairProgress.items.reduce(
      (sum, item) => sum + (stairStages[item.structural_element_id]?.length ?? 0),
      0,
    );
    return completed / (stairProgress.items.length * stairStageOptions.length) * 100;
  }, [stairProgress, stairStageOptions.length, stairStages]);
  const roofProgressForWbs = useCallback((wbs: string) => {
    const items = roofProgress?.items.filter((item) => item.activity_wbs === wbs) ?? [];
    if (!items.length) return 0;
    const completed = items.reduce((sum, item) => (
      sum + (roofQuantities[item.structural_element_id] ?? (roofCompletion[item.structural_element_id] ? roofTotals[item.structural_element_id] ?? 1 : 0))
    ), 0);
    const total = items.reduce((sum, item) => sum + (roofTotals[item.structural_element_id] ?? 1), 0);
    return total ? completed / total * 100 : 0;
  }, [roofCompletion, roofProgress, roofQuantities, roofTotals]);
  const localBeamProgress = (() => {
    if (!beamProgress?.items.length) return 0;
    const completedStageLength = beamProgress.items.reduce((sum, item) => (
      sum + beamStages.reduce(
        (stageSum, stage) => stageSum + coveredLength(beamStageRanges[item.beam_segment_id]?.[stage.code]),
        0,
      )
    ), 0);
    const denominator = beamProgress.items.reduce(
      (sum, item) => sum + Number(item.length_m ?? 0) * beamStages.length,
      0,
    );
    return denominator ? (completedStageLength / denominator) * 100 : 0;
  })();
  const currentPlanPosition = selectedFrame?.pose?.floor_id === activeFloor?.id
    && Number.isFinite(Number(selectedFrame.pose.x))
    && Number.isFinite(Number(selectedFrame.pose.y))
    ? {
      x: Number(selectedFrame.pose.x),
      y: Number(selectedFrame.pose.y),
      heading: Number(selectedFrame.pose.heading_deg) + panoramaView.longitude,
      confidence: Number(selectedFrame.pose.confidence),
      reviewed: Boolean(selectedFrame.pose.reviewed_at) || !selectedFrame.pose.needs_review,
    }
    : null;
  useEffect(() => {
    if (!activeFloor?.id || !activeFloor.has_plan) return;
    let cancelled = false;
    fetch(`/api/projects/${projectId}/floors/${activeFloor.id}/plan-info`, { cache: "no-store" })
      .then((response) => response.ok ? response.json() : null)
      .then((info) => {
        const width = Number(info?.width_px);
        const height = Number(info?.height_px);
        if (!cancelled && width > 0 && height > 0) setPlanAspectRatio(width / height);
      })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [activeFloor?.has_plan, activeFloor?.id, projectId]);
  const handlePanoramaViewChange = useCallback((view: PanoramaViewState) => {
    setPanoramaView(view);
  }, []);

  const selectBeamFromPlan = useCallback((
    beamItem: BeamProgress["items"][number],
    selectionMode: PlanSelectionMode = "replace",
  ) => {
    const element = structuralElements.find((candidate) => (
      candidate.element_kind === "BEAM" && candidate.code === beamItem.code
    ));
    if (selectionMode === "subtract") {
      const remainingIds = element
        ? selectedPlanElementIds.filter((id) => id !== element.id)
        : selectedPlanElementIds;
      setSelectedPlanElementIds(remainingIds);
      if (selectedBeamSegmentId !== beamItem.beam_segment_id) return;
      const nextElement = structuralElements.find((candidate) => (
        remainingIds.includes(candidate.id) && candidate.element_kind === "BEAM"
      ));
      const nextBeam = beamProgress?.items.find((candidate) => candidate.code === nextElement?.code);
      setSelectedBeamSegmentId(nextBeam?.beam_segment_id ?? null);
      setBeamSaveMessage(null);
      setRangeStartM("0");
      setRangeEndM("");
      setBeamLengthDraft("");
      return;
    }
    if (selectionMode === "replace" && selectedBeamSegmentId === beamItem.beam_segment_id) {
      setSelectedBeamSegmentId(null);
      setSelectedPlanElementIds([]);
      setBeamSaveMessage(null);
      setRangeStartM("0");
      setRangeEndM("");
      setBeamLengthDraft("");
      return;
    }
    setSelectedBeamSegmentId(beamItem.beam_segment_id);
    setSelectedPlanElementIds((current) => element
      ? selectionMode === "add" ? [...new Set([...current, element.id])] : [element.id]
      : selectionMode === "add" ? current : []);
    setBeamLengthDraft(beamItem.length_m ? Number(beamItem.length_m).toFixed(3) : "");
    setSelectedColumnId(null);
    setSelectedSlabId(null);
    setSelectedStairId(null);
    setSelectedRoofId(null);
    setBeamSaveMessage(null);
    setRangeStartM("0");
    setRangeEndM(beamItem.length_m ? Number(beamItem.length_m).toFixed(3) : "");
  }, [beamProgress?.items, selectedBeamSegmentId, selectedPlanElementIds, structuralElements]);

  async function addSelectedBeamRange() {
    if (!selectedBeamItem) return;
    const beamLength = Number(selectedBeamItem.length_m ?? 0);
    const startM = Number(rangeStartM);
    const endM = Number(rangeEndM);
    if (!Number.isFinite(startM) || !Number.isFinite(endM) || startM < 0 || endM <= startM || endM > beamLength) {
      setBeamSaveMessage(`ช่วงงานต้องอยู่ระหว่าง 0.000–${beamLength.toFixed(3)} ม. และจุดสิ้นสุดต้องมากกว่าจุดเริ่ม`);
      return;
    }
    const wholePrimaryBeam = Math.abs(startM) < 1e-6 && Math.abs(endM - beamLength) < 1e-6;
    const tooShort = wholePrimaryBeam
      ? null
      : beamItemsToEdit.find((item) => Number(item.length_m ?? 0) < endM);
    if (tooShort) {
      setBeamSaveMessage(
        `${beamDisplayName(tooShort)} ยาว ${Number(tooShort.length_m ?? 0).toFixed(3)} ม. ซึ่งสั้นกว่าช่วงที่ระบุ กรุณาลดค่าถึงเมตรที่ หรือเลือกคานชุดใหม่`,
      );
      return;
    }
    const nextRangesByBeam = Object.fromEntries(beamItemsToEdit.map((item) => {
      const beamRanges = beamStageRanges[item.beam_segment_id] ?? {};
      const itemLength = Number(item.length_m ?? 0);
      return [item.beam_segment_id, {
        ...beamRanges,
        [editingBeamStage]: normalizeRanges([
          ...(beamRanges[editingBeamStage] ?? []),
          { start_m: wholePrimaryBeam ? 0 : startM, end_m: wholePrimaryBeam ? itemLength : endM },
        ]),
      }];
    }));
    await persistSelectedBeamProgress(
      nextRangesByBeam,
      `เพิ่มและบันทึกช่วงงานให้คาน ${beamItemsToEdit.length} ชิ้น พร้อมวันตรวจและภาพ 360 แล้ว`,
    );
  }

  async function removeSelectedBeamRange(stage: BeamStageCode, index: number) {
    if (!selectedBeamItem || !beamItemsToEdit.length) return;
    const primaryRanges = beamStageRanges[selectedBeamItem.beam_segment_id] ?? {};
    const selectedRange = primaryRanges[stage]?.[index];
    if (!selectedRange) return;
    if (
      beamItemsToEdit.length > 1
      && !window.confirm(`ลบช่วงงานนี้จากคานที่เลือกทั้ง ${beamItemsToEdit.length} ชิ้นใช่หรือไม่?`)
    ) return;

    const primaryLength = Number(selectedBeamItem.length_m ?? 0);
    const nextRangesByBeam = Object.fromEntries(beamItemsToEdit.map((item) => {
      const itemRanges = beamStageRanges[item.beam_segment_id] ?? {};
      const itemLength = Number(item.length_m ?? 0);
      const remaining = (itemRanges[stage] ?? []).filter((range) => !beamRangeMatchesBulkRemoval(
        range,
        selectedRange,
        itemLength,
        primaryLength,
      ));
      return [item.beam_segment_id, { ...itemRanges, [stage]: remaining }];
    }));
    await persistSelectedBeamProgress(
      nextRangesByBeam,
      beamItemsToEdit.length > 1
        ? `ลบช่วงงานจากคานที่เลือก ${beamItemsToEdit.length} ชิ้นและบันทึกแล้ว`
        : "ลบช่วงงานและบันทึกแล้ว",
    );
  }

  async function saveSelectedBeamLength() {
    if (!activeFloor || !selectedBeamItem) return;
    const lengthM = Number(beamLengthDraft);
    if (!Number.isFinite(lengthM) || lengthM <= 0 || lengthM > 10000) {
      setBeamSaveMessage("ความยาวคานต้องมากกว่า 0 และไม่เกิน 10,000 เมตร");
      return;
    }
    setBeamLengthSaveBusy(true);
    setBeamSaveMessage(null);
    const response = await fetch(
      `/api/projects/${projectId}/floors/${activeFloor.id}/beam-segments/${selectedBeamItem.beam_segment_id}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ length_m: lengthM }),
      },
    );
    const body = await response.json().catch(() => ({}));
    if (response.ok) {
      setRangeEndM(lengthM.toFixed(3));
      setBeamSaveMessage(`แก้ความยาวคานเป็น ${lengthM.toFixed(3)} ม. แล้ว ทุกวันที่ตรวจจะใช้ค่านี้`);
      router.refresh();
    } else {
      setBeamSaveMessage(body.detail || "แก้ความยาวคานไม่สำเร็จ");
    }
    setBeamLengthSaveBusy(false);
  }

  async function saveSelectedSlabArea() {
    if (!activeFloor || !selectedSlabItem) return;
    const areaM2 = Number(slabAreaDraft);
    if (!Number.isFinite(areaM2) || areaM2 <= 0 || areaM2 > 1000000) {
      setSlabSaveMessage("พื้นที่ตรวจต้องมากกว่า 0 และไม่เกิน 1,000,000 ตร.ม.");
      return;
    }
    setSlabAreaSaveBusy(true);
    setSlabSaveMessage(null);
    const response = await fetch(
      `/api/projects/${projectId}/floors/${activeFloor.id}/structural-elements/${selectedSlabItem.structural_element_id}/area`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ area_m2: areaM2 }),
      },
    );
    const body = await response.json().catch(() => ({}));
    setSlabSaveMessage(
      response.ok
        ? `แก้พื้นที่ตรวจเป็น ${areaM2.toFixed(3)} ตร.ม. แล้ว ทุกวันที่ตรวจจะใช้ค่านี้`
        : body.detail || "แก้พื้นที่ตรวจไม่สำเร็จ",
    );
    if (response.ok) router.refresh();
    setSlabAreaSaveBusy(false);
  }

  async function persistSelectedBeamProgress(
    nextRangesByBeam: Record<string, BeamStageRanges>,
    successMessage: string,
  ) {
    if (!beamProgress || !Object.keys(nextRangesByBeam).length) return;
    setBeamSaveBusy(true);
    setBeamSaveMessage(null);
    try {
      const rangesForRequest = Object.fromEntries(Object.entries(nextRangesByBeam).map(([beamSegmentId, stageRanges]) => {
        const item = beamProgress.items.find((candidate) => candidate.beam_segment_id === beamSegmentId);
        return [beamSegmentId, clampStageRangesToBeamLength(stageRanges, Number(item?.length_m ?? 0), beamStages)];
      }));
      const response = await fetch(`/api/projects/${projectId}/captures/${captureId}/beam-progress`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          floor_id: beamProgress.floor_id,
          entries: Object.entries(rangesForRequest).map(([beamSegmentId, stageRanges]) => ({
            beam_segment_id: beamSegmentId,
            stage_ranges: stageRanges,
            evidence_keyframe_id: selectedKeyframeId,
          })),
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (response.ok) {
        const savedRanges = Object.fromEntries(
          (body.items ?? [])
            .filter((item: { beam_segment_id: string }) => item.beam_segment_id in rangesForRequest)
            .map((item: { beam_segment_id: string; stage_ranges?: Record<string, Array<{ start_m: string; end_m: string }>> }) => [
              item.beam_segment_id,
              Object.fromEntries(Object.entries(item.stage_ranges ?? {}).map(([stage, ranges]) => [
                stage,
                (Array.isArray(ranges) ? ranges : []).map((range) => ({
                  start_m: Number(range.start_m),
                  end_m: Number(range.end_m),
                })),
              ])),
            ]),
        );
        setBeamStageRanges((current) => ({ ...current, ...savedRanges }));
      }
      setBeamSaveMessage(response.ok ? successMessage : body.detail || "บันทึกไม่สำเร็จ ข้อมูลเดิมยังคงอยู่");
    } catch {
      setBeamSaveMessage("เชื่อมต่อระบบบันทึกไม่สำเร็จ กรุณากดบันทึกอีกครั้ง");
    } finally {
      setBeamSaveBusy(false);
    }
  }

  async function saveSelectedBeamProgress() {
    if (!selectedBeamItem) return;
    await persistSelectedBeamProgress(
      Object.fromEntries(beamItemsToEdit.map((item) => [
        item.beam_segment_id,
        beamStageRanges[item.beam_segment_id] ?? {},
      ])),
      `บันทึกช่วงความยาว งาน วันที่ตรวจ และภาพ 360 ให้คาน ${beamItemsToEdit.length} ชิ้นแล้ว`,
    );
  }

  function selectColumnFromPlan(
    item: ColumnProgress["items"][number],
    selectionMode: PlanSelectionMode = "replace",
  ) {
    if (selectionMode === "subtract") {
      const remainingIds = selectedPlanElementIds.filter((id) => id !== item.structural_element_id);
      setSelectedPlanElementIds(remainingIds);
      if (selectedColumnId === item.structural_element_id) setSelectedColumnId(remainingIds[0] ?? null);
      setColumnSaveMessage(null);
      return;
    }
    if (selectionMode === "replace" && selectedColumnId === item.structural_element_id) {
      setSelectedColumnId(null);
      setSelectedPlanElementIds([]);
      setColumnSaveMessage(null);
      return;
    }
    setSelectedColumnId(item.structural_element_id);
    setSelectedPlanElementIds((current) => selectionMode === "add"
      ? [...new Set([...current, item.structural_element_id])]
      : [item.structural_element_id]);
    setSelectedBeamSegmentId(null);
    setSelectedSlabId(null);
    setSelectedStairId(null);
    setSelectedRoofId(null);
    setColumnSaveMessage(null);
  }

  async function toggleSelectedColumnStage(stage: ColumnStageCode) {
    if (!selectedColumnItem) return;
    const previousStages = Object.fromEntries(columnItemsToEdit.map((item) => [
      item.structural_element_id,
      columnStages[item.structural_element_id] ?? [],
    ]));
    const allCompleted = columnItemsToEdit.every((item) => previousStages[item.structural_element_id].includes(stage));
    const nextStages = Object.fromEntries(columnItemsToEdit.map((item) => {
      const completed = previousStages[item.structural_element_id];
      return [item.structural_element_id, allCompleted
        ? completed.filter((candidate) => candidate !== stage)
        : [...new Set([...completed, stage])]];
    }));
    setColumnStages((current) => ({ ...current, ...nextStages }));
    const saved = await persistSelectedColumnProgress(nextStages, `อัปเดตและบันทึกงานเสา ${columnItemsToEdit.length} ต้นแล้ว`);
    if (!saved) {
      setColumnStages((current) => ({ ...current, ...previousStages }));
    }
  }

  async function persistSelectedColumnProgress(
    stagesByElement: Record<string, ColumnStageCode[]>,
    successMessage = "บันทึกงานเสาต้นนี้พร้อมวันที่ตรวจและภาพ 360 แล้ว",
  ) {
    if (!columnProgress || !Object.keys(stagesByElement).length) return false;
    setColumnSaveBusy(true);
    setColumnSaveMessage(null);
    try {
      const response = await fetch(`/api/projects/${projectId}/captures/${captureId}/column-progress`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          floor_id: columnProgress.floor_id,
          entries: Object.entries(stagesByElement).map(([structuralElementId, completedStages]) => ({
            structural_element_id: structuralElementId,
            completed_stages: completedStages,
            evidence_keyframe_id: selectedKeyframeId,
          })),
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (response.ok) {
        const savedStages = Object.fromEntries((body.items ?? [])
          .filter((item: { structural_element_id: string }) => item.structural_element_id in stagesByElement)
          .map((item: { structural_element_id: string; completed_stages: ColumnStageCode[] }) => [
            item.structural_element_id,
            item.completed_stages,
          ]));
        setColumnStages((current) => ({ ...current, ...savedStages }));
      }
      setColumnSaveMessage(response.ok ? successMessage : body.detail || "บันทึก Progress เสาไม่สำเร็จ ข้อมูลเดิมยังคงอยู่");
      return response.ok;
    } catch {
      setColumnSaveMessage("เชื่อมต่อระบบบันทึกงานเสาไม่สำเร็จ กรุณาลองอีกครั้ง");
      return false;
    } finally {
      setColumnSaveBusy(false);
    }
  }

  async function saveSelectedColumnProgress() {
    return persistSelectedColumnProgress(
      Object.fromEntries(columnItemsToEdit.map((item) => [
        item.structural_element_id,
        columnStages[item.structural_element_id] ?? [],
      ])),
      `บันทึกงานเสา ${columnItemsToEdit.length} ต้น พร้อมวันที่ตรวจและภาพ 360 แล้ว`,
    );
  }

  function selectSlabFromPlan(
    item: SlabProgress["items"][number],
    selectionMode: PlanSelectionMode = "replace",
  ) {
    if (selectionMode === "subtract") {
      const remainingIds = selectedPlanElementIds.filter((id) => id !== item.structural_element_id);
      setSelectedPlanElementIds(remainingIds);
      if (selectedSlabId === item.structural_element_id) {
        const nextSlab = slabProgress?.items.find((candidate) => remainingIds.includes(candidate.structural_element_id));
        setSelectedSlabId(nextSlab?.structural_element_id ?? null);
        setSlabAreaDraft(nextSlab?.area_m2 ? Number(nextSlab.area_m2).toFixed(3) : "");
      }
      setSlabSaveMessage(null);
      return;
    }
    if (selectionMode === "replace" && selectedSlabId === item.structural_element_id) {
      setSelectedSlabId(null);
      setSelectedPlanElementIds([]);
      setSlabSaveMessage(null);
      setSlabAreaDraft("");
      return;
    }
    setSelectedSlabId(item.structural_element_id);
    setSelectedPlanElementIds((current) => selectionMode === "add"
      ? [...new Set([...current, item.structural_element_id])]
      : [item.structural_element_id]);
    setSlabAreaDraft(item.area_m2 ? Number(item.area_m2).toFixed(3) : "");
    setSelectedBeamSegmentId(null);
    setSelectedColumnId(null);
    setSelectedStairId(null);
    setSelectedRoofId(null);
    setSlabSaveMessage(null);
  }

  function selectStairFromPlan(
    item: StairProgress["items"][number],
    selectionMode: PlanSelectionMode = "replace",
  ) {
    if (selectionMode === "subtract") {
      const remainingIds = selectedPlanElementIds.filter((id) => id !== item.structural_element_id);
      setSelectedPlanElementIds(remainingIds);
      if (selectedStairId === item.structural_element_id) {
        const nextStair = stairProgress?.items.find((candidate) => remainingIds.includes(candidate.structural_element_id));
        setSelectedStairId(nextStair?.structural_element_id ?? null);
      }
      setStairSaveMessage(null);
      return;
    }
    if (selectionMode === "replace" && selectedStairId === item.structural_element_id) {
      setSelectedStairId(null);
      setSelectedPlanElementIds([]);
      setStairSaveMessage(null);
      return;
    }
    setSelectedStairId(item.structural_element_id);
    setSelectedPlanElementIds((current) => selectionMode === "add"
      ? [...new Set([...current, item.structural_element_id])]
      : [item.structural_element_id]);
    setSelectedBeamSegmentId(null);
    setSelectedColumnId(null);
    setSelectedSlabId(null);
    setSelectedRoofId(null);
    setStairSaveMessage(null);
  }

  function selectRoofFromPlan(elementId: string, selectionMode: PlanSelectionMode = "replace") {
    if (selectionMode === "subtract") {
      const remainingIds = selectedPlanElementIds.filter((id) => id !== elementId);
      setSelectedPlanElementIds(remainingIds);
      if (selectedRoofId === elementId) {
        const nextId = remainingIds[0] ?? null;
        const nextItem = roofProgress?.items.find((item) => item.structural_element_id === nextId);
        setSelectedRoofId(nextId);
        setRoofQuantityDraft(String(nextItem ? roofQuantities[nextItem.structural_element_id] ?? 0 : 0));
        setRoofTotalDraft(String(nextItem ? roofTotals[nextItem.structural_element_id] ?? nextItem.total_quantity ?? 1 : 1));
      }
      return;
    }
    if (selectionMode === "replace" && selectedRoofId === elementId) {
      setSelectedRoofId(null);
      setSelectedPlanElementIds([]);
      setRoofQuantityDraft("0");
      setRoofTotalDraft("1");
      return;
    }
    const item = roofProgress?.items.find((candidate) => candidate.structural_element_id === elementId);
    setSelectedRoofId(elementId);
    setRoofQuantityDraft(String(item ? roofQuantities[item.structural_element_id] ?? 0 : 0));
    setRoofTotalDraft(String(item ? roofTotals[item.structural_element_id] ?? item.total_quantity ?? 1 : 1));
    setSelectedPlanElementIds((current) => selectionMode === "add"
      ? [...new Set([...current, elementId])]
      : [elementId]);
    setSelectedBeamSegmentId(null);
    setSelectedColumnId(null);
    setSelectedSlabId(null);
    setSelectedStairId(null);
  }

  function selectAllElementsInCurrentWork() {
    const ids = selectedStructuralElements.map((element) => element.id);
    setSelectedPlanElementIds(ids);
    const primary = selectedStructuralElements[0];
    if (!primary) return;
    if (selectedElementKind === "BEAM") {
      const item = beamProgress?.items.find((candidate) => candidate.code === primary.code);
      if (item) {
        setSelectedBeamSegmentId(item.beam_segment_id);
        setBeamLengthDraft(item.length_m ? Number(item.length_m).toFixed(3) : "");
        setRangeStartM("0");
        setRangeEndM(item.length_m ? Number(item.length_m).toFixed(3) : "");
      }
    } else if (selectedElementKind === "COLUMN") {
      setSelectedColumnId(primary.id);
    } else if (selectedElementKind === "SLAB") {
      const item = slabProgress?.items.find((candidate) => candidate.structural_element_id === primary.id);
      setSelectedSlabId(primary.id);
      setSlabAreaDraft(item?.area_m2 ? Number(item.area_m2).toFixed(3) : "");
    } else if (selectedElementKind === "STAIR") {
      setSelectedStairId(primary.id);
    } else if (selectedElementKind === "ROOF") {
      setSelectedRoofId(primary.id);
      const item = roofProgress?.items.find((candidate) => candidate.structural_element_id === primary.id);
      setRoofQuantityDraft(String(item ? roofQuantities[item.structural_element_id] ?? 0 : 0));
      setRoofTotalDraft(String(item ? roofTotals[item.structural_element_id] ?? item.total_quantity ?? 1 : 1));
    }
  }

  async function toggleSelectedSlabStage(stage: SlabStageCode) {
    if (!selectedSlabItem) return;
    const eligibleItems = slabItemsToEdit.filter((item) => (
      slabStageOptions(item).some((option) => option.code === stage)
    ));
    if (!eligibleItems.length) return;
    const previousStages = Object.fromEntries(eligibleItems.map((item) => [
      item.structural_element_id,
      slabStages[item.structural_element_id] ?? [],
    ]));
    const allCompleted = eligibleItems.every((item) => previousStages[item.structural_element_id].includes(stage));
    const nextStages = Object.fromEntries(eligibleItems.map((item) => {
      const completed = previousStages[item.structural_element_id];
      return [item.structural_element_id, allCompleted
        ? completed.filter((candidate) => candidate !== stage)
        : [...new Set([...completed, stage])]];
    }));
    setSlabStages((current) => ({ ...current, ...nextStages }));
    const saved = await persistSelectedSlabProgress(nextStages, `อัปเดตและบันทึกงานพื้น ${eligibleItems.length} พื้นที่แล้ว`);
    if (!saved) {
      setSlabStages((current) => ({ ...current, ...previousStages }));
    }
  }

  async function persistSelectedSlabProgress(
    stagesByElement: Record<string, SlabStageCode[]>,
    successMessage = "บันทึกงานพื้นโซนนี้แล้ว",
  ) {
    if (!slabProgress || !Object.keys(stagesByElement).length) return false;
    setSlabSaveBusy(true);
    setSlabSaveMessage(null);
    try {
      const response = await fetch(`/api/projects/${projectId}/captures/${captureId}/slab-progress`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          floor_id: slabProgress.floor_id,
          entries: Object.entries(stagesByElement).map(([structuralElementId, completedStages]) => ({
            structural_element_id: structuralElementId,
            completed_stages: completedStages,
            evidence_keyframe_id: selectedKeyframeId,
          })),
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (response.ok) {
        const savedStages = Object.fromEntries((body.items ?? [])
          .filter((item: { structural_element_id: string }) => item.structural_element_id in stagesByElement)
          .map((item: { structural_element_id: string; completed_stages: SlabStageCode[] }) => [
            item.structural_element_id,
            item.completed_stages,
          ]));
        setSlabStages((current) => ({ ...current, ...savedStages }));
      }
      setSlabSaveMessage(response.ok ? successMessage : body.detail || "บันทึก Progress พื้นไม่สำเร็จ ข้อมูลเดิมยังคงอยู่");
      return response.ok;
    } catch {
      setSlabSaveMessage("เชื่อมต่อระบบบันทึกงานพื้นไม่สำเร็จ กรุณาลองอีกครั้ง");
      return false;
    } finally {
      setSlabSaveBusy(false);
    }
  }

  async function saveSelectedSlabProgress() {
    return persistSelectedSlabProgress(
      Object.fromEntries(slabItemsToEdit.map((item) => [
        item.structural_element_id,
        slabStages[item.structural_element_id] ?? [],
      ])),
      `บันทึกงานพื้น ${slabItemsToEdit.length} พื้นที่ พร้อมวันที่ตรวจและภาพ 360 แล้ว`,
    );
  }

  async function toggleSelectedStairStage(stage: StairStageCode) {
    if (!selectedStairItem || !stairItemsToEdit.length) return;
    const previousStages = Object.fromEntries(stairItemsToEdit.map((item) => [
      item.structural_element_id,
      stairStages[item.structural_element_id] ?? [],
    ]));
    const allCompleted = stairItemsToEdit.every((item) => previousStages[item.structural_element_id].includes(stage));
    const nextStages = Object.fromEntries(stairItemsToEdit.map((item) => {
      const completed = previousStages[item.structural_element_id];
      return [item.structural_element_id, allCompleted
        ? completed.filter((candidate) => candidate !== stage)
        : [...new Set([...completed, stage])]];
    }));
    setStairStages((current) => ({ ...current, ...nextStages }));
    const saved = await persistSelectedStairProgress(nextStages, `อัปเดตและบันทึกงานบันได ${stairItemsToEdit.length} ชุดแล้ว`);
    if (!saved) setStairStages((current) => ({ ...current, ...previousStages }));
  }

  async function persistSelectedStairProgress(
    stagesByElement: Record<string, StairStageCode[]>,
    successMessage = "บันทึกงานบันไดพร้อมวันที่ตรวจและภาพ 360 แล้ว",
  ) {
    if (!stairProgress || !Object.keys(stagesByElement).length) return false;
    setStairSaveBusy(true);
    setStairSaveMessage(null);
    try {
      const response = await fetch(`/api/projects/${projectId}/captures/${captureId}/stair-progress`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          floor_id: stairProgress.floor_id,
          entries: Object.entries(stagesByElement).map(([structuralElementId, completedStages]) => ({
            structural_element_id: structuralElementId,
            completed_stages: completedStages,
            evidence_keyframe_id: selectedKeyframeId,
          })),
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (response.ok) {
        const savedStages = Object.fromEntries((body.items ?? [])
          .filter((item: { structural_element_id: string }) => item.structural_element_id in stagesByElement)
          .map((item: { structural_element_id: string; completed_stages: StairStageCode[] }) => [
            item.structural_element_id,
            item.completed_stages,
          ]));
        setStairStages((current) => ({ ...current, ...savedStages }));
      }
      setStairSaveMessage(response.ok ? successMessage : body.detail || "บันทึก Progress บันไดไม่สำเร็จ ข้อมูลเดิมยังคงอยู่");
      return response.ok;
    } catch {
      setStairSaveMessage("เชื่อมต่อระบบบันทึกงานบันไดไม่สำเร็จ กรุณาลองอีกครั้ง");
      return false;
    } finally {
      setStairSaveBusy(false);
    }
  }

  async function saveSelectedStairProgress() {
    return persistSelectedStairProgress(
      Object.fromEntries(stairItemsToEdit.map((item) => [
        item.structural_element_id,
        stairStages[item.structural_element_id] ?? [],
      ])),
      `บันทึกงานบันได ${stairItemsToEdit.length} ชุด พร้อมวันที่ตรวจและภาพ 360 แล้ว`,
    );
  }

  async function persistSelectedRoofProgress(
    completionByElement: Record<string, boolean>,
    successMessage: string,
  ) {
    if (!roofProgress || !Object.keys(completionByElement).length) return false;
    setRoofSaveBusy(true);
    setRoofSaveMessage(null);
    try {
      const response = await fetch(`/api/projects/${projectId}/captures/${captureId}/roof-progress`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          floor_id: roofProgress.floor_id,
          entries: Object.entries(completionByElement).map(([structuralElementId, complete]) => ({
            structural_element_id: structuralElementId,
            complete,
            evidence_keyframe_id: selectedKeyframeId,
          })),
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || "บันทึก Progress งานหลังคาไม่สำเร็จ");
      setRoofCompletion(Object.fromEntries((body.items ?? []).map((item: { structural_element_id: string; complete: boolean }) => [
        item.structural_element_id,
        item.complete,
      ])));
      setRoofQuantities(Object.fromEntries((body.items ?? []).map((item: RoofProgress["items"][number]) => [
        item.structural_element_id,
        item.completed_quantity ?? (item.complete ? item.total_quantity ?? 1 : 0),
      ])));
      setRoofTotals(Object.fromEntries((body.items ?? []).map((item: RoofProgress["items"][number]) => [
        item.structural_element_id,
        item.total_quantity ?? 1,
      ])));
      setRoofSaveMessage(successMessage);
      router.refresh();
      return true;
    } catch (error) {
      setRoofSaveMessage(error instanceof Error ? error.message : "บันทึก Progress งานหลังคาไม่สำเร็จ");
      return false;
    } finally {
      setRoofSaveBusy(false);
    }
  }

  async function toggleSelectedRoofComplete() {
    if (!roofItemsToEdit.length) return;
    const previous = Object.fromEntries(roofItemsToEdit.map((item) => [
      item.structural_element_id,
      roofCompletion[item.structural_element_id] ?? false,
    ]));
    const nextValue = !roofItemsToEdit.every((item) => roofCompletion[item.structural_element_id]);
    const next = Object.fromEntries(roofItemsToEdit.map((item) => [item.structural_element_id, nextValue]));
    setRoofCompletion((current) => ({ ...current, ...next }));
    const saved = await persistSelectedRoofProgress(
      next,
      `${nextValue ? "บันทึกว่าเสร็จแล้ว" : "ยกเลิกสถานะเสร็จ"} ${roofItemsToEdit.length} ชิ้น พร้อมภาพ 360 แล้ว`,
    );
    if (!saved) setRoofCompletion((current) => ({ ...current, ...previous }));
  }

  async function saveSelectedRoofQuantity() {
    if (!roofProgress || !selectedRoofItem || !selectedRoofUsesCount || !roofCountItemsToEdit.length) return;
    const completedQuantity = Number(roofQuantityDraft);
    const totalQuantity = Number(roofTotalDraft);
    if (
      !Number.isInteger(completedQuantity)
      || !Number.isInteger(totalQuantity)
      || completedQuantity < 0
      || totalQuantity <= 0
      || completedQuantity > totalQuantity
    ) {
      setRoofSaveMessage("กรุณากรอกจำนวนเต็ม โดยจำนวนที่ตรวจแล้วต้องไม่เกินจำนวนทั้งหมด");
      return;
    }
    setRoofSaveBusy(true);
    setRoofSaveMessage(null);
    try {
      const response = await fetch(`/api/projects/${projectId}/captures/${captureId}/roof-progress`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          floor_id: roofProgress.floor_id,
          entries: roofCountItemsToEdit.map((item) => ({
            structural_element_id: item.structural_element_id,
            completed_quantity: completedQuantity,
            total_quantity: totalQuantity,
            evidence_keyframe_id: selectedKeyframeId,
          })),
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || "บันทึกจำนวนแปเหล็กไม่สำเร็จ");
      const selectedIds = new Set(roofCountItemsToEdit.map((item) => item.structural_element_id));
      const savedItems = (body.items ?? []).filter((item: RoofProgress["items"][number]) => selectedIds.has(item.structural_element_id));
      setRoofQuantities((current) => ({ ...current, ...Object.fromEntries(savedItems.map((item: RoofProgress["items"][number]) => [item.structural_element_id, item.completed_quantity ?? 0])) }));
      setRoofTotals((current) => ({ ...current, ...Object.fromEntries(savedItems.map((item: RoofProgress["items"][number]) => [item.structural_element_id, item.total_quantity ?? totalQuantity])) }));
      setRoofCompletion((current) => ({ ...current, ...Object.fromEntries(savedItems.map((item: RoofProgress["items"][number]) => [item.structural_element_id, item.complete])) }));
      setRoofSaveMessage(`บันทึกผลตรวจ ${roofCountItemsToEdit.length} ชุด ชุดละ ${completedQuantity}/${totalQuantity} ตัว (${(completedQuantity / totalQuantity * 100).toFixed(2)}%) แล้ว`);
      router.refresh();
    } catch (error) {
      setRoofSaveMessage(error instanceof Error ? error.message : "บันทึกจำนวนแปเหล็กไม่สำเร็จ");
    } finally {
      setRoofSaveBusy(false);
    }
  }

  async function deleteSelectedRoofProgress() {
    if (!roofProgress || !roofItemsRecordedOnThisCapture.length) return;
    const count = roofItemsRecordedOnThisCapture.length;
    const unit = selectedRoofUsesCount ? "ชุด" : "ชิ้น";
    if (!window.confirm(`ลบผลตรวจของวันนี้สำหรับ ${count} ${unit} ใช่หรือไม่?\nจำนวนและภาพหลักฐานที่บันทึกในวันนี้จะถูกลบ`)) return;
    setRoofSaveBusy(true);
    setRoofSaveMessage(null);
    try {
      const response = await fetch(`/api/projects/${projectId}/captures/${captureId}/roof-progress`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          floor_id: roofProgress.floor_id,
          structural_element_ids: roofItemsRecordedOnThisCapture.map((item) => item.structural_element_id),
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || "ลบผลตรวจงานหลังคาไม่สำเร็จ");
      const returnedItems = (body.items ?? []) as RoofProgress["items"];
      setRoofCompletion(Object.fromEntries(returnedItems.map((item) => [item.structural_element_id, item.complete])));
      setRoofQuantities(Object.fromEntries(returnedItems.map((item) => [
        item.structural_element_id,
        item.completed_quantity ?? (item.complete ? item.total_quantity ?? 1 : 0),
      ])));
      setRoofTotals(Object.fromEntries(returnedItems.map((item) => [
        item.structural_element_id,
        item.total_quantity ?? 1,
      ])));
      const refreshedSelected = returnedItems.find((item) => item.structural_element_id === selectedRoofId);
      setRoofQuantityDraft(String(refreshedSelected?.completed_quantity ?? 0));
      setRoofTotalDraft(String(refreshedSelected?.total_quantity ?? 1));
      setRoofSaveMessage(`ลบผลตรวจของวันนี้ ${count} ${unit} แล้ว`);
      router.refresh();
    } catch (error) {
      setRoofSaveMessage(error instanceof Error ? error.message : "ลบผลตรวจงานหลังคาไม่สำเร็จ");
    } finally {
      setRoofSaveBusy(false);
    }
  }

  return (
    <div className={`capture-review-workspace mode-${viewMode}`}>
      <nav aria-label="โหมดมุมมอง" className="compare-mode-switcher">
        <button className={viewMode === "360" ? "is-active" : ""} onClick={() => setViewMode("360")} type="button">Virtual Tour</button>
        <button className={viewMode === "split" ? "is-active" : ""} onClick={() => setViewMode("split")} type="button">Virtual Tour | BIM</button>
        <button className={viewMode === "bim" ? "is-active" : ""} onClick={() => setViewMode("bim")} type="button">BIM</button>
        <button className={viewMode === "3d" ? "is-active" : ""} onClick={() => setViewMode("3d")} type="button">3D จุดวาร์ป</button>
        <button className={viewMode === "track" ? "is-active" : ""} onClick={() => setViewMode("track")} type="button">แปลน | 360° | Progress</button>
      </nav>

      {viewMode === "3d" ? <SpatialTourInspector
        activeKeyframeId={selectedKeyframeId}
        captureId={captureId}
        detail={detail}
        onOpenStation={(keyframeId) => { setSelectedKeyframeId(keyframeId); setViewMode("360"); }}
        projectId={projectId}
      /> : viewMode === "track" ? <div className="track-sheet-stage">
        <section className="track-sheet-plan-pane">
          <header><div><label className="track-plan-floor-selector"><span>แปลนที่ตรวจ</span><select aria-label="เลือกแปลนที่ตรวจ" onChange={(event) => selectPlanFloor(event.target.value)} value={activeFloor?.id ?? ""}>{floors.map((floor) => <option key={floor.id} value={floor.id}>{floor.name}</option>)}</select></label></div><nav aria-label="เลือกสิ่งที่จะตรวจบนแปลน" className="plan-element-mode-switcher">
            {isRoofPlan ? <>
              {roofTrackOptions.map((option) => <button
                className={selectedTrackGroup?.wbs === option.wbs ? "is-active" : ""}
                key={option.wbs}
                onClick={() => selectTrackGroup(option.group)}
                type="button"
              >{option.label}</button>)}
            </> : <>
            <button className={selectedElementKind === "BEAM" ? "is-active" : ""} disabled={!beamGroup} onClick={() => {
              selectTrackGroup(beamGroup);
            }} type="button">คาน</button>
            <button className={selectedElementKind === "COLUMN" ? "is-active" : ""} disabled={!columnGroup} onClick={() => {
              selectTrackGroup(columnGroup);
            }} type="button">เสา</button>
            <button className={selectedElementKind === "SLAB" ? "is-active" : ""} disabled={!slabGroup} onClick={() => {
              selectTrackGroup(slabGroup);
            }} type="button">พื้น</button>
            <button className={selectedElementKind === "STAIR" ? "is-active" : ""} disabled={!stairGroup} onClick={() => {
              selectTrackGroup(stairGroup);
            }} type="button">บันได</button>
            <button className={selectedElementKind === "ROOF" ? "is-active" : ""} disabled={!canOpenRoofPlan} onClick={() => {
              const roofActivity = roofGroup?.rows[0] ?? firstRoofActivity;
              if (!roofActivity) return;
              setSelectedTrackActivityId(roofActivity.id);
              setSelectedBeamSegmentId(null);
              setSelectedColumnId(null);
              setSelectedSlabId(null);
              setSelectedStairId(null);
              setSelectedRoofId(null);
              setSelectedPlanElementIds([]);
              if ((activeFloor?.level_index ?? 0) < 5 && firstAvailableRoofFloor) {
                selectPlanFloor(firstAvailableRoofFloor.id);
              }
            }} type="button">หลังคา</button>
            </>}
          </nav><label className="track-capture-toggle"><input checked={showCaptureTrack} onChange={(event) => {
            setShowCaptureTrack(event.target.checked);
            if (!event.target.checked) setIsCameraPickMode(false);
          }} type="checkbox" />เส้นทาง Capture</label><button
            aria-pressed={isCameraPickMode}
            className={`track-camera-pick-toggle${isCameraPickMode ? " is-active" : ""}`}
            onClick={() => {
              setIsCameraPickMode((current) => {
                const next = !current;
                if (next) setShowCaptureTrack(true);
                return next;
              });
            }}
            type="button"
          >{isCameraPickMode ? "กำลังเลือกมุม" : "เลือกมุมกล้อง"}</button><Link href={`/projects/${projectId}/dashboard?captureId=${captureId}`}>กลับภาพรวม</Link></header>
          <div className="track-sheet-plan-canvas">
            <div
              className={`track-plan-viewport${isPlanPanning ? " is-panning" : ""}`}
              onAuxClick={(event) => { if (event.button === 1) event.preventDefault(); }}
              onPointerCancel={finishPlanPan}
              onPointerDown={beginPlanPan}
              onPointerMove={movePlanPan}
              onPointerUp={finishPlanPan}
              ref={planViewportRef}
              style={{ aspectRatio: planAspectRatio }}
            >
            <div
              className={`track-plan-sheet${isCameraPickMode ? " is-camera-picking" : ""}`}
              style={{
                // Size and position the plan without a CSS transform. Chrome can
                // promote a large plan plus SVG overlays into a GPU texture when
                // translate3d/will-change is used; on some Windows drivers that
                // layer intermittently renders as a black rectangle.
                bottom: "auto",
                height: `${planViewport.scale * 100}%`,
                left: `${planViewport.offsetX}px`,
                right: "auto",
                top: `${planViewport.offsetY}px`,
                width: `${planViewport.scale * 100}%`,
              }}
            >
            {activeFloor?.has_plan ? <>
              <Image
                alt={`แปลน ${activeFloor.name}`}
                fill
                key={`${activeFloor.id}:${planImageRevision}`}
                onError={() => setFailedPlanFloorId(activeFloor.id)}
                onLoad={() => {
                  setFailedPlanFloorId((current) => current === activeFloor.id ? null : current);
                  setLoadedPlanFloorId(activeFloor.id);
                }}
                priority
                ref={planImageRef}
                sizes="40vw"
                src={`/api/projects/${projectId}/floors/${activeFloor.id}/plan?v=${planImageRevision}`}
                unoptimized
              />
            </> : <div className="track-sheet-no-plan">ยังไม่มีแปลนชั้นนี้</div>}
            {showCaptureTrack && <><svg aria-hidden="true" className="capture-track-overlay" preserveAspectRatio="none" viewBox="0 0 1 1"><polyline points={floorFrames.map((frame) => `${Number(frame.pose!.x)},${Number(frame.pose!.y)}`).join(" ")} /></svg>{floorFrames.map((frame) => <button aria-label={`เปิดภาพเวลา ${(frame.timestamp_ms / 1000).toFixed(1)} วินาที`} className={selectedKeyframeId === frame.id ? "is-active" : ""} key={frame.id} onClick={() => { if (isCameraPickMode) setSelectedKeyframeId(frame.id); }} style={{ left: `${Number(frame.pose!.x) * 100}%`, top: `${Number(frame.pose!.y) * 100}%` }} type="button" />)}</>}
            {selectedTrackGroup && selectedStructuralElements.length > 0 && <svg
              aria-label={`ตำแหน่ง ${selectedTrackGroup.rows.find((row) => row.id === selectedTrackActivityId)?.name ?? selectedTrackGroup.name}`}
              className={`structural-progress-overlay${selectedPlanElementIds.length ? " has-selection" : ""}${planSelectionBox ? " is-box-selecting" : ""}`}
              onPointerCancel={() => setPlanSelectionBox(null)}
              onPointerDown={beginPlanSelection}
              onPointerMove={movePlanSelection}
              onPointerUp={finishPlanSelection}
              preserveAspectRatio="none"
              viewBox="0 0 1 1"
            >
              <rect className="plan-selection-surface" height="1" width="1" x="0" y="0" />
              {selectedStructuralElements.map((element) => {
              const beamItem = selectedElementKind === "BEAM" ? beamProgress?.items.find((item) => item.code === element.code) : null;
              const columnItem = selectedElementKind === "COLUMN" ? columnProgress?.items.find((item) => item.structural_element_id === element.id) : null;
              const slabItem = selectedElementKind === "SLAB" ? slabProgress?.items.find((item) => item.structural_element_id === element.id) : null;
              const stairItem = selectedElementKind === "STAIR" ? stairProgress?.items.find((item) => item.structural_element_id === element.id) : null;
              const roofItem = selectedElementKind === "ROOF" ? roofProgress?.items.find((item) => item.structural_element_id === element.id) : null;
              const columnStage = COLUMN_STAGES[Math.min(Math.max(selectedStageIndex, 0), COLUMN_STAGES.length - 1)].code;
              const slabStageOptionsForMarker = slabItem ? slabStageOptions(slabItem) : LEGACY_SLAB_STAGES;
              const slabStage = slabStageOptionsForMarker[
                Math.min(Math.max(selectedStageIndex, 0), slabStageOptionsForMarker.length - 1)
              ].code;
              const stairStage = stairStageForActivity(
                selectedTrackGroup.rows[Math.max(selectedStageIndex, 0)]?.name ?? "",
                stairStageOptions,
                Math.max(selectedStageIndex, 0),
              );
              const value = stairItem
                ? (stairStages[stairItem.structural_element_id] ?? []).includes(stairStage) ? 100 : 0
                : slabItem
                ? (slabStages[slabItem.structural_element_id] ?? []).includes(slabStage) ? 100 : 0
                : columnItem
                ? (columnStages[columnItem.structural_element_id] ?? []).includes(columnStage) ? 100 : 0
                : beamItem
                ? beamStagePercent(beamItem, beamStageRanges[beamItem.beam_segment_id], selectedBeamStageCode)
                : roofItem
                ? (roofQuantities[roofItem.structural_element_id] ?? (roofCompletion[roofItem.structural_element_id] ? roofTotals[roofItem.structural_element_id] ?? 1 : 0))
                  / Math.max(roofTotals[roofItem.structural_element_id] ?? 1, 1) * 100
                : selectedTrackGroup.percent;
              const completed = selectedElementKind === "BEAM" || selectedElementKind === "COLUMN" || selectedElementKind === "SLAB" || selectedElementKind === "STAIR" || selectedElementKind === "ROOF" ? value >= 99.999 : value >= selectedStageThreshold;
              const partial = selectedElementKind === "BEAM" || selectedElementKind === "COLUMN" || selectedElementKind === "SLAB" || selectedElementKind === "STAIR" || selectedElementKind === "ROOF"
                ? value > 0 && value < 99.999
                : value > selectedStagePreviousThreshold && value < selectedStageThreshold;
              const showIncomplete = showNotStarted[selectedTrackGroup.wbs] ?? false;
              const selected = selectedPlanElementIdSet.has(element.id)
                || beamItem?.beam_segment_id === selectedBeamSegmentId
                || columnItem?.structural_element_id === selectedColumnId
                || slabItem?.structural_element_id === selectedSlabId
                || stairItem?.structural_element_id === selectedStairId
                || (selectedElementKind === "ROOF" && element.id === selectedRoofId);
              if (!completed && !partial && !showIncomplete && !selected) return null;
              const center = structuralElementCenter(element);
              const nearCurrent = Boolean(currentPlanPosition && center && Math.hypot(center[0] - currentPlanPosition.x, center[1] - currentPlanPosition.y) <= 0.09);
              const className = `${completed ? "is-complete" : partial ? "is-partial" : "is-not-started"}${nearCurrent ? " is-current-area" : ""}${selected ? " is-selected-element" : ""}`;
              // Keep every physical item visible in the selected work group.
              // Unreviewed items use the group's own colour with a lighter,
              // dashed treatment; they must not look like completed work.
              const stroke = completed ? selectedTrackGroup.color : partial ? "#e89b2d" : selectedTrackGroup.color;
              const line = element.geometry_json.line;
              const lines = element.geometry_json.lines;
              const footprint = element.geometry_json.footprint;
              const isKingPostElement = selectedTrackGroup.wbs === roofKingPostGroup?.wbs;
              const isRoofColumnElement = selectedElementKind === "ROOF" && selectedTrackGroup.wbs === "1.2.5.10";
              const kingPostRadiusX = 0.0075;
              const kingPostRadiusY = kingPostRadiusX * planAspectRatio;
              if (selectedElementKind === "ROOF" && lines?.length) {
                return <g key={element.id}>
                  {lines.map((member, index) => <line
                    aria-label={`เลือก ${element.code}`}
                    className={className}
                    key={`${element.id}-${index}`}
                    onClick={(event) => selectRoofFromPlan(element.id, planElementSelectionMode(event, element.id))}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") selectRoofFromPlan(element.id);
                    }}
                    role="button"
                    stroke={stroke}
                    tabIndex={0}
                    x1={member[0][0]}
                    x2={member[1][0]}
                    y1={member[0][1]}
                    y2={member[1][1]}
                  />)}
                </g>;
              }
              if (selectedElementKind !== "BEAM" && footprint && footprint.length >= 3) {
                return <g key={element.id}>
                  {columnItem && center ? <rect
                    className={`column-plan-marker ${className}`}
                    fill={selected ? "rgba(0, 167, 122, .34)" : "rgba(255, 255, 255, .82)"}
                    height="0.015"
                    rx="0.0015"
                    stroke={selected ? "#007f5f" : completed ? "#00a77a" : "#3aa7eb"}
                    width="0.009"
                    x={center[0] - 0.0045}
                    y={center[1] - 0.0075}
                  /> : isRoofColumnElement ? <polygon
                    className={`roof-column-plan-marker ${className}`}
                    points={footprint.map((point) => point.join(",")).join(" ")}
                    stroke={selected ? "#007f5f" : stroke}
                  /> : isKingPostElement && center ? <>
                    <ellipse
                      className={`king-post-plan-marker ${className}`}
                      cx={center[0]}
                      cy={center[1]}
                      fill={stroke}
                      rx={kingPostRadiusX}
                      ry={kingPostRadiusY}
                      stroke={stroke}
                    />
                    <ellipse
                      aria-hidden="true"
                      className="king-post-plan-center"
                      cx={center[0]}
                      cy={center[1]}
                      rx={kingPostRadiusX * 0.28}
                      ry={kingPostRadiusY * 0.28}
                    />
                  </> : <polygon
                    className={`${slabItem || stairItem ? "slab-plan-zone " : ""}${className}`}
                    fill={stroke}
                    points={footprint.map((point) => point.join(",")).join(" ")}
                    stroke={(slabItem || stairItem) && selected ? "#007f5f" : stroke}
                  />}
                  {columnItem && center && <circle
                    aria-label={`เลือกเสา ${columnItem.code} Grid ${columnItem.grid_label}`}
                    className="column-hit-target"
                    cx={center[0]}
                    cy={center[1]}
                    onClick={(event) => selectColumnFromPlan(columnItem, planElementSelectionMode(event, element.id))}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") selectColumnFromPlan(columnItem);
                    }}
                    r="0.011"
                    role="button"
                    tabIndex={0}
                  />}
                  {slabItem && <polygon
                    aria-label={`เลือก${slabItem.code}`}
                    className="slab-hit-target"
                    onClick={(event) => selectSlabFromPlan(slabItem, planElementSelectionMode(event, element.id))}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") selectSlabFromPlan(slabItem);
                    }}
                    points={footprint.map((point) => point.join(",")).join(" ")}
                    role="button"
                    tabIndex={0}
                  />}
                  {stairItem && <polygon
                    aria-label={`เลือกบันได ${stairItem.code}`}
                    className="stair-hit-target"
                    onClick={(event) => selectStairFromPlan(stairItem, planElementSelectionMode(event, element.id))}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") selectStairFromPlan(stairItem);
                    }}
                    points={footprint.map((point) => point.join(",")).join(" ")}
                    role="button"
                    tabIndex={0}
                  />}
                  {selectedElementKind === "ROOF" && isKingPostElement && center ? <ellipse
                    aria-label={`เลือก ${element.code}`}
                    className="roof-hit-target"
                    cx={center[0]}
                    cy={center[1]}
                    onClick={(event) => selectRoofFromPlan(element.id, planElementSelectionMode(event, element.id))}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") selectRoofFromPlan(element.id);
                    }}
                    rx={kingPostRadiusX * 1.7}
                    ry={kingPostRadiusY * 1.7}
                    role="button"
                    tabIndex={0}
                  /> : selectedElementKind === "ROOF" && <polygon
                    aria-label={`เลือก ${element.code}`}
                    className="roof-hit-target"
                    onClick={(event) => selectRoofFromPlan(element.id, planElementSelectionMode(event, element.id))}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") selectRoofFromPlan(element.id);
                    }}
                    points={footprint.map((point) => point.join(",")).join(" ")}
                    role="button"
                    tabIndex={0}
                  />}
                </g>;
              }
              if (beamItem && line) {
                const beamLength = Number(beamItem.length_m ?? 0);
                const ranges = beamStageRanges[beamItem.beam_segment_id]?.[selectedBeamStageCode] ?? [];
                return <g key={element.id}>
                  <line
                    className={`beam-range-base is-not-started${beamLength <= 1 ? " is-short-beam" : ""}${nearCurrent ? " is-current-area" : ""}${selected ? " is-selected-element" : ""}`}
                    stroke={selectedTrackGroup.color}
                    x1={line[0][0]}
                    x2={line[1][0]}
                    y1={line[0][1]}
                    y2={line[1][1]}
                  />
                  {beamLength > 0 && ranges.map((range, index) => {
                    const startRatio = Math.max(0, Math.min(1, range.start_m / beamLength));
                    const endRatio = Math.max(0, Math.min(1, range.end_m / beamLength));
                    return <line
                      className={`beam-range-completed is-complete${nearCurrent ? " is-current-area" : ""}${selected ? " is-selected-element" : ""}`}
                      key={`${range.start_m}-${range.end_m}-${index}`}
                      stroke={selectedTrackGroup.color}
                      x1={line[0][0] + (line[1][0] - line[0][0]) * startRatio}
                      x2={line[0][0] + (line[1][0] - line[0][0]) * endRatio}
                      y1={line[0][1] + (line[1][1] - line[0][1]) * startRatio}
                      y2={line[0][1] + (line[1][1] - line[0][1]) * endRatio}
                    />;
                  })}
                  <line
                    aria-hidden="true"
                    className="beam-hit-target"
                    onClick={(event) => selectBeamFromPlan(beamItem, planElementSelectionMode(event, element.id))}
                    x1={line[0][0]}
                    x2={line[1][0]}
                    y1={line[0][1]}
                    y2={line[1][1]}
                  />
                </g>;
              }
              return line ? <line
                aria-label={beamItem ? `เลือก${beamDisplayName(beamItem)}` : selectedElementKind === "ROOF" ? `เลือก ${element.code}` : undefined}
                className={className}
                key={element.id}
                onClick={beamItem
                  ? (event) => selectBeamFromPlan(beamItem, planElementSelectionMode(event, element.id))
                  : selectedElementKind === "ROOF"
                    ? (event) => selectRoofFromPlan(element.id, planElementSelectionMode(event, element.id))
                    : undefined}
                onKeyDown={beamItem ? (event) => {
                  if (event.key === "Enter" || event.key === " ") selectBeamFromPlan(beamItem);
                } : selectedElementKind === "ROOF" ? (event) => {
                  if (event.key === "Enter" || event.key === " ") selectRoofFromPlan(element.id);
                } : undefined}
                role={beamItem || selectedElementKind === "ROOF" ? "button" : undefined}
                stroke={stroke}
                tabIndex={beamItem || selectedElementKind === "ROOF" ? 0 : undefined}
                x1={line[0][0]}
                x2={line[1][0]}
                y1={line[0][1]}
                y2={line[1][1]}
              /> : null;
            })}
              {planSelectionBox && <rect
                className={planSelectionBox.current[0] >= planSelectionBox.start[0] ? "plan-selection-box is-window" : "plan-selection-box is-crossing"}
                height={Math.abs(planSelectionBox.current[1] - planSelectionBox.start[1])}
                width={Math.abs(planSelectionBox.current[0] - planSelectionBox.start[0])}
                x={Math.min(planSelectionBox.start[0], planSelectionBox.current[0])}
                y={Math.min(planSelectionBox.start[1], planSelectionBox.current[1])}
              />}
            </svg>}
            {selectedPlanElementIds.length > 1 && <span className="plan-selection-count">เลือกแล้ว {selectedPlanElementIds.length} ชิ้น</span>}
            {selectedTrackGroup && selectedStructuralElements.length > 0 && <span className="plan-selection-help">{isCameraPickMode ? "คลิกซ้ายที่จุดสีเขียวเพื่อเปลี่ยนมุมกล้อง · Esc ออกจากโหมด" : multiSelectEnabled ? "โหมดหลายชิ้น · คลิกเพื่อเพิ่ม/ลบ · ลากครอบเพื่อเพิ่ม · Shift ลบ · Esc ล้าง" : "โหมดชิ้นเดียว · คลิกหรือครอบเพื่อเลือก · Ctrl เพิ่ม · Shift ลบ · Esc ล้าง"}</span>}
            {currentPlanPosition && <>
              <span aria-hidden="true" className="current-view-cone track-current-view-cone" style={{ left: `${currentPlanPosition.x * 100}%`, top: `${currentPlanPosition.y * 100}%`, transform: `translate(-50%, -88%) rotate(${currentPlanPosition.heading + 90}deg)` }} />
              <span aria-label="ตำแหน่งภาพ 360 ปัจจุบัน" className="current-path-position track-current-position" style={{ left: `${currentPlanPosition.x * 100}%`, top: `${currentPlanPosition.y * 100}%` }} />
            </>}
            </div>
            {activeFloor?.has_plan && loadedPlanFloorId !== activeFloor.id && <div className={`track-plan-image-state${failedPlanFloorId === activeFloor.id ? " is-error" : ""}`} role="status">
              {failedPlanFloorId === activeFloor.id ? <>
                <strong>เปิดภาพแปลนไม่สำเร็จ</strong>
                <span>การเลือกชั้นยังอยู่ที่ {activeFloor.name}</span>
                <button onClick={() => {
                  setLoadedPlanFloorId(null);
                  setFailedPlanFloorId(null);
                  setPlanImageRevision((current) => current + 1);
                }} type="button">ลองโหลดแปลนอีกครั้ง</button>
              </> : <><span className="track-plan-loading-spinner" /><strong>กำลังโหลดแปลน {activeFloor.name}</strong></>}
            </div>}
            </div>
          </div>
        </section>
        <section className="track-sheet-360-pane"><span className="track-image-date">ภาพวันที่ {new Date(detail.capture.captured_at).toLocaleDateString("th-TH")}</span><PanoramaViewer canEdit={canEdit} detail={detail} floors={floors} onSelectedKeyframeChange={setSelectedKeyframeId} onViewStateChange={handlePanoramaViewChange} projectId={projectId} requestedKeyframeId={selectedKeyframeId} /></section>
        <aside className="track-sheet-breakdown"><header><strong>Progress งานโครงสร้าง</strong><span>ณ {new Date(detail.capture.captured_at).toLocaleDateString("th-TH")}</span></header><div className="track-sheet-actions"><button onClick={() => setVisibleTrackGroups(Object.fromEntries(trackGroups.map((group) => [group.wbs, true])))} type="button">แสดงทุกงาน</button><button onClick={() => setVisibleTrackGroups(Object.fromEntries(trackGroups.map((group) => [group.wbs, false])))} type="button">ซ่อนทุกงาน</button></div>{selectedStructuralElements.length > 0 && <div className="track-sheet-actions plan-bulk-actions"><button aria-pressed={multiSelectEnabled} className={multiSelectEnabled ? "is-active" : ""} onClick={() => setMultiSelectEnabled((current) => !current)} type="button">{multiSelectEnabled ? "เลือกหลายชิ้น ✓" : "เลือกชิ้นเดียว"}</button><button onClick={selectAllElementsInCurrentWork} type="button">เลือกทั้งหมด ({selectedStructuralElements.length})</button><button disabled={!selectedPlanElementIds.length} onClick={() => {
          setSelectedPlanElementIds([]);
          setSelectedBeamSegmentId(null);
          setSelectedColumnId(null);
          setSelectedSlabId(null);
          setSelectedStairId(null);
          setSelectedRoofId(null);
        }} type="button">ล้างที่เลือก</button></div>}{selectedElementKind === "BEAM" && beamProgress?.items.length ? <label className="beam-segment-picker"><span>คานที่กำลังตรวจ</span><select aria-label="เลือกช่วงคาน" onChange={(event) => {
          const item = beamProgress.items.find((candidate) => candidate.beam_segment_id === event.target.value);
          if (!item) return;
          selectBeamFromPlan(item, multiSelectEnabled ? "add" : "replace");
        }} value={selectedBeamSegmentId ?? ""}><option value="">คลิกคานในแบบ หรือเลือกจากรายการ</option>{beamProgress.items.map((item) => <option key={item.beam_segment_id} value={item.beam_segment_id}>{beamDisplayName(item)} · {beamOverallPercent(item, beamStageRanges[item.beam_segment_id], beamStages).toFixed(1)}%</option>)}</select></label> : null}{selectedBeamItem && <section className="beam-stage-editor">
          <header><div><strong>{beamItemsToEdit.length > 1 ? `เลือกคาน ${beamItemsToEdit.length} ชิ้น` : beamDisplayName(selectedBeamItem)}</strong><span>คานหลัก {beamDisplayName(selectedBeamItem)} · ความยาว {Number(selectedBeamItem.length_m ?? 0).toFixed(3)} ม.</span></div><b>{beamOverallPercent(selectedBeamItem, beamStageRanges[selectedBeamItem.beam_segment_id], beamStages).toFixed(1)}%</b></header>
          <p>{beamItemsToEdit.length > 1 ? "ช่วงงานด้านล่างจะบันทึกให้คานที่เลือกทั้งหมด ถ้าระบุเต็มความยาวคานหลัก ระบบจะใช้เต็มความยาวจริงของคานแต่ละชิ้น ภาพหลักฐานจะใช้จุดบนเส้นทาง Capture ที่เลือกอยู่" : "เลือกจุดกล้องจากเส้นทาง Capture ด้วยตนเอง แล้วเลือกงานและระยะตามแนวคาน การคลิกคานจะไม่เปลี่ยนตำแหน่งหรือทิศกล้อง ภาพ 360 ปัจจุบันจะถูกเก็บเป็นหลักฐานของวันตรวจ"}</p>
          {canEditProgressQuantities && <div className="beam-length-form">
            <label><span>แก้ความยาวคานจริง (เมตร)</span><input inputMode="decimal" min="0.001" onChange={(event) => setBeamLengthDraft(event.target.value)} step="0.001" type="number" value={beamLengthDraft} /></label>
            <button disabled={beamLengthSaveBusy} onClick={saveSelectedBeamLength} type="button">{beamLengthSaveBusy ? "กำลังบันทึก…" : "บันทึกความยาวคาน"}</button>
            <small>ค่านี้แก้เฉพาะคานหลักที่แสดงอยู่ และจะเปลี่ยนทุกวันที่ตรวจ</small>
          </div>}
          <div className="beam-range-form">
            <label><span>งานที่ตรวจ</span><select disabled={!canEditProgress} onChange={(event) => setEditingBeamStage(event.target.value as BeamStageCode)} value={editingBeamStage}>{beamStages.map((stage) => <option key={stage.code} value={stage.code}>{stage.label}</option>)}</select></label>
            <label><span>จากเมตรที่</span><input disabled={!canEditProgress} inputMode="decimal" min="0" onChange={(event) => setRangeStartM(event.target.value)} step="0.001" type="number" value={rangeStartM} /></label>
            <label><span>ถึงเมตรที่</span><input disabled={!canEditProgress} inputMode="decimal" max={Number(selectedBeamItem.length_m ?? 0)} min="0" onChange={(event) => setRangeEndM(event.target.value)} step="0.001" type="number" value={rangeEndM} /></label>
            {canEditProgress && <button disabled={beamSaveBusy} onClick={addSelectedBeamRange} type="button">{beamSaveBusy ? "กำลังบันทึก…" : beamItemsToEdit.length > 1 ? `เพิ่มและบันทึกให้ ${beamItemsToEdit.length} คาน` : "เพิ่มและบันทึกช่วงงาน"}</button>}
            {beamSaveMessage && <p role="status">{beamSaveMessage}</p>}
          </div>
          <div className="beam-range-list">{beamStages.map((stage) => {
            const ranges = beamStageRanges[selectedBeamItem.beam_segment_id]?.[stage.code] ?? [];
            const done = coveredLength(ranges);
            return <section key={stage.code}><header><strong>{stage.label}</strong><span>{done.toFixed(3)} / {Number(selectedBeamItem.length_m ?? 0).toFixed(3)} ม. · {beamStagePercent(selectedBeamItem, beamStageRanges[selectedBeamItem.beam_segment_id], stage.code).toFixed(1)}%</span></header>{ranges.length ? <ul>{ranges.map((range, index) => <li key={`${range.start_m}-${range.end_m}-${index}`}><span>{range.start_m.toFixed(3)}–{range.end_m.toFixed(3)} ม.</span>{canEditProgress && <button aria-label={`ลบช่วง ${range.start_m.toFixed(3)} ถึง ${range.end_m.toFixed(3)} เมตร${beamItemsToEdit.length > 1 ? ` จากคานที่เลือก ${beamItemsToEdit.length} ชิ้น` : ""}`} disabled={beamSaveBusy} onClick={() => removeSelectedBeamRange(stage.code, index)} type="button">{beamItemsToEdit.length > 1 ? `ลบจาก ${beamItemsToEdit.length} คาน` : "ลบ"}</button>}</li>)}</ul> : <small>ยังไม่มีช่วงงาน</small>}</section>;
          })}</div>
          <small>งานคานทั้งชั้นยาว {formatQuantity2(beamProgress?.total_length_m)} ม. · Progress รวมคิดจาก 5 งาน = {localBeamProgress.toFixed(2)}%</small>
          {canEditProgress && <button disabled={beamSaveBusy} onClick={saveSelectedBeamProgress} type="button">{beamSaveBusy ? "กำลังบันทึก…" : "บันทึกช่วงงาน + วันที่ตรวจ + ภาพ 360"}</button>}
        </section>}{selectedElementKind === "COLUMN" && columnProgress?.items.length ? <>
          <label className="beam-segment-picker"><span>เสาที่กำลังตรวจ</span><select aria-label="เลือกเสา" onChange={(event) => {
            const item = columnProgress.items.find((candidate) => candidate.structural_element_id === event.target.value);
            if (item) selectColumnFromPlan(item, multiSelectEnabled ? "add" : "replace");
          }} value={selectedColumnId ?? ""}><option value="">คลิกเสาในแบบ หรือเลือกจากรายการ</option>{columnProgress.items.map((item) => <option key={item.structural_element_id} value={item.structural_element_id}>{item.code} · Grid {item.grid_label} · {(columnStages[item.structural_element_id]?.length ?? 0) * 25}%</option>)}</select></label>
          {selectedColumnItem && <section className="beam-stage-editor column-stage-editor">
            <header><div><strong>{columnItemsToEdit.length > 1 ? `เลือกเสา ${columnItemsToEdit.length} ต้น` : `${selectedColumnItem.code} · Grid ${selectedColumnItem.grid_label}`}</strong><span>การเปลี่ยนขั้นงานจะบันทึกให้เสาที่เลือกพร้อมกัน</span></div><b>{(columnStages[selectedColumnItem.structural_element_id]?.length ?? 0) * 25}%</b></header>
            <p>แต่ละขั้นงานคิด 25% เลือกเฉพาะงานที่ทำเสร็จแล้ว หากเลือกหลายต้น ช่องจะถูกเลือกเมื่อทุกต้นมีขั้นงานนั้น</p>
            <div>{COLUMN_STAGES.map((stage) => <label key={stage.code}><input checked={columnItemsToEdit.length > 0 && columnItemsToEdit.every((item) => (columnStages[item.structural_element_id] ?? []).includes(stage.code))} disabled={!canEditProgress || columnSaveBusy} onChange={() => toggleSelectedColumnStage(stage.code)} type="checkbox" /><span>{stage.label}</span><small>25%</small></label>)}</div>
            <small>เสาทั้งชั้น {columnProgress.column_count} ต้น · Progress งานเสารวม {localColumnProgress.toFixed(2)}%</small>
            {canEditProgress && <button disabled={columnSaveBusy} onClick={() => void saveSelectedColumnProgress()} type="button">{columnSaveBusy ? "กำลังบันทึก…" : columnItemsToEdit.length > 1 ? `บันทึกพร้อมกัน ${columnItemsToEdit.length} ต้น` : "บันทึกงานเสาอีกครั้ง"}</button>}
            {columnSaveMessage && <p role="status">{columnSaveMessage}</p>}
          </section>}
        </> : null}{selectedElementKind === "SLAB" && slabProgress?.items.length ? <>
          <label className="beam-segment-picker"><span>พื้นที่กำลังตรวจ</span><select aria-label="เลือกพื้นที่พื้น" onChange={(event) => {
            const item = slabProgress.items.find((candidate) => candidate.structural_element_id === event.target.value);
            if (item) selectSlabFromPlan(item, multiSelectEnabled ? "add" : "replace");
          }} value={selectedSlabId ?? ""}><option value="">คลิกพื้นที่สีแดงในแบบ หรือเลือกจากรายการ</option>{slabProgress.items.map((item) => <option key={item.structural_element_id} value={item.structural_element_id}>{item.geometry_json.slab_type ? `${item.geometry_json.slab_type} · ` : ""}{item.code} · {Number(item.area_m2).toFixed(2)} ตร.ม. · {slabItemProgress(item, slabStages[item.structural_element_id] ?? []).toFixed(0)}%</option>)}</select></label>
          {selectedSlabItem && <section className="beam-stage-editor slab-stage-editor">
            <header><div><strong>{slabItemsToEdit.length > 1 ? `เลือกพื้น ${slabItemsToEdit.length} พื้นที่` : `${selectedSlabItem.geometry_json.slab_type ? `${selectedSlabItem.geometry_json.slab_type} · ` : ""}${selectedSlabItem.code}`}</strong><span>พื้นที่หลักประมาณ {Number(selectedSlabItem.area_m2).toFixed(2)} ตร.ม.</span></div><b>{selectedSlabProgress.toFixed(0)}%</b></header>
            <p>{slabWorkflowSummary(selectedSlabItem)} เปอร์เซ็นต์ด้านขวาคือผลรวมของพื้นที่ที่เลือก และผลจากวันก่อนจะถูกยกมาแสดงในจำนวนแต่ละขั้นด้านล่าง</p>
            {canEditProgressQuantities && <div className="beam-length-form">
              <label><span>แก้พื้นที่ตรวจจริง (ตร.ม.)</span><input inputMode="decimal" min="0.001" onChange={(event) => setSlabAreaDraft(event.target.value)} step="0.001" type="number" value={slabAreaDraft} /></label>
              <button disabled={slabAreaSaveBusy} onClick={saveSelectedSlabArea} type="button">{slabAreaSaveBusy ? "กำลังบันทึก…" : "บันทึกพื้นที่ตรวจ"}</button>
              <small>แก้เฉพาะพื้นที่คำนวณ Progress โดยไม่เปลี่ยนรหัสหรือรูปทรงในแปลน</small>
            </div>}
            <div>{selectedSlabStageOptions.map((stage, index) => {
              const eligibleItems = slabItemsToEdit.filter((item) => slabStageOptions(item).some((option) => option.code === stage.code));
              const label = selectedSlabItem.geometry_json.slab_type
                ? stage.label
                : selectedTrackGroup?.rows[index]?.name ?? stage.label;
              const completedItems = eligibleItems.filter((item) => (slabStages[item.structural_element_id] ?? []).includes(stage.code)).length;
              return <label key={stage.code}><input aria-label={`${label} เสร็จ ${completedItems} จาก ${eligibleItems.length} พื้นที่`} checked={eligibleItems.length > 0 && completedItems === eligibleItems.length} disabled={!canEditProgress || slabSaveBusy} onChange={() => toggleSelectedSlabStage(stage.code)} type="checkbox" /><span>{label}</span><small>{eligibleItems.length ? `${completedItems}/${eligibleItems.length} พื้นที่` : "–"}</small></label>;
            })}</div>
            <small>พื้นทั้งชั้น {slabProgress.zone_count} โซน · {formatQuantity2(slabProgress.total_area_m2)} ตร.ม. · Progress รวม {localSlabProgress.toFixed(2)}%</small>
            {canEditProgress && <button disabled={slabSaveBusy} onClick={() => void saveSelectedSlabProgress()} type="button">{slabSaveBusy ? "กำลังบันทึก…" : slabItemsToEdit.length > 1 ? `บันทึกพร้อมกัน ${slabItemsToEdit.length} พื้นที่` : "บันทึกงานพื้นอีกครั้ง"}</button>}
            {slabSaveMessage && <p role="status">{slabSaveMessage}</p>}
          </section>}
        </> : null}{selectedElementKind === "STAIR" && stairProgress?.items.length ? <>
          <label className="beam-segment-picker"><span>บันไดที่กำลังตรวจ</span><select aria-label="เลือกบันได" onChange={(event) => {
            const item = stairProgress.items.find((candidate) => candidate.structural_element_id === event.target.value);
            if (item) selectStairFromPlan(item, multiSelectEnabled ? "add" : "replace");
          }} value={selectedStairId ?? ""}><option value="">คลิกพื้นที่บันไดในแบบ หรือเลือกจากรายการ</option>{stairProgress.items.map((item) => <option key={item.structural_element_id} value={item.structural_element_id}>{item.code} · {(stairStages[item.structural_element_id]?.length ?? 0) / stairStageOptions.length * 100}%</option>)}</select></label>
          {selectedStairItem && <section className="beam-stage-editor stair-stage-editor">
            <header><div><strong>{stairItemsToEdit.length > 1 ? `เลือกบันได ${stairItemsToEdit.length} ชุด` : selectedStairItem.code}</strong><span>การเปลี่ยนขั้นงานจะบันทึกให้บันไดที่เลือกพร้อมกัน</span></div><b>{((stairStages[selectedStairItem.structural_element_id]?.length ?? 0) / stairStageOptions.length * 100).toFixed(0)}%</b></header>
            <p>ขั้นงานแยกตามชั้นโดยตรง ชั้น 2 ขึ้นไปมีงานค้ำยัน และผลตรวจของแต่ละชั้นจะไม่ปะปนกัน</p>
            <div>{stairStageOptions.map((stage) => <label key={stage.code}><input checked={stairItemsToEdit.length > 0 && stairItemsToEdit.every((item) => (stairStages[item.structural_element_id] ?? []).includes(stage.code))} disabled={!canEditProgress || stairSaveBusy} onChange={() => void toggleSelectedStairStage(stage.code)} type="checkbox" /><span>{stage.label}</span><small>{(100 / stairStageOptions.length).toFixed(stairStageOptions.length === 4 ? 0 : 2)}%</small></label>)}</div>
            <small>บันไดทั้งชั้น {stairProgress.stair_count} ชุด · Progress รวม {localStairProgress.toFixed(2)}%</small>
            {canEditProgress && <button disabled={stairSaveBusy} onClick={() => void saveSelectedStairProgress()} type="button">{stairSaveBusy ? "กำลังบันทึก…" : stairItemsToEdit.length > 1 ? `บันทึกพร้อมกัน ${stairItemsToEdit.length} ชุด` : "บันทึกงานบันไดอีกครั้ง"}</button>}
            {stairSaveMessage && <p role="status">{stairSaveMessage}</p>}
          </section>}
        </> : null}{selectedElementKind === "ROOF" && roofProgress ? <>
          <label className="beam-segment-picker"><span>ชิ้นงานหลังคาที่กำลังตรวจ</span><select aria-label="เลือกชิ้นงานหลังคา" onChange={(event) => {
            const item = roofProgress.items.find((candidate) => candidate.structural_element_id === event.target.value);
            if (item) selectRoofFromPlan(item.structural_element_id, multiSelectEnabled ? "add" : "replace");
          }} value={selectedRoofId ?? ""}><option value="">คลิกชิ้นงานในแบบ หรือเลือกจากรายการ</option>{roofProgress.items.filter((item) => item.activity_wbs === selectedTrackGroup?.wbs).map((item) => {
            const total = roofTotals[item.structural_element_id] ?? 1;
            const completed = roofQuantities[item.structural_element_id] ?? (roofCompletion[item.structural_element_id] ? total : 0);
            return <option key={item.structural_element_id} value={item.structural_element_id}>{item.code} · {item.geometry_json.progress_mode === "COUNT" ? `${completed}/${total} ตัว · ${(completed / total * 100).toFixed(0)}%` : roofCompletion[item.structural_element_id] ? "เสร็จแล้ว" : "ยังไม่เสร็จ"}</option>;
          })}</select></label>
          {selectedRoofItem && <section className="beam-stage-editor roof-stage-editor">
            <header><div><strong>{roofItemsToEdit.length > 1 ? `เลือกงานหลังคา ${roofItemsToEdit.length} ชิ้น` : selectedRoofItem.code}</strong><span>{selectedTrackGroup?.name ?? "งานโครงสร้างหลังคา"} · บันทึกพร้อมภาพ 360 ปัจจุบัน</span></div><b>{selectedRoofUsesCount ? `${((roofQuantities[selectedRoofItem.structural_element_id] ?? 0) / Math.max(roofTotals[selectedRoofItem.structural_element_id] ?? 1, 1) * 100).toFixed(0)}%` : roofItemsToEdit.every((item) => roofCompletion[item.structural_element_id]) ? "100%" : "0%"}</b></header>
            {selectedRoofUsesCount ? <>
              <p>ชุดนี้ตรวจตามจำนวนตัว ผู้ตรวจกรอกจำนวนที่พบจริง ระบบคำนวณเปอร์เซ็นต์จากจำนวนที่ตรวจแล้วเทียบกับจำนวนทั้งหมด</p>
              <div className="beam-length-form">
                <label><span>จำนวนทั้งหมด (ตัว)</span><input inputMode="numeric" min="1" onChange={(event) => setRoofTotalDraft(event.target.value)} step="1" type="number" value={roofTotalDraft} /></label>
                <label><span>จำนวนที่ตรวจแล้ว (ตัว)</span><input inputMode="numeric" min="0" onChange={(event) => setRoofQuantityDraft(event.target.value)} step="1" type="number" value={roofQuantityDraft} /></label>
                <button disabled={!canEditProgress || roofSaveBusy} onClick={() => void saveSelectedRoofQuantity()} type="button">{roofSaveBusy ? "กำลังบันทึก…" : roofCountItemsToEdit.length > 1 ? `บันทึกพร้อมกัน ${roofCountItemsToEdit.length} ชุด` : "บันทึกจำนวนที่ตรวจ"}</button>
              </div>
            </> : <>
              <p>เลือกเฉพาะชิ้นงานที่ตรวจจากภาพ 360 แล้ว การเปลี่ยนสถานะจะบันทึกให้ชิ้นงานที่เลือกทั้งหมดพร้อมกันและส่งผลรวมไปยัง Dashboard</p>
              <div><label><input checked={roofItemsToEdit.length > 0 && roofItemsToEdit.every((item) => roofCompletion[item.structural_element_id])} disabled={!canEditProgress || roofSaveBusy} onChange={() => void toggleSelectedRoofComplete()} type="checkbox" /><span>ดำเนินงานชิ้นนี้เสร็จแล้ว</span><small>100%</small></label></div>
            </>}
            {canEditProgress && roofItemsRecordedOnThisCapture.length > 0 && <button className="button button-danger roof-progress-delete" disabled={roofSaveBusy} onClick={() => void deleteSelectedRoofProgress()} type="button">{roofSaveBusy ? "กำลังดำเนินการ…" : `ลบผลตรวจของวันนี้ (${roofItemsRecordedOnThisCapture.length})`}</button>}
            <small>งานประเภทนี้ {roofProgress.items.filter((item) => item.activity_wbs === selectedTrackGroup?.wbs).length} ชุด/ชิ้น · Progress รวม {roofProgressForWbs(selectedTrackGroup?.wbs ?? "").toFixed(2)}%</small>
            {roofSaveMessage && <p role="status">{roofSaveMessage}</p>}
          </section>}
        </> : null}<div className="track-sheet-groups">{trackGroups.map((group) => {
          const visible = visibleTrackGroups[group.wbs] ?? true;
          const groupKind = elementKindForGroup(group.name);
          const groupElements = groupKind ? structuralElements.filter((item) => (
            item.element_kind === groupKind
            && (groupKind !== "ROOF" || item.geometry_json.activity_wbs === group.wbs)
          )) : [];
          const beamSpatialGroup = groupKind === "BEAM" && beamProgress?.items.length;
          const columnSpatialGroup = groupKind === "COLUMN" && columnProgress?.items.length;
          const slabSpatialGroup = groupKind === "SLAB" && slabProgress?.items.length;
          const stairSpatialGroup = groupKind === "STAIR" && stairProgress?.items.length;
          const roofSpatialGroup = groupKind === "ROOF" && roofProgress?.items.some((item) => item.activity_wbs === group.wbs);
          const spatialPercent = beamSpatialGroup
            ? localBeamProgress
            : columnSpatialGroup
            ? localColumnProgress
            : slabSpatialGroup
            ? localSlabProgress
            : stairSpatialGroup
            ? localStairProgress
            : roofSpatialGroup
            ? roofProgressForWbs(group.wbs)
            : group.percent;
          return <article className={!visible ? "is-muted" : ""} key={group.wbs}><label><input checked={visible} onChange={(event) => setVisibleTrackGroups((current) => ({ ...current, [group.wbs]: event.target.checked }))} type="checkbox" /><i style={{ background: group.color }} /><strong>{group.name}</strong></label><div className="track-sheet-progress"><span><i style={{ background: group.color, width: `${spatialPercent}%` }} /></span><b>{spatialPercent.toFixed(0)}%</b></div><small>{beamSpatialGroup ? `${beamProgress!.labeled_count} / ${beamProgress!.segment_count} ชิ้นตรวจแล้ว` : columnSpatialGroup ? `${columnProgress!.labeled_count} / ${columnProgress!.column_count} ต้นตรวจแล้ว` : slabSpatialGroup ? `${slabProgress!.labeled_count} / ${slabProgress!.zone_count} โซนตรวจแล้ว` : stairSpatialGroup ? `${stairProgress!.labeled_count} / ${stairProgress!.stair_count} ชุดตรวจแล้ว` : roofSpatialGroup ? `${roofProgress!.items.filter((item) => item.activity_wbs === group.wbs && item.progress_percent !== null).length} / ${roofProgress!.items.filter((item) => item.activity_wbs === group.wbs).length} ชิ้นตรวจแล้ว` : groupElements.length ? `${groupElements.length} ชิ้นจาก IFC/แปลน · ${group.reviewed}/${group.rows.length} ขั้นตรวจแล้ว` : `${group.reviewed} / ${group.rows.length} รายการตรวจแล้ว`}</small><div className="track-stage-list">{group.rows.map((row, index) => {
            const stageCode = beamStageForActivity(row.name, beamStages, index);
            const columnStageCode = COLUMN_STAGES[Math.min(index, COLUMN_STAGES.length - 1)].code;
            const completedLength = beamSpatialGroup ? beamProgress!.items.reduce((sum, item) => (
              sum + coveredLength(beamStageRanges[item.beam_segment_id]?.[stageCode])
            ), 0) : 0;
            const completedColumns = columnSpatialGroup ? columnProgress!.items.filter((item) => (columnStages[item.structural_element_id] ?? []).includes(columnStageCode)).length : 0;
            const slabStageCode = slabStageForActivity(row.name, selectedSlabStageOptions, index);
            const completedSlabArea = slabSpatialGroup ? slabProgress!.items.reduce((sum, item) => sum + ((slabStages[item.structural_element_id] ?? []).includes(slabStageCode) ? Number(item.area_m2) : 0), 0) : 0;
            const stairStageCode = stairStageForActivity(row.name, stairStageOptions, index);
            const completedStairs = stairSpatialGroup ? stairProgress!.items.filter((item) => (stairStages[item.structural_element_id] ?? []).includes(stairStageCode)).length : 0;
          return <button className={selectedTrackActivityId === row.id ? "is-active" : ""} key={row.id} onClick={() => {
            setSelectedTrackActivityId(row.id);
            if (beamSpatialGroup) setEditingBeamStage(beamStageForActivity(row.name, beamStages, index));
          }} type="button"><span>{row.name}</span>{beamSpatialGroup && <b>{completedLength.toFixed(2)}/{formatQuantity2(beamProgress!.total_length_m)} ม.</b>}{columnSpatialGroup && <b>{completedColumns}/{columnProgress!.column_count} ต้น</b>}{slabSpatialGroup && <b>{completedSlabArea.toFixed(2)}/{formatQuantity2(slabProgress!.total_area_m2)} ตร.ม.</b>}{stairSpatialGroup && <b>{completedStairs}/{stairProgress!.stair_count} ชุด</b>}</button>;
          })}</div><label className="track-not-started-toggle"><span>แสดงตำแหน่งที่ยังไม่เริ่ม</span><input checked={showNotStarted[group.wbs] ?? false} onChange={(event) => setShowNotStarted((current) => ({ ...current, [group.wbs]: event.target.checked }))} type="checkbox" /></label></article>;
        })}</div></aside>
      </div> : <div className="capture-bim-stage">
        <div className="capture-pane panorama-pane">
          <PanoramaViewer
            canEdit={canEditProgress}
            detail={detail}
            floors={floors}
            onSelectedKeyframeChange={setSelectedKeyframeId}
            onViewStateChange={handlePanoramaViewChange}
            projectId={projectId}
            requestedKeyframeId={selectedKeyframeId}
          />
        </div>
        {viewMode !== "360" && (
          <div className="capture-pane bim-pane">
            {bimModel ? (
              <>
                <BimViewer
                  activeKeyframeId={selectedKeyframeId}
                  canSaveViewpoint={canEditProgress}
                  keyframes={detail.keyframes}
                  model={bimModel}
                  onSelectKeyframe={setSelectedKeyframeId}
                  panoramaView={panoramaView}
                  planImageUrl={activeFloor?.has_plan ? `/api/projects/${projectId}/floors/${activeFloor.id}/plan` : null}
                  structuralElements={structuralElements}
                />
                {canManageBim && <BimModelUploader compact projectId={projectId} />}
              </>
            ) : (
              <div className="bim-empty-state">
                <span aria-hidden="true">3D</span>
                <strong>ยังไม่มีโมเดล BIM ของโครงการ</strong>
                <p>เพิ่มไฟล์ IFC โครงสร้างจาก Revit เพื่อเทียบกับภาพ 360°</p>
                {canManageBim ? <BimModelUploader projectId={projectId} /> : <small>ผู้ดูแลโครงการเป็นผู้เพิ่มไฟล์ IFC ได้</small>}
              </div>
            )}
          </div>
        )}
      </div>}

      <CaptureFieldNotes
        canEdit={canEditProgress}
        detail={detail}
        floors={floors}
        initialNotes={fieldNotes}
        members={members}
        projectId={projectId}
        selectedKeyframeId={selectedKeyframeId}
        view={panoramaView}
      />
    </div>
  );
}
