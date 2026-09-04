"use client";

import { FormEvent, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import type { Activity, HumanProgressEntry, SchedulePreview } from "@/lib/types";

type Props = {
  projectId: string;
  role: "admin" | "sub_admin" | "reviewer" | "viewer" | null;
  activities: Activity[];
  progress: HumanProgressEntry[];
};

async function readResponse(response: Response) {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "เกิดข้อผิดพลาด กรุณาลองใหม่");
  return body;
}

function localDateTimeValue() {
  const now = new Date(Date.now() - new Date().getTimezoneOffset() * 60_000);
  return now.toISOString().slice(0, 16);
}

export function ScheduleWorkspace({ projectId, role, activities, progress }: Props) {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<SchedulePreview | null>(null);
  const [versionName, setVersionName] = useState("Baseline Version 1");
  const [busy, setBusy] = useState<"preview" | "import" | "progress" | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [activityId, setActivityId] = useState(activities.find((item) => !item.is_summary)?.id ?? "");
  const [percent, setPercent] = useState("0");
  const [observedAt, setObservedAt] = useState(localDateTimeValue);
  const [note, setNote] = useState("");

  const latestByActivity = useMemo(() => {
    const latest = new Map<string, HumanProgressEntry>();
    const currentIds = new Set(activities.map((item) => item.id));
    const currentIdByWbs = new Map(activities.map((item) => [item.wbs, item.id]));
    for (const item of progress) {
      const currentId = currentIds.has(item.activity_id)
        ? item.activity_id
        : item.activity_wbs ? currentIdByWbs.get(item.activity_wbs) : undefined;
      if (currentId && !latest.has(currentId)) latest.set(currentId, item);
    }
    return latest;
  }, [activities, progress]);

  async function previewFile(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setBusy("preview");
    setMessage(null);
    try {
      const formData = new FormData();
      formData.set("file", file);
      const response = await fetch(`/api/projects/${projectId}/schedules/preview`, {
        method: "POST",
        body: formData,
      });
      setPreview((await readResponse(response)) as SchedulePreview);
    } catch (error) {
      setPreview(null);
      setMessage(error instanceof Error ? error.message : "ไม่สามารถตรวจไฟล์ได้");
    } finally {
      setBusy(null);
    }
  }

  async function confirmImport() {
    if (!file || !preview) return;
    setBusy("import");
    setMessage(null);
    try {
      const formData = new FormData();
      formData.set("file", file);
      formData.set("name", versionName);
      formData.set("is_baseline", "true");
      const response = await fetch(`/api/projects/${projectId}/schedules/import`, {
        method: "POST",
        body: formData,
      });
      await readResponse(response);
      setPreview(null);
      setFile(null);
      setMessage("นำเข้าแผนสำเร็จ — Percent Complete จาก Excel ไม่ถูกนำมาใช้");
      router.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ไม่สามารถนำเข้าแผนได้");
    } finally {
      setBusy(null);
    }
  }

  async function saveProgress(event: FormEvent) {
    event.preventDefault();
    setBusy("progress");
    setMessage(null);
    try {
      const response = await fetch(`/api/projects/${projectId}/progress/manual`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          activity_id: activityId,
          observed_at: new Date(observedAt).toISOString(),
          progress_percent: Number(percent),
          note: note.trim() || null,
        }),
      });
      await readResponse(response);
      setNote("");
      setMessage("บันทึก Human Actual แล้ว และเก็บค่าก่อนหน้าไว้ในประวัติ");
      router.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ไม่สามารถบันทึกได้");
    } finally {
      setBusy(null);
    }
  }

  const canImport = role === "admin";
  const canEnterProgress = role === "admin" || role === "sub_admin" || role === "reviewer";

  return (
    <div className="schedule-stack">
      {message && <p className="notice" role="status">{message}</p>}

      <section className="panel schedule-panel">
        <div className="panel-header">
          <div><h2>นำเข้าแผนงาน</h2><p>ใช้ Name, WBS, Start และ Finish เท่านั้น</p></div>
          <span className="source-badge">PLANNED</span>
        </div>
        <form className="import-row" onSubmit={previewFile}>
          <label className="file-field">
            <span>ไฟล์ Excel (.xlsx)</span>
            <input accept=".xlsx" disabled={!canImport || busy !== null} onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              setPreview(null);
            }} required type="file" />
          </label>
          <button className="button button-secondary" disabled={!file || !canImport || busy !== null} type="submit">
            {busy === "preview" ? "กำลังตรวจ..." : "Preview"}
          </button>
        </form>
        {!canImport && <p className="panel-note">เฉพาะ Project Admin ที่นำเข้า Schedule ได้</p>}
        {preview && (
          <div className="preview-result">
            <div className="preview-summary">
              <strong>{preview.sheet_name}</strong><span>{preview.row_count} กิจกรรม</span>
            </div>
            {preview.warnings.map((warning) => <p className="warning" key={warning}>{warning}</p>)}
            <div className="table-scroll">
              <table className="data-table compact">
                <thead><tr><th>WBS</th><th>กิจกรรม</th><th>Start</th><th>Finish</th></tr></thead>
                <tbody>{preview.activities.slice(0, 8).map((item) => (
                  <tr key={`${item.source_row_no}-${item.wbs}`}><td>{item.wbs}</td><td>{item.name}</td><td>{new Date(item.planned_start).toLocaleDateString("th-TH")}</td><td>{new Date(item.planned_finish).toLocaleDateString("th-TH")}</td></tr>
                ))}</tbody>
              </table>
            </div>
            {preview.row_count > 8 && <p className="panel-note">แสดง 8 รายการแรกจากทั้งหมด {preview.row_count}</p>}
            <div className="confirm-row">
              <label className="field"><span>ชื่อ Schedule Version</span><input maxLength={200} onChange={(event) => setVersionName(event.target.value)} value={versionName} /></label>
              <button className="button button-primary" disabled={!versionName.trim() || busy !== null} onClick={confirmImport} type="button">{busy === "import" ? "กำลังนำเข้า..." : "ยืนยัน Import"}</button>
            </div>
          </div>
        )}
      </section>

      <section className="panel schedule-panel">
        <div className="panel-header">
          <div><h2>ความก้าวหน้าจริงจากคน</h2><p>กรอกบนเว็บพร้อมหลักฐาน โดยไม่แก้ค่าจาก Excel</p></div>
          <span className="human-badge">HUMAN ACTUAL</span>
        </div>
        {activities.length ? (
          <>
            <form className="progress-form" onSubmit={saveProgress}>
              <label className="field field-wide"><span>กิจกรรม</span><select disabled={!canEnterProgress} onChange={(event) => setActivityId(event.target.value)} value={activityId}>{activities.map((item) => <option key={item.id} value={item.id}>{item.wbs} — {item.name}</option>)}</select></label>
              <label className="field"><span>Progress (%)</span><input disabled={!canEnterProgress} max="100" min="0" onChange={(event) => setPercent(event.target.value)} required step="0.1" type="number" value={percent} /></label>
              <label className="field"><span>วันที่สังเกต</span><input disabled={!canEnterProgress} onChange={(event) => setObservedAt(event.target.value)} required type="datetime-local" value={observedAt} /></label>
              <label className="field field-wide"><span>หมายเหตุ (ไม่บังคับ)</span><input disabled={!canEnterProgress} maxLength={3000} onChange={(event) => setNote(event.target.value)} value={note} /></label>
              <button className="button button-primary" disabled={!activityId || !canEnterProgress || busy !== null} type="submit">{busy === "progress" ? "กำลังบันทึก..." : "บันทึก Human Actual"}</button>
            </form>
            <div className="table-scroll">
              <table className="data-table">
                <thead><tr><th>WBS / กิจกรรม</th><th>ช่วงแผน</th><th>Human Actual ล่าสุด</th><th>วันที่สังเกต</th><th>ประวัติ</th></tr></thead>
                <tbody>{activities.map((item) => {
                  const latest = latestByActivity.get(item.id);
                  const historyCount = progress.filter((entry) => (
                    entry.activity_id === item.id || entry.activity_wbs === item.wbs
                  )).length;
                  return <tr key={item.id}><td><strong>{item.wbs}</strong><span>{item.name}</span></td><td>{new Date(item.planned_start).toLocaleDateString("th-TH")} – {new Date(item.planned_finish).toLocaleDateString("th-TH")}</td><td>{latest ? `${Number(latest.progress_percent)}%` : "ยังไม่กรอก"}</td><td>{latest ? new Date(latest.observed_at).toLocaleString("th-TH") : "—"}</td><td>{historyCount} รายการ</td></tr>;
                })}</tbody>
              </table>
            </div>
          </>
        ) : <div className="empty-state"><strong>ยังไม่มีกิจกรรม</strong><p>Preview และ Import Excel ก่อน จึงจะกรอก Human Actual ได้</p></div>}
      </section>
    </div>
  );
}
