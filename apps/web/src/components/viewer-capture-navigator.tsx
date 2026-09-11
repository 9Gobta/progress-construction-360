"use client";

import { useMemo, useState } from "react";

import type { Capture, Floor } from "@/lib/types";

function bangkokDateKey(value: string) {
  return new Intl.DateTimeFormat("en-CA", {
    day: "2-digit",
    month: "2-digit",
    timeZone: "Asia/Bangkok",
    year: "numeric",
  }).format(new Date(value));
}

function dateLabel(value: string) {
  return new Intl.DateTimeFormat("th-TH", {
    day: "numeric",
    month: "long",
    timeZone: "Asia/Bangkok",
    year: "numeric",
  }).format(new Date(value));
}

export function ViewerCaptureNavigator({
  activePlanFloorId,
  captures,
  currentCaptureId,
  floors,
  trackMode,
  projectId,
}: {
  activePlanFloorId: string | null;
  captures: Capture[];
  currentCaptureId: string;
  floors: Floor[];
  trackMode: boolean;
  projectId: string;
}) {
  const [pending, setPending] = useState(false);
  const floorById = useMemo(() => new Map(floors.map((floor) => [floor.id, floor])), [floors]);
  const orderedCaptures = useMemo(() => [...captures].sort((first, second) => (
    second.captured_at.localeCompare(first.captured_at)
  )), [captures]);
  const current = orderedCaptures.find((capture) => capture.id === currentCaptureId) ?? orderedCaptures[0];
  const currentDateKey = current ? bangkokDateKey(current.captured_at) : "";
  const dateGroups = useMemo(() => {
    const groups = new Map<string, Capture[]>();
    for (const capture of orderedCaptures) {
      const key = bangkokDateKey(capture.captured_at);
      groups.set(key, [...(groups.get(key) ?? []), capture]);
    }
    return Array.from(groups.entries()).map(([key, rows]) => ({
      key,
      rows: [...rows].sort((first, second) => (
        (floorById.get(first.start_floor_id)?.level_index ?? 999)
        - (floorById.get(second.start_floor_id)?.level_index ?? 999)
        || first.captured_at.localeCompare(second.captured_at)
      )),
    }));
  }, [floorById, orderedCaptures]);
  const currentDateIndex = dateGroups.findIndex((group) => group.key === currentDateKey);
  const newerDate = currentDateIndex > 0 ? dateGroups[currentDateIndex - 1] : null;
  const olderDate = currentDateIndex >= 0 && currentDateIndex < dateGroups.length - 1
    ? dateGroups[currentDateIndex + 1]
    : null;
  const captureForDate = (group: typeof dateGroups[number] | null) => (
    group?.rows.find((capture) => capture.start_floor_id === current?.start_floor_id)
      ?? group?.rows[0]
      ?? null
  );
  const newerCapture = captureForDate(newerDate);
  const olderCapture = captureForDate(olderDate);
  const capturesOnDate = dateGroups.find((group) => group.key === currentDateKey)?.rows ?? [];
  const roofFloors = useMemo(() => floors.filter((floor) => (
    floor.level_index >= 5
    && floor.has_plan
    && (!floor.available_from || floor.available_from <= currentDateKey)
  )).sort((first, second) => first.level_index - second.level_index), [currentDateKey, floors]);
  const selectedRoofFloor = roofFloors.find((floor) => floor.id === activePlanFloorId) ?? null;

  function captureHref(captureId: string) {
    return `/projects/${projectId}/captures/${captureId}${trackMode ? "?mode=track" : ""}`;
  }

  function openCapture(captureId: string) {
    if (!captureId || captureId === currentCaptureId) return;
    setPending(true);
    // A full document navigation is intentional here. Some remote reviewers
    // access the development server through a Cloudflare tunnel where an RSC
    // transition can be interrupted and leave the controlled select showing
    // the old capture. Loading the canonical URL guarantees that the header,
    // panorama, route, plan and progress data all belong to the same capture.
    window.location.assign(captureHref(captureId));
  }

  function selectDate(dateKey: string) {
    const rows = dateGroups.find((group) => group.key === dateKey)?.rows ?? [];
    const target = rows.find((capture) => capture.start_floor_id === current?.start_floor_id)
      ?? rows[0];
    if (target) openCapture(target.id);
  }

  function openRoofPlan(floorId: string) {
    if (!floorId || (selectedRoofFloor?.id === floorId && current?.id === currentCaptureId)) return;
    const next = new URLSearchParams();
    next.set("floorId", floorId);
    next.set("mode", "track");
    setPending(true);
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- full reload prevents interrupted tunnel RSC transitions
    window.location.assign(`/projects/${projectId}/captures/${currentCaptureId}?${next.toString()}`);
  }

  function selectFloorOrCapture(value: string) {
    if (value.startsWith("roof:")) {
      openRoofPlan(value.slice("roof:".length));
      return;
    }
    openCapture(value);
  }

  return (
    <nav aria-busy={pending} aria-label="เปลี่ยนวันที่และชั้นใน Viewer" className="viewer-capture-navigator">
      <div className="viewer-capture-date">
        <span>วันที่ Capture</span>
        <span className="capture-date-stepper">
          {olderCapture && !pending ? <a aria-label="เปิด Capture วันก่อนหน้า" href={captureHref(olderCapture.id)} title={dateLabel(olderCapture.captured_at)}>←</a> : <button aria-label="เปิด Capture วันก่อนหน้า" disabled title="ไม่มีวันก่อนหน้า" type="button">←</button>}
          <select aria-label="เลือกวันที่ Capture" disabled={pending} onChange={(event) => selectDate(event.target.value)} value={currentDateKey}>
            {dateGroups.map((group) => <option key={group.key} value={group.key}>{dateLabel(group.rows[0].captured_at)} · {group.rows.length} ไฟล์</option>)}
          </select>
          {newerCapture && !pending ? <a aria-label="เปิด Capture วันถัดไป" href={captureHref(newerCapture.id)} title={dateLabel(newerCapture.captured_at)}>→</a> : <button aria-label="เปิด Capture วันถัดไป" disabled title="ไม่มีวันถัดไป" type="button">→</button>}
        </span>
      </div>
      <label>
        <span>ชั้น / คลิป</span>
        <select disabled={pending} onChange={(event) => selectFloorOrCapture(event.target.value)} value={selectedRoofFloor ? `roof:${selectedRoofFloor.id}` : currentCaptureId}>
          {capturesOnDate.map((capture) => {
            const floorName = floorById.get(capture.start_floor_id)?.name ?? "ไม่ระบุชั้น";
            const sameFloor = capturesOnDate.filter((item) => item.start_floor_id === capture.start_floor_id);
            const clipNumber = sameFloor.findIndex((item) => item.id === capture.id) + 1;
            return <option key={capture.id} value={capture.id}>{floorName}{sameFloor.length > 1 ? ` · คลิป ${clipNumber}` : ""} · {capture.status}</option>;
          })}
          {roofFloors.map((floor) => (
            <option key={`roof:${floor.id}`} value={`roof:${floor.id}`}>{floor.name} · แปลนโครงสร้าง</option>
          ))}
        </select>
      </label>
      {pending && <span className="viewer-capture-changing">กำลังเปลี่ยนข้อมูล…</span>}
    </nav>
  );
}
