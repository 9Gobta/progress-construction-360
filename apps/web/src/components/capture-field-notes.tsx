"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { FieldNoteDetail } from "@/components/field-notes-workspace";
import type { CaptureDetail, FieldNote, Floor, ProjectMember } from "@/lib/types";
import type { PanoramaViewState } from "@/components/panorama-viewer";

export function CaptureFieldNotes({ projectId, detail, floors, initialNotes, members, selectedKeyframeId, view, canEdit }: {
  projectId: string;
  detail: CaptureDetail;
  floors: Floor[];
  initialNotes: FieldNote[];
  members: ProjectMember[];
  selectedKeyframeId: string | null;
  view: PanoramaViewState;
  canEdit: boolean;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [notes, setNotes] = useState(initialNotes);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState("");
  const [status, setStatus] = useState("OPEN");
  const [dueDate, setDueDate] = useState("");
  const [assigneeId, setAssigneeId] = useState("");
  const [message, setMessage] = useState("");
  const selectedFrame = detail.keyframes.find((frame) => frame.id === selectedKeyframeId)
    ?? detail.keyframes.find((frame) => frame.pose) ?? detail.keyframes[0];
  const activeFloorId = selectedFrame?.pose?.floor_id ?? detail.capture.start_floor_id;
  const activeFloor = floors.find((floor) => floor.id === activeFloorId);
  const selected = notes.find((note) => note.id === selectedId) ?? null;

  async function create() {
    if (!selectedFrame || !title.trim()) return;
    setCreating(true); setMessage("");
    const response = await fetch(`/api/projects/${projectId}/field-notes`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        capture_id: detail.capture.id, floor_id: activeFloorId, keyframe_id: selectedFrame.id,
        title, description: description || null, status, due_date: dueDate || null,
        tags: tags.split(",").map((item) => item.trim()).filter(Boolean),
        assignee_id: assigneeId || null,
        plan_x: selectedFrame.pose ? Number(selectedFrame.pose.x) : null,
        plan_y: selectedFrame.pose ? Number(selectedFrame.pose.y) : null,
        panorama_longitude: view.longitude, panorama_latitude: view.latitude, panorama_fov: view.fov,
      }),
    });
    const body = await response.json(); setCreating(false);
    if (!response.ok) return setMessage(body.detail ?? "สร้างบันทึกไม่สำเร็จ");
    setNotes((current) => [body, ...current]); setSelectedId(body.id);
    setTitle(""); setDescription(""); setTags(""); router.refresh();
  }

  function replace(next: FieldNote) {
    setNotes((current) => current.map((note) => note.id === next.id ? next : note));
    router.refresh();
  }

  return <div className="capture-field-notes">
    <button className="field-note-launcher" onClick={() => setOpen(true)} type="button"><span>＋</span> ประเด็นหน้างาน <b>{notes.length}</b></button>
    {open && <div className="field-note-drawer" role="dialog" aria-label="ประเด็นหน้างาน">
      <header><div><strong>ประเด็นหน้างาน</strong><small>{activeFloor?.name ?? "ไม่ระบุชั้น"} · ภาพวินาที {Math.round((selectedFrame?.timestamp_ms ?? 0) / 1000)}</small></div><button aria-label="ปิด" onClick={() => { setOpen(false); setSelectedId(null); }} type="button">×</button></header>
      {selected ? <><button className="field-note-back" onClick={() => setSelectedId(null)} type="button">← กลับไปรายการ</button><FieldNoteDetail canEdit={canEdit} members={members} note={selected} onChange={replace} projectId={projectId} /></> : <>
        {canEdit && <details className="field-note-create" open={!notes.length}><summary>＋ สร้างประเด็นจากภาพปัจจุบัน</summary><div>
          <input maxLength={180} onChange={(event) => setTitle(event.target.value)} placeholder="หัวข้อที่ต้องติดตาม" value={title} />
          <textarea maxLength={5000} onChange={(event) => setDescription(event.target.value)} placeholder="รายละเอียด จุดที่พบ หรือสิ่งที่ต้องแก้ไข" value={description} />
          <div><select onChange={(event) => setStatus(event.target.value)} value={status}><option value="OPEN">เปิดอยู่</option><option value="P1">ด่วนมาก P1</option><option value="P2">เร่งด่วน P2</option><option value="P3">ติดตาม P3</option></select><input onChange={(event) => setDueDate(event.target.value)} type="date" value={dueDate} /></div>
          <select onChange={(event) => setAssigneeId(event.target.value)} value={assigneeId}><option value="">ยังไม่มอบหมาย</option>{members.map((member) => <option key={member.user_id} value={member.user_id}>{member.display_name}</option>)}</select>
          <input onChange={(event) => setTags(event.target.value)} placeholder="แท็ก คั่นด้วยจุลภาค เช่น โครงสร้าง, ค้ำยัน" value={tags} />
          <button disabled={creating || !title.trim() || !selectedFrame} onClick={() => void create()} type="button">{creating ? "กำลังบันทึก…" : "บันทึกพร้อมหลักฐาน 360"}</button>{message && <small role="status">{message}</small>}
        </div></details>}
        <div className="capture-field-note-list">{notes.map((note) => <button key={note.id} onClick={() => setSelectedId(note.id)} type="button"><span><b>{note.title}</b><small>{note.assignee_name || "ยังไม่มอบหมาย"}</small></span><i className={`status-${note.status.toLowerCase()}`}>{note.status}</i></button>)}{!notes.length && <p>ยังไม่มีประเด็นหน้างานใน Capture นี้</p>}</div>
      </>}
    </div>}
  </div>;
}
