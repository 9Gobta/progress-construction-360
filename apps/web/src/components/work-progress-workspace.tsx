"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import type { CaptureDetail, Floor, WorkProgress } from "@/lib/types";

const pct = (value: string | null) =>
  value === null ? "ยังไม่ครบ" : `${Number(value).toFixed(1)}%`;

type Props = {
  projectId: string;
  captureId: string;
  floors: Floor[];
  floorId: string;
  progress: WorkProgress;
  detail: CaptureDetail;
  canEdit: boolean;
};

export function WorkProgressWorkspace({
  projectId,
  captureId,
  floors,
  floorId,
  progress,
  detail,
  canEdit,
}: Props) {
  const router = useRouter();
  const structuralItems = progress.items.filter(
    (item) => item.discipline === "STRUCTURAL",
  );
  const [values, setValues] = useState<Record<string, number>>(() =>
    Object.fromEntries(
      structuralItems.map((item) => [
        item.work_item_id,
        Number(item.progress_percent ?? 0),
      ]),
    ),
  );
  const [evidence, setEvidence] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      structuralItems.map((item) => [
        item.work_item_id,
        item.evidence_keyframe_id ?? "",
      ]),
    ),
  );
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const usableFrames = detail.keyframes.filter(
    (frame) => frame.quality_status === "USABLE",
  );

  async function saveProgress() {
    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch(
        `/api/projects/${projectId}/captures/${captureId}/work-progress`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            floor_id: floorId,
            entries: structuralItems.map((item) => ({
              work_item_id: item.work_item_id,
              progress_percent: values[item.work_item_id] ?? 0,
              evidence_keyframe_id: evidence[item.work_item_id] || null,
            })),
          }),
        },
      );
      const result = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(result?.detail ?? "บันทึกผลตรวจไม่สำเร็จ");
      }
      setMessage("บันทึกผลตรวจงานโครงสร้างแล้ว");
      router.refresh();
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "บันทึกผลตรวจไม่สำเร็จ",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="work-progress-shell">
      <section className="work-progress-toolbar panel">
        <div>
          <span>ชั้นที่ตรวจ</span>
          <select
            value={floorId}
            onChange={(event) =>
              router.push(
                `/projects/${projectId}/captures/${captureId}/progress?floorId=${event.target.value}`,
              )
            }
          >
            {floors.map((floor) => (
              <option key={floor.id} value={floor.id}>
                {floor.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <strong>ตรวจโดยผู้ใช้งาน</strong>
          <small>ผู้ตรวจแต่ละคนใช้บัญชีของตนเอง ระบบบันทึกชื่อและเวลา</small>
        </div>
      </section>

      <section className="work-progress-kpis">
        <div>
          <span>Progress งานโครงสร้าง</span>
          <strong>{pct(progress.human_progress_percent)}</strong>
          <small>
            ตรวจแล้ว {progress.labeled_count}/{structuralItems.length} งาน
          </small>
        </div>
        <div>
          <span>รายการในขอบเขต</span>
          <strong>{structuralItems.length}</strong>
          <small>งานโครงสร้างเท่านั้น</small>
        </div>
        <div>
          <span>ภาพหลักฐาน</span>
          <strong>{usableFrames.length}</strong>
          <small>ภาพ 360° ที่เลือกอ้างอิงได้</small>
        </div>
      </section>

      <section className="panel work-progress-list">
        <header>
          <div>
            <h2>ตรวจ Progress งานโครงสร้าง 0–100%</h2>
            <p>กรอกตามสิ่งที่เห็นจากภาพ 360° และเลือกภาพหลักฐานของรายการนั้น</p>
          </div>
        </header>
        <div className="work-table-head human-only">
          <span>รายการงาน</span>
          <span>Progress ที่ตรวจพบ</span>
          <span>ภาพหลักฐาน</span>
        </div>
        {structuralItems.map((item) => (
          <div className="work-progress-row human-only" key={item.work_item_id}>
            <div>
              <b>{item.code}</b>
              <strong>{item.name}</strong>
              <small>งานโครงสร้าง</small>
            </div>
            <label>
              <span>{values[item.work_item_id] ?? 0}%</span>
              <input
                disabled={!canEdit}
                min="0"
                max="100"
                step="5"
                type="range"
                value={values[item.work_item_id] ?? 0}
                onChange={(event) =>
                  setValues((current) => ({
                    ...current,
                    [item.work_item_id]: Number(event.target.value),
                  }))
                }
              />
            </label>
            <select
              disabled={!canEdit}
              value={evidence[item.work_item_id] ?? ""}
              onChange={(event) =>
                setEvidence((current) => ({
                  ...current,
                  [item.work_item_id]: event.target.value,
                }))
              }
            >
              <option value="">เลือกภาพหลักฐาน</option>
              {usableFrames.map((frame) => (
                <option key={frame.id} value={frame.id}>
                  {(frame.timestamp_ms / 1000).toFixed(1)} วินาที
                </option>
              ))}
            </select>
          </div>
        ))}
        {canEdit && (
          <footer>
            <button
              className="button button-primary"
              disabled={busy}
              onClick={saveProgress}
              type="button"
            >
              {busy ? "กำลังบันทึก…" : "บันทึกผลตรวจงานโครงสร้าง"}
            </button>
          </footer>
        )}
        {message && (
          <p className="notice" role="status">
            {message}
          </p>
        )}
      </section>
    </div>
  );
}
