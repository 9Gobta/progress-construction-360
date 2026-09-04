"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import Image from "next/image";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { BimModelUploader } from "@/components/bim-model-uploader";
import { PanoramaViewer, type PanoramaViewState } from "@/components/panorama-viewer";
import { StructuralProgressInspector } from "@/components/structural-progress-inspector";
import { SpatialTourInspector } from "@/components/spatial-tour-inspector";
import type { Activity, BeamProgress, BimModel, CaptureDetail, ColumnProgress, ColumnStageCode, Floor, HumanProgressEntry, SlabProgress, SlabStageCode, StructuralElement } from "@/lib/types";

type BeamStageCode = "SETTING_OUT" | "REBAR" | "FORMWORK" | "CONCRETE" | "STRIP_FORM";
type BeamRange = { start_m: number; end_m: number };
type BeamStageRanges = Partial<Record<BeamStageCode, BeamRange[]>>;
type BeamViewRequest = { keyframeId: string; worldHeading: number; token: number };

const BEAM_STAGES: Array<{ code: BeamStageCode; label: string }> = [
  { code: "SETTING_OUT", label: "เทลีน / เตรียมแนว" },
  { code: "REBAR", label: "ผูกเหล็ก" },
  { code: "FORMWORK", label: "เข้าแบบ" },
  { code: "CONCRETE", label: "เทคอนกรีต" },
  { code: "STRIP_FORM", label: "แกะแบบ" },
];

const COLUMN_STAGES: Array<{ code: ColumnStageCode; label: string }> = [
  { code: "REBAR", label: "ผูกเหล็กเสา" },
  { code: "FORMWORK", label: "เข้าแบบเสา" },
  { code: "CONCRETE", label: "เทคอนกรีตเสา" },
  { code: "STRIP_FORM", label: "ถอดแบบเสา" },
];
const SLAB_STAGE_CODES: SlabStageCode[] = ["STEP_1", "STEP_2", "STEP_3", "STEP_4", "STEP_5"];

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

function beamOverallPercent(item: BeamProgress["items"][number], ranges: BeamStageRanges | undefined) {
  const length = Number(item.length_m ?? 0);
  if (length <= 0) return 0;
  const completed = BEAM_STAGES.reduce((sum, stage) => sum + coveredLength(ranges?.[stage.code]), 0);
  return Math.min(100, (completed / (length * BEAM_STAGES.length)) * 100);
}

const PLAN_GRID_X = [0.1998, 0.2889, 0.3783, 0.4674, 0.5570, 0.6487] as const;
const PLAN_GRID_Y = [0.2729, 0.4075, 0.4715, 0.6057] as const;
const PLAN_GRID_X_LABELS = ["1", "2", "3", "4", "5", "6"] as const;
const PLAN_GRID_Y_LABELS = ["A", "B", "C", "D"] as const;
const PLAN_METERS_PER_NORMALIZED_Y = 9.9 / (0.6057 - 0.2729);
const MAX_BEAM_VIEW_DISTANCE_M = 3;

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

function beamStageThreshold(activityName: string, fallbackIndex: number, fallbackTotal: number) {
  if (activityName.includes("ผูกเหล็ก")) return 40;
  if (activityName.includes("เข้าแบบ") || activityName.includes("ตั้งแบบ")) return 60;
  if (activityName.includes("เท")) return 80;
  if (activityName.includes("ถอดแบบ") || activityName.includes("แกะแบบ")) return 100;
  return ((fallbackIndex + 1) * 100) / Math.max(fallbackTotal, 1);
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
  const line = element.geometry_json.line;
  return line
    ? [(Number(line[0][0]) + Number(line[1][0])) / 2, (Number(line[0][1]) + Number(line[1][1])) / 2]
    : null;
}

function closestPointOnPlanLine(
  point: [number, number],
  line: [[number, number], [number, number]],
  aspectRatio: number,
) {
  const scaleX = Math.max(aspectRatio, 0.01);
  const px = point[0] * scaleX;
  const py = point[1];
  const ax = Number(line[0][0]) * scaleX;
  const ay = Number(line[0][1]);
  const bx = Number(line[1][0]) * scaleX;
  const by = Number(line[1][1]);
  const dx = bx - ax;
  const dy = by - ay;
  const denominator = dx * dx + dy * dy;
  const ratio = denominator > 1e-12
    ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / denominator))
    : 0;
  const x = ax + dx * ratio;
  const y = ay + dy * ratio;
  return { x: x / scaleX, y, distance: Math.hypot(px - x, py - y) };
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
  structuralElements,
  canEdit,
  canEditProgress,
  canEditProgressQuantities,
  canManageBim,
  bimModel,
  initialFloorId,
  initialKeyframeId,
  initialViewMode,
  initialProgressOpen = false,
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
  structuralElements: StructuralElement[];
  canEdit: boolean;
  canEditProgress: boolean;
  canEditProgressQuantities: boolean;
  canManageBim: boolean;
  bimModel: BimModel | null;
  initialFloorId?: string | null;
  initialKeyframeId?: string | null;
  initialViewMode?: "360" | "split" | "bim" | "track" | "3d";
  initialProgressOpen?: boolean;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const progressOpen = initialProgressOpen;
  const defaultTourStation = detail.keyframes.find((frame) => (
    frame.is_warp_point && frame.pose
  )) ?? detail.keyframes.find((frame) => frame.pose)
    ?? detail.keyframes[0];
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
  const reviewedActivityIds = useMemo(() => new Set(humanProgress.flatMap((item) => {
    if (currentActivityIds.has(item.activity_id)) return [item.activity_id];
    const currentId = item.activity_wbs ? currentActivityIdByWbs.get(item.activity_wbs) : null;
    return currentId ? [currentId] : [];
  })), [currentActivityIdByWbs, currentActivityIds, humanProgress]);
  const reviewedCount = measurableActivities.filter((item) => reviewedActivityIds.has(item.id)).length;
  const activeFloor = floors.find((item) => item.id === initialFloorId) ?? floors.find((item) => item.id === detail.capture.start_floor_id) ?? floors[0] ?? null;
  function selectPlanFloor(floorId: string) {
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
    return [...groups.entries()].map(([wbs, rows], index) => {
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
  const [selectedRoofId, setSelectedRoofId] = useState<string | null>(null);
  const [slabStages, setSlabStages] = useState<Record<string, SlabStageCode[]>>(() =>
    Object.fromEntries((slabProgress?.items ?? []).map((item) => [
      item.structural_element_id,
      item.completed_stages,
    ])),
  );
  const [slabSaveBusy, setSlabSaveBusy] = useState(false);
  const [slabSaveMessage, setSlabSaveMessage] = useState<string | null>(null);
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
  const [editingBeamStage, setEditingBeamStage] = useState<BeamStageCode>("SETTING_OUT");
  const [rangeStartM, setRangeStartM] = useState("0");
  const [rangeEndM, setRangeEndM] = useState("");
  const [beamSaveBusy, setBeamSaveBusy] = useState(false);
  const [beamLengthDraft, setBeamLengthDraft] = useState("");
  const [beamLengthSaveBusy, setBeamLengthSaveBusy] = useState(false);
  const [beamSaveMessage, setBeamSaveMessage] = useState<string | null>(null);
  const [planAspectRatio, setPlanAspectRatio] = useState(1.414);
  const [beamViewRequest, setBeamViewRequest] = useState<BeamViewRequest | null>(null);
  const selectedTrackGroup = trackGroups.find((group) => group.rows.some((row) => row.id === selectedTrackActivityId)) ?? null;
  function selectTrackGroup(group: (typeof trackGroups)[number] | null) {
    if (!group?.rows[0]) return;
    setSelectedTrackActivityId(group.rows[0].id);
    setSelectedBeamSegmentId(null);
    setSelectedColumnId(null);
    setSelectedSlabId(null);
    setSelectedRoofId(null);
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
  const selectedBeamStageCode = selectedStageIndex >= 0
    ? BEAM_STAGES[Math.min(selectedStageIndex, BEAM_STAGES.length - 1)].code
    : "SETTING_OUT";
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
  const selectedFrame = detail.keyframes.find((frame) => frame.id === selectedKeyframeId) ?? null;
  const selectedBeamItem = beamProgress?.items.find((item) => item.beam_segment_id === selectedBeamSegmentId) ?? null;
  const selectedColumnItem = columnProgress?.items.find((item) => item.structural_element_id === selectedColumnId) ?? null;
  const selectedSlabItem = slabProgress?.items.find((item) => item.structural_element_id === selectedSlabId) ?? null;
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
    const denominator = Number(slabProgress.total_area_m2) * SLAB_STAGE_CODES.length;
    return denominator ? completedEquivalentArea / denominator * 100 : 0;
  }, [slabProgress, slabStages]);
  const localBeamProgress = useMemo(() => {
    if (!beamProgress?.items.length) return 0;
    const completedStageLength = beamProgress.items.reduce((sum, item) => (
      sum + BEAM_STAGES.reduce(
        (stageSum, stage) => stageSum + coveredLength(beamStageRanges[item.beam_segment_id]?.[stage.code]),
        0,
      )
    ), 0);
    const denominator = beamProgress.items.reduce(
      (sum, item) => sum + Number(item.length_m ?? 0) * BEAM_STAGES.length,
      0,
    );
    return denominator ? (completedStageLength / denominator) * 100 : 0;
  }, [beamProgress, beamStageRanges]);
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

  const selectBeamFromPlan = useCallback((beamItem: BeamProgress["items"][number], center: [number, number] | null) => {
    if (selectedBeamSegmentId === beamItem.beam_segment_id) {
      setSelectedBeamSegmentId(null);
      setBeamViewRequest(null);
      setBeamSaveMessage(null);
      setRangeStartM("0");
      setRangeEndM("");
      setBeamLengthDraft("");
      return;
    }
    setSelectedBeamSegmentId(beamItem.beam_segment_id);
    setBeamLengthDraft(beamItem.length_m ? Number(beamItem.length_m).toFixed(3) : "");
    setSelectedColumnId(null);
    setSelectedSlabId(null);
    setBeamSaveMessage(null);
    setRangeStartM("0");
    setRangeEndM(beamItem.length_m ? Number(beamItem.length_m).toFixed(3) : "");
    const element = structuralElements.find((candidate) => (
      candidate.element_kind === "BEAM" && candidate.code === beamItem.code
    ));
    const line = element?.geometry_json.line;
    if (!line || !center || !floorFrames.length) return;
    // A saved evidence frame documents an inspection; it is not necessarily
    // the closest station geometrically, but a human-confirmed link is
    // authoritative and must remain repeatable on later inspections.
    const usableFrames = floorFrames.filter((frame) => frame.quality_status === "USABLE");
    const stations = usableFrames.filter((frame) => frame.is_warp_point);
    const evidenceFrame = beamItem.evidence_keyframe_id
      ? floorFrames.find((frame) => frame.id === beamItem.evidence_keyframe_id)
      : null;
    const candidates = evidenceFrame
      ? [evidenceFrame]
      : (stations.length ? stations : (usableFrames.length ? usableFrames : floorFrames));
    const nearest = candidates.reduce((best, frame) => {
      const framePoint: [number, number] = [Number(frame.pose!.x), Number(frame.pose!.y)];
      const target = closestPointOnPlanLine(framePoint, line, planAspectRatio);
      return !best || target.distance < best.distance ? { frame, target, distance: target.distance } : best;
    }, null as {
      frame: (typeof floorFrames)[number];
      target: { x: number; y: number; distance: number };
      distance: number;
    } | null);
    if (!nearest) return;
    const distanceM = nearest.distance * PLAN_METERS_PER_NORMALIZED_Y;
    if (!evidenceFrame && distanceM > MAX_BEAM_VIEW_DISTANCE_M) {
      const needsAlignment = candidates.every((frame) => frame.pose?.needs_review);
      setBeamSaveMessage(
        needsAlignment
          ? `ยังไม่วาร์ปภาพ 360: เส้นทางคลิปนี้ยังไม่ได้จัดแนวกับแปลน และจุดที่ระบบคำนวณว่าใกล้ที่สุดอยู่ห่างคานประมาณ ${distanceM.toFixed(1)} ม.`
          : `ไม่มีจุดถ่าย 360 ใกล้คานนี้ จุดที่ใกล้ที่สุดอยู่ห่างประมาณ ${distanceM.toFixed(1)} ม. จึงไม่เปิดภาพที่อาจทำให้เข้าใจผิด`,
      );
      return;
    }
    const frameX = Number(nearest.frame.pose!.x);
    const frameY = Number(nearest.frame.pose!.y);
    const targetIsCamera = Math.abs(nearest.target.x - frameX) + Math.abs(nearest.target.y - frameY) <= 1e-6;
    const targetX = targetIsCamera ? center[0] : nearest.target.x;
    const targetY = targetIsCamera ? center[1] : nearest.target.y;
    const worldHeading = Math.atan2(
      targetY - frameY,
      (targetX - frameX) * planAspectRatio,
    ) * 180 / Math.PI;
    setSelectedKeyframeId(nearest.frame.id);
    setBeamViewRequest((current) => ({
      keyframeId: nearest.frame.id,
      worldHeading,
      token: (current?.token ?? 0) + 1,
    }));
    setBeamSaveMessage(
      evidenceFrame
        ? "เปิดภาพ 360 หลักฐานที่ผูกกับคานนี้ไว้แล้ว"
        : candidates.every((frame) => frame.pose?.needs_review)
        ? `เปิดจุด 360 ใกล้คานที่สุด (ระยะคำนวณประมาณ ${distanceM.toFixed(1)} ม.) แต่เส้นทางคลิปนี้ยังรอจัดแนวบนแปลน`
        : `เปิดจุด 360 ใกล้คานที่สุด ระยะประมาณ ${distanceM.toFixed(1)} ม. และหันกล้องเข้าหาคานแล้ว`,
    );
  }, [floorFrames, planAspectRatio, selectedBeamSegmentId, structuralElements]);

  async function addSelectedBeamRange() {
    if (!selectedBeamItem) return;
    const beamLength = Number(selectedBeamItem.length_m ?? 0);
    const startM = Number(rangeStartM);
    const endM = Number(rangeEndM);
    if (!Number.isFinite(startM) || !Number.isFinite(endM) || startM < 0 || endM <= startM || endM > beamLength) {
      setBeamSaveMessage(`ช่วงงานต้องอยู่ระหว่าง 0.000–${beamLength.toFixed(3)} ม. และจุดสิ้นสุดต้องมากกว่าจุดเริ่ม`);
      return;
    }
    const beamRanges = beamStageRanges[selectedBeamItem.beam_segment_id] ?? {};
    const nextRanges = {
      ...beamRanges,
      [editingBeamStage]: normalizeRanges([
        ...(beamRanges[editingBeamStage] ?? []),
        { start_m: startM, end_m: endM },
      ]),
    };
    await persistSelectedBeamProgress(
      nextRanges,
      "เพิ่มและบันทึกช่วงงานพร้อมวันตรวจและภาพ 360 แล้ว",
    );
  }

  async function removeSelectedBeamRange(stage: BeamStageCode, index: number) {
    if (!selectedBeamItem) return;
    const beamRanges = beamStageRanges[selectedBeamItem.beam_segment_id] ?? {};
    await persistSelectedBeamProgress({
      ...beamRanges,
      [stage]: (beamRanges[stage] ?? []).filter((_, candidate) => candidate !== index),
    }, "ลบช่วงงานและบันทึกแล้ว");
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
    nextRanges: Record<string, Array<{ start_m: number; end_m: number }>>,
    successMessage: string,
  ) {
    if (!beamProgress || !selectedBeamItem) return;
    setBeamSaveBusy(true);
    setBeamSaveMessage(null);
    const response = await fetch(`/api/projects/${projectId}/captures/${captureId}/beam-progress`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        floor_id: beamProgress.floor_id,
        entries: [{
          beam_segment_id: selectedBeamItem.beam_segment_id,
          stage_ranges: nextRanges,
          evidence_keyframe_id: selectedKeyframeId,
        }],
      }),
    });
    const body = await response.json().catch(() => ({}));
    if (response.ok) {
      const saved = body.items?.find((item: { beam_segment_id: string }) => (
        item.beam_segment_id === selectedBeamItem.beam_segment_id
      ));
      if (saved?.stage_ranges) {
        setBeamStageRanges((current) => ({
          ...current,
          [selectedBeamItem.beam_segment_id]: Object.fromEntries(
            Object.entries(saved.stage_ranges as Record<string, Array<{ start_m: string; end_m: string }>>)
              .map(([stage, ranges]) => [stage, ranges.map((range) => ({
                start_m: Number(range.start_m),
                end_m: Number(range.end_m),
              }))]),
          ),
        }));
      }
    }
    setBeamSaveMessage(response.ok ? successMessage : body.detail || "บันทึกไม่สำเร็จ ข้อมูลเดิมยังคงอยู่");
    setBeamSaveBusy(false);
  }

  async function saveSelectedBeamProgress() {
    if (!selectedBeamItem) return;
    await persistSelectedBeamProgress(
      beamStageRanges[selectedBeamItem.beam_segment_id] ?? {},
      "บันทึกช่วงความยาว งาน วันที่ตรวจ และภาพ 360 แล้ว",
    );
  }

  function selectColumnFromPlan(item: ColumnProgress["items"][number]) {
    if (selectedColumnId === item.structural_element_id) {
      setSelectedColumnId(null);
      setColumnSaveMessage(null);
      return;
    }
    setSelectedColumnId(item.structural_element_id);
    setSelectedBeamSegmentId(null);
    setSelectedSlabId(null);
    setColumnSaveMessage(null);
  }

  async function toggleSelectedColumnStage(stage: ColumnStageCode) {
    if (!selectedColumnItem) return;
    const completed = columnStages[selectedColumnItem.structural_element_id] ?? [];
    const nextStages = completed.includes(stage)
      ? completed.filter((item) => item !== stage)
      : [...completed, stage];
    setColumnStages((current) => ({
      ...current,
      [selectedColumnItem.structural_element_id]: nextStages,
    }));
    const saved = await saveSelectedColumnProgress(nextStages, "อัปเดตและบันทึกงานเสาแล้ว");
    if (!saved) {
      setColumnStages((current) => ({
        ...current,
        [selectedColumnItem.structural_element_id]: completed,
      }));
    }
  }

  async function saveSelectedColumnProgress(
    completedStages = selectedColumnItem
      ? columnStages[selectedColumnItem.structural_element_id] ?? []
      : [],
    successMessage = "บันทึกงานเสาต้นนี้พร้อมวันที่ตรวจและภาพ 360 แล้ว",
  ) {
    if (!columnProgress || !selectedColumnItem) return;
    setColumnSaveBusy(true);
    setColumnSaveMessage(null);
    const response = await fetch(`/api/projects/${projectId}/captures/${captureId}/column-progress`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        floor_id: columnProgress.floor_id,
        entries: [{
          structural_element_id: selectedColumnItem.structural_element_id,
          completed_stages: completedStages,
          evidence_keyframe_id: selectedKeyframeId,
        }],
      }),
    });
    const body = await response.json().catch(() => ({}));
    if (response.ok) {
      const saved = body.items?.find((item: { structural_element_id: string }) => (
        item.structural_element_id === selectedColumnItem.structural_element_id
      ));
      if (saved?.completed_stages) {
        setColumnStages((current) => ({
          ...current,
          [selectedColumnItem.structural_element_id]: saved.completed_stages,
        }));
      }
    }
    setColumnSaveMessage(response.ok ? successMessage : body.detail || "บันทึก Progress เสาไม่สำเร็จ ข้อมูลเดิมยังคงอยู่");
    setColumnSaveBusy(false);
    return response.ok;
  }

  function selectSlabFromPlan(item: SlabProgress["items"][number]) {
    if (selectedSlabId === item.structural_element_id) {
      setSelectedSlabId(null);
      setSlabSaveMessage(null);
      setSlabAreaDraft("");
      return;
    }
    setSelectedSlabId(item.structural_element_id);
    setSlabAreaDraft(item.area_m2 ? Number(item.area_m2).toFixed(3) : "");
    setSelectedBeamSegmentId(null);
    setSelectedColumnId(null);
    setSlabSaveMessage(null);
  }

  async function toggleSelectedSlabStage(stage: SlabStageCode) {
    if (!selectedSlabItem) return;
    const completed = slabStages[selectedSlabItem.structural_element_id] ?? [];
    const nextStages = completed.includes(stage)
      ? completed.filter((item) => item !== stage)
      : [...completed, stage];
    setSlabStages((current) => ({
      ...current,
      [selectedSlabItem.structural_element_id]: nextStages,
    }));
    const saved = await saveSelectedSlabProgress(nextStages, "อัปเดตและบันทึกงานพื้นแล้ว");
    if (!saved) {
      setSlabStages((current) => ({
        ...current,
        [selectedSlabItem.structural_element_id]: completed,
      }));
    }
  }

  async function saveSelectedSlabProgress(
    completedStages = selectedSlabItem
      ? slabStages[selectedSlabItem.structural_element_id] ?? []
      : [],
    successMessage = "บันทึกงานพื้นโซนนี้แล้ว",
  ) {
    if (!slabProgress || !selectedSlabItem) return;
    setSlabSaveBusy(true);
    setSlabSaveMessage(null);
    const response = await fetch(`/api/projects/${projectId}/captures/${captureId}/slab-progress`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        floor_id: slabProgress.floor_id,
        entries: [{
          structural_element_id: selectedSlabItem.structural_element_id,
          completed_stages: completedStages,
          evidence_keyframe_id: selectedKeyframeId,
        }],
      }),
    });
    const body = await response.json().catch(() => ({}));
    if (response.ok) {
      const saved = body.items?.find((item: { structural_element_id: string }) => (
        item.structural_element_id === selectedSlabItem.structural_element_id
      ));
      if (saved?.completed_stages) {
        setSlabStages((current) => ({
          ...current,
          [selectedSlabItem.structural_element_id]: saved.completed_stages,
        }));
      }
    }
    setSlabSaveMessage(response.ok ? successMessage : body.detail || "บันทึก Progress พื้นไม่สำเร็จ ข้อมูลเดิมยังคงอยู่");
    setSlabSaveBusy(false);
    return response.ok;
  }

  return (
    <div className={`capture-review-workspace mode-${viewMode} ${progressOpen ? "is-progress-open" : ""}`}>
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
            <button className={selectedElementKind === "ROOF" ? "is-active" : ""} disabled={!canOpenRoofPlan} onClick={() => {
              const roofActivity = roofGroup?.rows[0] ?? firstRoofActivity;
              if (!roofActivity) return;
              setSelectedTrackActivityId(roofActivity.id);
              setSelectedBeamSegmentId(null);
              setSelectedColumnId(null);
              setSelectedSlabId(null);
              setSelectedRoofId(null);
              if ((activeFloor?.level_index ?? 0) < 5 && firstAvailableRoofFloor) {
                selectPlanFloor(firstAvailableRoofFloor.id);
              }
            }} type="button">หลังคา</button>
            </>}
          </nav><label className="track-capture-toggle"><input checked={showCaptureTrack} onChange={(event) => setShowCaptureTrack(event.target.checked)} type="checkbox" />เส้นทาง Capture</label><Link href={`/projects/${projectId}/dashboard?captureId=${captureId}`}>กลับภาพรวม</Link></header>
          <div className="track-sheet-plan-canvas">
            <div className="track-plan-sheet" style={{ aspectRatio: planAspectRatio }}>
            {activeFloor?.has_plan ? <Image alt={`แปลน ${activeFloor.name}`} fill priority sizes="40vw" src={`/api/projects/${projectId}/floors/${activeFloor.id}/plan`} unoptimized /> : <div className="track-sheet-no-plan">ยังไม่มีแปลนชั้นนี้</div>}
            {showCaptureTrack && <><svg aria-hidden="true" className="capture-track-overlay" preserveAspectRatio="none" viewBox="0 0 1 1"><polyline points={floorFrames.map((frame) => `${Number(frame.pose!.x)},${Number(frame.pose!.y)}`).join(" ")} /></svg>{floorFrames.map((frame) => <button aria-label={`เปิดภาพเวลา ${(frame.timestamp_ms / 1000).toFixed(1)} วินาที`} className={selectedKeyframeId === frame.id ? "is-active" : ""} key={frame.id} onClick={() => setSelectedKeyframeId(frame.id)} style={{ left: `${Number(frame.pose!.x) * 100}%`, top: `${Number(frame.pose!.y) * 100}%` }} type="button" />)}</>}
            {selectedTrackGroup && selectedStructuralElements.length > 0 && <svg aria-label={`ตำแหน่ง ${selectedTrackGroup.rows.find((row) => row.id === selectedTrackActivityId)?.name ?? selectedTrackGroup.name}`} className={`structural-progress-overlay${(selectedBeamSegmentId && selectedElementKind === "BEAM") || (selectedColumnId && selectedElementKind === "COLUMN") || (selectedSlabId && selectedElementKind === "SLAB") || (selectedRoofId && selectedElementKind === "ROOF") ? " has-selection" : ""}`} preserveAspectRatio="none" viewBox="0 0 1 1">{selectedStructuralElements.map((element) => {
              const beamItem = selectedElementKind === "BEAM" ? beamProgress?.items.find((item) => item.code === element.code) : null;
              const columnItem = selectedElementKind === "COLUMN" ? columnProgress?.items.find((item) => item.structural_element_id === element.id) : null;
              const slabItem = selectedElementKind === "SLAB" ? slabProgress?.items.find((item) => item.structural_element_id === element.id) : null;
              const columnStage = COLUMN_STAGES[Math.min(Math.max(selectedStageIndex, 0), COLUMN_STAGES.length - 1)].code;
              const slabStage = SLAB_STAGE_CODES[Math.min(Math.max(selectedStageIndex, 0), SLAB_STAGE_CODES.length - 1)];
              const value = slabItem
                ? (slabStages[slabItem.structural_element_id] ?? []).includes(slabStage) ? 100 : 0
                : columnItem
                ? (columnStages[columnItem.structural_element_id] ?? []).includes(columnStage) ? 100 : 0
                : beamItem
                ? beamStagePercent(beamItem, beamStageRanges[beamItem.beam_segment_id], selectedBeamStageCode)
                : selectedTrackGroup.percent;
              const completed = selectedElementKind === "BEAM" || selectedElementKind === "COLUMN" || selectedElementKind === "SLAB" ? value >= 99.999 : value >= selectedStageThreshold;
              const partial = selectedElementKind === "BEAM" || selectedElementKind === "COLUMN" || selectedElementKind === "SLAB"
                ? value > 0 && value < 99.999
                : value > selectedStagePreviousThreshold && value < selectedStageThreshold;
              const showIncomplete = showNotStarted[selectedTrackGroup.wbs] ?? false;
              const selected = beamItem?.beam_segment_id === selectedBeamSegmentId || columnItem?.structural_element_id === selectedColumnId || slabItem?.structural_element_id === selectedSlabId || (selectedElementKind === "ROOF" && element.id === selectedRoofId);
              if (!completed && !partial && !showIncomplete && !selected) return null;
              const center = structuralElementCenter(element);
              const nearCurrent = Boolean(currentPlanPosition && center && Math.hypot(center[0] - currentPlanPosition.x, center[1] - currentPlanPosition.y) <= 0.09);
              const className = `${completed ? "is-complete" : partial ? "is-partial" : "is-not-started"}${nearCurrent ? " is-current-area" : ""}${selected ? " is-selected-element" : ""}`;
              // Keep every physical item visible in the selected work group.
              // Unreviewed items use the group's own colour with a lighter,
              // dashed treatment; they must not look like completed work.
              const stroke = completed ? selectedTrackGroup.color : partial ? "#e89b2d" : selectedTrackGroup.color;
              const line = element.geometry_json.line;
              const footprint = element.geometry_json.footprint;
              const isKingPostElement = selectedTrackGroup.wbs === roofKingPostGroup?.wbs;
              const isRoofColumnElement = selectedElementKind === "ROOF" && selectedTrackGroup.wbs === "1.2.5.10";
              const kingPostRadiusX = 0.0075;
              const kingPostRadiusY = kingPostRadiusX * planAspectRatio;
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
                    className={`${slabItem ? "slab-plan-zone " : ""}${className}`}
                    fill={slabItem && selected ? "#00a77a" : stroke}
                    points={footprint.map((point) => point.join(",")).join(" ")}
                    stroke={slabItem && selected ? "#007f5f" : stroke}
                  />}
                  {columnItem && center && <circle
                    aria-label={`เลือกเสา ${columnItem.code} Grid ${columnItem.grid_label}`}
                    className="column-hit-target"
                    cx={center[0]}
                    cy={center[1]}
                    onClick={() => selectColumnFromPlan(columnItem)}
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
                    onClick={() => selectSlabFromPlan(slabItem)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") selectSlabFromPlan(slabItem);
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
                    onClick={() => setSelectedRoofId((current) => current === element.id ? null : element.id)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") setSelectedRoofId((current) => current === element.id ? null : element.id);
                    }}
                    rx={kingPostRadiusX * 1.7}
                    ry={kingPostRadiusY * 1.7}
                    role="button"
                    tabIndex={0}
                  /> : selectedElementKind === "ROOF" && <polygon
                    aria-label={`เลือก ${element.code}`}
                    className="roof-hit-target"
                    onClick={() => setSelectedRoofId((current) => current === element.id ? null : element.id)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") setSelectedRoofId((current) => current === element.id ? null : element.id);
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
                    onClick={() => selectBeamFromPlan(beamItem, center)}
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
                onClick={beamItem ? () => selectBeamFromPlan(beamItem, center) : selectedElementKind === "ROOF" ? () => setSelectedRoofId((current) => current === element.id ? null : element.id) : undefined}
                onKeyDown={beamItem ? (event) => {
                  if (event.key === "Enter" || event.key === " ") selectBeamFromPlan(beamItem, center);
                } : selectedElementKind === "ROOF" ? (event) => {
                  if (event.key === "Enter" || event.key === " ") setSelectedRoofId((current) => current === element.id ? null : element.id);
                } : undefined}
                role={beamItem || selectedElementKind === "ROOF" ? "button" : undefined}
                stroke={stroke}
                tabIndex={beamItem || selectedElementKind === "ROOF" ? 0 : undefined}
                x1={line[0][0]}
                x2={line[1][0]}
                y1={line[0][1]}
                y2={line[1][1]}
              /> : null;
            })}</svg>}
            {currentPlanPosition && <>
              <span aria-hidden="true" className="current-view-cone track-current-view-cone" style={{ left: `${currentPlanPosition.x * 100}%`, top: `${currentPlanPosition.y * 100}%`, transform: `translate(-50%, -88%) rotate(${currentPlanPosition.heading + 90}deg)` }} />
              <span aria-label="ตำแหน่งภาพ 360 ปัจจุบัน" className="current-path-position track-current-position" style={{ left: `${currentPlanPosition.x * 100}%`, top: `${currentPlanPosition.y * 100}%` }} />
            </>}
            </div>
          </div>
        </section>
        <section className="track-sheet-360-pane"><span className="track-image-date">ภาพวันที่ {new Date(detail.capture.captured_at).toLocaleDateString("th-TH")}</span><PanoramaViewer canEdit={canEdit} detail={detail} floors={floors} onSelectedKeyframeChange={setSelectedKeyframeId} onViewStateChange={handlePanoramaViewChange} projectId={projectId} requestedKeyframeId={selectedKeyframeId} requestedViewToken={beamViewRequest?.token} requestedWorldHeading={beamViewRequest?.keyframeId === selectedKeyframeId ? beamViewRequest.worldHeading : null} /></section>
        <aside className="track-sheet-breakdown"><header><strong>Progress งานโครงสร้าง</strong><span>ณ {new Date(detail.capture.captured_at).toLocaleDateString("th-TH")}</span></header><div className="track-sheet-actions"><button onClick={() => setVisibleTrackGroups(Object.fromEntries(trackGroups.map((group) => [group.wbs, true])))} type="button">เลือกทั้งหมด</button><button onClick={() => setVisibleTrackGroups(Object.fromEntries(trackGroups.map((group) => [group.wbs, false])))} type="button">ล้างทั้งหมด</button></div>{selectedElementKind === "BEAM" && beamProgress?.items.length ? <label className="beam-segment-picker"><span>คานที่กำลังตรวจ</span><select aria-label="เลือกช่วงคาน" onChange={(event) => {
          const item = beamProgress.items.find((candidate) => candidate.beam_segment_id === event.target.value);
          if (!item) return;
          const element = structuralElements.find((candidate) => candidate.element_kind === "BEAM" && candidate.code === item.code);
          selectBeamFromPlan(item, element ? structuralElementCenter(element) : null);
        }} value={selectedBeamSegmentId ?? ""}><option value="">คลิกคานในแบบ หรือเลือกจากรายการ</option>{beamProgress.items.map((item) => <option key={item.beam_segment_id} value={item.beam_segment_id}>{beamDisplayName(item)} · {beamOverallPercent(item, beamStageRanges[item.beam_segment_id]).toFixed(1)}%</option>)}</select></label> : null}{selectedBeamItem && <section className="beam-stage-editor">
          <header><div><strong>{beamDisplayName(selectedBeamItem)}</strong><span>ความยาวคาน {Number(selectedBeamItem.length_m ?? 0).toFixed(3)} ม.</span></div><b>{beamOverallPercent(selectedBeamItem, beamStageRanges[selectedBeamItem.beam_segment_id]).toFixed(1)}%</b></header>
          <p>เลือกงาน แล้วระบุระยะตามแนวคานจากจุดเริ่มถึงจุดสิ้นสุด ภาพ 360 ปัจจุบันจะถูกเก็บเป็นหลักฐานของวันตรวจ</p>
          {canEditProgressQuantities && <div className="beam-length-form">
            <label><span>แก้ความยาวคานจริง (เมตร)</span><input inputMode="decimal" min="0.001" onChange={(event) => setBeamLengthDraft(event.target.value)} step="0.001" type="number" value={beamLengthDraft} /></label>
            <button disabled={beamLengthSaveBusy} onClick={saveSelectedBeamLength} type="button">{beamLengthSaveBusy ? "กำลังบันทึก…" : "บันทึกความยาวคาน"}</button>
            <small>ค่านี้เป็นข้อมูลหลักของคานและจะเปลี่ยนทุกวันที่ตรวจ</small>
          </div>}
          <div className="beam-range-form">
            <label><span>งานที่ตรวจ</span><select disabled={!canEditProgress} onChange={(event) => setEditingBeamStage(event.target.value as BeamStageCode)} value={editingBeamStage}>{BEAM_STAGES.map((stage) => <option key={stage.code} value={stage.code}>{stage.label}</option>)}</select></label>
            <label><span>จากเมตรที่</span><input disabled={!canEditProgress} inputMode="decimal" min="0" onChange={(event) => setRangeStartM(event.target.value)} step="0.001" type="number" value={rangeStartM} /></label>
            <label><span>ถึงเมตรที่</span><input disabled={!canEditProgress} inputMode="decimal" max={Number(selectedBeamItem.length_m ?? 0)} min="0" onChange={(event) => setRangeEndM(event.target.value)} step="0.001" type="number" value={rangeEndM} /></label>
            {canEditProgress && <button disabled={beamSaveBusy} onClick={addSelectedBeamRange} type="button">{beamSaveBusy ? "กำลังบันทึก…" : "เพิ่มและบันทึกช่วงงาน"}</button>}
          </div>
          <div className="beam-range-list">{BEAM_STAGES.map((stage) => {
            const ranges = beamStageRanges[selectedBeamItem.beam_segment_id]?.[stage.code] ?? [];
            const done = coveredLength(ranges);
            return <section key={stage.code}><header><strong>{stage.label}</strong><span>{done.toFixed(3)} / {Number(selectedBeamItem.length_m ?? 0).toFixed(3)} ม. · {beamStagePercent(selectedBeamItem, beamStageRanges[selectedBeamItem.beam_segment_id], stage.code).toFixed(1)}%</span></header>{ranges.length ? <ul>{ranges.map((range, index) => <li key={`${range.start_m}-${range.end_m}-${index}`}><span>{range.start_m.toFixed(3)}–{range.end_m.toFixed(3)} ม.</span>{canEditProgress && <button aria-label={`ลบช่วง ${range.start_m.toFixed(3)} ถึง ${range.end_m.toFixed(3)} เมตร`} disabled={beamSaveBusy} onClick={() => removeSelectedBeamRange(stage.code, index)} type="button">ลบ</button>}</li>)}</ul> : <small>ยังไม่มีช่วงงาน</small>}</section>;
          })}</div>
          <small>งานคานทั้งชั้นยาว {formatQuantity2(beamProgress?.total_length_m)} ม. · Progress รวมคิดจาก 5 งาน = {localBeamProgress.toFixed(2)}%</small>
          {canEditProgress && <button disabled={beamSaveBusy} onClick={saveSelectedBeamProgress} type="button">{beamSaveBusy ? "กำลังบันทึก…" : "บันทึกช่วงงาน + วันที่ตรวจ + ภาพ 360"}</button>}
          {beamSaveMessage && <p role="status">{beamSaveMessage}</p>}
        </section>}{selectedElementKind === "COLUMN" && columnProgress?.items.length ? <>
          <label className="beam-segment-picker"><span>เสาที่กำลังตรวจ</span><select aria-label="เลือกเสา" onChange={(event) => {
            const item = columnProgress.items.find((candidate) => candidate.structural_element_id === event.target.value);
            if (item) selectColumnFromPlan(item);
          }} value={selectedColumnId ?? ""}><option value="">คลิกเสาในแบบ หรือเลือกจากรายการ</option>{columnProgress.items.map((item) => <option key={item.structural_element_id} value={item.structural_element_id}>{item.code} · Grid {item.grid_label} · {(columnStages[item.structural_element_id]?.length ?? 0) * 25}%</option>)}</select></label>
          {selectedColumnItem && <section className="beam-stage-editor column-stage-editor">
            <header><div><strong>{selectedColumnItem.code} · Grid {selectedColumnItem.grid_label}</strong><span>Progress แยกรายต้น ไม่รวมกับงานคาน</span></div><b>{(columnStages[selectedColumnItem.structural_element_id]?.length ?? 0) * 25}%</b></header>
            <p>แต่ละขั้นงานคิด 25% ของเสาต้นนี้ เลือกเฉพาะงานที่ทำเสร็จแล้ว</p>
            <div>{COLUMN_STAGES.map((stage) => <label key={stage.code}><input checked={(columnStages[selectedColumnItem.structural_element_id] ?? []).includes(stage.code)} disabled={!canEditProgress || columnSaveBusy} onChange={() => toggleSelectedColumnStage(stage.code)} type="checkbox" /><span>{stage.label}</span><small>25%</small></label>)}</div>
            <small>เสาทั้งชั้น {columnProgress.column_count} ต้น · Progress งานเสารวม {localColumnProgress.toFixed(2)}%</small>
            {canEditProgress && <button disabled={columnSaveBusy} onClick={() => void saveSelectedColumnProgress()} type="button">{columnSaveBusy ? "กำลังบันทึก…" : "บันทึกงานเสาอีกครั้ง"}</button>}
            {columnSaveMessage && <p role="status">{columnSaveMessage}</p>}
          </section>}
        </> : null}{selectedElementKind === "SLAB" && slabProgress?.items.length ? <>
          <label className="beam-segment-picker"><span>พื้นที่กำลังตรวจ</span><select aria-label="เลือกพื้นที่พื้น" onChange={(event) => {
            const item = slabProgress.items.find((candidate) => candidate.structural_element_id === event.target.value);
            if (item) selectSlabFromPlan(item);
          }} value={selectedSlabId ?? ""}><option value="">คลิกพื้นที่สีแดงในแบบ หรือเลือกจากรายการ</option>{slabProgress.items.map((item) => <option key={item.structural_element_id} value={item.structural_element_id}>{item.code} · {Number(item.area_m2).toFixed(2)} ตร.ม. · {(slabStages[item.structural_element_id]?.length ?? 0) * 20}%</option>)}</select></label>
          {selectedSlabItem && <section className="beam-stage-editor slab-stage-editor">
            <header><div><strong>{selectedSlabItem.code}</strong><span>พื้นที่ประมาณ {Number(selectedSlabItem.area_m2).toFixed(2)} ตร.ม.</span></div><b>{(slabStages[selectedSlabItem.structural_element_id]?.length ?? 0) * 20}%</b></header>
            <p>แต่ละขั้นคิด 20% ของพื้นที่โซนนี้ ชื่อขั้นงานใช้ตาม WBS ของชั้นที่กำลังตรวจ</p>
            {canEditProgressQuantities && <div className="beam-length-form">
              <label><span>แก้พื้นที่ตรวจจริง (ตร.ม.)</span><input inputMode="decimal" min="0.001" onChange={(event) => setSlabAreaDraft(event.target.value)} step="0.001" type="number" value={slabAreaDraft} /></label>
              <button disabled={slabAreaSaveBusy} onClick={saveSelectedSlabArea} type="button">{slabAreaSaveBusy ? "กำลังบันทึก…" : "บันทึกพื้นที่ตรวจ"}</button>
              <small>แก้เฉพาะพื้นที่คำนวณ Progress โดยไม่เปลี่ยนรหัสหรือรูปทรงในแปลน</small>
            </div>}
            <div>{SLAB_STAGE_CODES.map((stage, index) => <label key={stage}><input checked={(slabStages[selectedSlabItem.structural_element_id] ?? []).includes(stage)} disabled={!canEditProgress || slabSaveBusy} onChange={() => toggleSelectedSlabStage(stage)} type="checkbox" /><span>{selectedTrackGroup?.rows[index]?.name ?? `ขั้นงานพื้น ${index + 1}`}</span><small>20%</small></label>)}</div>
            <small>พื้นทั้งชั้น {slabProgress.zone_count} โซน · {formatQuantity2(slabProgress.total_area_m2)} ตร.ม. · Progress รวม {localSlabProgress.toFixed(2)}%</small>
            {canEditProgress && <button disabled={slabSaveBusy} onClick={() => void saveSelectedSlabProgress()} type="button">{slabSaveBusy ? "กำลังบันทึก…" : "บันทึกงานพื้นอีกครั้ง"}</button>}
            {slabSaveMessage && <p role="status">{slabSaveMessage}</p>}
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
          const spatialPercent = beamSpatialGroup
            ? localBeamProgress
            : columnSpatialGroup
            ? localColumnProgress
            : slabSpatialGroup
            ? localSlabProgress
            : group.percent;
          return <article className={!visible ? "is-muted" : ""} key={group.wbs}><label><input checked={visible} onChange={(event) => setVisibleTrackGroups((current) => ({ ...current, [group.wbs]: event.target.checked }))} type="checkbox" /><i style={{ background: group.color }} /><strong>{group.name}</strong></label><div className="track-sheet-progress"><span><i style={{ background: group.color, width: `${spatialPercent}%` }} /></span><b>{spatialPercent.toFixed(0)}%</b></div><small>{beamSpatialGroup ? `${beamProgress!.labeled_count} / ${beamProgress!.segment_count} ชิ้นตรวจแล้ว` : columnSpatialGroup ? `${columnProgress!.labeled_count} / ${columnProgress!.column_count} ต้นตรวจแล้ว` : slabSpatialGroup ? `${slabProgress!.labeled_count} / ${slabProgress!.zone_count} โซนตรวจแล้ว` : groupElements.length ? `${groupElements.length} ชิ้นจาก IFC/แปลน · ${group.reviewed}/${group.rows.length} ขั้นตรวจแล้ว` : `${group.reviewed} / ${group.rows.length} รายการตรวจแล้ว`}</small><div className="track-stage-list">{group.rows.map((row, index) => {
            const stageCode = BEAM_STAGES[Math.min(index, BEAM_STAGES.length - 1)].code;
            const columnStageCode = COLUMN_STAGES[Math.min(index, COLUMN_STAGES.length - 1)].code;
            const completedLength = beamSpatialGroup ? beamProgress!.items.reduce((sum, item) => (
              sum + coveredLength(beamStageRanges[item.beam_segment_id]?.[stageCode])
            ), 0) : 0;
            const completedColumns = columnSpatialGroup ? columnProgress!.items.filter((item) => (columnStages[item.structural_element_id] ?? []).includes(columnStageCode)).length : 0;
            const slabStageCode = SLAB_STAGE_CODES[Math.min(index, SLAB_STAGE_CODES.length - 1)];
            const completedSlabArea = slabSpatialGroup ? slabProgress!.items.reduce((sum, item) => sum + ((slabStages[item.structural_element_id] ?? []).includes(slabStageCode) ? Number(item.area_m2) : 0), 0) : 0;
          return <button className={selectedTrackActivityId === row.id ? "is-active" : ""} key={row.id} onClick={() => setSelectedTrackActivityId(row.id)} type="button"><span>{row.name}</span>{beamSpatialGroup && <b>{completedLength.toFixed(2)}/{formatQuantity2(beamProgress!.total_length_m)} ม.</b>}{columnSpatialGroup && <b>{completedColumns}/{columnProgress!.column_count} ต้น</b>}{slabSpatialGroup && <b>{completedSlabArea.toFixed(2)}/{formatQuantity2(slabProgress!.total_area_m2)} ตร.ม.</b>}</button>;
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
            requestedViewToken={beamViewRequest?.token}
            requestedWorldHeading={beamViewRequest?.keyframeId === selectedKeyframeId ? beamViewRequest.worldHeading : null}
          />
        </div>
        {viewMode !== "360" && (
          <div className="capture-pane bim-pane">
            {bimModel ? (
              <>
                <BimViewer
                  activeKeyframeId={selectedKeyframeId}
                  floors={floors}
                  keyframes={detail.keyframes}
                  model={bimModel}
                  onSelectKeyframe={setSelectedKeyframeId}
                  panoramaView={panoramaView}
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

      <Link
        className="review-progress-trigger"
        href={`/projects/${projectId}/captures/${captureId}?panel=progress`}
      >
        <span aria-hidden="true">✓</span>
        <span><strong>ตรวจ Progress โครงสร้าง</strong><small>มีผลตรวจ {reviewedCount}/{measurableActivities.length} กิจกรรม</small></span>
      </Link>

      <aside className={`review-progress-drawer ${progressOpen ? "is-open" : ""}`}>
        <header>
          <div>
            <span className="drawer-eyebrow">รายการตรวจหน้างาน</span>
            <h2>ตรวจ Progress งานโครงสร้าง</h2>
            <p>ตรวจทีละกิจกรรม WBS จากภาพ 360 แล้วบันทึกพร้อมหลักฐาน ส่วนภาพรวมให้ระบบรวมผลภายหลัง</p>
          </div>
          <Link aria-label="ปิด" className="review-drawer-close" href={`/projects/${projectId}/captures/${captureId}`}>×</Link>
        </header>
        <div className="review-drawer-summary">
          <div><span>ขอบเขต</span><strong>โครงสร้าง</strong></div>
          <div><span>กิจกรรมที่มีผลตรวจ</span><strong>{reviewedCount}/{measurableActivities.length}</strong></div>
          <div><span>ภาพปัจจุบัน</span><strong>{selectedKeyframeId ? "พร้อมใช้" : "ยังไม่เลือก"}</strong></div>
        </div>
        <div className="review-progress-content">
          <StructuralProgressInspector activities={activities} canEdit={canEditProgress} captureId={captureId} detail={detail} progress={humanProgress} projectId={projectId} selectedKeyframeId={selectedKeyframeId} />
        </div>
        <footer><Link href={`/projects/${projectId}/schedule`}>เปิดแผนงานและดูประวัติ Progress</Link></footer>
      </aside>
    </div>
  );
}
