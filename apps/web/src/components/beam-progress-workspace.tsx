"use client";

import Image from "next/image";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import type { BeamProgress, CaptureDetail } from "@/lib/types";

const TRIAL_SEGMENTS = [
  ["F1-B-1-2", "B1", "B2", 0.2000, 0.4071, 0.2891, 0.4071],
  ["F1-B-2-3", "B2", "B3", 0.2891, 0.4071, 0.3782, 0.4071],
  ["F1-B-3-4", "B3", "B4", 0.3782, 0.4071, 0.4673, 0.4071],
  ["F1-B-4-5", "B4", "B5", 0.4673, 0.4071, 0.5565, 0.4071],
  ["F1-B-5-6", "B5", "B6", 0.5565, 0.4071, 0.6468, 0.4071],
  ["F1-C-1-2", "C1", "C2", 0.2000, 0.4704, 0.2891, 0.4704],
  ["F1-C-2-3", "C2", "C3", 0.2891, 0.4704, 0.3782, 0.4704],
  ["F1-C-3-4", "C3", "C4", 0.3782, 0.4704, 0.4673, 0.4704],
  ["F1-C-4-5", "C4", "C5", 0.4673, 0.4704, 0.5565, 0.4704],
  ["F1-C-5-6", "C5", "C6", 0.5565, 0.4704, 0.6468, 0.4704],
] as const;

function progressColor(value: number) {
  if (value >= 100) return "#16855b";
  if (value > 0) return "#e89b2d";
  return "#aeb8b2";
}

export function BeamProgressWorkspace({
  projectId,
  captureId,
  floorId,
  progress,
  detail,
  canEdit,
  compact = false,
  activeEvidenceKeyframeId = null,
}: {
  projectId: string;
  captureId: string;
  floorId: string;
  progress: BeamProgress;
  detail: CaptureDetail;
  canEdit: boolean;
  compact?: boolean;
  activeEvidenceKeyframeId?: string | null;
}) {
  const router = useRouter();
  const [values, setValues] = useState<Record<string, number>>(() => Object.fromEntries(
    progress.items.map((item) => [item.beam_segment_id, Number(item.progress_percent ?? 0)]),
  ));
  const [evidence, setEvidence] = useState<Record<string, string>>(() => Object.fromEntries(
    progress.items.map((item) => [item.beam_segment_id, item.evidence_keyframe_id ?? ""]),
  ));
  const [selectedId, setSelectedId] = useState(progress.items[0]?.beam_segment_id ?? "");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const average = useMemo(() => {
    if (!progress.items.length) return 0;
    return progress.items.reduce((sum, item) => sum + (values[item.beam_segment_id] ?? 0), 0)
      / progress.items.length;
  }, [progress.items, values]);

  async function initializeSegments() {
    setBusy(true);
    setMessage(null);
    const response = await fetch(`/api/projects/${projectId}/floors/${floorId}/beam-segments`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sheet_name: "แปลนโครงสร้างชั้น 1 ST-03",
        segments: TRIAL_SEGMENTS.map((segment) => ({
          code: segment[0], beam_type: "B3", start_x: segment[3], start_y: segment[4],
          end_x: segment[5], end_y: segment[6], length_m: 3.75,
        })),
      }),
    });
    const body = await response.json().catch(() => ({}));
    setMessage(response.ok ? "สร้างคานทดลอง 10 ช่วงแล้ว กรุณาตรวจตำแหน่งก่อนกรอก" : body.detail || "สร้างรายการคานไม่สำเร็จ");
    if (response.ok) router.refresh();
    setBusy(false);
  }

  async function saveProgress() {
    setBusy(true);
    setMessage(null);
    const response = await fetch(`/api/projects/${projectId}/captures/${captureId}/beam-progress`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        floor_id: floorId,
        entries: progress.items.map((item) => ({
          beam_segment_id: item.beam_segment_id,
          progress_percent: values[item.beam_segment_id] ?? 0,
          evidence_keyframe_id: evidence[item.beam_segment_id] || null,
        })),
      }),
    });
    const body = await response.json().catch(() => ({}));
    setMessage(response.ok ? "บันทึกผลตรวจคานโดยผู้ใช้ครบแล้ว" : body.detail || "บันทึกไม่สำเร็จ");
    if (response.ok) router.refresh();
    setBusy(false);
  }

  if (!progress.items.length) {
    return <section className="panel beam-empty"><strong>ยังไม่มีรายการคานบนแปลน</strong><p>เริ่มจาก 10 ช่วงบนแนว Grid B และ C แล้วตรวจตำแหน่งก่อนบันทึกผลตรวจ</p>{canEdit && <button className="button button-primary" disabled={busy} onClick={initializeSegments} type="button">{busy ? "กำลังสร้าง..." : "สร้างคานทดลอง 10 ช่วง"}</button>}{message && <p className="notice">{message}</p>}</section>;
  }

  return <div className={`beam-progress-layout ${compact ? "is-compact" : ""}`}>
    <section className="panel beam-plan-review">
      <div className="panel-header"><div><h2>ตำแหน่งคานชั้น 1</h2><p>คลิกเส้นคานเพื่อกรอกค่าจริงจากภาพ 360 และผูกภาพหลักฐาน</p></div><div><span className="human-badge">ตรวจโดยผู้ใช้</span></div></div>
      <div className="beam-plan-canvas">
        <Image alt="แปลนโครงสร้างชั้น 1" fill priority sizes="60vw" src="/plans/floor-1-structural.png" />
        <svg preserveAspectRatio="none" viewBox="0 0 1000 1000">
          {progress.items.map((item) => <line
            className={selectedId === item.beam_segment_id ? "is-selected" : ""}
            key={item.beam_segment_id}
            onClick={() => setSelectedId(item.beam_segment_id)}
            stroke={progressColor(values[item.beam_segment_id] ?? 0)}
            x1={Number(item.start_x) * 1000} x2={Number(item.end_x) * 1000}
            y1={Number(item.start_y) * 1000} y2={Number(item.end_y) * 1000}
          />)}
        </svg>
      </div>
      <div className="beam-progress-summary"><strong>ผลตรวจโดยผู้ใช้ {average.toFixed(1)}%</strong><span>ตรวจแล้ว {progress.labeled_count}/{progress.segment_count} ช่วงคาน</span></div>
    </section>
    <section className="panel beam-label-list">
      <div className="panel-header"><div><h2>Progress คาน 0–100%</h2><p>ค่าที่บันทึกใหม่จะเก็บประวัติเดิมไว้</p></div></div>
      <div className="beam-label-scroll">{progress.items.map((item) => <div className={`beam-label-row ${selectedId === item.beam_segment_id ? "is-selected" : ""}`} key={item.beam_segment_id} onClick={() => setSelectedId(item.beam_segment_id)}>
        <div><strong>{item.code}</strong><span>{item.beam_type ?? "ไม่ระบุชนิด"} · {item.length_m ? `${Number(item.length_m)} ม.` : "ไม่ระบุความยาว"}</span></div>
        <label><span>{values[item.beam_segment_id] ?? 0}%</span><input disabled={!canEdit} max="100" min="0" onChange={(event) => setValues((current) => ({ ...current, [item.beam_segment_id]: Number(event.target.value) }))} step="5" type="range" value={values[item.beam_segment_id] ?? 0} /></label>
        <select aria-label={`ภาพหลักฐาน ${item.code}`} disabled={!canEdit} onChange={(event) => setEvidence((current) => ({ ...current, [item.beam_segment_id]: event.target.value }))} value={evidence[item.beam_segment_id] ?? ""}><option value="">ยังไม่เลือกภาพหลักฐาน</option>{detail.keyframes.filter((frame) => frame.pose?.floor_id === floorId).map((frame) => <option key={frame.id} value={frame.id}>{Math.floor(frame.timestamp_ms / 1000)} วินาที</option>)}</select>
        {compact && canEdit && selectedId === item.beam_segment_id && activeEvidenceKeyframeId && <button className="use-current-evidence" onClick={(event) => { event.stopPropagation(); setEvidence((current) => ({ ...current, [item.beam_segment_id]: activeEvidenceKeyframeId })); }} type="button">ใช้ภาพ 360 ที่กำลังดูเป็นหลักฐาน</button>}
      </div>)}</div>
      {canEdit && <button className="button button-primary beam-save" disabled={busy} onClick={saveProgress} type="button">{busy ? "กำลังบันทึก..." : "บันทึก Progress คานทั้งหมด"}</button>}
      {message && <p className="notice" role="status">{message}</p>}
    </section>
  </div>;
}
