"use client";

import { FormEvent, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import type { Activity, CaptureDetail, HumanProgressEntry } from "@/lib/types";

type Props = { activities: Activity[]; canEdit: boolean; captureId: string; detail: CaptureDetail; progress: HumanProgressEntry[]; projectId: string; selectedKeyframeId: string | null };
type WorklistMode = "due" | "all" | "reviewed";

function captureTimeWithTimezone(value: string) {
  const trimmed = value.trim();
  if (/[zZ]$|[+-]\d{2}:?\d{2}$/.test(trimmed)) return trimmed;
  // Capture dates in this project are entered in local Thailand time.
  return `${trimmed}+07:00`;
}

function displayDate(value: string) {
  return new Date(value).toLocaleDateString("th-TH", { day: "2-digit", month: "2-digit", year: "2-digit" });
}

function dateValue(value: string) {
  const result = new Date(value).getTime();
  return Number.isFinite(result) ? result : 0;
}

const progressPresets = [
  { value: "0", label: "ยังไม่เริ่ม" }, { value: "25", label: "เริ่มแล้ว" },
  { value: "50", label: "ครึ่งหนึ่ง" }, { value: "75", label: "เกือบเสร็จ" },
  { value: "100", label: "เสร็จ" },
];

export function StructuralProgressInspector({ activities, canEdit, captureId, detail, progress, projectId, selectedKeyframeId }: Props) {
  const router = useRouter();
  const measurableActivities = useMemo(() => activities.filter((item) => !item.is_summary && (item.wbs === "1.2" || item.wbs.startsWith("1.2."))), [activities]);
  const activityById = useMemo(() => new Map(activities.map((item) => [item.id, item])), [activities]);
  const latestByActivity = useMemo(() => {
    const result = new Map<string, HumanProgressEntry>();
    const currentIds = new Set(activities.map((item) => item.id));
    const currentIdByWbs = new Map(activities.map((item) => [item.wbs, item.id]));
    for (const row of progress) {
      const currentId = currentIds.has(row.activity_id)
        ? row.activity_id
        : row.activity_wbs ? currentIdByWbs.get(row.activity_wbs) : undefined;
      if (currentId && !result.has(currentId)) result.set(currentId, row);
    }
    return result;
  }, [activities, progress]);
  const captureDate = dateValue(detail.capture.captured_at);
  const reviewedCount = measurableActivities.filter((item) => latestByActivity.has(item.id)).length;
  const dueActivities = useMemo(() => measurableActivities.filter((item) => {
    const latest = latestByActivity.get(item.id);
    const started = dateValue(item.planned_start) <= captureDate;
    const activeOnCapture = dateValue(item.planned_finish) >= captureDate;
    return started && (activeOnCapture || Number(latest?.progress_percent ?? 0) < 100);
  }), [captureDate, latestByActivity, measurableActivities]);

  const [mode, setMode] = useState<WorklistMode>("due");
  const [activityId, setActivityId] = useState(dueActivities[0]?.id ?? measurableActivities[0]?.id ?? "");
  const [selectedActivityIds, setSelectedActivityIds] = useState<string[]>(() => activityId ? [activityId] : []);
  const [search, setSearch] = useState("");
  const [percent, setPercent] = useState(latestByActivity.get(activityId)?.progress_percent ?? "0");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const selectedActivity = measurableActivities.find((item) => item.id === activityId) ?? null;
  const previous = activityId ? latestByActivity.get(activityId) : undefined;
  const selectedFrame = detail.keyframes.find((item) => item.id === selectedKeyframeId) ?? null;

  const parentPath = useMemo(() => {
    if (!selectedActivity) return [];
    const result: Activity[] = [];
    let parentId = selectedActivity.parent_activity_id;
    while (parentId && result.length < 8) {
      const parent = activityById.get(parentId);
      if (!parent) break;
      result.unshift(parent);
      parentId = parent.parent_activity_id;
    }
    return result.filter((item) => item.wbs !== "1" && item.wbs !== "1.2");
  }, [activityById, selectedActivity]);

  const visibleActivities = useMemo(() => {
    const source = mode === "due" ? dueActivities : mode === "reviewed" ? measurableActivities.filter((item) => latestByActivity.has(item.id)) : measurableActivities;
    const query = search.trim().toLocaleLowerCase("th-TH");
    return query ? source.filter((item) => `${item.wbs} ${item.name}`.toLocaleLowerCase("th-TH").includes(query)) : source;
  }, [dueActivities, latestByActivity, measurableActivities, mode, search]);

  function changeActivity(nextId: string) {
    setActivityId(nextId);
    setPercent(latestByActivity.get(nextId)?.progress_percent ?? "0");
    setNote("");
    setMessage(null);
  }

  function toggleActivitySelection(nextId: string) {
    changeActivity(nextId);
    setSelectedActivityIds((current) => current.includes(nextId)
      ? current.filter((id) => id !== nextId)
      : [...current, nextId]);
  }

  function changeMode(nextMode: WorklistMode) {
    setMode(nextMode);
    setSearch("");
    const source = nextMode === "due" ? dueActivities : nextMode === "reviewed" ? measurableActivities.filter((item) => latestByActivity.has(item.id)) : measurableActivities;
    if (source.length && !source.some((item) => item.id === activityId)) changeActivity(source[0].id);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!selectedActivity) return;
    const targetIds = selectedActivityIds.length ? selectedActivityIds : [selectedActivity.id];
    setBusy(true);
    setMessage(null);
    const evidence = selectedFrame ? `หลักฐานภาพ 360 เวลา ${(selectedFrame.timestamp_ms / 1000).toFixed(1)} วินาที [keyframe:${selectedFrame.id}]` : "หลักฐานจาก Capture นี้ (ไม่ได้ระบุภาพย่อย)";
    try {
      const response = await fetch(`/api/projects/${projectId}/progress/manual/bulk`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entries: targetIds.map((targetId) => ({ activity_id: targetId, capture_id: captureId, observed_at: captureTimeWithTimezone(detail.capture.captured_at), progress_percent: Number(percent), note: [note.trim(), evidence].filter(Boolean).join(" | ") })) }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = Array.isArray(body.detail)
          ? body.detail.map((item: { msg?: string }) => item.msg).filter(Boolean).join("; ")
          : body.detail;
        throw new Error(detail || "บันทึกความก้าวหน้าไม่สำเร็จ");
      }
      setMessage(`บันทึกผลตรวจ ${targetIds.length} งาน พร้อมภาพ 360 แล้ว`);
      router.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "บันทึกความก้าวหน้าไม่สำเร็จ");
    } finally { setBusy(false); }
  }

  if (!measurableActivities.length) return <div className="structural-progress-empty"><strong>ยังไม่พบกิจกรรมโครงสร้าง</strong><p>กรุณานำเข้าแผนงานก่อนเริ่มตรวจ</p></div>;

  return <form className="structural-progress-inspector" onSubmit={save}>
    <nav aria-label="ตัวกรองรายการตรวจ" className="structural-worklist-tabs">
      <button className={mode === "due" ? "is-active" : ""} onClick={() => changeMode("due")} type="button">ควรตรวจวันนี้ <b>{dueActivities.length}</b></button>
      <button className={mode === "all" ? "is-active" : ""} onClick={() => changeMode("all")} type="button">ทั้งหมด <b>{measurableActivities.length}</b></button>
      <button className={mode === "reviewed" ? "is-active" : ""} onClick={() => changeMode("reviewed")} type="button">มีผลตรวจ <b>{reviewedCount}</b></button>
    </nav>
    <input aria-label="ค้นหางาน" className="structural-progress-search" onChange={(event) => setSearch(event.target.value)} placeholder="ค้นหา WBS หรืองาน เช่น คานชั้น 2" type="search" value={search} />
    <div className="structural-bulk-actions">
      <span>เลือกแล้ว <b>{selectedActivityIds.length}</b> งาน</span>
      <button disabled={!visibleActivities.length} onClick={() => setSelectedActivityIds(visibleActivities.map((item) => item.id))} type="button">เลือกงานที่แสดงทั้งหมด</button>
      <button disabled={!selectedActivityIds.length} onClick={() => setSelectedActivityIds([])} type="button">ยกเลิกการเลือก</button>
    </div>
    <div className="structural-worklist" role="list">
      {visibleActivities.length ? visibleActivities.map((item) => {
        const latest = latestByActivity.get(item.id);
        const selected = selectedActivityIds.includes(item.id);
        return <button aria-pressed={selected} className={`${item.id === activityId ? "is-selected" : ""}${selected ? " is-bulk-selected" : ""}`} key={item.id} onClick={() => toggleActivitySelection(item.id)} type="button"><span><b>{selected ? "✓ " : ""}{item.wbs}</b>{latest ? `${Number(latest.progress_percent).toFixed(0)}%` : "ยังไม่ตรวจ"}</span><strong>{item.name}</strong><small>{displayDate(item.planned_start)} – {displayDate(item.planned_finish)}</small></button>;
      }) : <p className="structural-worklist-empty">ไม่พบงานในตัวกรองนี้</p>}
    </div>
    {selectedActivity && <section className="structural-selected-task">
      {parentPath.length > 0 && <p>{parentPath.map((item) => item.name).join(" › ")}</p>}
      <span>{selectedActivity.wbs}</span><h3>{selectedActivity.name}</h3>
      <div><small>แผน {displayDate(selectedActivity.planned_start)} – {displayDate(selectedActivity.planned_finish)}</small><b>{previous ? `ล่าสุด ${Number(previous.progress_percent).toFixed(0)}%` : "ยังไม่เคยตรวจ"}</b></div>
    </section>}
    {selectedActivityIds.length > 1 && <p className="structural-bulk-hint">สถานะ เปอร์เซ็นต์ หมายเหตุ และภาพหลักฐานด้านล่างจะบันทึกให้ทั้ง {selectedActivityIds.length} งานพร้อมกัน</p>}
    <div className="structural-progress-presets"><span>เลือกสถานะเร็ว</span><div>{progressPresets.map((preset) => <button className={percent === preset.value ? "is-active" : ""} disabled={!canEdit || busy} key={preset.value} onClick={() => setPercent(preset.value)} type="button"><b>{preset.value}%</b><small>{preset.label}</small></button>)}</div></div>
    <label className="structural-exact-progress"><span>ปรับเปอร์เซ็นต์ละเอียด <strong>{Number(percent).toFixed(0)}%</strong></span><input disabled={!canEdit || busy} max="100" min="0" onChange={(event) => setPercent(event.target.value)} step="1" type="range" value={percent} /></label>
    <div className={`structural-evidence ${selectedFrame ? "is-ready" : ""}`}><span>หลักฐานแนบอัตโนมัติ</span><strong>{selectedFrame ? `ภาพ 360 เวลา ${(selectedFrame.timestamp_ms / 1000).toFixed(1)} วินาที` : "กรุณาเลือกภาพบนเส้นทาง"}</strong><small>หมุนและเลื่อนภาพ 360 ด้านซ้ายได้ตลอด ระบบจะบันทึกภาพที่กำลังเปิด ตำแหน่ง Capture เวลา และชื่อผู้ตรวจ</small></div>
    <label><span>หมายเหตุ (ถ้ามี)</span><textarea disabled={!canEdit || busy} maxLength={2500} onChange={(event) => setNote(event.target.value)} placeholder="สิ่งที่พบ ปัญหา หรือส่วนที่ยังไม่เสร็จ" rows={2} value={note} /></label>
    {message && <p className="structural-progress-message" role="status">{message}</p>}
    <button className="button button-primary structural-progress-save" disabled={!canEdit || busy || !activityId || !selectedFrame || !selectedActivityIds.length} type="submit">{busy ? "กำลังบันทึก..." : selectedActivityIds.length > 1 ? `บันทึกพร้อมกัน ${selectedActivityIds.length} งาน` : "บันทึกผลตรวจงานนี้"}</button>
    <p className="structural-progress-audit">ผลตรวจเป็นประวัติถาวร ไม่เขียนทับรายการเดิม</p>
  </form>;
}
